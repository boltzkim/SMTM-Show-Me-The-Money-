"""Protocols describing module boundaries."""

from __future__ import annotations

from typing import Protocol

from .models import AccountInfo, CandleInfo, OrderResult, RiskDecision, TradeRequest


class DataProvider(Protocol):
    def initialize(self, config: dict) -> None:
        ...

    def get_info(self) -> CandleInfo | None:
        ...


class Strategy(Protocol):
    strategy_id: str

    def initialize(self, budget: int, min_order_price: int, params: dict) -> None:
        ...

    def update_trading_info(self, info: CandleInfo) -> None:
        ...

    def get_request(self, account: AccountInfo) -> list[TradeRequest]:
        ...

    def update_result(self, result: OrderResult) -> None:
        ...


class RiskManager(Protocol):
    def validate(self, request: TradeRequest, account: AccountInfo, context: dict) -> RiskDecision:
        ...


class Trader(Protocol):
    def initialize(self, config: dict) -> None:
        ...

    def send_request(self, request: TradeRequest) -> OrderResult | None:
        ...

    def get_account_info(self) -> AccountInfo:
        ...

    def get_order_status(self, order_id: str) -> OrderResult | None:
        ...

    def cancel_order(self, order_id: str) -> OrderResult:
        ...


class Analyzer(Protocol):
    def record_event(self, event: dict) -> None:
        ...

    def record_balance(self, account: AccountInfo) -> None:
        ...

    def get_return_report(self, output_path: str | None = None) -> dict:
        ...

