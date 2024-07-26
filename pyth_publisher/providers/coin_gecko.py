import asyncio
from math import floor
import time
from typing import Dict, List, Optional
from pycoingecko import CoinGeckoAPI
from structlog import get_logger

from pyth_publisher.provider import Price, Provider, Symbol
from ..config import CoinGeckoConfig

log = get_logger()

Id = str  # The "API id" of the CoinGecko price, listed on CoinGecko page for each coin.

USD = "usd"


class CoinGecko(Provider):
    def __init__(self, config: CoinGeckoConfig) -> None:
        self._api: CoinGeckoAPI = CoinGeckoAPI()
        self._prices: Dict[Id, Price] = {}
        self._symbol_to_id: Dict[Symbol, Id] = {
            product.symbol: product.coin_gecko_id for product in config.products
        }
        self._config = config

    def upd_products(self, product_symbols: List[Symbol]) -> None:
        new_prices = {}
        for coin_gecko_product in self._config.products:
            if coin_gecko_product.symbol in product_symbols:
                id = coin_gecko_product.coin_gecko_id
                new_prices[id] = self._prices.get(id, None)
            else:
                raise ValueError(
                    f"{coin_gecko_product.symbol} not found in available products"  # noqa: E713
                )

        self._prices = new_prices

    async def _update_loop(self) -> None:
        while True:
            self._update_prices()
            await asyncio.sleep(self._config.update_interval_secs)

    def _update_prices(self) -> None:
        result = self._api.get_price(
            ids=list(self._prices.keys()), vs_currencies=USD, precision=18
        )
        for id_, prices in result.items():
            price = prices[USD]
            self._prices[id_] = Price(
                price,
                price * self._config.confidence_ratio_bps / 10000,
                floor(time.time()),
            )
        log.info("updated prices from CoinGecko", prices=self._prices)

    def _get_price(self, id: Id) -> Optional[Price]:
        return self._prices.get(id, None)

    def latest_price(self, symbol: Symbol) -> Optional[Price]:
        id = self._symbol_to_id.get(symbol)
        if id is None:
            return None
        return self._get_price(id)
