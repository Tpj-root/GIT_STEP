"""FastAPI application.

Owns both transports (Deriv WS for data, a Broker for execution) and exposes a
single WebSocket to the frontend. The frontend never holds a broker credential
and never enforces a risk limit.
"""
from __future__ import annotations
import asyncio, logging, uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .config import settings, ConfigBundle, ModeConfig, AutoModeConfig, Mode, BrokerKind
from .symbols import registry, TIMEFRAMES
from .feed import DerivFeed, FeedState
from .chart_service import ChartService, Signal
from .hub import hub
from .risk import RiskGuard, Reject
from .store import Store
from .brokers import PaperBroker, MT5Broker, DerivContractBroker
from .indicators import specs as indicator_specs, overlay_specs
from .deriv_auth import get_ws_url

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(name)-12s %(message)s")
log = logging.getLogger("app")

DEFAULT_SUBS = [("stpRNG", 60), ("frxXAUUSD", 60)]


class App:
    """Process-wide singletons, grouped so tests can build one in isolation."""
    def __init__(self) -> None:
        self.feed = DerivFeed(settings.ws_url, stale_after=settings.stale_tick_seconds,
                              url_provider=get_ws_url,
                              headers={"Deriv-App-ID": settings.deriv_app_id})
        self.chart = ChartService(self.feed)
        self.store = Store(settings.db_path)
        self.risk = RiskGuard(settings.hard_max_lots, settings.hard_max_daily_loss,
                              settings.stale_tick_seconds, settings.counter_reset_utc_hour)
        self.config = ConfigBundle()
        self.broker = None
        self._mtm_task: Optional[asyncio.Task] = None
        # the (symbol, granularity) auto mode is armed for; None when not armed
        self.armed_on: Optional[tuple[str, int]] = None

    # --------------------------------------------------------------- helpers
    def symbol_stale(self, symbol: str) -> bool:
        """Authoritative staleness for order gating: the socket must be live AND
        this symbol must actually be producing new bars."""
        if self.feed.state != FeedState.live:
            return True
        return self.chart.symbol_age(symbol) > settings.stale_tick_seconds

    def last_price(self, symbol: str) -> Optional[float]:
        for (sym, gran), series in self.chart.series.items():
            if sym == symbol and series.last:
                return series.last.close
        return None

    def point(self, symbol: str) -> float:
        info = registry.get(symbol)
        return info.point if info else 0.1

    def make_broker(self):
        if settings.broker is BrokerKind.mt5:
            return MT5Broker(settings.mt5_login, settings.mt5_password,
                             settings.mt5_server,
                             {s.code: s.mt5_symbol for s in registry.all()})
        if settings.broker is BrokerKind.deriv:
            return DerivContractBroker(
                self.feed, token=settings.deriv_api_token,
                contract_kind=settings.deriv_contract_type,
                multiplier=settings.deriv_multiplier)
        return PaperBroker(price_fn=self.last_price, point_fn=self.point)

    @property
    def cfg(self) -> ModeConfig:
        return self.config.auto if self.risk.mode is Mode.auto else self.config.manual

    async def status_payload(self) -> dict:
        acct = await self.broker.account_info() if self.broker else None
        return {
            "feed": self.feed.state, "transport": self.feed.transport,
            "feed_stale": self.feed.is_stale,
            "data_age": round(self.feed.data_age, 1),
            "symbol_age": {s.code: (None if self.chart.symbol_age(s.code) == float("inf")
                                    else round(self.chart.symbol_age(s.code), 1))
                           for s in registry.all()},
            "symbol_stale": {s.code: self.symbol_stale(s.code) for s in registry.all()},
            "broker": acct.to_dict() if acct else None,
            "symbols_note": registry.note,
            "armed_on": (f"{self.armed_on[0]}/{self.armed_on[1]}s"
                         if self.armed_on else None),
            **self.risk.status(),
        }

    async def push_status(self) -> None:
        await hub.broadcast("status", await self.status_payload())

    # --------------------------------------------------------------- events
    async def on_reconnected(self) -> None:
        """A new socket is a new session: Deriv does not carry authorization
        across connections. Without this the broker silently drops to
        unauthenticated after any reconnect and every order fails."""
        b = self.broker
        if b is not None and getattr(b, "name", "") == "deriv":
            ok = await b.connect()
            log.info("re-authorized deriv broker after reconnect: %s", ok)
            if not ok and self.risk.disarm("broker re-auth failed"):
                await hub.broadcast("alert", {
                    "level": "critical",
                    "message": "AUTO DISARMED - broker re-authorization failed "
                               "after a reconnect."})

    async def on_feed_state(self, state: str, detail: str) -> None:
        if state != FeedState.live and self.risk.disarm(f"feed {state}"):
            self.armed_on = None
            await hub.broadcast("alert", {
                "level": "critical",
                "message": "AUTO MODE DISARMED - market data feed lost. "
                           "Re-arm manually once the feed is live.",
            })
        await self.push_status()

    async def on_bar_event(self, kind: str, payload: dict) -> None:
        await hub.broadcast(kind, payload)

    async def on_signal(self, sig: Signal) -> None:
        await self.store.log_signal(sig)
        await hub.broadcast("signal", {**sig.to_dict(),
                                       "idem_key": sig.idempotency_key,
                                       "executed": self.risk.mode is Mode.auto})
        if self.risk.mode is not Mode.auto:
            return
        if self.armed_on is not None and (sig.symbol, sig.granularity) != self.armed_on:
            log.info("ignoring %s signal on %s/%ss -- armed on %s/%ss",
                     sig.action, sig.symbol, sig.granularity, *self.armed_on)
            return
        side = "buy" if sig.direction > 0 else "sell"
        await self.submit(symbol=sig.symbol, side=side, source="auto",
                          idem_key=sig.idempotency_key)

    # --------------------------------------------------------------- ordering
    async def submit(self, *, symbol: str, side: str, source: str,
                     lots: Optional[float] = None,
                     sl: Optional[float] = None, tp: Optional[float] = None,
                     idem_key: Optional[str] = None) -> dict:
        cfg = self.cfg
        lots = cfg.lots if lots is None else float(lots)
        sl = cfg.stop_loss_points if sl is None else sl
        tp = cfg.take_profit_points if tp is None else tp
        order_uuid = uuid.uuid4().hex
        positions = await self.broker.positions()
        acct = await self.broker.account_info()

        common = dict(order_uuid=order_uuid, idem_key=idem_key, source=source,
                      mode=self.risk.mode.value, symbol=symbol, side=side,
                      lots=lots, sl_points=sl, tp_points=tp,
                      broker=self.broker.name)
        try:
            self.risk.check(cfg=cfg, symbol=symbol, lots=lots,
                            open_positions=len(positions),
                            # per-symbol bar age, not a global clock
                            feed_stale=self.symbol_stale(symbol),
                            broker_connected=acct.connected,
                            source=source, idem_key=idem_key)
        except Reject as r:
            await self.store.log_order(**common, accepted=0,
                                       reject_reason=f"{r.reason}: {r.detail}")
            await hub.broadcast("order", {"ok": False, "reason": r.reason,
                                          "detail": r.detail, "symbol": symbol,
                                          "side": side, "source": source})
            log.warning("REJECTED %s %s (%s): %s", side, symbol, source, r)
            return {"ok": False, "reason": r.reason, "detail": r.detail}

        res = await self.broker.place_order(symbol, side, lots, sl, tp,
                                            comment=f"{source}:chandelier")
        if res.ok:
            self.risk.record_trade()
            if idem_key:
                self.risk.remember(idem_key, order_uuid)
        await self.store.log_order(**common, accepted=1 if res.ok else 0,
                                   reject_reason=None if res.ok else res.message,
                                   ticket=res.ticket, fill_price=res.price,
                                   response=res.message)
        await hub.broadcast("order", {"ok": res.ok, **res.to_dict(),
                                      "symbol": symbol, "side": side,
                                      "source": source})
        await self.broadcast_positions()
        return {"ok": res.ok, **res.to_dict()}

    async def broadcast_positions(self) -> None:
        pos = await self.broker.positions()
        acct = await self.broker.account_info()
        await hub.broadcast("positions", {
            "positions": [p.to_dict() for p in pos],
            "account": acct.to_dict()})

    # --------------------------------------------------------------- loop
    async def mark_loop(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            try:
                if isinstance(self.broker, PaperBroker):
                    closed = await self.broker.mark_to_market()
                    for t in closed:
                        rec = next((c for c in reversed(self.broker.closed_log)
                                    if c["ticket"] == t), None)
                        if rec:
                            self.risk.record_pnl(rec["profit"])
                            await hub.broadcast("alert", {
                                "level": "info",
                                "message": f"{rec['symbol']} auto-closed "
                                           f"({'TP' if rec['profit'] > 0 else 'SL'}) "
                                           f"pnl {rec['profit']:+.2f}"})
                if hub.count:
                    await self.broadcast_positions()
                    await self.push_status()
            except Exception as e:  # noqa: BLE001
                log.debug("mark loop: %s", e)


application = App()


@asynccontextmanager
async def lifespan(_: FastAPI):
    a = application
    await a.store.open()
    a.feed.on_state = a.on_feed_state
    a.feed.on_reconnected = a.on_reconnected
    a.chart.on_signal = a.on_signal
    a.chart.on_bar_event = a.on_bar_event
    a.feed.start()

    if await a.feed.wait_ready(30):
        registry.enrich(await a.feed.fetch_active_symbols())
        log.info("symbols: %s", registry.note)
    else:
        log.error("feed did not become ready within 30s")

    a.broker = a.make_broker()
    await a.broker.connect()
    log.info("broker=%s connected=%s", a.broker.name,
             (await a.broker.account_info()).connected)

    for sym, gran in DEFAULT_SUBS:
        try:
            await a.chart.ensure(sym, gran, count=1000)
        except Exception as e:  # noqa: BLE001
            log.error("initial subscribe %s/%s failed: %s", sym, gran, e)

    a._mtm_task = asyncio.create_task(a.mark_loop())
    log.info("ready -- mode=%s (auto never survives a restart)", a.risk.mode.value)
    yield
    if a._mtm_task:
        a._mtm_task.cancel()
    await a.feed.stop()
    await a.store.close()


app = FastAPI(title="Step Index Terminal", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])


# ------------------------------------------------------------------ schemas
class OrderReq(BaseModel):
    symbol: str
    side: str = Field(pattern="^(buy|sell)$")
    lots: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    source: str = Field("manual", pattern="^(manual|auto)$")
    # Links a manual order back to the signal that prompted it. Recorded for the
    # audit trail only -- the duplicate check applies to auto orders, because a
    # human clicking BUY twice genuinely means two orders.
    idem_key: Optional[str] = None


class ModeReq(BaseModel):
    mode: str = Field(pattern="^(auto|manual)$")
    # Arming binds to ONE symbol + timeframe. Every chart you visit stays
    # subscribed and keeps producing signals, so without this an armed bot would
    # trade instruments and timeframes you only browsed past -- which is not
    # what the arm dialog promises.
    symbol: Optional[str] = None
    granularity: Optional[int] = None


class IndicatorReq(BaseModel):
    period: Optional[int] = Field(None, ge=1, le=200)
    multiplier: Optional[float] = Field(None, gt=0, le=10)


class OverlayReq(BaseModel):
    """Toggle or reconfigure one display indicator."""
    id: str
    visible: Optional[bool] = None
    params: dict[str, float] = Field(default_factory=dict)


# ------------------------------------------------------------------ routes
@app.get("/api/symbols")
async def get_symbols():
    return {"symbols": [s.to_dict() for s in registry.all()],
            "timeframes": [{"granularity": g, "label": l} for g, l in TIMEFRAMES.items()],
            "note": registry.note, "enriched": registry.enriched}


@app.get("/api/indicators")
async def get_indicators():
    return {"indicators": indicator_specs(),
            "overlays": overlay_specs(),
            "params": application.chart.params,
            "overlay_state": application.chart.overlays}


@app.put("/api/overlays")
async def put_overlay(req: OverlayReq):
    patch: dict = dict(req.params)
    if req.visible is not None:
        patch["visible"] = req.visible
    try:
        state = application.chart.set_overlay(req.id, patch)
    except KeyError:
        raise HTTPException(404, f"unknown indicator {req.id}")
    for (sym, gran) in list(application.chart.series):
        await hub.broadcast("overlays", {
            "symbol": sym, "granularity": gran,
            "overlays": application.chart.overlay_data(sym, gran)})
    return {"id": req.id, "state": state,
            "overlay_state": application.chart.overlays}


@app.put("/api/indicators")
async def put_indicators(req: IndicatorReq):
    application.chart.set_params(period=req.period, multiplier=req.multiplier)
    for (sym, gran) in list(application.chart.series):
        await hub.broadcast("indicator_line", {
            "symbol": sym, "granularity": gran,
            "line": application.chart.indicator_line(sym, gran)})
    return {"params": application.chart.params}


@app.get("/api/candles")
async def get_candles(symbol: str, tf: int = Query(60), count: int = Query(1000, le=20000)):
    if registry.get(symbol) is None:
        raise HTTPException(404, f"unknown symbol {symbol}")
    if tf not in TIMEFRAMES:
        raise HTTPException(400, f"unsupported timeframe {tf}")
    await application.chart.ensure(symbol, tf, count=count)
    series = application.chart.series[(symbol, tf)]
    return {"symbol": symbol, "granularity": tf,
            "candles": [c.to_dict() for c in series.bars],
            "line": application.chart.indicator_line(symbol, tf),
            "overlays": application.chart.overlay_data(symbol, tf),
            "indicator": application.chart.snapshot(symbol, tf)}


@app.get("/api/config")
async def get_config():
    return application.config.model_dump()


@app.put("/api/config")
async def put_config(bundle: ConfigBundle):
    application.config = bundle
    await hub.broadcast("config", bundle.model_dump())
    return bundle.model_dump()


@app.post("/api/mode")
async def set_mode(req: ModeReq):
    a = application
    if req.mode == "auto":
        if a.risk.kill_switch:
            raise HTTPException(409, "kill switch engaged - release it first")
        arm_sym = req.symbol or "stpRNG"
        if a.symbol_stale(arm_sym):
            age = a.chart.symbol_age(arm_sym)
            raise HTTPException(409, f"{arm_sym} has no recent data "
                                     f"({'never' if age == float('inf') else f'{age:.0f}s old'})"
                                     " - refusing to arm. Is the market open?")
        try:
            AutoModeConfig(**a.config.auto.model_dump())
        except Exception as e:
            raise HTTPException(422, f"auto config invalid: {e}")
        if req.symbol and registry.get(req.symbol) is None:
            raise HTTPException(404, f"unknown symbol {req.symbol}")
        if req.symbol and req.granularity:
            a.armed_on = (req.symbol, int(req.granularity))
        else:
            a.armed_on = None          # legacy callers: no restriction
        a.risk.mode = Mode.auto
        log.warning("AUTO MODE ARMED on %s: %s",
                    a.armed_on or "ALL SUBSCRIBED SERIES", a.config.auto.model_dump())
    else:
        a.risk.mode = Mode.manual
        a.armed_on = None
    await a.push_status()
    return {**a.risk.status(),
            "armed_on": (f"{a.armed_on[0]}/{a.armed_on[1]}s" if a.armed_on else None)}


@app.post("/api/order")
async def post_order(req: OrderReq):
    return await application.submit(symbol=req.symbol, side=req.side,
                                    source=req.source, lots=req.lots,
                                    sl=req.sl, tp=req.tp, idem_key=req.idem_key)


@app.post("/api/close")
async def post_close(ticket: str):
    res = await application.broker.close_position(ticket)
    await application.broadcast_positions()
    return res.to_dict()


@app.post("/api/close-all")
async def post_close_all():
    res = await application.broker.close_all()
    await application.broadcast_positions()
    return {"closed": [r.to_dict() for r in res]}


@app.post("/api/kill")
async def post_kill():
    """Kill switch. Must work even when the feed is down."""
    a = application
    a.risk.engage_kill_switch()
    a.armed_on = None
    results = []
    try:
        results = [r.to_dict() for r in await a.broker.close_all()]
    except Exception as e:  # noqa: BLE001
        log.error("close_all during kill: %s", e)
    await hub.broadcast("alert", {"level": "critical",
                                  "message": "KILL SWITCH - all positions closed, "
                                             "auto mode disabled."})
    await a.push_status()
    return {"killed": True, "closed": results, **a.risk.status()}


@app.post("/api/kill/release")
async def post_kill_release():
    application.risk.release_kill_switch()
    await application.push_status()
    return application.risk.status()


@app.get("/api/positions")
async def get_positions():
    pos = await application.broker.positions()
    return {"positions": [p.to_dict() for p in pos]}


@app.get("/api/account")
async def get_account():
    return (await application.broker.account_info()).to_dict()


@app.get("/health")
async def health():
    """Liveness only — deliberately does NOT touch the broker or the feed, so a
    closed market or a disconnected broker cannot make the container look dead
    and trigger a restart loop."""
    return {"ok": True}


@app.get("/api/status")
async def get_status():
    return await application.status_payload()


@app.get("/api/log")
async def get_log(limit: int = Query(100, le=1000), table: str = "orders"):
    return {"rows": await application.store.recent(table, limit)}


@app.websocket("/stream")
async def stream(ws: WebSocket):
    await hub.connect(ws)
    try:
        # Send through the hub so these share the per-connection lock with the
        # broadcast loop. Writing directly would race it and kill the socket.
        await hub.send(ws, "status", await application.status_payload())
        # snapshot the mapping: the feed can add a series mid-iteration
        for (sym, gran), series in list(application.chart.series.items()):
            await hub.send(ws, "history", {
                "symbol": sym, "granularity": gran,
                "candles": [c.to_dict() for c in series.bars],
                "line": application.chart.indicator_line(sym, gran),
                "overlays": application.chart.overlay_data(sym, gran),
                "indicator": application.chart.snapshot(sym, gran)})
        while True:
            await ws.receive_text()      # client keepalive; no client commands
    except WebSocketDisconnect:
        pass
    except Exception as e:                                  # noqa: BLE001
        log.warning("stream closed: %s", e)
    finally:
        await hub.disconnect(ws)