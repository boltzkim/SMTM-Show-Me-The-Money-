import time
import unittest

from smtm.ui import SimulationRegistry


class SimulationRegistryTests(unittest.TestCase):
    def test_ui_job_completes_with_progress_snapshot(self) -> None:
        registry = SimulationRegistry(enable_market_monitor=False)
        job = registry.start_simulation("simulation.example.json", tick_delay=0.01)

        deadline = time.time() + 5
        snapshot = job.snapshot()
        while snapshot["current_tick"] < 25 and time.time() < deadline:
            time.sleep(0.05)
            snapshot = job.snapshot()

        self.assertEqual(snapshot["state"], "RUNNING")
        self.assertGreaterEqual(snapshot["current_tick"], 25)
        self.assertTrue(snapshot["is_continuous"])
        self.assertEqual(snapshot["source_tick_count"], 20)
        registry.stop_run(job.run_id)
        snapshot = job.snapshot()
        self.assertEqual(snapshot["state"], "STOPPED")
        self.assertGreater(snapshot["report"]["fill_count"], 0)


if __name__ == "__main__":
    unittest.main()
