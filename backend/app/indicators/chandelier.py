"""Chandelier Exit (Chuck LeBeau).

    ATR       = Wilder-smoothed True Range over `period`
    longStop  = highest_high(period) - multiplier * ATR
    shortStop = lowest_low(period)   + multiplier * ATR

Direction is STATEFUL and must be folded bar by bar -- it cannot be vectorised
independently per bar, because each bar's direction depends on the previous
bar's ratcheted stops:

    direction starts at +1
    close > prev_shortStop -> +1
    close < prev_longStop  -> -1
    otherwise                 unchanged

    longStop  ratchets up   while direction == +1 (never decreases)
    shortStop ratchets down while direction == -1 (never increases)

The inactive side is not ratcheted, so a flip restarts the ratchet from a fresh
value rather than inheriting a stale one.

`update()` must be called ONCE PER CLOSED BAR. Feeding it a forming bar will
produce signals that later repaint away.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from typing import Optional
from .base import IndicatorSpec, ParamSpec, SeriesSpec, register


@dataclass
class ChandelierState:
    epoch: int = 0
    atr: Optional[float] = None
    long_stop: Optional[float] = None
    short_stop: Optional[float] = None
    direction: int = 1
    flipped: bool = False           # direction changed on THIS bar
    signal: Optional[str] = None    # "BUY" | "SELL" | None
    ready: bool = False             # ATR seeded, values meaningful

    def to_dict(self) -> dict:
        return {
            "epoch": self.epoch, "atr": self.atr,
            "long_stop": self.long_stop, "short_stop": self.short_stop,
            "direction": self.direction, "flipped": self.flipped,
            "signal": self.signal, "ready": self.ready,
            "active_stop": (self.long_stop if self.direction > 0 else self.short_stop),
        }


class ChandelierEngine:
    def __init__(self, period: int = 22, multiplier: float = 3.0,
                 use_close: bool = True, tv_ratchet: bool = True) -> None:
        """`use_close` and `tv_ratchet` default to TradingView's behaviour.

        The most-installed TradingView script (Chandelier Exit by everget)
        differs from the plain textbook definition in two ways, and both move
        flip points:

          use_close   extremes from highest(CLOSE)/lowest(CLOSE) rather than
                      highest(HIGH)/lowest(LOW). This is everget's DEFAULT and
                      it dominates: on XAUUSD 1h it is the difference between
                      92.5% and 99.4% direction agreement.
          tv_ratchet  the ratchet is gated on close[1] vs the previous stop, and
                      the inactive side is never reset. The textbook form gates
                      on direction and resets the inactive side.

        Set both False for the textbook definition.
        """
        if period < 1:
            raise ValueError("period must be >= 1")
        if multiplier <= 0:
            raise ValueError("multiplier must be > 0")
        self.period = int(period)
        self.multiplier = float(multiplier)
        self.use_close = bool(use_close)
        self.tv_ratchet = bool(tv_ratchet)
        self._prev_bar_close: Optional[float] = None

        self._highs: deque[float] = deque(maxlen=self.period)
        self._lows: deque[float] = deque(maxlen=self.period)
        self._closes: deque[float] = deque(maxlen=self.period)
        self._tr_seed: list[float] = []
        self._prev_close: Optional[float] = None
        self.state = ChandelierState()

    # ------------------------------------------------------------------ helpers
    def _true_range(self, high: float, low: float) -> float:
        if self._prev_close is None:
            return high - low
        return max(high - low,
                   abs(high - self._prev_close),
                   abs(low - self._prev_close))

    def _update_atr(self, tr: float) -> Optional[float]:
        """Wilder smoothing, seeded with a simple mean of the first `period` TRs."""
        if self.state.atr is None:
            self._tr_seed.append(tr)
            if len(self._tr_seed) < self.period:
                return None
            return sum(self._tr_seed) / self.period
        return (self.state.atr * (self.period - 1) + tr) / self.period

    # ------------------------------------------------------------------ fold
    def update(self, bar) -> dict:
        """Fold one CLOSED bar. Returns the new state as a dict."""
        high, low, close = float(bar.high), float(bar.low), float(bar.close)

        tr = self._true_range(high, low)
        atr = self._update_atr(tr)
        prev_bar_close = self._prev_bar_close      # close[1]
        self._highs.append(high)
        self._lows.append(low)
        self._closes.append(close)
        self._prev_close = close
        self._prev_bar_close = close

        prev_long = self.state.long_stop
        prev_short = self.state.short_stop
        prev_dir = self.state.direction

        if atr is None or len(self._highs) < self.period:
            self.state = ChandelierState(epoch=int(bar.epoch), atr=atr,
                                         direction=prev_dir, ready=False)
            return self.state.to_dict()

        hi = max(self._closes) if self.use_close else max(self._highs)
        lo = min(self._closes) if self.use_close else min(self._lows)
        raw_long = hi - self.multiplier * atr
        raw_short = lo + self.multiplier * atr

        # --- direction, decided against the PREVIOUS bar's stops ---------------
        # Pine writes this as nz(longStop[1], longStop): on the FIRST computable
        # bar the "previous" stop falls back to this bar's raw stop, so a
        # direction is chosen immediately instead of keeping the +1 seed. The
        # textbook form has no such rule and simply holds the seed.
        if self.tv_ratchet:
            lsp_dir = prev_long if prev_long is not None else raw_long
            ssp_dir = prev_short if prev_short is not None else raw_short
        else:
            lsp_dir, ssp_dir = prev_long, prev_short

        if ssp_dir is not None and close > ssp_dir:
            direction = 1
        elif lsp_dir is not None and close < lsp_dir:
            direction = -1
        else:
            direction = prev_dir

        if self.tv_ratchet:
            # Both sides ratchet every bar, gated on the PREVIOUS close against
            # the previous stop. Neither side is ever reset.
            long_stop = (max(raw_long, lsp_dir)
                         if prev_bar_close is not None and prev_bar_close > lsp_dir
                         else raw_long)
            short_stop = (min(raw_short, ssp_dir)
                          if prev_bar_close is not None and prev_bar_close < ssp_dir
                          else raw_short)
        else:
            # Textbook: ratchet only the ACTIVE side; the inactive side resets so
            # a flip restarts from a fresh value instead of inheriting a stale one.
            if direction > 0:
                long_stop = raw_long if prev_long is None or prev_dir < 0 \
                    else max(raw_long, prev_long)
                short_stop = raw_short
            else:
                short_stop = raw_short if prev_short is None or prev_dir > 0 \
                    else min(raw_short, prev_short)
                long_stop = raw_long

        flipped = self.state.ready and direction != prev_dir
        signal = None
        if flipped:
            signal = "BUY" if direction > 0 else "SELL"

        self.state = ChandelierState(
            epoch=int(bar.epoch), atr=atr, long_stop=long_stop, short_stop=short_stop,
            direction=direction, flipped=flipped, signal=signal, ready=True)
        return self.state.to_dict()

    def snapshot(self) -> dict:
        return self.state.to_dict()


SPEC = IndicatorSpec(
    id="chandelier",
    label="Chandelier Exit",
    params=[
        ParamSpec("period", "Period", "int", 22, 1, 200, 1),
        ParamSpec("multiplier", "Multiplier", "float", 3.0, 0.1, 10.0, 0.1),
        ParamSpec("use_close", "Use close for extremes (TradingView default)",
                  "int", 1, 0, 1, 1),
    ],
    series=[SeriesSpec("active_stop", "Chandelier Stop", "overlay", "line")],
    emits_signals=True,
)
register(SPEC, ChandelierEngine)
