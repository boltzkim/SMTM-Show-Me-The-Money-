from __future__ import annotations

import base64
import hashlib
import json
import os
from decimal import Decimal
import unittest
from unittest.mock import patch

from smtm.live_trading import (
    LiveTradingService,
    ManualOrder,
    build_query_string,
    create_jwt,
)


class FakeUpbitClient:
    configured = True

    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, str]]] = []

    def post(self, path: str, body: dict[str, str]) -> dict[str, str]:
        self.posts.append((path, body))
        return {"uuid": "exchange-order-1", "state": "wait"}


class LiveTradingTests(unittest.TestCase):
    def make_service(self, **env: str) -> LiveTradingService:
        defaults = {
            "SMTM_ALLOWED_MARKETS": "KRW-BTC,KRW-XRP",
            "SMTM_MAX_ORDER_KRW": "100000",
            "SMTM_LIVE_TRADING_ENABLED": "false",
            "UPBIT_ACCESS_KEY": "",
            "UPBIT_SECRET_KEY": "",
        }
        defaults.update(env)
        with patch.dict(os.environ, defaults, clear=True), patch("smtm.live_trading.load_dotenv", lambda: None):
            return LiveTradingService()

    def test_query_string_preserves_array_keys_for_upbit_hash(self) -> None:
        query = build_query_string({"market": "KRW-BTC", "states[]": ["wait", "watch"]})
        self.assertEqual(query, "market=KRW-BTC&states[]=wait&states[]=watch")

    def test_create_jwt_includes_sha512_query_hash(self) -> None:
        token = create_jwt("access-key", "secret-key", "market=KRW-BTC")
        parts = token.split(".")
        self.assertEqual(len(parts), 3)
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "==").decode("utf-8"))
        expected_hash = hashlib.sha512("market=KRW-BTC".encode("utf-8")).hexdigest()
        self.assertEqual(payload["access_key"], "access-key")
        self.assertEqual(payload["query_hash"], expected_hash)
        self.assertEqual(payload["query_hash_alg"], "SHA512")

    def test_manual_market_buy_maps_to_upbit_price_order(self) -> None:
        order = ManualOrder.from_payload(
            {"market": "krw-btc", "order_kind": "market_buy", "price": "5000", "volume": ""}
        )
        body = order.to_upbit_body()
        self.assertEqual(body["market"], "KRW-BTC")
        self.assertEqual(body["side"], "bid")
        self.assertEqual(body["ord_type"], "price")
        self.assertEqual(body["price"], "5000")
        self.assertNotIn("volume", body)

    def test_submit_order_is_virtual_when_live_trading_disabled(self) -> None:
        service = self.make_service(SMTM_LIVE_TRADING_ENABLED="false")
        fake_client = FakeUpbitClient()
        service.client = fake_client  # type: ignore[assignment]

        result = service.submit_order({"market": "KRW-BTC", "order_kind": "market_buy", "price": "5000"})

        self.assertEqual(result["mode"], "virtual")
        self.assertEqual(result["status"], "virtual_submitted")
        self.assertEqual(fake_client.posts, [])

    def test_test_order_is_virtual_when_live_trading_disabled(self) -> None:
        service = self.make_service(SMTM_LIVE_TRADING_ENABLED="false")
        fake_client = FakeUpbitClient()
        service.client = fake_client  # type: ignore[assignment]

        result = service.test_order({"market": "KRW-BTC", "order_kind": "market_buy", "price": "5000"})

        self.assertEqual(result["mode"], "virtual")
        self.assertEqual(result["status"], "virtual_validated")
        self.assertEqual(fake_client.posts, [])

    def test_submit_order_calls_exchange_only_when_live_trading_enabled(self) -> None:
        service = self.make_service(SMTM_LIVE_TRADING_ENABLED="true")
        fake_client = FakeUpbitClient()
        service.client = fake_client  # type: ignore[assignment]

        result = service.submit_order({"market": "KRW-BTC", "order_kind": "market_buy", "price": "5000"})

        self.assertEqual(result["mode"], "live")
        self.assertEqual(result["status"], "submitted")
        self.assertEqual(fake_client.posts[0][0], "/v1/orders")

    def test_order_amount_cannot_exceed_configured_krw_limit(self) -> None:
        service = self.make_service(SMTM_MAX_ORDER_KRW="1000")

        with self.assertRaisesRegex(ValueError, "SMTM_MAX_ORDER_KRW"):
            service.submit_order({"market": "KRW-BTC", "order_kind": "market_buy", "price": "1001"})

    def test_market_sell_requires_latest_price_for_amount_guard(self) -> None:
        service = self.make_service()

        with self.assertRaisesRegex(ValueError, "추정"):
            service.submit_order({"market": "KRW-BTC", "order_kind": "market_sell", "volume": "0.1"})

        result = service.submit_order(
            {"market": "KRW-BTC", "order_kind": "market_sell", "volume": "0.1"},
            latest_price=Decimal("5000"),
        )
        self.assertEqual(result["status"], "virtual_submitted")


if __name__ == "__main__":
    unittest.main()
