import asyncio
from dataclasses import dataclass, field
import sys
import traceback
from dataclasses_json import config, DataClassJsonMixin
from typing import Callable, Coroutine, List
from structlog import get_logger
from jsonrpc_websocket import Server

log = get_logger()

SubscriptionId = int
Status = str

TRADING = "trading"


@dataclass
class Price(DataClassJsonMixin):
    account: str
    exponent: int = field(metadata=config(field_name="price_exponent"))


@dataclass
class Metadata(DataClassJsonMixin):
    symbol: str


@dataclass
class Product(DataClassJsonMixin):
    account: str
    metadata: Metadata = field(metadata=config(field_name="attr_dict"))
    prices: List[Price] = field(metadata=config(field_name="price"))


class Pythd:
    def __init__(
        self,
        address: str,
        on_notify_price_sched: Callable[[SubscriptionId], Coroutine[None, None, None]],
    ) -> None:
        self.address = address
        self.server: Server
        self.on_notify_price_sched = on_notify_price_sched
        self._tasks = set()

    async def connect(self):
        self.server = Server(self.address)
        self.server.notify_price_sched = self._notify_price_sched
        task = await self.server.ws_connect()
        task.add_done_callback(Pythd._on_connection_done)
        self._tasks.add(task)

    @staticmethod
    def _on_connection_done(task):
        log.error("pythd connection closed")
        if not task.cancelled() and task.exception() is not None:
            e = task.exception()
            traceback.print_exception(None, e, e.__traceback__)
        sys.exit(1)

    async def subscribe_price_sched(self, account: str) -> int:
        subscription = (await self.server.subscribe_price_sched(account=account))[
            "subscription"
        ]
        log.debug(
            "subscribed to price_sched", account=account, subscription=subscription
        )
        return subscription

    def _notify_price_sched(self, subscription: int) -> None:
        log.debug("notify_price_sched RPC call received", subscription=subscription)
        task = asyncio.get_event_loop().create_task(
            self.on_notify_price_sched(subscription)
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def all_products(self) -> List[Product]:
        result = await self.server.get_product_list()
        return [Product.from_dict(d) for d in result]

    async def update_price(
        self, account: str, price: int, conf: int, status: str
    ) -> None:
        await self.server.update_price(
            account=account, price=price, conf=conf, status=status
        )
