"""SQLite persistence used by analyzer and recovery workflows."""

from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from typing import Any

from .models import AccountInfo, CandleInfo, Event, OrderResult, ReturnRecord, TradeRequest
from .utils import json_safe


class SQLiteRepository:
    def __init__(self, sqlite_path: str | Path) -> None:
        self.path = Path(sqlite_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.initialize()

    def initialize(self) -> None:
        self.connection.executescript(
            """
            create table if not exists market_candles (
                market text not null,
                interval text not null,
                candle_time text not null,
                open text not null,
                high text not null,
                low text not null,
                close text not null,
                acc_price text not null,
                acc_volume text not null,
                primary key (market, interval, candle_time)
            );

            create table if not exists simulation_runs (
                run_id text primary key,
                title text,
                strategy_id text,
                config_json text not null,
                started_at text not null,
                ended_at text,
                status text not null
            );

            create table if not exists trade_requests (
                request_id text primary key,
                run_id text not null,
                strategy_id text not null,
                market text not null,
                side text not null,
                price text not null,
                amount text not null,
                status text not null,
                reason text,
                created_at text not null
            );

            create table if not exists orders (
                order_id text primary key,
                request_id text not null,
                exchange text not null,
                exchange_order_id text,
                client_order_id text,
                status text not null,
                submitted_at text not null
            );

            create table if not exists fills (
                fill_id text primary key,
                order_id text not null,
                filled_price text not null,
                filled_amount text not null,
                fee text not null,
                filled_at text not null
            );

            create table if not exists account_snapshots (
                snapshot_id integer primary key autoincrement,
                run_id text not null,
                cash text not null,
                balances_json text not null,
                valuation text not null,
                captured_at text not null
            );

            create table if not exists return_records (
                run_id text not null,
                record_time text not null,
                cumulative_return text not null,
                item_return text not null,
                price_change_ratio text not null,
                asset_value text not null
            );

            create table if not exists audit_logs (
                event_id text primary key,
                run_id text not null,
                event_type text not null,
                payload_json text not null,
                created_at text not null
            );

            create table if not exists alerts (
                alert_id text primary key,
                severity text not null,
                channel text not null,
                message text not null,
                acknowledged_at text
            );
            """
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def record_run_start(self, run_id: str, title: str, strategy_id: str, config: dict, started_at: str) -> None:
        self.connection.execute(
            """
            insert or replace into simulation_runs
            (run_id, title, strategy_id, config_json, started_at, status)
            values (?, ?, ?, ?, ?, ?)
            """,
            (run_id, title, strategy_id, _json(config), started_at, "RUNNING"),
        )
        self.connection.commit()

    def record_run_end(self, run_id: str, ended_at: str, status: str) -> None:
        self.connection.execute(
            "update simulation_runs set ended_at = ?, status = ? where run_id = ?",
            (ended_at, status, run_id),
        )
        self.connection.commit()

    def record_candle(self, candle: CandleInfo, interval: str) -> None:
        self.connection.execute(
            """
            insert or replace into market_candles
            (market, interval, candle_time, open, high, low, close, acc_price, acc_volume)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candle.market,
                interval,
                candle.date_time.isoformat(),
                str(candle.opening_price),
                str(candle.high_price),
                str(candle.low_price),
                str(candle.closing_price),
                str(candle.acc_price),
                str(candle.acc_volume),
            ),
        )

    def record_trade_request(self, run_id: str, request: TradeRequest, status: str = "accepted") -> None:
        self.connection.execute(
            """
            insert or replace into trade_requests
            (request_id, run_id, strategy_id, market, side, price, amount, status, reason, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request.request_id,
                run_id,
                request.strategy_id,
                request.market,
                request.type,
                str(request.price),
                str(request.amount),
                status,
                request.reason,
                request.created_at.isoformat(),
            ),
        )
        self.connection.commit()

    def record_order_result(self, run_id: str, result: OrderResult, exchange: str) -> None:
        order_id = result.exchange_order_id or result.request_id
        self.connection.execute(
            """
            insert or replace into orders
            (order_id, request_id, exchange, exchange_order_id, client_order_id, status, submitted_at)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_id,
                result.request_id,
                exchange,
                result.exchange_order_id,
                result.raw.get("client_order_id"),
                result.status,
                result.created_at.isoformat(),
            ),
        )
        if result.filled_amount > Decimal("0"):
            self.connection.execute(
                """
                insert into fills
                (fill_id, order_id, filled_price, filled_amount, fee, filled_at)
                values (?, ?, ?, ?, ?, ?)
                """,
                (
                    f"fill-{result.request_id}-{result.created_at.timestamp()}",
                    order_id,
                    str(result.filled_price),
                    str(result.filled_amount),
                    str(result.fee),
                    result.created_at.isoformat(),
                ),
            )
        self.connection.commit()

    def record_balance(self, run_id: str, account: AccountInfo) -> None:
        self.connection.execute(
            """
            insert into account_snapshots
            (run_id, cash, balances_json, valuation, captured_at)
            values (?, ?, ?, ?, ?)
            """,
            (
                run_id,
                str(account.cash),
                _json(account.balances),
                str(account.valuation),
                account.captured_at.isoformat(),
            ),
        )
        self.connection.commit()

    def record_return(self, record: ReturnRecord) -> None:
        self.connection.execute(
            """
            insert into return_records
            (run_id, record_time, cumulative_return, item_return, price_change_ratio, asset_value)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                record.run_id,
                record.record_time.isoformat(),
                str(record.cumulative_return),
                str(record.item_return),
                str(record.price_change_ratio),
                str(record.asset_value),
            ),
        )
        self.connection.commit()

    def record_event(self, event: Event) -> None:
        self.connection.execute(
            """
            insert or replace into audit_logs
            (event_id, run_id, event_type, payload_json, created_at)
            values (?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.run_id,
                event.event_type,
                _json(event.payload),
                event.created_at.isoformat(),
            ),
        )
        self.connection.commit()


def _json(payload: Any) -> str:
    return json.dumps(json_safe(payload), ensure_ascii=False, sort_keys=True)

