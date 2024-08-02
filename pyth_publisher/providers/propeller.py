import asyncio
import re
from datetime import datetime
from decimal import Decimal
from math import floor
from typing import Dict, List, Optional

from drfs import DRPath
import pandas as pd
from core.models.evm.ethereum_token import EthereumToken
from storage.token_prices import RedisPricesGateway

from pyth_publisher.config import PropellerConfig
from pyth_publisher.provider import Price, Provider, PythSymbol, Symbol

from logging import getLogger

log = getLogger()

USD = "usd"

PYTH_SYMBOL_REGEX = r"Crypto\.(\w+)/USD"

Address = str


class Propeller(Provider):
    def __init__(
        self,
        config: PropellerConfig,
        token_symbol_to_address: Optional[dict[Symbol, Address]] = None,
        quote_amount: Optional[int] = None,
    ) -> None:
        self._prices: dict[Address, Price] = {}
        self._config = config
        self._token_symbol_to_address: dict[Symbol, Address] = (
            token_symbol_to_address
            if token_symbol_to_address
            else self._get_token_info()
        )
        self._supported_products: set[Symbol] = set()
        self._redis_gtw = RedisPricesGateway()
        self._quote_amount = quote_amount
        self._quote_token = EthereumToken(
            symbol="USDC",
            address="0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
            decimals=6,
        )

    def upd_products(self, product_symbols: List[PythSymbol]) -> None:
        """Update our provider with new products from Pyth"""
        for product in product_symbols:
            symbol = self._get_token_symbol_from_pyth_symbol(product)
            if symbol is not None:
                if symbol not in self._token_symbol_to_address:
                    log.warning(f"Symbol {symbol} not found in token info")
                else:
                    self._supported_products.add(symbol)

    @staticmethod
    def _get_token_symbol_from_pyth_symbol(pyth_symbol: PythSymbol) -> Optional[Symbol]:
        pattern = re.compile(PYTH_SYMBOL_REGEX)
        symbol = pattern.findall(pyth_symbol)
        if len(symbol) > 0:
            return symbol[0]
        return None

    async def _update_loop(self) -> None:
        while True:
            await self._update_prices()
            await asyncio.sleep(self._config.update_interval_secs)

    async def _update_prices(self) -> None:
        prices = await self._redis_gtw.get_token_prices(self._quote_amount)
        spreads = await self._redis_gtw.get_token_spreads(self._quote_amount)
        quote_token_price_in_eth = prices[self._quote_token]
        quote_token_spread_relative_to_eth = spreads[self._quote_token]
        for token, base_token_price_in_eth in prices.items():
            if token.symbol in self._supported_products:
                price = base_token_price_in_eth / quote_token_price_in_eth
                base_token_spread_relative_to_eth = spreads[token]
                spread = self._compute_spread(
                    base_token_price_in_eth,
                    quote_token_price_in_eth,
                    base_token_spread_relative_to_eth,
                    quote_token_spread_relative_to_eth,
                )
                self._prices[token.address] = Price(
                    float(price), float(spread), floor(datetime.utcnow().timestamp())
                )
        log.info(f"Updated prices from Redis: {self._prices}")

    def latest_price(self, symbol: PythSymbol) -> Optional[Price]:
        symbol = self._get_token_symbol_from_pyth_symbol(symbol)
        address = self._token_symbol_to_address.get(symbol)
        if address is None:
            return None
        return self._prices.get(address)

    @staticmethod
    def _get_token_info() -> dict[Symbol, str]:
        """Get a mapping of supported token symbols to addresses from s3."""
        supported_tokens_path = DRPath(
            "s3://defibot-data/price-oracle-evaluation/symbols_to_address.csv"
        )
        supported_tokens_df = pd.read_csv(supported_tokens_path)
        supported_tokens_dict = supported_tokens_df.set_index("symbol")[
            "address"
        ].to_dict()
        return supported_tokens_dict

    @staticmethod
    def _compute_spread(
        base_token_price_in_eth: Decimal,
        quote_token_price_in_eth: Decimal,
        base_token_spread_relative_to_eth: Decimal,
        quote_token_spread_relative_to_eth: Decimal,
    ) -> Decimal:
        # copied from defibot
        """Return the price spread of the base token in terms of the quote token.

        Example
        --------
                Calculate the Spread for WBTC (base token) -> USDC (quote token)
                                (considering an extreme case)

                         0.057 WBTC                     3100 USDC
        (price of selling WBTC / buying ETH)    (price of selling USDC / buying ETH)
                             ⟍                      ⟋
                                ⟍                ⟋
                                   ↘          ↙
           (WBTC spread: 0.001)         1 ETH          (USDC spread: 100)
         (WBTC mid-price: 0.056)   ⟋        ⟍      (USDC mid-price: 3000)
                                ⟋              ⟍
                             ↙                    ↘
                        0.055 WBTC                   2900 USDC
        (price of buying WBTC / selling ETH)        (price of buying USDC / selling ETH)

         Sell 1 WBTC to get X USDC:
         We sell 0.057 WBTC at the best price to get 1 ETH,
         then we sell 1 ETH at the best price to get 2900 USDC.
         0.057 WBTC : 2900 USDC -> 1 WBTC = 50877.19298 USDC

         Sell X USDC to get 1 WBTC:
         We sell 3100 USDC at the best price to get 1 ETH,
         then we sell 1 ETH at the best price to get 0.055 WBTC.
         3100 USDC : 0.055 WBTC -> 1 WBTC = 56363.63636 USDC

         In this case the final spread should be around 5486.44 USDC (the difference
         between the two prices)
        """
        # How much of the base and quote token 1 ETH will buy
        eth_price_in_base_token = 1 / base_token_price_in_eth
        eth_price_in_quote_token = 1 / quote_token_price_in_eth

        sell_base_buy_eth_price = (
            eth_price_in_base_token + base_token_spread_relative_to_eth
        )
        buy_base_sell_eth_price = (
            eth_price_in_base_token - base_token_spread_relative_to_eth
        )
        sell_quote_buy_eth_price = (
            eth_price_in_quote_token + quote_token_spread_relative_to_eth
        )
        buy_quote_sell_eth_price = (
            eth_price_in_quote_token - quote_token_spread_relative_to_eth
        )

        # Price to sell the base and buy the quote token
        sell_base_price = buy_quote_sell_eth_price / sell_base_buy_eth_price
        # Price to buy the base and sell the quote token
        buy_base_price = sell_quote_buy_eth_price / buy_base_sell_eth_price
        return buy_base_price - sell_base_price
