"""Candle series with explicit closed-bar detection.

The single most important rule in this app: an indicator signal may only be
acted on once its bar has CLOSED. A forming bar repaints -- its high, low and
close all still move -- so a signal derived from it can appear, trigger an
order, and then vanish from the chart. That is the phantom-trade bug, and it is
prevented here rather than in the engine.

Deriv's `ohlc` messages always describe the currently-forming bar. A bar is
therefore known to be closed only when a bar with a LATER open_time appears.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable, Optional
from .feed import Candle


@dataclass
class Update:
    """Result of folding one incoming bar into the series."""
    bar: Candle                 # the bar as it now stands (forming)
    appended: bool              # True if this opened a new bar
    closed: Optional[Candle]    # the bar that just closed, if any


class CandleSeries:
    def __init__(self, granularity: int, max_len: int = 20_000) -> None:
        self.granularity = granularity
        self.max_len = max_len
        self.bars: list[Candle] = []
        self._index: dict[int, int] = {}

    # ------------------------------------------------------------------ loading
    def reset(self, candles: Iterable[Candle]) -> None:
        """Replace the whole series -- used on first load and after a reconnect."""
        self.bars = sorted({c.epoch: c for c in candles}.values(), key=lambda c: c.epoch)
        self._trim()
        self._reindex()

    def reconcile(self, candles: Iterable[Candle]) -> int:
        """Merge a freshly fetched history over the existing series after a
        reconnect. Returns how many bars were added or corrected. Never assume
        the stream resumed where it left off -- gaps and revisions both happen."""
        changed = 0
        for c in sorted(candles, key=lambda c: c.epoch):
            i = self._index.get(c.epoch)
            if i is None:
                self.bars.append(c)
                changed += 1
            elif (self.bars[i].open != c.open or self.bars[i].high != c.high
                  or self.bars[i].low != c.low or self.bars[i].close != c.close):
                self.bars[i] = c
                changed += 1
        if changed:
            self.bars.sort(key=lambda c: c.epoch)
            self._trim()
            self._reindex()
        return changed

    # ------------------------------------------------------------------ streaming
    def upsert(self, bar: Candle) -> Update:
        """Fold one incoming (forming) bar into the series."""
        if not self.bars:
            self.bars.append(bar)
            self._index[bar.epoch] = 0
            return Update(bar=bar, appended=True, closed=None)

        last = self.bars[-1]
        if bar.epoch == last.epoch:
            self.bars[-1] = bar                     # same bar, updated values
            return Update(bar=bar, appended=False, closed=None)

        if bar.epoch < last.epoch:
            i = self._index.get(bar.epoch)          # late correction to an old bar
            if i is not None:
                self.bars[i] = bar
            return Update(bar=bar, appended=False, closed=None)

        # bar.epoch > last.epoch -> `last` is now final
        self.bars.append(bar)
        self._index[bar.epoch] = len(self.bars) - 1
        self._trim()
        return Update(bar=bar, appended=True, closed=last)

    # ------------------------------------------------------------------ helpers
    @property
    def closed_bars(self) -> list[Candle]:
        """Every bar except the one still forming."""
        return self.bars[:-1] if self.bars else []

    @property
    def last(self) -> Optional[Candle]:
        return self.bars[-1] if self.bars else None

    def _trim(self) -> None:
        if len(self.bars) > self.max_len:
            self.bars = self.bars[-self.max_len:]

    def _reindex(self) -> None:
        self._index = {c.epoch: i for i, c in enumerate(self.bars)}

    def __len__(self) -> int:
        return len(self.bars)
