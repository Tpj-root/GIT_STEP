"""Symbol registry.

Deriv's `active_symbols` is geo/IP restricted and returns an EMPTY list from
blocked networks (datacenters, restricted countries) -- with no error. Booting
straight off it means the app simply has no symbols and no explanation.

So: a static fallback table is the source of truth for the symbols this app
trades, and a successful `active_symbols` response ENRICHES it with live
display names and pip sizes. Never the other way round.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict, replace


@dataclass(frozen=True)
class SymbolInfo:
    code: str            # Deriv WS code, e.g. stpRNG
    display: str
    mt5_symbol: str      # symbol name on the MT5 terminal
    digits: int
    point: float         # smallest price increment
    min_lot: float = 0.01
    max_lot: float = 100.0
    lot_step: float = 0.01
    tradable_via: str = "mt5"   # mt5 | deriv-contract

    def to_dict(self) -> dict:
        return asdict(self)


FALLBACK: dict[str, SymbolInfo] = {
    "stpRNG": SymbolInfo(
        code="stpRNG", display="Step Index", mt5_symbol="Step Index",
        digits=1, point=0.1, tradable_via="mt5"),
    "frxXAUUSD": SymbolInfo(
        code="frxXAUUSD", display="Gold/USD", mt5_symbol="XAUUSD",
        digits=2, point=0.01, tradable_via="mt5"),
}


class SymbolRegistry:
    def __init__(self) -> None:
        self._symbols: dict[str, SymbolInfo] = dict(FALLBACK)
        self.enriched = False
        self.note = "using built-in symbol table (active_symbols not yet fetched)"

    def all(self) -> list[SymbolInfo]:
        return list(self._symbols.values())

    def get(self, code: str) -> SymbolInfo | None:
        return self._symbols.get(code)

    def enrich(self, active_symbols: list[dict]) -> None:
        """Merge a live active_symbols response over the fallback table."""
        if not active_symbols:
            self.note = ("active_symbols returned empty -- this network is likely "
                         "geo/IP restricted by Deriv. Using built-in symbol table. "
                         "Market data still works; trade offerings may not.")
            return
        by_code = {s.get("symbol"): s for s in active_symbols}
        for code, info in list(self._symbols.items()):
            live = by_code.get(code)
            if not live:
                continue
            self._symbols[code] = replace(
                info,
                display=live.get("display_name") or info.display,
                digits=int(live.get("pip", 0) and
                           round(-1 * (len(str(live["pip"]).split(".")[-1]) * -1))
                           or info.digits),
            )
        self.enriched = True
        self.note = f"enriched from active_symbols ({len(active_symbols)} symbols live)"


registry = SymbolRegistry()

# granularity seconds -> UI label
TIMEFRAMES: dict[int, str] = {
    60: "1m", 300: "5m", 900: "15m", 3600: "1h", 14400: "4h", 86400: "1d",
}
