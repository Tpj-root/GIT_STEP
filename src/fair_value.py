"""Exact fair values for Step Index contracts.

Because the process is a symmetric +-1 step walk on a lattice, EVERY contract
has a closed-form / exact-DP probability. No simulation, no model risk.
Prices are in STEPS (1 step = 0.1 index points).
"""
import numpy as np
from math import comb

def _dist(N):
    """Exact distribution of position (in steps) after N ticks."""
    pos = np.arange(-N, N+1, 2)
    pr  = np.array([comb(N, (k+N)//2) for k in pos], dtype=float) / 2.0**N
    return pos, pr

def rise(N):
    pos, pr = _dist(N); return pr[pos > 0].sum()

def rise_equals(N):
    pos, pr = _dist(N); return pr[pos >= 0].sum()

def tie(N):
    pos, pr = _dist(N); return pr[pos == 0].sum()

def higher_than(N, k):
    pos, pr = _dist(N); return pr[pos > k].sum()

def _dp(N, lo=None, hi=None, absorb=False):
    """DP over the lattice. lo/hi are barriers in steps.
    absorb=True -> returns P(absorbed by either barrier within N ticks)."""
    span = N + 2
    cur = np.zeros(2*span+1); cur[span] = 1.0
    absorbed = 0.0
    for _ in range(N):
        nxt = np.zeros_like(cur)
        nxt[1:]  += 0.5*cur[:-1]
        nxt[:-1] += 0.5*cur[1:]
        if lo is not None:
            i = span + lo
            if 0 <= i < len(nxt): absorbed += nxt[:i+1].sum(); nxt[:i+1] = 0.0
        if hi is not None:
            j = span + hi
            if 0 <= j < len(nxt): absorbed += nxt[j:].sum(); nxt[j:] = 0.0
        cur = nxt
    return absorbed if absorb else cur.sum()

def one_touch(N, k):
    """P(price touches +k steps (or -k) at any point within N ticks)."""
    return _dp(N, lo=-abs(k), hi=abs(k), absorb=True)

def no_touch(N, k):
    return 1.0 - one_touch(N, k)

def stays_in(N, k):
    """P(price never leaves +-k steps during N ticks)."""
    return _dp(N, lo=-abs(k), hi=abs(k), absorb=False)

def only_ups(N):
    """RUNHIGH: all N ticks strictly up."""
    return 0.5**N

def table(payout_mult=1.95):
    print(f"{'N':>3} {'P(rise)':>9} {'P(tie)':>9} {'P(riseEq)':>10} "
          f"{'fairX rise':>11} {'fairX eq':>10} {'edge@%.2fx' % payout_mult:>12}")
    print("-"*70)
    for N in range(1, 13):
        pr, pt, pe = rise(N), tie(N), rise_equals(N)
        print(f"{N:>3} {pr:>9.5f} {pt:>9.5f} {pe:>10.5f} "
              f"{1/pr:>11.4f} {1/pe:>10.4f} {(1-pr*payout_mult)*100:>11.2f}%")
    print("\nOnly Ups / Only Downs (RUNHIGH/RUNLOW) - exact:")
    for N in range(1, 9):
        print(f"   N={N:>2}  P={only_ups(N):.6f}   fair payout = {1/only_ups(N):>10.2f}x")
    print("\nTouch / No-Touch, barrier k steps (k x 0.1 index pts), N ticks:")
    print(f"{'N':>4}" + "".join(f"{'k='+str(k):>11}" for k in (1,2,3,5,10)))
    for N in (5, 10, 20, 50, 100):
        print(f"{N:>4}" + "".join(f"{one_touch(N,k):>11.5f}" for k in (1,2,3,5,10)))

if __name__ == "__main__":
    table()
