#!/usr/bin/env python3.7
# -*- coding: utf-8 -*-

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, Iterable, List, Optional, Union, TypeVar
from urllib.parse import quote as urlencode

from .json_to_obj import dc, extract_to_model, timestamp_to_dt, str_to_dt
from .json_to_obj import Numeric, Serializable


class InstrumentType(Enum):
    STOCK = 'STOCK'
    FUTURE = 'FUTURE'
    BOND = 'BOND'
    FOREX = 'CURRENCY'
    FUND = 'FUND'
    OPTION = 'OPTION'
    CFD = 'CFD'
    CALENDAR_SPREAD = 'CALENDAR_SPREAD'
    FX_SPOT = 'FX_SPOT'


class Durations(Enum):
    day = 'day'
    good_till_cancel = 'good_till_cancel'
    good_till_time = 'good_till_time'
    immediate_or_cancel = 'immediate_or_cancel'
    fill_or_kill = 'fill_or_kill'
    at_the_opening = 'at_the_opening'
    at_the_close = 'at_the_close'
    unknown = 'unknown'


class OrderTypes(Enum):
    market = 'market'
    limit = 'limit'
    stop = 'stop'
    stop_limit = 'stop_limit'
    twap = 'twap'
    iceberg = 'iceberg'
    trailing_stop = 'trailing_stop'
    unknown = 'unknown'


class Side(Enum):
    BUY = 'buy'
    SELL = 'sell'


class PermissionStatus(Enum):
    full_access = 'Full'
    read_only = 'ReadOnly'
    close_only = 'CloseOnly'


class OptionRight(Enum):
    PULL = 'PUT'
    CALL = 'CALL'
    BOTH = "BOTH"


class CandleDurations(Enum):
    DAY1 = 86400
    HOUR1 = 3600
    MIN5 = 300
    MIN1 = 60


class DataType(Enum):
    QUOTES = "quotes"
    TRADES = "trades"


class FeedLevel(Enum):
    BP = "best_price"
    MD = "market_depth"
    BEST_PRICE = "best_price"
    MARKET_DEPTH = "market_depth"


class Ordering(Enum):
    ASC = "ASC"
    DESC = "DESC"


class OrderStatuses(Enum):
    created = 'created'
    accepted = 'accepted'
    pending = 'pending'
    placing = 'placing'
    working = 'working'
    cancelled = 'cancelled'
    filled = 'filled'
    rejected = 'rejected'

    @staticmethod
    def terminated(other: Enum):
        return other in (OrderStatuses.filled, OrderStatuses.rejected, OrderStatuses.cancelled)

    @staticmethod
    def active(other: Enum):
        return not OrderStatuses.terminated(other)


class ModifyAction(Enum):
    REPLACE = 'replace'
    CANCEL = 'cancel'


class Scopes(Enum):
    symbols = "symbols"
    feed = "feed"
    change = "change"
    ohlc = "ohlc"
    crossrates = "crossrates"
    summary = "summary"
    orders = "orders"
    transactions = "transactions"
    accounts = "accounts"


class AuthMethods(Enum):
    JWT = "jwt"
    BASIC = "basic"


class QuoteV1(Serializable):

    def __init__(self, symbol_id: str, timestamp: int, bid: Numeric, ask: Numeric) -> None:
        self.timestamp = timestamp_to_dt(timestamp)
        self.symbol_id = symbol_id
        self.bid = dc(bid)
        self.ask = dc(ask)

    @property
    def mid(self) -> Optional[Decimal]:
        if (self.bid is None) or (self.ask is None):
            return None
        else:
            return (self.bid + self.ask) / dc(2)


class QuoteV2(Serializable):
    class Level(Serializable):
        def __init__(self, value: str, size: str) -> None:
            self.value = dc(value)
            self.size = dc(size)

        @property
        def price(self) -> Decimal:
            return self.value

    def __init__(self, symbol_id: str, timestamp: int, bid: List[Dict[str, Numeric]],
                 ask: List[Dict[str, Numeric]]) -> None:
        self.timestamp = timestamp_to_dt(timestamp)
        self.symbol_id = symbol_id
        self.bid = extract_to_model(bid, self.Level)
        self.ask = extract_to_model(ask, self.Level)

    @property
    def mid(self) -> Optional[Decimal]:
        if (self.bid is None) or (self.ask is None):
            return None
        else:
            return (self.bid[0].price + self.ask[0].price) / dc(2)


class QuoteV3(Serializable):
    class Level(Serializable):
        def __init__(self, price: str, size: str) -> None:
            self.price = dc(price)
            self.size = dc(size)

    def __init__(self, symbol_id: str, timestamp: int, bid: List[Dict[str, Numeric]],
                 ask: List[Dict[str, Numeric]]) -> None:
        self.timestamp = timestamp_to_dt(timestamp)
        self.symbol_id = symbol_id
        self.bid = extract_to_model(bid, self.Level)
        self.ask = extract_to_model(ask, self.Level)

    @property
    def mid(self) -> Optional[Decimal]:
        if (self.bid is None) or (self.ask is None):
            return None
        else:
            return (self.bid[0].price + self.ask[0].price) / dc(2)


QuoteType = TypeVar('QuoteType', QuoteV1, QuoteV2, QuoteV3, covariant=True)


class TradeV1(Serializable):
    def __init__(self, timestamp: int, symbol_id: str, value: str, size: str) -> None:
        self.timestamp = timestamp_to_dt(timestamp)
        self.symbol_id = symbol_id
        self.value = dc(value)
        self.size = dc(size)


class TradeV2(TradeV1):
    pass


class TradeV3(Serializable):
    def __init__(self, timestamp: int, symbol_id: str, price: str, size: str) -> None:
        self.timestamp = timestamp_to_dt(timestamp)
        self.symbol_id = symbol_id
        self.price = dc(price)
        self.size = dc(size)


TradeType = TypeVar('TradeType', TradeV1, TradeV2, TradeV3, covariant=True)


class ChangeV1(Serializable):
    def __init__(self, base_price: str, daily_change: str, symbol_id: str) -> None:
        self.base_price = dc(base_price)
        self.daily_change = dc(daily_change)
        self.symbol_id = symbol_id


class ChangeV2(ChangeV1):
    pass


class ChangeV3(Serializable):
    def __init__(self, last_session_close_price: str, daily_change: str, symbol_id: str) -> None:
        self.last_session_close_price = dc(last_session_close_price)
        self.daily_change = dc(daily_change)
        self.symbol_id = symbol_id


ChangeType = TypeVar('ChangeType', ChangeV1, ChangeV2, ChangeV3, covariant=True)


class OHLCQuotes(Serializable):
    def __init__(self, open_: Numeric, low: Numeric, high: Numeric, close: Numeric, timestamp: int) -> None:
        self.open_ = dc(open_)
        self.low = dc(low)
        self.high = dc(high)
        self.close = dc(close)
        self.timestamp = timestamp_to_dt(timestamp)


class OHLCTrades(OHLCQuotes):
    def __init__(self, open_: Numeric, low: Numeric, high: Numeric, close: Numeric, timestamp: int,
                 volume: Numeric) -> None:
        super().__init__(open_, low, high, close, timestamp)
        self.volume = dc(volume)


class Crossrate(Serializable):
    def __init__(self, pair: str, symbol_id: str, rate: str) -> None:
        self.pair = pair
        self.symbol_id = symbol_id
        self.rate = rate


class SummaryV1(Serializable):
    class CurrencyPos(Serializable):
        def __init__(self, code: str, value: float, converted_value: float) -> None:
            self.code = code
            self.value = dc(value)
            self.converted_value = dc(converted_value)

    class Position(Serializable):
        def __init__(self, id_: str, symbol_type: str, currency: str, price: float, average_price: float,
                     quantity: float, value: float, converted_value: float, pnl: float, converted_pnl: float) -> None:
            self.id_ = id_
            self.symbol_type = Serializable.to_enum(symbol_type, InstrumentType)
            self.currency = currency
            self.price = dc(price)
            self.average_price = dc(average_price)
            self.quantity = dc(quantity)
            self.value = dc(value)
            self.converted_value = dc(converted_value)
            self.pnl = dc(pnl)
            self.converted_pnl = dc(converted_pnl)

    def __init__(self, account: str, timestamp: int, currency: str, margin_utilization: float, free_money: float,
                 net_asset_value: float, money_used_for_margin: float, session_date: str, currencies: List[str],
                 positions: List[Dict[str, Union[str, float]]]) -> None:
        self.account = account
        self.positions = extract_to_model(positions, self.Position)
        self.currencies = extract_to_model(currencies, self.CurrencyPos)
        self.session_date = session_date
        self.free_money = dc(free_money)
        self.timestamp = timestamp_to_dt(timestamp)
        self.net_asset_value = dc(net_asset_value)
        self.margin_utilization = dc(margin_utilization)
        self.money_used_for_margin = dc(money_used_for_margin)
        self.currency = currency


class SummaryV2(Serializable):
    class CurrencyPos(Serializable):
        def __init__(self, code: str, value: str, converted_value: str) -> None:
            self.code = code
            self.value = dc(value)
            self.converted_value = dc(converted_value)

    class Position(Serializable):
        def __init__(self, id_: str, symbol_type: str, currency: str, price: str, average_price: str, quantity: str,
                     value: str, converted_value: str, pnl: str, converted_pnl: str) -> None:
            self.id_ = id_
            self.symbol_type = Serializable.to_enum(symbol_type, InstrumentType)
            self.currency = currency
            self.price = dc(price)
            self.average_price = dc(average_price)
            self.quantity = dc(quantity)
            self.value = dc(value)
            self.converted_value = dc(converted_value)
            self.pnl = dc(pnl)
            self.converted_pnl = dc(converted_pnl)

    def __init__(self, account: str, timestamp: int, currency: str, margin_utilization: str, free_money: str,
                 net_asset_value: str, money_used_for_margin: str, session_date: Optional[List[int]],
                 currencies: List[Dict[str, str]],  positions: List[Dict[str, str]]) -> None:
        self.account = account
        self.positions = extract_to_model(positions, self.Position)
        self.currencies = extract_to_model(currencies, self.CurrencyPos)
        self.session_date = datetime(*session_date) if session_date else None
        self.free_money = dc(free_money)
        self.timestamp = timestamp_to_dt(timestamp)
        self.net_asset_value = dc(net_asset_value)
        self.margin_utilization = dc(margin_utilization)
        self.money_used_for_margin = dc(money_used_for_margin)
        self.currency = currency


class SummaryV3(Serializable):
    class CurrencyPos(Serializable):
        def __init__(self, code: str, price: str, converted_value: str) -> None:
            self.code = code
            self.price = dc(price)
            self.converted_value = dc(converted_value)

    class Position(Serializable):
        def __init__(self, symbol_id: str, symbol_type: str, currency: str, price: str,
                     average_price: str, quantity: str, value: str, converted_value: str,
                     pnl: str, converted_pnl: str) -> None:
            self.symbol_id = symbol_id
            self.symbol_type = Serializable.to_enum(symbol_type, InstrumentType)
            self.currency = currency
            self.price = dc(price)
            self.average_price = dc(average_price)
            self.quantity = dc(quantity)
            self.value = dc(value)
            self.converted_value = dc(converted_value)
            self.pnl = dc(pnl)
            self.converted_pnl = dc(converted_pnl)

    def __init__(self, account_id: str, timestamp: int, currency: str, margin_utilization: float, free_money: float,
                 net_asset_value: float, money_used_for_margin: float, session_date: str, currencies: List[str],
                 positions: List[Dict[str, str]]) -> None:
        self.account_id = account_id
        self.positions = extract_to_model(positions, self.Position)
        self.currencies = extract_to_model(currencies, self.CurrencyPos)
        self.session_date = session_date
        self.free_money = dc(free_money)
        self.timestamp = timestamp_to_dt(timestamp)
        self.net_asset_value = dc(net_asset_value)
        self.margin_utilization = dc(margin_utilization)
        self.money_used_for_margin = dc(money_used_for_margin)
        self.currency = currency


SummaryType = TypeVar('SummaryType', SummaryV1, SummaryV2, SummaryV3, covariant=True)


class TransactionV1(Serializable):
    def __init__(self, operation_type: str, id_: str, asset: Optional[str], when: int, sum_: float,
                 symbol_id: Optional[str] = None, account_id: Optional[str] = None) -> None:
        self.operation_type = operation_type
        self.id_ = id_
        self.asset = asset
        self.when = timestamp_to_dt(when)
        self.sum_ = sum_
        self.symbol_id = symbol_id
        self.account_id = account_id


class TransactionV2(TransactionV1):
    pass


class TransactionV3(Serializable):
    def __init__(self, operation_type: str, id_: str, asset: Optional[str], timestamp: int, sum_: float,
                 symbol_id: Optional[str] = None, account_id: Optional[str] = None) -> None:
        self.operation_type = operation_type
        self.id_ = id_
        self.asset = asset
        self.timestamp = timestamp_to_dt(timestamp)
        self.sum_ = sum_
        self.symbol_id = symbol_id
        self.account_id = account_id


TransactionType = TypeVar('TransactionType', TransactionV1, TransactionV2, TransactionV3, covariant=True)


class UserAccount(Serializable):
    def __init__(self, status: str, account_id: str) -> None:
        self.status = Serializable.to_enum(status, PermissionStatus)
        self.account_id = account_id


class SymbolV1(Serializable):
    class OptionData(Serializable):
        def __init__(self, option_group_id: str, right: str, strike_price: float) -> None:
            self.option_group_id = option_group_id
            self.right = Serializable.to_enum(right, OptionRight)
            self.strike_price = dc(strike_price)

    def __init__(self, i18n: Dict[str, str], name: str, description: str, country: str, exchange: str, id_: str,
                 currency: str, mpi: float, type_: str, ticker: str, group: Optional[str] = None,
                 option_data: Optional[Dict[str, str]] = None, expiration: Optional[int] = None) -> None:
        self.option_data = extract_to_model(option_data, self.OptionData)
        self.i18n = i18n
        self.name = name
        self.description = description
        self.country = country
        self.exchange = exchange
        self.id_ = id_
        self.currency = currency
        self.mpi = dc(mpi)
        self.type_ = Serializable.to_enum(type_, InstrumentType)
        self.ticker = ticker
        self.expiration = timestamp_to_dt(expiration)
        self.group = group


class SymbolV2(Serializable):
    class OptionData(Serializable):
        def __init__(self, option_group_id: str, right: str, strike_price: str) -> None:
            self.option_group_id = option_group_id
            self.right = Serializable.to_enum(right, OptionRight)
            self.strike_price = dc(strike_price)

    def __init__(self, i18n: Dict[str, str], name: str, description: str, country: str, exchange: str, id_: str,
                 currency: str, mpi: str, type_: str, ticker: str, group: Optional[str] = None,
                 option_data: Optional[Dict[str, str]] = None, expiration: Optional[int] = None) -> None:
        self.option_data = extract_to_model(option_data, self.OptionData)
        self.i18n = i18n
        self.name = name
        self.description = description
        self.country = country
        self.exchange = exchange
        self.id_ = id_
        self.currency = currency
        self.mpi = dc(mpi)
        self.type_ = Serializable.to_enum(type_, InstrumentType)
        self.ticker = ticker
        self.expiration = timestamp_to_dt(expiration)
        self.group = group


class SymbolV3(Serializable):
    class OptionData(Serializable):
        def __init__(self, option_group_id: str, option_right: str, strike_price: str) -> None:
            self.option_group_id = option_group_id
            self.option_right = Serializable.to_enum(option_right, OptionRight)
            self.strike_price = dc(strike_price)

    def __init__(self, name: str, description: str, country: str, exchange: str, symbol_id: str, currency: str,
                 min_price_increment: str, symbol_type: str, ticker: str, group: str, expiration: Optional[int] = None,
                 option_data: Optional[Dict[str, str]] = None) -> None:
        self.option_data = extract_to_model(option_data, self.OptionData)
        self.name = name
        self.description = description
        self.country = country
        self.exchange = exchange
        self.symbol_id = symbol_id
        self.currency = currency
        self.min_price_increment = dc(min_price_increment)
        self.symbol_type = Serializable.to_enum(symbol_type, InstrumentType)
        self.ticker = ticker
        self.expiration = timestamp_to_dt(expiration)
        self.group = group


SymbolType = TypeVar('SymbolType', SymbolV1, SymbolV2, SymbolV3, covariant=True)


class SymbolSpecification(Serializable):
    def __init__(self, leverage: Numeric, contract_multiplier: Numeric, price_unit: Numeric, units: str,
                 lot_size: Numeric) -> None:
        self.leverage = dc(leverage)
        self.contract_multiplier = dc(contract_multiplier)
        self.price_unit = dc(price_unit)
        self.units = units
        self.lot_size = dc(lot_size)


class Exchange(Serializable):
    def __init__(self, id_: str, name: str, country: str) -> None:
        self.id_ = id_
        self.name = name
        self.country = country


class Group(Serializable):
    def __init__(self, group: str, name: str, types: List[str], exchange: str) -> None:
        self.group = group
        self.name = name
        self.types = [Serializable.to_enum(ty, InstrumentType) for ty in types]
        self.exchange = exchange


class Schedule(Serializable):
    class Interval(Serializable):
        class Period(Serializable):
            def __init__(self, start: int, end: int) -> None:
                self.start = timestamp_to_dt(start)
                self.end = timestamp_to_dt(end)

        def __init__(self, name: str, period: Dict[str, int], order_types: Optional[Dict[str, str]] = None) -> None:
            self.name = name
            self.period = extract_to_model(period, self.Period)
            self.order_types = order_types

        @property
        def start(self) -> Decimal:
            return self.period.start

        @property
        def end(self) -> Decimal:
            return self.period.end

    def __init__(self, intervals: list) -> None:
        self.intervals = extract_to_model(intervals, self.Interval)


class OrderSentV1(Serializable):
    order_type = None  # type: OrderTypes

    def __init__(self, account: str, instrument: str, side: Side, quantity: Numeric, duration: Durations,
                 client_tag: Optional[str] = None, oco_group: Optional[str] = None,
                 if_done_parent_id: Optional[str] = None) -> None:
        self.account = account
        self.instrument = instrument
        self.side = side
        self.quantity = dc(quantity)
        self.duration = duration
        self.client_tag = client_tag
        self.oco_group = oco_group
        self.if_done_parent_id = if_done_parent_id


class OrderSentV2(Serializable):
    order_type = None  # type: OrderTypes

    def __init__(self, account_id: str, instrument: str, side: Side, quantity: Numeric, duration: Durations,
                 client_tag: Optional[str] = None, oco_group: Optional[str] = None,
                 if_done_parent_id: Optional[str] = None, take_profit: Optional[Numeric] = None,
                 stop_loss: Optional[Numeric] = None) -> None:
        self.account_id = account_id
        self.instrument = instrument
        self.side = side
        self.quantity = dc(quantity)
        self.duration = duration
        self.client_tag = client_tag
        self.oco_group = oco_group
        self.if_done_parent_id = if_done_parent_id
        self.take_profit = take_profit
        self.stop_loss = stop_loss


class OrderSentV3(Serializable):
    order_type = None  # type: OrderTypes

    def __init__(self, account_id: str, symbol_id: str, side: Side, quantity: Numeric, duration: Durations,
                 client_tag: Optional[str] = None, oco_group: Optional[str] = None,
                 if_done_parent_id: Optional[str] = None, take_profit: Optional[Numeric] = None,
                 stop_loss: Optional[Numeric] = None) -> None:
        self.account_id = account_id
        self.symbol_id = symbol_id
        self.side = side
        self.quantity = dc(quantity)
        self.duration = duration
        self.client_tag = client_tag
        self.oco_group = oco_group
        self.if_done_parent_id = if_done_parent_id
        self.take_profit = take_profit
        self.stop_loss = stop_loss


OrderSentType = TypeVar('OrderSentType', OrderSentV1, OrderSentV2, OrderSentV3, covariant=True)


class OrderMarketV1(OrderSentV1):
    def __init__(self, account: str, instrument: str, side: Side, quantity: Numeric, duration: Durations,
                 client_tag: Optional[str] = None, oco_group: Optional[str] = None,
                 if_done_parent_id: Optional[str] = None) -> None:
        super().__init__(account, instrument, side, quantity, duration, client_tag, oco_group, if_done_parent_id)
        self.order_type = OrderTypes.market


class OrderMarketV2(OrderSentV2):
    def __init__(self, account_id: str, instrument: str, side: Side, quantity: Numeric, duration: Durations,
                 client_tag: Optional[str] = None, oco_group: Optional[str] = None,
                 if_done_parent_id: Optional[str] = None, take_profit: Optional[Numeric] = None,
                 stop_loss: Optional[Numeric] = None) -> None:
        super().__init__(account_id, instrument, side, quantity, duration, client_tag, oco_group, if_done_parent_id,
                         take_profit, stop_loss)
        self.order_type = OrderTypes.market


class OrderMarketV3(OrderSentV3):
    def __init__(self, account_id: str, instrument: str, side: Side, quantity: Numeric, duration: Durations,
                 client_tag: Optional[str] = None, oco_group: Optional[str] = None,
                 if_done_parent_id: Optional[str] = None, take_profit: Optional[Numeric] = None,
                 stop_loss: Optional[Numeric] = None) -> None:
        super().__init__(account_id, instrument, side, quantity, duration, client_tag, oco_group, if_done_parent_id,
                         take_profit, stop_loss)
        self.order_type = OrderTypes.market


OrderMarketType = TypeVar("OrderMarketType", OrderMarketV1, OrderMarketV2, OrderMarketV3, covariant=True)


class OrderLimitV1(OrderSentV1):
    def __init__(self, account: str, instrument: str, side: Side, quantity: Numeric, duration: Durations,
                 limit_price: Numeric, client_tag: Optional[str] = None, oco_group: Optional[str] = None,
                 if_done_parent_id: Optional[str] = None) -> None:
        super().__init__(account, instrument, side, quantity, duration, client_tag, oco_group, if_done_parent_id)
        self.order_type = OrderTypes.limit
        self.limit_price = dc(limit_price)


class OrderLimitV2(OrderSentV2):
    def __init__(self, account_id: str, instrument: str, side: Side, quantity: Numeric, duration: Durations,
                 limit_price: Numeric, client_tag: Optional[str] = None, oco_group: Optional[str] = None,
                 if_done_parent_id: Optional[str] = None, take_profit: Optional[Numeric] = None,
                 stop_loss: Optional[Numeric] = None) -> None:
        super().__init__(account_id, instrument, side, quantity, duration, client_tag, oco_group, if_done_parent_id,
                         take_profit, stop_loss)
        self.order_type = OrderTypes.limit
        self.limit_price = dc(limit_price)


class OrderLimitV3(OrderSentV3):
    def __init__(self, account_id: str, symbol_id: str, side: Side, quantity: Numeric, duration: Durations,
                 limit_price: Numeric, client_tag: Optional[str] = None, oco_group: Optional[str] = None,
                 if_done_parent_id: Optional[str] = None, take_profit: Optional[Numeric] = None,
                 stop_loss: Optional[Numeric] = None) -> None:
        super().__init__(account_id, symbol_id, side, quantity, duration, client_tag, oco_group, if_done_parent_id,
                         take_profit, stop_loss)
        self.order_type = OrderTypes.limit
        self.limit_price = limit_price


OrderLimitType = TypeVar("OrderLimitType", OrderLimitV1, OrderLimitV2, OrderLimitV3, covariant=True)


class OrderStopV1(OrderSentV1):
    def __init__(self, account: str, instrument: str, side: Side, quantity: Numeric, duration: Durations,
                 stop_price: Numeric, client_tag: Optional[str] = None, oco_group: Optional[str] = None,
                 if_done_parent_id: Optional[str] = None) -> None:
        super().__init__(account, instrument, side, quantity, duration, client_tag, oco_group, if_done_parent_id)
        self.order_type = OrderTypes.stop
        self.stop_price = stop_price


class OrderStopV2(OrderSentV2):
    def __init__(self, account_id: str, instrument: str, side: Side, quantity: Numeric, duration: Durations,
                 stop_price: Numeric, client_tag: Optional[str] = None, oco_group: Optional[str] = None,
                 if_done_parent_id: Optional[str] = None, take_profit: Optional[Numeric] = None,
                 stop_loss: Optional[Numeric] = None) -> None:
        super().__init__(account_id, instrument, side, quantity, duration, client_tag, oco_group, if_done_parent_id,
                         take_profit, stop_loss)
        self.order_type = OrderTypes.stop
        self.stop_price = stop_price


class OrderStopV3(OrderSentV3):
    def __init__(self, account_id: str, symbol_id: str, side: Side, quantity: Numeric, duration: Durations,
                 stop_price: Numeric, client_tag: Optional[str] = None, oco_group: Optional[str] = None,
                 if_done_parent_id: Optional[str] = None, take_profit: Optional[Numeric] = None,
                 stop_loss: Optional[Numeric] = None) -> None:
        super().__init__(account_id, symbol_id, side, quantity, duration, client_tag, oco_group, if_done_parent_id,
                         take_profit, stop_loss)
        self.order_type = OrderTypes.stop
        self.stop_price = stop_price


OrderStopType = TypeVar("OrderStopType", OrderStopV1, OrderStopV2, OrderStopV3, covariant=True)


class OrderStopLimitV1(OrderSentV1):
    def __init__(self, account: str, instrument: str, side: Side, quantity: Numeric, duration: Durations,
                 limit_price: Numeric, stop_price: Numeric, client_tag: Optional[str] = None,
                 oco_group: Optional[str] = None, if_done_parent_id: Optional[str] = None) -> None:
        super().__init__(account, instrument, side, quantity, duration, client_tag, oco_group, if_done_parent_id)
        self.order_type = OrderTypes.stop_limit
        self.limit_price = limit_price
        self.stop_price = stop_price


class OrderStopLimitV2(OrderSentV2):
    def __init__(self, account_id: str, instrument: str, side: Side, quantity: Numeric, duration: Durations,
                 limit_price: Numeric, stop_price: Numeric, client_tag: Optional[str] = None,
                 oco_group: Optional[str] = None, if_done_parent_id: Optional[str] = None,
                 take_profit: Optional[Numeric] = None, stop_loss: Optional[Numeric] = None) -> None:
        super().__init__(account_id, instrument, side, quantity, duration, client_tag, oco_group, if_done_parent_id,
                         take_profit, stop_loss)
        self.order_type = OrderTypes.stop_limit
        self.limit_price = limit_price
        self.stop_price = stop_price


class OrderStopLimitV3(OrderSentV3):
    def __init__(self, account_id: str, symbol_id: str, side: Side, quantity: Numeric, duration: Durations,
                 limit_price: Numeric, stop_price: Numeric, client_tag: Optional[str] = None,
                 oco_group: Optional[str] = None, if_done_parent_id: Optional[str] = None,
                 take_profit: Optional[Numeric] = None, stop_loss: Optional[Numeric] = None) -> None:
        super().__init__(account_id, symbol_id, side, quantity, duration, client_tag, oco_group, if_done_parent_id,
                         take_profit, stop_loss)
        self.order_type = OrderTypes.stop_limit
        self.limit_price = limit_price
        self.stop_price = stop_price


OrderStopLimitType = TypeVar("OrderStopLimitType", OrderStopLimitV1, OrderStopLimitV2, OrderStopLimitV3, covariant=True)


class OrderTrailingStopV1(OrderSentV1):
    def __init__(self, account: str, instrument: str, side: Side, quantity: Numeric, duration: Durations,
                 price_distance: Numeric, client_tag: Optional[str] = None, oco_group: Optional[str] = None,
                 if_done_parent_id: Optional[str] = None) -> None:
        super().__init__(account, instrument, side, quantity, duration, client_tag, oco_group, if_done_parent_id)
        self.order_type = OrderTypes.trailing_stop
        self.price_distance = price_distance


class OrderTrailingStopV2(OrderSentV2):
    def __init__(self, account_id: str, instrument: str, side: Side, quantity: Numeric, duration: Durations,
                 price_distance: Numeric, client_tag: Optional[str] = None, oco_group: Optional[str] = None,
                 if_done_parent_id: Optional[str] = None, take_profit: Optional[Numeric] = None,
                 stop_loss: Optional[Numeric] = None) -> None:
        super().__init__(account_id, instrument, side, quantity, duration, client_tag, oco_group, if_done_parent_id,
                         take_profit, stop_loss)
        self.order_type = OrderTypes.trailing_stop
        self.price_distance = price_distance


class OrderTrailingStopV3(OrderSentV3):
    def __init__(self, account_id: str, symbol_id: str, side: Side, quantity: Numeric, duration: Durations,
                 price_distance: Numeric, client_tag: Optional[str] = None, oco_group: Optional[str] = None,
                 if_done_parent_id: Optional[str] = None, take_profit: Optional[Numeric] = None,
                 stop_loss: Optional[Numeric] = None) -> None:
        super().__init__(account_id, symbol_id, side, quantity, duration, client_tag, oco_group, if_done_parent_id,
                         take_profit, stop_loss)
        self.order_type = OrderTypes.trailing_stop
        self.price_distance = price_distance


OrderTrailingStopType = TypeVar("OrderTrailingStopType", OrderTrailingStopV1, OrderTrailingStopV2, OrderTrailingStopV3,
                                covariant=True)


class OrderTwapV1(OrderSentV1):
    def __init__(self, account: str, instrument: str, side: Side, quantity: Numeric, duration: Durations,
                 part_quantity: Numeric, place_interval: Numeric, client_tag: Optional[str] = None,
                 oco_group: Optional[str] = None, if_done_parent_id: Optional[str] = None) -> None:
        super().__init__(account, instrument, side, quantity, duration, client_tag, oco_group, if_done_parent_id)
        self.order_type = OrderTypes.twap
        self.part_quantity = part_quantity
        self.place_interval = place_interval


class OrderTwapV2(OrderSentV2):
    def __init__(self, account_id: str, instrument: str, side: Side, quantity: Numeric, duration: Durations,
                 part_quantity: Numeric, place_interval: Numeric, client_tag: Optional[str] = None,
                 oco_group: Optional[str] = None, if_done_parent_id: Optional[str] = None,
                 take_profit: Optional[Numeric] = None, stop_loss: Optional[Numeric] = None) -> None:
        super().__init__(account_id, instrument, side, quantity, duration, client_tag, oco_group, if_done_parent_id,
                         take_profit, stop_loss)
        self.order_type = OrderTypes.twap
        self.part_quantity = part_quantity
        self.place_interval = place_interval


class OrderTwapV3(OrderSentV3):
    def __init__(self, account_id: str, symbol_id: str, side: Side, quantity: Numeric, duration: Durations,
                 part_quantity: Numeric, place_interval: Numeric, client_tag: Optional[str] = None,
                 oco_group: Optional[str] = None, if_done_parent_id: Optional[str] = None,
                 take_profit: Optional[Numeric] = None, stop_loss: Optional[Numeric] = None) -> None:
        super().__init__(account_id, symbol_id, side, quantity, duration, client_tag, oco_group, if_done_parent_id,
                         take_profit, stop_loss)
        self.order_type = OrderTypes.twap
        self.part_quantity = part_quantity
        self.place_interval = place_interval


OrderTwapType = TypeVar("OrderTwapType", OrderTwapV1, OrderTwapV2, OrderTwapV3, covariant=True)


class OrderIcebergV1(OrderSentV1):
    def __init__(self, account: str, instrument: str, side: Side, quantity: Numeric, duration: Durations,
                 part_quantity: Numeric, limit_price: Numeric, client_tag: Optional[str] = None,
                 oco_group: Optional[str] = None, if_done_parent_id: Optional[str] = None) -> None:
        super().__init__(account, instrument, side, quantity, duration, client_tag, oco_group, if_done_parent_id)
        self.order_type = OrderTypes.iceberg
        self.limit_price = limit_price
        self.part_quantity = part_quantity


class OrderIcebergV2(OrderSentV2):
    def __init__(self, account_id: str, instrument: str, side: Side, quantity: Numeric, duration: Durations,
                 part_quantity: Numeric, limit_price: Numeric, client_tag: Optional[str] = None,
                 oco_group: Optional[str] = None, if_done_parent_id: Optional[str] = None,
                 take_profit: Optional[Numeric] = None, stop_loss: Optional[Numeric] = None) -> None:
        super().__init__(account_id, instrument, side, quantity, duration, client_tag, oco_group, if_done_parent_id,
                         take_profit, stop_loss)
        self.order_type = OrderTypes.iceberg
        self.limit_price = limit_price
        self.part_quantity = part_quantity


class OrderIcebergV3(OrderSentV3):
    def __init__(self, account_id: str, symbol_id: str, side: Side, quantity: Numeric, duration: Durations,
                 part_quantity: Numeric, limit_price: Numeric, client_tag: Optional[str] = None,
                 oco_group: Optional[str] = None, if_done_parent_id: Optional[str] = None,
                 take_profit: Optional[Numeric] = None, stop_loss: Optional[Numeric] = None) -> None:
        super().__init__(account_id, symbol_id, side, quantity, duration, client_tag, oco_group, if_done_parent_id,
                         take_profit, stop_loss)
        self.order_type = OrderTypes.iceberg
        self.limit_price = limit_price
        self.part_quantity = part_quantity


OrderIcebergType = TypeVar("OrderIcebergType", OrderIcebergV1, OrderIcebergV2, OrderIcebergV3, covariant=True)


class Fill(Serializable):
    def __init__(self, quantity: str, price: str, position: int, time: str) -> None:
        self.quantity = dc(quantity)
        self.price = dc(price)
        self.position = position
        self.time = str_to_dt(time)


class OrderState(Serializable):
    def __init__(self, last_update: str, status: str, fills: List[Dict[str, Union[str, int]]],
                 reason: Optional[str] = None):
        self.last_update = str_to_dt(last_update)
        self.status = Serializable.to_enum(status, OrderStatuses)
        self.fills = extract_to_model(fills, Fill)
        # TODO: rewrite it to normal Reject model
        self.reason = reason


class Reject(Serializable):
    def __init__(self, group: str, message: str):
        self.group = group
        self.message = message


class OrderV1(Serializable):
    class OrderParameters(Serializable):
        def __init__(self, side: str, duration: str, quantity: str, instrument: str, order_type: str,
                     oco_group: Optional[str] = None, if_done_parent_id: Optional[str] = None,
                     limit_price: Optional[str] = None, stop_price: Optional[str] = None,
                     price_distance: Optional[str] = None, part_quantity: Optional[str] = None,
                     place_interval: Optional[str] = None) -> None:
            self.side = Serializable.to_enum(side, Side)
            self.duration = Serializable.to_enum(duration, Durations)
            self.quantity = dc(quantity)
            self.instrument = instrument
            self.order_type = Serializable.to_enum(order_type, OrderTypes)
            self.oco_group = oco_group
            self.if_done_parent_id = if_done_parent_id
            self.limit_price = dc(limit_price)
            self.stop_price = dc(stop_price)
            self.price_distance = dc(price_distance)
            self.part_quantity = dc(part_quantity)
            self.place_interval = dc(place_interval)

    def __init__(self, place_time: str, order_state: Dict[str, Union[List, str, None]], id_: str,
                 order_parameters: Dict[str, Optional[str]], current_modification_id: str, exante_account: str,
                 client_tag: Optional[str] = None, username: Optional[str] = None):
        self.place_time = str_to_dt(place_time)
        self.order_state = extract_to_model(order_state, OrderState)
        self.id_ = id_
        self.client_tag = client_tag
        self.order_parameters = extract_to_model(order_parameters, self.OrderParameters)
        self.current_modification_id = current_modification_id
        self.exante_account = exante_account
        self.username = username


class OrderV2(Serializable):
    class OrderParameters(Serializable):
        def __init__(self, side: str, duration: str, quantity: str, instrument: str, order_type: str,
                     oco_group: Optional[str] = None, if_done_parent_id: Optional[str] = None,
                     limit_price: Optional[str] = None, stop_price: Optional[str] = None,
                     price_distance: Optional[str] = None, part_quantity: Optional[str] = None,
                     place_interval: Optional[str] = None) -> None:
            self.side = Serializable.to_enum(side, Side)
            self.duration = Serializable.to_enum(duration, Durations)
            self.quantity = dc(quantity)
            self.instrument = instrument
            self.order_type = Serializable.to_enum(order_type, OrderTypes)
            self.oco_group = oco_group
            self.if_done_parent_id = if_done_parent_id
            self.limit_price = dc(limit_price)
            self.stop_price = dc(stop_price)
            self.price_distance = dc(price_distance)
            self.part_quantity = dc(part_quantity)
            self.place_interval = dc(place_interval)

    def __init__(self, place_time: str, order_state: Dict, id_: str, order_parameters: Dict,
                 username: str, current_modification_id: str, account_id: str = None,
                 client_tag: Optional[str] = None) -> None:
        self.place_time = str_to_dt(place_time)
        self.order_state = extract_to_model(order_state, OrderState)
        self.id_ = id_
        self.client_tag = client_tag
        self.order_parameters = extract_to_model(order_parameters, self.OrderParameters)
        self.current_modification_id = current_modification_id
        self.account_id = account_id
        self.username = username


class OrderV3(Serializable):
    class OrderParameters(Serializable):
        def __init__(self, side: str, duration: str, quantity: str, symbol_id: str, order_type: str,
                     oco_group: Optional[str] = None, if_done_parent_id: Optional[str] = None,
                     limit_price: Optional[str] = None, stop_price: Optional[str] = None,
                     price_distance: Optional[str] = None, part_quantity: Optional[str] = None,
                     place_interval: Optional[str] = None) -> None:
            self.side = Serializable.to_enum(side, Side)
            self.duration = Serializable.to_enum(duration, Durations)
            self.quantity = dc(quantity)
            self.symbol_id = symbol_id
            self.order_type = Serializable.to_enum(order_type, OrderTypes)
            self.oco_group = oco_group
            self.if_done_parent_id = if_done_parent_id
            self.limit_price = dc(limit_price)
            self.stop_price = dc(stop_price)
            self.price_distance = dc(price_distance)
            self.part_quantity = dc(part_quantity)
            self.place_interval = dc(place_interval)

    def __init__(self, place_time: str, order_state: Dict, order_id: str, order_parameters: Dict, username: str,
                 current_modification_id: str, account_id: str, client_tag: Optional[str] = None) -> None:
        self.place_time = str_to_dt(place_time)
        self.order_state = extract_to_model(order_state, OrderState)
        self.order_id = order_id
        self.client_tag = client_tag
        self.order_parameters = extract_to_model(order_parameters, self.OrderParameters)
        self.current_modification_id = current_modification_id
        self.account_id = account_id
        self.username = username


OrderType = TypeVar('OrderType', OrderV1, OrderV2, OrderV3, covariant=True)


class ExOrderV1(Serializable):
    def __init__(self, quantity: str, order_id: str, event: str, price: str, position: str, time: str,):
        self.quantity = dc(quantity)
        self.order_id = order_id
        self.event = event
        self.price = dc(price)
        self.position = dc(position)
        self.time = str_to_dt(time)


class ExOrderV2(ExOrderV1):
    pass


class ExOrderV3(Serializable):
    def __init__(self, quantity: str, order_id: str, price: str, position: str, timestamp: str):
        self.quantity = dc(quantity)
        self.order_id = order_id
        self.price = dc(price)
        self.position = dc(position)
        self.timestamp = str_to_dt(timestamp)


ExOrderType = TypeVar("ExOrderType", ExOrderV1, ExOrderV2, ExOrderV3, covariant=True)


def resolve_model(version: str,
                  class_type: Union[TradeType, QuoteType, ChangeType, TradeType, SummaryType, OrderSentType,
                                    OrderMarketType, OrderLimitType, OrderStopType, OrderStopLimitType,
                                    OrderTrailingStopType, OrderTwapType, OrderIcebergType]):
    classes = list(filter(lambda x: f"{class_type.__name__[:-4]}V{version.split('.')[0]}" == x.__name__,
                          class_type.__constraints__))  # type: List[Serializable]
    if len(classes) > 1:
        raise Exception("Unexpected resolution!")
    else:
        return classes[0]


def resolve_symbol(symbol: Union[str, SymbolType, Iterable[str], Iterable[SymbolType]]) -> Optional[str]:
    if isinstance(symbol, SymbolV3):
        return urlencode(symbol.symbol_id, safe="")
    elif isinstance(symbol, (SymbolV1, SymbolV2)):
        return urlencode(symbol.id_, safe="")
    elif isinstance(symbol, Iterable) and not isinstance(symbol, str):
        return ",".join([resolve_symbol(x) for x in symbol])
    elif symbol:
        return urlencode(symbol, safe="")
    else:
        return symbol
