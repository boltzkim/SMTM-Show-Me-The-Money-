"""Market data providers."""

from __future__ import annotations

import csv
from datetime import datetime
import json
from pathlib import Path
from time import monotonic, sleep
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .exceptions import ConfigurationError, DataProviderError
from .models import CandleInfo
from .utils import parse_datetime


class FileDataProvider:
    """Reads normalized or exchange-like candles from a CSV file."""

    def __init__(self, path: str | Path | None = None, market: str | None = None) -> None:
        self.path = Path(path) if path else None
        self.market = market
        self.loop = False
        self._candles: list[CandleInfo] = []
        self._cursor = 0

    def initialize(self, config: dict) -> None:
        path = config.get("path") or self.path
        if not path:
            raise ConfigurationError("file data provider requires data.path")
        self.path = Path(path)
        if not self.path.exists():
            raise DataProviderError(f"market data file not found: {self.path}")
        self.market = config.get("market") or self.market
        self.loop = bool(config.get("loop", False))
        start = config.get("start")
        end = config.get("end")
        self._candles = self._load_csv(self.path, self.market, start, end)
        self._cursor = 0
        if not self._candles:
            raise DataProviderError(f"no candles loaded from {self.path}")

    def get_info(self) -> CandleInfo | None:
        if self._cursor >= len(self._candles):
            if self.loop and self._candles:
                self._cursor = 0
            else:
                return None
        if self._cursor >= len(self._candles):
            return None
        candle = self._candles[self._cursor]
        self._cursor += 1
        return candle

    def reset(self) -> None:
        self._cursor = 0

    @property
    def candles(self) -> list[CandleInfo]:
        return list(self._candles)

    @staticmethod
    def _load_csv(
        path: Path,
        market: str | None,
        start: str | datetime | None,
        end: str | datetime | None,
    ) -> list[CandleInfo]:
        start_dt = parse_datetime(start) if start else None
        end_dt = parse_datetime(end) if end else None
        candles: dict[tuple[str, datetime], CandleInfo] = {}
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                candle = CandleInfo.from_mapping(row, default_market=market)
                if start_dt and candle.date_time < start_dt:
                    continue
                if end_dt and candle.date_time > end_dt:
                    continue
                candles[(candle.market, candle.date_time)] = candle
        return [candles[key] for key in sorted(candles, key=lambda item: item[1])]


class UpbitDataProvider:
    """Fetches public minute candles from Upbit quotation REST API."""

    ALLOWED_UNITS = {1, 3, 5, 10, 15, 30, 60, 240}

    def __init__(self) -> None:
        self.market = "KRW-BTC"
        self.base_url = "https://api.upbit.com"
        self.unit = 1
        self.count = 1
        self.timeout = 10
        self.min_interval_seconds = 0.12
        self._last_call_at = 0.0
        self._last_candle_time: datetime | None = None

    def initialize(self, config: dict) -> None:
        self.market = config.get("market") or config.get("currency") or self.market
        self.base_url = str(config.get("base_url", self.base_url)).rstrip("/")
        self.unit = int(config.get("unit", self.unit))
        self.count = int(config.get("count", self.count))
        self.timeout = int(config.get("timeout", self.timeout))
        if self.unit not in self.ALLOWED_UNITS:
            raise ConfigurationError(f"unsupported Upbit minute unit: {self.unit}")
        if self.count < 1:
            raise ConfigurationError("Upbit count must be greater than zero")

    def get_info(self) -> CandleInfo | None:
        candles = self.fetch_recent(count=self.count)
        if not candles:
            return None
        latest = candles[-1]
        if latest.date_time == self._last_candle_time:
            return None
        self._last_candle_time = latest.date_time
        return latest

    def fetch_recent(self, count: int = 1, to: str | None = None) -> list[CandleInfo]:
        self._respect_rate_limit()
        query: dict[str, Any] = {"market": self.market, "count": count}
        if to:
            query["to"] = to
        url = f"{self.base_url}/v1/candles/minutes/{self.unit}?{urlencode(query)}"
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "smtm/0.1"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise DataProviderError(f"Upbit HTTP error {exc.code}: {exc.reason}") from exc
        except (URLError, TimeoutError) as exc:
            raise DataProviderError(f"Upbit request failed: {exc}") from exc
        if not isinstance(payload, list):
            raise DataProviderError(f"unexpected Upbit response: {payload!r}")
        candles = [CandleInfo.from_mapping(item, default_market=self.market) for item in payload]
        return sorted(candles, key=lambda candle: candle.date_time)

    def _respect_rate_limit(self) -> None:
        elapsed = monotonic() - self._last_call_at
        if elapsed < self.min_interval_seconds:
            sleep(self.min_interval_seconds - elapsed)
        self._last_call_at = monotonic()


def build_data_provider(config: dict) -> FileDataProvider | UpbitDataProvider:
    provider_name = str(config.get("provider", "file")).lower()
    if provider_name == "file":
        provider = FileDataProvider()
    elif provider_name == "upbit":
        provider = UpbitDataProvider()
    else:
        raise ConfigurationError(f"unknown data provider: {provider_name}")
    provider.initialize(config)
    return provider
