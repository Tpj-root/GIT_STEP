import type { IndicatorSpec, OverlayState } from "../types";
import { Section } from "./Section";

interface Props {
  specs: IndicatorSpec[];
  state: OverlayState;
  onToggle: (id: string, visible: boolean) => void;
  onParam: (id: string, name: string, value: number) => void;

  // Chandelier is the signal source, not a display overlay, so it is listed
  // first and separately: it can be hidden from the chart but never switched
  // off, because auto mode trades from it.
  chandelierVisible: boolean;
  onChandelierVisible: (v: boolean) => void;
  period: number;
  multiplier: number;
  onChandelierParam: (p: { period?: number; multiplier?: number }) => void;
  digitsHint?: string;
}

function Eye({ on, onClick, label }: { on: boolean; onClick: () => void; label: string }) {
  return (
    <button className={`eye ${on ? "on" : ""}`} onClick={onClick}
            aria-pressed={on} title={on ? `Hide ${label}` : `Show ${label}`}>
      {on ? "●" : "○"}
    </button>
  );
}

function ParamInput({ id, name, label, value, min, max, step, kind, onChange }: {
  id: string; name: string; label: string; value: number;
  min: number; max: number; step: number; kind: "int" | "float";
  onChange: (v: number) => void;
}) {
  return (
    <label className="param" title={label}>
      <span>{label}</span>
      <input type="number" value={value} min={min} max={max} step={step}
             id={`${id}-${name}`}
             onChange={(e) => {
               const raw = e.target.value;
               if (raw === "") return;
               const v = kind === "int" ? parseInt(raw, 10) : parseFloat(raw);
               if (!Number.isFinite(v) || v < min || v > max) return;
               onChange(v);
             }} />
    </label>
  );
}

export function IndicatorPanel({
  specs, state, onToggle, onParam,
  chandelierVisible, onChandelierVisible, period, multiplier, onChandelierParam,
}: Props) {
  return (
    <Section id="indicators" title="Indicators" defaultOpen={false}
             badge={<span style={{ color: "var(--text-face)", letterSpacing: 0,
                                   textTransform: "none" }}>
                      {1 + specs.filter((s) => state[s.id]?.visible).length} on
                    </span>}>
      <div className="ind-row">
        <div className="ind-head">
          <Eye on={chandelierVisible} onClick={() => onChandelierVisible(!chandelierVisible)}
               label="Chandelier Exit" />
          <span className="ind-name">Chandelier Exit</span>
          <span className="ind-tag" title="This indicator drives automated execution">signal</span>
        </div>
        <div className="ind-params">
          <ParamInput id="ce" name="period" label="period" value={period}
                      min={1} max={200} step={1} kind="int"
                      onChange={(v) => onChandelierParam({ period: v })} />
          <ParamInput id="ce" name="multiplier" label="mult" value={multiplier}
                      min={0.1} max={10} step={0.1} kind="float"
                      onChange={(v) => onChandelierParam({ multiplier: v })} />
        </div>
      </div>

      {specs.map((sp) => {
        const st = state[sp.id] ?? {};
        const on = !!st.visible;
        const pane = sp.series.some((s) => s.pane === "separate") ? "pane" : "overlay";
        return (
          <div className={`ind-row ${on ? "" : "off"}`} key={sp.id}>
            <div className="ind-head">
              <Eye on={on} onClick={() => onToggle(sp.id, !on)} label={sp.label} />
              <span className="ind-name">{sp.label}</span>
              <span className="ind-tag dim">{pane}</span>
            </div>
            {on && (
              <div className="ind-params">
                {sp.params.map((p) => (
                  <ParamInput key={p.name} id={sp.id} name={p.name} label={p.label.toLowerCase()}
                              value={Number(st[p.name] ?? p.default)}
                              min={p.min} max={p.max} step={p.step} kind={p.kind}
                              onChange={(v) => onParam(sp.id, p.name, v)} />
                ))}
              </div>
            )}
          </div>
        );
      })}
    </Section>
  );
}
