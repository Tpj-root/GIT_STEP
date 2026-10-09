import { useState } from "react";
import type { OrderEvent, Position, SignalEvent, Status, SymbolInfo } from "../types";
import { type Zone, hhmmss } from "../tz";



interface Props {
  positions: Position[]; signals: SignalEvent[]; orders: OrderEvent[];
  status: Status | null; symbols: SymbolInfo[];
  onClose: (ticket: string) => void; onKill: () => void; onRelease: () => void;
  zone: Zone;
}

type Tab = "positions" | "signals" | "orders";

export function BottomPanel({ positions, signals, orders, status, symbols,
                              onClose, onKill, onRelease, zone }: Props) {
  const [tab, setTab] = useState<Tab>("positions");
  const killed = !!status?.kill_switch;
  const dig = (code: string) => symbols.find((s) => s.code === code)?.digits ?? 2;

  return (
    <section className="bottom">
      <div className="tabs" role="tablist">
        {(["positions", "signals", "orders"] as Tab[]).map((t) => (
          <button key={t} role="tab" className="tab" aria-selected={tab === t} onClick={() => setTab(t)}>
            {t}<span className="count">
              {t === "positions" ? positions.length : t === "signals" ? signals.length : orders.length}
            </span>
          </button>
        ))}
        {killed ? (
          <button className="kill released" onClick={onRelease} title="Re-enable trading">
            ⏻ Release kill switch
          </button>
        ) : (
          <button className="kill" onClick={onKill} title="Close all positions and force manual (Ctrl+Shift+K)">
            ⏻ Close all &amp; stop
          </button>
        )}
      </div>

      <div className="tbl-wrap">
        {tab === "positions" && (
          positions.length === 0 ? <div className="empty">No open positions</div> : (
            <table>
              <thead><tr>
                <th>Ticket</th><th>Symbol</th><th>Side</th><th className="r">Lots</th>
                <th className="r">Entry</th><th className="r">Now</th><th className="r">SL</th>
                <th className="r">TP</th><th className="r">P&amp;L</th><th />
              </tr></thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.ticket}>
                    <td style={{ color: "var(--text-face)" }}>{p.ticket.slice(0, 8)}</td>
                    <td>{p.symbol}</td>
                    <td><span className={`pill ${p.side}`}>{p.side.toUpperCase()}</span></td>
                    <td className="r num">{p.lots}</td>
                    <td className="r num">{p.open_price.toFixed(dig(p.symbol))}</td>
                    <td className="r num">{p.current_price.toFixed(dig(p.symbol))}</td>
                    <td className="r num">{p.sl?.toFixed(dig(p.symbol)) ?? "—"}</td>
                    <td className="r num">{p.tp?.toFixed(dig(p.symbol)) ?? "—"}</td>
                    <td className={`r num ${p.profit >= 0 ? "pos" : "neg"}`}>
                      {p.profit >= 0 ? "+" : ""}{p.profit.toFixed(2)}
                    </td>
                    <td className="r">
                      <button className="linkish" onClick={() => onClose(p.ticket)}>close</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        )}

        {tab === "signals" && (
          signals.length === 0
            ? <div className="empty">No signals yet — Chandelier fires only on a direction flip at bar close</div>
            : (
              <table>
                <thead><tr>
                  <th>Bar time ({zone})</th><th>Symbol</th><th>TF</th><th>Signal</th>
                  <th className="r">Price</th><th>Executed</th><th>Idempotency key</th>
                </tr></thead>
                <tbody>
                  {signals.map((s) => (
                    <tr key={s.idem_key}>
                      <td className="num">{hhmmss(s.bar_epoch, zone)}</td>
                      <td>{s.symbol}</td>
                      <td className="num">{s.granularity}s</td>
                      <td><span className={`pill ${s.direction > 0 ? "buy" : "sell"}`}>{s.action}</span></td>
                      <td className="r num">{s.price}</td>
                      <td>{s.executed
                        ? <span className="pill auto">AUTO</span>
                        : <span style={{ color: "var(--text-face)" }}>logged only</span>}</td>
                      <td style={{ color: "var(--text-face)" }}>{s.idem_key}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )
        )}

        {tab === "orders" && (
          orders.length === 0 ? <div className="empty">No orders this session</div> : (
            <table>
              <thead><tr>
                <th>Result</th><th>Source</th><th>Symbol</th><th>Side</th>
                <th className="r">Fill</th><th>Detail</th>
              </tr></thead>
              <tbody>
                {orders.map((o, i) => (
                  <tr key={i}>
                    <td><span className={`pill ${o.ok ? "ok" : "rej"}`}>{o.ok ? "FILLED" : "REJECTED"}</span></td>
                    <td><span className={`pill ${o.source === "auto" ? "auto" : "manual"}`}>{o.source}</span></td>
                    <td>{o.symbol}</td>
                    <td><span className={`pill ${o.side === "buy" ? "buy" : "sell"}`}>{o.side?.toUpperCase()}</span></td>
                    <td className="r num">{o.price != null ? o.price : "—"}</td>
                    <td style={{ color: o.ok ? "var(--text-dim)" : "var(--short)" }}>
                      {o.ok ? o.message : `${o.reason}: ${o.detail}`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        )}
      </div>
    </section>
  );
}
