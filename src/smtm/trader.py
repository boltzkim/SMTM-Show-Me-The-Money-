"""Trader implementations and simulation virtual market."""

from __future__ import annotations

from decimal import Decimal

from .exceptions import TraderError
from .models import AccountInfo, CandleInfo, OrderResult, TradeRequest
from .utils import DECIMAL_ZERO, make_id, quantize_down, to_decimal, utc_now


class VirtualMarket:
    def __init__(
        self,
        fee_rate: Decimal = Decimal("0.0005"),
        slippage_rate: Decimal = Decimal("0"),
        max_volume_participation: Decimal = Decimal("1"),
    ) -> None:
        self.fee_rate = fee_rate
        self.slippage_rate = slippage_rate
        self.max_volume_participation = max_volume_participation
        self.pending_orders: list[TradeRequest] = []

    def submit(self, request: TradeRequest) -> OrderResult:
        self.pending_orders.append(request)
        return OrderResult(
            request_id=request.request_id,
            market=request.market,
            side=request.type,
            status="submitted",
            exchange_order_id=f"sim-{request.request_id}",
            reason="accepted by virtual market",
            raw={"client_order_id": request.client_order_id},
        )

    def cancel(self, order_id: str) -> OrderResult:
        for index, request in enumerate(self.pending_orders):
            if order_id in {request.request_id, f"sim-{request.request_id}"}:
                self.pending_orders.pop(index)
                return OrderResult(
                    request_id=request.request_id,
                    market=request.market,
                    side=request.type,
                    status="canceled",
                    exchange_order_id=f"sim-{request.request_id}",
                    reason="canceled in virtual market",
                )
        raise TraderError(f"order not found: {order_id}")

    def settle(self, candle: CandleInfo, account: AccountInfo) -> list[OrderResult]:
        results: list[OrderResult] = []
        still_pending: list[TradeRequest] = []
        for request in self.pending_orders:
            if request.market != candle.market:
                still_pending.append(request)
                continue
            result, remaining = self._try_fill(request, candle, account)
            if result is not None:
                results.append(result)
            if remaining is not None and remaining.amount > DECIMAL_ZERO:
                still_pending.append(remaining)
        self.pending_orders = still_pending
        return results

    def _try_fill(
        self,
        request: TradeRequest,
        candle: CandleInfo,
        account: AccountInfo,
    ) -> tuple[OrderResult | None, TradeRequest | None]:
        fill_price = self._fill_price(request, candle)
        if fill_price is None:
            return None, request

        volume_cap = candle.acc_volume * self.max_volume_participation
        fill_amount = request.amount
        if volume_cap > DECIMAL_ZERO:
            fill_amount = min(fill_amount, volume_cap)
        fill_amount = quantize_down(fill_amount)
        if fill_amount <= DECIMAL_ZERO:
            return None, request

        if request.type == "buy":
            fill_amount = self._cap_buy_amount(account, fill_price, fill_amount)
            if fill_amount <= DECIMAL_ZERO:
                return self._rejected(request, "insufficient virtual cash"), None
            fee = fill_price * fill_amount * self.fee_rate
            gross = fill_price * fill_amount
            account.cash -= gross + fee
            self._add_balance(account, request.market, fill_amount, fill_price)
        elif request.type == "sell":
            fill_amount = min(fill_amount, account.balance_for(request.market))
            fill_amount = quantize_down(fill_amount)
            if fill_amount <= DECIMAL_ZERO:
                return self._rejected(request, "insufficient virtual balance"), None
            fee = fill_price * fill_amount * self.fee_rate
            gross = fill_price * fill_amount
            account.cash += gross - fee
            self._subtract_balance(account, request.market, fill_amount)
        else:
            return self._rejected(request, f"unsupported request type: {request.type}"), None

        remaining_amount = quantize_down(request.amount - fill_amount)
        status = "partially_filled" if remaining_amount > DECIMAL_ZERO else "filled"
        remaining = request.with_amount(remaining_amount) if remaining_amount > DECIMAL_ZERO else None
        return (
            OrderResult(
                request_id=request.request_id,
                market=request.market,
                side=request.type,
                status=status,
                exchange_order_id=f"sim-{request.request_id}",
                filled_price=fill_price,
                filled_amount=fill_amount,
                fee=fee,
                reason="filled by virtual market",
                raw={"client_order_id": request.client_order_id},
            ),
            remaining,
        )

    def _fill_price(self, request: TradeRequest, candle: CandleInfo) -> Decimal | None:
        if request.order_type == "market":
            if request.type == "buy":
                return candle.opening_price * (Decimal("1") + self.slippage_rate)
            return candle.opening_price * (Decimal("1") - self.slippage_rate)
        if request.type == "buy" and candle.low_price <= request.price:
            return min(request.price, candle.opening_price) * (Decimal("1") + self.slippage_rate)
        if request.type == "sell" and candle.high_price >= request.price:
            return max(request.price, candle.opening_price) * (Decimal("1") - self.slippage_rate)
        return None

    def _cap_buy_amount(self, account: AccountInfo, price: Decimal, amount: Decimal) -> Decimal:
        required = price * amount * (Decimal("1") + self.fee_rate)
        if account.cash >= required:
            return amount
        return quantize_down(account.cash / (price * (Decimal("1") + self.fee_rate)))

    @staticmethod
    def _add_balance(account: AccountInfo, market: str, amount: Decimal, price: Decimal) -> None:
        current_amount = account.balances.get(market, DECIMAL_ZERO)
        current_cost = current_amount * account.average_prices.get(market, DECIMAL_ZERO)
        next_amount = current_amount + amount
        account.balances[market] = next_amount
        if next_amount > DECIMAL_ZERO:
            account.average_prices[market] = (current_cost + amount * price) / next_amount

    @staticmethod
    def _subtract_balance(account: AccountInfo, market: str, amount: Decimal) -> None:
        next_amount = quantize_down(account.balances.get(market, DECIMAL_ZERO) - amount)
        if next_amount <= DECIMAL_ZERO:
            account.balances.pop(market, None)
            account.average_prices.pop(market, None)
        else:
            account.balances[market] = next_amount

    @staticmethod
    def _rejected(request: TradeRequest, reason: str) -> OrderResult:
        return OrderResult(
            request_id=request.request_id,
            market=request.market,
            side=request.type,
            status="rejected",
            exchange_order_id=f"sim-{request.request_id}",
            reason=reason,
        )


class SimulationTrader:
    def __init__(self) -> None:
        self.account = AccountInfo.empty(0)
        self.market = VirtualMarket()
        self.last_candle: CandleInfo | None = None

    def initialize(self, config: dict) -> None:
        self.account = AccountInfo.empty(config.get("budget", 0))
        self.market = VirtualMarket(
            fee_rate=to_decimal(config.get("fee_rate", "0.0005")),
            slippage_rate=to_decimal(config.get("slippage_rate", "0")),
            max_volume_participation=to_decimal(config.get("max_volume_participation", "1")),
        )

    def settle(self, candle: CandleInfo) -> list[OrderResult]:
        self.last_candle = candle
        results = self.market.settle(candle, self.account)
        self.account.mark_to_market(candle)
        return results

    def send_request(self, request: TradeRequest) -> OrderResult | None:
        if request.type == "cancel":
            return self.cancel_order(request.request_id)
        return self.market.submit(request)

    def get_account_info(self) -> AccountInfo:
        return self.account.copy().mark_to_market(self.last_candle)

    def get_order_status(self, order_id: str) -> OrderResult | None:
        for request in self.market.pending_orders:
            if order_id in {request.request_id, f"sim-{request.request_id}"}:
                return OrderResult(
                    request_id=request.request_id,
                    market=request.market,
                    side=request.type,
                    status="submitted",
                    exchange_order_id=f"sim-{request.request_id}",
                )
        return None

    def cancel_order(self, order_id: str) -> OrderResult:
        return self.market.cancel(order_id)

    @property
    def active_orders(self) -> list[TradeRequest]:
        return list(self.market.pending_orders)


class DryRunTrader:
    """Records live-mode order intent without touching an exchange account."""

    def __init__(self) -> None:
        self.account = AccountInfo.empty(0)
        self.orders: dict[str, OrderResult] = {}

    def initialize(self, config: dict) -> None:
        self.account = AccountInfo.empty(config.get("budget", 0))

    def send_request(self, request: TradeRequest) -> OrderResult | None:
        result = OrderResult(
            request_id=request.request_id,
            market=request.market,
            side=request.type,
            status="submitted",
            exchange_order_id=f"dry-{make_id('order')}",
            reason="dry-run: no exchange order submitted",
            raw={"client_order_id": request.client_order_id},
        )
        self.orders[result.exchange_order_id] = result
        return result

    def get_account_info(self) -> AccountInfo:
        return self.account.copy()

    def get_order_status(self, order_id: str) -> OrderResult | None:
        return self.orders.get(order_id)

    def cancel_order(self, order_id: str) -> OrderResult:
        result = self.orders.get(order_id)
        if result is None:
            raise TraderError(f"dry-run order not found: {order_id}")
        canceled = OrderResult(
            request_id=result.request_id,
            market=result.market,
            side=result.side,
            status="canceled",
            exchange_order_id=order_id,
            reason="dry-run cancellation",
            created_at=utc_now(),
        )
        self.orders[order_id] = canceled
        return canceled

    @property
    def active_orders(self) -> list[TradeRequest]:
        return []


def build_trader(config: dict) -> SimulationTrader | DryRunTrader:
    mode = str(config.get("mode", "simulation")).lower()
    dry_run = bool(config.get("dry_run", True))
    if mode == "simulation":
        trader = SimulationTrader()
    elif mode == "live" and dry_run:
        trader = DryRunTrader()
    else:
        raise TraderError("live exchange orders are not implemented in this MVP; use dry_run=true")
    trader.initialize(config)
    return trader

