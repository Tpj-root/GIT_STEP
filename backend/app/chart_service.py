"""Owns candle series + indicator engines per (symbol, timeframe) and turns
CLOSED bars into signals.

The one invariant that matters here: engines are only ever fed bars that the
CandleSeries has confirmed closed. Forming bars update the chart and nothing
else.
"""
from __future__ import annotations
import logging, time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from .feed import Candle, DerivFeed
from .series import CandleSeries
from .indicators import create, compute_overlay, overlay_specs

log = logging.getLogger("chart")

Key = tuple[str, int]


@dataclass
class Signal:
    symbol: str
    granularity: int
    bar_epoch: int
    direction: int            # +1 buy, -1 sell
    action: str               # "BUY" | "SELL"
    price: float
    indicator: str = "chandelier"
    state: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"symbol": self.symbol, "granularity": self.granularity,
                "bar_epoch": self.bar_epoch, "direction": self.direction,
                "action": self.action, "price": self.price,
                "indicator": self.indicator, "state": self.state}

    @property
    def idempotency_key(self) -> str:
        """(symbol, timeframe, bar_epoch, direction) -- one order per signal bar,
        no matter how many times the bar is re-delivered after a reconnect."""
        return f"{self.symbol}:{self.granularity}:{self.bar_epoch}:{self.direction}"


class ChartService:
    def __init__(self, feed: DerivFeed) -> None:
        self.feed = feed
        self.series: dict[Key, CandleSeries] = {}
        self.engines: dict[Key, object] = {}
        self.params: dict[str, float] = {"period": 22, "multiplier": 3.0}
        # Display indicators, TradingView-style: each can be toggled on/off and
        # carries its own parameters. Chandelier is not in here -- it is the
        # signal source and is always computed.
        self.overlays: dict[str, dict] = {
            s["id"]: {"visible": False,
                      **{p["name"]: p["default"] for p in s["params"]}}
            for s in overlay_specs()
        }
        self.on_signal: Optional[Callable[[Signal], Awaitable]] = None
        self.on_bar_event: Optional[Callable[[str, dict], Awaitable]] = None

        feed.on_history = self._handle_history
        feed.on_bar = self._handle_bar

    # ------------------------------------------------------------------ setup
    async def ensure(self, symbol: str, granularity: int, count: int = 1000) -> list[Candle]:
        key = (symbol, granularity)
        if key not in self.series:
            self.series[key] = CandleSeries(granularity)
        candles = await self.feed.subscribe(symbol, granularity, count=count)
        return candles

    def set_params(self, **params) -> None:
        """Changing indicator parameters invalidates every engine -- they are
        stateful folds, so they must be rebuilt from history, not patched."""
        self.params.update({k: v for k, v in params.items() if v is not None})
        for key in list(self.engines):
            self._rebuild(key)

    def _new_engine(self):
        return create("chandelier", period=int(self.params["period"]),
                      multiplier=float(self.params["multiplier"]))

    def _rebuild(self, key: Key) -> None:
        """Replay the engine over every CLOSED bar in the series."""
        s = self.series.get(key)
        if s is None:
            return
        eng = self._new_engine()
        for bar in s.closed_bars:
            eng.update(bar)
        self.engines[key] = eng

    # ------------------------------------------------------------------ feed hooks
    async def _handle_history(self, symbol: str, granularity: int,
                              candles: list[Candle]) -> None:
        key = (symbol, granularity)
        s = self.series.setdefault(key, CandleSeries(granularity))
        if len(s) == 0:
            s.reset(candles)
        else:
            changed = s.reconcile(candles)
            log.info("reconciled %s/%ss: %d bars added/corrected", symbol, granularity, changed)
        self._rebuild(key)
        if self.on_bar_event:
            await self.on_bar_event("history", {
                "symbol": symbol, "granularity": granularity,
                "candles": [c.to_dict() for c in s.bars],
                "line": self.indicator_line(symbol, granularity),
                "overlays": self.overlay_data(symbol, granularity),
                "indicator": self.snapshot(symbol, granularity),
            })

    async def _handle_bar(self, symbol: str, granularity: int,
                          bar: Candle, _closed: bool) -> None:
        key = (symbol, granularity)
        s = self.series.setdefault(key, CandleSeries(granularity))
        if key not in self.engines:
            self._rebuild(key)

        update = s.upsert(bar)

        if update.closed is not None:
            eng = self.engines[key]
            state = eng.update(update.closed)          # ONLY closed bars
            if state.get("signal"):
                sig = Signal(
                    symbol=symbol, granularity=granularity,
                    bar_epoch=update.closed.epoch,
                    direction=state["direction"], action=state["signal"],
                    price=update.closed.close, state=state)
                log.info("SIGNAL %s %s @ %s (bar %s)", sig.action, symbol,
                         sig.price, sig.bar_epoch)
                if self.on_signal:
                    await self.on_signal(sig)

        if self.on_bar_event:
            await self.on_bar_event("ohlc", {
                "symbol": symbol, "granularity": granularity,
                "bar": update.bar.to_dict(), "appended": update.appended,
                "closed_epoch": update.closed.epoch if update.closed else None,
                "indicator": self.snapshot(symbol, granularity),
            })

    # ------------------------------------------------------------------ reads
    def symbol_age(self, symbol: str) -> float:
        """Seconds since this symbol produced a NEW BAR.

        Not "seconds since the last API response": a poller keeps getting
        replies for a closed market, they just contain the same stale bars. A
        forming bar is legitimately up to `granularity` seconds old, so that is
        subtracted before judging.
        """
        best: Optional[float] = None
        now = time.time()
        for (sym, gran), series in self.series.items():
            if sym != symbol or series.last is None:
                continue
            age = now - (series.last.epoch + gran)
            best = age if best is None else min(best, age)
        return float("inf") if best is None else max(best, 0.0)

    def snapshot(self, symbol: str, granularity: int) -> dict:
        eng = self.engines.get((symbol, granularity))
        return eng.snapshot() if eng else {"ready": False}

    def overlay_data(self, symbol: str, granularity: int) -> dict[str, dict]:
        """Computed series for every VISIBLE display indicator.

        Hidden indicators are skipped entirely rather than computed and dropped
        client-side -- on 1000 bars that is real work for pixels nobody sees.
        """
        series = self.series.get((symbol, granularity))
        if not series or not series.bars:
            return {}
        bars = series.closed_bars or series.bars
        out: dict[str, dict] = {}
        for oid, cfg in self.overlays.items():
            if not cfg.get("visible"):
                continue
            params = {k: v for k, v in cfg.items() if k != "visible"}
            try:
                out[oid] = compute_overlay(oid, bars, **params)
            except Exception as e:                      # noqa: BLE001
                log.warning("overlay %s failed: %s", oid, e)
        return out

    def set_overlay(self, oid: str, patch: dict) -> dict:
        if oid not in self.overlays:
            raise KeyError(oid)
        self.overlays[oid] = {**self.overlays[oid], **patch}
        return self.overlays[oid]

    def indicator_line(self, symbol: str, granularity: int) -> list[dict]:
        """Replay history to produce the drawable stop line.

        Only the ACTIVE side is emitted per bar -- drawing both stops at once
        reads as support/resistance and is visually wrong for this indicator.
        """
        s = self.series.get((symbol, granularity))
        if not s:
            return []
        eng = self._new_engine()
        out = []
        for bar in s.closed_bars:
            st = eng.update(bar)
            if st.get("ready"):
                out.append({"epoch": bar.epoch,
                            "value": st["active_stop"],
                            "direction": st["direction"],
                            "flip": bool(st["flipped"]),
                            "signal": st["signal"]})
        return out
