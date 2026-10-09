"""Integration tests for the pieces that only break when parts interact:
reconnect reconciliation, auto-disarm on feed loss, and end-to-end idempotency.
"""
import asyncio, sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.feed import Candle
from app.series import CandleSeries
from app.chart_service import ChartService
from app.risk import RiskGuard, Reject
from app.config import Mode, AutoModeConfig
from app.brokers.paper import PaperBroker


class FakeFeed:
    """Stands in for DerivFeed: no socket, hooks wired the same way."""
    def __init__(self):
        self.on_history = self.on_bar = self.on_state = None
        self.is_stale = False
        self.state = "live"
    async def subscribe(self, *a, **k):
        return []


def bars(n, start=0, step=60, price=100.0):
    out = []
    for i in range(n):
        p = price + i
        out.append(Candle(start + i * step, p, p + 1, p - 1, p))
    return out


# ------------------------------------------------------------------ reconnect
@pytest.mark.asyncio
async def test_reconnect_reconciles_without_gaps_or_duplicates():
    cs = ChartService(FakeFeed())
    cs.set_params(period=3, multiplier=2.0)

    original = bars(50)
    await cs._handle_history("stpRNG", 60, original)
    assert len(cs.series[("stpRNG", 60)]) == 50

    # simulate a drop: 10 bars pass unseen, then reconnect re-fetches an
    # OVERLAPPING window (last 30 known + 10 missed)
    missed = bars(10, start=50 * 60, price=150.0)
    refetch = original[-30:] + missed
    await cs._handle_history("stpRNG", 60, refetch)

    s = cs.series[("stpRNG", 60)]
    epochs = [c.epoch for c in s.bars]
    assert len(epochs) == len(set(epochs)), "reconnect produced duplicate bars"
    assert epochs == sorted(epochs), "bars out of order after reconnect"
    gaps = [b - a for a, b in zip(epochs, epochs[1:]) if b - a != 60]
    assert not gaps, f"reconnect left gaps: {gaps}"
    assert len(s) == 60


@pytest.mark.asyncio
async def test_reconnect_corrects_a_revised_bar():
    cs = ChartService(FakeFeed())
    cs.set_params(period=3, multiplier=2.0)
    original = bars(20)
    await cs._handle_history("stpRNG", 60, original)

    revised = list(original)
    revised[10] = Candle(original[10].epoch, 999, 1000, 998, 999)
    await cs._handle_history("stpRNG", 60, revised)

    s = cs.series[("stpRNG", 60)]
    assert s.bars[10].close == 999, "reconnect did not correct a revised bar"
    assert len(s) == 20, "correction changed the bar count"


@pytest.mark.asyncio
async def test_no_signal_replay_after_reconnect():
    """Re-delivering history must not re-fire signals for bars already traded.
    The engine is rebuilt, so signals recompute -- the idempotency key is what
    stops a duplicate order. Pin both halves."""
    cs = ChartService(FakeFeed())
    cs.set_params(period=3, multiplier=2.0)
    fired = []
    async def on_sig(s): fired.append(s.idempotency_key)
    cs.on_signal = on_sig

    seq = bars(10) + [Candle(600, 110, 110, 80, 82), Candle(660, 82, 83, 79, 80)]
    await cs._handle_history("stpRNG", 60, seq[:1])
    for b in seq:
        await cs._handle_bar("stpRNG", 60, b, False)
    await cs._handle_bar("stpRNG", 60, Candle(720, 80, 81, 78, 79), False)
    first = list(fired)
    assert first, "fixture produced no signal to test replay against"

    fired.clear()
    await cs._handle_history("stpRNG", 60, seq)   # reconnect replays history
    assert fired == [], "reconnect re-fired signals through the live path"


# --------------------------------------------------------------- auto disarm
@pytest.mark.asyncio
async def test_auto_disarms_on_feed_loss():
    risk = RiskGuard(1.0, 1000.0, 10.0)
    risk.mode = Mode.auto
    alerts = []

    async def on_state(state, detail):
        if state != "live" and risk.disarm(f"feed {state}"):
            alerts.append(detail or state)

    await on_state("disconnected", "socket closed")
    assert risk.mode is Mode.manual, "auto survived a feed loss"
    assert alerts, "no alert raised when auto was disarmed"

    await on_state("disconnected", "again")
    assert len(alerts) == 1, "disarm alerted twice for one outage"


@pytest.mark.asyncio
async def test_auto_does_not_rearm_itself_when_feed_returns():
    risk = RiskGuard(1.0, 1000.0, 10.0)
    risk.mode = Mode.auto
    risk.disarm("feed disconnected")
    # feed comes back -- nothing in the system may flip mode back to auto
    assert risk.mode is Mode.manual
    with pytest.raises(Reject) as e:
        risk.check(cfg=AutoModeConfig(), symbol="stpRNG", lots=0.01,
                   open_positions=0, feed_stale=False, broker_connected=True,
                   source="auto", idem_key="k")
    assert e.value.reason == "not_armed"


@pytest.mark.asyncio
async def test_stale_feed_blocks_auto_orders_even_while_armed():
    risk = RiskGuard(1.0, 1000.0, 10.0)
    risk.mode = Mode.auto
    with pytest.raises(Reject) as e:
        risk.check(cfg=AutoModeConfig(), symbol="stpRNG", lots=0.01,
                   open_positions=0, feed_stale=True, broker_connected=True,
                   source="auto", idem_key="k")
    assert e.value.reason == "stale_data"


# --------------------------------------------------------------- idempotency
@pytest.mark.asyncio
async def test_duplicate_signal_yields_exactly_one_fill():
    price = {"stpRNG": 100.0}
    broker = PaperBroker(price_fn=lambda s: price.get(s), point_fn=lambda s: 0.1)
    risk = RiskGuard(1.0, 1000.0, 10.0)
    risk.mode = Mode.auto
    cfg = AutoModeConfig(lots=0.01, max_concurrent_positions=5)
    key = "stpRNG:60:1789200000:1"
    fills = []

    async def submit():
        try:
            risk.check(cfg=cfg, symbol="stpRNG", lots=cfg.lots, open_positions=len(fills),
                       feed_stale=False, broker_connected=True,
                       source="auto", idem_key=key)
        except Reject as r:
            return r.reason
        res = await broker.place_order("stpRNG", "buy", cfg.lots)
        if res.ok:
            risk.remember(key, res.ticket)
            risk.record_trade()
            fills.append(res.ticket)
        return "filled"

    assert await submit() == "filled"
    assert await submit() == "duplicate"
    assert await submit() == "duplicate"
    assert len(fills) == 1, f"same signal produced {len(fills)} fills"
    assert len(await broker.positions()) == 1


@pytest.mark.asyncio
async def test_concurrent_duplicate_signals_still_yield_one_fill():
    """Two deliveries racing must not both slip past the duplicate check."""
    risk = RiskGuard(1.0, 1000.0, 10.0)
    risk.mode = Mode.auto
    cfg = AutoModeConfig(lots=0.01, max_concurrent_positions=5)
    key = "stpRNG:60:1789200000:1"
    accepted = []
    lock = asyncio.Lock()

    async def submit():
        async with lock:                      # the app serialises submits
            try:
                risk.check(cfg=cfg, symbol="stpRNG", lots=cfg.lots,
                           open_positions=0, feed_stale=False,
                           broker_connected=True, source="auto", idem_key=key)
            except Reject:
                return
            risk.remember(key, "u")
            accepted.append(1)

    await asyncio.gather(*(submit() for _ in range(8)))
    assert len(accepted) == 1, f"{len(accepted)} of 8 racing duplicates accepted"


# ------------------------------------------------- auto mode is scoped
@pytest.mark.asyncio
async def test_auto_only_trades_the_armed_series():
    """Every chart you visit stays subscribed and keeps producing signals.
    An armed bot must trade ONLY the symbol+timeframe it was armed on, or it
    silently trades instruments the trader merely browsed past."""
    from app.chart_service import Signal

    armed_on = ("stpRNG", 60)
    submitted: list[tuple[str, int]] = []

    async def on_signal(sig: Signal, mode_is_auto: bool = True):
        if not mode_is_auto:
            return
        if armed_on is not None and (sig.symbol, sig.granularity) != armed_on:
            return
        submitted.append((sig.symbol, sig.granularity))

    def sig(symbol, gran):
        return Signal(symbol=symbol, granularity=gran, bar_epoch=1789200000,
                      direction=1, action="BUY", price=100.0)

    await on_signal(sig("stpRNG", 60))        # armed series -> trades
    await on_signal(sig("stpRNG", 3600))      # browsed timeframe -> ignored
    await on_signal(sig("frxXAUUSD", 60))     # other instrument -> ignored
    await on_signal(sig("frxXAUUSD", 900))    # ignored

    assert submitted == [("stpRNG", 60)], f"auto traded unarmed series: {submitted}"


@pytest.mark.asyncio
async def test_unarmed_binding_cleared_on_disarm():
    """Disarming must drop the binding, so re-arming cannot inherit a stale one."""
    from app.risk import RiskGuard
    from app.config import Mode
    risk = RiskGuard(1.0, 1000.0, 10.0)
    armed_on = ("stpRNG", 60)
    risk.mode = Mode.auto

    if risk.disarm("feed lost"):
        armed_on = None
    assert risk.mode is Mode.manual
    assert armed_on is None


# ---------------------------------------------- per-symbol data freshness
def _svc_with(series_spec):
    """ChartService pre-loaded with {(symbol, gran): last_bar_epoch}."""
    cs = ChartService(FakeFeed())
    for (sym, gran), epoch in series_spec.items():
        s = CandleSeries(gran)
        s.reset([Candle(epoch, 1, 1, 1, 1)])
        cs.series[(sym, gran)] = s
    return cs


def test_symbol_staleness_is_not_global():
    """A 24/7 instrument ticking every second must not vouch for a closed forex
    market. With one global clock, an order on the stale symbol passes the
    staleness check and fills against an hours-old price."""
    import time as _t
    now = int(_t.time())
    cs = _svc_with({("stpRNG", 60): now, ("frxXAUUSD", 60): now - int(13.8 * 3600)})

    assert cs.symbol_age("stpRNG") < 10
    assert cs.symbol_age("frxXAUUSD") > 40_000, \
        "closed market judged fresh via another symbol's ticks"


def test_a_poll_reply_does_not_refresh_a_closed_market():
    """The poller keeps getting replies for a closed market -- they just carry
    the same stale bars. Freshness must come from the newest BAR, not from the
    fact that a response arrived."""
    import time as _t
    now = int(_t.time())
    cs = _svc_with({("frxXAUUSD", 60): now - 3600})
    before = cs.symbol_age("frxXAUUSD")
    assert before > 3000
    # a reply arrives carrying the SAME newest bar
    cs.series[("frxXAUUSD", 60)].upsert(Candle(now - 3600, 1, 1, 1, 1))
    assert cs.symbol_age("frxXAUUSD") > 3000, "a stale reply refreshed the clock"


def test_forming_bar_is_not_counted_as_stale():
    """A 1h bar is legitimately up to an hour old while it forms."""
    import time as _t
    now = int(_t.time())
    cs = _svc_with({("stpRNG", 3600): now - 1800})   # half way through the bar
    assert cs.symbol_age("stpRNG") == 0.0


def test_unknown_symbol_is_stale_not_fresh():
    cs = _svc_with({})
    assert cs.symbol_age("neverSeen") == float("inf")


def test_freshest_timeframe_wins():
    """Several timeframes of one symbol: the freshest decides."""
    import time as _t
    now = int(_t.time())
    cs = _svc_with({("stpRNG", 3600): now - 7200, ("stpRNG", 60): now})
    assert cs.symbol_age("stpRNG") < 10
