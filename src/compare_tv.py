"""Compare our Chandelier Exit against the most-used TradingView version.

The widely-installed TradingView script is Chandelier Exit by "everget".
It differs from the spec this app was built to in TWO material ways:

  1. useClose defaults to TRUE  -> extremes are highest(CLOSE)/lowest(CLOSE),
     not highest(HIGH)/lowest(LOW).
  2. The ratchet is gated on close[1] vs the previous stop, NOT on direction,
     and the inactive side is never reset.

Either difference alone moves flip points. This script measures how much.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.feed import Candle                                  # noqa: E402
from app.indicators.chandelier import ChandelierEngine       # noqa: E402


def wilder_atr(bars, n):
    out, atr, seed = [], None, []
    prev_close = None
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


def tradingview_variant(bars, n=22, mult=3.0, use_close=True):
    """everget's Chandelier Exit, transcribed from the published Pine."""
    atrs = wilder_atr(bars, n)
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

        prev_dir = direction
        if b.close > ssp:
            direction = 1
        elif b.close < lsp:
            direction = -1
        out.append({"epoch": b.epoch, "direction": direction,
                    "flip": direction != prev_dir,
                    "stop": long_stop if direction > 0 else short_stop})
        long_prev, short_prev = long_stop, short_stop
    return out


def ours(bars, n=22, mult=3.0):
    e = ChandelierEngine(period=n, multiplier=mult)
    out = []
    for b in bars:
        st = e.update(b)
        out.append({"epoch": b.epoch, "direction": st["direction"],
                    "flip": bool(st["flipped"]),
                    "stop": st["active_stop"]} if st["ready"] else None)
    return out


def compare(bars, label, n=22, mult=3.0):
    a = ours(bars, n, mult)
    variants = {
        "TV everget (useClose=TRUE, the default)": tradingview_variant(bars, n, mult, True),
        "TV everget (useClose=false, high/low)":   tradingview_variant(bars, n, mult, False),
    }
    a_flips = {x["epoch"] for x in a if x and x["flip"]}
    print(f"\n{'=' * 78}\n{label}   bars={len(bars)}  period={n} mult={mult}\n{'=' * 78}")
    print(f"  ours                                     flips={len(a_flips)}")
    for name, b in variants.items():
        b_flips = {x["epoch"] for x in b if x and x["flip"]}
        both = [(x, y) for x, y in zip(a, b) if x and y]
        agree = sum(1 for x, y in both if x["direction"] == y["direction"])
        shared = a_flips & b_flips
        print(f"  {name:<40} flips={len(b_flips)}")
        print(f"      direction agrees on {agree}/{len(both)} bars "
              f"({100 * agree / max(len(both), 1):.1f}%)")
        print(f"      flips at the SAME bar: {len(shared)}   "
              f"ours-only: {len(a_flips - b_flips)}   theirs-only: {len(b_flips - a_flips)}")


if __name__ == "__main__":
    import json, urllib.request  # noqa: F401
    import asyncio, websockets   # noqa: F401

    async def fetch(symbol, gran, count):
        import json as j
        url = "wss://ws.derivws.com/websockets/v3?app_id=1089"
        async with websockets.connect(url, open_timeout=30, max_size=16_000_000) as ws:
            await ws.send(j.dumps({"ticks_history": symbol, "end": "latest",
                                   "count": count, "style": "candles",
                                   "granularity": gran, "adjust_start_time": 1}))
            while True:
                r = j.loads(await ws.recv())
                if r.get("msg_type") == "candles":
                    return [Candle(int(c["epoch"]), float(c["open"]), float(c["high"]),
                                   float(c["low"]), float(c["close"]))
                            for c in r["candles"]]

    for sym, gran, lbl in (("frxXAUUSD", 3600, "XAUUSD 1h (Deriv feed)"),
                           ("stpRNG", 3600, "Step Index 1h (Deriv feed)")):
        bars = asyncio.run(fetch(sym, gran, 1000))
        compare(bars, lbl)
