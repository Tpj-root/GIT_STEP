"""Display-only indicators.

These render; they do not trade. Chandelier stays the single signal source --
the execution path has one authority on purpose, and adding more would make
"which indicator fired this order?" ambiguous in the audit log.

Each computes from a full bar list and returns {series_key: [{epoch, value}]}.
"""
from __future__ import annotations
from .base import IndicatorSpec, ParamSpec, SeriesSpec, register_overlay


def _ema(vals: list[float], n: int) -> list[float | None]:
    if n <= 0 or not vals:
        return [None] * len(vals)
    k = 2.0 / (n + 1.0)
    out: list[float | None] = []
    run = None
    for i, v in enumerate(vals):
        if i < n - 1:
            out.append(None); continue
        if run is None:
            run = sum(vals[i - n + 1:i + 1]) / n
        else:
            run = v * k + run * (1 - k)
        out.append(run)
    return out


def _sma(vals: list[float], n: int) -> list[float | None]:
    out: list[float | None] = []
    acc = 0.0
    for i, v in enumerate(vals):
        acc += v
        if i >= n:
            acc -= vals[i - n]
        out.append(acc / n if i >= n - 1 else None)
    return out


def _pts(bars, vals):
    return [{"epoch": b.epoch, "value": round(v, 8)}
            for b, v in zip(bars, vals) if v is not None]


# ------------------------------------------------------------------ EMA
def ema_compute(bars, period: int = 50, **_):
    closes = [b.close for b in bars]
    return {"ema": _pts(bars, _ema(closes, int(period)))}


EMA_SPEC = IndicatorSpec(
    id="ema", label="EMA",
    params=[ParamSpec("period", "Period", "int", 50, 2, 400, 1)],
    series=[SeriesSpec("ema", "EMA", "overlay", "line")],
)


# ------------------------------------------------------------------ Bollinger
def bollinger_compute(bars, period: int = 20, stddev: float = 2.0, **_):
    closes = [b.close for b in bars]
    n, k = int(period), float(stddev)
    mid = _sma(closes, n)
    up: list[float | None] = []
    lo: list[float | None] = []
    for i, m in enumerate(mid):
        if m is None:
            up.append(None); lo.append(None); continue
        win = closes[i - n + 1:i + 1]
        var = sum((x - m) ** 2 for x in win) / n
        sd = var ** 0.5
        up.append(m + k * sd); lo.append(m - k * sd)
    return {"bb_upper": _pts(bars, up), "bb_mid": _pts(bars, mid), "bb_lower": _pts(bars, lo)}


BOLL_SPEC = IndicatorSpec(
    id="bollinger", label="Bollinger Bands",
    params=[ParamSpec("period", "Period", "int", 20, 2, 200, 1),
            ParamSpec("stddev", "Std dev", "float", 2.0, 0.1, 5.0, 0.1)],
    series=[SeriesSpec("bb_upper", "Upper", "overlay", "line"),
            SeriesSpec("bb_mid", "Basis", "overlay", "line"),
            SeriesSpec("bb_lower", "Lower", "overlay", "line")],
)


# ------------------------------------------------------------------ RSI
def rsi_compute(bars, period: int = 14, **_):
    n = int(period)
    closes = [b.close for b in bars]
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= n:
        return {"rsi": []}
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0.0); losses += max(-d, 0.0)
    ag, al = gains / n, losses / n
    out[n] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(d, 0.0)) / n
        al = (al * (n - 1) + max(-d, 0.0)) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return {"rsi": _pts(bars, out)}


RSI_SPEC = IndicatorSpec(
    id="rsi", label="RSI",
    params=[ParamSpec("period", "Period", "int", 14, 2, 100, 1)],
    series=[SeriesSpec("rsi", "RSI", "separate", "line")],
)


# ------------------------------------------------------------------ MACD
def macd_compute(bars, fast: int = 12, slow: int = 26, signal: int = 9, **_):
    closes = [b.close for b in bars]
    f, s, g = int(fast), int(slow), int(signal)
    ef, es = _ema(closes, f), _ema(closes, s)
    line = [(a - b) if (a is not None and b is not None) else None for a, b in zip(ef, es)]
    dense = [v for v in line if v is not None]
    off = len(line) - len(dense)
    sig_dense = _ema(dense, g)
    sig: list[float | None] = [None] * off + sig_dense
    hist = [(a - b) if (a is not None and b is not None) else None for a, b in zip(line, sig)]
    return {"macd": _pts(bars, line), "macd_signal": _pts(bars, sig),
            "macd_hist": _pts(bars, hist)}


MACD_SPEC = IndicatorSpec(
    id="macd", label="MACD",
    params=[ParamSpec("fast", "Fast", "int", 12, 2, 100, 1),
            ParamSpec("slow", "Slow", "int", 26, 3, 200, 1),
            ParamSpec("signal", "Signal", "int", 9, 2, 100, 1)],
    series=[SeriesSpec("macd_hist", "Histogram", "separate", "histogram"),
            SeriesSpec("macd", "MACD", "separate", "line"),
            SeriesSpec("macd_signal", "Signal", "separate", "line")],
)

for spec, fn in ((EMA_SPEC, ema_compute), (BOLL_SPEC, bollinger_compute),
                 (RSI_SPEC, rsi_compute), (MACD_SPEC, macd_compute)):
    register_overlay(spec, fn)
