import { useCallback, useEffect, useRef, useState } from "react";
import { useStore } from "./store";
import { api } from "./api";
import { Chart } from "./components/Chart";
import { TopBar } from "./components/TopBar";
import { SidePanel } from "./components/SidePanel";
import { BottomPanel } from "./components/BottomPanel";
import { IndicatorPanel } from "./components/IndicatorPanel";
import { ArmDialog } from "./components/ArmDialog";
import type { ModeName, Side } from "./types";

export default function App() {
  const s = useStore();
  const [arming, setArming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [bootErr, setBootErr] = useState<string | null>(null);
  const [ceVisible, setCeVisible] = useState(true);

  const booted = useRef(false);
  useEffect(() => {
    if (booted.current) return;      // StrictMode double-invokes effects in dev
    booted.current = true;
    s.boot().catch((e) => setBootErr(String(e)));
  }, []);

  const mode: ModeName = s.status?.mode ?? "manual";
  const killed = !!s.status?.kill_switch;
  const sym = s.symbols.find((x) => x.code === s.symbol);
  const cfg = s.config ? s.config[mode] : null;

  const kill = useCallback(async () => {
    setBusy(true);
    try { await api.kill(); } finally { setBusy(false); }
  }, []);

  // When sound is enabled but the browser has not allowed audio yet, the first
  // click should UNLOCK it, not switch the feature off — otherwise the obvious
  // action on a warning icon is the one that makes things worse.
  const toggleSound = async () => {
    if (s.soundOn && s.soundBlocked) { await s.unlockSound(); return; }
    await s.setSound(!s.soundOn);
  };

  // Browsers block audio until a real gesture. Unlock on the first one, so the
  // first signal after load actually makes a sound instead of silently failing.
  useEffect(() => {
    const go = () => { void s.unlockSound(); };
    window.addEventListener("pointerdown", go, { once: true });
    window.addEventListener("keydown", go, { once: true });
    return () => {
      window.removeEventListener("pointerdown", go);
      window.removeEventListener("keydown", go);
    };
  }, []);

  // Kill switch must be reachable without hunting for a button.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === "k") { e.preventDefault(); void kill(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [kill]);

  const requestMode = async (m: ModeName) => {
    if (m === "auto") { setArming(true); return; }  // deliberate
    await s.setMode("manual").catch(() => {});      // instant, no friction
  };

  const confirmArm = async () => {
    setArming(false);
    await s.setMode("auto").catch(() => {});
  };

  // The signal chip is a manual-mode convenience only. In auto the order is
  // already placed, and while killed nothing may be sent at all.
  const pending = mode === "manual" && !killed ? s.pendingSignal : null;

  const takeSignal = async () => {
    const sig = s.pendingSignal;
    if (!sig) return;
    s.clearPending();          // clear first so a double-click cannot double-fire
    await trade(sig.direction > 0 ? "buy" : "sell", sig.idem_key);
  };

  const trade = async (side: Side, idemKey?: string) => {
    setBusy(true);
    try {
      const r = await api.order({ symbol: s.symbol, side, idem_key: idemKey });
      if (!r.ok) {
        useStore.setState((st) => ({
          alerts: [...st.alerts, { level: "warn", message: `Order rejected — ${r.reason}: ${r.detail}` }],
        }));
      }
    } catch (e) {
      useStore.setState((st) => ({ alerts: [...st.alerts, { level: "warn", message: String(e) }] }));
    } finally { setBusy(false); }
  };

  if (bootErr) {
    return (
      <div style={{ padding: 28, maxWidth: 560 }}>
        <h1 style={{ fontSize: 15, margin: "0 0 10px" }}>Backend unreachable</h1>
        <p style={{ color: "var(--text-dim)", lineHeight: 1.6 }}>
          Could not reach <code>{api.base}</code>.<br />{bootErr}
        </p>
        <p style={{ color: "var(--text-face)" }}>
          Start it with:<br />
          <code>cd backend &amp;&amp; uvicorn app.main:app --port 8010</code>
        </p>
      </div>
    );
  }

  const hasRail = killed || mode === "auto";

  return (
    <div className={`app ${hasRail ? "has-rail" : ""} ${mode === "auto" ? "armed" : ""} ${killed ? "killed" : ""}`}>
      {killed && (
        <div className="armed-rail killed-rail">
          <span>⏻ Kill switch engaged — trading disabled</span>
          <span>Release it from the panel below to resume</span>
        </div>
      )}
      {!killed && mode === "auto" && (
        <div className="armed-rail">
          <span>● AUTO ARMED — {s.status?.armed_on ?? sym?.display} only · Chandelier flips place live orders</span>
          <span>{cfg?.lots} lots · SL {cfg?.stop_loss_points ?? "—"} · max loss ${cfg?.max_daily_loss ?? "—"}</span>
        </div>
      )}

      <TopBar symbols={s.symbols} timeframes={s.timeframes} symbol={s.symbol} tf={s.tf}
              status={s.status} connected={s.connected}
              onSymbol={(v) => s.select(v, s.tf)} onTf={(v) => s.select(s.symbol, v)}
              onRequestMode={requestMode}
              zone={s.zone} onZone={s.setZone}
              soundOn={s.soundOn} soundBlocked={s.soundBlocked}
              onSound={toggleSound} />

      <div className="middle">
        <div className="chart-wrap">
          {s.candles.length === 0 && <div className="chart-empty">loading market data…</div>}
          <Chart candles={s.candles} line={s.line} digits={sym?.digits ?? 2}
                 overlays={s.overlays} overlaySpecs={s.overlaySpecs}
                 overlayState={s.overlayState} showChandelier={ceVisible}
                 granularity={s.tf} title={sym?.display ?? s.symbol}
                 tfLabel={s.timeframes.find((t) => t.granularity === s.tf)?.label ?? ""}
                 zone={s.zone}
                 pending={pending} pendingLots={cfg?.lots ?? 0.01}
                 onTake={takeSignal} onDismiss={s.clearPending} />
        </div>

        <SidePanel indicator={s.indicator}
                   indicatorsSlot={
                     <IndicatorPanel
                       specs={s.overlaySpecs} state={s.overlayState}
                       onToggle={(id, v) => s.toggleOverlay(id, v)}
                       onParam={(id, n, v) => s.setOverlayParam(id, n, v)}
                       chandelierVisible={ceVisible}
                       onChandelierVisible={setCeVisible}
                       period={s.indicatorParams.period}
                       multiplier={s.indicatorParams.multiplier}
                       onChandelierParam={(p) => s.setParams(p)} />
                   }
                   config={cfg} mode={mode}
                   onConfig={(patch) => s.setConfig(mode, patch)}
                   symbol={sym} status={s.status} onTrade={trade} busy={busy} />
      </div>

      <BottomPanel positions={s.positions} signals={s.signals} orders={s.orders}
                   status={s.status} symbols={s.symbols} zone={s.zone}
                   onClose={(t) => api.close(t)} onKill={kill}
                   onRelease={() => api.releaseKill()} />

      {arming && cfg && (
        <ArmDialog config={cfg} symbol={sym} period={s.indicatorParams.period}
                   multiplier={s.indicatorParams.multiplier}
                   tfLabel={s.timeframes.find((t) => t.granularity === s.tf)?.label ?? ""}
                   onCancel={() => setArming(false)} onConfirm={confirmArm} />
      )}

      {s.alerts.length > 0 && (
        <div className="alerts">
          {s.alerts.map((a, i) => (
            <div key={i} className={`alert ${a.level}`}>
              <span>{a.message}</span>
              <button onClick={() => s.dismissAlert(i)} aria-label="Dismiss">✕</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
