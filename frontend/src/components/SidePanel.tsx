import type { IndicatorState, ModeConfig, ModeName, Side, Status, SymbolInfo } from "../types";
import { Section } from "./Section";

interface Props {
  indicator: IndicatorState | null;
  config: ModeConfig | null; mode: ModeName;
  onConfig: (patch: Partial<ModeConfig>) => void;
  symbol: SymbolInfo | undefined;
  status: Status | null;
  onTrade: (side: Side) => void;
  busy: boolean;
  indicatorsSlot?: React.ReactNode;
}

function Num({ label, value, onChange, min, max, step = 1, disabled, invalid, suffix }: {
  label: string; value: number | null; onChange: (v: number | null) => void;
  min?: number; max?: number; step?: number; disabled?: boolean;
  invalid?: boolean; suffix?: string;
}) {
  return (
    <div className="row">
      <label htmlFor={`f-${label}`}>{label}{suffix ? ` (${suffix})` : ""}</label>
      <input id={`f-${label}`} type="number" value={value ?? ""} min={min} max={max} step={step}
             disabled={disabled} className={invalid ? "invalid" : ""}
             onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} />
    </div>
  );
}

export function SidePanel({ indicator, config, mode,
                            onConfig, symbol, status, onTrade, busy,
                            indicatorsSlot }: Props) {
  const auto = mode === "auto";
  const killed = !!status?.kill_switch;
  const symStale = !!status?.symbol_stale?.[symbol?.code ?? ""];
  const canTrade = !auto && !killed && !busy && !!status && !symStale;
  const dir = indicator?.direction ?? 0;
  const hardMax = status?.hard_max_lots ?? 1;

  const lotsBad = !!config && (config.lots <= 0 || config.lots > hardMax
    || (symbol ? config.lots < symbol.min_lot : false));
  const slBad = auto && !config?.stop_loss_points;
  const lossBad = auto && !config?.max_daily_loss;
  const tradesBad = auto && !config?.max_trades_per_day;

  return (
    <aside className="side">
      {indicatorsSlot}

      <Section id="cestate" title="Chandelier State" defaultOpen={false}
               badge={<span className={`val ${dir > 0 ? "long" : dir < 0 ? "short" : ""}`}
                            style={{ fontSize: 10 }}>
                        {!indicator?.ready ? "—" : dir > 0 ? "LONG" : "SHORT"}
                      </span>}>
      <div className="row">
        <span className="k">direction</span>
        <span className={`val ${dir > 0 ? "long" : dir < 0 ? "short" : ""}`}>
          {!indicator?.ready ? "warming up" : dir > 0 ? "▲ LONG" : "▼ SHORT"}
        </span>
      </div>
      <div className="row">
        <span className="k">active stop</span>
        <span className={`val num ${dir > 0 ? "long" : "short"}`}>
          {indicator?.ready && indicator.active_stop != null
            ? indicator.active_stop.toFixed(symbol?.digits ?? 2) : "—"}
        </span>
      </div>
      <div className="row">
        <span className="k">ATR</span>
        <span className="val num">{indicator?.atr != null ? indicator.atr.toFixed(3) : "—"}</span>
      </div>
      </Section>

      <Section id="exec" title="Execution" defaultOpen forceOpen={auto}
               badge={<span className={`pill ${auto ? "auto" : "manual"}`}>{mode}</span>}>
      {config && (
        <>
          <Num label="lots" value={config.lots} min={symbol?.min_lot ?? 0.01}
               max={hardMax} step={symbol?.lot_step ?? 0.01} invalid={lotsBad}
               onChange={(v) => v != null && onConfig({ lots: v })} />
          <Num label="stop loss" suffix="pts" value={config.stop_loss_points} min={1}
               invalid={slBad}
               onChange={(v) => onConfig({ stop_loss_points: v })} />
          <Num label="take profit" suffix="pts" value={config.take_profit_points} min={1}
               onChange={(v) => onConfig({ take_profit_points: v })} />
          <Num label="max positions" value={config.max_concurrent_positions} min={1} max={5}
               onChange={(v) => v && onConfig({ max_concurrent_positions: v })} />
          <Num label="max daily loss" suffix="$" value={config.max_daily_loss} min={1}
               invalid={lossBad}
               onChange={(v) => onConfig({ max_daily_loss: v })} />
          <Num label="max trades/day" value={config.max_trades_per_day} min={1}
               invalid={tradesBad}
               onChange={(v) => onConfig({ max_trades_per_day: v })} />
          <div className="row">
            <label htmlFor="sigact">signal action</label>
            <select id="sigact" className="mini" value={config.signal_action}
                    onChange={(e) => onConfig({ signal_action: e.target.value as ModeConfig["signal_action"] })}>
              <option value="reverse">reverse</option>
              <option value="open-only">open-only</option>
              <option value="close-only">close-only</option>
            </select>
          </div>
        </>
      )}
      </Section>

      <div className="trade-btns">
        <button className="tbtn buy" disabled={!canTrade} onClick={() => onTrade("buy")}>BUY</button>
        <button className="tbtn sell" disabled={!canTrade} onClick={() => onTrade("sell")}>SELL</button>
      </div>
      <p className="hint">
        {killed ? "Kill switch engaged — release it to trade."
          : auto ? "Auto mode armed. Manual entry is disabled; Chandelier flips execute on closed bars."
          : symStale ? `No recent ${symbol?.display ?? "market"} data — orders blocked server-side. Market closed?`
          : "Manual mode. Signals are logged and marked on the chart but never executed."}
      </p>
      <p className="hint">
        Editing the <b>{mode}</b> profile — auto and manual keep separate settings.
      </p>
    </aside>
  );
}
