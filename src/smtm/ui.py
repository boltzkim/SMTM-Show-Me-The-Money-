"""Local web UI for simulation progress and reports."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
from pathlib import Path
import posixpath
from threading import Event as ThreadEvent
from threading import RLock, Thread
from time import sleep
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, unquote, urlparse
from urllib.request import Request, urlopen
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .live_trading import LiveTradingService
from .operator import OperatorState, TradingOperator
from .utils import json_safe, read_json, to_decimal, utc_now, write_json


WORKSPACE_ROOT = Path.cwd()
CONFIG_DIR = WORKSPACE_ROOT / "configs"
REPORT_DIR = WORKSPACE_ROOT / "reports"
WEB_DIR = Path(__file__).with_name("web")


class RealtimeMarketMonitor:
    def __init__(
        self,
        markets: dict[str, str] | None = None,
        interval_seconds: float = 3,
        max_points: int = 240,
    ) -> None:
        self.markets = markets or {"KRW-BTC": "비트코인", "KRW-XRP": "엑스알피(리플)"}
        self.interval_seconds = max(1, min(interval_seconds, 30))
        self.max_points = max_points
        self.points: dict[str, list[dict[str, Any]]] = {market: [] for market in self.markets}
        self.lock = RLock()
        self.stop_requested = ThreadEvent()
        self.thread: Thread | None = None
        self.history_seeded = False
        self.started_at: str | None = None
        self.last_updated_at: str | None = None
        self.last_attempt_at: str | None = None
        self.error: str | None = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_requested.clear()
        self.started_at = utc_now().isoformat()
        self.history_seeded = False
        with self.lock:
            self.points = {market: [] for market in self.markets}
        self.thread = Thread(target=self._run, name="smtm-market-monitor", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_requested.set()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "started_at": self.started_at,
                "last_updated_at": self.last_updated_at,
                "last_attempt_at": self.last_attempt_at,
                "error": self.error,
                "running": bool(self.thread and self.thread.is_alive() and not self.stop_requested.is_set()),
                "markets": {
                    market: {
                        "market": market,
                        "name": self.markets[market],
                        "points": list(points),
                        "latest": points[-1] if points else None,
                    }
                    for market, points in self.points.items()
                },
            }

    def _run(self) -> None:
        self._seed_history()
        while not self.stop_requested.is_set():
            try:
                with self.lock:
                    self.last_attempt_at = utc_now().isoformat()
                points = self._fetch_ticker()
            except Exception as exc:
                with self.lock:
                    self.error = str(exc)
            else:
                with self.lock:
                    self.error = None
                    self.last_updated_at = utc_now().isoformat()
                    for point in points:
                        market_points = self.points.setdefault(point["market"], [])
                        market_points.append(point)
                        del market_points[:-self.max_points]
            self.stop_requested.wait(self.interval_seconds)

    def _seed_history(self) -> None:
        if self.history_seeded:
            return
        try:
            history_points: dict[str, list[dict[str, Any]]] = {}
            for market in self.markets:
                history_points[market] = self._fetch_minute_history(market)
        except Exception as exc:
            with self.lock:
                self.error = str(exc)
            return
        with self.lock:
            for market, points in history_points.items():
                self.points[market] = points[-self.max_points :]
            self.history_seeded = True
            self.last_updated_at = utc_now().isoformat()

    def _fetch_minute_history(self, market: str) -> list[dict[str, Any]]:
        url = f"https://api.upbit.com/v1/candles/minutes/1?{urlencode({'market': market, 'count': 60})}"
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "smtm-ui/0.1"})
        try:
            with urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"최근 1시간 분봉 조회 HTTP 오류 {exc.code}: {exc.reason}") from exc
        except (URLError, TimeoutError) as exc:
            raise RuntimeError(f"최근 1시간 분봉 조회 실패: {exc}") from exc
        if not isinstance(payload, list):
            raise RuntimeError("최근 1시간 분봉 응답 형식이 올바르지 않습니다.")
        points = []
        for item in reversed(payload):
            candle_time = item.get("candle_date_time_utc") or item.get("candle_date_time_kst")
            if candle_time and "+" not in str(candle_time):
                candle_time = f"{candle_time}+00:00"
            points.append(
                {
                    "market": market,
                    "name": self.markets[market],
                    "date_time": candle_time or utc_now().isoformat(),
                    "trade_price": item.get("trade_price"),
                    "trade_volume": item.get("candle_acc_trade_volume"),
                    "signed_change_rate": None,
                    "signed_change_price": None,
                    "acc_trade_price_24h": None,
                    "acc_trade_volume_24h": item.get("candle_acc_trade_volume"),
                    "source": "minute_candle",
                }
            )
        return points

    def _fetch_ticker(self) -> list[dict[str, Any]]:
        query = ",".join(self.markets)
        url = f"https://api.upbit.com/v1/ticker?{urlencode({'markets': query})}"
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "smtm-ui/0.1"})
        try:
            with urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"시세 API HTTP 오류 {exc.code}: {exc.reason}") from exc
        except (URLError, TimeoutError) as exc:
            raise RuntimeError(f"시세 API 연결 실패: {exc}") from exc
        if not isinstance(payload, list):
            raise RuntimeError("시세 API 응답 형식이 올바르지 않습니다.")
        timestamp = utc_now().isoformat()
        points = []
        for item in payload:
            market = str(item.get("market", ""))
            if market not in self.markets:
                continue
            points.append(
                {
                    "market": market,
                    "name": self.markets[market],
                    "date_time": timestamp,
                    "trade_price": item.get("trade_price"),
                    "trade_volume": item.get("trade_volume"),
                    "signed_change_rate": item.get("signed_change_rate"),
                    "signed_change_price": item.get("signed_change_price"),
                    "acc_trade_price_24h": item.get("acc_trade_price_24h"),
                    "acc_trade_volume_24h": item.get("acc_trade_volume_24h"),
                }
            )
        return points


@dataclass
class SimulationJob:
    config: dict[str, Any]
    config_name: str
    output_path: Path
    tick_delay: float = 0.2
    operator: TradingOperator = field(init=False)
    thread: Thread | None = field(default=None, init=False)
    lock: RLock = field(default_factory=RLock, init=False)
    stop_requested: ThreadEvent = field(default_factory=ThreadEvent, init=False)
    started_at: str = field(default_factory=lambda: utc_now().isoformat(), init=False)
    ended_at: str | None = field(default=None, init=False)
    total_ticks: int | None = field(default=None, init=False)
    error: str | None = field(default=None, init=False)
    report_write_error: str | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.operator = TradingOperator(self.config)

    @property
    def run_id(self) -> str:
        return self.operator.run_id

    def start(self) -> None:
        self.thread = Thread(target=self._run, name=f"smtm-ui-{self.run_id}", daemon=True)
        self.thread.start()

    def request_stop(self) -> None:
        self.stop_requested.set()
        with self.lock:
            if self.operator.state in {OperatorState.RUNNING, OperatorState.READY, OperatorState.PAUSED}:
                self.operator.stop("ui_stop")
                self.ended_at = utc_now().isoformat()
                self._write_report()

    def _run(self) -> None:
        try:
            with self.lock:
                self.operator.initialize()
                self.total_ticks = self._detect_total_ticks()
                self.operator.start()
            while not self.stop_requested.is_set():
                with self.lock:
                    progressed = self.operator.step()
                    if not progressed or self.operator.state != OperatorState.RUNNING:
                        break
                if self.tick_delay > 0:
                    sleep(self.tick_delay)
            with self.lock:
                if self.operator.state == OperatorState.RUNNING:
                    self.operator.stop("ui_stop")
                if self.operator.state != OperatorState.STOPPED:
                    self.operator.stop("completed")
                self.ended_at = utc_now().isoformat()
                self._write_report()
        except Exception as exc:
            with self.lock:
                self.error = str(exc)
                self.operator.last_error = str(exc)
                self.operator.state = OperatorState.ERROR
                self.ended_at = utc_now().isoformat()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            analyzer = self.operator.analyzer
            status = self.operator.get_status()
            report = self.operator.report() if analyzer else {}
            current_tick = report.get("market_tick_count", 0)
            progress_ratio = 0
            if self.total_ticks:
                progress_ratio = min(current_tick / self.total_ticks, 1)
            recent_events = []
            equity_points = []
            fills = []
            if analyzer:
                recent_events = [event.to_dict() for event in analyzer.events[-30:]]
                equity_points = [record.to_dict() for record in analyzer.return_records]
                fills = [result.to_dict() for result in analyzer.order_results if result.filled_amount > 0]
            return {
                "run_id": self.run_id,
                "config_name": self.config_name,
                "started_at": self.started_at,
                "ended_at": self.ended_at,
                "state": status["state"],
                "last_tick_at": status["last_tick_at"],
                "active_orders": status["active_orders"],
                "last_error": self.error or status["last_error"],
                "report_write_error": self.report_write_error,
                "current_tick": current_tick,
                "total_ticks": self.total_ticks,
                "progress_ratio": progress_ratio,
                "output_path": str(self.output_path),
                "report": report,
                "recent_events": recent_events,
                "equity_points": equity_points,
                "fills": fills,
                "is_continuous": bool(self.config.get("data", {}).get("loop", False)),
                "source_tick_count": self.total_ticks,
            }

    def _detect_total_ticks(self) -> int | None:
        provider = self.operator.data_provider
        candles = getattr(provider, "candles", None)
        if isinstance(candles, list):
            return len(candles)
        return None

    def _write_report(self) -> None:
        report = self.operator.report()
        try:
            write_json(self.output_path, report)
        except OSError as exc:
            self.report_write_error = str(exc)


class SimulationRegistry:
    def __init__(self, enable_market_monitor: bool = True) -> None:
        self.jobs: dict[str, SimulationJob] = {}
        self.lock = RLock()
        self.enable_market_monitor = enable_market_monitor
        self.market_monitor = RealtimeMarketMonitor() if enable_market_monitor else None
        self.live_trading = LiveTradingService()

    def list_configs(self) -> list[dict[str, str]]:
        configs = []
        for path in sorted(CONFIG_DIR.glob("*.json")):
            try:
                payload = read_json(path)
            except Exception:
                title = path.stem
            else:
                if payload.get("mode", "simulation") != "simulation":
                    continue
                title = str(payload.get("title") or path.stem)
            configs.append({"name": path.name, "title": title, "path": str(path)})
        return configs

    def start_simulation(self, config_name: str, tick_delay: float, market_interval: float = 3) -> SimulationJob:
        if self.market_monitor:
            self.market_monitor.interval_seconds = max(1, min(market_interval, 30))
            self.market_monitor.start()
        config_path = self._resolve_config(config_name)
        config = read_json(config_path)
        config["_config_dir"] = str(config_path.parent)
        config["mode"] = "simulation"
        config.setdefault("title", config_path.stem)
        config.setdefault("data", {})
        config["data"]["loop"] = True
        timestamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
        output_path = REPORT_DIR / f"ui_{config_path.stem}_{timestamp}.json"
        config["repository"] = {}
        job = SimulationJob(
            config=config,
            config_name=config_path.name,
            output_path=output_path,
            tick_delay=max(0, min(tick_delay, 10)),
        )
        with self.lock:
            self.jobs[job.run_id] = job
        job.start()
        return job

    def list_runs(self) -> list[dict[str, Any]]:
        with self.lock:
            return [job.snapshot() for job in self.jobs.values()]

    def get_run(self, run_id: str) -> SimulationJob | None:
        with self.lock:
            return self.jobs.get(run_id)

    def stop_run(self, run_id: str) -> bool:
        job = self.get_run(run_id)
        if not job:
            return False
        job.request_stop()
        if self.market_monitor and not self._has_running_job(except_run_id=run_id):
            self.market_monitor.stop()
        return True

    def get_market_snapshot(self) -> dict[str, Any]:
        if not self.market_monitor:
            return {"running": False, "error": None, "markets": {}}
        return self.market_monitor.snapshot()

    def get_account_snapshot(self) -> dict[str, Any]:
        return self.live_trading.snapshot(self._latest_price_map())

    def get_order_chance(self, market: str) -> dict[str, Any]:
        return self.live_trading.chance(market)

    def test_manual_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.live_trading.test_order(payload, self._latest_price(str(payload.get("market") or "")))

    def submit_manual_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.live_trading.submit_order(payload, self._latest_price(str(payload.get("market") or "")))

    def _latest_price_map(self) -> dict[str, Any]:
        snapshot = self.get_market_snapshot()
        prices = {}
        for market, payload in (snapshot.get("markets") or {}).items():
            latest = payload.get("latest") or {}
            price = latest.get("trade_price")
            if price not in {None, ""}:
                try:
                    prices[market] = to_decimal(price)
                except ValueError:
                    continue
        return prices

    def _latest_price(self, market: str) -> Any:
        return self._latest_price_map().get(market.upper())

    def _has_running_job(self, except_run_id: str | None = None) -> bool:
        with self.lock:
            for run_id, job in self.jobs.items():
                if run_id == except_run_id:
                    continue
                if job.operator.state in {OperatorState.READY, OperatorState.RUNNING, OperatorState.PAUSED}:
                    return True
        return False

    @staticmethod
    def _resolve_config(config_name: str) -> Path:
        safe_name = Path(config_name).name
        path = CONFIG_DIR / safe_name
        if not path.exists() or path.suffix.lower() != ".json":
            raise ValueError(f"unknown config: {config_name}")
        return path


REGISTRY = SimulationRegistry()


class UIRequestHandler(BaseHTTPRequestHandler):
    server_version = "SMTMUI/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/configs":
            self._send_json({"configs": REGISTRY.list_configs()})
            return
        if parsed.path == "/api/runs":
            self._send_json({"runs": REGISTRY.list_runs()})
            return
        if parsed.path == "/api/markets":
            self._send_json(REGISTRY.get_market_snapshot())
            return
        if parsed.path == "/api/account":
            self._send_json(REGISTRY.get_account_snapshot())
            return
        if parsed.path == "/api/orders/chance":
            market = parse_qs(parsed.query).get("market", ["KRW-BTC"])[0]
            try:
                self._send_json(REGISTRY.get_order_chance(market))
            except Exception as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path.startswith("/api/runs/"):
            if parsed.path.endswith("/report"):
                run_id = parsed.path.split("/")[-2]
                job = REGISTRY.get_run(run_id)
                if not job:
                    self._send_json({"error": "run not found"}, HTTPStatus.NOT_FOUND)
                    return
                self._send_json(job.snapshot().get("report", {}))
                return
            run_id = parsed.path.rsplit("/", 1)[-1]
            job = REGISTRY.get_run(run_id)
            if not job:
                self._send_json({"error": "run not found"}, HTTPStatus.NOT_FOUND)
                return
            self._send_json(job.snapshot())
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/runs":
            payload = self._read_json_body()
            try:
                job = REGISTRY.start_simulation(
                    config_name=str(payload.get("config_name", "simulation.example.json")),
                    tick_delay=float(payload.get("tick_delay", 0.2)),
                    market_interval=float(payload.get("market_interval", 3)),
                )
            except Exception as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            self._send_json(job.snapshot(), HTTPStatus.CREATED)
            return
        if parsed.path.startswith("/api/runs/") and parsed.path.endswith("/stop"):
            run_id = parsed.path.split("/")[-2]
            if not REGISTRY.stop_run(run_id):
                self._send_json({"error": "run not found"}, HTTPStatus.NOT_FOUND)
                return
            job = REGISTRY.get_run(run_id)
            self._send_json(job.snapshot() if job else {"stopped": True})
            return
        if parsed.path == "/api/orders/test":
            payload = self._read_json_body()
            try:
                self._send_json(REGISTRY.test_manual_order(payload))
            except Exception as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/orders":
            payload = self._read_json_body()
            try:
                self._send_json(REGISTRY.submit_manual_order(payload), HTTPStatus.CREATED)
            except Exception as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: Any) -> None:
        return None

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        data = self.rfile.read(length)
        return json.loads(data.decode("utf-8"))

    def _serve_static(self, request_path: str) -> None:
        path = "/index.html" if request_path in {"", "/"} else request_path
        normalized = posixpath.normpath(unquote(path)).lstrip("/")
        target = (WEB_DIR / normalized).resolve()
        if WEB_DIR.resolve() not in target.parents and target != WEB_DIR.resolve():
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not target.exists() or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".svg": "image/svg+xml",
        }.get(target.suffix.lower(), "application/octet-stream")
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            pass

    def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(json_safe(payload), ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            pass


def run_server(host: str = "127.0.0.1", port: int = 8765) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((host, port), UIRequestHandler)
    print(f"SMTM UI running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="smtm-ui", description="SMTM local simulation dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    run_server(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
