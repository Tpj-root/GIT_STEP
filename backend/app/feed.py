"""Deriv WebSocket v3 market-data feed.

Owns exactly one socket. Responsibilities:
  * historical candle loads (paged, 5000 max per request -- server hard cap)
  * live `ohlc` subscriptions per (symbol, granularity)
  * keepalive ping (Deriv drops idle sockets after ~2 minutes)
  * exponential backoff reconnect, capped
  * on reconnect: re-fetch history and reconcile, never resume blind
  * staleness tracking so the risk guard can refuse to trade on old data
"""
from __future__ import annotations
import asyncio, json, time, logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional
import websockets

log = logging.getLogger("feed")

MAX_COUNT = 5000          # Deriv hard cap, verified live
PING_SECONDS = 30.0
BACKOFF_CAP = 30.0


@dataclass
class Candle:
    epoch: int
    open: float
    high: float
    low: float
    close: float

    @staticmethod
    def from_deriv(d: dict) -> "Candle":
        return Candle(int(d["epoch"]), float(d["open"]), float(d["high"]),
                      float(d["low"]), float(d["close"]))

    def to_dict(self) -> dict:
        return {"epoch": self.epoch, "open": self.open, "high": self.high,
                "low": self.low, "close": self.close}


class FeedState:
    disconnected = "disconnected"
    connecting = "connecting"
    live = "live"


class DerivFeed:
    def __init__(self, ws_url: str, stale_after: float = 10.0) -> None:
        self.ws_url = ws_url
        self.stale_after = stale_after
        self.state = FeedState.disconnected
        self.last_message_at: float = 0.0   # ANY frame -- socket liveness
        self.last_data_at: float = 0.0      # market data only -- feed freshness
        # Freshness is PER SYMBOL. A global clock is worse than none: a 24/7
        # instrument ticking every second keeps it warm while a closed forex
        # market sits hours stale, and orders on the stale symbol sail through.
        self.last_data_by_symbol: dict[str, float] = {}
        self._ws = None
        self._req_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._subs: set[tuple[str, int]] = set()
        self._pollers: dict[tuple[str, int], asyncio.Task] = {}
        self.streaming_blocked = False   # set when subscribe:1 is refused
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._ready = asyncio.Event()

        # callbacks, wired by the app
        self.on_history: Optional[Callable[[str, int, list[Candle]], Awaitable]] = None
        self.on_bar: Optional[Callable[[str, int, Candle, bool], Awaitable]] = None
        self.on_state: Optional[Callable[[str, str], Awaitable]] = None
        self.on_active_symbols: Optional[Callable[[list], Awaitable]] = None
        self.on_reconnected: Optional[Callable[[], Awaitable]] = None
        self._connections = 0

    # ---------------------------------------------------------------- lifecycle
    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        for t in self._pollers.values():
            t.cancel()
        self._pollers.clear()
        if self._ws:
            await self._ws.close()
        if self._task:
            self._task.cancel()

    @property
    def is_stale(self) -> bool:
        """Freshness of MARKET DATA, not of the socket.

        A keepalive pong proves the connection is alive; it proves nothing about
        whether prices are still arriving. Measuring staleness off any frame
        would let a dead data feed hide behind healthy pongs -- and this value
        gates order placement."""
        if self.state != FeedState.live:
            return True
        if self.last_data_at == 0.0:
            return True
        return (time.time() - self.last_data_at) > self.stale_after

    @property
    def data_age(self) -> float:
        if self.last_data_at == 0.0:
            return float("inf")
        return time.time() - self.last_data_at

    def symbol_age(self, symbol: str) -> float:
        """Seconds since this SYMBOL last printed. inf if never."""
        t = self.last_data_by_symbol.get(symbol)
        return float("inf") if t is None else time.time() - t

    def symbol_stale(self, symbol: str) -> bool:
        """Whether orders on this symbol must be refused. A closed market is
        stale by this measure, which is the correct answer -- you should not be
        filling against a price from hours ago."""
        if self.state != FeedState.live:
            return True
        return self.symbol_age(symbol) > self.stale_after

    async def _set_state(self, s: str, detail: str = "") -> None:
        if s != self.state:
            self.state = s
            log.info("feed state -> %s %s", s, detail)
            if self.on_state:
                await self.on_state(s, detail)

    # ---------------------------------------------------------------- run loop
    async def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                await self._set_state(FeedState.connecting)
                async with websockets.connect(
                    self.ws_url, open_timeout=30, max_size=16_000_000,
                    ping_interval=None,  # we drive our own Deriv-level ping
                ) as ws:
                    self._ws = ws
                    self.last_message_at = time.time()
                    await self._set_state(FeedState.live)
                    self._ready.set()
                    backoff = 1.0

                    self._connections += 1
                    pinger = asyncio.create_task(self._ping_loop(ws))
                    reauth = (asyncio.create_task(self.on_reconnected())
                              if self.on_reconnected and self._connections > 1 else None)
                    resub = asyncio.create_task(self._resubscribe_all())
                    try:
                        await self._read_loop(ws)
                    finally:
                        pinger.cancel()
                        resub.cancel()
                        if reauth:
                            reauth.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as e:                       # noqa: BLE001
                log.warning("feed error: %s", e)
            finally:
                self._ready.clear()
                self._ws = None
                self._fail_pending(ConnectionError("socket closed"))
                await self._set_state(FeedState.disconnected)

            if self._stop.is_set():
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_CAP)

    def _fail_pending(self, exc: Exception) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(exc)
        self._pending.clear()

    async def _ping_loop(self, ws) -> None:
        while True:
            await asyncio.sleep(PING_SECONDS)
            try:
                await ws.send(json.dumps({"ping": 1}))
            except Exception:
                return

    async def _read_loop(self, ws) -> None:
        async for raw in ws:
            self.last_message_at = time.time()
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            await self._dispatch(msg)

    async def _dispatch(self, msg: dict) -> None:
        rid = msg.get("req_id")
        if rid is not None and rid in self._pending:
            fut = self._pending.pop(rid)
            if not fut.done():
                fut.set_result(msg)
            # a subscribed history reply also seeds the chart; fall through
        mt = msg.get("msg_type")
        if mt in ("ohlc", "candles", "tick", "history"):
            now = time.time()
            self.last_data_at = now
            sym = None
            if mt == "ohlc":
                sym = (msg.get("ohlc") or {}).get("symbol")
            elif mt == "tick":
                sym = (msg.get("tick") or {}).get("symbol")
            else:
                sym = (msg.get("echo_req") or {}).get("ticks_history")
            if sym:
                self.last_data_by_symbol[sym] = now
        if mt == "ohlc" and self.on_bar:
            o = msg["ohlc"]
            bar = Candle(int(o["open_time"]), float(o["open"]), float(o["high"]),
                         float(o["low"]), float(o["close"]))
            closed = False  # `ohlc` always describes the forming bar
            await self.on_bar(o["symbol"], int(o["granularity"]), bar, closed)

    # ---------------------------------------------------------------- requests
    async def _send(self, payload: dict, timeout: float = 30.0) -> dict:
        if self._ws is None:
            raise ConnectionError("feed not connected")
        self._req_id += 1
        rid = self._req_id
        payload = {**payload, "req_id": rid}
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        await self._ws.send(json.dumps(payload))
        try:
            msg = await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(rid, None)
        if "error" in msg:
            raise RuntimeError(f"{msg['error'].get('code')}: {msg['error'].get('message')}")
        return msg

    async def wait_ready(self, timeout: float = 30.0) -> bool:
        try:
            await asyncio.wait_for(self._ready.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def fetch_active_symbols(self) -> list:
        try:
            msg = await self._send({"active_symbols": "brief", "product_type": "basic"})
            return msg.get("active_symbols", []) or []
        except Exception as e:                            # noqa: BLE001
            log.warning("active_symbols failed: %s", e)
            return []

    async def history(self, symbol: str, granularity: int,
                      count: int = 1000, end: str | int = "latest") -> list[Candle]:
        """Fetch candles. Pages backwards when count > the 5000 server cap."""
        out: list[Candle] = []
        remaining = count
        cursor: str | int = end
        while remaining > 0:
            n = min(remaining, MAX_COUNT)
            msg = await self._send({
                "ticks_history": symbol, "end": cursor, "count": n,
                "style": "candles", "granularity": granularity,
                "adjust_start_time": 1})
            batch = [Candle.from_deriv(c) for c in msg.get("candles", [])]
            if not batch:
                break
            out = batch + out
            remaining -= len(batch)
            cursor = batch[0].epoch - 1
            if len(batch) < n:
                break
        # de-dup + sort (paging boundaries can overlap)
        seen: dict[int, Candle] = {c.epoch: c for c in out}
        return [seen[k] for k in sorted(seen)]

    async def subscribe(self, symbol: str, granularity: int, count: int = 1000) -> list[Candle]:
        """Subscribe to live bars and return the seeded history in one step.

        Deriv refuses `subscribe:1` from geo/IP-restricted networks with a
        misleading `InvalidSymbol` -- the same symbol fetches history fine. When
        that happens we transparently fall back to polling so the app still runs.
        """
        self._subs.add((symbol, granularity))
        key = (symbol, granularity)
        req = {"ticks_history": symbol, "end": "latest", "count": min(count, MAX_COUNT),
               "style": "candles", "granularity": granularity, "adjust_start_time": 1}

        candles: list[Candle] = []
        if not self.streaming_blocked:
            try:
                msg = await self._send({**req, "subscribe": 1})
                candles = [Candle.from_deriv(c) for c in msg.get("candles", [])]
            except RuntimeError as e:
                if "InvalidSymbol" not in str(e):
                    raise
                log.warning("streaming subscribe refused (%s) -- falling back to polling", e)
                self.streaming_blocked = True

        if self.streaming_blocked:
            msg = await self._send(req)
            candles = [Candle.from_deriv(c) for c in msg.get("candles", [])]
            self._start_poller(symbol, granularity)

        if self.on_history:
            await self.on_history(symbol, granularity, candles)
        return candles

    # ------------------------------------------------------------ poll fallback
    def _poll_interval(self, granularity: int) -> float:
        """Poll fast enough that the forming bar looks live AND that market data
        never ages past the staleness threshold -- `is_stale` gates order
        placement, so a poll slower than that budget would make the app
        permanently un-tradeable. Still far under the 220 req/min limit."""
        budget = max(2.0, self.stale_after / 2.0)
        return max(2.0, min(granularity / 4.0, 15.0, budget))

    def _start_poller(self, symbol: str, granularity: int) -> None:
        key = (symbol, granularity)
        if key in self._pollers and not self._pollers[key].done():
            return
        self._pollers[key] = asyncio.create_task(self._poll_loop(symbol, granularity))

    async def _poll_loop(self, symbol: str, granularity: int) -> None:
        interval = self._poll_interval(granularity)
        log.info("polling %s/%ss every %.1fs", symbol, granularity, interval)
        while not self._stop.is_set() and (symbol, granularity) in self._subs:
            await asyncio.sleep(interval)
            if self._ws is None:
                continue
            try:
                msg = await self._send({
                    "ticks_history": symbol, "end": "latest", "count": 2,
                    "style": "candles", "granularity": granularity,
                    "adjust_start_time": 1})
                for c in msg.get("candles", []):
                    if self.on_bar:
                        await self.on_bar(symbol, granularity, Candle.from_deriv(c), False)
            except Exception as e:                        # noqa: BLE001
                log.debug("poll %s/%s failed: %s", symbol, granularity, e)

    @property
    def transport(self) -> str:
        return "polled" if self.streaming_blocked else "streaming"

    async def unsubscribe(self, symbol: str, granularity: int) -> None:
        self._subs.discard((symbol, granularity))
        t = self._pollers.pop((symbol, granularity), None)
        if t:
            t.cancel()
        try:
            await self._send({"forget_all": "candles"})
            await self._resubscribe_all()
        except Exception:
            pass

    async def _resubscribe_all(self) -> None:
        """After a reconnect, re-request history for every live subscription and
        hand it back for reconciliation. Never resume a stream blind."""
        await asyncio.sleep(0.1)
        for symbol, gran in list(self._subs):
            try:
                await self.subscribe(symbol, gran)
                log.info("resubscribed %s/%ss", symbol, gran)
            except Exception as e:                        # noqa: BLE001
                log.warning("resubscribe failed %s/%s: %s", symbol, gran, e)
