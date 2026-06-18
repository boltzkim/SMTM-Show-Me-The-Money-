from copy import deepcopy
import tempfile
from pathlib import Path
import unittest

from smtm.operator import TradingOperator
from smtm.utils import read_json


class OperatorIntegrationTests(unittest.TestCase):
    def test_simulation_pipeline_generates_report(self) -> None:
        config = read_json("configs/simulation.example.json")
        config["_config_dir"] = str(Path.cwd())
        with tempfile.TemporaryDirectory() as tmpdir:
            config = deepcopy(config)
            config["repository"] = {"sqlite_path": str(Path(tmpdir) / "test.sqlite3")}
            output = Path(tmpdir) / "report.json"

            operator = TradingOperator(config)
            report = operator.run_until_complete()
            operator.report(str(output))

            self.assertEqual(report["market_tick_count"], 20)
            self.assertGreater(report["trade_request_count"], 0)
            self.assertTrue(output.exists())
            self.assertTrue(output.with_suffix(".csv").exists())
            self.assertEqual(operator.get_status()["state"], "STOPPED")


if __name__ == "__main__":
    unittest.main()

