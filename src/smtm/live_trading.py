"""Authenticated Upbit account and manual order helpers."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode
from urllib.request import Request, urlopen
import uuid

from .utils import DECIMAL_ZERO, make_id, to_decimal, utc_now


DEFAULT_ALLOWED_MARKETS = ("KRW-BTC", "KRW-XRP")


def load_dotenv(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_decimal(name: str, default: str = "5000") -> Decimal:
    try:
        return to_decimal(os.environ.get(name, default))
    except ValueError:
        return to_decimal(default)


@dataclass(frozen=True)
class ManualOrder:
    market: str
    side: str
    order_kind: str
    price: Decimal | None = None
    volume: Decimal | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ManualOrder":
        market = str(payload.get("market") or "KRW-BTC").strip().upper()
        side = str(payload.get("side") or "buy").strip().lower()
        order_kind = str(payload.get("order_kind") or "limit").strip().lower()
        price = optional_decimal(payload.get("price"))
        volume = optional_decimal(payload.get("volume"))
        return cls(market=market, side=side, order_kind=order_kind, price=price, volume=volume)

    def to_upbit_body(self) -> dict[str, str]:
        if self.side not in {"buy", "sell"}:
            raise ValueError("주문 방향은 매수 또는 매도만 가능합니다.")
        if self.order_kind == "limit":
            if self.price is None or self.price <= DECIMAL_ZERO:
                raise ValueError("지정가 주문에는 주문 가격이 필요합니다.")
            if self.volume is None or self.volume <= DECIMAL_ZERO:
                raise ValueError("지정가 주문에는 주문 수량이 필요합니다.")
            return {
                "market": self.market,
                "side": "bid" if self.side == "buy" else "ask",
                "ord_type": "limit",
                "price": format_decimal(self.price),
                "volume": format_decimal(self.volume),
                "identifier": make_identifier(self.market),
            }
        if self.order_kind == "market_buy":
            if self.price is None or self.price <= DECIMAL_ZERO:
                raise ValueError("시장가 매수에는 주문 금액이 필요합니다.")
            return {
                "market": self.market,
                "side": "bid",
                "ord_type": "price",
                "price": format_decimal(self.price),
                "identifier": make_identifier(self.market),
            }
        if self.order_kind == "market_sell":
            if self.volume is None or self.volume <= DECIMAL_ZERO:
                raise ValueError("시장가 매도에는 주문 수량이 필요합니다.")
            return {
                "market": self.market,
                "side": "ask",
                "ord_type": "market",
                "volume": format_decimal(self.volume),
                "identifier": make_identifier(self.market),
            }
        raise ValueError("지원하지 않는 주문 방식입니다.")

    def estimated_notional(self, latest_price: Decimal | None = None) -> Decimal | None:
        if self.order_kind == "market_buy":
            return self.price
        if self.order_kind == "limit" and self.price is not None and self.volume is not None:
            return self.price * self.volume
        if self.order_kind == "market_sell" and latest_price is not None and self.volume is not None:
            return latest_price * self.volume
        return None


class UpbitAuthClient:
    def __init__(self, access_key: str, secret_key: str, base_url: str = "https://api.upbit.com") -> None:
        self.access_key = access_key
        self.secret_key = secret_key
        self.base_url = base_url.rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(self.access_key and self.secret_key)

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        query_string = build_query_string(params or {})
        url = f"{self.base_url}{path}"
        if query_string:
            url = f"{url}?{query_string}"
        return self._request("GET", url, query_string=query_string)

    def post(self, path: str, body: dict[str, Any]) -> Any:
        query_string = build_query_string(body)
        data = json.dumps(body).encode("utf-8")
        return self._request("POST", f"{self.base_url}{path}", data=data, query_string=query_string)

    def _request(self, method: str, url: str, data: bytes | None = None, query_string: str = "") -> Any:
        if not self.configured:
            raise RuntimeError("Upbit API Key가 설정되지 않았습니다.")
        token = create_jwt(self.access_key, self.secret_key, query_string)
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "smtm-ui/0.1",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=8) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            message = exc.reason
            try:
                payload = json.loads(exc.read().decode("utf-8"))
                message = payload.get("error", {}).get("message") or payload.get("message") or message
            except Exception:
                pass
            raise RuntimeError(f"Upbit API 오류 {exc.code}: {message}") from exc
        except (URLError, TimeoutError) as exc:
            raise RuntimeError(f"Upbit API 연결 실패: {exc}") from exc


class LiveTradingService:
    def __init__(self) -> None:
        load_dotenv()
        self.allowed_markets = parse_allowed_markets(os.environ.get("SMTM_ALLOWED_MARKETS"))
        self.max_order_krw = env_decimal("SMTM_MAX_ORDER_KRW", "5000")
        self.live_trading_enabled = env_bool("SMTM_LIVE_TRADING_ENABLED", False)
        self.client = UpbitAuthClient(
            access_key=os.environ.get("UPBIT_ACCESS_KEY", ""),
            secret_key=os.environ.get("UPBIT_SECRET_KEY", ""),
        )
        self.virtual_orders: list[dict[str, Any]] = []

    def snapshot(self, price_map: dict[str, Decimal] | None = None) -> dict[str, Any]:
        accounts: list[dict[str, Any]] = []
        error = None
        if self.client.configured:
            try:
                accounts = self._format_accounts(self.client.get("/v1/accounts"), price_map or {})
            except Exception as exc:
                error = str(exc)
        return {
            "api_configured": self.client.configured,
            "live_trading_enabled": self.live_trading_enabled,
            "mode": "실거래" if self.live_trading_enabled else "가상 주문",
            "allowed_markets": list(self.allowed_markets),
            "max_order_krw": self.max_order_krw,
            "accounts": accounts,
            "total_krw": sum((item["valuation_krw"] for item in accounts), DECIMAL_ZERO),
            "available_krw": next((item["balance"] for item in accounts if item["currency"] == "KRW"), DECIMAL_ZERO),
            "virtual_orders": self.virtual_orders[-10:],
            "error": error,
            "updated_at": utc_now().isoformat(),
        }

    def chance(self, market: str) -> dict[str, Any]:
        market = market.upper()
        self._validate_market(market)
        return self.client.get("/v1/orders/chance", {"market": market})

    def test_order(self, payload: dict[str, Any], latest_price: Decimal | None = None) -> dict[str, Any]:
        order = ManualOrder.from_payload(payload)
        body = self._validated_body(order, latest_price)
        if not self.live_trading_enabled:
            return self._virtual_result("virtual_validated", body, "SMTM_LIVE_TRADING_ENABLED=false: 가상 검증으로 처리했습니다.")
        if not self.client.configured:
            return self._virtual_result("virtual_validated", body, "API Key 미설정: 가상 검증으로 처리했습니다.")
        try:
            response = self.client.post("/v1/orders/test", body)
        except Exception as exc:
            raise RuntimeError(f"주문 검증 실패: {exc}") from exc
        return {"mode": "test", "status": "validated", "request": safe_order_body(body), "response": response}

    def submit_order(self, payload: dict[str, Any], latest_price: Decimal | None = None) -> dict[str, Any]:
        order = ManualOrder.from_payload(payload)
        body = self._validated_body(order, latest_price)
        if not self.live_trading_enabled:
            return self._virtual_result("virtual_submitted", body, "SMTM_LIVE_TRADING_ENABLED=false: 가상 주문으로 처리했습니다.")
        response = self.client.post("/v1/orders", body)
        return {"mode": "live", "status": "submitted", "request": safe_order_body(body), "response": response}

    def _validated_body(self, order: ManualOrder, latest_price: Decimal | None) -> dict[str, str]:
        self._validate_market(order.market)
        body = order.to_upbit_body()
        notional = order.estimated_notional(latest_price)
        if notional is None:
            raise ValueError("주문 금액을 추정할 수 없어 주문을 막았습니다.")
        if notional > self.max_order_krw:
            raise ValueError(f"주문 금액이 SMTM_MAX_ORDER_KRW({format_decimal(self.max_order_krw)} KRW)를 초과합니다.")
        return body

    def _validate_market(self, market: str) -> None:
        if market not in self.allowed_markets:
            raise ValueError(f"허용되지 않은 마켓입니다: {market}")

    def _virtual_result(self, status: str, body: dict[str, str], reason: str) -> dict[str, Any]:
        result = {
            "mode": "virtual",
            "status": status,
            "exchange_order_id": f"virtual-{make_id('order')}",
            "request": safe_order_body(body),
            "reason": reason,
            "created_at": utc_now().isoformat(),
        }
        self.virtual_orders.append(result)
        del self.virtual_orders[:-20]
        return result

    @staticmethod
    def _format_accounts(payload: Any, price_map: dict[str, Decimal]) -> list[dict[str, Any]]:
        if not isinstance(payload, list):
            raise RuntimeError("계좌 응답 형식이 올바르지 않습니다.")
        accounts = []
        for item in payload:
            currency = str(item.get("currency") or "").upper()
            balance = to_decimal(item.get("balance", "0"), default=DECIMAL_ZERO)
            locked = to_decimal(item.get("locked", "0"), default=DECIMAL_ZERO)
            avg_buy_price = to_decimal(item.get("avg_buy_price", "0"), default=DECIMAL_ZERO)
            total = balance + locked
            market = "KRW" if currency == "KRW" else f"KRW-{currency}"
            latest_price = Decimal("1") if currency == "KRW" else price_map.get(market, avg_buy_price)
            valuation = total * latest_price
            if total <= DECIMAL_ZERO and locked <= DECIMAL_ZERO:
                continue
            accounts.append(
                {
                    "currency": currency,
                    "market": market,
                    "balance": balance,
                    "locked": locked,
                    "total": total,
                    "avg_buy_price": avg_buy_price,
                    "latest_price": latest_price,
                    "valuation_krw": valuation,
                    "unit_currency": item.get("unit_currency") or "KRW",
                }
            )
        return accounts


def create_jwt(access_key: str, secret_key: str, query_string: str = "") -> str:
    payload: dict[str, Any] = {"access_key": access_key, "nonce": str(uuid.uuid4())}
    if query_string:
        payload["query_hash"] = hashlib.sha512(query_string.encode("utf-8")).hexdigest()
        payload["query_hash_alg"] = "SHA512"
    header = {"alg": "HS512", "typ": "JWT"}
    signing_input = b".".join([base64url_json(header), base64url_json(payload)])
    signature = hmac.new(secret_key.encode("utf-8"), signing_input, hashlib.sha512).digest()
    return b".".join([signing_input, base64url(signature)]).decode("ascii")


def build_query_string(params: dict[str, Any]) -> str:
    clean = {key: value for key, value in params.items() if value is not None and value != ""}
    return unquote(urlencode(clean, doseq=True))


def parse_allowed_markets(value: str | None) -> tuple[str, ...]:
    if not value:
        return DEFAULT_ALLOWED_MARKETS
    markets = tuple(item.strip().upper() for item in value.split(",") if item.strip())
    return markets or DEFAULT_ALLOWED_MARKETS


def optional_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return to_decimal(value)


def format_decimal(value: Decimal) -> str:
    return format(value.normalize(), "f")


def make_identifier(market: str) -> str:
    return f"smtm-{market}-{uuid.uuid4().hex[:16]}"[:64]


def safe_order_body(body: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in body.items() if key != "identifier"}


def base64url_json(payload: dict[str, Any]) -> bytes:
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64url(data)


def base64url(data: bytes) -> bytes:
    return base64.urlsafe_b64encode(data).rstrip(b"=")
