"""Command line controller."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .mass_simulator import MassSimulator
from .operator import TradingOperator
from .ui import run_server
from .utils import json_safe, read_json, write_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="smtm", description="SMTM auto trading controller")
    subparsers = parser.add_subparsers(dest="command", required=True)

    simulate = subparsers.add_parser("simulate", help="run one simulation")
    simulate.add_argument("--config", required=True, help="path to simulation config JSON")
    simulate.add_argument("--output", help="path to report JSON")

    mass = subparsers.add_parser("mass-simulate", help="run period list simulations")
    mass.add_argument("--config", required=True, help="path to mass simulation config JSON")
    mass.add_argument("--output", help="path to summary JSON")

    live = subparsers.add_parser("live-dry-run", help="poll live data without exchange orders")
    live.add_argument("--config", required=True, help="path to live dry-run config JSON")
    live.add_argument("--ticks", type=int, default=1, help="number of market ticks to process")
    live.add_argument("--sleep", type=float, default=0, help="seconds to sleep between ticks")
    live.add_argument("--output", help="path to report JSON")

    ui = subparsers.add_parser("ui", help="run local simulation dashboard")
    ui.add_argument("--host", default="127.0.0.1", help="host to bind")
    ui.add_argument("--port", type=int, default=8765, help="port to bind")

    args = parser.parse_args(argv)
    try:
        if args.command == "simulate":
            result = command_simulate(args.config, args.output)
        elif args.command == "mass-simulate":
            result = command_mass_simulate(args.config, args.output)
        elif args.command == "live-dry-run":
            result = command_live_dry_run(args.config, args.ticks, args.sleep, args.output)
        elif args.command == "ui":
            run_server(host=args.host, port=args.port)
            return 0
        else:
            parser.error(f"unknown command: {args.command}")
            return 2
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(json_safe(result), ensure_ascii=False, indent=2))
    return 0


def command_simulate(config_path: str, output_path: str | None) -> dict:
    config = load_config(config_path)
    operator = TradingOperator(config)
    report = operator.run_until_complete()
    if output_path:
        operator.report(output_path)
    return {"status": operator.get_status(), "report": report}


def command_mass_simulate(config_path: str, output_path: str | None) -> dict:
    config = load_config(config_path)
    result = MassSimulator(config).run()
    if output_path:
        write_json(output_path, result)
    return result


def command_live_dry_run(config_path: str, ticks: int, sleep_seconds: float, output_path: str | None) -> dict:
    config = load_config(config_path)
    config["mode"] = "live"
    config["dry_run"] = True
    operator = TradingOperator(config)
    report = operator.run_until_complete(max_ticks=ticks, sleep_seconds=sleep_seconds)
    if output_path:
        operator.report(output_path)
    return {"status": operator.get_status(), "report": report}


def load_config(config_path: str) -> dict:
    path = Path(config_path).resolve()
    config = read_json(path)
    config["_config_dir"] = str(path.parent)
    return config


if __name__ == "__main__":
    raise SystemExit(main())
