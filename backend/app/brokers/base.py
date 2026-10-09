"""Broker protocol. Three implementations ship: paper (default), mt5, deriv."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Literal, Optional, Protocol, runtime_checkable

Side = Literal["buy", "sell"]


@dataclass
class Position:
    ticket: str
    symbol: str
    side: Side
    lots: float
    open_price: float
    open_time: int
    sl: Optional[float] = None
    tp: Optional[float] = None
    profit: float = 0.0
    current_price: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OrderResult:
    ok: bool
    ticket: Optional[str] = None
    price: Optional[float] = None
    message: str = ""
    retcode: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AccountInfo:
    broker: str
    balance: float
    equity: float
    margin: float = 0.0
    currency: str = "USD"
    connected: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@runtime_checkable
class Broker(Protocol):
    name: str
    async def connect(self) -> bool: ...
    async def place_order(self, symbol: str, side: Side, lots: float,
                          sl_points: Optional[float] = None,
                          tp_points: Optional[float] = None,
                          comment: str = "") -> OrderResult: ...
    async def close_position(self, ticket: str) -> OrderResult: ...
    async def close_all(self) -> list[OrderResult]: ...
    async def positions(self) -> list[Position]: ...
    async def account_info(self) -> AccountInfo: ...
