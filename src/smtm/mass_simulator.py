"""Mass simulation runner for multiple periods."""

from __future__ import annotations

from typing import Any

from .analyzer import summarize_reports
from .operator import TradingOperator, build_simulation_config_for_period


class MassSimulator:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    def run(self) -> dict[str, Any]:
        periods = self.config.get("period_list") or []
        if not periods:
            periods = [{"start": None, "end": None}]
        reports = []
        for period in periods:
            run_config = build_simulation_config_for_period(self.config, period)
            operator = TradingOperator(run_config)
            reports.append(operator.run_until_complete())
        summary = summarize_reports(reports)
        return {"reports": reports, "summary": summary}

