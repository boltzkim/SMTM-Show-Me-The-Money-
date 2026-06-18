from decimal import Decimal
import unittest

from smtm.models import AccountInfo, CandleInfo, TradeRequest
from smtm.risk import BasicRiskManager
from smtm.utils import parse_datetime


class RiskManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candle = CandleInfo(
            market="KRW-BTC",
            date_time=parse_datetime("2025-01-01T00:00:00+09:00"),
            opening_price=Decimal("100000000"),
            high_price=Decimal("101000000"),
            low_price=Decimal("99000000"),
            closing_price=Decimal("100000000"),
        )

    def test_rejects_max_order(self) -> None:
        risk = BasicRiskManager()
        risk.initialize({"max_order_krw": 50000, "min_order_krw": 5000})
        account = AccountInfo.empty(500000)
        request = TradeRequest(
            strategy_id="test",
            type="buy",
            market="KRW-BTC",
            price=Decimal("100000000"),
            amount=Decimal("0.001"),
        )

        decision = risk.validate(request, account, {"mode": "simulation", "candle": self.candle})

        self.assertFalse(decision.accepted)
        self.assertEqual(decision.rule_id, "MAX_ORDER")

    def test_accepts_bounded_buy(self) -> None:
        risk = BasicRiskManager()
        risk.initialize({"max_order_krw": 50000, "min_order_krw": 5000, "max_position_ratio": "0.5"})
        account = AccountInfo.empty(500000)
        request = TradeRequest(
            strategy_id="test",
            type="buy",
            market="KRW-BTC",
            price=Decimal("100000000"),
            amount=Decimal("0.0005"),
        )

        decision = risk.validate(request, account, {"mode": "simulation", "candle": self.candle})

        self.assertTrue(decision.accepted)


if __name__ == "__main__":
    unittest.main()

