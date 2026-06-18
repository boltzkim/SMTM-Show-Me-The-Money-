"""Dataclass models shared by SMTM modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from .utils import DECIMAL_ZERO, make_id, parse_datetime, to_decimal, utc_now


@dataclass(frozen=True)
class CandleInfo:
    market: str
    date_time: datetime
    opening_price: Decimal
    high_price: Decimal
    low_price: Decimal
    closing_price: Decimal
    acc_price: Decimal = DECIMAL_ZERO
    acc_volume: Decimal = DECIMAL_ZERO

    @classmethod
    def from_mapping(cls, payload: dict[str, Any], default_market: str | None = None) -> "CandleInfo":
        market = str(payload.get("market") or default_market or "").strip()
        if not market:
            raise ValueError("market is required")
        date_value = payload.get("date_time") or payload.get("candle_date_time_utc")
        if date_value is None:
            raise ValueError("date_time is required")
        return cls(
            market=market,
            date_time=parse_datetime(date_value),
            opening_price=to_decimal(payload.get("opening_price", payload.get("open"))),
            high_price=to_decimal(payload.get("high_price", payload.get("high"))),
            low_price=to_decimal(payload.get("low_price", payload.get("low"))),
            closing_price=to_decimal(
                payload.get("closing_price", payload.get("trade_price", payload.get("close")))
            ),
            acc_price=to_decimal(
                payload.get("acc_price", payload.get("candle_acc_trade_price", 0)),
                default=DECIMAL_ZERO,
            ),
            acc_volume=to_decimal(
                payload.get("acc_volume", payload.get("candle_acc_trade_volume", payload.get("volume", 0))),
                default=DECIMAL_ZERO,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "market": self.market,
            "date_time": self.date_time.isoformat(),
            "opening_price": self.opening_price,
            "high_price": self.high_price,
            "low_price": self.low_price,
            "closing_price": self.closing_price,
            "acc_price": self.acc_price,
            "acc_volume": self.acc_volume,
        }


@dataclass
class AccountInfo:
    cash: Decimal
    balances: dict[str, Decimal] = field(default_factory=dict)
    average_prices: dict[str, Decimal] = field(default_factory=dict)
    valuation: Decimal = DECIMAL_ZERO
    captured_at: datetime = field(default_factory=utc_now)

    @classmethod
    def empty(cls, cash: Decimal | int | str) -> "AccountInfo":
        cash_decimal = to_decimal(cash)
        return cls(cash=cash_decimal, valuation=cash_decimal)

    def balance_for(self, market: str) -> Decimal:
        return self.balances.get(market, DECIMAL_ZERO)

    def copy(self) -> "AccountInfo":
        return AccountInfo(
            cash=self.cash,
            balances=dict(self.balances),
            average_prices=dict(self.average_prices),
            valuation=self.valuation,
            captured_at=self.captured_at,
        )

    def mark_to_market(self, candles: dict[str, CandleInfo] | CandleInfo | None = None) -> "AccountInfo":
        prices: dict[str, Decimal] = {}
        if isinstance(candles, CandleInfo):
            prices[candles.market] = candles.closing_price
        elif isinstance(candles, dict):
            prices = {market: candle.closing_price for market, candle in candles.items()}

        value = self.cash
        for market, amount in self.balances.items():
            value += amount * prices.get(market, self.average_prices.get(market, DECIMAL_ZERO))
        self.valuation = value
        self.captured_at = utc_now()
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "cash": self.cash,
            "balances": self.balances,
            "average_prices": self.average_prices,
            "valuation": self.valuation,
            "captured_at": self.captured_at.isoformat(),
        }


@dataclass(frozen=True)
class TradeRequest:
    strategy_id: str
    type: str
    market: str
    price: Decimal
    amount: Decimal
    order_type: str = "limit"
    reason: str = ""
    request_id: str = field(default_factory=lambda: make_id("req"))
    client_order_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    def notional(self) -> Decimal:
        return self.price * self.amount

    def with_amount(self, amount: Decimal) -> "TradeRequest":
        return TradeRequest(
            strategy_id=self.strategy_id,
            type=self.type,
            market=self.market,
            price=self.price,
            amount=amount,
            order_type=self.order_type,
            reason=self.reason,
            request_id=self.request_id,
            client_order_id=self.client_order_id,
            created_at=self.created_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "strategy_id": self.strategy_id,
            "type": self.type,
            "market": self.market,
            "price": self.price,
            "amount": self.amount,
            "order_type": self.order_type,
            "reason": self.reason,
            "client_order_id": self.client_order_id,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class OrderResult:
    request_id: str
    market: str
    side: str
    status: str
    exchange_order_id: str
    filled_price: Decimal = DECIMAL_ZERO
    filled_amount: Decimal = DECIMAL_ZERO
    fee: Decimal = DECIMAL_ZERO
    reason: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "market": self.market,
            "side": self.side,
            "status": self.status,
            "exchange_order_id": self.exchange_order_id,
            "filled_price": self.filled_price,
            "filled_amount": self.filled_amount,
            "fee": self.fee,
            "reason": self.reason,
            "raw": self.raw,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class RiskDecision:
    accepted: bool
    rule_id: str = "OK"
    reason: str = "accepted"

    def to_dict(self) -> dict[str, Any]:
        return {"accepted": self.accepted, "rule_id": self.rule_id, "reason": self.reason}


@dataclass(frozen=True)
class Event:
    event_type: str
    run_id: str
    payload: dict[str, Any]
    event_id: str = field(default_factory=lambda: make_id("evt"))
    created_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "event_type": self.event_type,
            "payload": self.payload,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class ReturnRecord:
    run_id: str
    record_time: datetime
    asset_value: Decimal
    cumulative_return: Decimal
    price_change_ratio: Decimal
    item_return: Decimal = DECIMAL_ZERO

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "record_time": self.record_time.isoformat(),
            "asset_value": self.asset_value,
            "cumulative_return": self.cumulative_return,
            "price_change_ratio": self.price_change_ratio,
            "item_return": self.item_return,
        }

