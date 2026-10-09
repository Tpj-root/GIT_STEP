"""Deriv contract broker (proposal -> buy).

IMPORTANT: this does NOT trade lots. Deriv's WebSocket API sells CONTRACTS
(multipliers, turbos, rise/fall) priced in STAKE. The `lots` argument is
interpreted as stake in account currency, and stop-loss / take-profit are passed
as a multiplier `limit_order`, not as broker-side price levels.

It is also the transport most likely to be geo/IP blocked: `proposal` and
`contracts_for` return OfferingsValidationError from restricted networks even
when market data flows fine on the same socket.
"""
from __future__ import annotations
import logging
from typing import Optional
from .base import AccountInfo, OrderResult, Position, Side

log = logging.getLogger("derivbroker")


class DerivContractBroker:
    name = "deriv"

    def __init__(self, feed, token: Optional[str] = None,
                 contract_kind: str = "MULT", multiplier: int = 100) -> None:
        self.feed = feed            # reuses the DerivFeed socket
        self.token = token
        self.contract_kind = contract_kind
        self.multiplier = multiplier
        self.connected = False
        self._authorized = False
        self.account: dict = {}

    async def connect(self) -> bool:
        if not self.token:
            log.warning("no Deriv API token -- contract trading disabled")
            self.connected = False
            return False
        try:
            res = await self.feed._send({"balance": 1})
            a = res.get("authorize", {})
            self.account = {"is_virtual": settings.deriv_account_type == "demo",
                            "balance": res["balance"]["balance"],
                            "currency": res["balance"].get("currency", "USD")}
            if not self.account["is_virtual"]:
                log.warning("Deriv token is for a REAL account (%s) -- "
                            "this is live money", self.account["loginid"])
            if "trade" not in self.account["scopes"]:
                log.error("token lacks the 'trade' scope; orders will be refused")
            self._authorized = self.connected = True
        except Exception as e:  # noqa: BLE001
            log.error("authorize failed: %s", e)
            self.connected = False
        return self.connected

    async def place_order(self, symbol, side: Side, lots, sl_points=None,
                          tp_points=None, comment="") -> OrderResult:
        if not self._authorized:
            return OrderResult(False, message="deriv broker not authorized")
        ctype = "MULTUP" if side == "buy" else "MULTDOWN"
        req = {"proposal": 1, "amount": float(lots), "basis": "stake",
               "contract_type": ctype, "currency": "USD", "symbol": symbol,
               "multiplier": self.multiplier}
        limit: dict = {}
        if sl_points:
            limit["stop_loss"] = float(sl_points)
        if tp_points:
            limit["take_profit"] = float(tp_points)
        if limit:
            req["limit_order"] = limit
        try:
            prop = await self.feed._send(req)
            pid = prop["proposal"]["id"]
            ask = float(prop["proposal"]["ask_price"])
            bought = await self.feed._send({"buy": pid, "price": ask})
            c = bought["buy"]
            return OrderResult(True, ticket=str(c["contract_id"]),
                               price=float(c.get("buy_price", ask)),
                               message="contract bought")
        except Exception as e:  # noqa: BLE001
            return OrderResult(False, message=str(e))

    async def close_position(self, ticket: str) -> OrderResult:
        try:
            res = await self.feed._send({"sell": int(ticket), "price": 0})
            return OrderResult(True, ticket=ticket,
                               price=float(res["sell"].get("sold_for", 0)),
                               message="contract sold")
        except Exception as e:  # noqa: BLE001
            return OrderResult(False, message=str(e))

    async def close_all(self) -> list[OrderResult]:
        return [await self.close_position(p.ticket) for p in await self.positions()]

    async def positions(self) -> list[Position]:
        if not self._authorized:
            return []
        try:
            res = await self.feed._send({"portfolio": 1})
            out = []
            for c in res.get("portfolio", {}).get("contracts", []):
                out.append(Position(
                    ticket=str(c["contract_id"]), symbol=c.get("symbol", ""),
                    side="buy" if "UP" in c.get("contract_type", "") else "sell",
                    lots=float(c.get("buy_price", 0)),
                    open_price=float(c.get("buy_price", 0)),
                    open_time=int(c.get("date_start", 0))))
            return out
        except Exception as e:  # noqa: BLE001
            log.debug("portfolio failed: %s", e)
            return []

    async def account_info(self) -> AccountInfo:
        if not self._authorized:
            return AccountInfo(broker=self.name, balance=0, equity=0, connected=False)
        try:
            res = await self.feed._send({"balance": 1})
            b = float(res["balance"]["balance"])
            return AccountInfo(broker=self.name, balance=b, equity=b,
                               currency=res["balance"].get("currency", "USD"))
        except Exception as e:  # noqa: BLE001
            return AccountInfo(broker=self.name, balance=0, equity=0, connected=False)
