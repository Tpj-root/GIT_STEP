"""Backtest Rise/Fall contracts on stpRNG driven by classical indicators.

Contract model (plain CALL/PUT, 'Allow equals' OFF):
  enter at tick i with direction d in {+1,-1}, settle at tick i+N
  WIN  if sign(P[i+N] - P[i]) == d
  LOSS otherwise, INCLUDING an exact tie (P[i+N] == P[i])

Trades are forced NON-OVERLAPPING (cooldown = N ticks after entry). Overlapping
trades share ticks, are positively correlated, and inflate significance.
"""
import sys, math
import numpy as np
from math import comb
from scipy import stats
sys.path.insert(0, "src")
import indicators as I


# ---------------------------------------------------------------- theory
def theoretical_win_prob(N):
    """P(price strictly higher after N fixed +-1 steps), tie counts as loss."""
    p_tie = comb(N, N//2) / 2**N if N % 2 == 0 else 0.0
    return (1.0 - p_tie) / 2.0, p_tie


# ---------------------------------------------------------------- strategies
def build_strategies(p):
    S = {}
    def add(name, sig): S[name] = sig

    f, s = I.sma(p, 5), I.sma(p, 20)
    x = np.sign(f - s)
    cross = np.zeros_like(x); cross[1:] = np.where(x[1:] != x[:-1], x[1:], 0)
    add("SMA 5/20 crossover (momentum)",  cross)
    add("SMA 5/20 crossover (fade)",     -cross)

    fe, se = I.ema(p, 12), I.ema(p, 26)
    xe = np.sign(fe - se)
    ce = np.zeros_like(xe); ce[1:] = np.where(xe[1:] != xe[:-1], xe[1:], 0)
    add("EMA 12/26 crossover (momentum)", ce)

    r = I.rsi(p, 14)
    add("RSI-14 reversal (<30 buy, >70 sell)",
        np.where(r < 30, 1, np.where(r > 70, -1, 0)))
    add("RSI-14 momentum  (>70 buy, <30 sell)",
        np.where(r > 70, 1, np.where(r < 30, -1, 0)))
    add("RSI-14 extreme   (<20 buy, >80 sell)",
        np.where(r < 20, 1, np.where(r > 80, -1, 0)))

    _, _, hist = I.macd(p)
    hx = np.sign(hist)
    hc = np.zeros_like(hx); hc[1:] = np.where(hx[1:] != hx[:-1], hx[1:], 0)
    add("MACD histogram zero-cross", hc)

    m, up, lo = I.bollinger(p, 20, 2.0)
    add("Bollinger 20/2 revert", np.where(p <= lo, 1, np.where(p >= up, -1, 0)))
    add("Bollinger 20/2 breakout", np.where(p >= up, 1, np.where(p <= lo, -1, 0)))

    k, d = I.stochastic(p, 14, 3)
    add("Stochastic 14 revert", np.where(k < 20, 1, np.where(k > 80, -1, 0)))

    w = I.williams_r(p, 14)
    add("Williams %R-14 revert", np.where(w < -80, 1, np.where(w > -20, -1, 0)))

    c = I.cci(p, 20)
    add("CCI-20 revert",   np.where(c < -100, 1, np.where(c > 100, -1, 0)))
    add("CCI-20 momentum", np.where(c > 100, 1, np.where(c < -100, -1, 0)))

    z = I.zscore(p, 50)
    zz = np.nan_to_num(z)
    add("Z-score-50 revert (|z|>2)", np.where(zz < -2, 1, np.where(zz > 2, -1, 0)))

    hi, lonn = I.donchian(p, 20)
    add("Donchian-20 breakout", np.where(p >= hi, 1, np.where(p <= lonn, -1, 0)))

    st = I.streak(p)
    for kk in (3, 5, 7):
        add(f"Streak-{kk} reversal (after {kk} same, fade)",
            np.where(st <= -kk, 1, np.where(st >= kk, -1, 0)))
        add(f"Streak-{kk} continuation",
            np.where(st >= kk, 1, np.where(st <= -kk, -1, 0)))

    add("ALWAYS RISE (baseline)", np.ones(len(p)))
    rng = np.random.default_rng(20260912)
    add("RANDOM CONTROL (coin flip)", rng.choice([-1, 1], len(p)))
    return S


# ---------------------------------------------------------------- engine
def run(prices, signal, N, warmup=200):
    idx = np.flatnonzero(signal != 0)
    idx = idx[(idx >= warmup) & (idx + N < len(prices))]
    if len(idx) == 0:
        return 0, 0, 0
    wins = ties = n = 0
    last = -10**9
    for i in idx:
        if i < last + N:            # enforce non-overlap
            continue
        last = i
        d = signal[i]
        move = prices[i+N] - prices[i]
        n += 1
        if move == 0:   ties += 1
        elif np.sign(move) == np.sign(d): wins += 1
    return n, wins, ties


def wilson(k, n, z=1.96):
    if n == 0: return (0.0, 0.0)
    ph = k/n; d = 1 + z*z/n
    c = (ph + z*z/(2*n))/d
    h = z*math.sqrt(ph*(1-ph)/n + z*z/(4*n*n))/d
    return (c-h, c+h)


def main(path, holds=(3, 5, 7), payout=1.95):
    z = np.load(path)
    P = z["prices"].astype(np.float64)
    T = z["times"]
    print(f"loaded {len(P):,} ticks  "
          f"({(T[-1]-T[0])/86400:.2f} days)\n")

    strategies = build_strategies(P)
    rows = []
    for N in holds:
        p_theory, p_tie = theoretical_win_prob(N)
        print("="*104)
        print(f"HOLD = {N} ticks   |   theoretical P(win) = {p_theory:.5f}   "
              f"P(exact tie) = {p_tie:.5f}   |   payout {payout}x")
        print("="*104)
        print(f"{'strategy':<44}{'trades':>8}{'win%':>9}{'95% CI':>17}"
              f"{'vs theory':>11}{'EV/trade':>10}")
        print("-"*104)
        for name, sig in strategies.items():
            n, w, t = run(P, sig, N)
            if n < 30:
                print(f"{name:<44}{n:>8}   (too few trades)"); continue
            wr = w/n
            lo, hi = wilson(w, n)
            pv = stats.binomtest(w, n, p_theory).pvalue
            ev = wr*payout - 1.0
            rows.append((N, name, n, w, t, wr, pv, ev))
            star = "***" if pv < 0.001 else "**" if pv < 0.01 else "*" if pv < 0.05 else ""
            print(f"{name:<44}{n:>8}{wr*100:>8.2f}%"
                  f"{'['+format(lo*100,'.2f')+','+format(hi*100,'.2f')+']':>17}"
                  f"{'p='+format(pv,'.3f'):>11}{ev*100:>9.2f}% {star}")
        print()
    return rows, len(strategies)*len(holds)


if __name__ == "__main__":
    rows, ncomp = main(sys.argv[1])
    print("="*104)
    print(f"MULTIPLE COMPARISONS: {ncomp} strategy x hold combinations tested.")
    print(f"Bonferroni-corrected alpha for 0.05 family-wise = {0.05/ncomp:.6f}")
    sig = [r for r in rows if r[6] < 0.05/ncomp]
    print(f"Results surviving Bonferroni correction: {len(sig)}")
    for r in sig:
        print(f"   HOLD={r[0]}  {r[1]}  n={r[2]}  win={r[5]*100:.2f}%  p={r[6]:.2e}")
    if not sig:
        print("   (none)")
