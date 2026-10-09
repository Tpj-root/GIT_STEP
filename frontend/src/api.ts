import type { ConfigBundle, ModeName, Side, Status, SymbolInfo, Timeframe,
  Candle, LinePoint, IndicatorState, Position, IndicatorSpec,
  OverlayData, OverlayState } from "./types";

/** Empty string == same origin. In Docker, nginx serves the app and proxies
 *  /api and /stream to the backend, so nothing host-specific is baked into the
 *  bundle — the same image works on any machine and any port. In `vite dev` the
 *  backend is a separate process, so point at it directly. */
const BASE = import.meta.env.VITE_API
  ?? (import.meta.env.DEV ? "http://localhost:8010" : "");

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(BASE + path, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail ?? detail; } catch { /* body not json */ }
    throw new Error(detail);
  }
  return r.json() as Promise<T>;
}

export const api = {
  base: BASE,
  wsUrl: () => {
    if (BASE) return BASE.replace(/^http/, "ws") + "/stream";
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${location.host}/stream`;
  },

  symbols: () => j<{ symbols: SymbolInfo[]; timeframes: Timeframe[]; note: string; enriched: boolean }>("/api/symbols"),

  candles: (symbol: string, tf: number, count = 1000) =>
    j<{ symbol: string; granularity: number; candles: Candle[]; line: LinePoint[];
        overlays: OverlayData; indicator: IndicatorState }>(
      `/api/candles?symbol=${encodeURIComponent(symbol)}&tf=${tf}&count=${count}`),

  status: () => j<Status>("/api/status"),
  config: () => j<ConfigBundle>("/api/config"),
  putConfig: (b: ConfigBundle) => j<ConfigBundle>("/api/config", { method: "PUT", body: JSON.stringify(b) }),

  indicators: () => j<{ indicators: IndicatorSpec[]; overlays: IndicatorSpec[];
                        params: Record<string, number>; overlay_state: OverlayState }>("/api/indicators"),

  setOverlay: (id: string, visible?: boolean, params: Record<string, number> = {}) =>
    j<{ id: string; state: Record<string, number | boolean>; overlay_state: OverlayState }>(
      "/api/overlays", { method: "PUT", body: JSON.stringify({ id, visible, params }) }),
  putIndicators: (p: { period?: number; multiplier?: number }) =>
    j<{ params: Record<string, number> }>("/api/indicators", { method: "PUT", body: JSON.stringify(p) }),

  setMode: (mode: ModeName, symbol?: string, granularity?: number) =>
    j<Status>("/api/mode", { method: "POST",
      body: JSON.stringify({ mode, symbol, granularity }) }),

  order: (p: { symbol: string; side: Side; lots?: number; sl?: number; tp?: number;
               source?: string; idem_key?: string }) =>
    j<{ ok: boolean; ticket?: string; price?: number; reason?: string; detail?: string; message?: string }>(
      "/api/order", { method: "POST", body: JSON.stringify({ source: "manual", ...p }) }),

  close: (ticket: string) => j(`/api/close?ticket=${encodeURIComponent(ticket)}`, { method: "POST" }),
  closeAll: () => j("/api/close-all", { method: "POST" }),
  kill: () => j<Status & { killed: boolean }>("/api/kill", { method: "POST" }),
  releaseKill: () => j<Status>("/api/kill/release", { method: "POST" }),
  positions: () => j<{ positions: Position[] }>("/api/positions"),
  log: (table: "orders" | "signals", limit = 100) =>
    j<{ rows: Record<string, unknown>[] }>(`/api/log?table=${table}&limit=${limit}`),
};
