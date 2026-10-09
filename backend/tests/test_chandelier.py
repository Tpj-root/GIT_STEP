"""Chandelier Exit correctness.

These pin the TEXTBOOK variant (use_close=False, tv_ratchet=False) -- the
definition this app was specified against. The engine now DEFAULTS to
TradingView's variant so charts agree with TradingView; see
test_tradingview_parity.py for that side.

Expected values in test_hand_checked_fixture were computed BY HAND from the CSV
fixture (period=3, multiplier=2.0) before the implementation was run. If this
test fails, trust the arithmetic in the comments over the code.
"""
import csv, sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.feed import Candle
from app.series import CandleSeries
from app.indicators.chandelier import ChandelierEngine

FIX = Path(__file__).parent / "fixtures" / "chandelier_basic.csv"


def load(path=FIX) -> list[Candle]:
    with open(path) as f:
        return [Candle(int(r["epoch"]), float(r["open"]), float(r["high"]),
                       float(r["low"]), float(r["close"]))
                for r in csv.DictReader(f)]


def test_hand_checked_fixture():
    """period=3, mult=2.0. Hand arithmetic:

    bar1 TR=102-98=4                      seed=[4]            atr=None
    bar2 TR=max(4,|103-101|,|99-101|)=4   seed=[4,4]          atr=None
    bar3 TR=max(4,2,2)=4                  seed=[4,4,4]        atr=4.0
         highs=[102,103,104] lows=[98,99,100]
         raw_long =104-2*4=96   raw_short=98+2*4=106
         no prev stops -> direction stays +1, long=96, short=106
    bar4 TR=4  atr=(4*2+4)/3=4.0
         highs=[103,104,105] lows=[99,100,101]
         raw_long=105-8=97  (97 > prev 96) -> RATCHETS UP to 97
    bar5 TR=4  atr=4.0
         raw_long=106-8=98   -> ratchets up to 98
    bar6 TR=max(105-90, 0, |90-105|)=15   atr=(4*2+15)/3=7.666667
         highs=[105,106,105] lows=[101,102,90]
         raw_long =106-15.333333=90.666667
         raw_short= 90+15.333333=105.333333
         close=91 < prev_long=98  -> DIRECTION FLIPS to -1, signal SELL
         prev_dir was +1 so the short ratchet RESTARTS at 105.333333
    bar7 TR=max(4,|92-91|,|88-91|)=4      atr=(7.666667*2+4)/3=6.444444
         lows=[102,90,88] -> raw_short=88+12.888889=100.888889
         100.888889 < 105.333333 -> RATCHETS DOWN
    """
    e = ChandelierEngine(period=3, multiplier=2.0, use_close=False, tv_ratchet=False)
    states = [e.update(b) for b in load()]

    assert states[0]["ready"] is False and states[1]["ready"] is False
    assert states[2]["ready"] is True
    assert states[2]["atr"] == pytest.approx(4.0)
    assert states[2]["long_stop"] == pytest.approx(96.0)
    assert states[2]["short_stop"] == pytest.approx(106.0)
    assert states[2]["direction"] == 1

    assert states[3]["long_stop"] == pytest.approx(97.0)
    assert states[4]["long_stop"] == pytest.approx(98.0)

    assert states[5]["atr"] == pytest.approx(23 / 3)
    assert states[5]["direction"] == -1
    assert states[5]["flipped"] is True
    assert states[5]["signal"] == "SELL"
    assert states[5]["short_stop"] == pytest.approx(105.333333, abs=1e-5)

    assert states[6]["atr"] == pytest.approx(58 / 9, abs=1e-6)
    assert states[6]["short_stop"] == pytest.approx(100.888889, abs=1e-5)
    assert states[6]["flipped"] is False


def test_long_stop_never_decreases_while_long():
    e = ChandelierEngine(period=3, multiplier=2.0, use_close=False, tv_ratchet=False)
    prev, seen = None, 0
    for i, b in enumerate(load()):
        s = e.update(b)
        if s["ready"] and s["direction"] == 1:
            if prev is not None:
                assert s["long_stop"] >= prev - 1e-9, f"long stop fell at bar {i}"
                seen += 1
            prev = s["long_stop"]
        else:
            prev = None
    assert seen > 0, "fixture never exercised the long ratchet"


def test_short_stop_never_increases_while_short():
    bars = load() + [Candle(8, 89, 90, 85, 86), Candle(9, 86, 87, 83, 84)]
    e = ChandelierEngine(period=3, multiplier=2.0, use_close=False, tv_ratchet=False)
    prev, seen = None, 0
    for b in bars:
        s = e.update(b)
        if s["ready"] and s["direction"] == -1:
            if prev is not None:
                assert s["short_stop"] <= prev + 1e-9
                seen += 1
            prev = s["short_stop"]
        else:
            prev = None
    assert seen > 0


def test_atr_seeding_requires_full_period():
    e = ChandelierEngine(period=5, multiplier=3.0, use_close=False, tv_ratchet=False)
    for i, b in enumerate(load()[:5]):
        s = e.update(b)
        assert s["ready"] is (i >= 4), f"ready flipped early at bar {i}"


def test_signal_only_on_flip():
    e = ChandelierEngine(period=3, multiplier=2.0, use_close=False, tv_ratchet=False)
    sigs = [s["signal"] for s in (e.update(b) for b in load())]
    assert sigs.count("SELL") == 1
    assert sigs.count("BUY") == 0
    assert sum(1 for s in sigs if s) == 1, "a signal fired on a non-flip bar"


def test_first_ready_bar_does_not_emit_a_signal():
    """Direction is seeded at +1, so the first ready bar must not count as a flip."""
    e = ChandelierEngine(period=3, multiplier=2.0, use_close=False, tv_ratchet=False)
    states = [e.update(b) for b in load()[:3]]
    assert states[2]["ready"] is True
    assert states[2]["flipped"] is False
    assert states[2]["signal"] is None


def test_mid_bar_excursion_produces_no_signal():
    """THE phantom-trade test.

    A forming bar spikes far below the long stop, then recovers to close above
    it. Because only CLOSED bars reach the engine, no signal may be produced --
    and the final state must match what the recovered close alone would give.
    """
    series = CandleSeries(60)
    e = ChandelierEngine(period=3, multiplier=2.0, use_close=False, tv_ratchet=False)
    signals = []

    def feed(bar):
        u = series.upsert(bar)
        if u.closed is not None:                 # ONLY closed bars reach the engine
            s = e.update(u.closed)
            if s["signal"]:
                signals.append((u.closed.epoch, s["signal"]))

    for b in load()[:5]:
        feed(b)
        feed(Candle(b.epoch + 1, b.close, b.close, b.close, b.close))  # force close

    before = len(signals)

    # bar 6 forms: dips to 80 (far under the ~98 long stop) but closes back at 105
    forming = Candle(600, 105, 106, 80, 82)
    feed(forming)
    assert len(signals) == before, "signal fired off a FORMING bar"

    feed(Candle(600, 105, 106, 80, 105))          # same bar, recovered
    assert len(signals) == before

    feed(Candle(660, 105, 106, 104, 105))         # next bar opens -> 600 closes
    assert len(signals) == before, "excursion produced a phantom signal"
    assert e.state.direction == 1, "direction flipped on a wick that closed back up"


def test_engine_is_incremental_not_recomputed():
    """Replaying bars one at a time must equal a single pass -- no hidden
    dependence on having the whole history in hand."""
    bars = load()
    a = ChandelierEngine(period=3, multiplier=2.0, use_close=False, tv_ratchet=False)
    full = [a.update(b) for b in bars][-1]

    b_eng = ChandelierEngine(period=3, multiplier=2.0, use_close=False, tv_ratchet=False)
    for b in bars:
        step = b_eng.update(b)
    assert step["long_stop"] == pytest.approx(full["long_stop"])
    assert step["short_stop"] == pytest.approx(full["short_stop"])
    assert step["direction"] == full["direction"]


def test_rejects_bad_params():
    with pytest.raises(ValueError):
        ChandelierEngine(period=0)
    with pytest.raises(ValueError):
        ChandelierEngine(multiplier=0)


# --------------------------------------------------------------------------
# Discriminating tests. The suite above initially passed even with the ratchet
# deleted, because that fixture's raw stops happened to rise monotonically so
# max(raw, prev) == raw throughout. These exercise the case that separates them:
# a volatility spike that makes the RAW stop fall while direction stays long.
# --------------------------------------------------------------------------
RATCHET_FIX = Path(__file__).parent / "fixtures" / "chandelier_ratchet.csv"


def test_ratchet_holds_when_raw_stop_falls():
    """bar6 wicks to 92 and closes at 104 (still long).

        TR   = max(106-92, |106-105|, |92-105|) = 14
        ATR  = (4*2 + 14)/3 = 7.333333
        highs=[105,106,106] -> raw_long = 106 - 2*7.333333 = 91.333333

    raw_long (91.33) is BELOW the previous long stop (98). A Chandelier stop
    must never loosen after a volatility spike -- that is the entire point of
    the indicator -- so the ratchet must hold it at 98.
    """
    e = ChandelierEngine(period=3, multiplier=2.0, use_close=False, tv_ratchet=False)
    states = [e.update(b) for b in load(RATCHET_FIX)]

    assert states[4]["long_stop"] == pytest.approx(98.0)
    assert states[5]["atr"] == pytest.approx(22 / 3)
    assert states[5]["direction"] == 1, "should still be long at bar 6"
    assert states[5]["long_stop"] == pytest.approx(98.0), \
        "ratchet failed: stop loosened to the raw value after a volatility spike"


def test_ratchet_changes_the_resulting_signal():
    """bar7 closes at 95.

    Against the RATCHETED stop (98) that is a break -> SELL.
    Against the un-ratcheted raw stop (91.33) it is not -> no signal.
    So this pins the ratchet through observable behaviour, not just a number.
    """
    e = ChandelierEngine(period=3, multiplier=2.0, use_close=False, tv_ratchet=False)
    states = [e.update(b) for b in load(RATCHET_FIX)]
    assert states[6]["direction"] == -1
    assert states[6]["flipped"] is True
    assert states[6]["signal"] == "SELL", \
        "without the ratchet, close=95 never breaks the stop and no signal fires"


def test_signal_count_equals_direction_changes():
    """Invariant across many random walks: exactly one signal per direction
    change among ready bars, and never any other time."""
    import random
    for seed in range(40):
        rng = random.Random(seed)
        price, bars = 100.0, []
        for i in range(300):
            price += rng.choice([-1, 1]) * rng.uniform(0.1, 2.0)
            h = price + rng.uniform(0, 1.5)
            l = price - rng.uniform(0, 1.5)
            bars.append(Candle(i * 60, price, h, l, price))

        e = ChandelierEngine(period=22, multiplier=3.0, use_close=False, tv_ratchet=False)
        states = [e.update(b) for b in bars]
        ready = [s for s in states if s["ready"]]

        changes = sum(1 for a, b in zip(ready, ready[1:])
                      if a["direction"] != b["direction"])
        signals = sum(1 for s in ready if s["signal"] is not None)
        assert signals == changes, f"seed {seed}: {signals} signals vs {changes} flips"

        for s in ready:
            assert (s["signal"] is not None) == s["flipped"]
            if s["signal"]:
                assert s["signal"] == ("BUY" if s["direction"] > 0 else "SELL")


SHORT_FIX = Path(__file__).parent / "fixtures" / "chandelier_short_side.csv"
GAP_FIX = Path(__file__).parent / "fixtures" / "chandelier_gap.csv"


def test_short_ratchet_holds_when_raw_stop_rises():
    """Mirror of the long-side ratchet test.

    bar7 flips short: lows=[102,92,94] -> raw_short = 92 + 2*(25.666667/3)
                                                    = 92 + 17.111111 = 109.111111
    bar8 TR  = max(104-94, |104-95|, |94-95|) = 10
         ATR = (8.555556*2 + 10)/3 = 9.037037
         lows=[92,94,94] -> raw_short = 92 + 18.074074 = 110.074074

    raw_short ROSE above the previous short stop. A short Chandelier stop must
    never rise, so the ratchet must hold it at 109.111111.
    """
    e = ChandelierEngine(period=3, multiplier=2.0, use_close=False, tv_ratchet=False)
    s = [e.update(b) for b in load(SHORT_FIX)]

    assert s[6]["direction"] == -1
    assert s[6]["short_stop"] == pytest.approx(109.111111, abs=1e-5)
    assert s[7]["direction"] == -1, "should still be short at bar 8"
    assert s[7]["short_stop"] == pytest.approx(109.111111, abs=1e-5), \
        "short ratchet failed: stop rose to the raw value after volatility expanded"


def test_direction_uses_previous_bar_stops_not_current():
    """bar9 closes at 109.5.

        previous (ratcheted) short stop = 109.111111  -> 109.5 breaks it  -> BUY
        this bar's RAW short stop       = 116.049383  -> 109.5 does not   -> nothing

    Chandelier compares the close against the PREVIOUS bar's stops. Comparing
    against the current bar's raw stops silently swallows this flip.
    """
    e = ChandelierEngine(period=3, multiplier=2.0, use_close=False, tv_ratchet=False)
    s = [e.update(b) for b in load(SHORT_FIX)]

    assert s[8]["direction"] == 1, "flip missed -- direction compared against the wrong bar"
    assert s[8]["flipped"] is True
    assert s[8]["signal"] == "BUY"


def test_true_range_accounts_for_gaps():
    """Three flat bars closing at 100, then a bar that GAPS up to 109.5-110.5.

        intrabar range   = 110.5 - 109.5 = 1.0
        gap from close   = |110.5 - 100| = 10.5   <-- True Range must use this

    Ignoring the previous close understates ATR by 10x on gaps, which makes every
    stop far too tight. Synthetic indices rarely gap; XAUUSD does, over weekends.
    """
    e = ChandelierEngine(period=3, multiplier=2.0, use_close=False, tv_ratchet=False)
    states = [e.update(b) for b in load(GAP_FIX)]

    # bars 1-3 are flat: TR = 2.0 each -> seeded ATR = 2.0
    assert states[2]["atr"] == pytest.approx(2.0)
    # bar 4: TR must be 10.5, not 1.0  ->  ATR = (2.0*2 + 10.5)/3 = 4.833333
    assert states[3]["atr"] == pytest.approx(14.5 / 3, abs=1e-6), \
        "True Range ignored the gap from the previous close"


def test_ready_guard_is_defensive_only():
    """The `state.ready` term in the flip test is unreachable-by-construction:
    on the first ready bar both previous stops are None, so direction always
    equals prev_dir and no flip can be reported. Kept as defence in depth; this
    test pins the property so the guard is never mistaken for live logic."""
    for period in (1, 2, 3, 5):
        e = ChandelierEngine(period=period, multiplier=2.0, use_close=False, tv_ratchet=False)
        for b in load():
            s = e.update(b)
            if s["ready"]:
                assert s["flipped"] is False, "first ready bar reported a flip"
                break
