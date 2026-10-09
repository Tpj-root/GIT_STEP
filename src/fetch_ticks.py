"""Backfill stpRNG ticks using EXPLICIT start/end windows.

Deriv serves ~365 days of tick history, but ONLY when `start` is given.
A count-based backward walk (end + count, no start) silently stops advancing
after ~1 day. Requests >365 days back silently return recent data with no error.
Both traps are guarded here.
"""
import asyncio, json, sys, time
import numpy as np
import websockets

URL    = "wss://ws.derivws.com/websockets/v3?app_id=1089"
SYMBOL = "stpRNG"
WIN    = 5000                      # seconds per window == 5000 ticks (1/sec), server cap
TARGET = int(sys.argv[1]) if len(sys.argv) > 1 else 1_000_000
OUT    = sys.argv[2] if len(sys.argv) > 2 else "ticks.npz"
PACE   = 0.34
MAX_BACK = 364 * 86400             # stay inside the 365d boundary

async def fetch(ws, start, end):
    await ws.send(json.dumps({"ticks_history": SYMBOL, "start": int(start),
                              "end": int(end), "count": WIN, "style": "ticks"}))
    while True:
        r = json.loads(await asyncio.wait_for(ws.recv(), 30))
        if r.get("msg_type") == "history":
            h = r["history"]
            return (np.asarray(h["times"], dtype=np.int64),
                    np.asarray(h["prices"], dtype=np.float64))
        if "error" in r:
            raise RuntimeError(r["error"])

async def main():
    now = int(time.time())
    times, prices, total = [], [], 0
    end = now - 60
    t0 = time.time()

    async with websockets.connect(URL, open_timeout=30, max_size=8_000_000) as ws:
        while total < TARGET:
            start = end - WIN + 1
            if now - start > MAX_BACK:
                print("\nreached 365-day boundary, stopping"); break

            t, p = await fetch(ws, start, end)
            if len(t) == 0:
                print(f"\nempty window at {start}, stopping"); break

            # --- guards -----------------------------------------------------
            if t[0] < start - 3600 or t[-1] > end + 3600:
                raise SystemExit(f"WINDOW MISMATCH: got [{t[0]},{t[-1]}] "
                                 f"for requested [{start},{end}] - silent fallback")
            if not np.all(np.diff(t) >= 0):
                raise SystemExit("non-monotonic timestamps in batch")
            # ----------------------------------------------------------------

            times.append(t); prices.append(p); total += len(t)
            end = int(t[0]) - 1
            if len(times) % 25 == 0:            # incremental save; survives timeout
                _T = np.concatenate(times[::-1]); _P = np.concatenate(prices[::-1])
                _o = np.argsort(_T, kind="stable")
                np.savez_compressed(OUT, times=_T[_o], prices=_P[_o])
            if len(times) % 20 == 0:
                print(f"\r{total:>9,} ticks | oldest "
                      f"{time.strftime('%Y-%m-%d %H:%M', time.gmtime(t[0]))} | "
                      f"{time.time()-t0:5.1f}s", end="", flush=True)
            await asyncio.sleep(PACE)

    T = np.concatenate(times[::-1]); P = np.concatenate(prices[::-1])
    o = np.argsort(T, kind="stable"); T, P = T[o], P[o]
    keep = np.ones(len(T), bool); keep[1:] = np.diff(T) != 0
    T, P = T[keep], P[keep]

    np.savez_compressed(OUT, times=T, prices=P)
    print(f"\n\nsaved {len(T):,} unique ticks -> {OUT}")
    print(f"span {time.strftime('%Y-%m-%d %H:%M', time.gmtime(T[0]))} .. "
          f"{time.strftime('%Y-%m-%d %H:%M', time.gmtime(T[-1]))} "
          f"({(T[-1]-T[0])/86400:.1f} days)")
    d = np.round(np.diff(P), 4)
    u = dict(zip(*np.unique(d, return_counts=True)))
    print(f"distinct tick moves: {u}")
    gaps = np.diff(T); gu = dict(zip(*np.unique(gaps, return_counts=True)))
    print(f"timestamp gaps (top): {dict(list(sorted(gu.items(), key=lambda x:-x[1]))[:5])}")

asyncio.run(main())
