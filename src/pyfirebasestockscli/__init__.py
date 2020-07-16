#!/usr/bin/env python
# -*- coding: utf-8 -*-
""" pyfirebasestockscli

  Copyright 2019 Slash Gordon

  Use of this source code is governed by an MIT-style license that
  can be found in the LICENSE file.
"""
import argparse
import datetime
import itertools
import json
import logging
import math
import os
import sys

import firebase_admin
from firebase_admin import credentials, firestore
from pony.orm import db_session, desc, select
from pystockdb.db.schema.stocks import Price, PriceItem, Stock, Tag, Type
from pystockdb.tools.create import CreateAndFillDataBase
from pystockdb.tools.update import UpdateDataBaseStocks
from pystockfilter.base.base_helper import BaseHelper
from pystockfilter.tool.build_filters import BuildFilters
from pystockfilter.tool.build_internal_filters import BuildInternalFilters
from pytickersymbols import PyTickerSymbols

from pyfirebasestockscli.dividend_kings import DividendKings


def create_job(indices, stock_data):
    my_id = int(os.environ['STOCK2FIREBASE_ID'])
    max_processes = int(os.environ['STOCK2FIREBASE_MAX_PROCESSES'])
    index_symbols = []
    stocks = []
    for index in indices:
        stocks = stocks + stock_data.get_yahoo_ticker_symbols_by_index(index)
        # we also need index data for levermann filter
        index_symbols.append(stock_data.index_to_yahoo_symbol(index))

    # removes duplicate values
    stocks.sort()
    stocks_clean = list(stocks for stocks, _ in itertools.groupby(stocks))

    # create chunks

    chunk_size = math.ceil((len(stocks_clean) / max_processes))
    chunks = [
        stocks_clean[x : x + chunk_size]
        for x in range(0, len(stocks_clean), chunk_size)
    ]
    stocks = chunks[my_id]

    fra_symbols = [
        sym for syms in stocks for sym in syms if sym.endswith('.F')
    ]
    all_symbols = [sym for syms in stocks for sym in syms]
    return all_symbols, fra_symbols, index_symbols


class BatchWriter(object):
    def __init__(self, max_writes, delete=False):
        self.delete = delete
        self.max_writes = max_writes

    def __call__(self, f):
        def wrapped_f(*args, **kwargs):
            reference_name = args[1]
            items = args[2]
            store = firestore.client()
            batch = store.batch()
            ref = store.collection(reference_name)
            if self.delete:
                self.delete_collection(ref, 50)
            chunks = [
                items[x : x + self.max_writes]
                for x in range(0, len(items), self.max_writes)
            ]
            args = list(args)
            for chunk in chunks:
                args[2] = chunk
                writes = f(*args, **kwargs)
                for write in writes:
                    batch.set(ref.document(), write)
                batch.commit()

        return wrapped_f

    def delete_collection(self, coll_ref, batch_size):
        docs = coll_ref.limit(batch_size).stream()
        deleted = 0

        for doc in docs:
            doc.reference.delete()
            deleted = deleted + 1

        if deleted >= batch_size:
            return self.delete_collection(coll_ref, batch_size)


batch_writer = BatchWriter


class BatchUpdate(object):
    def __init__(self, max_updates, delete=False):
        self.max_updates = max_updates

    def __call__(self, f):
        def wrapped_f(*args, **kwargs):
            items = args[2]
            store = firestore.client()
            batch = store.batch()
            chunks = [
                items[x : x + self.max_updates]
                for x in range(0, len(items), self.max_updates)
            ]
            args = list(args)
            for chunk in chunks:
                args[2] = chunk
                updates = f(*args, **kwargs)
                for my_doc, update in updates:
                    batch.set(my_doc.reference, update, merge=True)
                batch.commit()

        return wrapped_f


batch_updater = BatchUpdate


class FirbaseBase:
    def __init__(self, *args, **kwargs):
        options = {'databaseURL': kwargs['databaseURL']}
        cred_json_path = kwargs['cred_json']
        cred = credentials.Certificate(cred_json_path)
        try:
            firebase_admin.get_app()
        except ValueError:
            firebase_admin.initialize_app(cred, options=options)
        self.logger = kwargs['logger']


class CreateTagFile(FirbaseBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.output_file = kwargs['output_file']

    def build(self):
        store = firestore.client()
        tag_docs = store.collection('tags').stream()
        stock_docs = store.collection('stocks').stream()
        data = {'stocks': []}
        for stock_dock in stock_docs:
            stock_dock = stock_dock.to_dict()
            data['stocks'].append(
                {
                    'name': stock_dock['name'],
                    'symbols_eur': stock_dock['symbols_eur'],
                    'symbols_usd': stock_dock['symbols_usd'],
                    'tags': stock_dock['tags'],
                    'indices': stock_dock['indices'],
                    'country': stock_dock['country'],
                }
            )
        for tag_doc in tag_docs:
            tag_dict = tag_doc.to_dict()
            my_tags = set([tag for tag in tag_dict['tags']])
            if tag_dict['type'] == 'industries':
                pass
            data[tag_dict['type']] = list(my_tags)
        with open(self.output_file, 'w') as outfile:
            json.dump(data, outfile)


class AddStrategiesFirebaseDB(FirbaseBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.data_root = kwargs['data_root']

    def build(self):
        json_files = [
            os.path.join(self.data_root, pos_json)
            for pos_json in os.listdir(self.data_root)
            if pos_json.endswith('.json')
        ]
        self.__write_strategies('strategies', json_files)

    @batch_writer(400, delete=True)
    def __write_strategies(self, ref, items):
        for item in items:
            with open(item, 'r') as f:
                yield json.load(f)


class FindMissingStocks(FirbaseBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @staticmethod
    def _is_stock_missing(stock_db, stock_docs):
        for doc_dict, _ in stock_docs:
            if stock_db.name == doc_dict['name']:
                return False
        return True

    @db_session
    def build(self, symbols):
        store = firestore.client()
        stock_docs = store.collection('stocks').stream()
        stock_docs = [(doc.to_dict(), doc) for doc in stock_docs]
        stocks = select(
            p.stock
            for p in PriceItem
            for sym in p.symbols
            if sym.name in symbols
        )
        missing_stocks = list(
            map(
                lambda s: s.name,
                filter(
                    lambda x: self._is_stock_missing(x, stock_docs), stocks
                ),
            )
        )
        return missing_stocks


class SyncFirebaseDB(FirbaseBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @db_session
    def build(self, symbols):
        store = firestore.client()
        stock_docs = store.collection('stocks').stream()
        stock_docs = [(doc.to_dict(), doc) for doc in stock_docs]
        stocks = select(
            p.stock
            for p in PriceItem
            for sym in p.symbols
            if sym.name in symbols
        )
        # add missing stocks
        self.__update(stock_docs, stocks)

    @batch_updater(400)
    def __update(self, docs, stocks):
        for stock_item in stocks:
            # find coresbondanding document
            my_doc = None
            for doc_dict, doc in docs:
                if stock_item.name == doc_dict['name']:
                    my_doc = doc
                    break

            if not my_doc:
                raise RuntimeError(
                    f"Stock {stock_item.name} doesn't exist in firestore."
                )

            signals = []
            for signal_item in stock_item.price_item.signals:
                signal = {
                    'value': signal_item.result.value,
                    'status': signal_item.result.status,
                    'name': [tag.name for tag in signal_item.item.tags][0],
                }

                def is_in(signals, signal):
                    for si in signals:
                        if si['name'] == signal['name']:
                            return True
                    return False

                if not is_in(signals, signal):
                    signals.append(signal)

            stock = {
                'date': datetime.datetime.now().strftime('%m/%d/%Y'),
                'last_price_usd': None,
                'last_price_eur': None,
            }
            # add signals to document in a flat way to simplify queries
            for signal_item in signals:
                stock['{}_value'.format(signal_item['name'])] = signal_item[
                    'value'
                ]
                stock['{}_status'.format(signal_item['name'])] = signal_item[
                    'status'
                ]

            my_doc_dict = my_doc.to_dict()

            for price_key in (
                ('last_price_eur', 'symbols_eur'),
                ('last_price_usd', 'symbols_usd'),
            ):
                stock[price_key[0]] = {}
                # get prices for each symbol
                for usd_symbol in my_doc_dict[price_key[1]]:
                    stock[price_key[0]][usd_symbol] = (
                        Price.select(lambda p: p.symbol.name == usd_symbol)
                        .order_by(lambda p: desc(p.date))
                        .first()
                    )
                # set latest price for each symbol
                for key, value in stock[price_key[0]].items():
                    if value is None:
                        self.logger.warning(
                            f'Prices are not correct for {key}'
                            f'({stock_item.name}).'
                        )
                    else:
                        stock[price_key[0]][key] = stock[price_key[0]][
                            key
                        ].close
            yield my_doc, stock


class CreateFirebaseDB(FirbaseBase):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stock_data = kwargs['stock_data']
        self.stock_names_missing = kwargs.get('stocks_missing', None)

    @db_session
    def build(self):
        stocks = list(select(i for i in Stock))
        if self.stock_names_missing is not None:
            stocks = list(
                filter(lambda x: x.name in self.stock_names_missing, stocks)
            )

        self.__write('stocks', stocks)
        tags = [
            {
                'type': 'countries',
                'tags': list(self.stock_data.get_all_countries()),
            },
            {
                'type': 'industries',
                'tags': self.stock_data.get_all_industries(),
            },
            {'type': 'indices', 'tags': self.stock_data.get_all_indices()},
        ]
        self.__write_tags('tags', tags)

    @batch_writer(400, delete=True)
    def __write_tags(self, ref, items):
        for item in items:
            yield item

    @batch_writer(400, delete=True)
    def __write(self, ref, items):
        for idx, stock_item in enumerate(items):
            stock = {
                'id': idx,
                'name': stock_item.name,
                'date': datetime.datetime.now().strftime('%m/%d/%Y'),
                'symbols_usd': [
                    sym.name
                    for sym in stock_item.price_item.symbols
                    if Tag.YAO in sym.item.tags.name
                    and Tag.USD in sym.item.tags.name
                ],
                'symbols_eur': [
                    sym.name
                    for sym in stock_item.price_item.symbols
                    if Tag.YAO in sym.item.tags.name
                    and Tag.EUR in sym.item.tags.name
                ],
                'country': [
                    tag.name
                    for tag in stock_item.price_item.item.tags
                    if tag.type.name == Type.REG
                ][0],
                'tags': [
                    tag.name
                    for tag in stock_item.price_item.item.tags
                    if tag.type.name == Type.IND
                ],
                'indices': [index.name for index in stock_item.indexs],
                'last_price_usd': None,
                'last_price_eur': None,
            }
            yield stock

class CreateFirebaseDBWithoutWipe(FirbaseBase):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stock_data = kwargs['stock_data']
        self.stock_names_missing = kwargs.get('stocks_missing', None)

    @db_session
    def build(self):
        stocks = list(select(i for i in Stock))
        if self.stock_names_missing is not None:
            stocks = list(
                filter(lambda x: x.name in self.stock_names_missing, stocks)
            )

        self.__write('stocks', stocks)
        tags = [
            {
                'type': 'countries',
                'tags': list(self.stock_data.get_all_countries()),
            },
            {
                'type': 'industries',
                'tags': self.stock_data.get_all_industries(),
            },
            {'type': 'indices', 'tags': self.stock_data.get_all_indices()},
        ]
        self.__write_tags('tags', tags)

    @batch_writer(400, delete=True)
    def __write_tags(self, ref, items):
        for item in items:
            yield item

    @batch_writer(400, delete=False)
    def __write(self, ref, items):
        for idx, stock_item in enumerate(items):
            stock = {
                'id': idx,
                'name': stock_item.name,
                'date': datetime.datetime.now().strftime('%m/%d/%Y'),
                'symbols_usd': [
                    sym.name
                    for sym in stock_item.price_item.symbols
                    if Tag.YAO in sym.item.tags.name
                    and Tag.USD in sym.item.tags.name
                ],
                'symbols_eur': [
                    sym.name
                    for sym in stock_item.price_item.symbols
                    if Tag.YAO in sym.item.tags.name
                    and Tag.EUR in sym.item.tags.name
                ],
                'country': [
                    tag.name
                    for tag in stock_item.price_item.item.tags
                    if tag.type.name == Type.REG
                ][0],
                'tags': [
                    tag.name
                    for tag in stock_item.price_item.item.tags
                    if tag.type.name == Type.IND
                ],
                'indices': [index.name for index in stock_item.indexs],
                'last_price_usd': None,
                'last_price_eur': None,
            }
            yield stock

def app(args=sys.argv[1:]):
    '''
    Main entry point for application
    :return:
    '''
    parser = argparse.ArgumentParser(description='Firesbase stock db creator.')

    parser.add_argument(
        '-c',
        '--create',
        action='store_true',
        help='Create database and delete existing.',
        default=False,
    )
    parser.add_argument(
        '-u',
        '--update',
        action='store_true',
        help='Update prices and filter.',
        default=False,
    )
    parser.add_argument(
        '-p',
        '--updateprices',
        action='store_true',
        help='Update prices.',
        default=False,
    )
    parser.add_argument(
        '-s',
        '--strategies',
        action='store_true',
        help='Create all strategies.',
        default=False,
    )
    parser.add_argument(
        '-t',
        '--tags',
        action='store_true',
        help='Create json tag file.',
        default=False,
    )

    args = parser.parse_args(args)

    logger = BaseHelper.setup_logger('firebase')
    logger.setLevel(logging.WARNING)

    root_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(root_dir, 'full.sqlite')

    # get all possible indices
    stock_data = PyTickerSymbols()
    indices = stock_data.get_all_indices()

    config_build = {
        'max_history': 5,
        'indices': indices,
        'currencies': ['EUR', 'USD'],
        'prices': False,  # create db in fast mode
        'db_args': {
            'provider': 'sqlite',
            'filename': db_path,
            'create_db': True,
        },
    }

    firbase_config = {
        'databaseURL': os.environ['DATABASE_URL'],
        'cred_json': os.environ['CRED_JSON'],
        'data_root': os.environ['DATA_ROOT'],
        'stock_data': stock_data,
        'logger': logger,
    }

    if args.tags:
        logger.info('Create tag file')
        firbase_config['output_file'] = 'tags.json'
        tags = CreateTagFile(**firbase_config)
        tags.build()

    if args.strategies:
        logger.info('Create strategies')
        strategies = AddStrategiesFirebaseDB(**firbase_config)
        strategies.build()

    if args.create:
        logger.info('Create database')
        create = CreateAndFillDataBase(config_build, logger)
        create.build()
        logger.info('Delete old data and add new')
        create_fb = CreateFirebaseDB(**firbase_config)
        create_fb.build()

    if args.update or args.updateprices:
        create = CreateAndFillDataBase(config_build, logger)
        create.build()
        all_symbols, fra_symbols, index_symbols = create_job(
            indices, stock_data
        )
        logger.info('Update database prices')
        config_update_prices = {
            'symbols': index_symbols + all_symbols,
            'prices': True,
            'fundamentals': False,
            'db_args': {'provider': 'sqlite', 'filename': db_path},
        }
        update = UpdateDataBaseStocks(config_update_prices, logger)
        update.build()

    if args.update:
        logger.info('Update database fundamentals')
        config_update_fundamentals = {
            'symbols': fra_symbols,
            'prices': False,
            'fundamentals': True,
            'db_args': {'provider': 'sqlite', 'filename': db_path},
        }
        update = UpdateDataBaseStocks(config_update_fundamentals, logger)
        update.build()

        arguments_div = {
            'name': 'DividendKings',
            'bars': False,
            'index_bars': False,
            'args': {
                'threshold_buy': 3,
                'threshold_sell': 0.2,
                'intervals': None,
                'max_div_yield': 9,
                'lookback': 2,
            },
        }

        config_filter = {'symbols': fra_symbols}

        config_custom_filter = {
            'symbols': config_filter['symbols'],
            'filters': [DividendKings(arguments_div, logger)],
        }

        logger.info('Build Filters')
        builder = BuildInternalFilters(config_filter, logger)
        builder.build()
        logger.info('Create custom Filters')
        custom = BuildFilters(config_custom_filter, logger)
        custom.build()

    if args.update or args.updateprices:
        logger.info('Find missing stocks')
        find_missing = FindMissingStocks(**firbase_config)
        missing_stocks = find_missing.build(fra_symbols)
        if missing_stocks:
            logger.info('Add missing stocks')
            add_missing = firbase_config
            add_missing['delete_existing'] = False
            add_missing['stocks_missing'] = missing_stocks
            create_fb = CreateFirebaseDBWithoutWipe(**add_missing)
            create_fb.build()
        logger.info('Sync with firestore')
        sync = SyncFirebaseDB(**firbase_config)
        sync.build(fra_symbols)
    return 0
