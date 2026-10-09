import type { ModeName, Status, SymbolInfo, Timeframe } from "../types";
import type { Zone } from "../tz";

interface Props {
  symbols: SymbolInfo[]; timeframes: Timeframe[];
  symbol: string; tf: number; status: Status | null; connected: boolean;
  onSymbol: (s: string) => void; onTf: (t: number) => void;
  onRequestMode: (m: ModeName) => void;
  zone: Zone;
  onZone: (z: Zone) => void;
  soundOn: boolean; soundBlocked: boolean;
  onSound: () => void;
}

export function TopBar({ symbols, timeframes, symbol, tf, status, connected,
                         onSymbol, onTf, onRequestMode, zone, onZone,
                         soundOn, soundBlocked, onSound }: Props) {
  // Judge the SYMBOL on screen, not the global clock: a 24/7 instrument
  // ticking away must not make a closed forex market look live.
  const symAge = status?.symbol_age?.[symbol] ?? null;
  const symStale = status?.symbol_stale?.[symbol] ?? false;
  const feedOk = connected && status?.feed === "live" && !symStale;
  const ageLabel = symAge == null ? "no data"
    : symAge >= 3600 ? `${(symAge / 3600).toFixed(1)}h old`
    : symAge >= 60 ? `${Math.round(symAge / 60)}m old`
    : "live";
  const brokerOk = !!status?.broker?.connected;
  const mode = status?.mode ?? "manual";
  const killed = !!status?.kill_switch;

  return (
    <header className="top">
      <select className="sym-select" value={symbol} aria-label="Instrument"
              onChange={(e) => onSymbol(e.target.value)}>
        {symbols.map((s) => <option key={s.code} value={s.code}>{s.display}</option>)}
      </select>

      <div className="tf-group" role="group" aria-label="Timeframe">
        {timeframes.map((t) => (
          <button key={t.granularity} className="tf" aria-pressed={t.granularity === tf}
                  onClick={() => onTf(t.granularity)}>{t.label}</button>
        ))}
      </div>

      <div className="lamp"
           title={status ? `${symbol}: newest bar ${ageLabel} · transport ${status.transport}` : ""}>
        <span className={`dot ${feedOk ? "ok" : symStale ? "warn" : "bad"}`} />
        feed <b>{!connected ? "offline" : symStale ? ageLabel : "live"}</b>
        {status?.transport === "polled" && <span style={{ color: "var(--text-face)" }}>(polled)</span>}
      </div>

      <div className="lamp">
        <span className={`dot ${brokerOk ? "ok" : "bad"}`} />
        {status?.broker?.broker ?? "broker"} <b>{brokerOk ? "ok" : "down"}</b>
      </div>

      <div className="lamp">
        <span className="k">equity</span>
        <b className="num">{status?.broker ? status.broker.equity.toFixed(2) : "—"}</b>
      </div>

      <div className="lamp">
        <span className="k">day P&amp;L</span>
        <b className={`num ${(status?.realised_pnl ?? 0) >= 0 ? "pos" : "neg"}`}>
          {status ? (status.realised_pnl >= 0 ? "+" : "") + status.realised_pnl.toFixed(2) : "—"}
        </b>
      </div>

      <div className="lamp">
        <span className="k">trades</span><b className="num">{status?.trades_today ?? 0}</b>
      </div>

      <button className={`snd-btn ${soundOn ? (soundBlocked ? "blocked" : "on") : ""}`}
              onClick={onSound}
              aria-pressed={soundOn}
              title={!soundOn ? "Enable audio alerts on Chandelier signals"
                     : soundBlocked
                       ? "Audio enabled — click to let the browser allow sound"
                       : "Audio alerts on. Rising tone = BUY, falling = SELL."}>
        {soundOn ? (soundBlocked ? "♪!" : "♪") : "♪̶"}
      </button>

      <button className="tz-btn" onClick={() => onZone(zone === "IST" ? "UTC" : "IST")}
              title="Switch chart display timezone. Stored data stays UTC.">
        {zone}
      </button>

      <div className="grow" />

      <div className="mode-switch" role="group" aria-label="Execution mode">
        <button className="mode-btn" aria-pressed={mode === "manual"}
                onClick={() => onRequestMode("manual")}>MANUAL</button>
        <button className="mode-btn auto" aria-pressed={mode === "auto"} disabled={killed}
                title={killed ? "Kill switch engaged — release it first" : "Arm automated execution"}
                onClick={() => onRequestMode("auto")}>AUTO</button>
      </div>
    </header>
  );
}
