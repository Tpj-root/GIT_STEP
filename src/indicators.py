"""Indicator library. All functions take a 1-D float array of prices and return
a float array of the same length, NaN-padded at the front where undefined."""
import numpy as np
import pandas as pd

def _s(p): return pd.Series(p)

def sma(p, n):
    return _s(p).rolling(n, min_periods=n).mean().to_numpy()

def ema(p, n):
    return _s(p).ewm(span=n, adjust=False, min_periods=n).mean().to_numpy()

def rsi(p, n=14):
    d = _s(p).diff()
    up = d.clip(lower=0.0)
    dn = (-d).clip(lower=0.0)
    au = up.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    ad = dn.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    rs = au / ad.replace(0, np.nan)
    out = 100 - 100/(1+rs)
    return out.fillna(50.0).to_numpy()

def macd(p, fast=12, slow=26, sig=9):
    f = _s(p).ewm(span=fast, adjust=False).mean()
    s = _s(p).ewm(span=slow, adjust=False).mean()
    line = f - s
    signal = line.ewm(span=sig, adjust=False).mean()
    return line.to_numpy(), signal.to_numpy(), (line-signal).to_numpy()

def bollinger(p, n=20, k=2.0):
    m = _s(p).rolling(n, min_periods=n).mean()
    sd = _s(p).rolling(n, min_periods=n).std(ddof=0)
    return m.to_numpy(), (m+k*sd).to_numpy(), (m-k*sd).to_numpy()

def stochastic(p, n=14, d=3):
    lo = _s(p).rolling(n, min_periods=n).min()
    hi = _s(p).rolling(n, min_periods=n).max()
    rng = (hi-lo).replace(0, np.nan)
    k = 100*(_s(p)-lo)/rng
    return k.fillna(50).to_numpy(), k.rolling(d, min_periods=d).mean().fillna(50).to_numpy()

def williams_r(p, n=14):
    lo = _s(p).rolling(n, min_periods=n).min()
    hi = _s(p).rolling(n, min_periods=n).max()
    rng = (hi-lo).replace(0, np.nan)
    return (-100*(hi-_s(p))/rng).fillna(-50).to_numpy()

def cci(p, n=20):
    m = _s(p).rolling(n, min_periods=n).mean()
    md = _s(p).rolling(n, min_periods=n).apply(lambda x: np.abs(x-x.mean()).mean(), raw=True)
    return ((_s(p)-m)/(0.015*md.replace(0, np.nan))).fillna(0).to_numpy()

def roc(p, n=10):
    return _s(p).pct_change(n).to_numpy()

def zscore(p, n=50):
    m = _s(p).rolling(n, min_periods=n).mean()
    sd = _s(p).rolling(n, min_periods=n).std(ddof=0).replace(0, np.nan)
    return ((_s(p)-m)/sd).to_numpy()

def donchian(p, n=20):
    return (_s(p).rolling(n, min_periods=n).max().to_numpy(),
            _s(p).rolling(n, min_periods=n).min().to_numpy())

def streak(p):
    """Current run length of consecutive same-direction ticks, signed.
    +3 == three consecutive up-ticks. The 'after N reds, bet green' indicator."""
    d = np.sign(np.diff(p, prepend=p[0]))
    out = np.zeros(len(d))
    run = 0; prev = 0
    for i, x in enumerate(d):
        if x == 0:      run = 0
        elif x == prev: run += x
        else:           run = x
        out[i] = run; prev = x if x != 0 else prev
    return out
