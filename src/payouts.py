"""Probe Deriv for the Step Index payout table across tick durations.
This is the H2/H3 test: are odd and even tick durations priced differently?"""
import asyncio, json
import websockets
from math import comb

URL="wss://ws.derivws.com/websockets/v3?app_id=1089"
SYM="stpRNG"; STAKE=10.0

def theory(N):
    pt = comb(N,N//2)/2**N if N%2==0 else 0.0
    return (1-pt)/2, pt

async def q(ws, req, tag):
    await ws.send(json.dumps(req))
    for _ in range(6):
        r=json.loads(await asyncio.wait_for(ws.recv(),25))
        if "error" in r: return ("ERR", r["error"].get("code"), r["error"].get("message"))
        if r.get("msg_type") in ("proposal","contracts_for","active_symbols"): return ("OK", r)
    return ("TIMEOUT",None,None)

async def main():
    async with websockets.connect(URL, open_timeout=30, max_size=8_000_000) as ws:
        print("--- contracts_for stpRNG ---")
        st,*rest = await q(ws,{"contracts_for":SYM,"currency":"USD"},"cf")
        if st=="OK":
            av=rest[0]["contracts_for"]["available"]
            types=sorted({c["contract_type"] for c in av})
            print("contract types enabled:", types)
            rf=[c for c in av if c["contract_type"] in ("CALL","PUT","CALLE","PUTE")]
            for c in rf[:12]:
                print("  ",c["contract_type"],c.get("min_contract_duration"),
                      "->",c.get("max_contract_duration"),c.get("contract_category_display"))
        else:
            print("  blocked:",rest)

        print("\n--- proposal: payout vs tick duration ---")
        print(f"{'N':>3}{'type':>7}{'payout':>10}{'return%':>10}"
              f"{'impliedP':>11}{'theoryP':>10}{'edge%':>9}")
        for N in range(1,11):
            for ct in ("CALL","CALLE"):
                st,*rest = await q(ws,{"proposal":1,"amount":STAKE,"basis":"stake",
                    "contract_type":ct,"currency":"USD","duration":N,
                    "duration_unit":"t","symbol":SYM},"p")
                if st!="OK":
                    print(f"{N:>3}{ct:>7}   blocked: {rest[0]} {rest[1]}"); continue
                pr=rest[0]["proposal"]; payout=float(pr["payout"])
                ret=payout/STAKE
                impl=1/ret
                th,_=theory(N)
                if ct=="CALLE": th=th+ (theory(N)[1])
                edge=(1-th*ret)*100
                print(f"{N:>3}{ct:>7}{payout:>10.2f}{(ret-1)*100:>9.2f}%"
                      f"{impl:>11.4f}{th:>10.4f}{edge:>8.2f}%")
                await asyncio.sleep(0.8)

asyncio.run(main())
