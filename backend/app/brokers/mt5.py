"""MT5 broker bridge.

The `MetaTrader5` package is Windows-only and talks to a locally running MT5
terminal. It is imported LAZILY so the rest of the app -- and the whole paper
path -- runs on Linux and in CI, where the package cannot even be installed.

Deriv's WebSocket API cannot place MT5 orders. Its `mt5_*` calls cover account
creation, balance and transfers only; there is no `mt5_buy`. Lot-based trading
on Step Index and XAUUSD therefore has to go through this bridge.
"""
from __future__ import annotations
import asyncio, logging, uuid
from typing import Optional
from .base import AccountInfo, OrderResult, Position, Side

log = logging.getLogger("mt5")


class MT5Unavailable(RuntimeError):
    pass


def _import_mt5():
    try:
        import MetaTrader5 as mt5  # type: ignore
        return mt5
    except Exception as e:  # noqa: BLE001
        raise MT5Unavailable(
            "MetaTrader5 package unavailable (Windows only, and the MT5 terminal "
            f"must be running). Underlying: {e}") from e


class MT5Broker:
    name = "mt5"

    def __init__(self, login: Optional[int], password: Optional[str],
                 server: Optional[str], symbol_map: dict[str, str] | None = None) -> None:
        self.login, self.password, self.server = login, password, server
        self.symbol_map = symbol_map or {}
        self._mt5 = None
        self.connected = False

    def _sym(self, symbol: str) -> str:
        return self.symbol_map.get(symbol, symbol)

    async def connect(self) -> bool:
        def _do():
            mt5 = _import_mt5()
            if not mt5.initialize(login=self.login, password=self.password,
                                  server=self.server):
                raise MT5Unavailable(f"initialize failed: {mt5.last_error()}")
            return mt5
        try:
            self._mt5 = await asyncio.to_thread(_do)
            self.connected = True
            log.info("MT5 connected (%s@%s)", self.login, self.server)
        except Exception as e:  # noqa: BLE001
            self.connected = False
            log.error("MT5 connect failed: %s", e)
        return self.connected

    def _require(self):
        if not self.connected or self._mt5 is None:
            raise MT5Unavailable("MT5 not connected")
        return self._mt5

    async def place_order(self, symbol, side: Side, lots, sl_points=None,
                          tp_points=None, comment="") -> OrderResult:
        def _do():
            mt5 = self._require()
            sym = self._sym(symbol)
            info = mt5.symbol_info(sym)
            if info is None:
                raise MT5Unavailable(f"symbol {sym} not found on terminal")
            if not info.visible:
                mt5.symbol_select(sym, True)
            tick = mt5.symbol_info_tick(sym)
            price = tick.ask if side == "buy" else tick.bid
            point = info.point
            sign = 1 if side == "buy" else -1
            req = {
                "action": mt5.TRADE_ACTION_DEAL, "symbol": sym,
                "volume": float(lots),
                "type": mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL,
                "price": price, "deviation": 20,
                "magic": 20260912, "comment": (comment or "chandelier")[:31],
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            if sl_points:
                req["sl"] = price - sign * sl_points * point
            if tp_points:
                req["tp"] = price + sign * tp_points * point
            res = mt5.order_send(req)
            if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
                code = getattr(res, "retcode", None)
                return OrderResult(False, message=f"order_send failed: {code} "
                                                  f"{getattr(res,'comment','')}",
                                   retcode=code)
            return OrderResult(True, ticket=str(res.order), price=res.price,
                               message="filled", retcode=res.retcode)
        try:
            return await asyncio.to_thread(_do)
        except Exception as e:  # noqa: BLE001
            return OrderResult(False, message=str(e))

    async def close_position(self, ticket: str) -> OrderResult:
        def _do():
            mt5 = self._require()
            pos = mt5.positions_get(ticket=int(ticket))
            if not pos:
                return OrderResult(False, message=f"no open position {ticket}")
            p = pos[0]
            tick = mt5.symbol_info_tick(p.symbol)
            is_buy = p.type == mt5.POSITION_TYPE_BUY
            res = mt5.order_send({
                "action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol,
                "volume": p.volume, "position": p.ticket,
                "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
                "price": tick.bid if is_buy else tick.ask,
                "deviation": 20, "magic": 20260912, "comment": "close",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC})
            ok = res is not None and res.retcode == mt5.TRADE_RETCODE_DONE
            return OrderResult(ok, ticket=ticket, price=getattr(res, "price", None),
                               message="closed" if ok else f"close failed {getattr(res,'retcode',None)}")
        try:
            return await asyncio.to_thread(_do)
        except Exception as e:  # noqa: BLE001
            return OrderResult(False, message=str(e))

    async def close_all(self) -> list[OrderResult]:
        return [await self.close_position(p.ticket) for p in await self.positions()]

    async def positions(self) -> list[Position]:
        def _do():
            mt5 = self._require()
            out = []
            for p in (mt5.positions_get() or []):
                out.append(Position(
                    ticket=str(p.ticket), symbol=p.symbol,
                    side="buy" if p.type == mt5.POSITION_TYPE_BUY else "sell",
                    lots=p.volume, open_price=p.price_open, open_time=int(p.time),
                    sl=p.sl or None, tp=p.tp or None, profit=p.profit,
                    current_price=p.price_current))
            return out
        try:
            return await asyncio.to_thread(_do)
        except Exception as e:  # noqa: BLE001
            log.debug("positions failed: %s", e)
            return []

    async def account_info(self) -> AccountInfo:
        def _do():
            mt5 = self._require()
            a = mt5.account_info()
            return AccountInfo(broker=self.name, balance=a.balance, equity=a.equity,
                               margin=a.margin, currency=a.currency, connected=True)
        try:
            return await asyncio.to_thread(_do)
        except Exception as e:  # noqa: BLE001
            return AccountInfo(broker=self.name, balance=0, equity=0,
                               connected=False, currency="USD")
