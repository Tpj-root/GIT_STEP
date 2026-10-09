export type Side = "buy" | "sell";
export type ModeName = "manual" | "auto";

export interface SymbolInfo {
  code: string; display: string; mt5_symbol: string;
  digits: number; point: number; min_lot: number; max_lot: number;
  lot_step: number; tradable_via: string;
}
export interface Timeframe { granularity: number; label: string }

export interface Candle { epoch: number; open: number; high: number; low: number; close: number }

export interface LinePoint {
  epoch: number; value: number; direction: number; flip: boolean; signal: string | null;
}

export interface IndicatorState {
  ready: boolean; direction: number; atr: number | null;
  long_stop: number | null; short_stop: number | null;
  active_stop: number | null; signal: string | null; epoch: number;
}

export interface Position {
  ticket: string; symbol: string; side: Side; lots: number;
  open_price: number; open_time: number; sl: number | null; tp: number | null;
  profit: number; current_price: number;
}

export interface Account {
  broker: string; balance: number; equity: number;
  margin: number; currency: string; connected: boolean;
}

export interface Status {
  feed: string; transport: string; feed_stale: boolean; data_age: number;
  /** per-symbol age of the NEWEST BAR, seconds; null = never seen */
  symbol_age: Record<string, number | null>;
  symbol_stale: Record<string, boolean>;
  broker: Account | null; symbols_note: string;
  mode: ModeName; kill_switch: boolean; day: string;
  /** "stpRNG/60s" while armed, else null */
  armed_on: string | null;
  trades_today: number; realised_pnl: number;
  hard_max_lots: number; signals_traded: number;
}

export interface ModeConfig {
  lots: number;
  stop_loss_points: number | null;
  take_profit_points: number | null;
  max_concurrent_positions: number;
  max_daily_loss: number | null;
  max_trades_per_day: number | null;
  signal_action: "reverse" | "open-only" | "close-only";
  close_and_reverse_on_opposite: boolean;
}
export interface ConfigBundle { manual: ModeConfig; auto: ModeConfig }

export interface SignalEvent {
  symbol: string; granularity: number; bar_epoch: number;
  direction: number; action: string; price: number;
  indicator: string; idem_key: string; executed: boolean;
}

export interface OrderEvent {
  ok: boolean; symbol: string; side: string; source: string;
  ticket?: string | null; price?: number | null;
  message?: string; reason?: string; detail?: string;
}

export interface AlertEvent { level: "info" | "warn" | "critical"; message: string }

export interface ParamSpec {
  name: string; label: string; kind: "int" | "float";
  default: number; min: number; max: number; step: number;
}
export interface SeriesSpec {
  key: string; label: string;
  pane: "overlay" | "separate"; kind: "line" | "histogram";
}
export interface IndicatorSpec {
  id: string; label: string; params: ParamSpec[];
  series: SeriesSpec[]; emits_signals: boolean;
}
export interface OverlayPoint { epoch: number; value: number }
/** indicator id -> series key -> points */
export type OverlayData = Record<string, Record<string, OverlayPoint[]>>;
/** indicator id -> { visible, ...params } */
export type OverlayState = Record<string, Record<string, number | boolean>>;
