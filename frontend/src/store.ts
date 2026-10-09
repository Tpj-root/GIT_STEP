import { create } from "zustand";
import { api } from "./api";
import { type Zone, loadZone, saveZone } from "./tz";
import * as sound from "./sound";
import type {
  Account, AlertEvent, Candle, ConfigBundle, IndicatorState, IndicatorSpec,
  LinePoint, ModeConfig, ModeName, OrderEvent, OverlayData, OverlayState,
  Position, SignalEvent, Status, SymbolInfo, Timeframe,
} from "./types";

const LS_KEY = "step-terminal.config.v1";

function loadLocalConfig(): ConfigBundle | null {
  try {
    const raw = localStorage.getItem(LS_KEY);
    return raw ? (JSON.parse(raw) as ConfigBundle) : null;
  } catch { return null; }
}
function saveLocalConfig(b: ConfigBundle) {
  try { localStorage.setItem(LS_KEY, JSON.stringify(b)); } catch { /* private mode */ }
}

interface State {
  connected: boolean;
  zone: Zone;
  soundOn: boolean;
  soundBlocked: boolean;
  symbols: SymbolInfo[];
  timeframes: Timeframe[];
  symbolsNote: string;

  symbol: string;
  tf: number;

  candles: Candle[];
  line: LinePoint[];
  indicator: IndicatorState | null;
  indicatorParams: { period: number; multiplier: number };
  overlaySpecs: IndicatorSpec[];
  overlayState: OverlayState;
  overlays: OverlayData;

  status: Status | null;
  positions: Position[];
  account: Account | null;

  config: ConfigBundle | null;
  signals: SignalEvent[];
  /** Latest manual-mode signal the trader has not acted on or dismissed. */
  pendingSignal: SignalEvent | null;
  orders: OrderEvent[];
  alerts: AlertEvent[];

  boot: () => Promise<void>;
  select: (symbol: string, tf: number) => Promise<void>;
  setParams: (p: { period?: number; multiplier?: number }) => Promise<void>;
  toggleOverlay: (id: string, visible: boolean) => Promise<void>;
  setOverlayParam: (id: string, name: string, value: number) => Promise<void>;
  setConfig: (mode: ModeName, patch: Partial<ModeConfig>) => Promise<void>;
  setMode: (m: ModeName) => Promise<void>;
  dismissAlert: (i: number) => void;
  setZone: (z: Zone) => void;
  setSound: (on: boolean) => Promise<void>;
  unlockSound: () => Promise<void>;
  clearPending: () => void;
}

let socket: WebSocket | null = null;
let retry = 0;

export const useStore = create<State>((set, get) => ({
  connected: false,
  zone: loadZone(),
  soundOn: sound.loadEnabled(), soundBlocked: true,
  symbols: [], timeframes: [], symbolsNote: "",
  symbol: "stpRNG", tf: 60,
  candles: [], line: [], indicator: null,
  indicatorParams: { period: 22, multiplier: 3.0 },
  overlaySpecs: [], overlayState: {}, overlays: {},
  status: null, positions: [], account: null,
  config: null, signals: [], orders: [], alerts: [], pendingSignal: null,

  boot: async () => {
    const [s, cfg, ind] = await Promise.all([api.symbols(), api.config(), api.indicators()]);
    // Backend is the source of truth on boot; localStorage only wins if the
    // user changed something locally and the backend is still on defaults.
    const local = loadLocalConfig();
    const config = local ?? cfg;
    if (local) { try { await api.putConfig(local); } catch { /* keep local */ } }

    set({
      symbols: s.symbols, timeframes: s.timeframes, symbolsNote: s.note,
      config,
      indicatorParams: {
        period: Number(ind.params.period ?? 22),
        multiplier: Number(ind.params.multiplier ?? 3.0),
      },
      overlaySpecs: ind.overlays ?? [],
      overlayState: ind.overlay_state ?? {},
    });
    await get().select(get().symbol, get().tf);
    connect(set, get);
  },

  select: async (symbol, tf) => {
    set({ symbol, tf, candles: [], line: [], indicator: null, pendingSignal: null });
    const d = await api.candles(symbol, tf, 1000);
    if (get().symbol !== symbol || get().tf !== tf) return;   // user moved on
    set({ candles: d.candles, line: d.line, indicator: d.indicator,
          overlays: d.overlays ?? {} });
  },

  setParams: async (p) => {
    const next = { ...get().indicatorParams, ...p };
    set({ indicatorParams: next });
    await api.putIndicators(p);
    const d = await api.candles(get().symbol, get().tf, 1000);
    set({ candles: d.candles, line: d.line, indicator: d.indicator,
          overlays: d.overlays ?? {} });
  },

  toggleOverlay: async (id, visible) => {
    set((st) => ({
      overlayState: { ...st.overlayState, [id]: { ...st.overlayState[id], visible } },
      // drop stale series immediately so hiding feels instant
      overlays: visible ? st.overlays
        : Object.fromEntries(Object.entries(st.overlays).filter(([k]) => k !== id)),
    }));
    const r = await api.setOverlay(id, visible);
    const d = await api.candles(get().symbol, get().tf, 1000);
    set({ overlayState: r.overlay_state, overlays: d.overlays ?? {} });
  },

  setOverlayParam: async (id, name, value) => {
    set((st) => ({
      overlayState: { ...st.overlayState, [id]: { ...st.overlayState[id], [name]: value } },
    }));
    const r = await api.setOverlay(id, undefined, { [name]: value });
    const d = await api.candles(get().symbol, get().tf, 1000);
    set({ overlayState: r.overlay_state, overlays: d.overlays ?? {} });
  },

  setConfig: async (mode, patch) => {
    const cur = get().config;
    if (!cur) return;
    const next: ConfigBundle = { ...cur, [mode]: { ...cur[mode], ...patch } };
    set({ config: next });
    saveLocalConfig(next);
    try { await api.putConfig(next); }
    catch (e) {
      set((s) => ({ alerts: [...s.alerts, { level: "warn", message: `Config rejected: ${String(e)}` }] }));
    }
  },

  setMode: async (m) => {
    try {
      const st = await api.setMode(m, get().symbol, get().tf);
      set({ status: { ...(get().status as Status), ...st } });
    } catch (e) {
      set((s) => ({ alerts: [...s.alerts, { level: "critical", message: `Cannot arm: ${String(e)}` }] }));
      throw e;
    }
  },

  dismissAlert: (i) => set((s) => ({ alerts: s.alerts.filter((_, k) => k !== i) })),

  setZone: (z) => { saveZone(z); set({ zone: z }); },

  setSound: async (on) => {
    sound.saveEnabled(on);
    set({ soundOn: on });
    if (on) {
      const ok = await sound.unlock();
      set({ soundBlocked: !ok });
      if (ok) sound.play("fill");        // confirm it is actually audible
    }
  },

  // Browsers refuse audio until a real gesture; called from the first click.
  unlockSound: async () => {
    if (!get().soundOn) return;
    const ok = await sound.unlock();
    set({ soundBlocked: !ok });
  },

  clearPending: () => set({ pendingSignal: null }),
}));

function connect(set: (p: Partial<State>) => void, get: () => State) {
  // Detach the old handler BEFORE closing. Otherwise closing a socket in order
  // to replace it fires its own onclose, which schedules another connect, which
  // closes the new socket... a self-sustaining reconnect storm that looks
  // exactly like a flaky network.
  if (socket) {
    const old = socket;
    old.onclose = null;
    old.onerror = null;
    try { old.close(); } catch { /* already closing */ }
  }

  const ws = new WebSocket(api.wsUrl());
  socket = ws;

  ws.onopen = () => { retry = 0; set({ connected: true }); };
  ws.onclose = () => {
    if (socket !== ws) return;        // superseded -- not ours to reconnect
    set({ connected: false });
    retry = Math.min(retry + 1, 6);
    setTimeout(() => { if (socket === ws) connect(set, get); },
               Math.min(1000 * 2 ** retry, 30000));
  };
  ws.onerror = () => { if (socket === ws) { try { ws.close(); } catch { /* noop */ } } };

  ws.onmessage = (ev) => {
    const { type, data } = JSON.parse(ev.data);
    const s = get();
    switch (type) {
      case "status":
        set({ status: data, account: data.broker ?? s.account });
        break;
      case "history":
        if (data.symbol === s.symbol && data.granularity === s.tf) {
          set({ candles: data.candles, line: data.line ?? s.line,
                indicator: data.indicator, overlays: data.overlays ?? s.overlays });
        }
        break;
      case "ohlc": {
        if (data.symbol !== s.symbol || data.granularity !== s.tf) break;
        const bar: Candle = data.bar;
        const next = s.candles.slice();
        if (next.length && next[next.length - 1].epoch === bar.epoch) next[next.length - 1] = bar;
        else if (!next.length || bar.epoch > next[next.length - 1].epoch) next.push(bar);
        set({ candles: next, indicator: data.indicator ?? s.indicator });
        break;
      }
      case "indicator_line":
        if (data.symbol === s.symbol && data.granularity === s.tf) set({ line: data.line });
        break;
      case "overlays":
        if (data.symbol === s.symbol && data.granularity === s.tf) set({ overlays: data.overlays });
        break;
      case "signal": {
        const sig = data as SignalEvent;
        const mine = sig.symbol === s.symbol && sig.granularity === s.tf;
        set({
          signals: [sig, ...s.signals].slice(0, 200),
          // Only offer a one-click trade for the chart actually on screen, and
          // only in manual mode -- in auto the order is already placed.
          pendingSignal: mine && !sig.executed ? sig : s.pendingSignal,
        });
        // Alert for the chart you are watching, and always for the ARMED series
        // even if you have navigated away from it -- that one is placing orders.
        const armed = s.status?.armed_on === `${sig.symbol}/${sig.granularity}s`;
        if (s.soundOn && (mine || armed)) {
          sound.play(sig.direction > 0 ? "buy" : "sell");
        }
        break;
      }
      case "order": {
        const o = data as OrderEvent;
        set({ orders: [o, ...s.orders].slice(0, 200) });
        // An auto order that was silently rejected is exactly the thing you
        // need to hear about; a manual one you are already watching for.
        if (s.soundOn) sound.play(o.ok ? "fill" : "reject");
        break;
      }
      case "positions":
        set({ positions: data.positions, account: data.account });
        break;
      case "config":
        set({ config: data });
        break;
      case "alert": {
        const a = data as AlertEvent;
        set({ alerts: [...s.alerts, a].slice(-5) });
        if (s.soundOn && a.level === "critical") sound.play("critical");
        break;
      }
    }
  };
}
