#!/usr/bin/env python3.7
# -*- coding: utf-8 -*-

import logging
import orjson as json
from datetime import datetime, timezone
from queue import Queue, Empty
from threading import Thread, Event
from time import sleep
from typing import Any, Callable, Dict, Iterable, Optional, List, Type, Union
from urllib.parse import quote as urlencode

import backoff
import jwt
import requests
from requests import exceptions, adapters
from requests.auth import AuthBase, HTTPBasicAuth

from xnt.models.http_api_models import AuthMethods, CandleDurations, ChangeType, Crossrate, DataType, Exchange
from xnt.models.http_api_models import ExOrderType, FeedLevel, Group, InstrumentType, ModifyAction, OHLCQuotes
from xnt.models.http_api_models import OHLCTrades, Ordering, OrderType, OrderV1, OrderV2, OrderV3, OrderSentType
from xnt.models.http_api_models import QuoteType, Reject, Schedule, Scopes, SummaryType, SymbolType
from xnt.models.http_api_models import SymbolSpecification, TradeType, TransactionType, UserAccount
from xnt.models.http_api_models import resolve_model, resolve_symbol
from xnt.models.http_jto import Numeric, SerializableType
from xnt.models.http_jto import attr_or, extract_to_model, opt_int, dt_to_str, dt_to_timestamp, timestamp_to_dt

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
    def __init__(self, auth: AuthBase, api: str, handler: str, model: Type[SerializableType],
                 params: Optional[Dict[str, Any]] = None, event_filter: Optional[str] = None,
                 chunk_size: Optional[int] = 1, session: Optional[requests.Session] = None,
                 logger: Optional[logging.Logger] = None, log_level: Optional[int] = logging.ERROR,
                 backup_model: Optional[Type[SerializableType]] = None,
                 debug_raise_model_exceptions: bool = False) -> None:
        self.auth = auth
        self.api = api
        self.handler = handler
        self.chunk_size = chunk_size
        self.params = params
        self.model = model
        self.backup_model = backup_model
        self.session = session or requests.Session()
        self.session.mount(api, adapters.HTTPAdapter())
        self.is_finished = Event()
        self.queue = Queue(maxsize=0)
        self.event_filter = event_filter
        self._eraise = debug_raise_model_exceptions
        super().__init__(daemon=True)
        self.logger = logger or logging.Logger(name=self.name, level=log_level)
        self.start()

    def run(self) -> None:
        headers = {"Accept": "application/x-json-stream", "Accept-Encoding": "gzip"}
        mes: Dict = {}
        while not self.is_finished.is_set():
            for message in self.session.get(self.api + self.handler, headers=headers, stream=True,
                                            params=self.params, timeout=60,
                                            auth=self.auth).iter_lines(chunk_size=self.chunk_size):
                if self.is_finished.is_set():
                    break
                try:
                    mes = json.loads(message.decode())
                    if mes.get("event") == "heartbeat":
                        continue
                    elif self.event_filter and self.event_filter == mes.get("event"):
                        parsed_message = extract_to_model(mes[self.event_filter], self.model, self._eraise,
                                                          backup_obj=self.backup_model)
                    else:
                        parsed_message = extract_to_model(mes, self.model, self._eraise, backup_obj=self.backup_model)
                    if parsed_message is not None:
                        self.queue.put(parsed_message)
                except json.JSONDecodeError as exc:
                    if self._eraise:
                        raise exc
                    else:
                        self.logger.error("Unable to parse message as JSON: %s" % message)
                        continue
                except RuntimeError as exc:
                    if self._eraise:
                        raise exc
                    else:
                        self.logger.error("%s found at %s: '%s'" % (exc.__class__, mes, exc.args[0]))
                        continue

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
                 logger: Optional[logging.Logger] = None, log_level: Optional[int] = logging.ERROR,
                 debug_raise_model_exceptions: bool = False) -> None:
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
        :param logger: external logging.Logger object
        :param log_level: log_level int code (50 for ERROR) or logging.LOG_LEVEL const
        :param debug_raise_model_exceptions: raise RuntimeError on failures on model serializing
        (default will return None and warning)
        Usefull on API changes, testing or forking
        """
        if version in versions:
            self.version = version
        else:
            raise ValueError(f"Version should be one of {versions}")
        self._eraise = debug_raise_model_exceptions
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
        self.logger = logger or logging.getLogger("HTTPApi")
        self.logger.setLevel(log_level)

    @backoff.on_exception(backoff.constant, (exceptions.ConnectionError, exceptions.Timeout,
                                             exceptions.ConnectTimeout, exceptions.ReadTimeout),
                          max_tries=5, max_time=60)
    def __request(self, method: Callable, api: str, handler: str, version: str, params: Optional[Dict[str, Any]] = None,
                  jdata: Optional[Dict[str, Any]] = None,
                  secret_jdata: Optional[Dict[str, Any]] = None) -> requests.Response:
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
        self.logger.debug("received url %s" % api.format(version) + handler)
        self.logger.debug("passed headers: %s" % headers)
        if params:
            self.logger.debug("passed params: %s" % params)
        if jdata:
            self.logger.debug("passed json data: %s" % jdata)
        if secret_jdata and jdata:
            jdata.update(secret_jdata)
        elif secret_jdata:
            jdata = secret_jdata
        r = method(api.format(version) + handler, params=params, headers=headers, json=jdata, auth=self.auth)
        if r.status_code > 204:
            self.logger.error("Got [%d] response" % r.status_code)
        else:
            self.logger.info("Got [%d] response" % r.status_code)
        self.logger.debug(r.text)
        return r

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

    def _wrap(self, r: requests.Response, non_json_resp: bool) -> Union[None, str, List, Dict]:
        """
        simple wrapper to catch JSON parser errors
        """
        try:
            return json.loads(r.text)
        except json.JSONDecodeError:
            if not non_json_resp:
                self.logger.warning("Unable to parse JSON from %s" % r.text)

    def _get(self, api: str, handler: str, version: str, params: Optional[Dict[str, Any]] = None,
             non_json_resp: bool = False) -> Union[None, Dict[str, Any], List[Dict[str, Any]]]:
        return self._wrap(self.__request(method=self.session.get, api=api, handler=handler,
                                         version=version or self.version, params=params), non_json_resp)

    def _post(self, api: str, handler: str, version: str, params: Optional[Dict[str, Any]] = None,
              jdata: Optional[Dict[str, Any]] = None, secret_jdata: Optional[Dict[str, Any]] = None,
              non_json_resp: bool = False) -> Union[None, str, Dict[str, Any], List[Dict[str, Any]]]:
        return self._wrap(self.__request(method=self.session.post, api=api, handler=handler,
                                         version=version or self.version, params=params, jdata=jdata,
                                         secret_jdata=secret_jdata), non_json_resp)

    def _delete(self, api: str, handler: str, version: str, params: Optional[Dict[str, Any]] = None,
                non_json_resp: bool = False) -> Union[None, str, Dict[str, Any], List[Dict[str, Any]]]:
        return self._wrap(self.__request(method=self.session.delete, api=api, handler=handler,
                                         version=version or self.version, params=params), non_json_resp)

    def get_user_accounts(self, version: str = None) -> Optional[List[UserAccount]]:
        """
        Return the list of user accounts and their statuses
        :param version: any version
        :return: UserAccount object
        """
        return extract_to_model(self._get(self.api_md, "/accounts", version), UserAccount, self._eraise)

    def get_changes(self, symbolid: Union[str, Iterable[str], None] = None, version: str = None) \
            -> Optional[List[ChangeType]]:
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
                                                           urlencode(",".join(symbolid), safe=",")), version),
                model, self._eraise)
        else:
            return extract_to_model(self._get(self.api_md, "/change", version), model, self._eraise)

    def get_currencies(self, version: str = None) -> List[str]:
        """
        Return the list of available currencies
        :param version: all versions
        :return: List of currencies
        """
        return self._get(self.api_md, "/crossrates", version).get("currencies", [])

    def get_crossrates(self, fr: str = "EUR", to: str = "USD", version: str = None) -> Optional[Crossrate]:
        """
        Return the crossrate from one currency to another
        :param fr: pair from
        :param to: pair to
        :param version: all versions
        :return:
        """
        return extract_to_model(self._get(self.api_md, f"/crossrates/{fr.upper()}/{to.upper()}", version),
                                Crossrate, self._eraise)

    def get_exchanges(self, version: str = None) -> Optional[List[Exchange]]:
        """
        Return list of exchanges
        :param version: any version
        :return: List of Exchanges
        """
        return extract_to_model(self._get(self.api_md, "/exchanges", version), Exchange, self._eraise)

    def get_symbols_by_exch(self, exchange: Union[str, Exchange], version: str = None) -> Optional[List[SymbolType]]:
        """
        Return the requested exchange financial instruments
        :param exchange: exchange
        :param version: all versions
        :return: List of Symbols
        """
        model = resolve_model(version or self.version, SymbolType)
        return extract_to_model(
            self._get(self.api_md, f"/exchanges/{attr_or(exchange, 'id_')}", version), model, self._eraise)

    def get_groups(self, version: str = None) -> Optional[List[Group]]:
        """
        Return list of available instrument groups
        :param version: all versions
        :return: List of Groups
        """
        return extract_to_model(self._get(self.api_md, "/groups", version), Group, self._eraise)

    def get_symbols_by_gr(self, group: Union[str, Group], version: str = None) -> Optional[List[SymbolType]]:
        """
        Return financial instruments which belong to specified group
        :param group: group string to Group object
        :param version: all versions
        :return: List of Symbols
        """
        model = resolve_model(version or self.version, SymbolType)
        return extract_to_model(self._get(self.api_md, f"/groups/{attr_or(group, 'group')}", version),
                                model, self._eraise)

    def get_nearest(self, group: Union[str, Group], version: str = None) -> Optional[SymbolType]:
        """
        Return financial instrument which has the nearest expiration in the group
        :param group: group string to Group object
        :param version: 1.0 or 2.0
        :return: Symbol
        """
        if (version or self.version) not in ("1.0", "2.0",):
            raise NotImplementedError(f"API not available in {version or self.version}")
        model = resolve_model(version or self.version, SymbolType)
        return extract_to_model(self._get(self.api_md, f"/groups/{attr_or(group, 'group')}/nearest", version),
                                model, self._eraise)

    def get_symbols(self, version: str = None) -> Optional[List[SymbolType]]:
        """
        Return list of instruments available for authorized user
        :param version: all versions
        :return: List of Symbols
        """
        model = resolve_model(version or self.version, SymbolType)
        return extract_to_model(self._get(self.api_md, "/symbols", version), model, self._eraise)

    def get_symbol(self, symbol: str, version: str = None) -> Optional[SymbolType]:
        """
        Return instrument available for authorized user
        :param symbol: symbolId
        :param version: all versions
        :return: Symbol
        """
        model = resolve_model(version or self.version, SymbolType)
        return extract_to_model(self._get(self.api_md, f"/symbols/{symbol}", version), model, self._eraise)

    def get_symbol_schedule(self, symbol: Union[str, SymbolType], types: bool = False,
                            version: str = None) -> Optional[Schedule]:
        """
        Return financial schedule for requested instrument
        :param symbol: SymbolType or symbol string
        :param types: show order types in response
        :param version: all versions
        :return: Schedule
        """
        return extract_to_model(self._get(self.api_md, f"/symbols/{resolve_symbol(symbol)}/schedule", version,
                                          params={"types": str(types).lower()}), Schedule, self._eraise)

    def get_symbol_spec(self, symbol: Union[str, SymbolType], version: str = None) -> Optional[SymbolSpecification]:
        """
        Return additional parameters for requested instrument
        :param symbol: SymbolType or symbol string
        :param version: all versions
        :return: SymbolSpecification
        """
        return extract_to_model(self._get(self.api_md, f"/symbols/{resolve_symbol(symbol)}/specification", version),
                                SymbolSpecification, self._eraise)

    def get_types(self, version: str = None) -> List[InstrumentType]:
        """
        Return list of known instrument types
        :param version: all versions
        :return: List of InstrumentTypes
        """
        return [InstrumentType(x['id']) for x in self._get(self.api_md, "/types", version)]

    def get_symbol_by_type(self, sym_type: InstrumentType, version: str = None) -> Optional[List[SymbolType]]:
        """
        Return financial instruments of the requrested type
        :param sym_type: InstrumentType Enum
        :param version: all versions
        :return: List of Symbols
        """
        model = resolve_model(version or self.version, SymbolType)
        return extract_to_model(self._get(self.api_md, f"/types/{sym_type.value}", version), model, self._eraise)

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
            resolve_model(version or self.version, QuoteType), {"level": level.value}, logger=self.logger,
            log_level=self.logger.getEffectiveLevel(), debug_raise_model_exceptions=self._eraise)

    def get_trade_stream(self, symbols: Union[str, SymbolType, Iterable[str], Iterable[SymbolType]],
                         version: str = None) -> HTTPApiStreaming:
        """
        Return the trades stream for the specified financial instruments
        :param symbols: single or List/Tuple/etc of Symbols
        :param version: 3.0 version
        :return: HTTPApiStreaming instance thread
        """
        if (version or self.version) not in ("3.0",):
            raise NotImplementedError(f"API not available in {version or self.version}")
        return HTTPApiStreaming(
            self.auth, self.api_md.format(version or self.version), f"/feed/trades/{resolve_symbol(symbols)}",
            resolve_model(version or self.version, TradeType), logger=self.logger,
            log_level=self.logger.getEffectiveLevel(), debug_raise_model_exceptions=self._eraise)

    def get_last_quote(self, symbol: Union[str, Iterable[str], SymbolType, Iterable[SymbolType]],
                       level: FeedLevel = FeedLevel.BP, version: str = None) -> Optional[List[QuoteType]]:
        """
        Return the last quote for the specified financial instrument
        :param symbol: symbol string or Symbol object
        :param level: Quote Type - FeedLevel enum: BP|BEST_PRICE for top book and MD|MARKET_DEPTH for full market
        :param version: all versions, MD level available since 2.0
        :return: List of Quotes
        """
        model = resolve_model(version or self.version, QuoteType)
        return extract_to_model(
            self._get(self.api_md, f"/feed/{resolve_symbol(symbol)}/last", version, {"level": level.value}),
            model, self._eraise)

    def get_ohlc(self, symbol: Union[str, SymbolType], duration: Union[int, CandleDurations],
                 agg_type: DataType = DataType.QUOTES, start: Optional[Union[Numeric, datetime]] = None,
                 end: Optional[Union[Numeric, datetime]] = None, limit: int = 60,
                 version: str = None) -> Optional[List[Union[OHLCQuotes, OHLCTrades]]]:
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
            self._get(self.api_md, f"/ohlc/{s}/{attr_or(duration, 'value')}",
                      version, params), OHLCQuotes if agg_type == DataType.QUOTES else OHLCTrades, self._eraise)

    def get_ticks(self, symbol: Union[str, SymbolType], agg_type: DataType = DataType.QUOTES,
                  start: Optional[Union[Numeric, datetime]] = None,
                  end: Optional[Union[Numeric, datetime]] = None, limit: int = 1000,
                  version: str = None) -> Optional[List[Union[QuoteType, TradeType]]]:
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
            self._get(self.api_md, f"/ticks/{resolve_symbol(symbol)}", version, params), model, self._eraise)

    def get_account_summary(self, account: str, currency: str = "EUR", req_date: Union[str, datetime] = None,
                            version: str = None) -> Optional[SummaryType]:
        """
        Return the summary for the specified account
        :param account: accountId
        :param currency: on of NAV currency, default is EUR
        :param req_date: historical account summary, datetime or YYYY-MM-DD string
        :param version: all versions
        :return: AccountSummary
        """
        model = resolve_model(version or self.version, SummaryType)
        if req_date:
            if isinstance(req_date, datetime):
                d = dt_to_str(req_date, "%Y-%m-%d")
            else:
                d = req_date
            return extract_to_model(self._get(self.api_md, f"/summary/{account}/{d}/{currency.upper()}", version),
                                    model, self._eraise)
        else:
            return extract_to_model(self._get(self.api_md, f"/summary/{account}/{currency.upper()}", version),
                                    model, self._eraise)

    def get_transactions(self, account: Optional[str] = None, uuid: Optional[str] = None,
                         symbol: Union[str, SymbolType, None] = None,
                         asset: Optional[str] = None, op_type: Union[str, Iterable[str], None] = None,
                         order_id: Optional[str] = None, order_pos: Optional[int] = None, offset: Numeric = None,
                         limit: Numeric = 10, order: Ordering = Ordering.ASC, fr: Union[int, datetime] = None,
                         to: Union[int, datetime] = None,
                         version: str = None) -> Optional[List[TransactionType]]:
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
            "fromDate": dt_to_str(fr, '%Y-%m-%d') if isinstance(fr, datetime) else dt_to_str(timestamp_to_dt(fr),
                                                                                             '%Y-%m-%d'),
            "toDate": dt_to_str(to, '%Y-%m-%d') if isinstance(to, datetime) else dt_to_str(timestamp_to_dt(to),
                                                                                           '%Y-%m-%d')
            # full datetime filter doesn't work
            # "fromDate": dt_to_str(fr) if isinstance(fr, datetime) else dt_to_str(timestamp_to_dt(fr)),
            # "toDate": dt_to_str(to) if isinstance(to, datetime) else dt_to_str(timestamp_to_dt(to))
        }
        if hasattr(op_type, '__iter__') and not isinstance(op_type, str):
            params.update({"operationType": ",".join(op_type)})
        else:
            params.update({"operationType": op_type})
        model = resolve_model(version or self.version, TransactionType)
        return extract_to_model(self._get(self.api_md, "/transactions", version, params), model, self._eraise)

    def place_order(self, order: OrderSentType, version: str = None) -> Optional[List[Union[OrderType, Reject]]]:
        """
        Place new trading order
        :param order: Order Model
        :param version: all versions, check the differences in naming models
        :return: List of Orders
        """
        model = resolve_model(version or self.version, OrderType)
        r = self._post(self.api_trade, "/orders", version, jdata=order.to_json())
        if version == "1.0":
            return [extract_to_model(r, model, self._eraise, backup_obj=Reject)]
        else:
            return extract_to_model(r, model, self._eraise, backup_obj=Reject)

    def get_orders(self, account: Optional[str] = None, limit: Numeric = 1000, fr: Union[int, datetime] = None,
                   to: Union[int, datetime] = None, version: str = None) -> Optional[List[OrderType]]:
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
        return extract_to_model(self._get(self.api_trade, "/orders", version, params), model, self._eraise)

    def get_active_orders(self, account: Optional[str] = None, limit: Numeric = 10,
                          symbol: Union[str, SymbolType, None] = None,
                          version: str = None) -> Optional[List[OrderType]]:
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
        return extract_to_model(self._get(self.api_trade, "/orders/active", version, params),
                                model, self._eraise)

    def get_order(self, orderid: Union[str, OrderType], version: str = None) -> Optional[OrderType]:
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
        return extract_to_model(self._get(self.api_trade, f"/orders/{id_}", version), model, self._eraise)

    def _modify_order(self, orderid: Union[str, OrderType], action: ModifyAction, version: str = None,
                      **kwargs) -> Union[None, Reject, OrderType]:
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
        return extract_to_model(r, model, self._eraise, backup_obj=Reject)

    def cancel_order(self, orderid: Union[str, OrderType], version: str = None) -> Union[None, Reject, OrderType]:
        """
        Cancel trading order
        :param orderid: orderId
        :param version: all versions
        :return: OrderType or Reject
        """
        return self._modify_order(orderid, ModifyAction.CANCEL, version)

    def replace_order(self, orderid: Union[str, OrderType], quantity: Numeric, limit_price: Optional[Numeric] = None,
                      stop_price: Optional[Numeric] = None, price_distance: Optional[Numeric] = None,
                      version: str = None) -> Union[None, Reject, OrderType]:
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
            self.auth, self.api_trade.format(version or self.version), "/stream/orders",
            resolve_model(version or self.version, OrderType), event_filter="order", logger=self.logger,
            log_level=self.logger.getEffectiveLevel(), debug_raise_model_exceptions=self._eraise)

    def get_exec_orders_stream(self, version: str = None) -> HTTPApiStreaming:
        """
        Return the life quote stream for the specified financial instruments
        :param version: all versions
        :return: HTTPApiStreaming instance thread
        """
        return HTTPApiStreaming(
            self.auth, self.api_trade.format(version or self.version), "/stream/trades",
            resolve_model(version or self.version, ExOrderType),
            event_filter="trade" if (version or self.version) == "3.0" else None, logger=self.logger,
            log_level=self.logger.getEffectiveLevel(), debug_raise_model_exceptions=self._eraise)
