from abc import ABC, abstractmethod
import asyncio
from dataclasses import dataclass
from typing import List, Optional


PythSymbol = str  # e.g., Crypto.FDUSD/USD
Symbol = str  # e.g., BTC
UnixTimestamp = int


@dataclass
class Price:
    price: float
    conf: float
    timestamp: UnixTimestamp


class Provider(ABC):
    _update_loop_task = None

    @abstractmethod
    def upd_products(self, product_symbols: List[PythSymbol]): ...

    def start(self) -> None:
        self._update_loop_task = asyncio.create_task(self._update_loop())

    @abstractmethod
    async def _update_loop(self): ...

    @abstractmethod
    def latest_price(self, symbol: PythSymbol) -> Optional[Price]: ...
