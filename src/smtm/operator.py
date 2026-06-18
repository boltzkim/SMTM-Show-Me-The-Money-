"""Operator orchestration and state model."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from time import sleep
from typing import Any

from .analyzer import TradingAnalyzer
from .data_provider import build_data_provider
from .exceptions import ConfigurationError
from .models import CandleInfo, Event, OrderResult, TradeRequest
from .repository import SQLiteRepository
from .risk import BasicRiskManager, build_risk_manager
from .strategies import build_strategy
from .trader import DryRunTrader, SimulationTrader, build_trader
from .utils import make_id, parse_datetime, to_decimal, utc_now


class OperatorState:
    INIT = "INIT"
    READY = "READY"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


class TradingOperator:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = deepcopy(config)
        self.state = OperatorState.INIT
        self.run_id = self.config.get("run_id") or make_id("run")
        self.data_provider = None
        self.strategy = None
        self.risk_manager: BasicRiskManager | None = None
        self.trader: SimulationTrader | DryRunTrader | None = None
        self.analyzer: TradingAnalyzer | None = None
        self.repository: SQLiteRepository | None = None
        self.last_error: str | None = None
        self.last_tick_at = None
        self.daily_start_value = Decimal("0")

    def initialize(self) -> None:
        mode = self.config.get("mode", "simulation")
        budget = int(self.config.get("budget", 0))
        currency = self.config.get("currency", "KRW-BTC")
        market_config = dict(self.config.get("market", {}))
        market_config.setdefault("budget", budget)
        market_config.setdefault("mode", mode)
        market_config.setdefault("dry_run", self.config.get("dry_run", True))

        data_config = dict(self.config.get("data", {}))
        data_config.setdefault("market", currency)
        data_config.setdefault("currency", currency)
        self._resolve_relative_path(data_config, "path")
        self.data_provider = build_data_provider(data_config)

        risk_config = self.config.get("risk", {})
        self.risk_manager = build_risk_manager(risk_config)
        min_order = int(to_decimal(risk_config.get("min_order_krw", 0)))
        self.strategy = build_strategy(self.config.get("strategy", {}), budget=budget, min_order_price=min_order)

        trader_config = {**market_config, "budget": budget, "mode": mode, "dry_run": self.config.get("dry_run", True)}
        self.trader = build_trader(trader_config)
        initial_account = self.trader.get_account_info()
        self.daily_start_value = initial_account.valuation

        repository_config = dict(self.config.get("repository", {}))
        sqlite_path = repository_config.get("sqlite_path")
        if sqlite_path:
            sqlite_path = str(self._resolve_path(sqlite_path))
            self.repository = SQLiteRepository(sqlite_path)

        self.analyzer = TradingAnalyzer(
            run_id=self.run_id,
            initial_asset_value=initial_account.valuation,
            repository=self.repository,
            interval=market_config.get("interval", "1m"),
            exchange=market_config.get("exchange", self.config.get("exchange", "simulation")),
        )
        if self.repository:
            self.repository.record_run_start(
                self.run_id,
                self.config.get("title", self.run_id),
                self.strategy.strategy_id,
                self.config,
                utc_now().isoformat(),
            )
        self.state = OperatorState.READY
        self._record_state("initialized")

    def start(self) -> None:
        if self.state == OperatorState.INIT:
            self.initialize()
        if self.state not in {OperatorState.READY, OperatorState.PAUSED}:
            raise ConfigurationError(f"operator cannot start from state {self.state}")
        self.state = OperatorState.RUNNING
        self._record_state("started")

    def pause(self) -> None:
        if self.state == OperatorState.RUNNING:
            self.state = OperatorState.PAUSED
            self._record_state("paused")

    def resume(self) -> None:
        if self.state == OperatorState.PAUSED:
            self.state = OperatorState.RUNNING
            self._record_state("resumed")

    def stop(self, reason: str = "user") -> None:
        self.state = OperatorState.STOPPED
        self._record_state(reason)
        if self.repository:
            self.repository.record_run_end(self.run_id, utc_now().isoformat(), self.state)
            self.repository.close()
            self.repository = None
            if self.analyzer:
                self.analyzer.repository = None

    def emergency_stop(self, reason: str = "emergency_stop") -> None:
        if self.risk_manager:
            self.risk_manager.set_emergency_stop(True)
        self.stop(reason)

    def run_until_complete(self, max_ticks: int | None = None, sleep_seconds: float = 0) -> dict[str, Any]:
        self.start()
        ticks = 0
        while self.state == OperatorState.RUNNING:
            progressed = self.step()
            if not progressed:
                break
            ticks += 1
            if max_ticks is not None and ticks >= max_ticks:
                break
            if sleep_seconds > 0:
                sleep(sleep_seconds)
        if self.state == OperatorState.RUNNING and self.config.get("mode") == "simulation":
            self.stop("data_exhausted")
        elif self.state == OperatorState.RUNNING and max_ticks is not None:
            self.stop("max_ticks_reached")
        return self.report()

    def step(self) -> bool:
        self._ensure_ready_for_step()
        if self.state != OperatorState.RUNNING:
            return False
        candle = self.data_provider.get_info()
        if candle is None:
            if self.config.get("mode") == "simulation":
                self.stop("data_exhausted")
            return False
        self.last_tick_at = candle.date_time
        self.analyzer.record_candle(candle)

        fill_results = self._settle(candle)
        for result in fill_results:
            self._handle_order_result(result)

        account = self.trader.get_account_info().mark_to_market(candle)
        self.analyzer.record_balance(account, candle)

        if self.state == OperatorState.PAUSED:
            return True

        self.strategy.update_trading_info(candle)
        requests = self.strategy.get_request(account)
        for request in requests:
            self._process_request(request, account, candle)
        return True

    def report(self, output_path: str | None = None) -> dict[str, Any]:
        self._ensure_initialized()
        return self.analyzer.get_return_report(output_path)

    def get_status(self) -> dict[str, Any]:
        active_orders = []
        if self.trader and hasattr(self.trader, "active_orders"):
            active_orders = [request.to_dict() for request in self.trader.active_orders]
        return {
            "run_id": self.run_id,
            "state": self.state,
            "last_tick_at": self.last_tick_at.isoformat() if self.last_tick_at else None,
            "active_orders": active_orders,
            "last_error": self.last_error,
        }

    def _process_request(self, request: TradeRequest, account, candle: CandleInfo) -> None:
        context = self._context(candle)
        decision = self.risk_manager.validate(request, account, context)
        if not decision.accepted:
            payload = {**request.to_dict(), **decision.to_dict()}
            self.analyzer.record_event(Event("RISK_REJECT", self.run_id, payload))
            self.analyzer.record_trade_request(request, status="rejected")
            return
        accepted_request = self._with_client_order_id(request)
        self.analyzer.record_trade_request(accepted_request, status="accepted")
        result = self.trader.send_request(accepted_request)
        if result:
            self._handle_order_result(result)

    def _handle_order_result(self, result: OrderResult) -> None:
        self.analyzer.record_order_result(result)
        self.strategy.update_result(result)

    def _settle(self, candle: CandleInfo) -> list[OrderResult]:
        if isinstance(self.trader, SimulationTrader):
            return self.trader.settle(candle)
        return []

    def _context(self, candle: CandleInfo) -> dict[str, Any]:
        fee_rate = self.config.get("market", {}).get("fee_rate", "0")
        active_orders = self.trader.active_orders if hasattr(self.trader, "active_orders") else []
        now = candle.date_time if self.config.get("mode") == "simulation" else utc_now()
        return {
            "mode": self.config.get("mode", "simulation"),
            "candle": candle,
            "now": now,
            "fee_rate": fee_rate,
            "active_orders": active_orders,
            "daily_start_value": self.daily_start_value,
        }

    def _record_state(self, reason: str) -> None:
        if not self.analyzer:
            return
        self.analyzer.record_event(
            Event(
                "ENGINE_STATE",
                self.run_id,
                {
                    "state": self.state,
                    "reason": reason,
                    "active_orders": self.get_status().get("active_orders", []),
                    "last_tick_at": self.last_tick_at.isoformat() if self.last_tick_at else None,
                },
            )
        )

    def _ensure_ready_for_step(self) -> None:
        self._ensure_initialized()
        if self.state == OperatorState.READY:
            self.start()

    def _ensure_initialized(self) -> None:
        if self.state == OperatorState.INIT:
            self.initialize()
        if not all([self.data_provider, self.strategy, self.risk_manager, self.trader, self.analyzer]):
            raise ConfigurationError("operator is not initialized")

    def _with_client_order_id(self, request: TradeRequest) -> TradeRequest:
        if request.client_order_id:
            return request
        return TradeRequest(
            strategy_id=request.strategy_id,
            type=request.type,
            market=request.market,
            price=request.price,
            amount=request.amount,
            order_type=request.order_type,
            reason=request.reason,
            request_id=request.request_id,
            client_order_id=f"smtm-{request.market}-{request.request_id}"[:64],
            created_at=request.created_at,
        )

    def _resolve_relative_path(self, target: dict[str, Any], key: str) -> None:
        if key in target and target[key]:
            target[key] = str(self._resolve_path(target[key]))

    def _resolve_path(self, value: str | Path) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        config_dir = self.config.get("_config_dir")
        if config_dir:
            config_relative = Path(config_dir) / path
            cwd_relative = Path.cwd() / path
            if config_relative.exists():
                return config_relative
            if cwd_relative.exists():
                return cwd_relative
            if cwd_relative.parent.exists() and not config_relative.parent.exists():
                return cwd_relative
            return config_relative
        return Path.cwd() / path


def build_simulation_config_for_period(config: dict[str, Any], period: dict[str, Any]) -> dict[str, Any]:
    next_config = deepcopy(config)
    next_config["run_id"] = make_id("run")
    data_config = dict(next_config.get("data", {}))
    data_config["start"] = period.get("start")
    data_config["end"] = period.get("end")
    next_config["data"] = data_config
    title = next_config.get("title", "simulation")
    next_config["title"] = f"{title}:{period.get('start')}:{period.get('end')}"
    return next_config
