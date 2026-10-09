"""Split-half replication of the T2/T3 flags.
A finding that does not reproduce out-of-sample is noise."""
import sys, math
import numpy as np
from scipy import stats

z=np.load(sys.argv[1]); P=z["prices"]
d=np.diff(P); x=np.where(d>0,1,-1).astype(np.int8)
half=len(x)//2
A,B=x[:half],x[half:2*half]
lags=list(range(1,51))+[100,200,500,1000]

def acf(s):
    c=s-s.mean(); v=c@c
    return {k: float(c[:-k]@c[k:]/v) for k in lags}

print(f"split-half replication: A={len(A):,}  B={len(B):,} increments\n")

# --- T2 bias
for nm,s in (("A",A),("B",B),("ALL",x)):
    up=int((s==1).sum()); n=len(s)
    p=stats.binomtest(up,n,0.5).pvalue
    print(f"T2 {nm:>3}: P(up)={up/n:.6f}  z={(up/n-0.5)/math.sqrt(0.25/n):+.3f}  p={p:.4f}")
print()

aA,aB=acf(A),acf(B)
critA=1.96/math.sqrt(len(A))
exA=[k for k in lags if abs(aA[k])>critA]
exB=[k for k in lags if abs(aB[k])>critA]
both=sorted(set(exA)&set(exB))
print(f"T3 half A: {len(exA)} lags outside band -> {exA}")
print(f"T3 half B: {len(exB)} lags outside band -> {exB}")
print(f"T3 exceed in BOTH halves: {both if both else 'NONE'}")
samesign=[k for k in both if np.sign(aA[k])==np.sign(aB[k])]
print(f"T3 same SIGN in both halves: {samesign if samesign else 'NONE'}")
print()

print("largest |acf| in full sample and what it would be worth:")
full=acf(x); k=max(lags,key=lambda k:abs(full[k]))
r=full[k]
print(f"   lag {k}: acf={r:+.6f}")
print(f"   best achievable win rate from this = {0.5+abs(r)/2:.6f}")
print(f"   break-even win rate needed at 1.95x payout = {1/1.95:.6f}")
print(f"   shortfall = {1/1.95-(0.5+abs(r)/2):.6f}  "
      f"({(1/1.95-(0.5+abs(r)/2))/ (abs(r)/2):,.0f}x too small)")
