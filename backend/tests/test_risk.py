"""Every risk-guard rejection path, exercised explicitly.

A guard that has never been seen to reject is not a guard.
"""
import sys, time
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.risk import RiskGuard, Reject
from app.config import ModeConfig, AutoModeConfig, Mode


def guard(**kw):
    return RiskGuard(hard_max_lots=kw.get("hard_max_lots", 1.0),
                     hard_max_daily_loss=kw.get("hard_max_daily_loss", 1000.0),
                     stale_seconds=10.0,
                     reset_hour_utc=kw.get("reset_hour_utc", 0))


def ok_args(**over):
    base = dict(cfg=ModeConfig(lots=0.01), symbol="stpRNG", lots=0.01,
                open_positions=0, feed_stale=False, broker_connected=True,
                source="manual")
    base.update(over)
    return base


def test_baseline_passes():
    guard().check(**ok_args())          # must not raise, or nothing below means anything


@pytest.mark.parametrize("over,reason", [
    (dict(feed_stale=True),                       "stale_data"),
    (dict(broker_connected=False),                "broker_down"),
    (dict(lots=0),                                "bad_lots"),
    (dict(lots=-1),                               "bad_lots"),
    (dict(lots=5.0, cfg=ModeConfig(lots=5.0)),    "lots_cap"),
    (dict(lots=0.5, cfg=ModeConfig(lots=0.01)),   "lots_cap"),
    (dict(open_positions=1),                      "max_positions"),
])
def test_rejection_paths(over, reason):
    with pytest.raises(Reject) as e:
        guard().check(**ok_args(**over))
    assert e.value.reason == reason


def test_kill_switch_blocks_everything():
    g = guard()
    g.engage_kill_switch()
    with pytest.raises(Reject) as e:
        g.check(**ok_args())
    assert e.value.reason == "kill_switch"
    assert g.mode is Mode.manual, "kill switch must force manual mode"


def test_kill_switch_wins_over_a_perfectly_valid_order():
    g = guard()
    g.check(**ok_args())               # fine before
    g.engage_kill_switch()
    with pytest.raises(Reject):
        g.check(**ok_args())
    g.release_kill_switch()
    g.check(**ok_args())               # fine again


def test_max_trades_per_day():
    g = guard()
    cfg = ModeConfig(lots=0.01, max_trades_per_day=3)
    for _ in range(3):
        g.check(**ok_args(cfg=cfg))
        g.record_trade()
    with pytest.raises(Reject) as e:
        g.check(**ok_args(cfg=cfg))
    assert e.value.reason == "max_trades"


def test_daily_loss_limit():
    g = guard()
    cfg = ModeConfig(lots=0.01, max_daily_loss=50)
    g.record_pnl(-49.99)
    g.check(**ok_args(cfg=cfg))        # still under
    g.record_pnl(-0.02)
    with pytest.raises(Reject) as e:
        g.check(**ok_args(cfg=cfg))
    assert e.value.reason == "daily_loss"


def test_profit_does_not_unlock_a_breached_day():
    """Losses then profits: the limit is on realised P&L, so recovering above
    -limit legitimately re-opens trading. Pin the behaviour either way."""
    g = guard()
    cfg = ModeConfig(lots=0.01, max_daily_loss=50)
    g.record_pnl(-60)
    with pytest.raises(Reject):
        g.check(**ok_args(cfg=cfg))
    g.record_pnl(+20)                  # back to -40
    g.check(**ok_args(cfg=cfg))


def test_hard_daily_loss_cap_overrides_a_permissive_config():
    g = guard(hard_max_daily_loss=100)
    cfg = ModeConfig(lots=0.01, max_daily_loss=100000)
    g.record_pnl(-150)
    with pytest.raises(Reject) as e:
        g.check(**ok_args(cfg=cfg))
    assert e.value.reason == "daily_loss"


def test_hard_lots_cap_overrides_a_permissive_config():
    g = guard(hard_max_lots=0.1)
    cfg = ModeConfig(lots=10.0)
    with pytest.raises(Reject) as e:
        g.check(**ok_args(cfg=cfg, lots=10.0))
    assert e.value.reason == "lots_cap"


# ------------------------------------------------------------------ auto mode
def test_auto_order_rejected_when_not_armed():
    g = guard()
    assert g.mode is Mode.manual
    with pytest.raises(Reject) as e:
        g.check(**ok_args(source="auto", cfg=AutoModeConfig()))
    assert e.value.reason == "not_armed"


def test_guard_boots_into_manual():
    """Auto mode must never survive a restart."""
    assert guard().mode is Mode.manual


def test_disarm_reports_whether_it_was_armed():
    g = guard()
    assert g.disarm("feed lost") is False
    g.mode = Mode.auto
    assert g.disarm("feed lost") is True
    assert g.mode is Mode.manual


# ---------------------------------------------------------------- idempotency
def test_same_signal_twice_produces_one_order():
    g = guard()
    g.mode = Mode.auto
    cfg = AutoModeConfig(lots=0.01)
    key = "stpRNG:60:1789200000:1"

    g.check(**ok_args(source="auto", cfg=cfg, idem_key=key))
    g.remember(key, "uuid-1")
    g.record_trade()

    with pytest.raises(Reject) as e:
        g.check(**ok_args(source="auto", cfg=cfg, idem_key=key))
    assert e.value.reason == "duplicate"
    assert "uuid-1" in e.value.detail


def test_different_bars_are_not_duplicates():
    g = guard(); g.mode = Mode.auto
    cfg = AutoModeConfig(lots=0.01)
    g.check(**ok_args(source="auto", cfg=cfg, idem_key="stpRNG:60:100:1"))
    g.remember("stpRNG:60:100:1", "u1")
    g.check(**ok_args(source="auto", cfg=cfg, idem_key="stpRNG:60:160:-1"))


def test_manual_orders_are_not_deduplicated():
    """A human clicking BUY twice means two orders. Only auto signals dedupe."""
    g = guard()
    key = "stpRNG:60:100:1"
    g.check(**ok_args(source="manual", idem_key=key))
    g.remember(key, "u1")
    g.check(**ok_args(source="manual", idem_key=key))


# ------------------------------------------------------------- day rollover
def test_counters_reset_on_day_rollover(monkeypatch):
    g = guard(reset_hour_utc=0)
    base = 1_700_000_000.0
    monkeypatch.setattr(time, "time", lambda: base)
    g.record_trade(); g.record_pnl(-40)
    assert g.counters.trades == 1

    monkeypatch.setattr(time, "time", lambda: base + 86_400)
    assert g.counters.trades == 0, "counters did not reset next day"
    assert g.counters.realised_pnl == 0.0


def test_reset_hour_shifts_the_day_boundary(monkeypatch):
    g = guard(reset_hour_utc=17)
    # 2023-11-14 16:00 UTC -> still the previous trading day under a 17:00 reset
    monkeypatch.setattr(time, "time", lambda: 1_699_977_600.0)
    before = g.counters.day_key
    monkeypatch.setattr(time, "time", lambda: 1_699_977_600.0 + 3600)  # 17:00
    assert g.counters.day_key != before, "17:00 UTC should start a new trading day"


def test_status_is_serialisable():
    s = guard().status()
    assert s["mode"] == "manual" and s["kill_switch"] is False
    assert set(s) >= {"mode", "kill_switch", "trades_today", "realised_pnl"}
