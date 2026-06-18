from pathlib import Path
import unittest

from smtm.data_provider import FileDataProvider


class FileDataProviderTests(unittest.TestCase):
    def test_loads_sample_candles_sorted(self) -> None:
        provider = FileDataProvider()
        provider.initialize({"path": Path("data/sample_krw_btc_1m.csv")})

        candles = provider.candles
        self.assertEqual(len(candles), 20)
        self.assertEqual(candles[0].market, "KRW-BTC")
        self.assertLess(candles[0].date_time, candles[-1].date_time)

    def test_period_filter(self) -> None:
        provider = FileDataProvider()
        provider.initialize(
            {
                "path": Path("data/sample_krw_btc_1m.csv"),
                "start": "2025-01-01T00:05:00+09:00",
                "end": "2025-01-01T00:06:00+09:00",
            }
        )

        self.assertEqual(len(provider.candles), 2)


if __name__ == "__main__":
    unittest.main()

