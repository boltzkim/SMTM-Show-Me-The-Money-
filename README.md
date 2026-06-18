# SMTM crypto auto trading system

This repository implements the MVP described in
`crypto_auto_trading_system_design_v1.0.docx`.

The current build focuses on the safe path first:

- file and Upbit public candle data providers
- replaceable strategy interface with an SMA cross strategy
- pre-order risk manager
- simulation trader and virtual market with fees, slippage, and partial fills
- analyzer with audit events, balance snapshots, return report, JSON/CSV output
- SQLite repository for audit and recovery-oriented records
- CLI for simulation, mass simulation, and live dry-run polling

Actual exchange order submission is intentionally not enabled in this MVP. The
live command uses public market data plus a dry-run trader so orders are recorded
as events without touching an exchange account.

## Quick start

```powershell
python -m pip install -e .
python -m unittest discover -s tests
smtm simulate --config configs/simulation.example.json --output reports/sample_report.json
```

Without installation, run with `PYTHONPATH`:

```powershell
$env:PYTHONPATH="src"
python -m smtm.cli simulate --config configs/simulation.example.json --output reports/sample_report.json
```

## Local dashboard

```powershell
$env:PYTHONPATH="src"
python -m smtm.cli ui --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765` to start a simulation and watch progress, return,
fills, audit events, and real-time BTC/XRP prices update in the browser. The UI
keeps updating until you press the stop button.

## Live dry-run

```powershell
smtm live-dry-run --config configs/live.dry-run.example.json --ticks 3
```

This calls Upbit quotation endpoints only. It does not create authenticated
orders.

## Project layout

- `src/smtm/models.py`: dataclass models used across modules
- `src/smtm/data_provider.py`: file and Upbit candle providers
- `src/smtm/strategies.py`: strategy implementations
- `src/smtm/risk.py`: order risk checks and kill switch
- `src/smtm/trader.py`: simulation virtual market and dry-run trader
- `src/smtm/analyzer.py`: event storage and performance reports
- `src/smtm/repository.py`: SQLite persistence
- `src/smtm/operator.py`: orchestration and state model
- `src/smtm/mass_simulator.py`: multi-period simulation runner
- `src/smtm/cli.py`: command line controller

## Safety notes

This project is engineering software, not investment advice. Keep live trading
disabled until strategy, risk limits, exchange permissions, and operational
runbooks are tested with fixed data, dry-run, and small canary runs.
