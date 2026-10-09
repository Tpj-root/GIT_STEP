# Step Index / XAUUSD Charting Terminal

A single-user charting terminal for Deriv's **Step Index** and **Gold/USD**, with
a Chandelier Exit overlay and optional automated execution.

Runs end to end with **no credentials** — the paper broker is the default.

---

## Quick start

```bash
docker compose up --build
```

Open <http://localhost:5173>. That's it — no `.env`, no API token, no account.

Cold start is ~13s. Only one port is published: the frontend container serves
the built app *and* proxies `/api` and `/stream` to the backend, so nothing
host-specific is baked into the bundle and the same image runs anywhere. The
audit database lives in a named volume (`trading-data`) and survives
`docker compose down`.

To use credentials later, copy `.env.example` to `.env`.

### Running without Docker (development)

```bash
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements-dev.txt
cd backend && ../.venv/bin/uvicorn app.main:app --port 8010     # terminal 1
cd frontend && npm install && npm run dev                       # terminal 2
```

In dev the frontend calls `http://localhost:8010` directly; in the Docker build
it uses same-origin URLs through nginx. Nothing to configure either way.

---

## Windows handover

`docker compose up --build` is all that is needed on Windows with Docker
Desktop — **with one exception.**

### MT5 lot trading cannot run inside Docker

The `MetaTrader5` Python package drives a locally installed MT5 terminal over
Windows IPC. Docker Desktop runs Linux containers inside a WSL2 VM, which cannot
reach that terminal.

| Broker | In Docker | Notes |
|---|---|---|
| `paper` | works | default, no credentials |
| `deriv` | works | contracts priced in **stake**, needs an API token |
| `mt5` | **cannot** | backend must run natively on Windows |

For MT5, run the backend natively and keep the frontend in Docker.

**Step 1** — on the Windows host, from the `backend\` folder:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\pip install -r requirements.txt MetaTrader5
.venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --port 8010
```

**Step 2** — in a second terminal, from the project root:

```powershell
docker compose -f docker-compose.yml -f docker-compose.windows-mt5.yml up
```

The overlay drops the backend container and repoints nginx at
`host.docker.internal:8010`. `BACKEND_ORIGIN` is an environment variable on the
frontend image, so switching between layouts needs no rebuild.

The MT5 terminal must be installed, running, and logged in on the same machine.

### Other Windows notes

- **Line endings.** `.gitattributes` forces LF. A CRLF config file copied into a
  Linux container fails with `\r: command not found` — a classic and very
  confusing handover trap.
- **Named volume, not a bind mount.** `trading-data` sidesteps Windows host-path
  and permission problems entirely.
- **Ports.** Only `5173` is published publicly; `8010` is bound to loopback for
  `doctor.py` and debugging. Change the left-hand side in `docker-compose.yml`
  if `5173` is taken.
- **Check the broker before trading:** `python backend/doctor.py`.

---

## Architecture

Two transports, and they are not interchangeable:

| Need | Transport |
|---|---|
| Live + historical prices, both symbols | Deriv WebSocket v3 |
| Orders in **lots** on MT5 | `MetaTrader5` package (Windows, local terminal) |
| Orders in **stake** (contracts) | Deriv WebSocket v3 `proposal` → `buy` |

Deriv's WebSocket API **cannot place MT5 orders**. Its `mt5_*` calls cover
account creation, balance and transfers only; there is no `mt5_buy`.

```
React (Vite + TS, lightweight-charts v4)
   │  ws /stream        ← candles, signals, orders, positions, status
   │  REST /api/…
   ▼
FastAPI backend
   ├── DerivFeed        → Deriv WS v3      (market data, both symbols)
   ├── ChartService     → series + indicators, closed-bar signals
   ├── Broker           → PaperBroker | MT5Broker | DerivContractBroker
   ├── RiskGuard        → limits, kill switch, idempotency
   └── Store            → append-only SQLite audit log
```

The frontend never holds a broker credential and never enforces a risk limit.

---

## Verified against the live API

Measured, not assumed:

| Fact | Value |
|---|---|
| Step Index symbol | `stpRNG` (`frxXAUUSD` for gold) |
| Tick interval | exactly 1s |
| Step size | exactly ±0.1, absolute |
| `ticks_history` max count | 5000 (hard cap) |
| History depth | ~365 days **with an explicit `start`** |
| Rate limits | 220/min general, 80/min pricing |
| Idle timeout | 2 min — ping required |

### Two traps worth knowing

1. **Silent history fallback.** Requesting >365 days back returns the *latest*
   ticks with **no error**. A backward-walking loop silently re-ingests recent
   data and corrupts everything downstream with no failure signal.
2. **Count-based paging quietly dies.** `end` + `count` without an explicit
   `start` stops advancing after ~1 day.

Both are guarded: every response is validated against the requested window and
hard-fails on mismatch.

### Geo restrictions and the polling fallback

From restricted networks (datacenters, some countries) Deriv refuses
`active_symbols`, `contracts_for`, `proposal`, **and streaming subscriptions** —
the last with a misleading `InvalidSymbol`, even though the same symbol fetches
history fine on the same socket.

The app degrades rather than failing:

- `active_symbols` empty → falls back to a built-in symbol table, and says so.
- `subscribe` refused → falls back to **polling**; the UI shows `(polled)`.

Poll cadence is capped at half the staleness threshold, otherwise the app would
be permanently un-tradeable by its own risk guard.

---

## Chandelier Exit

```
ATR       = Wilder-smoothed True Range over `period` (default 22)
longStop  = highest(period) - multiplier * ATR       (default 3.0)
shortStop = lowest(period)  + multiplier * ATR
```

Direction is a stateful fold — each bar depends on the **previous** bar's
ratcheted stops. **Signals fire only on a direction change, and only on a closed
bar.** A forming bar repaints, so acting on it produces phantom trades that later
vanish from the chart.

Only the active stop is drawn, as a single series coloured per point. Two series
would draw two continuous lines (lightweight-charts connects across whitespace
rather than breaking on it), which reads as a support/resistance channel and
misrepresents the indicator.

### TradingView parity

The engine **defaults to matching TradingView's Chandelier Exit** (the
widely-installed "everget" script), verified bar-for-bar against an independent
transcription of the Pine source across 12 random walks and confirmed on live
Deriv data:

| XAUUSD 1h, 691 bars | Flips | Same bar | Direction agrees |
|---|---:|---:|---:|
| default (`use_close=True`) | 22 vs 22 | **22** | **100.0%** |
| `use_close=False` (textbook) | 32 vs 32 | 30 | 99.4% |

Two differences had to be reproduced, both of which move flip points:

- **`use_close`** — TradingView takes extremes from `highest(close)`/`lowest(close)`,
  not `highest(high)`/`lowest(low)`. This dominates: the difference between
  92.5% and 100% agreement, worth ~10 extra flips per 690 bars.
- **Ratchet gating** — TradingView gates on `close[1]` vs the previous stop and
  never resets the inactive side. Also `nz(stop[1], stop)`: on the first
  computable bar the "previous" stop falls back to the current one, so a
  direction is chosen immediately rather than holding the `+1` seed.

Set `use_close=False, tv_ratchet=False` for the textbook definition.
`test_chandelier.py` pins that variant; `test_tradingview_parity.py` pins the
TradingView one.

**Prices still differ by venue.** Deriv's `frxXAUUSD` and OANDA's `XAUUSD` are
different feeds — roughly 0.02% apart, with different candle boundaries. Signals
near a threshold can land on different bars. Compare against Deriv data, not
OANDA, when checking this app.

---

## Indicators

Toggleable from the side panel, TradingView-style — an eye control per indicator
plus inline parameters.

| Indicator | Pane | Role |
|---|---|---|
| Chandelier Exit | price | **signal source** — drives auto execution |
| EMA | price | display |
| Bollinger Bands | price | display |
| RSI | own pane | display |
| MACD | own pane | display |

Chandelier can be hidden from the chart but never switched off: auto mode trades
from it, and it stays the single signal authority so the audit log is never
ambiguous about which indicator fired an order.

**Each oscillator gets its own pane and its own price scale.** Sharing one pane
would put RSI (0–100) and MACD (around 0) on a single scale and crush the smaller
into a flat line. Panes are time-synced in both directions, with the time axis on
the bottom pane only. Hidden indicators are not computed at all.

---

## Chart

### Readout

The legend follows the crosshair: timestamp, O/H/L/C, change, and the Chandelier
stop **at the hovered bar**. With no cursor it falls back to the last bar, so it
is never blank. Crosshair is in magnet mode and labels both axes.

### Timezone

Display defaults to **IST** (UTC+05:30), with a toggle in the top bar. Every
rendered timestamp carries its zone label, so a screenshot can never be misread
against a log line. Everything persisted — audit log, bar epochs, idempotency
keys — stays **UTC**. IST has no DST, so a fixed offset is exact.

Intraday tick marks always show the clock, with the date at each midnight
boundary. The default formatter drops the time entirely once a view spans several
days, which is useless on a 24/7 instrument.

### Colours

| Element | Colour | Why |
|---|---|---|
| Up candle | `#17b98a` | teal-green |
| Down candle | body `#A8121E`, edge `#D6202E` | blood red |
| BUY marker | `#7CFF2E` parrot green + `B` | |
| SELL marker | `#FF8A3D` orange + `S` | |

A true blood red (`#8B0000`) manages only **2.0x** contrast on this near-black
ground, so a one-pixel doji body disappears. A deep body with a brighter edge
keeps the character while thin candles and long wicks stay legible.

Markers deliberately do not reuse the candle palette — not even a brighter shade.
The failure is structural: a BUY fires at the *start* of an uptrend, so a green
marker lands exactly where the green candles begin. Parrot green works because
the candle green is **teal** (hue 163°) while parrot green is **yellow-green**
(~98°): 65° of hue separation and 1.94x the relative luminance. Cyan — the
obvious "not green" choice — is only 24° away and carries contrast on brightness
alone.

Direction is carried three other ways — arrow shape, above/below placement, and
the B/S letter — so nothing depends on remembering which colour means which.

Both marker constants are at the top of `frontend/src/components/Chart.tsx`
(`MARK_BUY`, `MARK_SELL`). Any pair works provided neither sits in the candle
green/red hue family.

---

## Trading

### Manual mode

Signals are logged and marked on the chart but never executed. BUY/SELL buttons
place orders at the manual profile's size.

**One-click signal trade.** When Chandelier flips, a small chip appears anchored
to the bar **after** the signal bar — the signal fires at bar close, so the next
bar is the first one you could act on. Clicking places an order in the signal's
direction; ✕ dismisses. It only appears for the chart on screen, only in manual
mode, and never while the kill switch is engaged. It goes through the same
`/api/order` path as the buttons, so every risk check still applies.

### Audio alerts

Toggle in the top bar (`♪`), persisted. Tones are synthesised with Web Audio — no
asset files, nothing to load.

| Event | Sound |
|---|---|
| BUY signal | rising pair, 587 → 880 Hz |
| SELL signal | falling pair, 587 → 392 Hz |
| Order filled | short high blip |
| Order **rejected** | low sawtooth buzz |
| Critical alert | three urgent square pulses |

Rising vs falling means you can tell buy from sell without looking. Signals sound
for the chart you are watching **and always for the armed series**, even if you
navigate away — that is the one placing orders.

Browsers refuse audio until a real gesture, so the context starts suspended and
unlocks on your first click. Until then the icon shows amber (`♪!`) rather than
pretending to be armed. Clicking the amber icon unlocks it rather than switching
it off.

### AUTO mode

Armed, a Chandelier direction flip on a **closed bar** submits an order with no
further confirmation. Manual entry is disabled while armed.

**It trades only the symbol + timeframe you armed on.** Every chart you visit
stays subscribed and keeps producing signals, so an unscoped bot would trade
instruments and timeframes you merely browsed past. Signals from any other series
are logged and ignored. The armed series is shown in the arm dialog and the
armed rail.

"Automatic" means *submitted*, not *guaranteed filled* — every auto order still
passes the full risk guard.

Auto is dropped, and the binding cleared, on feed loss, kill switch, and every
restart.

---

## Safety model

The frontend renders limits; the **backend enforces them**.

- **Staleness is per symbol, measured on the newest BAR** — not a global clock
  and not "did a reply arrive". A 24/7 instrument ticking every second must not
  vouch for a closed forex market, and a poller keeps getting replies for a shut
  market that simply carry the same stale bars. A forming bar is legitimately up
  to `granularity` seconds old, so that is subtracted before judging.
- Rejects on: kill switch · broker down · stale data · bad or oversized lots ·
  max concurrent positions · max trades/day · daily loss · hard caps · duplicate
  signal · auto order while not armed.
- **Idempotency** keyed on `(symbol, timeframe, bar_epoch, direction)` — one
  order per signal bar however many times it is re-delivered.
- **Auto mode never survives a restart.** Boot is always Manual.
- **Feed loss disarms auto** and raises a critical alert.
- **Kill switch** closes everything and forces Manual — `Ctrl+Shift+K`.
- Append-only SQLite audit log of every signal and every order attempt, accepted
  or rejected.
- Auto and manual keep **separate** config profiles, both fully editable.

Side panel sections (Indicators / Chandelier State / Execution) are collapsible
with persisted state. Execution is **force-opened when AUTO is armed**, so the
parameters that just went live can never sit behind a collapsed header.

---

## Going live

```bash
python backend/doctor.py
```

Read-only, never places an order. Reports: token validity, **DEMO vs REAL**,
whether the `trade` scope is present, whether Step Index is tradable from your
network, which contract types and multipliers are offered, and what a real order
would cost.

Run it before switching `BROKER` away from `paper`, and again whenever orders
start failing.

### Credentials

| You have | Set | You can trade |
|---|---|---|
| Deriv API token | `BROKER=deriv` | **contracts** — priced in stake |
| MT5 login + terminal | `BROKER=mt5` | **lots** (Windows, native) |
| nothing | `BROKER=paper` | paper, full loop |

Deriv token format: **~15 alphanumeric characters, no prefix**. A long `pat_…`
token is from a different service and Deriv rejects it with `InvalidToken`.
Create it at app.deriv.com → Settings → API token, with `read` **and** `trade`
scopes, while your **demo (VRTC…)** account is selected.

A Deriv token is bound to one account, so a demo token *cannot* reach the real
account whatever the app does — a stronger guarantee than any config flag.
`doctor.py` prints which one you have.

---

## Tests

```bash
.venv/bin/python -m pytest backend/tests -q      # 87 tests
```

The Chandelier and risk suites were **mutation-tested**. The first version of the
ratchet test passed even with the ratchet deleted, because the fixture's raw
stops happened to rise monotonically. `chandelier_ratchet.csv` and
`chandelier_short_side.csv` exist specifically to discriminate that case.

Covered: ATR seeding · gap-aware True Range · both ratchets · direction read off
the previous bar · signal-only-on-flip · **mid-bar excursion produces no
signal** · TradingView parity · every risk rejection path · idempotency including
a concurrent race · reconnect reconciliation without gaps or duplicates ·
auto-disarm on feed loss · auto trades only the armed series · per-symbol
staleness · all display indicators.

---

## Layout

```
backend/
  app/
    main.py           FastAPI app, routes, order submission
    feed.py           Deriv WS: history, subscriptions, reconnect, polling
    series.py         candle series + closed-bar detection
    chart_service.py  series + indicators -> signals
    risk.py           the authoritative risk guard
    store.py          append-only SQLite audit log
    brokers/          paper | mt5 | deriv, behind one protocol
    indicators/       chandelier (signal) + overlays (display)
  tests/              87 tests incl. mutation-tested suites
  doctor.py           read-only preflight check
frontend/
  src/
    components/       Chart, TopBar, SidePanel, BottomPanel, …
    store.ts          zustand + WebSocket client
    sound.ts          Web Audio alerts
    tz.ts             IST/UTC display
docs/                 Step Index domain research + verified API facts
src/                  standalone research scripts (backtests, tick stats)
```

---

## Status

1. Backend + Deriv feed + `/api/candles` + `/stream` — real candles verified
2. React shell + lightweight-charts + symbol/timeframe switching
3. Chandelier engine + tests against a hand-checked fixture
4. Signals on closed bars, rendered as chart markers
5. `PaperBroker` + positions + manual BUY/SELL
6. Risk guard + kill switch + audit log
7. **Auto mode — wired and armable; needs a multi-day paper run**
8. `MT5Broker` — written, untestable on Linux
9. Live

Step 7 is the gate: run auto on paper for several days and reconcile every logged
signal against the chart before going near step 8.

One thing the data already suggests: at Chandelier(22, 3.0) on 1m, Step Index
flipped **61 times in 1000 bars**. With `max_trades_per_day: 20` you would hit
the cap by mid-morning, each trade paying the spread. Choose the timeframe
deliberately rather than inheriting 1m.
