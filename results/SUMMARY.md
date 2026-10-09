# Step Index — Paper Trading Results

Data: **1,004,987 real `stpRNG` ticks**, 2026-08-31 16:23 → 2026-09-12 07:33 UTC
(11.63 days), pulled live from Deriv's API. Contract model: plain `CALL`/`PUT`
Rise/Fall, tie counts as loss, trades forced non-overlapping.

---

## Verdict

**69 backtests (23 strategies × 3 hold durations). Zero survived correction.**

```
MULTIPLE COMPARISONS: 69 strategy x hold combinations tested.
Bonferroni-corrected alpha for 0.05 family-wise = 0.000725
Results surviving Bonferroni correction: 0
```

No indicator beat a coin flip. Not one.

## Why the result is trustworthy

**Statistical power.** Individual strategies ran up to 240,198 non-overlapping
trades. At n = 240k the detectable effect at 80% power is ~0.29%. To break even
at a 1.95x payout you need a **1.28%** edge over 50%. We had roughly **4x more
power than required** to detect a merely break-even strategy. Nothing appeared.

**The inverse-pair signature.** Every strategy and its exact opposite sum to
100.00%:

| Pair | Win % | Inverse | Win % |
|---|---:|---|---:|
| SMA 5/20 momentum | 50.02 | SMA 5/20 fade | 49.98 |
| RSI-14 reversal | 50.12 | RSI-14 momentum | 49.88 |
| Bollinger revert | 49.85 | Bollinger breakout | 50.15 |
| CCI-20 revert | 50.06 | CCI-20 momentum | 49.94 |
| Streak-3 fade | 50.15 | Streak-3 continue | 49.85 |

If an indicator carried information, one side would beat 50% *and* its mirror
would not track it exactly. This is what zero information looks like.

**The control arm.** A coin flip scored 50.06% / 50.09% / 50.02% across the
three hold periods — statistically indistinguishable from every indicator
tested. That single row is the entire finding.

## Generator tests (T1–T9) on the same 1M ticks

```
T1 step size     0 non-(+-0.1) moves out of 1,004,986        CLEAN
T2 bias          P(up)=0.499090  z=-1.83  p=0.068            PASS
T3 autocorr      5/54 lags outside band (expect 2.7)         flagged -> see below
T4 Ljung-Box     Q=61.8 vs crit 67.5  p=0.123                PASS
T5 runs          503,028 vs expected 502,492  p=0.285        PASS
T6 conditional   P(up | last 1..12 moves), all p > 0.10      PASS
T7 spectrum      max/mean 13.97 vs guide 16.1                PASS
T8 time-of-day   1440 minute buckets  p=0.439                PASS
T9 tick timing   99.9998% exactly 1s (2 gaps in 1M)          CLEAN
```

**T3 resolved by split-half replication:**

```
half A: 1 lag outside band  -> [23]
half B: 4 lags outside band -> [10, 24, 25, 34]
exceed in BOTH halves: NONE
same sign in both halves:  NONE
```

The flag did not reproduce out-of-sample. It was noise — which is exactly what
the replication gate is for.

**Effect size, even if it were real:** the largest autocorrelation in the full
sample is −0.002666 at lag 10. Best achievable win rate from exploiting it:
**50.13%**. Break-even at 1.95x needs **51.28%**. It is **9x too small** to
overcome the house edge, before considering that it isn't real.

## What DOES change your expected cost

Nothing on a chart. Two things, both structural:

### 1. Odd vs even tick durations

Every tick moves exactly ±0.1 (verified: 1,004,986 of 1,004,986 moves). So exit
can equal entry only when ups and downs cancel — which requires an **even** tick
count. A tie is a **loss** on plain Rise/Fall.

| N ticks | P(win) | Fair payout | House edge @1.95x |
|---:|---:|---:|---:|
| 1, 3, 5, 7, 9 (odd) | 0.50000 | 2.00x | **2.50%** |
| 2 | 0.25000 | 4.00x | **51.25%** |
| 4 | 0.31250 | 3.20x | **39.06%** |
| 6 | 0.34375 | 2.91x | **32.97%** |
| 8 | 0.36328 | 2.75x | **29.16%** |
| 10 | 0.37695 | 2.65x | **26.49%** |

**Trade odd durations. Never even.** Up to 20x difference in cost for the same
click. This is the single most valuable line in this document.

### 2. Only Ups / Only Downs is a trap

`RUNHIGH`/`RUNLOW` is exactly `0.5^N`:

| N | P(win) | Fair payout |
|---:|---:|---:|
| 3 | 0.125 | 8x |
| 5 | 0.03125 | **32x** |
| 7 | 0.0078 | **128x** |

## The one thing still unmeasured

Deriv blocks `proposal` and `contracts_for` from this network
(`OfferingsValidationError`) — the same wall both research agents hit. Tick data
flows freely; trade offerings do not.

So the **quoted payout table** is unknown. If Deriv quotes a flat rate across
durations, the odd/even gap above is a live mispricing. If payouts scale with the
binomial table, it is correctly priced and dead.

`src/payouts.py` answers this from an unrestricted machine in about a minute,
no login required.

## Reproduce

```
python3 src/fetch_ticks.py 1000000 ticks.npz   # ~10 min, no auth
python3 src/randomness.py   ticks.npz          # T1-T9
python3 src/replicate.py    ticks.npz          # split-half gate
python3 src/backtest.py     ticks.npz          # 69 backtests
python3 src/fair_value.py                      # exact pricing, no data needed
python3 src/payouts.py                         # needs unrestricted IP
```

Raw ticks are held in the session scratchpad, not the repo — Deriv's ToS caps
feed caching at 24 hours. Only aggregates and results are kept here.
