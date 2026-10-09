import asyncio, json, websockets

URL = "wss://ws.derivws.com/websockets/v3?app_id=1089"

async def main():
    async with websockets.connect(URL, open_timeout=25) as ws:
        await ws.send(json.dumps({"ticks_history":"stpRNG","count":10,"end":"latest","style":"ticks"}))
        r = json.loads(await asyncio.wait_for(ws.recv(), 25))
        if "error" in r:
            print("ERROR:", r["error"]); return
        h = r["history"]
        print("prices:", h["prices"][:10])
        print("times :", h["times"][:10])
        d = [round(h["prices"][i+1]-h["prices"][i],4) for i in range(len(h["prices"])-1)]
        dt = [h["times"][i+1]-h["times"][i] for i in range(len(h["times"])-1)]
        print("diffs :", d)
        print("gaps  :", dt)

asyncio.run(main())
