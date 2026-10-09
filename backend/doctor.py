#!/usr/bin/env python3
"""Preflight check for live Deriv trading. READ-ONLY -- never places an order.

    python backend/doctor.py

Answers, in order: is the token valid, is it a DEMO account, does it have the
trade scope, is Step Index tradable from this network, which contract types and
multipliers are actually offered, and what would a real order cost.
"""
from __future__ import annotations
import asyncio, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.config import settings          # noqa: E402
from app.feed import DerivFeed           # noqa: E402

OK, BAD, WARN, INFO = "  \033[32mOK\033[0m  ", "  \033[31mFAIL\033[0m", "  \033[33mWARN\033[0m", "  ..  "
SYMBOLS = ["stpRNG", "frxXAUUSD"]


def line(tag, msg):
    print(f"{tag}  {msg}")


async def main() -> int:
    problems: list[str] = []
    print(f"\nendpoint : {settings.deriv_ws_url}?app_id={settings.deriv_app_id}")
    print(f"broker   : {settings.broker.value}")
    tok = settings.deriv_api_token
    print(f"token    : {'set (' + tok[:4] + '…' + str(len(tok)) + ' chars)' if tok else 'NOT SET'}\n")

    feed = DerivFeed(settings.ws_url, stale_after=settings.stale_tick_seconds)
    feed.start()
    if not await feed.wait_ready(30):
        line(BAD, "could not open a WebSocket to Deriv"); return 1
    line(OK, "websocket connected")

    # ---------------------------------------------------------------- limits
    try:
        st = await feed._send({"website_status": 1})
        lim = st["website_status"].get("api_call_limits", {})
        line(INFO, f"rate limits: {lim.get('max_requestes_general', {}).get('minutely', '?')}/min general, "
                   f"{lim.get('max_requests_pricing', {}).get('minutely', '?')}/min pricing")
    except Exception as e:
        line(WARN, f"website_status failed: {e}")

    # ---------------------------------------------------------------- auth
    if not tok:
        line(BAD, "DERIV_API_TOKEN is not set -- cannot check the account")
        problems.append("set DERIV_API_TOKEN in .env")
    else:
        try:
            res = await feed._send({"authorize": tok})
            a = res["authorize"]
            scopes = a.get("scopes", [])
            virtual = bool(a.get("is_virtual"))
            line(OK, f"authorized as {a.get('loginid')} "
                     f"({'DEMO' if virtual else 'REAL MONEY'}) "
                     f"balance {a.get('balance')} {a.get('currency')}")
            line(INFO, f"scopes: {', '.join(scopes) or 'none'}")
            if not virtual:
                line(WARN, "this token is for a REAL account. Use a demo (VRTC) token "
                           "until the strategy has been paper-validated.")
                problems.append("token is a REAL-money account")
            if "trade" not in scopes:
                line(BAD, "token lacks the 'trade' scope -- orders will be refused")
                problems.append("regenerate the token with the 'trade' scope")
            else:
                line(OK, "'trade' scope present")
        except Exception as e:
            line(BAD, f"authorize failed: {e}")
            problems.append("token rejected by Deriv")

    # ---------------------------------------------------------------- symbols
    syms = await feed.fetch_active_symbols()
    if not syms:
        line(WARN, "active_symbols returned EMPTY -- this network is geo/IP restricted. "
                   "Market data works; trade offerings may not.")
        problems.append("active_symbols blocked (geo/IP)")
    else:
        codes = {s.get("symbol") for s in syms}
        line(OK, f"active_symbols: {len(syms)} symbols")
        for want in SYMBOLS:
            line(OK if want in codes else BAD, f"  {want} {'tradable' if want in codes else 'NOT in the tradable list'}")

    # ---------------------------------------------------------------- data
    for sym in SYMBOLS:
        try:
            c = await feed.history(sym, 60, count=5)
            line(OK, f"{sym}: market data flowing (last close {c[-1].close})")
        except Exception as e:
            line(BAD, f"{sym}: history failed: {e}")
            problems.append(f"no market data for {sym}")

    # ---------------------------------------------------------------- offerings
    for sym in SYMBOLS:
        try:
            res = await feed._send({"contracts_for": sym, "currency": "USD"})
            av = res["contracts_for"]["available"]
            types = sorted({c["contract_type"] for c in av})
            line(OK, f"{sym}: {len(types)} contract types -> {', '.join(types)}")
            mults = sorted({m for c in av for m in (c.get("multiplier_range") or [])})
            if mults:
                line(INFO, f"  multipliers: {mults}")
            for c in av:
                if c["contract_type"] in ("MULTUP", "CALL"):
                    line(INFO, f"  {c['contract_type']}: duration "
                               f"{c.get('min_contract_duration')}..{c.get('max_contract_duration')}")
                    break
        except Exception as e:
            line(WARN, f"{sym}: contracts_for blocked ({e})")
            problems.append(f"contracts_for blocked for {sym}")

    # ---------------------------------------------------------------- proposal
    for sym in SYMBOLS:
        try:
            res = await feed._send({
                "proposal": 1, "amount": 1.0, "basis": "stake",
                "contract_type": "MULTUP", "currency": "USD", "symbol": sym,
                "multiplier": settings.deriv_multiplier})
            pr = res["proposal"]
            line(OK, f"{sym}: MULTUP x{settings.deriv_multiplier} priced -- "
                     f"ask {pr.get('ask_price')} ({pr.get('display_value')})")
        except Exception as e:
            line(WARN, f"{sym}: proposal blocked ({e})")
            problems.append(f"proposal blocked for {sym}")

    await feed.stop()

    print("\n" + "=" * 70)
    if problems:
        print("BLOCKERS / WARNINGS")
        for p in problems:
            print(f"  - {p}")
    else:
        print("All checks passed. Set BROKER=deriv in .env to trade contracts.")
    print("=" * 70)
    print("No order was placed. This script never buys.\n")
    return 1 if any("blocked by Deriv" in p or "rejected" in p for p in problems) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
