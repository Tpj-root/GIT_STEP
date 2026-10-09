"""Append-only SQLite audit log.

Every signal and every order attempt is written, accepted or rejected. This is
what you read when the app does something surprising, and it will.
"""
from __future__ import annotations
import json, time
import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL, symbol TEXT NOT NULL, granularity INTEGER NOT NULL,
  bar_epoch INTEGER NOT NULL, action TEXT NOT NULL, direction INTEGER NOT NULL,
  price REAL NOT NULL, indicator TEXT NOT NULL, state TEXT NOT NULL,
  idem_key TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL, order_uuid TEXT NOT NULL UNIQUE, idem_key TEXT,
  source TEXT NOT NULL, mode TEXT NOT NULL, symbol TEXT NOT NULL,
  side TEXT NOT NULL, lots REAL NOT NULL,
  sl_points REAL, tp_points REAL,
  accepted INTEGER NOT NULL, reject_reason TEXT,
  broker TEXT, ticket TEXT, fill_price REAL, response TEXT
);
CREATE INDEX IF NOT EXISTS ix_orders_ts ON orders(ts);
CREATE INDEX IF NOT EXISTS ix_signals_ts ON signals(ts);
"""


class Store:
    def __init__(self, path: str) -> None:
        self.path = path
        self._db: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    async def log_signal(self, sig) -> None:
        await self._db.execute(
            "INSERT INTO signals (ts,symbol,granularity,bar_epoch,action,direction,"
            "price,indicator,state,idem_key) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (time.time(), sig.symbol, sig.granularity, sig.bar_epoch, sig.action,
             sig.direction, sig.price, sig.indicator, json.dumps(sig.state),
             sig.idempotency_key))
        await self._db.commit()

    async def log_order(self, **kw) -> None:
        cols = ("order_uuid", "idem_key", "source", "mode", "symbol", "side", "lots",
                "sl_points", "tp_points", "accepted", "reject_reason", "broker",
                "ticket", "fill_price", "response")
        vals = [time.time()] + [kw.get(c) for c in cols]
        await self._db.execute(
            f"INSERT OR IGNORE INTO orders (ts,{','.join(cols)}) "
            f"VALUES ({','.join('?' * (len(cols) + 1))})", vals)
        await self._db.commit()

    async def recent(self, table: str, limit: int = 100) -> list[dict]:
        if table not in ("orders", "signals"):
            raise ValueError("bad table")
        cur = await self._db.execute(
            f"SELECT * FROM {table} ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in await cur.fetchall()]
