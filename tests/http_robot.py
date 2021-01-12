#!/usr/bin/env python3.7

import logging
import os
from configparser import ConfigParser, SectionProxy
from dataclasses import dataclass
from decimal import Decimal
from queue import Empty
from threading import Thread
from typing import Dict, Optional, Union

from src.http_api import HTTPApi, HTTPApiStreaming, AuthMethods
from src.models.http_api_models import QuoteType, OrderLimitType, Scopes, SummaryType, FeedLevel, Side, Durations, OrderStatuses
from src.models.http_api_models import resolve_model


def mk_logger(dir_path: str, level: str) -> logging.Logger:
    log_handler = logging.FileHandler(os.path.join(dir_path, 'robot.log'), mode='a')
    log_handler.setFormatter(logging.Formatter('[%(asctime)s][%(processName)s]%(message)s'))

    log = logging.getLogger('default')  # type: logging.Logger
    log.setLevel(getattr(logging, level))
    log.addHandler(log_handler)
    return log


def get_side_price(q: Union[QuoteType, Decimal], pos: Decimal, r: Optional[Decimal] = None) -> Decimal:
    if hasattr(q, "__model__"):
        if pos > 0:
            p = q.bid[0].price
        else:
            p = q.ask[0].price
    else:
        p = q

    if r and pos > 0:
        return p - r
    elif r and pos < 0:
        return p + r
    else:
        return p


def load_config() -> ConfigParser:
    c = ConfigParser()
    c["DEFAULT"] = {
        "url": "https://api-demo.exante.eu",
        "auth": "jwt",
        "logdir": "/var/log/robot/",
        "loglevel": "DEBUG"
    }
    c["AUTH"] = {
        "appid": "56ef81eb-c530-4f9d-936c-a6cefb72d772",
        "clientid": "85411166-368a-434b-8b4c-4d642fcd4493",
        "sharedkey": "xpeNrMLpgG3JEoWaj84+CBxvm0UpSwyd",
        "ttl": 86400,
        "scopes": "feed,orders,summary"
    }
    c["TRADER"] = {
        "account": "WWB1220.001",
        "symbols": "AAPL.NASDAQ,AAL.NASDAQ",
        "range": "0.1",
        "size": "100",
        "maxSize": "0",
        "keepStartPrice": False
    }
    return c


@dataclass
class State:
    position: Decimal
    last: Union[QuoteType, Decimal]
    order: Optional[str] = None

    @property
    def price(self) -> Decimal:
        if isinstance(self.last, Decimal):
            return self.last
        else:
            return get_side_price(self.last, self.position)


class FeedHandler(Thread):
    def __init__(self, client: HTTPApi, cfg: SectionProxy):
        self.client = client
        self.subsription = None  # type: Optional[HTTPApiStreaming]
        self.range = Decimal(cfg["range"])
        self.account = cfg["account"]
        self.ord_quantity = cfg["size"]
        self.keepStartPrice = cfg.getboolean("keepStartPrice")
        self.state = {k: None for k in cfg["symbols"].split(",")}  # type: Dict[str, Optional[State]]
        super().__init__(name="feed_handler", daemon=True)

    def run(self):
        self.init_state()
        while not self.subsription.is_finished.is_set():
            try:
                quote = self.subsription.get(True, eraise=True)
                if quote:
                    s = quote.symbol_id
                    q = get_side_price(quote, self.state[s].position)
                    if abs(self.state[s].price - q) > self.range and self.state[s].position != 0:
                        if self.state[s].order:
                            self.client.replace_order(self.state[s].order, self.ord_quantity,
                                                      limit_price=get_side_price(q, self.state[s].position, self.range))
                        else:
                            # order are not placed yet or wiped
                            order = resolve_model(self.client.version, OrderLimitType)(
                                self.account, s, Side.BUY if self.state[s].position < 0 else Side.SELL,
                                self.ord_quantity, Durations.day, get_side_price(q, self.state[s].position, self.range)
                            )
                            o = self.client.place_order(order)[0]
                            try:
                                self.state[s].order = o.id_
                            except AttributeError:
                                self.client.logger.warning(f"CAN'T PLACE ORDER: {o.message}")
                        if not self.keepStartPrice:
                            self.state[s].last = quote
                    else:
                        self.client.logger.debug(f"not going to place order because {abs(self.state[s].price - q)} is less than {self.range}")
            except Empty:
                continue

    def init_state(self):
        acc_sum = self.client.get_account_summary(self.account)  # type: SummaryType
        for pos in acc_sum.positions:
            if pos.id_ in self.state:
                self.state[pos.id_] = State(pos.quantity, pos.average_price)
        self.subsription = self.client.get_quote_stream(self.state.keys(), FeedLevel.BEST_PRICE)


class OrderHandler(Thread):
    def __init__(self, feed_handler: FeedHandler):
        self.fh = feed_handler
        self.subscription = self.fh.client.get_exec_orders_stream()
        self.map = {}
        super().__init__(name="OrderHandler", daemon=True)

    def run(self):
        while not self.subscription.is_finished.is_set():
            try:
                trade = self.subscription.get(True, eraise=True)
                self.update_map()
                if trade.order_id in self.map:
                    orig_order = self.fh.client.get_order(trade.order_id)
                    i = orig_order.order_parameters.instrument
                    if OrderStatuses.terminated(orig_order.order_state.status):
                        self.fh.state[i].order = None
                        if orig_order.order_parameters.side == Side.BUY:
                            self.fh.state[i].position += orig_order.order_parameters.quantity
                        else:
                            self.fh.state[i].position -= orig_order.order_parameters.quantity
            except Empty:
                continue

    def update_map(self):
        self.map = {v.order: k for k, v in self.fh.state.items() if v}


if __name__ == "__main__":
    config = load_config()
    api_client = HTTPApi(auth=AuthMethods(config['DEFAULT']['auth']),
                         appid=config["AUTH"]["appid"],
                         clientid=config["AUTH"]["clientid"],
                         sharedkey=config["AUTH"]["sharedkey"],
                         ttl=config["AUTH"].getint("ttl"),
                         scopes=[Scopes(x) for x in config["AUTH"]["scopes"].split(",")],
                         url=config['DEFAULT']['url'],
                         version="2.0",
                         logger=mk_logger(config["DEFAULT"]["logdir"], config["DEFAULT"]["loglevel"])
                         )
    fh = FeedHandler(api_client, config["TRADER"])
    fh.start()
    bh = OrderHandler(fh)
    bh.start()
    fh.join()
