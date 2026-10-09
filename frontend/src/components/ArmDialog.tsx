import { useEffect, useRef } from "react";
import type { ModeConfig, SymbolInfo } from "../types";

interface Props {
  config: ModeConfig; symbol: SymbolInfo | undefined;
  period: number; multiplier: number;
  tfLabel: string;
  onCancel: () => void; onConfirm: () => void;
}

/** Arming is the most consequential control in the app, so it is deliberate:
 *  it shows the exact parameters about to go live. Disarming needs no dialog —
 *  the safe direction must stay frictionless. */
export function ArmDialog({ config, symbol, period, multiplier, tfLabel,
                            onCancel, onConfirm }: Props) {
  const confirmRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    confirmRef.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onCancel(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  const row = (k: string, v: string) => (<><dt>{k}</dt><dd className="num">{v}</dd></>);

  return (
    <div className="scrim" role="dialog" aria-modal="true" aria-labelledby="arm-h">
      <div className="dialog">
        <h2 id="arm-h">Arm automated execution</h2>
        <div className="body">
          <p className="warn">
            Chandelier flips on <b>{symbol?.display ?? "—"} {tfLabel}</b> will place
            live orders without further confirmation. These exact parameters go live:
          </p>
          <dl>
            {row("Instrument", `${symbol?.display ?? "—"} (${symbol?.mt5_symbol ?? "—"})`)}
            {row("Timeframe", `${tfLabel} — signals on OTHER timeframes are ignored`)}
            {row("Chandelier", `period ${period} · multiplier ${multiplier}`)}
            {row("Order size", `${config.lots} lots`)}
            {row("Stop loss", config.stop_loss_points ? `${config.stop_loss_points} pts` : "NONE")}
            {row("Take profit", config.take_profit_points ? `${config.take_profit_points} pts` : "disabled")}
            {row("Max positions", String(config.max_concurrent_positions))}
            {row("Max daily loss", config.max_daily_loss ? `$${config.max_daily_loss}` : "NONE")}
            {row("Max trades/day", config.max_trades_per_day ? String(config.max_trades_per_day) : "NONE")}
            {row("On signal", config.signal_action)}
          </dl>
          <div className="actions">
            <button className="btn-cancel" onClick={onCancel}>Cancel</button>
            <button className="btn-arm" ref={confirmRef} onClick={onConfirm}>Arm AUTO</button>
          </div>
        </div>
      </div>
    </div>
  );
}
