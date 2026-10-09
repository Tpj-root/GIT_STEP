"""Display indicators. They don't trade, but a wrong RSI is still a wrong
decision aid, so the invariants are pinned."""
import math, sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.feed import Candle
from app.indicators import compute_overlay, overlay_specs


def bars(n=300, fn=lambda i: 100 + math.sin(i / 9) * 5):
    out = []
    for i in range(n):
        p = fn(i)
        out.append(Candle(i * 60, p, p + 1, p - 1, p))
    return out


def test_all_overlays_registered():
    assert {s["id"] for s in overlay_specs()} == {"ema", "bollinger", "rsi", "macd"}


def test_rsi_stays_in_bounds():
    for v in compute_overlay("rsi", bars(), period=14)["rsi"]:
        assert 0.0 <= v["value"] <= 100.0


def test_rsi_pegs_high_on_a_pure_uptrend():
    up = compute_overlay("rsi", bars(100, lambda i: 100 + i), period=14)["rsi"]
    assert up[-1]["value"] == pytest.approx(100.0), "no down moves must give RSI 100"


def test_rsi_pegs_low_on_a_pure_downtrend():
    dn = compute_overlay("rsi", bars(100, lambda i: 200 - i), period=14)["rsi"]
    assert dn[-1]["value"] == pytest.approx(0.0, abs=1e-9)


def test_bollinger_band_ordering():
    r = compute_overlay("bollinger", bars(), period=20, stddev=2.0)
    for u, m, l in zip(r["bb_upper"], r["bb_mid"], r["bb_lower"]):
        assert u["epoch"] == m["epoch"] == l["epoch"]
        assert u["value"] >= m["value"] >= l["value"]


def test_bollinger_collapses_on_a_flat_series():
    r = compute_overlay("bollinger", bars(60, lambda i: 100.0), period=20, stddev=2.0)
    u, m, l = r["bb_upper"][-1]["value"], r["bb_mid"][-1]["value"], r["bb_lower"][-1]["value"]
    assert u == pytest.approx(m) == pytest.approx(l) == pytest.approx(100.0)


def test_ema_tracks_a_constant_series():
    r = compute_overlay("ema", bars(120, lambda i: 42.0), period=50)["ema"]
    assert r[-1]["value"] == pytest.approx(42.0)


def test_ema_lags_a_ramp_below_price():
    """On a rising series an EMA must sit below the latest close."""
    b = bars(200, lambda i: 100 + i)
    r = compute_overlay("ema", b, period=50)["ema"]
    assert r[-1]["value"] < b[-1].close


def test_macd_histogram_equals_line_minus_signal():
    r = compute_overlay("macd", bars(), fast=12, slow=26, signal=9)
    line = {p["epoch"]: p["value"] for p in r["macd"]}
    sig = {p["epoch"]: p["value"] for p in r["macd_signal"]}
    for h in r["macd_hist"]:
        # values are rounded to 8dp on the way out, so the tolerance has to be
        # looser than that rounding -- 1e-9 would fail on the rounding alone
        assert h["value"] == pytest.approx(line[h["epoch"]] - sig[h["epoch"]], abs=1e-7)


def test_macd_is_zero_on_a_flat_series():
    r = compute_overlay("macd", bars(200, lambda i: 50.0))
    assert r["macd"][-1]["value"] == pytest.approx(0.0, abs=1e-9)


def test_overlays_survive_short_series():
    """Fewer bars than the period must yield empty output, not a crash."""
    tiny = bars(3)
    for oid in ("ema", "bollinger", "rsi", "macd"):
        r = compute_overlay(oid, tiny)
        assert all(isinstance(v, list) for v in r.values())


def test_overlays_handle_empty_input():
    for oid in ("ema", "bollinger", "rsi", "macd"):
        r = compute_overlay(oid, [])
        assert all(v == [] for v in r.values())
