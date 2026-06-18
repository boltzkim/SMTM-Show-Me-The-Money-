"""Pre-order risk management."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from .models import AccountInfo, CandleInfo, RiskDecision, TradeRequest
from .utils import DECIMAL_ZERO, parse_datetime, to_decimal, utc_now


class BasicRiskManager:
    def __init__(self) -> None:
        self.min_order_krw = Decimal("5000")
        self.max_order_krw = Decimal("50000")
        self.max_open_orders = 1
        self.max_position_ratio = Decimal("0.5")
        self.daily_loss_limit_ratio = Decimal("0.03")
        self.stale_data_seconds = 180
        self.order_cooldown_seconds = 0
        self.emergency_stop = False
        self._last_order_at: datetime | None = None

    def initialize(self, config: dict) -> None:
        self.min_order_krw = to_decimal(config.get("min_order_krw", self.min_order_krw))
        self.max_order_krw = to_decimal(config.get("max_order_krw", self.max_order_krw))
        self.max_open_orders = int(config.get("max_open_orders", self.max_open_orders))
        self.max_position_ratio = to_decimal(config.get("max_position_ratio", self.max_position_ratio))
        self.daily_loss_limit_ratio = to_decimal(
            config.get("daily_loss_limit_ratio", self.daily_loss_limit_ratio)
        )
        self.stale_data_seconds = int(config.get("stale_data_seconds", self.stale_data_seconds))
        self.order_cooldown_seconds = int(config.get("order_cooldown_seconds", self.order_cooldown_seconds))
        self.emergency_stop = bool(config.get("emergency_stop", self.emergency_stop))

    def set_emergency_stop(self, enabled: bool = True) -> None:
        self.emergency_stop = enabled

    def validate(self, request: TradeRequest, account: AccountInfo, context: dict) -> RiskDecision:
        if request.type == "hold":
            return RiskDecision(True)
        if self.emergency_stop:
            return RiskDecision(False, "EMERGENCY_STOP", "emergency stop is enabled")
        if request.type not in {"buy", "sell", "cancel"}:
            return RiskDecision(False, "UNKNOWN_REQUEST_TYPE", f"unsupported request type: {request.type}")
        if request.type == "cancel":
            return RiskDecision(True)

        active_orders = context.get("active_orders", [])
        if len(active_orders) >= self.max_open_orders:
            return RiskDecision(False, "MAX_OPEN_ORDERS", "open order limit reached")
        for active in active_orders:
            if active.market == request.market and active.type == request.type:
                return RiskDecision(False, "DUPLICATE_ORDER", "same market and side already has an open order")

        stale_decision = self._check_stale_data(context)
        if stale_decision is not None:
            return stale_decision

        if self._last_order_at and self.order_cooldown_seconds:
            now = parse_datetime(context.get("now", utc_now()))
            elapsed = (now - self._last_order_at).total_seconds()
            if elapsed < self.order_cooldown_seconds:
                return RiskDecision(False, "ORDER_COOLDOWN", "order cooldown is active")

        notional = request.notional()
        if notional < self.min_order_krw:
            return RiskDecision(False, "MIN_ORDER", "order value is below minimum")
        if notional > self.max_order_krw:
            return RiskDecision(False, "MAX_ORDER", "order value exceeds max_order_krw")

        if request.type == "buy":
            fee_buffer = to_decimal(context.get("fee_rate", "0")) * notional
            if account.cash < notional + fee_buffer:
                return RiskDecision(False, "INSUFFICIENT_CASH", "cash is not enough for order plus fee")
            position_after = self._position_value(account, request.market, context) + notional
            total_value = max(account.valuation, account.cash, Decimal("1"))
            if position_after / total_value > self.max_position_ratio:
                return RiskDecision(False, "MAX_POSITION_RATIO", "position ratio would exceed limit")

        if request.type == "sell" and account.balance_for(request.market) < request.amount:
            return RiskDecision(False, "INSUFFICIENT_BALANCE", "asset balance is not enough")

        daily_start_value = to_decimal(context.get("daily_start_value", account.valuation or account.cash))
        current_value = account.valuation or account.cash
        if daily_start_value > DECIMAL_ZERO:
            loss_ratio = (daily_start_value - current_value) / daily_start_value
            if loss_ratio > self.daily_loss_limit_ratio:
                return RiskDecision(False, "DAILY_LOSS_LIMIT", "daily loss limit exceeded")

        self._last_order_at = parse_datetime(context.get("now", utc_now()))
        return RiskDecision(True)

    def _check_stale_data(self, context: dict) -> RiskDecision | None:
        mode = context.get("mode", "simulation")
        if mode == "simulation":
            return None
        candle = context.get("candle")
        if not isinstance(candle, CandleInfo):
            return RiskDecision(False, "MISSING_CANDLE", "latest candle is missing")
        now = parse_datetime(context.get("now", utc_now()))
        age = (now - candle.date_time).total_seconds()
        if age > self.stale_data_seconds:
            return RiskDecision(False, "STALE_DATA", "market data is stale")
        return None

    @staticmethod
    def _position_value(account: AccountInfo, market: str, context: dict) -> Decimal:
        candle = context.get("candle")
        if isinstance(candle, CandleInfo) and candle.market == market:
            price = candle.closing_price
        else:
            price = account.average_prices.get(market, DECIMAL_ZERO)
        return account.balance_for(market) * price


def build_risk_manager(config: dict) -> BasicRiskManager:
    risk_manager = BasicRiskManager()
    risk_manager.initialize(config)
    return risk_manager

