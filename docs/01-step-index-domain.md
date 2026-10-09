# Step Index — Domain Model & Trading Plan

Status: DRAFT v1. Numbers marked `[VERIFY]` are pending confirmation from Deriv's
primary docs. Everything marked `[MATH]` is derived and does not need verification —
it follows from the stated generating process.

---

## 0. The single fact that determines everything else

Step Index is **not a market**. There is no order book, no participants, no news,
no supply and demand. It is a number sequence produced by Deriv's own random
number generator, and Deriv publishes the generating rule:

> Each tick moves a **fixed step of 0.1**, with **equal probability** of moving
> up or down. `[VERIFY exact wording + step size]`

Everything in this plan follows from taking that sentence seriously. If the
sentence is true, a large class of strategies is *provably* worthless — not
"usually loses", but mathematically zero-edge. If the sentence is false, that
falsehood is the only place an edge can live.

So the plan is built around one question: **is the stated process the real
process?** Everything else is downstream.

---

## 1. Formal model

Let `S_n` be the price after `n` ticks.

    S_n = S_0 + d * sum(X_1 .. X_n)

    where X_i = +1 or -1, each with probability 1/2, independent
    and d = 0.1  [VERIFY]

This is a **symmetric simple random walk**. Three properties matter:

**(a) It is a martingale.** `E[S_{n+k} | everything known at time n] = S_n`.
The best possible forecast of any future price is the current price. Not
approximately — exactly.

**(b) Increments are independent.** `X_{n+1}` is independent of `X_1..X_n`.
Nothing in the history carries information about the next tick.

**(c) The state space is a lattice.** Price can only ever sit on `S_0 + 0.1*k`
for integer `k`. This is unusual and it has real consequences — see §3.

---

## 2. What follows immediately: why indicators cannot work

Every technical indicator — RSI, MACD, moving averages, Bollinger Bands,
stochastics, support/resistance, candlestick patterns, Elliott waves, every
one of them — is a **function of past prices**. Write any such indicator as
`f(X_1, ..., X_n)`.

By property (b), `X_{n+1}` is independent of `X_1..X_n`. Therefore it is
independent of *any* function of them:

    Corr( f(X_1..X_n), X_{n+1} ) = 0    for every measurable f   [MATH]

This is not "indicators are unreliable on synthetics" or "you need to combine
them". It is: the predictive correlation is exactly zero, for every indicator
that has ever been written and every one that ever will be, as long as (b)
holds. No amount of parameter tuning, confluence, multi-timeframe confirmation,
or machine learning changes a zero to a non-zero.

**The corollary is the useful part:** because the null is so sharp, any
indicator that *does* show consistent predictive power on real Step Index data
is evidence that (b) is false — i.e. it is a finding about the RNG, not about
the indicator. That makes indicator testing worthwhile, but as a *diagnostic*,
not as a strategy. See §4.

### What about mean reversion?

"Price always comes back" is true of a random walk — a 1-D symmetric random walk
is recurrent, it returns to every level with probability 1. This feels like an
edge and is not one, for two reasons:

1. The *expected time* to return is infinite. Guaranteed eventually, unbounded
   wait.
2. Deriv contracts have a fixed expiry. You do not get "eventually". You get N ticks.

Recurrence pays nothing when you are on a clock and paying a spread.

---

## 3. Where an edge could actually exist

Only three places. Ranked by how likely they are to be real.

### 3.1 Tie structure on even tick counts  [HIGHEST PRIORITY]

This is the one genuinely interesting structural feature, and it comes from
property (c) — the lattice.

On a fixed-step walk, after `N` ticks the price is **exactly** back at `S_0`
whenever ups and downs are equal. That requires `N` even. So:

- **N odd** → a tie is *impossible*. `P(up) = P(down) = 0.5` exactly.
- **N even** → a tie has substantial probability, and it eats into both sides.

`P(tie after N ticks) = C(N, N/2) / 2^N`  `[MATH]`

**This now rests on measurement, not on trusting Deriv's marketing copy.** The
±0.1 fixed step was verified live — 499 of 499 consecutive tick diffs were
exactly ±0.1, with zero flat ticks and zero multi-step ticks. Given that, "exit
spot == entry spot requires an equal number of ups and downs, which requires N
even" is arithmetic, not an assumption.

| N ticks | P(exact tie) | P(price higher) | P(price lower) |
|--------:|-------------:|----------------:|---------------:|
| 1  | 0       | 0.5000 | 0.5000 |
| 2  | 0.5000  | 0.2500 | 0.2500 |
| 3  | 0       | 0.5000 | 0.5000 |
| 4  | 0.3750  | 0.3125 | 0.3125 |
| 5  | 0       | 0.5000 | 0.5000 |
| 6  | 0.3125  | 0.3438 | 0.3438 |
| 8  | 0.2734  | 0.3633 | 0.3633 |
| 10 | 0.2461  | 0.3770 | 0.3770 |

Read that table again. **A 6-tick "Rise" contract wins 34.4% of the time. A
5-tick "Rise" contract wins 50% of the time.** On a normal asset (continuous
prices) ties are measure-zero and this gap does not exist. On Step Index it is
enormous.

This produces three concrete, falsifiable hypotheses:

- **H1**: Deriv treats an exact tie as a **loss** on Rise/Fall.
  → Then even-tick durations are catastrophically bad and must never be traded.
  Pure risk avoidance, worth knowing regardless.
- **H2**: Deriv's quoted payout is **the same or similar** for odd and even tick
  durations. → That is a genuine, exploitable mispricing on the odd side, or a
  trap on the even side. `[VERIFY — this is the key number to look up]`
- **H3**: Deriv offers `CALLE`/`PUTE` ("Rise/Fall Equals", tie **wins**) on Step
  Index. → Then at N=6, `P(win) = 0.3438 + 0.3125 = 0.6563`. If that contract is
  priced off a generic continuous-asset model, it is badly underpriced. `[VERIFY]`

My honest prior: Deriv's quants know this and the payouts already reflect it.
But it costs almost nothing to check, the check is unambiguous, and if H2 or H3
holds it is a real edge rather than a story. **This is experiment #1.**

### 3.2 The RNG is not what is documented

If ticks are not i.i.d. 50/50 — autocorrelation, periodicity, a drift, a
seed that resets, step sizes that are not always exactly 0.1 — there is an
edge. Testable cheaply and decisively. See §4.

Prior: low. Deriv is regulated and audits its RNG `[VERIFY the audit exists]`.
But "low prior, cheap test, decisive result" is exactly when you run the test.

### 3.3 Pricing inconsistency between contract types

Because the process is fully specified, the **exact** fair value of every
contract is computable in closed form — no simulation, no model risk. Rise/Fall
is binomial. Touch/No-Touch is the reflection principle. Accumulators are a
first-passage problem on a lattice. Range contracts are gambler's ruin.

If two contracts express the same event and imply different probabilities, that
is arbitrage. Worth a systematic sweep once the pricing library exists.

### 3.4 Where an edge does NOT exist — settle this now

- **Indicators of any kind.** §2. Zero, provably.
- **Martingale / recovery / grid systems.** These do not change expected value
  at all. They convert "lose a little, often" into "win a little often, lose
  everything rarely". Same negative EV, worse shape, and the stake cap and your
  bankroll guarantee the tail eventually arrives.
- **Stop-loss and take-profit placement on Multipliers.** By the optional
  stopping theorem, on a martingale no stopping rule changes the expected
  value. SL/TP reshape the P&L distribution; they cannot make a negative
  expectancy positive.
- **"Reading the chart".** There is nothing to read. The chart is noise with a
  known distribution.

---

## 4. Phase 1 — Verify the generator (do this before anything else)

Test the documented process. No trading, no money, no strategy.

### The plan just got ~500x faster  [LIVE-VERIFIED]

Original plan: stream live ticks for ~12 days to reach 1M observations. That is
now obsolete. Live probing established:

- Tick interval is **exactly 1 second** (499/499 consecutive timestamp diffs).
- `ticks_history` serves **~365 days** of history, **5,000 ticks per request**
  (hard cap), **no authentication** — `app_id` alone.
- Rate limit for `ticks_history` is **220 requests/minute**.

So the available history is:

    365 days × 86,400 ticks/day  ≈  31,500,000 ticks
    31,500,000 / 5,000            =  6,300 requests
    6,300 / 220 per minute        ≈  29 minutes

**Roughly 31.5 million ticks, retrievable in about half an hour, with no login.**
Not 1 million in twelve days. That is a ~30x larger sample in ~1/500th the time.

What that buys in statistical power — standard error on P(up) at n = 31.5M:

    se = sqrt(0.25 / 31.5e6) ≈ 0.000089

A 5-sigma detection threshold is a directional bias of **0.045%**. If Deriv's
RNG has any bias worth trading, or any serial correlation at the lags we test,
a sample this size finds it. If nothing shows up at n = 31.5M, the process is
clean to a precision far beyond anything exploitable after a house edge.

Live streaming still runs afterwards — but as **out-of-sample confirmation** of
anything the historical pass flags, not as the primary collection method. That
split is exactly what §4's replication requirement needs, and now it's free.

### Trap: silent fallback past 365 days  [LIVE-VERIFIED]

Requesting a window **366+ days back returns the latest ticks instead**, with
**no error raised**. A backfill loop that walks backwards past the boundary will
silently start re-ingesting recent data and double-count it into the
accumulators, corrupting every statistic with no failure signal.

**Mandatory:** validate returned timestamps against the requested `start`/`end`
on *every* response, and hard-fail on mismatch. This is the single easiest way
to get a confidently wrong answer out of this entire project.

### Constraint: the 24-hour caching cap  [VERIFIED, ToS]

Deriv's API terms cap feed/content caching at **24 hours**. A 12-day raw tick
archive would breach that. So the collector must **never retain raw ticks beyond
24h** — and it doesn't need to.

Every test below is computable from **streaming sufficient statistics**. The
collector consumes each tick once, updates a set of accumulators, and discards
the tick. Total state is a few hundred KB regardless of how long it runs:

| Test | Sufficient statistic | Size |
|---|---|---|
| T1 step size | histogram of observed diffs | ~10 keys |
| T2 bias | up count, down count | 2 ints |
| T3 autocorrelation | running Σ Xₙ·Xₙ₊ₖ for k=1..500 | 500 ints |
| T4 Ljung–Box | derived from T3 | — |
| T5 runs | run-length histogram | ~64 keys |
| T6 conditional bias | 2^k counters, k=1..12 | 8,190 ints |
| T7 periodicity | FFT per 24h block, keep spectra only | small |
| T8 time-of-day | 1,440 minute-of-day counters | 1,440 ints |
| T9 tick timing | histogram of inter-tick gaps | ~100 keys |

This is strictly better engineering than a tick archive anyway: constant memory,
no storage growth, and the tests update continuously instead of in a batch at the
end. A rolling 24h raw buffer is kept only for spot-checking and debugging, and
is aged out on a hard timer.

Also per ToS: retain **written records of pre-deployment testing and control
settings for 12 months**. The accumulator snapshots and the pre-registered test
battery *are* those records — version them from day one.

### 4.0 The live probe — run this first, it takes minutes

The research pass could not confirm the symbol code, tick interval, per-symbol
contract list, or payout table, because its network egress is IP-blocked by
Deriv (every symbol query, including `R_100`, returned `OfferingsInvalidSymbol`).
**From your own machine these are all answerable in one short script.** No login,
no funding — `active_symbols`, `contracts_for`, `ticks`, and `proposal` are all
`auth_required: 0`; an `app_id` alone is enough.

One probe resolves nearly every open question in §9:

| Call | Resolves |
|---|---|
| `active_symbols` | the real Step Index symbol code(s), and which variants exist |
| `contracts_for` | **which contract types are actually enabled on Step Index** — critically, whether `CALLE`/`PUTE` are among them (H3), plus `ACCU` growth rates and multiplier values |
| `ticks` for 60s | the tick interval, and a first look at whether every move is exactly ±0.1 |
| `proposal` × N | **the payout table for tick durations 1..10** — the odd/even comparison that decides H1, H2, H3 |

That last row is the highest-value five minutes in this entire project. If the
quoted payout for 5 ticks and 6 ticks is the same or similar, §3.1 says one side
of that pair is badly mispriced. If the payouts differ by roughly the ratio the
binomial table predicts, Deriv has priced ties correctly, H2/H3 are dead, and we
have saved ourselves weeks.

Respect the limits while probing: 220 calls/min general, 80/min for `proposal`,
max 5 concurrent proposal subscriptions, and ping every <2 min or the socket
drops.

### Test battery

| # | Test | Null hypothesis | Method |
|---|------|-----------------|--------|
| T1 | Step size constancy | every move is exactly ±0.1 | tabulate all unique diffs; any diff ≠ ±0.1 is a headline finding |
| T2 | Directional bias | P(up) = 0.5 | binomial test on 1M ticks; detects bias ≥ 0.1% |
| T3 | Serial independence | corr(X_n, X_{n+k}) = 0 | autocorrelation, lags 1–500, with Bonferroni correction |
| T4 | Joint independence | no structure at any lag | Ljung–Box Q on the sign series |
| T5 | Runs | run lengths ~ Geometric(0.5) | Wald–Wolfowitz runs test |
| T6 | Conditional bias | P(up \| last k moves) = 0.5 | all 2^k histories for k = 1..12; chi-square |
| T7 | Periodicity | flat spectrum | FFT / periodogram on the sign series |
| T8 | Time-of-day effect | uniform across clock | bucket by UTC hour and minute; look for seed resets |
| T9 | Tick timing | intervals are regular | distribution of inter-tick gaps; gaps leak server behaviour |

**Multiple-comparisons discipline:** running nine tests at α=0.05 gives a ~37%
chance of at least one false positive. Pre-register the battery, correct for
multiplicity, and require any positive to **replicate on a fresh out-of-sample
block** before it is believed. One significant p-value is not a discovery.

### The decision gate

- **All tests pass** → the documented process is the real process. §2 applies in
  full. The only remaining work is §5 (measure the house edge precisely), and
  then an honest answer about whether to trade at all.
- **Any test fails and replicates** → that is the edge. Everything pivots to
  characterising and exploiting it.

This phase is cheap, fast, and it is the only part of the project whose outcome
is genuinely unknown. That is what makes it the right place to start.

---

## 5. Phase 2 — Price every contract exactly, and measure the house edge

Build a small pricing library. Not a trading system — a calculator.

For each contract type available on Step Index, implement the exact
probability under the random-walk model:

- **Rise/Fall (N ticks)** — binomial tail; the table in §3.1.
- **Rise/Fall Equals** — binomial tail plus the tie mass.
- **Higher/Lower (barrier b)** — binomial tail shifted to the lattice point
  nearest `b`. Note the barrier snapping: because price lives on a 0.1 grid,
  barriers between grid points behave identically to the grid point below.
  Another lattice artefact worth probing.
- **Touch / No-Touch** — reflection principle: `P(max_{n<=N} S_n >= S_0 + kd)`.
- **Stays In / Goes Out of range** — two-barrier gambler's ruin.
- **Accumulators** — first-passage out of a band; survival probability per tick
  raised to the tick count, with the exact band width in steps.
- **Multipliers** — EV is `-commission` under the martingale property; the whole
  question is the commission and spread. `[VERIFY the formula]`

Then, for every contract and every duration, compute:

    house_edge = 1 - P_true(win) * payout_multiplier

and tabulate it. **This deliverable is valuable whatever the outcome.** It tells
you exactly what you are paying, per contract, per duration — which is
information Deriv does not present directly and which almost no retail trader on
this instrument has.

If some cell in that table shows a **negative** house edge, that is a live edge
and Phase 3 begins. If every cell is positive — which is the likely outcome —
you have a precise, quantified answer to "can I make money here", and the
correct response is documented in §7.

---

## 6. Phase 3 — Paper trading protocol

Paper trading is **not** "try it and see if I'm up". It is a measurement
instrument, and it has to be designed like one.

### Sample size — the number most people get wrong

To detect an edge of size `δ` over a 50% baseline, at 95% confidence and 80%
power:

    n ≈ (1.96 + 0.84)^2 * 0.25 / δ^2      [MATH]

| True edge | Trades needed |
|-----------|--------------:|
| 10% (60% win rate) | ~196 |
| 5%  (55% win rate) | ~784 |
| 2%  (52% win rate) | ~4,900 |
| 1%  (51% win rate) | ~19,600 |

**So: 50 paper trades prove nothing. 200 paper trades prove nothing.** A
strategy that is up after 100 trades is indistinguishable from a coin that came
up heads 55 times. Any paper-trading run shorter than ~800 trades cannot
detect anything smaller than a 5% edge, and edges that large do not survive in a
regulated product.

This is why Phase 1 (tick statistics) comes first: 1M ticks gives vastly more
statistical power than 1,000 trades, because every tick is an observation
whereas every trade is a *bundle* of ticks collapsed into one bit.

### Protocol rules

1. **Pre-register.** Write the entry rule, exit rule, stake, contract type, and
   target sample size *before* the run. No mid-run changes; a changed rule
   starts a new run with a fresh counter.
2. **Log the quote, not just the outcome.** Every paper trade records: timestamp,
   entry tick, contract params, **Deriv's quoted payout at that moment**, the
   model's `P_true`, the implied edge, and the settlement. The quote is the part
   you cannot reconstruct later.
3. **Compare to the model, not to zero.** The question is never "did it make
   money" — it is "did the realised win rate match `P_true`?" A strategy that
   loses exactly as much as the model predicts is a *successful validation*.
   A strategy that wins more than `P_true` predicts is the interesting one.
4. **Track slippage explicitly.** Entry tick vs. the tick you actually got,
   latency, proposal-expiry rejections. On 1-tick-resolution contracts, one tick
   of latency is a material fraction of the contract.
5. **Run a null arm.** Alongside the real strategy, paper-trade a
   coin-flip strategy on the same ticks with the same stakes. If your strategy
   does not beat the random arm, it has no content. This single control kills
   most false discoveries.

---

## 7. Risk, sizing, and the honest answer

### Kelly on a negative-edge game

The Kelly criterion for a binary bet with win probability `p` and net odds `b`:

    f* = (p*b - (1-p)) / b     [MATH]

When the house edge is positive, `p*b < 1-p`, so **`f*` is negative**. The
mathematically optimal stake on every negative-EV contract is *zero*, or a
short position if one existed. There is no "correct" position size for a losing
game; there is only a rate of decay you choose.

### Risk of ruin

On a negative-EV game with repeated bets, ruin probability approaches 1 as the
number of bets grows, for any fixed bankroll. The only free variables are how
fast and how bumpy the path is. Martingale sizing (§3.4) makes the path smoother
and the ending sooner.

### The answer to "which indicator makes money"

If Phase 1 confirms the documented process: **none, and no combination of them.**
That is arithmetic, not pessimism, and it is worth far more than a strategy that
feels good for 40 trades. The honest framing of this instrument is that it is a
casino game with a published, computable house edge — which is genuinely
unusual and genuinely interesting, because **you can calculate the exact edge on
every bet**, something you cannot do in a real market.

What that is good for:
- Knowing precisely what each contract costs you, and picking the cheapest cell
  if you trade for entertainment.
- A clean, fully-specified testbed for building execution infrastructure,
  backtesting machinery, and risk systems — with zero model risk, because the
  data-generating process is known exactly.
- The Phase 1 result itself, which is a real empirical finding either way.

If Phase 1 finds a deviation, everything above is void and the project becomes
a genuine research programme. That is the outcome worth playing for, and it is
why Phase 1 comes first.

---

## 8. Decision gates

```
GATE 0  Verify Deriv's documented mechanics + tie handling + payout table
        -> if even/odd payouts are equal: investigate H2/H3 immediately

GATE 1  Collect 1M+ ticks, run the T1-T9 battery
        -> all pass: the process is as documented, proceed to GATE 2
        -> any replicated failure: STOP, pivot to characterising the deviation

GATE 2  Build exact pricer, tabulate house edge per contract x duration
        -> any negative-edge cell: validate in paper trading at required n
        -> all positive: report the edge table, and make an informed
           decision about whether to trade at all

GATE 3  Paper trade only pre-registered rules, with a random control arm,
        to the sample size the effect size demands

GATE 4  Real money only if a paper-traded edge survives out-of-sample
        at the required n. Demo-only until then, per your instruction.
```

Nothing before Gate 4 risks a cent.

---

## 9. Open questions for Deriv's docs  `[VERIFY]`

1. Exact symbol code(s) and whether Step 200/300/400/500 variants exist.
2. Exact step size and tick interval.
3. **Tie handling on Rise/Fall — loss, or refund?**
4. **Are `CALLE`/`PUTE` available on Step Index?**
5. **Quoted payout for odd vs even tick durations.** (The single most valuable number.)
6. Which contract types are actually offered on this symbol.
7. Accumulator barrier definition (absolute vs % of spot) and growth rates.
8. Multiplier commission formula.
9. Min/max stake.
10. `ticks_history` depth and rate limits, and whether streaming ticks needs auth.
