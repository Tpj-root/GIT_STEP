"""Parity with TradingView's Chandelier Exit (the "everget" script).

The reference below is an independent transcription of the published Pine, not
a refactor of our engine -- so agreement is evidence, not tautology.

    longStop  = (useClose ? highest(close, n) : highest(n)) - mult*atr(n)
    longStop := close[1] > nz(longStop[1], longStop) ? max(longStop, longStop[1]) : longStop
    shortStop = (useClose ? lowest(close, n)  : lowest(n))  + mult*atr(n)
    shortStop := close[1] < nz(shortStop[1], shortStop) ? min(shortStop, shortStop[1]) : shortStop
    dir := close > nz(shortStop[1]) ? 1 : close < nz(longStop[1]) ? -1 : dir[1]
"""
import math, random, sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.feed import Candle
from app.indicators.chandelier import ChandelierEngine


def pine_atr(bars, n):
    """Pine's atr() is RMA (Wilder), seeded with the mean of the first n TRs."""
    out, atr, seed, prev_close = [], None, [], None
    for b in bars:
        tr = (b.high - b.low) if prev_close is None else max(
            b.high - b.low, abs(b.high - prev_close), abs(b.low - prev_close))
        prev_close = b.close
        if atr is None:
            seed.append(tr)
            atr = sum(seed) / n if len(seed) == n else None
        else:
            atr = (atr * (n - 1) + tr) / n
        out.append(atr)
    return out


def reference(bars, n=22, mult=3.0, use_close=True):
    atrs = pine_atr(bars, n)
    long_prev = short_prev = None
    direction = 1
    out = []
    for i, b in enumerate(bars):
        atr = atrs[i]
        if atr is None or i < n - 1:
            out.append(None); continue
        win = bars[i - n + 1:i + 1]
        hi = max(c.close for c in win) if use_close else max(c.high for c in win)
        lo = min(c.close for c in win) if use_close else min(c.low for c in win)

        long_stop = hi - mult * atr
        lsp = long_prev if long_prev is not None else long_stop
        if i > 0 and bars[i - 1].close > lsp:
            long_stop = max(long_stop, lsp)

        short_stop = lo + mult * atr
        ssp = short_prev if short_prev is not None else short_stop
        if i > 0 and bars[i - 1].close < ssp:
            short_stop = min(short_stop, ssp)

        if b.close > ssp:
            direction = 1
        elif b.close < lsp:
            direction = -1

        out.append({"direction": direction,
                    "stop": long_stop if direction > 0 else short_stop})
        long_prev, short_prev = long_stop, short_stop
    return out


def synth(seed, n=400):
    rng = random.Random(seed)
    price, bars = 1000.0, []
    for i in range(n):
        price *= 1 + rng.gauss(0, 0.004)
        hi = price * (1 + abs(rng.gauss(0, 0.003)))
        lo = price * (1 - abs(rng.gauss(0, 0.003)))
        bars.append(Candle(i * 3600, price, hi, lo, price))
    return bars


@pytest.mark.parametrize("seed", range(12))
def test_defaults_match_tradingview(seed):
    """Default construction must reproduce TradingView bar for bar."""
    bars = synth(seed)
    ref = reference(bars, 22, 3.0, use_close=True)
    eng = ChandelierEngine(period=22, multiplier=3.0)   # defaults
    mism_dir = mism_stop = 0
    for b, r in zip(bars, ref):
        st = eng.update(b)
        if r is None or not st["ready"]:
            continue
        if st["direction"] != r["direction"]:
            mism_dir += 1
        elif not math.isclose(st["active_stop"], r["stop"], rel_tol=1e-9, abs_tol=1e-7):
            mism_stop += 1
    assert mism_dir == 0, f"seed {seed}: {mism_dir} direction mismatches vs TradingView"
    assert mism_stop == 0, f"seed {seed}: {mism_stop} stop-value mismatches vs TradingView"


@pytest.mark.parametrize("seed", range(6))
def test_use_close_false_matches_the_high_low_reference(seed):
    bars = synth(seed)
    ref = reference(bars, 22, 3.0, use_close=False)
    eng = ChandelierEngine(period=22, multiplier=3.0, use_close=False, tv_ratchet=True)
    for b, r in zip(bars, ref):
        st = eng.update(b)
        if r is None or not st["ready"]:
            continue
        assert st["direction"] == r["direction"]
        assert math.isclose(st["active_stop"], r["stop"], rel_tol=1e-9, abs_tol=1e-7)


def test_the_two_variants_actually_differ():
    """Guard against the parity tests passing because the flag does nothing."""
    bars = synth(3)
    tv = ChandelierEngine(period=22, multiplier=3.0)
    txt = ChandelierEngine(period=22, multiplier=3.0, use_close=False, tv_ratchet=False)
    tv_flips = txt_flips = 0
    for b in bars:
        a, c = tv.update(b), txt.update(b)
        tv_flips += bool(a["flipped"]); txt_flips += bool(c["flipped"])
    assert tv_flips != txt_flips, \
        "TradingView and textbook variants produced identical flips -- the flag is inert"


def test_textbook_variant_still_available():
    e = ChandelierEngine(period=22, multiplier=3.0, use_close=False, tv_ratchet=False)
    assert e.use_close is False and e.tv_ratchet is False
