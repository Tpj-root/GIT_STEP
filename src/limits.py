import asyncio, json, time
import websockets
URL="wss://ws.derivws.com/websockets/v3?app_id=1089"
NOW=int(time.time())

async def q(ws, req):
    await ws.send(json.dumps(req))
    while True:
        r=json.loads(await asyncio.wait_for(ws.recv(),30))
        if r.get("msg_type") in ("history","candles"): return r
        if "error" in r: return r

def fmt(t): return time.strftime('%Y-%m-%d %H:%M', time.gmtime(t))

async def main():
    async with websockets.connect(URL, open_timeout=30, max_size=8_000_000) as ws:
        print("=== TICK-style history: explicit start/end windows ===")
        for days in [0.5, 1, 2, 3, 7, 30, 90, 365]:
            start = NOW - int(days*86400)
            r = await q(ws, {"ticks_history":"stpRNG","start":start,"end":start+300,
                             "count":500,"style":"ticks"})
            if "error" in r:
                print(f"  {days:>5}d ago -> ERROR {r['error']['code']}"); continue
            t=r["history"]["times"]
            if not t: print(f"  {days:>5}d ago -> EMPTY"); continue
            drift=(t[0]-start)/86400
            ok = abs(t[0]-start) < 3600
            print(f"  {days:>5}d ago -> got {fmt(t[0])}  requested {fmt(start)}  "
                  f"drift {drift:+.2f}d  {'OK' if ok else '<-- FELL BACK TO RECENT'}")
            await asyncio.sleep(0.35)

        print("\n=== CANDLE-style history (granularity=60s) ===")
        for days in [7, 30, 90, 180, 365, 400]:
            start = NOW - int(days*86400)
            r = await q(ws, {"ticks_history":"stpRNG","start":start,"end":start+60*400,
                             "count":400,"style":"candles","granularity":60})
            if "error" in r:
                print(f"  {days:>5}d ago -> ERROR {r['error']['code']}"); continue
            c=r.get("candles") or []
            if not c: print(f"  {days:>5}d ago -> EMPTY"); continue
            drift=(c[0]['epoch']-start)/86400
            ok = abs(c[0]['epoch']-start) < 3600
            print(f"  {days:>5}d ago -> got {fmt(c[0]['epoch'])}  requested {fmt(start)}  "
                  f"drift {drift:+.2f}d  {'OK' if ok else '<-- FELL BACK'}")
            await asyncio.sleep(0.35)

asyncio.run(main())
