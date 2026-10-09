"""Server-side risk guard. Authoritative.

The frontend may render these limits, but it must never be the thing enforcing
them -- a stale tab, a paused JS thread or an open devtools console must not be
able to let an order through.
"""
from __future__ import annotations
import time, logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional
from .config import ModeConfig, Mode

log = logging.getLogger("risk")


class Reject(Exception):
    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


@dataclass
class DayCounters:
    day_key: str
    trades: int = 0
    realised_pnl: float = 0.0


class RiskGuard:
    def __init__(self, hard_max_lots: float, hard_max_daily_loss: float,
                 stale_seconds: float, reset_hour_utc: int = 0) -> None:
        self.hard_max_lots = hard_max_lots
        self.hard_max_daily_loss = hard_max_daily_loss
        self.stale_seconds = stale_seconds
        self.reset_hour_utc = reset_hour_utc

        self.kill_switch = False
        self.mode: Mode = Mode.manual      # never boots into auto; see reset_on_boot
        self._counters = DayCounters(self._day_key())
        self._seen_signals: dict[str, str] = {}   # idempotency key -> order uuid

    # ------------------------------------------------------------ day rollover
    def _day_key(self, now: Optional[float] = None) -> str:
        dt = datetime.fromtimestamp(now or time.time(), tz=timezone.utc)
        if dt.hour < self.reset_hour_utc:
            dt -= timedelta(days=1)
        return dt.strftime("%Y-%m-%d")

    @property
    def counters(self) -> DayCounters:
        key = self._day_key()
        if self._counters.day_key != key:
            log.info("daily counters reset (%s -> %s)", self._counters.day_key, key)
            self._counters = DayCounters(key)
            self._seen_signals.clear()
        return self._counters

    # ------------------------------------------------------------ idempotency
    def already_traded(self, idem_key: str) -> Optional[str]:
        return self.counters and self._seen_signals.get(idem_key)

    def remember(self, idem_key: str, order_uuid: str) -> None:
        self._seen_signals[idem_key] = order_uuid

    # ------------------------------------------------------------ the check
    def check(self, *, cfg: ModeConfig, symbol: str, lots: float,
              open_positions: int, feed_stale: bool, broker_connected: bool,
              source: str, idem_key: Optional[str] = None) -> None:
        """Raise Reject if this order must not be placed."""
        c = self.counters

        if self.kill_switch:
            raise Reject("kill_switch", "kill switch engaged")

        if not broker_connected:
            raise Reject("broker_down", "broker not connected")

        if feed_stale:
            raise Reject("stale_data",
                         f"no market data in >{self.stale_seconds:.0f}s")

        if lots <= 0:
            raise Reject("bad_lots", f"lots must be > 0, got {lots}")

        if lots > self.hard_max_lots:
            raise Reject("lots_cap",
                         f"{lots} exceeds hard cap {self.hard_max_lots}")

        if lots > cfg.lots * 1.0000001:
            raise Reject("lots_cap",
                         f"{lots} exceeds configured {cfg.lots} for this mode")

        if open_positions >= cfg.max_concurrent_positions:
            raise Reject("max_positions",
                         f"{open_positions} open, limit {cfg.max_concurrent_positions}")

        if cfg.max_trades_per_day is not None and c.trades >= cfg.max_trades_per_day:
            raise Reject("max_trades",
                         f"{c.trades} today, limit {cfg.max_trades_per_day}")

        if cfg.max_daily_loss is not None and -c.realised_pnl >= cfg.max_daily_loss:
            raise Reject("daily_loss",
                         f"realised {c.realised_pnl:.2f}, limit -{cfg.max_daily_loss}")

        if -c.realised_pnl >= self.hard_max_daily_loss:
            raise Reject("daily_loss", "hard daily-loss cap reached")

        if source == "auto":
            if self.mode is not Mode.auto:
                raise Reject("not_armed", "auto order while not in auto mode")
            if idem_key and idem_key in self._seen_signals:
                raise Reject("duplicate",
                             f"signal {idem_key} already traded as "
                             f"{self._seen_signals[idem_key]}")

    # ------------------------------------------------------------ bookkeeping
    def record_trade(self) -> None:
        self.counters.trades += 1

    def record_pnl(self, pnl: float) -> None:
        self.counters.realised_pnl += pnl

    def engage_kill_switch(self) -> None:
        self.kill_switch = True
        self.mode = Mode.manual
        log.warning("KILL SWITCH engaged -- forced to manual")

    def release_kill_switch(self) -> None:
        self.kill_switch = False
        log.info("kill switch released")

    def disarm(self, why: str) -> bool:
        """Drop out of auto mode. Returns True if it was armed."""
        was = self.mode is Mode.auto
        self.mode = Mode.manual
        if was:
            log.warning("AUTO DISARMED: %s", why)
        return was

    def status(self) -> dict:
        c = self.counters
        return {"mode": self.mode.value, "kill_switch": self.kill_switch,
                "day": c.day_key, "trades_today": c.trades,
                "realised_pnl": round(c.realised_pnl, 2),
                "hard_max_lots": self.hard_max_lots,
                "signals_traded": len(self._seen_signals)}
