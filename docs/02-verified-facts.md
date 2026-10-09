# Deriv API — Verified Facts (research pass 1)

Source: deep research pass against Deriv primary docs, raw JSON schemas in
`deriv-com/deriv-api-docs`, live API probing, and both official SDK issue trackers.
Confidence labels are the researcher's, carried through unchanged.

---

## Connection & limits  [VERIFIED]

| Item | Value |
|---|---|
| WebSocket endpoint | `wss://ws.derivws.com/websockets/v3?app_id={app_id}` |
| Public test app_id | `1089` (shared, rate-limited, not for production) |
| Idle timeout | **2 minutes** — must send `{"ping":1}` to hold the connection |
| Rate limit, general calls | 220/min, 14,400/hr |
| Rate limit, `proposal` / `proposal_open_contract` | 80/min, 3,600/hr |
| Rate limit, `portfolio` / `statement` | 30/min, 1,500/hr |
| Max concurrent `proposal` subscriptions | **5** |
| Reconnection | No session resume. A closed socket cannot be reused — new connection, re-`authorize`, re-subscribe. |

Limits are not fixed in prose docs; query `website_status` → `api_call_limits` at
runtime. The numbers above were read live.

## Step Index mechanics

| Item | Value | Confidence |
|---|---|---|
| Step size, classic | **0.1 per tick** | VERIFIED (2 independent sources) |
| Step 200/300/400/500 | 0.2 / 0.3 / 0.4 / 0.5 | VERIFIED (Deriv Academy) |
| Direction probability | **50/50, no drift**, CSPRNG-generated | VERIFIED (2 sources) |
| **Tick interval (seconds)** | **not found in any source** | **UNCONFIRMED** |
| Symbol code `STPRNG` / `stpRNG` | community repo only, no official doc | **UNCONFIRMED** |
| Market hours | 24/7 | INFERRED (consistent across sources) |
| Min stake | 0.35 USD (currency-dependent) | VERIFIED (2 sources) |
| Max payout | 50,000 | VERIFIED |

The researcher's live probe returned `OfferingsInvalidSymbol` for *every* symbol,
including known-good `R_100` — its egress IP is blocked (datacenter range). So
the symbol code and per-symbol contract list **must be confirmed from your own
machine**. See `03-live-probe.md`.

## Contract types

Platform-wide `contract_type` enum, read from the raw schema
(`config/v3/buy/send.json`) — this is the full list across all symbols, **not**
filtered to Step Index:

```
ACCU, ASIAND, ASIANU, CALL, CALLE, CALLSPREAD, DIGITDIFF, DIGITEVEN,
DIGITMATCH, DIGITODD, DIGITOVER, DIGITUNDER, EXPIRYMISS, EXPIRYMISSE,
EXPIRYRANGE, EXPIRYRANGEE, LBFLOATCALL, LBFLOATPUT, LBHIGHLOW, MULTDOWN,
MULTUP, NOTOUCH, ONETOUCH, PUT, PUTE, PUTSPREAD, RANGE, RESETCALL,
RESETPUT, RUNHIGH, RUNLOW, SNOWDOWN, SNOWUP, TICKHIGH, TICKLOW,
TURBOSLONG, TURBOSSHORT, UPORDOWN, VANILLALONGCALL, VANILLALONGPUT
```

**`CALLE` and `PUTE` exist.** These are Rise/Fall *Equals* — exit == entry wins.
Hypothesis H3 in `01-step-index-domain.md` §3.1 is live, pending confirmation
that they are enabled on Step Index specifically. Note `EXPIRYMISSE` /
`EXPIRYRANGEE` are the equivalent tie-inclusive variants for range contracts.

`duration_unit` enum: `d, m, s, h, t` (`t` = ticks).

**Multipliers**: `MULTUP`/`MULTDOWN` take a `limit_order` object (`stop_loss`,
`take_profit`) and a separate `cancellation` field. Numeric multiplier values and
commission rates for Step Index: UNCONFIRMED.

**Accumulators**: `ACCU` uses a `growth_rate` field (not a barrier). Growth-rate
values for Step Index: UNCONFIRMED.

## Data access

`ticks_history` — `count` defaults to 1,000. `style`: `ticks` | `candles`.
`granularity` (candles only) is a fixed enum in seconds:
60/120/180/300/600/900/1800/3600/7200/14400/28800/86400. No arbitrary
granularity. `subscribe:1` streams as new data forms.

`ticks`, `ticks_history`, `proposal`, `contracts_for` are all `auth_required: 0`
— **tick collection and pricing research need no login at all**, only an app_id.
Only `buy`, `sell`, `portfolio`, `balance`, `transaction` require `authorize`.

## ToS constraints  [VERIFIED — read directly from the ToS page]

From <https://deriv.com/terms-and-conditions/api-users>:

- **Feed/content caching is capped at 24 hours.** You may not indefinitely store
  historical ticks pulled via the API. *This directly constrains the Phase 1
  data-collection design — see `01-step-index-domain.md` §4.*
- You are responsible for all activity from your API keys, and must maintain
  "pre-trade and post-trade controls, testing, monitoring, supervision, rate
  limits, kill switches, error controls, and risk limits."
- Malfunctioning bots must be disabled promptly.
- Deriv can demand documentation of your automated system with 5 business days
  to respond; failure risks suspension.
- **Written records of pre-deployment testing and control settings must be kept
  12 months minimum.**
- API access can be terminated at any time, for any or no reason.

## SDK health  [VERIFIED via GitHub API]

| SDK | Stars | Last commit | Archived | Open issues |
|---|---|---|---|---|
| `python-deriv-api` (official) | 38 | 2024-12-03 | **YES** | 9 |
| `@deriv/deriv-api` (official, JS) | 77 | 2026-08-20 | No | 22 |

The official Python SDK is **archived** — unmaintained, bugs will not be fixed
upstream. The JS SDK's recent commits are Dependabot bumps only.

Recurring open bugs in **both** SDKs cluster on one theme: connection lifecycle.
Reconnection not automatic (`python-deriv-api#20`, `deriv-api#46`), connections
closing/hanging (`#16`, `#70`), buy calls hanging (`#36`), contract subscriptions
not updating (`#135`).

**Implication:** do not depend on either SDK's connection management. The
WebSocket protocol here is simple JSON; talk to it directly (`websockets` in
Python) and own the ping/reconnect/re-subscribe loop. That loop is the part
everyone gets wrong, including the vendor.

No documented server-side duplicate-buy protection or proposal-expiry semantics
were found — **build idempotency yourself**, don't assume the server dedupes.

## Prior art

Most GitHub "Deriv bots" are DBot visual XML strategy collections, not code.
No well-maintained, SDK-based, Step-Index-specific bot above ~100 stars exists.
One developer ([elkd/deriv](https://github.com/elkd/deriv)) automates the Deriv
*web UI via Playwright* specifically to dodge the WebSocket reliability
problems — a telling trade-off.

## Geographic restrictions  [UNCONFIRMED — secondary sources only]

Reported restricted: US, UK, Canada, UAE, Singapore, Hong Kong, Malaysia, others.
"Hybrid and Skewed Step Indices" reported unavailable to EU clients. Triangulated
from three broker-review sites that agree; no primary Deriv compliance page found.

---

# Research pass 2 — LIVE API VERIFIED

Second agent reached Deriv's production API (`wss://ws.derivws.com`, app_id=1089,
**no auth token**) and measured these directly. This supersedes the
`[UNCONFIRMED]` rows above.

| Fact | Value | How |
|---|---|---|
| Symbol code | **`stpRNG`** | live `ticks_history` returned real data |
| Variants | `stpRNG2`/`3`/`4`/`5` = step 0.2/0.3/0.4/0.5 | all five returned live prices |
| Step size | **exactly ±0.1**, absolute (not %) | **499/499** consecutive diffs were ±0.1, zero exceptions |
| Tick interval | **exactly 1 second** | **499/499** consecutive timestamp diffs = 1 |
| Flat ticks / multi-step ticks | **none observed** | 0 zero-diffs, 0 diffs >0.1 magnitude in 499 obs |
| `ticks_history` max count | **5,000** (hard cap) | count=5001/10000/20000 all returned exactly 5000 |
| History depth | **~365 days** | binary search on the boundary |
| **Silent fallback past 365d** | **366+ days returns LATEST ticks, no error** | binary search |
| Auth for `ticks_history` | **not required** | streamed live data with app_id only |
| Symbol lookup | case-insensitive | `STPRNG2` == `stpRNG2` |
| Rate limits | 220/min general, 80/min pricing, 30/min outcome, 5 concurrent proposal subs | live `website_status` |

Deriv's own field name in that response is `max_requestes_general` — typo theirs,
quoted verbatim, don't "fix" it when parsing.

## Sanity check on fairness (underpowered, disclosed as such)

500-tick sample: **266 up / 233 down** (n=499 diffs). Under a fair 50/50 null,
expected 249.5, sd ≈ 11.2 → **z ≈ 1.48, p ≈ 0.14, not significant**.

Consistent with a fair process. Far too small to conclude anything — which is
exactly why Phase 1 targets 31.5M.

## Nobody has done this before

The researcher searched GitHub, Reddit, Deriv's community forum and trading
forums for **any** rigorous statistical test of Step Index — runs test,
chi-square, autocorrelation. **None exists.** What's out there is anecdote
("supposed to crash every 25 minutes, went 120 minutes") with no methodology,
plus rebuttals citing eCOGRA/iTech Labs with no certificate linked.

Deriv's own article claims third-party RNG audits but **names no auditor and
links no report** — treat the specific-auditor claims as unsubstantiated.

So Phase 1 is not a formality. A properly powered, pre-registered test of this
instrument appears to be genuinely novel work, and it is cheap.

## Contract availability on Step Index — narrowed

| Contract | Status |
|---|---|
| `CALL` / `PUT` (Rise/Fall) | available (consensus, not live-confirmed) |
| `CALLE` / `PUTE` (Allow equals) | exist in API enum; **symbol-level enablement UNVERIFIED** |
| `RUNHIGH` / `RUNLOW` (Only Ups/Downs) | consensus: available |
| `MULTUP` / `MULTDOWN` | consensus: available |
| Deal cancellation on Multipliers | **not available on Step Index** (volatility indices only) |
| `ACCU` (Accumulators) | **likely NOT available** — Deriv's help text scopes them to volatility indices |

Accumulators drop out of pricing scope unless a live `contracts_for` says
otherwise. Deal cancellation drops out too.

**"Allow equals"** is confirmed as a real Deriv feature described as letting you
"earn a potential payout when the entry spot equals the exit spot." Its existence
as an opt-in implies plain `CALL`/`PUT` lose on a tie. Corroborated across
secondary sources; no single Deriv sentence saying "tie = loss" was found.

## Still blocked: payouts

Both research agents were IP-blocked on `active_symbols`, `contracts_for`, and
`proposal` — `OfferingsInvalidSymbol` / `OfferingsValidationError` for every
symbol including `R_100`, from datacenter egress. `ticks_history` and
`website_status` worked fine on the same connection.

So: **tick data is reachable from anywhere; payout quotes are not.** The
odd/even payout table (§3.1 H2/H3) can only come from your machine.
