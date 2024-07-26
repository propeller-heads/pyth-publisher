from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, AsyncMock

import pytest
import fakeredis.aioredis
from storage.gateways.redis import RedisTokenPricesGW
from storage.key_manager import RedisKeyManager
from storage.token_prices import RedisPricesGateway
from core.models.evm.ethereum_token import EthereumToken
from pyth_publisher.config import PropellerConfig
from pyth_publisher.providers.propeller import Propeller


@pytest.fixture()
def pyth_products():
    # example of products from Pyth
    return [
        "Crypto.USDC/USD",
        "Crypto.DAI/USD",
        "Crypto.USDT/USD",
        "Crypto.STX/USD",
        "Crypto.CAKE/USD",
        "Crypto.ALGO/USD",
        "Equity.US.HD/USD",
        "Crypto.QTUM/USD",
        "FX.USD/JPY",
        "Rates.US10Y",
        "Metal.XAG/USD",
        "Commodities.BRENT1M",
    ]


def test_upd_products(pyth_products):
    token_symbol_to_address = {
        "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "DAI": "0x6B175474E89094C44Da98b954EedeAC495271d0F",
        "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
    }
    provider = Propeller(
        PropellerConfig(), token_symbol_to_address=token_symbol_to_address
    )
    provider.upd_products(pyth_products)
    assert provider._supported_products == {"USDC", "DAI", "USDT"}


def test_compute_spread_stable_token_pair():
    # copied from defibot
    """Calculate the Spread for DAI (base token) -> USDC (quote token)
                            (considering an extreme case)

                     3200 DAI                     3100 USDC
    (price of selling DAI / buying ETH)     (price of selling USDC / buying ETH)
                         ⟍                      ⟋
                            ⟍                ⟋
                               ↘          ↙
       (DAI spread: 200)           1 ETH          (USDC spread: 100)
     (DAI mid-price: 3000)      ⟋        ⟍      (USDC mid-price: 3000)
                            ⟋              ⟍
                         ↙                    ↘
                    2800 DAI                   2900 USDC
    (price of buying DAI / selling ETH)           (price of buying USDC / selling ETH)

     Sell 1 DAI to get X USDC:
     We sell 3200 DAI at the best price to get 1 ETH,
     then we sell 1 ETH at the best price to get 2900 USDC.
     2900 USDC : 3200 DAI -> 1 DAI = 0.9062 USDC

     Sell X USDC to get 1 DAI:
     We sell 3100 USDC at the best price to get 1 ETH,
     then we sell 1 ETH at the best price to get 2800 DAI.
     2800 DAI : 3100 USDC -> 1 DAI = 1.1071 USDC

     In this case the final spread should be around 0.2 USDC
    """
    # Quote token
    usdc_price_in_eth = Decimal(1) / Decimal(3000)
    usdc_spread_relative_to_eth = Decimal(100)
    # Base token
    dai_price_in_eth = Decimal(1) / Decimal(3000)
    dai_spread_relative_to_eth = Decimal(200)
    provider = Propeller(PropellerConfig())
    spread = provider._compute_spread(
        base_token_price_in_eth=dai_price_in_eth,
        quote_token_price_in_eth=usdc_price_in_eth,
        base_token_spread_relative_to_eth=dai_spread_relative_to_eth,
        quote_token_spread_relative_to_eth=usdc_spread_relative_to_eth,
    )
    assert round(spread, 2) == Decimal("0.20")


def test_compute_spread_non_stable_token_pair():
    # copied from defibot
    """Calculate the Spread for WBTC (base token) -> USDC (quote token)
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
     We sell 0.057 USDC at the best price to get 1 ETH,
     then we sell 1 ETH at the best price to get 2900 USDC.
     0.057 WBTC : 2900 USDC -> 1 WBTC = 50877.19298 USDC

     Sell X USDC to get 1 WBTC:
     We sell 3100 USDC at the best price to get 1 ETH,
     then we sell 1 ETH at the best price to get 0.055 WBTC.
     3100 USDC : 0.055 WBTC -> 1 WBTC = 56363.63636 USDC

     In this case the final spread should be around 5486.44 USDC
    """
    # Quote token
    usdc_price_in_eth = Decimal(1) / Decimal(3000)
    usdc_spread_relative_to_eth = Decimal(100)
    # Base token
    wbtc_price_in_eth = Decimal(1) / Decimal(0.056)
    wbtc_spread_relative_to_eth = Decimal(0.001)
    provider = Propeller(PropellerConfig())
    spread = provider._compute_spread(
        base_token_price_in_eth=wbtc_price_in_eth,
        quote_token_price_in_eth=usdc_price_in_eth,
        base_token_spread_relative_to_eth=wbtc_spread_relative_to_eth,
        quote_token_spread_relative_to_eth=usdc_spread_relative_to_eth,
    )
    assert round(spread, 2) == Decimal("5486.44")


@pytest.mark.asyncio
async def test_update_prices():
    quote_amount = int(1e18)
    USDC = EthereumToken(
        symbol="USDC",
        address="0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
        decimals=6,
        gas=29000,
    )
    WBTC = EthereumToken(
        symbol="WBTC", address="0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", decimals=8
    )
    usdc_price = 3400 * 10**6
    usdc_spread = (100 * 10**6,)

    wbtc_price = 5_600_000
    wbtc_spread = int(0.001 * 10**8)

    mock_redis_gtw = MagicMock()
    # TODO: I have no idea why only the USDC price is being returned
    mock_redis_gtw.get_token_prices = AsyncMock(
        return_value={USDC: usdc_price, WBTC: wbtc_price}
    )
    mock_redis_gtw.get_token_spreads = AsyncMock(
        return_value={USDC: usdc_spread, WBTC: wbtc_spread}
    )
    provider = Propeller(PropellerConfig(), quote_amount=quote_amount)
    provider._supported_products = {"USDC", "WBTC"}
    provider._redis_gtw = mock_redis_gtw

    await provider._update_prices()
