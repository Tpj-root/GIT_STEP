"""Paper broker -- the default. The whole app must run end to end with no
credentials, so this is a first-class implementation, not a stub.

It marks positions to the live feed price, honours SL/TP, and keeps realised
P&L so the risk guard's daily-loss limit is exercised for real in paper mode.
"""
from __future__ import annotations
import time, uuid, logging
from typing import Callable, Optional
from .base import AccountInfo, Broker, OrderResult, Position, Side

log = logging.getLogger("paper")


class PaperBroker:
    name = "paper"

    def __init__(self, starting_balance: float = 10_000.0,
                 price_fn: Optional[Callable[[str], Optional[float]]] = None,
                 point_fn: Optional[Callable[[str], float]] = None) -> None:
        self.balance = starting_balance
        self.realised = 0.0
        self._positions: dict[str, Position] = {}
        self._price_fn = price_fn or (lambda s: None)
        self._point_fn = point_fn or (lambda s: 0.1)
        self.closed_log: list[dict] = []

    async def connect(self) -> bool:
        return True

    def _price(self, symbol: str) -> Optional[float]:
        return self._price_fn(symbol)

    async def place_order(self, symbol, side: Side, lots, sl_points=None,
                          tp_points=None, comment="") -> OrderResult:
        px = self._price(symbol)
        if px is None:
            return OrderResult(False, message=f"no price for {symbol}")
        point = self._point_fn(symbol)
        sign = 1 if side == "buy" else -1
        sl = px - sign * sl_points * point if sl_points else None
        tp = px + sign * tp_points * point if tp_points else None
        ticket = uuid.uuid4().hex[:12]
        self._positions[ticket] = Position(
            ticket=ticket, symbol=symbol, side=side, lots=float(lots),
            open_price=px, open_time=int(time.time()), sl=sl, tp=tp,
            current_price=px)
        log.info("paper OPEN %s %s %s @ %s sl=%s tp=%s", side, lots, symbol, px, sl, tp)
        return OrderResult(True, ticket=ticket, price=px, message="paper fill")

    async def close_position(self, ticket: str) -> OrderResult:
        pos = self._positions.get(ticket)
        if pos is None:
            return OrderResult(False, message=f"unknown ticket {ticket}")
        px = self._price(pos.symbol) or pos.open_price
        pnl = self._pnl(pos, px)
        self.realised += pnl
        self.balance += pnl
        del self._positions[ticket]
        self.closed_log.append({**pos.to_dict(), "close_price": px,
                                "close_time": int(time.time()), "profit": pnl})
        log.info("paper CLOSE %s @ %s pnl=%.2f", ticket, px, pnl)
        return OrderResult(True, ticket=ticket, price=px, message=f"closed pnl={pnl:.2f}")

    async def close_all(self) -> list[OrderResult]:
        return [await self.close_position(t) for t in list(self._positions)]

    def _pnl(self, pos: Position, px: float) -> float:
        sign = 1 if pos.side == "buy" else -1
        point = self._point_fn(pos.symbol)
        return sign * (px - pos.open_price) / point * pos.lots

    async def positions(self) -> list[Position]:
        await self.mark_to_market()
        return list(self._positions.values())

    async def mark_to_market(self) -> list[str]:
        """Update floating P&L and trigger SL/TP. Returns tickets auto-closed."""
        hit = []
        for ticket, pos in list(self._positions.items()):
            px = self._price(pos.symbol)
            if px is None:
                continue
            pos.current_price = px
            pos.profit = self._pnl(pos, px)
            if pos.side == "buy":
                if (pos.sl and px <= pos.sl) or (pos.tp and px >= pos.tp):
                    hit.append(ticket)
            else:
                if (pos.sl and px >= pos.sl) or (pos.tp and px <= pos.tp):
                    hit.append(ticket)
        for t in hit:
            await self.close_position(t)
        return hit

    async def account_info(self) -> AccountInfo:
        floating = sum(p.profit for p in self._positions.values())
        return AccountInfo(broker=self.name, balance=self.balance,
                           equity=self.balance + floating, connected=True)
