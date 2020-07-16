#!/usr/bin/env python
# -*- coding: utf-8 -*-
""" pyfirebasestockscli

  Copyright 2019 Slash Gordon

  Use of this source code is governed by an MIT-style license that
  can be found in the LICENSE file.
"""
import os
import unittest
import json

from _pytest.monkeypatch import MonkeyPatch, derive_importpath
from firebase_admin import firestore

import sys

sys.path.insert(0, 'src')

import pyfirebasestockscli


STOCK_ATTR = [
    'country',
    'date',
    'id',
    'indices',
    'last_price_eur',
    'last_price_usd',
    'name',
    'tags',
    'symbols_eur',
    'symbols_usd',
]


class MonkeyEnv(object):
    def __init__(self, env_dict):
        self.env_dict = env_dict

    def __call__(self, f):
        def wrapped_f(*args, **kwargs):
            for key, value in self.env_dict.items():
                args[0].monkeypatch.setenv(key, value)
            try:
                f(*args, **kwargs)
            finally:
                for key, _ in self.env_dict.items():
                    args[0].monkeypatch.delenv(key)

        return wrapped_f


monkey_env = MonkeyEnv


class MonkeyFunc(object):
    def __init__(self, target=None, func=None):
        self.target = target
        _name, _target = derive_importpath(self.target, raising=False)
        self.old = getattr(_target, _name)
        self.func = func

    def __call__(self, f):
        def wrapped_f(*args, **kwargs):
            args[0].monkeypatch.setattr(self.target, self.func)
            try:
                f(*args, **kwargs)
            finally:
                # todo: find out why delattr is not working
                args[0].monkeypatch.setattr(self.target, self.old)

        return wrapped_f


monkey_func = MonkeyFunc

# create test environment
root_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)), '..')
with open(os.path.join(root_dir, 'database.url'), 'r') as f:
    db_url = f.read()
cred = os.path.join(root_dir, 'test.json')
data_root = os.path.join(root_dir, 'test', 'data')
test_env = {'DATABASE_URL': db_url, 'CRED_JSON': cred, 'DATA_ROOT': data_root}


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.monkeypatch = MonkeyPatch()

    @monkey_env(test_env)
    def test_0_cli(self):
        self.assertEqual(pyfirebasestockscli.app([]), 0)

    def test_1_cli_err(self):
        self.assertRaises(KeyError, pyfirebasestockscli.app, [])

    @monkey_env(test_env)
    @monkey_func(
        target='pytickersymbols.PyTickerSymbols.get_all_indices',
        func=lambda x: ['DAX'],
    )
    def test_2_create_fastmode(self):
        self.assertEqual(pyfirebasestockscli.app(['-c']), 0)
        store = firestore.client()
        tag_docs = list(
            map(lambda x: x.to_dict(), store.collection('tags').stream())
        )
        self.assertEqual(len(tag_docs), 3)
        # check for all keys
        self.assertTrue(
            all(map(lambda x: 'tags' in x and 'type' in x, tag_docs))
        )

        # check for all types
        self.assertTrue(
            all(
                map(
                    lambda x: any(map(lambda y: x == y['type'], tag_docs)),
                    ['indices', 'countries', 'industries'],
                )
            )
        )
        indices = next(filter(lambda x: x['type'] == 'indices', tag_docs))
        self.assertIsNotNone(indices)
        self.assertEqual(len(indices['tags']), 1)
        self.assertEqual(indices['tags'][0], 'DAX')
        stocks_doc = list(
            map(lambda x: x.to_dict(), store.collection('stocks').stream())
        )
        self.assertEqual(len(stocks_doc), 30)
        # check all stock attributes
        self.assertTrue(
            all(
                map(
                    lambda x: all(map(lambda y: y in x, STOCK_ATTR)),
                    stocks_doc,
                )
            )
        )
        # check if all prices null
        self.assertTrue(
            all(
                map(
                    lambda y: y['last_price_eur'] is None
                    and y['last_price_usd'] is None,
                    stocks_doc,
                )
            )
        )

    @monkey_env(
        {
            **test_env,
            **{'STOCK2FIREBASE_MAX_PROCESSES': '1', 'STOCK2FIREBASE_ID': '0'},
        }
    )
    @monkey_func(
        target='pytickersymbols.PyTickerSymbols.get_all_indices',
        func=lambda x: ['DAX'],
    )
    def test_3_update_price(self):
        self.assertEqual(pyfirebasestockscli.app(['-p']), 0)
        store = firestore.client()
        stocks_doc = list(
            map(lambda x: x.to_dict(), store.collection('stocks').stream())
        )
        for stock in stocks_doc:
            is_ok = all(
                [
                    price_sym is not None
                    for key in ['last_price_usd', 'last_price_eur']
                    for price_sym in stock[key]
                ]
            )
            self.assertTrue(is_ok, f'Stock has incorrect prices: {stock}')

    @monkey_env(
        {
            **test_env,
            **{'STOCK2FIREBASE_MAX_PROCESSES': '1', 'STOCK2FIREBASE_ID': '0'},
        }
    )
    @monkey_func(
        target='pytickersymbols.PyTickerSymbols.get_all_indices',
        func=lambda x: ['DAX', 'OMX Helsinki 15'],
    )
    def test_4_update_missing_stocks(self):
        self.assertEqual(pyfirebasestockscli.app(['-p']), 0)
        store = firestore.client()
        stocks_doc = list(
            map(lambda x: x.to_dict(), store.collection('stocks').stream())
        )
        for stock in stocks_doc:
            is_ok = all(
                [
                    price_sym is not None
                    for key in ['last_price_usd', 'last_price_eur']
                    for price_sym in stock[key]
                ]
            )
            self.assertTrue(is_ok, f'Stock has incorrect prices: {stock}')

    @monkey_env(test_env)
    def test_5_tag_export(self):
        self.assertEqual(pyfirebasestockscli.app(['-t']), 0)
        json_file = os.path.join(root_dir, 'tags.json')
        self.assertTrue(os.path.exists(json_file))
        with open(json_file) as json_file:
            data = json.load(json_file)
            # check for all types
            self.assertTrue(
                all(
                    map(
                        lambda x: x in data,
                        ['indices', 'countries', 'industries'],
                    )
                )
            )
            data['indices'].sort()
            self.assertEqual(len(data['indices']), 2)
            self.assertEqual(data['indices'][0], 'DAX')
            self.assertEqual(data['indices'][1], 'OMX Helsinki 15')

    @monkey_env(test_env)
    def test_6_strategies(self):
        self.assertEqual(pyfirebasestockscli.app(['-s']), 0)
        store = firestore.client()
        strategy_docs = list(
            map(lambda x: x.to_dict(), store.collection('strategies').stream())
        )
        self.assertEqual(len(strategy_docs), 1)
        self.assertEqual(strategy_docs[0]['name'], 'test strategy')

    @monkey_env(
        {
            **test_env,
            **{'STOCK2FIREBASE_MAX_PROCESSES': '1', 'STOCK2FIREBASE_ID': '0'},
        }
    )
    @monkey_func(
        target='pyfirebasestockscli.create_job',
        func=lambda x, y: (['ADS.F', 'ADDDF'], ['ADS.F'], ['^GDAXI']),
    )
    def test_7_updates(self):
        self.assertEqual(pyfirebasestockscli.app(['-u']), 0)
        store = firestore.client()
        stocks_docs = list(
            map(lambda x: x.to_dict(), store.collection('stocks').stream())
        )

        filter_names = [
            'StockIsHot2Month',
            'StockIsHot3Month',
            'StockIsHot6Month',
            'SecureHotH2Month',
            'SecureHotH3Month',
            'SecureHotH6Month',
            'SecureHot2Month',
            'SecureHot3Month',
            'SecureHot6Month',
            'AdxP14',
            'AdxP5',
            'RsiP14',
            'RsiP5',
            'DividendKings',
            # 'LevermannScore',
            # 'PiotroskiScore',
            #  'PriceTargetScore',
        ]
        # check if custom filter exists
        for stock in filter(
            lambda x: 'name' in x and x['name'] == 'adidas AG', stocks_docs
        ):
            is_ok = all(
                map(
                    lambda x: f'{x}_status' in stock and f'{x}_value' in stock,
                    filter_names,
                )
            )
            self.assertTrue(is_ok, f'Stock has not all filter: {stock}')


if __name__ == '__main__':
    unittest.main()
