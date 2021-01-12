#!/usr/bin/env python3.7
# -*- coding: utf-8 -*-
import pytest
import requests_mock
import responses

from deepdiff import DeepDiff

from src.http_api import HTTPApi, current_api
from src.models.http_api_models import AuthMethods, CandleDurations, ChangeType, Crossrate, DataType, Durations
from src.models.http_api_models import Exchange, ExOrderType, FeedLevel, Group, InstrumentType, OHLCQuotes
from src.models.http_api_models import OHLCTrades, Ordering, OrderType, OrderLimitType, QuoteType, Reject
from src.models.http_api_models import Schedule, Side, SummaryType, SymbolType, SymbolSpecification, SymbolV1
from src.models.http_api_models import SymbolV2, SymbolV3, TradeType, TradeV2, TransactionType, UserAccount
from src.models.http_api_models import resolve_model, resolve_symbol
from src.models.json_to_obj import extract_to_model

try:
    import ujson as json
except ImportError:
    import json

api_url = "http://api-test.exante.eu"
api_md = "%s/md/{}" % api_url
api_trade = "%s/trade/{}" % api_url
account = "DEW8032.001"
symbol = "ASM.EURONEXT"
size = 4


@pytest.mark.parametrize("sym", (
        symbol,
        (symbol, symbol),
        SymbolV3("", "", "", "", symbol, "", "0.01", "STOCK", "", ""),
        SymbolV2({}, "", "", "", "", symbol, "", "0.01", "STOCK", "", ""),
        SymbolV1({}, "", "", "", "", symbol, "", 0.01, "STOCK", "", ""),
        (SymbolV3("", "", "", "", symbol, "", "0.01", "STOCK", "", ""),
         SymbolV2({}, "", "", "", "", symbol, "", "0.01", "STOCK", "", ""))
                                 ))
def test_resolve_symbol_func(sym):
    resolve = resolve_symbol(sym)
    if "," in resolve:
        assert resolve == f"{symbol},{symbol}"
    else:
        assert resolve == symbol


@pytest.mark.parametrize("mod,modtype", ((TradeV2, TradeType),))
def test_resolve_model_func(mod, modtype):
    assert mod == resolve_model(current_api, TradeType)


class TestHTTPApi:
    mock_adapter = None  # type: requests_mock.Adapter
    client = None  # type: HTTPApi

    def setup_class(self):
        self.mock_adapter = requests_mock.Adapter()
        self.client = HTTPApi(AuthMethods.JWT, "someappid", clientid="someclientid", sharedkey="somesharedkey",
                              ttl=3600, url=api_url)
        self.client.session.mount(api_url, self.mock_adapter)

    def test_get_user_accounts(self):
        data = [
            {"accountId": "DEW8032.001", "status": "Full"},
            {"accountId": "DEW8032.002", "status": "ReadOnly"},
            {"accountId": "DEW8032.003", "status": "CloseOnly"}
        ]
        self.mock_adapter.register_uri("GET", api_md.format(current_api) + "/accounts", json=data)
        assert all(a == b for a, b in zip(self.client.get_user_accounts(current_api),
                                          extract_to_model(data, UserAccount)))

    @pytest.mark.parametrize("symbols", (None, (symbol, "AAPL2.NASDAQ", "AAPL3.NASDAQ")))
    def test_get_changes(self, symbols):
        data = [
            {"symbolId": symbol, "dailyChange": "110.123", "basePrice": "111.111"},
            {"symbolId": "AAPL2.NASDAQ", "dailyChange": "110.123", "basePrice": "111.111"},
            {"symbolId": "AAPL3.NASDAQ", "dailyChange": "110.123", "basePrice": "111.111"}
        ]
        if symbols is None:
            self.mock_adapter.register_uri("GET", api_md.format(current_api) + "/change", json=data)
        else:
            self.mock_adapter.register_uri("GET", api_md.format(current_api) + "/change/" + ",".join(symbols),
                                           json=data)
        assert all(a == b for a, b in zip(self.client.get_changes(symbols, current_api),
                                          extract_to_model(data, resolve_model(current_api, ChangeType))))

    def test_get_currencies(self):
        data = {
            "currencies": [
                "PLN",
                "EUR",
                "USD",
                "BRL"
            ]
        }
        self.mock_adapter.register_uri("GET", api_md.format(current_api) + "/crossrates", json=data)
        assert self.client.get_currencies(current_api) == data["currencies"]

    def test_get_crossrates(self):
        data = {"pair": "EUR/USD", "symbolId": "EUR/USD.EXANTE", "rate": "1.18178"}
        self.mock_adapter.register_uri("GET", api_md.format(current_api) + "/crossrates/EUR/USD", json=data)
        assert self.client.get_crossrates("EUR", "USD", version=current_api) == Crossrate.from_json(data)

    def test_get_exchanges(self):
        data = [
            {"id": "NASDAQ", "name": "NASDAQ: National Association of Securities Dealers Auto Quota", "country": "US"},
            {"id": "FORTS", "name": "FORTS: Futures and Options on Russian Trading System", "country": "RU"},
            {"id": "NYSE", "name": "NYSE: New York Stock Exchange", "country": "US"}
        ]
        self.mock_adapter.register_uri("GET", api_md.format(current_api) + "/exchanges", json=data)
        assert all(a == b for a, b in zip(self.client.get_exchanges(current_api),
                                          extract_to_model(data, Exchange)))

    @pytest.mark.parametrize("exch", ("FORTS", Exchange("FORTS", "FORTS: Futu...", "RU")))
    def test_symbols_by_exch(self, exch):
        data = [
            {
                "optionData": {"optionGroupId": "ED.FORTS.Z2020.C*", "strikePrice": "1.1", "right": "CALL"}, "i18n": {},
                "name": "EUR/USD", "description": "Options On EUR/USD Futures Dec 2020 CALL 1.1", "country": "RU",
                "exchange": "FORTS", "id": "ED.FORTS.Z2020.C1_1", "currency": "USD", "mpi": "0.0001", "type": "OPTION",
                "ticker": "ED", "expiration": 1608202800000, "group": "ED"
            },
            {
                "optionData": {"optionGroupId": "SBRF.FORTS.U2020.C*", "strikePrice": "1550", "right": "CALL"},
                "i18n": {}, "name": "Sberbank", "description": "Options On Sberbank Futures Sep 2020 CALL 15500",
                "country": "RU", "exchange": "FORTS", "id": "SBRF.FORTS.U2020.C15500", "currency": "RUB", "mpi": "1.0",
                "type": "OPTION", "ticker": "SBRF", "expiration": 1600271100000, "group": "SBRF.FORTS"
            }
        ]
        self.mock_adapter.register_uri("GET", api_md.format(current_api) + "/exchanges/FORTS", json=data)
        assert all(a == b for a, b in zip(self.client.get_symbols_by_exch(exch, current_api),
                                          extract_to_model(data, resolve_model(current_api, SymbolType))))

    def test_groups(self):
        data = [
            {"group": "MS", "name": "Morgan Stanley", "types": ["OPTION"], "exchange": "CBOE"},
            {"group": "SLP", "name": "Simulations Plus", "types": ["FUTURE", "OPTION"], "exchange": "CBOE"},
            {"group": "RBCL", "name": "RBOB Gasoline/Crude oil", "types": ["FUTURE"], "exchange": "NYMEX"}
        ]
        self.mock_adapter.register_uri("GET", api_md.format(current_api) + "/groups", json=data)
        assert all(a == b for a, b in zip(self.client.get_groups(current_api),
                                          extract_to_model(data, Group)))

    @pytest.mark.parametrize("gr", ("NLMK.FORTS", Group("NLMK.FORTS", "NLMK", ["FUTURE"], "FORTS")))
    def test_symbols_by_gr(self, gr):
        data = [
            {
                "optionData": None, "i18n": {}, "name": "NLMK",
                "description": "Futures on NLMK ordinary shares Jun 2021",
                "country": "RU", "exchange": "FORTS", "id": "NLMK.FORTS.M2021", "currency": "RUB", "mpi": "1.0",
                "type": "FUTURE", "ticker": "NLMK", "expiration": 1623944700000, "group": "NLMK.FORTS"
            },
            {
                "optionData": None, "i18n": {}, "name": "NLMK",
                "description": "Futures on NLMK ordinary shares Mar 2021",
                "country": "RU", "exchange": "FORTS", "id": "NLMK.FORTS.H2021", "currency": "RUB", "mpi": "1.0",
                "type": "FUTURE", "ticker": "NLMK", "expiration": 1616082300000, "group": "NLMK.FORTS"
            }
        ]
        self.mock_adapter.register_uri("GET", api_md.format(current_api) + "/groups/NLMK.FORTS", json=data)
        assert all(a == b for a, b in zip(self.client.get_symbols_by_gr(gr, current_api),
                                          extract_to_model(data, resolve_model(current_api, SymbolType))))

    @pytest.mark.parametrize("gr", ("NLMK.FORTS", Group("NLMK.FORTS", "NLMK", ["FUTURE"], "FORTS")))
    def test_get_nearest(self, gr):
        data = {
            "optionData": None, "i18n": {}, "name": "NLMK", "description": "Futures on NLMK ordinary shares Jun 2021",
            "country": "RU", "exchange": "FORTS", "id": "NLMK.FORTS.U2020", "currency": "RUB", "mpi": "1.0",
            "type": "FUTURE", "ticker": "NLMK", "expiration": 1623944700000, "group": "NLMK.FORTS"
        }
        self.mock_adapter.register_uri("GET", api_md.format(current_api) + "/groups/NLMK.FORTS/nearest", json=data)
        assert self.client.get_nearest(gr, current_api) == \
               resolve_model(current_api, SymbolType).from_json(data)

    def test_get_symbols(self):
        data = [
            {
                "optionData": None, "i18n": {}, "name": "AAON", "description": "AAON, Inc. - Common Stock",
                "country": "US", "exchange": "NASDAQ", "id": "AAON.NASDAQ", "currency": "USD", "mpi": "0.01",
                "type": "STOCK", "ticker": "AAON", "expiration": None, "group": None
            },
            {
                "optionData": {"optionGroupId": "XLU.CBOE.21F2022.C*", "strikePrice": 65, "right": "CALL"}, "i18n": {},
                "name": "SPDR Select Sector Fund - Utilities",
                "description": "Options On SPDR Select Sector Fund - Utilities 21 Jan 2022 CALL 65", "country": "US",
                "exchange": "CBOE", "id": "XLU.CBOE.21F2022.C65", "currency": "USD", "mpi": "0.01", "type": "OPTION",
                "ticker": "XLU", "expiration": 1642798800000, "group": "XLU"
            }
        ]
        self.mock_adapter.register_uri("GET", api_md.format(current_api) + "/symbols", json=data)
        assert all(a == b for a, b in zip(self.client.get_symbols(current_api),
                                          extract_to_model(data, resolve_model(current_api, SymbolType))))

    @pytest.mark.parametrize("sym", (symbol,
                                     resolve_model(current_api, SymbolType)({}, "", "", "", "", symbol, "",
                                                                            "0.01", "STOCK", "")))
    @pytest.mark.parametrize("ordt", (None,
                                      {"market": ["day", "good_till_cancel"], "limit": ["day", "good_till_cancel"]}))
    def test_get_symbol_schedule(self, sym, ordt):
        data = {
            "intervals": [
                {"name": "Offline", "period": {"start": 1597550400000, "end": 1597651200000}, "orderTypes": ordt},
                {"name": "PreMarket", "period": {"start": 1597651200000, "end": 1597671000000}, "orderTypes": ordt},
                {"name": "MainSession", "period": {"start": 1597671000000, "end": 1597694400000}, "orderTypes": ordt},
                {"name": "AfterMarket", "period": {"start": 1597694400000, "end": 1597708800000}, "orderTypes": ordt},
                {"name": "Offline", "period": {"start": 1597708800000, "end": 1597737600000}, "orderTypes": ordt}
            ]
        }
        if not ordt:
            self.mock_adapter.register_uri("GET", api_md.format(current_api) +
                                           f"/symbols/{resolve_symbol(sym)}/schedule?types=false", json=data)
            assert self.client.get_symbol_schedule(sym, False, current_api) == Schedule.from_json(data)
        else:
            self.mock_adapter.register_uri("GET", api_md.format(current_api) +
                                           f"/symbols/{resolve_symbol(sym)}/schedule?types=true", json=data)
            assert self.client.get_symbol_schedule(sym, True, current_api) == Schedule.from_json(data)

    @pytest.mark.parametrize("sym", (symbol,
                                     resolve_model(current_api, SymbolType)({}, "", "", "", "", symbol, "",
                                                                            "0.01", "STOCK", "")))
    def test_get_symbol_spec(self, sym):
        data = {
            "leverage": "0.2",
            "contractMultiplier": "1.0",
            "priceUnit": "1.0",
            "units": "Shares",
            "lotSize": "1.0"
        }
        self.mock_adapter.register_uri("GET", api_md.format(current_api) +
                                       f"/symbols/{resolve_symbol(sym)}/specification", json=data)
        assert self.client.get_symbol_spec(sym, current_api) == SymbolSpecification.from_json(data)

    def test_get_types(self):
        data = [
            {"id": "CALENDAR_SPREAD"},
            {"id": "FX_SPOT"},
            {"id": "FUND"},
            {"id": "CFD"},
            {"id": "CURRENCY"},
            {"id": "STOCK"},
            {"id": "OPTION"},
            {"id": "FUTURE"},
            {"id": "BOND"}
        ]
        self.mock_adapter.register_uri("GET", api_md.format(current_api) + "/types", json=data)
        assert all(self.client.get_types(current_api).count(x) == 1 for x in list(InstrumentType))

    def test_get_symbols_by_type(self):
        data = [
            {
                "optionData": None, "i18n": {}, "name": "NLMK",
                "description": "Futures on NLMK ordinary shares Jun 2021",
                "country": "RU", "exchange": "FORTS", "id": "NLMK.FORTS.M2021", "currency": "RUB", "mpi": "1.0",
                "type": "FUTURE", "ticker": "NLMK", "expiration": 1623944700000, "group": "NLMK.FORTS"
            },
            {
                "optionData": None, "i18n": {}, "name": "NLMK",
                "description": "Futures on NLMK ordinary shares Mar 2021",
                "country": "RU", "exchange": "FORTS", "id": "NLMK.FORTS.H2021", "currency": "RUB", "mpi": "1.0",
                "type": "FUTURE", "ticker": "NLMK", "expiration": 1616082300000, "group": "NLMK.FORTS"
            }
        ]
        self.mock_adapter.register_uri("GET", api_md.format(current_api) + f"/types/{InstrumentType.FUTURE.value}",
                                       json=data)
        assert all(a == b for a, b in zip(self.client.get_symbol_by_type(InstrumentType.FUTURE, current_api),
                                          extract_to_model(data, resolve_model(current_api, SymbolType))))

    @pytest.mark.parametrize("sym",
                             (symbol,
                              [symbol, "SBRF.MICEX"],
                              resolve_model(current_api, SymbolType)({}, "", "", "", "", symbol, "", "0.01",
                                                                     "STOCK", ""),
                              [resolve_model(current_api, SymbolType)({}, "", "", "", "", symbol, "", "0.01",
                                                                      "STOCK", ""),
                               resolve_model(current_api, SymbolType)({}, "", "", "", "", "SBRF.MICEX", "", "0.01",
                                                                      "STOCK", "")]
                              ))
    @pytest.mark.parametrize("lvl", (FeedLevel.BEST_PRICE, FeedLevel.MARKET_DEPTH))
    def test_get_last_quote(self, sym, lvl):
        if lvl == FeedLevel.BEST_PRICE:
            data = [
                {
                    "timestamp": 1598544258088,
                    "symbolId": symbol,
                    "bid": [
                        {"value": "503.75", "size": "120000.0"},
                        {"value": "501.00", "size": "210000.0"}
                    ],
                    "ask": [
                        {"value": "503.93", "size": "40000.0"},
                        {"value": "508.00", "size": "192500.0"}
                    ]
                },
                {
                    "timestamp": 1598544258291,
                    "symbolId": "SBRF.MICEX",
                    "bid": [
                        {"value": "111.7270", "size": "500000000"},
                        {"value": "111.7260", "size": "500000000"},
                        {"value": "111.7250", "size": "500000000"},
                        {"value": "111.7240", "size": "500000000"}
                    ],
                    "ask": [
                        {"value": "111.7290", "size": "500000000"},
                        {"value": "111.7300", "size": "500000000"},
                        {"value": "111.7310", "size": "500000000"},
                        {"value": "111.7320", "size": "500000000"}
                    ]
                }
            ]
        else:
            data = [
                {
                    "timestamp": 1598544258088,
                    "symbolId": symbol,
                    "bid": [{"value": "503.75", "size": "120000.0"}],
                    "ask": [{"value": "503.93", "size": "40000.0"}]
                },
                {
                    "timestamp": 1598544258291,
                    "symbolId": "SBRF.MICEX",
                    "bid": [{"value": "111.7270", "size": "500000000"}],
                    "ask": [{"value": "111.7290", "size": "500000000"}]
                }
            ]
        if hasattr(sym, "__iter__") and not isinstance(sym, str):
            data = [data[0]]
        self.mock_adapter.register_uri("GET", api_md.format(current_api) + f"/feed/{resolve_symbol(sym)}/last",
                                       json=data)
        assert all(a == b for a, b in zip(self.client.get_last_quote(sym, lvl, current_api),
                                          extract_to_model(data, resolve_model(current_api, QuoteType))))

    @pytest.mark.parametrize("sym", (symbol,
                                     resolve_model(current_api, SymbolType)({}, "", "", "", "", symbol, "",
                                                                            "0.01", "STOCK", "")))
    @pytest.mark.parametrize("dur", (300, CandleDurations.MIN5))
    def test_get_ohlc_quotes(self, sym, dur):
        data = [
            {"timestamp": 1598545500000, "open": "502.935", "low": "502.645", "close": "502.69", "high": "503.295"},
            {"timestamp": 1598545200000, "open": "503.145", "low": "502.11", "close": "502.94", "high": "503.145"},
            {"timestamp": 1598544900000, "open": "504.055", "low": "503.115", "close": "503.14", "high": "504.135"},
            {"timestamp": 1598544600000, "open": "504.165", "low": "503.755", "close": "504.05", "high": "504.245"}
        ]
        self.mock_adapter.register_uri("GET", api_md.format(current_api) +
                                       f"/ohlc/{resolve_symbol(sym)}/300?size={size}&type={DataType.QUOTES.value}",
                                       json=data)
        assert all(a == b for a, b in zip(
            self.client.get_ohlc(sym, dur, DataType.QUOTES, limit=size, version=current_api),
            extract_to_model(data, OHLCQuotes)
        ))

    @pytest.mark.parametrize("sym", (symbol,
                                     resolve_model(current_api, SymbolType)({}, "", "", "", "", symbol, "",
                                                                            "0.01", "STOCK", "")))
    @pytest.mark.parametrize("dur", (300, CandleDurations.MIN5))
    def test_get_ohlc_trades(self, sym, dur):
        data = [
            {"timestamp": 1598545500000, "open": "502.935", "low": "502.645", "close": "502.69", "high": "503.295",
             "volume": "1000"},
            {"timestamp": 1598545200000, "open": "503.145", "low": "502.11", "close": "502.94", "high": "503.145",
             "volume": "10200"},
            {"timestamp": 1598544900000, "open": "504.055", "low": "503.115", "close": "503.14", "high": "504.135",
             "volume": "241000"},
            {"timestamp": 1598544600000, "open": "504.165", "low": "503.755", "close": "504.05", "high": "504.245",
             "volume": "411000"}
        ]
        self.mock_adapter.register_uri("GET", api_md.format(current_api) +
                                       f"/ohlc/{resolve_symbol(sym)}/300?size={size}&type={DataType.TRADES.value}",
                                       json=data)
        assert all(a == b for a, b in zip(
            self.client.get_ohlc(sym, dur, DataType.TRADES, limit=size, version=current_api),
            extract_to_model(data, OHLCTrades)
        ))

    @pytest.mark.parametrize("sym", (symbol,
                                     resolve_model(current_api, SymbolType)({}, "", "", "", "", symbol, "",
                                                                            "0.01", "STOCK", "")))
    def test_get_ticks_quotes(self, sym):
        data = [
            {
                "timestamp": 1598547082141,
                "symbolId": symbol,
                "bid": [{"value": "498.14", "size": "20000"}],
                "ask": [{"value": "498.22", "size": "20000"}]
            },
            {
                "timestamp": 1598547082118,
                "symbolId": symbol,
                "bid": [{"value": "498.14", "size": "20000"}],
                "ask": [{"value": "498.21", "size": "10000"}]
            },
            {
                "timestamp": 1598547081692,
                "symbolId": symbol,
                "bid": [{"value": "498.14", "size": "20000"}],
                "ask": [{"value": "498.22", "size": "10000"}]
            },
            {
                "timestamp": 1598547081679,
                "symbolId": symbol,
                "bid": [{"value": "498.15", "size": "10000"}],
                "ask": [{"value": "498.26", "size": "50000"}]
            }
        ]
        self.mock_adapter.register_uri("GET", api_md.format(current_api) +
                                       f"/ticks/{resolve_symbol(sym)}?size={size}&type={DataType.QUOTES.value}",
                                       json=data)
        assert all(a == b for a, b in zip(self.client.get_ticks(sym, DataType.QUOTES, limit=size, version=current_api),
                                          extract_to_model(data, resolve_model(current_api, QuoteType))))

    @pytest.mark.parametrize("sym", (symbol,
                                     resolve_model(current_api, SymbolType)({}, "", "", "", "", symbol, "",
                                                                            "0.01", "STOCK", "")))
    def test_get_ticks_trades(self, sym):
        data = [
            {"timestamp": 1598547318373, "symbolId": symbol, "value": "497.94", "size": "100"},
            {"timestamp": 1598547318373, "symbolId": symbol, "value": "497.94", "size": "100"},
            {"timestamp": 1598547318373, "symbolId": symbol, "value": "497.94", "size": "100"},
            {"timestamp": 1598547318373, "symbolId": symbol, "value": "497.94", "size": "100"}
        ]
        self.mock_adapter.register_uri("GET", api_md.format(current_api) +
                                       f"/ticks/{resolve_symbol(sym)}?size={size}&type={DataType.TRADES.value}",
                                       json=data)
        assert all(a == b for a, b in zip(self.client.get_ticks(sym, DataType.TRADES, limit=size, version=current_api),
                                          extract_to_model(data, resolve_model(current_api, TradeType))))

    @pytest.mark.parametrize("date", (None, "2020-08-27"))
    def test_get_account_summary(self, date):
        cur = "EUR"
        data = {
            "currencies": [
                {"code": "EUR", "convertedValue": "5409021.1", "value": "5409021.1"},
                {"code": "USD", "convertedValue": "-853029.89", "value": "-1006251.11"}
            ],
            "timestamp": 1598547616000,
            "freeMoney": "4453132.61",
            "netAssetValue": "4470325.01",
            "moneyUsedForMargin": "17192.4",
            "marginUtilization": "0.0",
            "positions": [
                {
                    "convertedPnl": "-84774.08",
                    "quantity": "1011",
                    "pnl": "-100001.2",
                    "convertedValue": "1010.97",
                    "price": "1.17958",
                    "id": "EUR/USD.E.FX",
                    "symbolType": "FX_SPOT",
                    "currency": "USD",
                    "averagePrice": "100.0927286",
                    "value": "1192.56"
                },
            ],
            "sessionDate": None,
            "currency": "EUR",
            "account": "DEW8032.001"
        }
        if date:
            self.mock_adapter.register_uri("GET", api_md.format(current_api) + f"/summary/{account}/{date}/{cur}",
                                           json=data)
        else:
            self.mock_adapter.register_uri("GET", api_md.format(current_api) + f"/summary/{account}/{cur}", json=data)
        assert self.client.get_account_summary(account, cur, date, current_api) == \
               resolve_model(current_api, SummaryType).from_json(data)

    def test_get_transactions(self):
        data = [
            {"symbolId": None, "operationType": "INTEREST", "accountId": "DEW8032.001", "id": 3555890, "asset": "EUR",
             "when": 1573718174726, "sum": "-4039708876.86"},
            {"symbolId": "ASM.EURONEXT", "operationType": "COMMISSION", "accountId": "DEW8032.001", "id": 3571087,
             "asset": "EUR", "when": 1573745310647, "sum": "-0.05"},
            {"symbolId": "ASM.EURONEXT", "operationType": "TRADE", "accountId": "DEW8032.001", "id": 3571086,
             "asset": "EUR", "when": 1573745310647, "sum": "-91.85"},
            {"symbolId": "ASM.EURONEXT", "operationType": "TRADE", "accountId": "DEW8032.001", "id": 3571085,
             "asset": "ASM.EURONEXT", "when": 1573745310647, "sum": "1"}
        ]
        self.mock_adapter.register_uri("GET", api_md.format(current_api) +
                                       f"/transactions?limit={size}&order={Ordering.ASC.value}&accountId={account}",
                                       json=data)
        assert all(a == b for a, b in
                   zip(self.client.get_transactions(account, limit=size, order=Ordering.ASC, version=current_api),
                       extract_to_model(data, resolve_model(current_api, TransactionType))))

    def test_place_order(self):
        def match_body(request):
            print(DeepDiff(request.json(), order, ignore_order=True))
            return not bool(DeepDiff(request.json(), order, ignore_order=True))

        data = [
            {
                "placeTime": "2020-08-28T10:56:09.969Z",
                "username": "unittest@login.com",
                "id": "c8ab844e-c3b6-424b-9729-767ae417f48b",
                "orderState": {
                    "status": "placing",
                    "lastUpdate": "2020-08-28T10:56:09.969ZASM.EURONEXT",
                    "fills": []
                },
                "accountId": "DEW8032.001",
                "orderParameters": {
                    "side": "buy",
                    "duration": "day",
                    "quantity": "2",
                    "instrument": "ASM.EURONEXT",
                    "ocoGroup": None,
                    "ifDoneParentId": None,
                    "orderType": "limit",
                    "limitPrice": "30"
                },
                "currentModificationId": "c8ab844e-c3b6-424b-9729-767ae417f48b"
            },
            {
                "placeTime": "2020-08-28T10:56:09.969Z",
                "username": "unittest@login.com",
                "id": "0045e5d6-bde1-45bc-81c1-e33ec84fea0f",
                "orderState": {
                    "status": "pending",
                    "lastUpdate": "2020-08-28T10:56:09.969Z",
                    "fills": []
                },
                "accountId": "DEW8032.001",
                "orderParameters": {
                    "side": "sell",
                    "duration": "day",
                    "quantity": "2",
                    "instrument": "ASM.EURONEXT",
                    "ocoGroup": "84eafbd7-3e91-41f4-a855-ce17df655a45",
                    "ifDoneParentId": "c8ab844e-c3b6-424b-9729-767ae417f48b",
                    "stopPrice": "25",
                    "orderType": "stop"
                },
                "currentModificationId": "0045e5d6-bde1-45bc-81c1-e33ec84fea0f"},
            {
                "placeTime": "2020-08-28T10:56:09.970Z",
                "username": "unittest@login.com",
                "id": "ea6f4ec6-b226-4b84-aef2-d067bc3439fb",
                "orderState": {
                    "status": "pending",
                    "lastUpdate": "2020-08-28T10:56:09.970Z",
                    "fills": []
                },
                "accountId": "DEW8032.001",
                "orderParameters": {
                    "side": "sell",
                    "duration": "day",
                    "quantity": "2",
                    "instrument": "ASM.EURONEXT",
                    "ocoGroup": "84eafbd7-3e91-41f4-a855-ce17df655a45",
                    "ifDoneParentId": "c8ab844e-c3b6-424b-9729-767ae417f48b",
                    "orderType": "limit",
                    "limitPrice": "35"
                },
                "currentModificationId": "ea6f4ec6-b226-4b84-aef2-d067bc3439fb"
            }
        ]
        order = {
            "instrument": "ASM.EURONEXT",
            "side": "buy",
            "quantity": "2",
            "orderType": "limit",
            "duration": "day",
            "accountId": "DEW8032.001",
            "limitPrice": "30",
            "takeProfit": "35",
            "stopLoss": "25"
        }
        self.mock_adapter.register_uri("POST", api_trade.format(current_api) + "/orders", additional_matcher=match_body,
                                       json=data)
        ord_obj = resolve_model(current_api, OrderLimitType)(account, "ASM.EURONEXT", Side.BUY, "2", Durations.day,
                                                             "30", take_profit="35", stop_loss="25")
        assert all(a == b for a, b in zip(self.client.place_order(ord_obj, current_api),
                                          extract_to_model(data, resolve_model(current_api, OrderType))))

    def test_get_orders(self):
        data = [
            {
                "placeTime": "2020-08-28T10:56:09.969Z",
                "username": "unittest@login.com",
                "orderState": {
                    "status": "working",
                    "lastUpdate": "2020-08-28T10:56:10.070Z",
                    "fills": []
                },
                "accountId": "DEW8032.001",
                "id": "c8ab844e-c3b6-424b-9729-767ae417f48b",
                "orderParameters": {
                    "side": "buy",
                    "duration": "day",
                    "quantity": "2",
                    "ocoGroup": None,
                    "ifDoneParentId": None,
                    "orderType": "limit",
                    "limitPrice": "30",
                    "instrument": "ASM.EURONEXT"
                },
                "currentModificationId": "c8ab844e-c3b6-424b-9729-767ae417f48b"
            },
            {
                "placeTime": "2020-08-28T10:56:09.970Z",
                "username": "unittest@login.com",
                "orderState": {
                    "status": "pending",
                    "lastUpdate": "2020-08-28T10:56:09.970Z",
                    "fills": []
                },
                "accountId": "DEW8032.001",
                "id": "ea6f4ec6-b226-4b84-aef2-d067bc3439fb",
                "orderParameters": {
                    "side": "sell",
                    "duration": "day",
                    "quantity": "2",
                    "ocoGroup": "84eafbd7-3e91-41f4-a855-ce17df655a45",
                    "ifDoneParentId": "c8ab844e-c3b6-424b-9729-767ae417f48b",
                    "orderType": "limit",
                    "limitPrice": "35",
                    "instrument": "ASM.EURONEXT"
                },
                "currentModificationId": "ea6f4ec6-b226-4b84-aef2-d067bc3439fb"
            },
            {
                "placeTime": "2020-08-28T10:56:09.969Z",
                "username": "unittest@login.com",
                "orderState": {
                    "status": "pending",
                    "lastUpdate": "2020-08-28T10:56:09.969Z",
                    "fills": []
                },
                "accountId": "DEW8032.001",
                "id": "0045e5d6-bde1-45bc-81c1-e33ec84fea0f",
                "orderParameters": {
                    "side": "sell",
                    "duration": "day",
                    "quantity": "2",
                    "ocoGroup": "84eafbd7-3e91-41f4-a855-ce17df655a45",
                    "ifDoneParentId": "c8ab844e-c3b6-424b-9729-767ae417f48b",
                    "stopPrice": "25",
                    "orderType": "stop",
                    "instrument": "ASM.EURONEXT"
                },
                'currentModificationId': '0045e5d6-bde1-45bc-81c1-e33ec84fea0f'
            },
            {
                "placeTime": "2020-08-28T11:40:47.351Z",
                "username": "unittest@login.com",
                "orderState": {
                    "status": "rejected",
                    "lastUpdate": "2020-08-28T11:40:47.351Z",
                    "fills": [],
                    "reason": "Invalid quantity"
                },
                "accountId": "DEW8032.001",
                "id": "15dac05f-693c-4090-afc2-012112ebb0eb",
                "orderParameters": {
                    "side": "buy",
                    "duration": "day",
                    "quantity": "-2",
                    "ocoGroup": None,
                    "ifDoneParentId": None,
                    "orderType": "limit",
                    "limitPrice": "30",
                    "instrument": "ASM.EURONEXT"
                },
                "currentModificationId": "15dac05f-693c-4090-afc2-012112ebb0eb"
            }
        ]
        self.mock_adapter.register_uri("GET", api_trade.format(current_api) +
                                       f"/orders?{list(HTTPApi._mk_account(account, current_api).keys())[0]}={account}"
                                       f"&limit={size}", json=data)
        assert all(a == b for a, b in zip(self.client.get_orders(account, size, version=current_api),
                                          extract_to_model(data, resolve_model(current_api, OrderType))))

    def test_get_active_orders(self):
        data = [
            {
                "placeTime": "2020-08-28T10:56:09.969Z",
                "username": "unittest@login.com",
                "orderState": {
                    "status": "working",
                    "lastUpdate": "2020-08-28T10:56:10.070Z",
                    "fills": []
                },
                "accountId": "DEW8032.001",
                "id": "c8ab844e-c3b6-424b-9729-767ae417f48b",
                "orderParameters": {
                    "side": "buy",
                    "duration": "day",
                    "quantity": "2",
                    "ocoGroup": None,
                    "ifDoneParentId": None,
                    "orderType": "limit",
                    "limitPrice": "30",
                    "instrument": "ASM.EURONEXT"
                },
                "currentModificationId": "c8ab844e-c3b6-424b-9729-767ae417f48b"
            }
        ]
        acc_str = list(HTTPApi._mk_account(account, current_api).keys())[0]
        sym_str = list(HTTPApi._mk_symbol(symbol, current_api).keys())[0]
        self.mock_adapter.register_uri("GET", api_trade.format(current_api) +
                                       f"/orders/active?{acc_str}={account}&limit={size}&{sym_str}={symbol}", json=data)
        assert all(a == b for a, b in zip(self.client.get_active_orders(account, size, symbol, current_api),
                                          extract_to_model(data, resolve_model(current_api, OrderType))))

    def test_get_order(self):
        data = {
            "placeTime": "2020-08-28T10:56:09.969Z",
            "username": "unittest@login.com",
            "orderState": {
                "status": "working",
                "lastUpdate": "2020-08-28T10:56:10.070Z",
                "fills": []
            },
            "accountId": "DEW8032.001",
            "id": "c8ab844e-c3b6-424b-9729-767ae417f48b",
            "orderParameters": {
                "side": "buy",
                "duration": "day",
                "quantity": "2",
                "ocoGroup": None,
                "ifDoneParentId": None,
                "orderType": "limit",
                "limitPrice": "30",
                "instrument": "ASM.EURONEXT"
            },
            "currentModificationId": "c8ab844e-c3b6-424b-9729-767ae417f48b"
        }
        self.mock_adapter.register_uri("GET", api_trade.format(current_api) + f"/orders/{data['id']}", json=data)
        assert self.client.get_order(data['id'], current_api) == resolve_model(current_api, OrderType).from_json(data)

    def test_replace_order(self):
        def match_body(request):
            return not bool(DeepDiff(request.json(),
                                     {"action": "replace", "parameters": {"quantity": "3", "limitPrice": "30.5"}},
                                     ignore_order=True))

        data = {
            "placeTime": "2020-08-28T10:56:09.969Z",
            "username": "unittest@login.com",
            "orderState": {
                "status": "working",
                "lastUpdate": "2020-08-28T13:20:10.070Z",
                "fills": []
            },
            "accountId": "DEW8032.001",
            "id": "c8ab844e-c3b6-424b-9729-767ae417f48c",
            "orderParameters": {
                "side": "buy",
                "duration": "day",
                "quantity": "3",
                "ocoGroup": None,
                "ifDoneParentId": None,
                "orderType": "limit",
                "limitPrice": "30.5",
                "instrument": "ASM.EURONEXT"
            },
            "currentModificationId": "64af451a-1bc6-401c-9c05-0aba12fce822"
        }
        self.mock_adapter.register_uri("POST", api_trade.format(current_api) + f"/orders/{data['id']}",
                                       additional_matcher=match_body, json=data)
        assert self.client.replace_order(data['id'], 3, '30.5', version=current_api) == \
               resolve_model(current_api, OrderType).from_json(data)

    def test_cancel_order(self):
        def match_body(request):
            return not bool(DeepDiff(request.json(), {"action": "cancel"}, ignore_order=True))

        data = {
            "placeTime": "2020-08-28T10:56:09.969Z",
            "username": "unittest@login.com",
            "orderState": {
                "status": "cancelled",
                "lastUpdate": "2020-08-28T13:25:10.070Z",
                "fills": []
            },
            "accountId": "DEW8032.001",
            "id": "c8ab844e-c3b6-424b-9729-767ae417f48b",
            "orderParameters": {
                "side": "buy",
                "duration": "day",
                "quantity": "3",
                "ocoGroup": None,
                "ifDoneParentId": None,
                "orderType": "limit",
                "limitPrice": "30.5",
                "instrument": "ASM.EURONEXT"
            },
            "currentModificationId": "cf816efe-1333-4bff-8af3-c46b56e10730"
        }
        self.mock_adapter.register_uri("POST", api_trade.format(current_api) + f"/orders/{data['id']}",
                                       additional_matcher=match_body, json=data)
        assert self.client.cancel_order(data['id'], current_api) == \
               resolve_model(current_api, OrderType).from_json(data)

    def test_place_rejected_order(self):
        def match_body(request):
            print(DeepDiff(request.json(), order, ignore_order=True))
            return not bool(DeepDiff(request.json(), order, ignore_order=True))

        data = [
            {"group": "client", "message": "Unknown or expired instrument"}
        ]
        order = {
            "instrument": "ASM.EURONEXT234",
            "side": "buy",
            "quantity": "2",
            "orderType": "limit",
            "duration": "day",
            "accountId": "DEW8032.001",
            "limitPrice": "40"
        }
        ord_obj = resolve_model(current_api, OrderLimitType)(account, "ASM.EURONEXT234", Side.BUY, 2, Durations.day, 40)
        self.mock_adapter.register_uri("POST", api_trade.format(current_api) + f"/orders",
                                       additional_matcher=match_body, json=data, status_code=400)
        x = self.client.place_order(ord_obj, current_api)
        y = extract_to_model(data, Reject)
        assert all(a == b for a, b in zip(x, y))

    @responses.activate
    def test_quote_stream(self):
        def formatter():
            return '\n'.join(json.dumps(item) for item in data).encode('ascii')

        data = [
            {
                "timestamp": 1598625378042,
                "symbolId": symbol,
                "bid": [{"value": "110.8660", "size": "500000000"}],
                "ask": [{"value": "110.8680", "size": "500000000"}]
            },
            {
                "timestamp": 1598625379044,
                "symbolId": symbol,
                "bid": [{"value": "110.8720", "size": "500000000"}],
                "ask": [{"value": "110.8740", "size": "500000000"}]
            },
            {
                "timestamp": 1598625381054,
                "symbolId": symbol,
                "bid": [{"value": "110.8750", "size": "500000000"}],
                "ask": [{"value": "110.8770", "size": "500000000"}]
            }
        ]

        responses.add("GET", api_md.format(current_api) + f"/feed/{symbol}?level=best_price",
                      body=formatter(), status=200, content_type='application/x-json-stream', stream=True)
        subscription = self.client.get_quote_stream(symbol, FeedLevel.BEST_PRICE, current_api)
        model = resolve_model(current_api, QuoteType)
        for quote in data:
            r = subscription.get(True, timeout=30)
            assert model.from_json(quote) == r

        subscription.stop()

    @responses.activate
    def test_trade_stream(self):
        def formatter():
            return '\n'.join(json.dumps(item) for item in data).encode('ascii')

        data = [
            {
                "timestamp": 1598625378042,
                "symbolId": symbol,
                "price": "111.047",
                "size": "14000"
            },
            {
                "timestamp": 1598625379044,
                "symbolId": symbol,
                "price": "115.091",
                "size": "9000"
            },
            {
                "timestamp": 1598625381054,
                "symbolId": symbol,
                "price": "112.352",
                "size": "21000"
            }
        ]

        responses.add("GET", api_md.format("3.0") + f"/feed/trades/{symbol}",
                      body=formatter(), status=200, content_type='application/x-json-stream', stream=True)
        subscription = self.client.get_trade_stream(symbol, "3.0")
        model = resolve_model("3.0", TradeType)
        for trade in data:
            r = subscription.get(True, timeout=30)
            assert model.from_json(trade) == r

        subscription.stop()

    @responses.activate
    def test_orders_stream(self):
        def formatter():
            return '\n'.join(json.dumps(item) for item in data).encode('ascii')

        data = [
            {
                "event": "order",
                "order": {
                    "placeTime": "2020-09-01T12:14:57.469Z",
                    "username": "unittest@login.com",
                    "orderState": {
                        "status": "rejected",
                        "lastUpdate": "2020-09-01T12:14:57.469Z",
                        "fills": [],
                        "reason": "Manual limit exceeded: destination positions -234879217.71 (limit), "
                                  "-234879216.71 (stop)"
                    },
                    "accountId": "DEW8032.001",
                    "id": "1b9229d3-9d9b-4628-8af5-77079fa03ec2",
                    "orderParameters": {
                        "side": "sell", "duration": "day", "quantity": "1",
                        "ocoGroup": None,
                        "ifDoneParentId": None,
                        "orderType": "limit",
                        "limitPrice": "1",
                        "instrument": "EUR/CZK.EXANTE"
                    },
                    "currentModificationId": "1b9229d3-9d9b-4628-8af5-77079fa03ec2"
                }
            },
            {"event": "heartbeat"},
            {"event": "heartbeat"},
            {
                "event": "order",
                "order": {
                    "placeTime": "2020-09-01T12:15:13.663Z",
                    "username": "unittest@login.com",
                    "orderState": {
                        "status": "rejected",
                        "lastUpdate": "2020-09-01T12:15:13.663Z",
                        "fills": [],
                        "reason": "Manual limit exceeded: destination positions -234879217.71 (limit), "
                                  "-234879216.71 (stop)"
                    },
                    "accountId": "DEW8032.001",
                    "id": "00dc7957-52d8-4efe-ae99-26f8b384a4cd",
                    "orderParameters": {
                        "side": "sell",
                        "duration": "day",
                        "quantity": "1",
                        "ocoGroup": None, "ifDoneParentId": None,
                        "orderType": "limit",
                        "limitPrice": "1",
                        "instrument": "EUR/HKD.EXANTE"
                    },
                    "currentModificationId": "00dc7957-52d8-4efe-ae99-26f8b384a4cd"
                }
            },
            {"event": "heartbeat"},
            {
                "event": "order",
                "order": {
                    "placeTime": "2020-09-01T12:15:22.270Z",
                    "username": "unittest@login.com",
                    "orderState": {
                        "status": "working",
                        "lastUpdate": "2020-09-01T12:15:22.270Z",
                        "fills": [],
                        "reason": None
                    },
                    "accountId": "DEW8032.001",
                    "id": "f6f510c9-5b46-4a23-abd7-93f550644c43",
                    "orderParameters": {
                        "side": "sell",
                        "duration": "day",
                        "quantity": "1",
                        "ocoGroup": None, "ifDoneParentId": None,
                        "orderType": "limit",
                        "limitPrice": "1.07",
                        "instrument": "EUR/HKD.EXANTE"
                    },
                    "currentModificationId": "f6f510c9-5b46-4a23-abd7-93f550644c43"
                }
            }
        ]

        responses.add("GET", api_trade.format(current_api) + f"/stream/orders",
                      body=formatter(), status=200, content_type='application/x-json-stream', stream=True)
        subscription = self.client.get_orders_stream(current_api)
        model = resolve_model(current_api, OrderType)
        for order in data:
            if order.get('event') == 'heartbeat':
                continue
            else:
                r = subscription.get(True, timeout=30)
                assert model.from_json(order['order']) == r

        subscription.stop()

    @responses.activate
    def test_exec_orders_stream(self):
        def formatter():
            return '\n'.join(json.dumps(item) for item in data).encode('ascii')

        data = [
            {"event": "heartbeat"},
            {"event": "heartbeat"},
            {"quantity": "1", "order_id": "818e0269-b21b-4f02-9b72-0b6f88e7f797", "event": "trade", "price": "111.478",
             "position": "0", "time": "2020-09-01T13:16:40.556Z"},
            {"event": "heartbeat"},
            {"event": "heartbeat"},
            {"event": "heartbeat"},
            {"quantity": "1", "order_id": "0344aaf4-7fa1-4105-b36a-57930b8f55c6", "event": "trade", "price": "111.436",
             "position": "0", "time": "2020-09-01T13:23:47.102Z"},
            {"event": "heartbeat"}
        ]

        responses.add("GET", api_trade.format(current_api) + f"/stream/trades",
                      body=formatter(), status=200, content_type='application/x-json-stream', stream=True)
        subscription = self.client.get_exec_orders_stream(current_api)
        model = resolve_model(current_api, ExOrderType)
        for trade in data:
            if trade.get('event') == 'heartbeat':
                continue
            else:
                r = subscription.get(True, timeout=30)
                assert model.from_json(trade) == r

        subscription.stop()
