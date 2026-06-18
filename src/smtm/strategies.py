"""Trading strategy implementations."""

from __future__ import annotations

from collections import deque
from datetime import timedelta
from decimal import Decimal
from statistics import mean

from .exceptions import ConfigurationError
from .models import AccountInfo, CandleInfo, OrderResult, TradeRequest
from .utils import DECIMAL_ZERO, quantize_down, to_decimal


class SmaCrossStrategy:
    """Simple moving-average cross strategy for MVP validation."""

    def __init__(self) -> None:
        self.strategy_id = "sma-v1"
        self.short_window = 20
        self.long_window = 60
        self.order_ratio = Decimal("0.1")
        self.avoid_rebuy_minutes = 0
        self.min_order_price = Decimal("0")
        self.history: deque[CandleInfo] = deque()
        self.last_buy_at = None
        self.last_result: OrderResult | None = None

    def initialize(self, budget: int, min_order_price: int, params: dict) -> None:
        self.short_window = int(params.get("short_window", self.short_window))
        self.long_window = int(params.get("long_window", self.long_window))
        self.order_ratio = to_decimal(params.get("order_ratio", self.order_ratio))
        self.avoid_rebuy_minutes = int(params.get("avoid_rebuy_minutes", self.avoid_rebuy_minutes))
        self.min_order_price = to_decimal(min_order_price)
        if self.short_window <= 0 or self.long_window <= 0:
            raise ConfigurationError("SMA windows must be positive")
        if self.short_window >= self.long_window:
            raise ConfigurationError("short_window must be less than long_window")
        if not Decimal("0") < self.order_ratio <= Decimal("1"):
            raise ConfigurationError("order_ratio must be between 0 and 1")

    def update_trading_info(self, info: CandleInfo) -> None:
        self.history.append(info)
        max_len = self.long_window + 2
        while len(self.history) > max_len:
            self.history.popleft()

    def get_request(self, account: AccountInfo) -> list[TradeRequest]:
        if len(self.history) < self.long_window + 1:
            return []
        candles = list(self.history)
        current = candles[-1]
        previous_diff = self._ma(candles[:-1], self.short_window) - self._ma(candles[:-1], self.long_window)
        current_diff = self._ma(candles, self.short_window) - self._ma(candles, self.long_window)

        if previous_diff <= DECIMAL_ZERO < current_diff:
            return self._buy_requests(current, account)
        if previous_diff >= DECIMAL_ZERO > current_diff:
            return self._sell_requests(current, account)
        return []

    def update_result(self, result: OrderResult) -> None:
        self.last_result = result
        if result.side == "buy" and result.status in {"filled", "partially_filled"}:
            self.last_buy_at = result.created_at

    def _buy_requests(self, candle: CandleInfo, account: AccountInfo) -> list[TradeRequest]:
        if self.last_buy_at and self.avoid_rebuy_minutes:
            elapsed = candle.date_time - self.last_buy_at
            if elapsed < timedelta(minutes=self.avoid_rebuy_minutes):
                return []
        order_value = account.cash * self.order_ratio
        if order_value < self.min_order_price:
            return []
        amount = quantize_down(order_value / candle.closing_price)
        if amount <= DECIMAL_ZERO:
            return []
        return [
            TradeRequest(
                strategy_id=self.strategy_id,
                type="buy",
                market=candle.market,
                price=candle.closing_price,
                amount=amount,
                order_type="limit",
                reason="short_sma_cross_up",
            )
        ]

    def _sell_requests(self, candle: CandleInfo, account: AccountInfo) -> list[TradeRequest]:
        balance = account.balance_for(candle.market)
        amount = quantize_down(balance * self.order_ratio)
        if amount <= DECIMAL_ZERO:
            return []
        if amount * candle.closing_price < self.min_order_price:
            return []
        return [
            TradeRequest(
                strategy_id=self.strategy_id,
                type="sell",
                market=candle.market,
                price=candle.closing_price,
                amount=amount,
                order_type="limit",
                reason="short_sma_cross_down",
            )
        ]

    @staticmethod
    def _ma(candles: list[CandleInfo], window: int) -> Decimal:
        sample = candles[-window:]
        value = mean(float(candle.closing_price) for candle in sample)
        return Decimal(str(value))


class HoldStrategy:
    """A no-op strategy useful for smoke tests and dry-run monitoring."""

    strategy_id = "hold-v1"

    def initialize(self, budget: int, min_order_price: int, params: dict) -> None:
        return None

    def update_trading_info(self, info: CandleInfo) -> None:
        return None

    def get_request(self, account: AccountInfo) -> list[TradeRequest]:
        return []

    def update_result(self, result: OrderResult) -> None:
        return None


def build_strategy(config: dict, budget: int, min_order_price: int) -> SmaCrossStrategy | HoldStrategy:
    name = str(config.get("name", "SMA")).lower()
    if name == "sma":
        strategy = SmaCrossStrategy()
    elif name == "hold":
        strategy = HoldStrategy()
    else:
        raise ConfigurationError(f"unknown strategy: {name}")
    strategy.initialize(budget=budget, min_order_price=min_order_price, params=config.get("params", {}))
    return strategy

