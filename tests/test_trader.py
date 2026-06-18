from decimal import Decimal
import unittest

from smtm.models import AccountInfo, CandleInfo, TradeRequest
from smtm.trader import VirtualMarket
from smtm.utils import parse_datetime


class VirtualMarketTests(unittest.TestCase):
    def test_limit_buy_fills_and_updates_account(self) -> None:
        market = VirtualMarket(fee_rate=Decimal("0.0005"), slippage_rate=Decimal("0"))
        account = AccountInfo.empty(100000)
        request = TradeRequest(
            strategy_id="test",
            type="buy",
            market="KRW-BTC",
            price=Decimal("100000000"),
            amount=Decimal("0.0005"),
        )
        market.submit(request)
        candle = CandleInfo(
            market="KRW-BTC",
            date_time=parse_datetime("2025-01-01T00:01:00+09:00"),
            opening_price=Decimal("100000000"),
            high_price=Decimal("101000000"),
            low_price=Decimal("99000000"),
            closing_price=Decimal("100000000"),
            acc_volume=Decimal("1"),
        )

        results = market.settle(candle, account)

        self.assertEqual(results[0].status, "filled")
        self.assertEqual(account.balance_for("KRW-BTC"), Decimal("0.00050000"))
        self.assertLess(account.cash, Decimal("50000"))


if __name__ == "__main__":
    unittest.main()

