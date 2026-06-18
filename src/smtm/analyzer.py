"""Event recording and return analysis."""

from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from .models import AccountInfo, CandleInfo, Event, OrderResult, ReturnRecord, TradeRequest
from .repository import SQLiteRepository
from .utils import DECIMAL_ZERO, json_safe, write_json


class TradingAnalyzer:
    def __init__(
        self,
        run_id: str,
        initial_asset_value: Decimal,
        repository: SQLiteRepository | None = None,
        interval: str = "1m",
        exchange: str = "simulation",
    ) -> None:
        self.run_id = run_id
        self.initial_asset_value = initial_asset_value
        self.repository = repository
        self.interval = interval
        self.exchange = exchange
        self.events: list[Event] = []
        self.candles: list[CandleInfo] = []
        self.requests: list[TradeRequest] = []
        self.order_results: list[OrderResult] = []
        self.balances: list[AccountInfo] = []
        self.return_records: list[ReturnRecord] = []

    def record_event(self, event: Event | dict[str, Any]) -> None:
        if isinstance(event, Event):
            item = event
        else:
            item = Event(
                event_type=str(event["event_type"]),
                run_id=str(event.get("run_id", self.run_id)),
                payload=dict(event.get("payload", {})),
            )
        self.events.append(item)
        if self.repository:
            self.repository.record_event(item)

    def record_candle(self, candle: CandleInfo) -> None:
        self.candles.append(candle)
        if self.repository:
            self.repository.record_candle(candle, self.interval)
        self.record_event(Event("MARKET_TICK", self.run_id, candle.to_dict()))

    def record_trade_request(self, request: TradeRequest, status: str = "accepted") -> None:
        self.requests.append(request)
        if self.repository:
            self.repository.record_trade_request(self.run_id, request, status)
        event_type = "ORDER_REQUEST" if status == "accepted" else "RISK_REJECT"
        payload = request.to_dict()
        payload["status"] = status
        self.record_event(Event(event_type, self.run_id, payload))

    def record_order_result(self, result: OrderResult) -> None:
        self.order_results.append(result)
        if self.repository:
            self.repository.record_order_result(self.run_id, result, self.exchange)
        event_type = "ORDER_FILL" if result.status in {"filled", "partially_filled"} else "ORDER_ACK"
        self.record_event(Event(event_type, self.run_id, result.to_dict()))

    def record_balance(self, account: AccountInfo, candle: CandleInfo | None = None) -> None:
        snapshot = account.copy().mark_to_market(candle)
        self.balances.append(snapshot)
        if self.repository:
            self.repository.record_balance(self.run_id, snapshot)
        self.record_event(Event("ACCOUNT_SNAPSHOT", self.run_id, snapshot.to_dict()))
        self._record_return(snapshot, candle)

    def _record_return(self, account: AccountInfo, candle: CandleInfo | None) -> None:
        if self.initial_asset_value <= DECIMAL_ZERO:
            cumulative_return = DECIMAL_ZERO
        else:
            cumulative_return = (account.valuation - self.initial_asset_value) / self.initial_asset_value
        price_change_ratio = DECIMAL_ZERO
        if candle and self.candles:
            first_price = self.candles[0].closing_price
            if first_price > DECIMAL_ZERO:
                price_change_ratio = (candle.closing_price - first_price) / first_price
        record = ReturnRecord(
            run_id=self.run_id,
            record_time=account.captured_at,
            asset_value=account.valuation,
            cumulative_return=cumulative_return,
            price_change_ratio=price_change_ratio,
        )
        self.return_records.append(record)
        if self.repository:
            self.repository.record_return(record)

    def get_return_report(self, output_path: str | None = None) -> dict[str, Any]:
        final_balance = self.balances[-1] if self.balances else AccountInfo.empty(self.initial_asset_value)
        cumulative_return = DECIMAL_ZERO
        if self.initial_asset_value > DECIMAL_ZERO:
            cumulative_return = (final_balance.valuation - self.initial_asset_value) / self.initial_asset_value
        report = {
            "run_id": self.run_id,
            "initial_asset_value": self.initial_asset_value,
            "final_asset_value": final_balance.valuation,
            "cumulative_return": cumulative_return,
            "max_drawdown": self._max_drawdown(),
            "trade_request_count": len(self.requests),
            "order_result_count": len(self.order_results),
            "fill_count": sum(1 for item in self.order_results if item.status in {"filled", "partially_filled"}),
            "reject_count": sum(1 for item in self.events if item.event_type == "RISK_REJECT"),
            "market_tick_count": len(self.candles),
            "started_at": self.candles[0].date_time.isoformat() if self.candles else None,
            "ended_at": self.candles[-1].date_time.isoformat() if self.candles else None,
            "return_records": [record.to_dict() for record in self.return_records],
            "fills": [result.to_dict() for result in self.order_results if result.filled_amount > DECIMAL_ZERO],
        }
        if output_path:
            target = Path(output_path)
            if target.suffix.lower() == ".csv":
                self.write_return_csv(target)
            else:
                write_json(target, report)
                self.write_return_csv(target.with_suffix(".csv"))
        return report

    def write_return_csv(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=[
                    "run_id",
                    "record_time",
                    "asset_value",
                    "cumulative_return",
                    "item_return",
                    "price_change_ratio",
                ],
            )
            writer.writeheader()
            for record in self.return_records:
                writer.writerow(json_safe(record.to_dict()))

    def _max_drawdown(self) -> Decimal:
        peak: Decimal | None = None
        max_drawdown = DECIMAL_ZERO
        for balance in self.balances:
            value = balance.valuation
            if peak is None or value > peak:
                peak = value
            if peak and peak > DECIMAL_ZERO:
                drawdown = (peak - value) / peak
                if drawdown > max_drawdown:
                    max_drawdown = drawdown
        return max_drawdown


def summarize_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    if not reports:
        return {"count": 0}
    returns = [Decimal(str(report["cumulative_return"])) for report in reports]
    sorted_reports = sorted(reports, key=lambda item: Decimal(str(item["cumulative_return"])), reverse=True)
    return {
        "count": len(reports),
        "average_return": Decimal(str(mean(float(item) for item in returns))),
        "return_stddev": Decimal(str(pstdev(float(item) for item in returns))) if len(returns) > 1 else DECIMAL_ZERO,
        "best": sorted_reports[0],
        "worst": sorted_reports[-1],
    }

