"""T1-T9 randomness battery on stpRNG tick data.
Tests whether the increments are really i.i.d. Bernoulli(0.5) +-1 steps.
This is the only place a tradeable edge could exist."""
import sys, math
import numpy as np
from scipy import stats

def run(path):
    z = np.load(path); P = z["prices"].astype(np.float64); T = z["times"]
    d = np.round(np.diff(P), 6)
    n = len(d)
    print(f"ticks={len(P):,}  increments={n:,}  "
          f"span={(T[-1]-T[0])/86400:.2f} days\n")

    # T1 -- step size constancy
    vals, cnts = np.unique(d, return_counts=True)
    print("T1  step-size constancy")
    for v, c in zip(vals, cnts):
        print(f"      {v:+.4f}  x {c:,}  ({100*c/n:.4f}%)")
    anomalies = cnts[(vals != 0.1) & (vals != -0.1)].sum()
    print(f"      -> non-(+-0.1) moves: {anomalies:,}"
          f"   {'CLEAN' if anomalies==0 else '<<< ANOMALY'}\n")

    x = np.where(d > 0, 1, -1).astype(np.int8)   # sign series
    up = int((x == 1).sum())

    # T2 -- directional bias
    bt = stats.binomtest(up, n, 0.5)
    se = math.sqrt(0.25/n)
    print("T2  directional bias")
    print(f"      up={up:,}  down={n-up:,}  P(up)={up/n:.6f}")
    print(f"      se={se:.6f}  z={(up/n-0.5)/se:+.3f}  p={bt.pvalue:.4f}"
          f"   {'PASS' if bt.pvalue>0.05 else '<<< BIASED'}\n")

    # T3 -- autocorrelation
    xc = x - x.mean(); v = xc @ xc
    lags = list(range(1, 51)) + [100, 200, 500, 1000]
    acf = {k: float(xc[:-k] @ xc[k:] / v) for k in lags}
    crit = 1.96/math.sqrt(n)
    worst = max(acf.items(), key=lambda kv: abs(kv[1]))
    nsig = sum(abs(a) > crit for a in acf.values())
    print("T3  autocorrelation")
    print(f"      |acf| 95% band = +-{crit:.6f}")
    print(f"      lag1={acf[1]:+.6f}  lag2={acf[2]:+.6f}  lag3={acf[3]:+.6f}"
          f"  lag10={acf[10]:+.6f}")
    print(f"      largest |acf| at lag {worst[0]}: {worst[1]:+.6f}")
    print(f"      lags outside band: {nsig}/{len(lags)}"
          f"  (expect ~{0.05*len(lags):.1f} by chance)"
          f"   {'PASS' if nsig <= 0.05*len(lags)+2 else '<<< STRUCTURE'}\n")

    # T4 -- Ljung-Box
    h = 50
    q = n*(n+2)*sum(acf[k]**2/(n-k) for k in range(1, h+1))
    pq = 1 - stats.chi2.cdf(q, h)
    print("T4  Ljung-Box (h=50)")
    print(f"      Q={q:.2f}  chi2_crit={stats.chi2.ppf(0.95,h):.2f}  p={pq:.4f}"
          f"   {'PASS' if pq>0.05 else '<<< STRUCTURE'}\n")

    # T5 -- runs test
    runs = 1 + int((x[1:] != x[:-1]).sum())
    n1, n2 = up, n-up
    mu = 2*n1*n2/n + 1
    sd = math.sqrt(2*n1*n2*(2*n1*n2-n)/(n*n*(n-1)))
    zr = (runs-mu)/sd
    pr = 2*(1-stats.norm.cdf(abs(zr)))
    print("T5  Wald-Wolfowitz runs")
    print(f"      runs={runs:,}  expected={mu:,.1f}  z={zr:+.3f}  p={pr:.4f}"
          f"   {'PASS' if pr>0.05 else '<<< NON-RANDOM'}\n")

    # T6 -- conditional bias on last k moves
    print("T6  conditional bias  P(up | previous k moves)")
    worst_p = 1.0
    for k in (1, 2, 3, 4, 6, 8, 10, 12):
        b = (x[:-1] > 0).astype(np.int64)
        code = np.zeros(n-k, dtype=np.int64)
        for j in range(k):
            code += b[j:n-k+j] << j
        nxt = (x[k:] > 0).astype(np.int64)
        tot = np.bincount(code, minlength=1 << k).astype(float)
        ups = np.bincount(code, weights=nxt, minlength=1 << k)
        m = tot >= 50
        if not m.any(): continue
        chi = (((ups[m]-tot[m]*0.5)**2)/(tot[m]*0.25)).sum()
        pv = 1 - stats.chi2.cdf(chi, m.sum())
        worst_p = min(worst_p, pv)
        rates = ups[m]/tot[m]
        ex = int(np.argmax(np.abs(rates-0.5)))
        print(f"      k={k:>2}  patterns={m.sum():>5}  chi2={chi:>10.2f}  p={pv:.4f}"
              f"   most extreme P(up)={rates[ex]:.4f}"
              f"   {'PASS' if pv>0.05 else '<<< PATTERN'}")
    print()

    # T7 -- spectrum
    f = np.fft.rfft(x - x.mean())
    ps = (np.abs(f)**2)[1:]
    ratio = ps.max()/ps.mean()
    thresh = math.log(len(ps))+3
    print("T7  spectral flatness")
    print(f"      max/mean power = {ratio:.2f}  (white-noise guide ~{thresh:.1f})"
          f"   {'PASS' if ratio < thresh else '<<< PERIODICITY'}\n")

    # T8 -- time of day
    sec = (T[:-1] % 86400)//60
    tot = np.bincount(sec, minlength=1440).astype(float)
    ups = np.bincount(sec, weights=(x > 0).astype(float), minlength=1440)
    m = tot >= 30
    chi = (((ups[m]-tot[m]*0.5)**2)/(tot[m]*0.25)).sum()
    pv = 1-stats.chi2.cdf(chi, m.sum())
    print("T8  time-of-day effect (minute buckets)")
    print(f"      buckets={m.sum()}  chi2={chi:.1f}  p={pv:.4f}"
          f"   {'PASS' if pv>0.05 else '<<< TIME EFFECT'}\n")

    # T9 -- tick timing
    g = np.diff(T); gv, gc = np.unique(g, return_counts=True)
    print("T9  inter-tick gaps (seconds)")
    for v, c in list(zip(gv, gc))[:6]:
        print(f"      {v:>6}s  x {c:,}  ({100*c/len(g):.4f}%)")
    print()

if __name__ == "__main__":
    run(sys.argv[1])
