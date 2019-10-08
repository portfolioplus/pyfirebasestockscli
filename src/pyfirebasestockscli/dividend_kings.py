#!/usr/bin/env python
# -*- coding: utf-8 -*-
""" pyfirebasestockscli

  Copyright 2019 Slash Gordon

  Use of this source code is governed by an MIT-style license that
  can be found in the LICENSE file.
"""
import logging
import math
from datetime import datetime

import numpy as np
import tulipy as ti
import yfinance as yf
from dateutil.relativedelta import relativedelta
from pony.orm import db_session, select
from pystockdb.db.schema.stocks import Price, Tag
from pystockfilter.filter.base_filter import BaseFilter


class DividendKings(BaseFilter):
    """
    Calculates median of last dividends
    """

    NAME = 'DividendKings'

    def __init__(self, arguments: dict, logger: logging.Logger):
        self.buy = arguments['args']['threshold_buy']
        self.sell = arguments['args']['threshold_sell']
        self.lookback = arguments['args']['lookback']
        self.max_yield = arguments['args']['max_div_yield']
        super(DividendKings, self).__init__(arguments, logger)

    @db_session
    def analyse(self):
        symbol = select(sym.name for sym in self.stock.price_item.symbols
                        if Tag.YAO in sym.item.tags.name).first()
        try:
            yao_item = yf.Ticker(symbol)
            data = yao_item.dividends
        except ValueError:
            raise RuntimeError("Couldn't load dividends for {}".format(symbol))

        dates = data.index.array
        drop = []
        # let us calculate the dividend yield
        for my_date in dates:
            price = Price.select(
                    lambda p: p.symbol.name == symbol
                    and p.date.date() == my_date.date()
                ).first()
            if price:
                div_yield = (data[my_date] / price.close) * 100
                if div_yield > self.max_yield:
                    drop.append(my_date)
                    self.logger.error(
                        '{} has a non plausible div yield at {} ({} = {} / {} * 100).'
                        .format(symbol, my_date, div_yield, data[my_date], price.close)
                    )
                else:
                    data[my_date] = div_yield
            else:
                drop.append(my_date)
        data = data.drop(labels=drop)
        self.calc = data.median(axis=0)
        if self.calc is None or math.isnan(self.calc):
            raise RuntimeError("Couldn't calculate dividend yield.")
        return super(DividendKings, self).analyse()

    def get_calculation(self):
        return self.calc

    def look_back_date(self):
        return self.now_date + relativedelta(months=-self.lookback)
