#!/usr/bin/env python3.7
# -*- coding: utf-8 -*-

import logging
from datetime import datetime, timezone
from json import JSONDecodeError
from queue import Queue, Empty
from threading import Thread, Event
from time import sleep
from typing import Any, Callable, Dict, Iterable, Optional, List, Union
from urllib.parse import quote as urlencode

import backoff
import jwt
import requests
from requests import exceptions, adapters
from requests.auth import AuthBase, HTTPBasicAuth

from src.models.http_api_models import AuthMethods, CandleDurations, ChangeType, Crossrate, DataType, Exchange
from src.models.http_api_models import ExOrderType, FeedLevel, Group, InstrumentType, ModifyAction, OHLCQuotes
from src.models.http_api_models import OHLCTrades, Ordering, OrderType, OrderV1, OrderV2, OrderV3, OrderSentType
from src.models.http_api_models import QuoteType, Reject, Schedule, Scopes, SummaryType, SymbolType
from src.models.http_api_models import SymbolSpecification, TradeType, TransactionType, UserAccount
from src.models.http_api_models import resolve_model, resolve_symbol
from src.models.json_to_obj import Numeric, SerializableType
from src.models.json_to_obj import dt_to_str, dt_to_timestamp, extract_to_model, opt_int, timestamp_to_dt

try:
    import ujson as json
except ImportError:
    import json


versions = ("1.0", "2.0", "3.0")
current_api = "2.0"


class JWTAuth(Thread, AuthBase):
    def __init__(self, appid: str, client_id: str, shared_key: str, ttl: Numeric, scopes: Iterable[Scopes]):
        self.appid = appid
        self.client_id = client_id
        self.shared_key = shared_key
        self.ttl = int(ttl)
        self.scopes = scopes
        self.token = None
        super().__init__(daemon=True)
        self.start()

    def make_token(self) -> str:
        now = int(datetime.now(tz=timezone.utc).timestamp())
        token = jwt.encode(payload={"iss": self.client_id,
                                    "sub": self.appid,
                                    "iat": now,
                                    "exp": now + self.ttl,
                                    "aud": [x.value for x in self.scopes]},
                           key=self.shared_key,
                           algorithm="HS256").decode("ascii")
        return token

    def run(self):
        while True:
            self.token = self.make_token()
            sleep(self.ttl)

    def __repr__(self):
        return f"Bearer {self.token}"

    def __call__(self, r):
        r.headers["Authorization"] = f"Bearer {self.token}"
        return r


def conerror(exc):
    exception = []
    print(exc, type(exc))
    return any([isinstance(exc, x) for x in exception])


class HTTPApiStreaming(Thread):
    def __init__(self, auth: AuthBase, api: str, handler: str, model: SerializableType,
                 params: Optional[Dict[str, Any]] = None, event_filter: Optional[str] = None,
                 chunk_size: Optional[int] = 1, session: Optional[requests.Session] = None,
                 logger: Optional[logging.Logger] = None) -> None:
        self.auth = auth
        self.api = api
        self.handler = handler
        self.chunk_size = chunk_size
        self.params = params
        self.model = model
        self.session = session or requests.Session()
        self.session.mount(api, adapters.HTTPAdapter())
        self.is_finished = Event()
        self.queue = Queue(maxsize=0)
        self.event_filter = event_filter
        super().__init__(daemon=True)
        self.logger = logger or logging.Logger(name=self.name, level=logging.ERROR)
        self.start()

    def run(self) -> None:
        headers = {"Accept": "application/x-json-stream", "Accept-Encoding": "gzip"}
        while not self.is_finished.is_set():
            for message in self.session.get(self.api + self.handler, headers=headers, stream=True,
                                            params=self.params, timeout=60,
                                            auth=self.auth).iter_lines(chunk_size=self.chunk_size):
                if self.is_finished.is_set():
                    break
                try:
                    mes = json.loads(message.decode())
                    if self.event_filter:
                        if self.event_filter == mes.get('event'):
                            self.queue.put(self.model.from_json(mes[self.event_filter]))
                            continue
                    else:
                        self.queue.put(self.model.from_json(mes))
                except RuntimeError:
                    self.logger.error(f"Unable to parse message {message}")

    def get(self, block: bool = False, timeout: int = 30, eraise: bool = False) -> Optional[SerializableType]:
        try:
            return self.queue.get(block=block, timeout=timeout)
        except Empty:
            if not eraise:
                return None
            else:
                raise Empty

    def stop(self) -> None:
        self.is_finished.set()
        self.join()


class HTTPApi:
    def __init__(self, auth: AuthMethods, appid: str, acckey: Optional[str] = None, clientid: Optional[str] = None,
                 sharedkey: Optional[str] = None, ttl: Optional[int] = None, scopes: Iterable[Scopes] = tuple(Scopes),
                 url: str = "https://api-live.exante.eu", version: str = current_api,
                 logger: Optional[logging.Logger] = None) -> None:
        """
        :param auth: auth - basic or jwt. Auth method
        :param appid: ApplicationId
        :param acckey: [Basic] AccessKey
        :param clientid: [JWT] ClientId
        :param sharedkey: [JWT] Shared Key for signing
        :param ttl: [JWT] token time to live in seconds, default is 1 hour
        :param scopes: [JWT] scopes token accessible to, reffer to specs, default is full
        :param url: url to connect to
        :param version: default API version, used if not overriden in call
        """
        if version in versions:
            self.version = version
        else:
            raise ValueError(f"Version should be one of {versions}")
        if auth == AuthMethods.BASIC:
            if appid and acckey:
                self.auth = HTTPBasicAuth(appid, acckey)
            else:
                raise ValueError("applicationId and accountKey must be provided for basic authentification")
        elif auth == AuthMethods.JWT:
            if appid and clientid and sharedkey and ttl and scopes:
                self.auth = JWTAuth(appid, clientid, sharedkey, ttl, scopes)
            else:
                raise ValueError("applicationId, clientId, sharedKey, token TTL and list of scopes must be provided "
                                 "for JWT authentification")
        else:
            raise Exception("Incorrect auth method {} specified".format(auth))

        self.url = url
        self.api_md = "%s/md/{}" % self.url
        self.api_trade = "%s/trade/{}" % self.url
        self.session = requests.Session()
        self.session.mount(self.url, adapters.HTTPAdapter())
        self.logger = logger or logging.Logger(name="HTTPApi", level=logging.ERROR)

    @backoff.on_exception(backoff.constant, (exceptions.ConnectionError, exceptions.Timeout,
                                             exceptions.ConnectTimeout, exceptions.ReadTimeout),
                          max_tries=5, max_time=60)
    def __request(self, method: Callable, api: str, handler: str, version: str, params: Optional[Dict[str, Any]] = None,
                  jdata: Optional[Dict[str, Any]] = None) -> requests.Response:
        """
        wrapper for requests
        :param method: self.session.get or self.session.post
        :param api: self.api_feed or self.api_trade addresses
        :param handler: API handle
        :param params: additional params
        :param jdata: data to be passed as JSON
        :return: requests response object
        """
        headers = {"Accept": "application/json", "Accept-Encoding": "gzip"}
        self.logger.debug(f"received url {api.format(version) + handler}")
        self.logger.debug(f"passed headers: {headers}")
        if params:
            self.logger.debug(f"passed params: {params}")
        if jdata:
            self.logger.debug(f"passed json data: {jdata}")
        return method(api.format(version) + handler, params=params, headers=headers, json=jdata, auth=self.auth)

    @staticmethod
    def _mk_account(account: Optional[str], version: str = None) -> Dict[str, Optional[str]]:
        if version == "3.0":
            return {"accountId": account}
        else:
            return {"account": account}

    @staticmethod
    def _mk_symbol(symbol: str, version: str = None) -> Dict[str, Optional[str]]:
        if version == "3.0":
            return {"symbolId": resolve_symbol(symbol)}
        else:
            return {"instrument": resolve_symbol(symbol)}

    def _get(self, api: str, handler: str, version: str,
             params: Optional[Dict[str, Any]] = None) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        r = self.__request(method=self.session.get, api=api, handler=handler, version=version or self.version,
                           params=params)
        try:
            return r.json()
        except JSONDecodeError:
            logging.warning(f"Unable to parse JSON from {r.text}")
            return {}

    def _post(self, api: str, handler: str, version: str, params: Optional[Dict[str, Any]] = None,
              jdata: Optional[Dict[str, Any]] = None) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        r = self.__request(method=self.session.post, api=api, handler=handler, version=version or self.version,
                           params=params, jdata=jdata)
        try:
            return r.json()
        except JSONDecodeError:
            logging.warning(f"Unable to parse JSON from {r.text}")
            return {}

    def get_user_accounts(self, version: str = None) -> UserAccount:
        """
        Return the list of user accounts and their statuses
        :param version: any version
        :return: UserAccount object
        """
        return extract_to_model(self._get(self.api_md, "/accounts", version), UserAccount)

    def get_changes(self, symbolid: Union[str, Iterable[str], None] = None, version: str = None) \
            -> List[ChangeType]:
        """
        Return the list of daily changes for all or requested instruments
        :param symbolid: single string or list of instruments
        :param version: any version
        :return: List of ChangeType objects of specified versions
        """
        model = resolve_model(version or self.version, ChangeType)
        if symbolid:
            return extract_to_model(
                self._get(self.api_md, "/change/{}".format(urlencode(symbolid, safe="")
                                                           if isinstance(symbolid, str) else
                                                           urlencode(",".join(symbolid), safe=",")), version), model)
        else:
            return extract_to_model(self._get(self.api_md, "/change", version), model)

    def get_currencies(self, version: str = None) -> List[str]:
        """
        Return the list of available currencies
        :param version: all versions
        :return: List of currencies
        """
        return self._get(self.api_md, "/crossrates", version).get("currencies", [])

    def get_crossrates(self, fr: str = "EUR", to: str = "USD", version: str = None) -> Crossrate:
        """
        Return the crossrate from one currency to another
        :param fr: pair from
        :param to: pair to
        :param version: all versions
        :return:
        """
        return Crossrate.from_json(self._get(self.api_md, f"/crossrates/{fr.upper()}/{to.upper()}", version))

    def get_exchanges(self, version: str = None) -> List[Exchange]:
        """
        Return list of exchanges
        :param version: any version
        :return: List of Exchanges
        """
        return extract_to_model(self._get(self.api_md, "/exchanges", version), Exchange)

    def get_symbols_by_exch(self, exchange: Union[str, Exchange], version: str = None) -> List[SymbolType]:
        """
        Return the requested exchange financial instruments
        :param exchange: exchange
        :param version: all versions
        :return: List of Symbols
        """
        model = resolve_model(version or self.version, SymbolType)
        return extract_to_model(
            self._get(self.api_md, "/exchanges/{}".format(
                exchange.id_ if isinstance(exchange, Exchange) else exchange), version), model)

    def get_groups(self, version: str = None) -> List[Group]:
        """
        Return list of available instrument groups
        :param version: all versions
        :return: List of Groups
        """
        return extract_to_model(self._get(self.api_md, "/groups", version), Group)

    def get_symbols_by_gr(self, group: Union[str, Group], version: str = None) -> List[SymbolType]:
        """
        Return financial instruments which belong to specified group
        :param group: group string to Group object
        :param version: all versions
        :return: List of Symbols
        """
        model = resolve_model(version or self.version, SymbolType)
        return extract_to_model(
            self._get(self.api_md, "/groups/{}".format(group.group if isinstance(group, Group) else group), version),
            model)

    def get_nearest(self, group: Union[str, Group], version: str = None) -> SymbolType:
        """
        Return financial instrument which has the nearest expiration in the group
        :param group: group string to Group object
        :param version: 1.0 or 2.0
        :return: Symbol
        """
        if version not in ("1.0", "2.0"):
            raise NotImplemented(f"API not available in {version}")
        model = resolve_model(version or self.version, SymbolType)
        return model.from_json(
            self._get(self.api_md, "/groups/{}/nearest".format(group.group if isinstance(group, Group) else group),
                      version))

    def get_symbols(self, version: str = None) -> List[SymbolType]:
        """
        Return list of instruments available for authorized user
        :param version: all versions
        :return: List of Symbols
        """
        model = resolve_model(version or self.version, SymbolType)
        return extract_to_model(self._get(self.api_md, "/symbols", version), model)

    def get_symbol(self, symbol: str, version: str = None) -> SymbolType:
        """
        Return instrument available for authorized user
        :param symbol: symbolId
        :param version: all versions
        :return: Symbol
        """
        model = resolve_model(version or self.version, SymbolType)
        return model.from_json(self._get(self.api_md, f"/symbols/{symbol}", version))

    def get_symbol_schedule(self, symbol: Union[str, SymbolType], types: bool = False, version: str = None) -> Schedule:
        """
        Return financial schedule for requested instrument
        :param symbol: SymbolType or symbol string
        :param types: show order types in response
        :param version: all versions
        :return: Schedule
        """
        return Schedule.from_json(self._get(self.api_md, f"/symbols/{resolve_symbol(symbol)}/schedule", version,
                                            params={"types": str(types).lower()}))

    def get_symbol_spec(self, symbol: Union[str, SymbolType], version: str = None) -> SymbolSpecification:
        """
        Return additional parameters for requested instrument
        :param symbol: SymbolType or symbol string
        :param version: all versions
        :return: SymbolSpecification
        """
        return SymbolSpecification.from_json(self._get(self.api_md, f"/symbols/{resolve_symbol(symbol)}/specification",
                                                       version))

    def get_types(self, version: str = None) -> List[InstrumentType]:
        """
        Return list of known instrument types
        :param version: 1.0 or 2.0. reffer docs to see difference
        :return: List of InstrumentTypes
        """
        return [InstrumentType(x['id']) for x in self._get(self.api_md, "/types", version)]

    def get_symbol_by_type(self, sym_type: InstrumentType, version: str = None) -> List[SymbolType]:
        """
        Return financial instruments of the requrested type
        :param sym_type: InstrumentType Enum
        :param version: all versions
        :return: List of Symbols
        """
        model = resolve_model(version or self.version, SymbolType)
        return extract_to_model(self._get(self.api_md, f"/types/{sym_type.value}", version), model)

    def get_quote_stream(self, symbols: Union[str, SymbolType, Iterable[str], Iterable[SymbolType]],
                         level: FeedLevel = FeedLevel.BP, version: str = None) -> HTTPApiStreaming:
        """
        Return the life quote stream for the specified financial instruments
        :param symbols: single or List/Tuple/etc of Symbols
        :param level: Quote Type - FeedLevel enum: BP|BEST_PRICE for top book and MD|MARKET_DEPTH for full market
        :param version: all versions
        :return: HTTPApiStreaming instance thread
        """
        return HTTPApiStreaming(
            self.auth, self.api_md.format(version or self.version), f"/feed/{resolve_symbol(symbols)}",
            resolve_model(version or self.version, QuoteType), {"level": level.value}, logger=self.logger)

    def get_trade_stream(self, symbols: Union[str, SymbolType, Iterable[str], Iterable[SymbolType]],
                         version: str = None) -> HTTPApiStreaming:
        """
        Return the trades stream for the specified financial instruments
        :param symbols: single or List/Tuple/etc of Symbols
        :param version: 3.0 version
        :return: HTTPApiStreaming instance thread
        """
        if version != "3.0":
            raise NotImplemented(f"API not available in {version}")
        return HTTPApiStreaming(
            self.auth, self.api_md.format(version or self.version), f"/feed/trades/{resolve_symbol(symbols)}",
            resolve_model(version or self.version, TradeType), logger=self.logger)

    def get_last_quote(self, symbol: Union[str, Iterable[str], SymbolType, Iterable[SymbolType]],
                       level: FeedLevel = FeedLevel.BP, version: str = None) -> List[QuoteType]:
        """
        Return the last quote for the specified financial instrument
        :param symbol: symbol string or Symbol object
        :param level: Quote Type - FeedLevel enum: BP|BEST_PRICE for top book and MD|MARKET_DEPTH for full market
        :param version: all versions, MD level available since 2.0
        :return: List of Quotes
        """
        model = resolve_model(version or self.version, QuoteType)
        return extract_to_model(
            self._get(self.api_md, f"/feed/{resolve_symbol(symbol)}/last", version, {"level": level.value}), model)

    def get_ohlc(self, symbol: Union[str, SymbolType], duration: Union[int, CandleDurations],
                 agg_type: DataType = DataType.QUOTES, start: Optional[Union[Numeric, datetime]] = None,
                 end: Optional[Union[Numeric, datetime]] = None, limit: int = 60,
                 version: str = None) -> List[Union[OHLCQuotes, OHLCTrades]]:
        """
        Return the list of OHLC candles for the specified financial instrument and duration
        :param symbol: symbol string or Symbol object
        :param duration: aggregate intreval in seconds or one of CandleDurations Enum
        :param agg_type: DataType Enum
        :param start: starting timestamp(ms) or datetime object in UTC timezone
        :param end: ending timestamp(ms) or datetime object in UTC timezone
        :param limit: maximum candle amount retrieved. Can be reduced by server
        :param version: all versions
        :return: List of OHLC objects
        """
        s = resolve_symbol(symbol)
        params = {
            "size": limit,
            "type": agg_type.value,
            "from": dt_to_timestamp(start, True) if isinstance(start, datetime) else opt_int(start),
            "to": dt_to_timestamp(end, True) if isinstance(end, datetime) else opt_int(end)
        }
        return extract_to_model(
            self._get(self.api_md, f"/ohlc/{s}/{duration.value if isinstance(duration, CandleDurations) else duration}",
                      version, params), OHLCQuotes if agg_type == DataType.QUOTES else OHLCTrades)

    def get_ticks(self, symbol: Union[str, SymbolType], agg_type: DataType = DataType.QUOTES,
                  start: Optional[Union[Numeric, datetime]] = None,
                  end: Optional[Union[Numeric, datetime]] = None, limit: int = 1000,
                  version: str = None) -> List[Union[QuoteType, TradeType]]:
        """
        Return the list of ticks for the specified financial instrument
        :param symbol: symbol string or Symbol object
        :param agg_type: DataType Enum
        :param start: starting timestamp(ms) or datetime object in UTC timezone
        :param end: ending timestamp(ms) or datetime object in UTC timezone
        :param limit: maximum candle amount retrieved. Can be reduced by server
        :param version: available since 2.0
        :return: List of Quotes or Trades
        """
        if agg_type == DataType.QUOTES:
            model = resolve_model(version or self.version, QuoteType)
        else:
            model = resolve_model(version or self.version, TradeType)
        params = {
            "size": limit,
            "type": agg_type.value,
            "from": dt_to_timestamp(start, True) if isinstance(start, datetime) else opt_int(start),
            "to": dt_to_timestamp(end, True) if isinstance(end, datetime) else opt_int(end)
        }
        return extract_to_model(
            self._get(self.api_md, f"/ticks/{resolve_symbol(symbol)}", version, params), model)

    def get_account_summary(self, account: str, currency: str = "EUR", date: Union[str, datetime] = None,
                            version: str = None) -> SummaryType:
        """
        Return the summary for the specified account
        :param account: accountId
        :param currency: on of NAV currency, default is EUR
        :param date: historical account summary, datetime or YYYY-MM-DD string
        :param version: all versions
        :return: AccountSummary
        """
        model = resolve_model(version or self.version, SummaryType)
        if date:
            if isinstance(date, datetime):
                d = dt_to_str(date, "%Y-%m-%d")
            else:
                d = date
            return model.from_json(self._get(self.api_md, f"/summary/{account}/{d}/{currency.upper()}", version))
        else:
            return model.from_json(self._get(self.api_md, f"/summary/{account}/{currency.upper()}", version))

    def get_transactions(self, account: Optional[str] = None, uuid: Optional[str] = None,
                         symbol: Union[str, SymbolType, None] = None,
                         asset: Optional[str] = None, op_type: Union[str, Iterable[str], None] = None,
                         order_id: Optional[str] = None, order_pos: Optional[int] = None, offset: Numeric = None,
                         limit: Numeric = 10, order: Ordering = Ordering.ASC, fr: Union[int, datetime] = None,
                         to: Union[int, datetime] = None,
                         version: str = None) -> List[TransactionType]:
        """
        Return the list of transactions with the specified filter
        :param account: filter transactions by accountId [single account]
        :param uuid: filter transactions by UUID [single uuid]
        :param symbol: filter transactions by symbol [single symol]
        :param asset: filter transactions by asset [single asset]
        :param op_type: filter transactions by operationType - note, this list is subject to change.
        It's not recommended to Enum this
        :param order_id: filter transactions by order UUID [single order]
        :param order_pos: filter transactions by order position
        :param offset: offset of retrived transaction list. Can be used for pagination
        :param limit: limit number of retrieved transactions. Can be maxed on server side
        :param order: Ordering enum: ASC or DESC ordering
        :param fr: retrive transactions from date - timestamp in ms or datetime (UTC timezone)
        :param to: retrive transactions till date - timestamp in ms or datetime (UTC timezone)
        :param version: all version
        :return: List of Transactions
        """
        params = {
            "uuid": uuid,
            "accountId": account,
            "symbolId": resolve_symbol(symbol),
            "asset": asset,
            "offset": opt_int(offset),
            "limit": opt_int(limit),
            "order": order.value,
            "orderId": order_id,
            "orderPos": opt_int(order_pos),
            "fromDate": dt_to_str(fr, '%Y-%m-%d') if isinstance(fr, datetime) else dt_to_str(timestamp_to_dt(fr), '%Y-%m-%d'),
            "toDate": dt_to_str(to, '%Y-%m-%d') if isinstance(to, datetime) else dt_to_str(timestamp_to_dt(to), '%Y-%m-%d')
            # full datetime filter doesn't work
            # "fromDate": dt_to_str(fr) if isinstance(fr, datetime) else dt_to_str(timestamp_to_dt(fr)),
            # "toDate": dt_to_str(to) if isinstance(to, datetime) else dt_to_str(timestamp_to_dt(to))
        }
        if hasattr(op_type, '__iter__') and not isinstance(op_type, str):
            params.update({"operationType": ",".join(op_type)})
        else:
            params.update({"operationType": op_type})
        model = resolve_model(version or self.version, TransactionType)
        return extract_to_model(self._get(self.api_md, "/transactions", version, params), model)

    def place_order(self, order: OrderSentType, version: str = None) -> List[Union[OrderType, Reject]]:
        """
        Place new trading order
        :param order: Order Model
        :param version: all versions, check the differences in naming models
        :return: List of Orders
        """
        model = resolve_model(version or self.version, OrderType)
        r = self._post(self.api_trade, "/orders", version, jdata=order.to_json())
        try:
            if version == "1.0":
                return [model.from_json(r)]
            else:
                return extract_to_model(r, model)
        except RuntimeError:
            if version == "1.0":
                return [Reject.from_json(r)]
            else:
                return extract_to_model(r, Reject)

    def get_orders(self, account: Optional[str] = None, limit: Numeric = 1000, fr: Union[int, datetime] = None,
                   to: Union[int, datetime] = None, version: str = None) -> List[OrderType]:
        """
        Return the list of historical orders
        :param account: account permissioned to request
        :param limit: max size of response
        :param fr: retrieve orders placed from date - timestamp in ms or datetime (UTC timezone)
        :param to: retrieve order placed before date - timestamp in ms or datetime (UTC timezone)
        :param version: all versions
        :return: List of Orders
        """
        model = resolve_model(version or self.version, OrderType)
        params = {
            "limit": opt_int(limit),
            "from": dt_to_str(fr) if isinstance(fr, datetime) else dt_to_str(timestamp_to_dt(fr)),
            "to": dt_to_str(to) if isinstance(to, datetime) else dt_to_str(timestamp_to_dt(to))
        }
        if account:
            params.update(HTTPApi._mk_account(account, version or self.version))
        return extract_to_model(self._get(self.api_trade, "/orders", version, params), model)

    def get_active_orders(self, account: Optional[str] = None, limit: Numeric = 10,
                          symbol: Union[str, SymbolType, None] = None, version: str = None) -> List[OrderType]:
        """
        Return the list of active trading orders
        :param account: account permissioned to request
        :param limit: max size of response
        :param symbol: filter orders by symbol
        :param version: all versions
        :return: List of Orders
        """
        params = {
            "limit": opt_int(limit)
        }
        params.update(HTTPApi._mk_account(account, version))
        params.update(HTTPApi._mk_symbol(symbol, version))
        model = resolve_model(version or self.version, OrderType)
        return extract_to_model(self._get(self.api_trade, "/orders/active", version, params), model)

    def get_order(self, orderid: Union[str, OrderType], version: str = None) -> OrderType:
        """
        Return the order with specified identifier
        :param orderid: OrderId via string or Order object
        :param version: all versions
        :return: Order
        """
        model = resolve_model(version or self.version, OrderType)
        if isinstance(orderid, OrderV3):
            id_ = orderid.order_id
        elif isinstance(orderid, (OrderV2, OrderV1)):
            id_ = orderid.id_
        else:
            id_ = orderid
        return model.from_json(self._get(self.api_trade, f"/orders/{id_}", version))

    def _modify_order(self, orderid: Union[str, OrderType], action: ModifyAction, version: str = None,
                      **kwargs) -> Union[Reject, OrderType]:
        """
        Replace or cancel trading order
        :param orderid: orderId
        :param action: replace or cancel
        :param version: 1.0 or 2.0. reffer docs to see difference
        :param kwargs: quantity and/or limitPrice for limit or stop-limit, stopPrice for stop or stop-limit order
        :return: dict
        """
        model = resolve_model(version or self.version, OrderType)
        data = {
            "action": action.value
        }
        if action == ModifyAction.REPLACE:
            data["parameters"] = {}
            if kwargs:
                for k, v in kwargs.items():
                    if v is not None:
                        data["parameters"][k] = str(v)
        r = self._post(self.api_trade, f"/orders/{orderid}", version, jdata=data)
        try:
            return model.from_json(r)
        except (TypeError, RuntimeError):
            return extract_to_model(r, Reject)[0]

    def cancel_order(self, orderid: Union[str, OrderType], version: str = None) -> Union[Reject, OrderType]:
        """
        Cancel trading order
        :param orderid: orderId
        :param version: all versions
        :return: OrderType or Reject
        """
        return self._modify_order(orderid, ModifyAction.CANCEL, version)

    def replace_order(self, orderid: Union[str, OrderType], quantity: Numeric, limit_price: Optional[Numeric] = None,
                      stop_price: Optional[Numeric] = None, price_distance: Optional[Numeric] = None,
                      version: str = None) -> Union[Reject, OrderType]:
        """
        Replace trading order
        :param orderid: orderId
        :param quantity: original or changed quantity for order
        :param limit_price: applied for Limit, StopLimit and Iceberg type of orders
        :param stop_price: applied for Stop and StopLimit type of orders
        :param price_distance: applied for TrailingStop type of orders
        :param version: all versions
        :return: OrderType or List of Rejects
        """
        return self._modify_order(orderid, ModifyAction.REPLACE, version, quantity=quantity, limitPrice=limit_price,
                                  stopPrice=stop_price, priceDistance=price_distance)

    def get_orders_stream(self, version: str = None) -> HTTPApiStreaming:
        """
        Return the life quote stream for the specified financial instruments
        :param version: all versions
        :return: HTTPApiStreaming instance thread
        """
        return HTTPApiStreaming(
            self.auth, self.api_trade.format(version or self.version), f"/stream/orders",
            resolve_model(version or self.version, OrderType), event_filter="order", logger=self.logger)

    def get_exec_orders_stream(self, version: str = None) -> HTTPApiStreaming:
        """
        Return the life quote stream for the specified financial instruments
        :param version: all versions
        :return: HTTPApiStreaming instance thread
        """
        return HTTPApiStreaming(
            self.auth, self.api_trade.format(version or self.version), f"/stream/trades",
            resolve_model(version or self.version, ExOrderType),
            event_filter="trade" if (version == "3.0") or (self.version == "3.0") else None, logger=self.logger)
