import { useEffect, useMemo, useRef, useState } from "react";
import {
  createChart, ColorType, CrosshairMode, LineStyle,
  type IChartApi, type ISeriesApi, type UTCTimestamp, type SeriesMarker,
  type MouseEventParams, type Time, type LogicalRange,
} from "lightweight-charts";
import type { Candle, LinePoint, IndicatorSpec, OverlayData, OverlayState,
  SignalEvent } from "../types";
import { type Zone, hhmm, dmy, isMidnight, fullStamp } from "../tz";

// Semantic line colours — Chandelier stop, MACD histogram.
const LONG = "#17b98a";
const SHORT = "#ef4d56";

/** Candle colours, kept separate from the line colours above.
 *
 *  A true blood red (#8B0000) manages only 2.0x contrast on this near-black
 *  ground, so a one-pixel doji body simply disappears. The body therefore uses
 *  a deep blood red and the border/wick a brighter one: the block reads as
 *  blood red while the outline keeps thin candles and long wicks legible.
 *
 *  Leaving the Chandelier stop line on the brighter coral (SHORT) is deliberate
 *  — against darker candles it now stands out more, not less. */
const CANDLE_UP = "#17b98a";
const CANDLE_DOWN = "#A8121E";        // deep blood red body
const CANDLE_DOWN_EDGE = "#D6202E";   // brighter edge so structure survives

/** Chandelier flip markers.
 *
 *  These deliberately do NOT reuse the candle colours, and not a brighter shade
 *  of them either. The worst case is structural: a BUY fires at the START of an
 *  uptrend, so a green marker lands exactly where green candles begin — and a
 *  SELL lands among red ones. Any same-hue marker disappears precisely when it
 *  matters most.
 *
 *  Parrot green works because the candle green is TEAL (hue 163°) while parrot
 *  green is yellow-green (~98°): 65° of hue separation plus 1.94x the relative
 *  luminance. Cyan, the obvious "not green" choice, is actually only 24° from
 *  the candle teal and was carrying the contrast on brightness alone.
 *  Orange sits 4x brighter than the candle red at a different hue again. */
const MARK_BUY = "#7CFF2E";    // parrot green — yellow-green, 65° off the teal candles
const MARK_SELL = "#FF8A3D";   // hot orange — 4x brighter than the candle red

/** Per-series colours. Kept here rather than in the backend spec so the palette
 *  stays a presentation concern. */
const SERIES_COLOR: Record<string, string> = {
  ema: "#4a9eff",
  bb_upper: "#8b93a5", bb_mid: "#c9a227", bb_lower: "#8b93a5",
  rsi: "#b46fd8",
  macd: "#4a9eff", macd_signal: "#f5a524", macd_hist: "#5b6778",
};

function baseOptions(digits: number, intraday: boolean, showTimeAxis: boolean,
                     zone: Zone, attribution = true) {
  return {
    layout: {
      background: { type: ColorType.Solid, color: "#07090d" },
      // Axis legibility: the previous #78828f on near-black was too faint to
      // read as an axis at all.
      textColor: "#a8b2c1",
      fontFamily: 'ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif',
      fontSize: 11,
      // Attribution is required, but once per screen -- not once per pane.
      attributionLogo: attribution,
    },
    grid: {
      vertLines: { color: "rgba(36,45,58,.7)" },
      horzLines: { color: "rgba(36,45,58,.7)" },
    },
    rightPriceScale: {
      borderColor: "#3a4757", borderVisible: true,
      // fixed width keeps the two panes' plot areas aligned
      minimumWidth: 68,
      scaleMargins: { top: 0.12, bottom: 0.12 },
      entireTextOnly: true,
    },
    timeScale: {
      borderColor: "#3a4757", borderVisible: true,
      visible: showTimeAxis,
      timeVisible: true, secondsVisible: false, rightOffset: 4,
      // The default tick marks drop the clock once a view spans several days,
      // which is useless on a 24/7 instrument. Always show the time intraday;
      // print the date at each midnight boundary.
      tickMarkFormatter: (time: Time) => {
        const t = time as number;
        if (!intraday) return dmy(t, zone);
        return isMidnight(t, zone) ? dmy(t, zone) : hhmm(t, zone);
      },
    },
    localization: {
      timeFormatter: (time: Time) => fullStamp(time as number, zone),
      priceFormatter: (p: number) => p.toFixed(digits),
    },
    crosshair: {
      mode: CrosshairMode.Magnet,
      vertLine: { color: "#6b7889", width: 1 as const, style: LineStyle.Dashed,
                  labelVisible: true, labelBackgroundColor: "#39465a" },
      horzLine: { color: "#6b7889", width: 1 as const, style: LineStyle.Dashed,
                  labelVisible: true, labelBackgroundColor: "#39465a" },
    },
    handleScale: { axisPressedMouseMove: { time: true, price: false } },
  };
}

interface Hover {
  time: number; open: number; high: number; low: number; close: number;
  stop: number | null; stopDir: number;
}

interface Props {
  candles: Candle[];
  line: LinePoint[];
  overlays: OverlayData;
  overlaySpecs: IndicatorSpec[];
  overlayState: OverlayState;
  digits: number;
  granularity: number;
  title: string;
  tfLabel: string;
  showChandelier: boolean;
  zone: Zone;
  /** Manual-mode one-click trade offer, anchored to the bar AFTER the signal
   *  bar -- the signal fires at close, so the next bar is the first one you
   *  could actually act on. */
  pending: SignalEvent | null;
  pendingLots: number;
  onTake: () => void;
  onDismiss: () => void;
}

export function Chart({ candles, line, overlays, overlaySpecs, overlayState,
                        digits, granularity, title, tfLabel, showChandelier,
                        zone, pending, pendingLots, onTake, onDismiss }: Props) {
  const mainBox = useRef<HTMLDivElement>(null);
  const oscBoxes = useRef<Map<string, HTMLDivElement>>(new Map());
  const mainChart = useRef<IChartApi | null>(null);
  const oscCharts = useRef<Map<string, IChartApi>>(new Map());
  const price = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const stopS = useRef<ISeriesApi<"Line"> | null>(null);
  const dynamic = useRef<Map<string, ISeriesApi<"Line" | "Histogram">>>(new Map());
  const fitted = useRef(false);
  const lineRef = useRef<LinePoint[]>(line);
  const syncing = useRef(false);
  const pendingRef = useRef<SignalEvent | null>(pending);
  const repositionRef = useRef<(() => void) | null>(null);
  const [hover, setHover] = useState<Hover | null>(null);
  const [anchor, setAnchor] = useState<{ x: number; y: number; flip: boolean } | null>(null);

  useEffect(() => { lineRef.current = line; }, [line]);
  useEffect(() => { pendingRef.current = pending; repositionRef.current?.(); }, [pending]);

  // which indicators want their own pane, and are actually on
  const oscIds = useMemo(() => overlaySpecs
    .filter((sp) => sp.series.some((se) => se.pane === "separate"))
    .filter((sp) => overlayState[sp.id]?.visible)
    .map((sp) => sp.id), [overlaySpecs, overlayState]);
  const hasOsc = oscIds.length > 0;
  const oscKey = oscIds.join(",");

  // ------------------------------------------------------------- chart setup
  useEffect(() => {
    if (!mainBox.current) return;
    fitted.current = false;          // a new instance must always re-frame
    const intraday = granularity < 86400;

    const main = createChart(mainBox.current, baseOptions(digits, intraday, !hasOsc, zone));
    price.current = main.addCandlestickSeries({
      upColor: CANDLE_UP, downColor: CANDLE_DOWN,
      borderUpColor: CANDLE_UP, borderDownColor: CANDLE_DOWN_EDGE,
      wickUpColor: CANDLE_UP, wickDownColor: CANDLE_DOWN_EDGE,
      priceFormat: { type: "price", precision: digits, minMove: 1 / 10 ** digits },
    });
    // ONE series carrying only the ACTIVE stop, coloured per point by direction.
    // Two series (one per side) would draw two continuous lines --
    // lightweight-charts connects across whitespace rather than breaking on it
    // -- which reads as a support/resistance channel and misrepresents it.
    stopS.current = main.addLineSeries({
      lineWidth: 2, color: LONG,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });
    mainChart.current = main;

    // One chart per oscillator so each keeps its own price scale.
    oscCharts.current.clear();
    oscIds.forEach((id, i) => {
      const box = oscBoxes.current.get(id);
      if (!box) return;
      const isLast = i === oscIds.length - 1;
      const c = createChart(box, {
        ...baseOptions(digits, intraday, isLast, zone, false),
        rightPriceScale: { borderColor: "#3a4757", borderVisible: true,
                           minimumWidth: 68, scaleMargins: { top: 0.18, bottom: 0.18 } },
      });
      oscCharts.current.set(id, c);
    });

    // Every pane shares one time axis: mirror the visible range across all of
    // them. The guard stops the subscriptions ping-ponging each other forever.
    const all = [main, ...oscCharts.current.values()];
    const unsubs: Array<() => void> = [];
    for (const src of all) {
      const handler = (r: LogicalRange | null) => {
        if (!r || syncing.current) return;
        syncing.current = true;
        for (const dst of all) if (dst !== src) dst.timeScale().setVisibleLogicalRange(r);
        syncing.current = false;
      };
      src.timeScale().subscribeVisibleLogicalRangeChange(handler);
      unsubs.push(() => src.timeScale().unsubscribeVisibleLogicalRangeChange(handler));
    }

    const onMove = (p: MouseEventParams) => {
      if (!p.time || !price.current) { setHover(null); return; }
      const bar = p.seriesData.get(price.current) as
        { open: number; high: number; low: number; close: number } | undefined;
      if (!bar) { setHover(null); return; }
      const t = p.time as number;
      const lp = lineRef.current.find((x) => x.epoch === t);
      setHover({ time: t, open: bar.open, high: bar.high, low: bar.low, close: bar.close,
                 stop: lp ? lp.value : null, stopDir: lp ? lp.direction : 0 });
    };
    main.subscribeCrosshairMove(onMove);

    // The chip is plain HTML over the canvas, so its position has to be
    // recomputed on every pan, zoom and new bar -- there is no anchoring API.
    const reposition = () => {
      const pend = pendingRef.current;
      if (!pend || !price.current) { setAnchor(null); return; }
      const at = (pend.bar_epoch + granularity) as UTCTimestamp;
      const x = main.timeScale().timeToCoordinate(at);
      const y = price.current.priceToCoordinate(pend.price);
      if (x == null || y == null) { setAnchor(null); return; }
      // The signal's next bar has not formed yet, so it lands in the right
      // margin. Flip the chip inward near the edge or it gets clipped by the
      // price scale and becomes unclickable.
      const w = mainBox.current?.clientWidth ?? 0;
      setAnchor({ x, y, flip: x > w - 96 });
    };
    repositionRef.current = reposition;
    main.timeScale().subscribeVisibleLogicalRangeChange(reposition);

    const ro = new ResizeObserver(() => {
      if (mainBox.current) main.resize(mainBox.current.clientWidth, mainBox.current.clientHeight);
      for (const [id, c] of oscCharts.current) {
        const b = oscBoxes.current.get(id);
        if (b) c.resize(b.clientWidth, b.clientHeight);
      }
    });
    ro.observe(mainBox.current);
    for (const b of oscBoxes.current.values()) ro.observe(b);

    return () => {
      main.unsubscribeCrosshairMove(onMove);
      main.timeScale().unsubscribeVisibleLogicalRangeChange(reposition);
      repositionRef.current = null;
      for (const u of unsubs) u();
      ro.disconnect();
      dynamic.current.clear();
      for (const c of oscCharts.current.values()) c.remove();
      oscCharts.current.clear();
      main.remove();
      mainChart.current = null;
    };
  }, [digits, granularity, oscKey, zone]);

  // ------------------------------------------------------------- price data
  useEffect(() => {
    if (!price.current || !candles.length) return;
    price.current.setData(candles.map((c) => ({
      time: c.epoch as UTCTimestamp,
      open: c.open, high: c.high, low: c.low, close: c.close,
    })));
    if (!fitted.current) {
      // fitContent() squeezes all 1000 bars into the pane, which is unreadable.
      // Frame the most recent window instead, as a terminal would.
      const n = candles.length;
      mainChart.current?.timeScale().setVisibleLogicalRange({
        from: n - Math.min(n, 220), to: n + 4,
      });
      fitted.current = true;
    }
    repositionRef.current?.();
  }, [candles]);

  useEffect(() => { setHover(null); }, [granularity, title]);

  // ------------------------------------------------------- chandelier stop
  useEffect(() => {
    if (!stopS.current) return;
    stopS.current.applyOptions({ visible: showChandelier });
    stopS.current.setData(showChandelier ? line.map((p) => ({
      time: p.epoch as UTCTimestamp, value: p.value,
      color: p.direction > 0 ? LONG : SHORT,
    })) : []);
    const markers: SeriesMarker<UTCTimestamp>[] = showChandelier ? line
      .filter((p) => p.flip)
      .map((p) => ({
        time: p.epoch as UTCTimestamp,
        position: p.direction > 0 ? "belowBar" : "aboveBar",
        color: p.direction > 0 ? MARK_BUY : MARK_SELL,
        shape: p.direction > 0 ? "arrowUp" : "arrowDown",
        size: 2,
        text: p.direction > 0 ? "B" : "S",
      })) : [];
    price.current?.setMarkers(markers);
  }, [line, showChandelier]);

  // ------------------------------------------------------------- overlays
  useEffect(() => {
    const main = mainChart.current;
    if (!main) return;
    const paneOf = new Map<string, "overlay" | "separate">();
    const kindOf = new Map<string, "line" | "histogram">();
    for (const sp of overlaySpecs) {
      for (const se of sp.series) { paneOf.set(se.key, se.pane); kindOf.set(se.key, se.kind); }
    }

    const wanted = new Set<string>();
    for (const [id, series] of Object.entries(overlays)) {
      for (const [key, points] of Object.entries(series)) {
        if (!points?.length) continue;
        // Each oscillator goes to ITS OWN chart. Sharing one pane would put
        // RSI (0-100) and MACD (around 0) on a single price scale and crush
        // the smaller of the two into a flat line.
        const pane = paneOf.get(key) ?? "overlay";
        const host = pane === "separate" ? oscCharts.current.get(id) : main;
        if (!host) continue;
        const handle = `${id}:${key}`;
        wanted.add(handle);

        let s = dynamic.current.get(handle);
        if (!s) {
          const color = SERIES_COLOR[key] ?? "#8b93a5";
          s = kindOf.get(key) === "histogram"
            ? host.addHistogramSeries({ color, priceLineVisible: false, lastValueVisible: false })
            : host.addLineSeries({
                color, lineWidth: key === "bb_mid" ? 1 : 2,
                lineStyle: key.startsWith("bb_") && key !== "bb_mid" ? LineStyle.Dotted : LineStyle.Solid,
                priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
              });
          dynamic.current.set(handle, s);
        }
        s.setData(points.map((p) => ({
          time: p.epoch as UTCTimestamp, value: p.value,
          ...(key === "macd_hist" ? { color: p.value >= 0 ? LONG : SHORT } : {}),
        })) as never);
      }
    }

    // drop series whose indicator was switched off, so hiding actually hides
    for (const [handle, s] of [...dynamic.current.entries()]) {
      if (wanted.has(handle)) continue;
      const [ownerId, seriesKey] = handle.split(":");
      const pane = paneOf.get(seriesKey) ?? "overlay";
      const host = pane === "separate" ? oscCharts.current.get(ownerId) : main;
      try { host?.removeSeries(s as never); } catch { /* chart already gone */ }
      dynamic.current.delete(handle);
    }
  }, [overlays, overlaySpecs]);

  // ------------------------------------------------------------- legend
  const lastBar = candles.length ? candles[candles.length - 1] : null;
  const lastStop = line.length ? line[line.length - 1] : null;
  const show: Hover | null = hover ?? (lastBar ? {
    time: lastBar.epoch, open: lastBar.open, high: lastBar.high,
    low: lastBar.low, close: lastBar.close,
    stop: lastStop ? lastStop.value : null,
    stopDir: lastStop ? lastStop.direction : 0,
  } : null);

  const f = (n: number) => n.toFixed(digits);
  const up = show ? show.close >= show.open : true;
  const chg = show ? show.close - show.open : 0;
  const chgPct = show && show.open ? (chg / show.open) * 100 : 0;

  return (
    <div className="chart-stack">
      <div className="chart-pane main">
        <div className="chart-legend">
          <span className="pair">{title}</span>
          <span className="tf">{tfLabel}</span>
          {show && (
            <>
              <span className="stamp">{fullStamp(show.time, zone)}</span>
              <span className="ohlc">
                <i>O</i><b className={up ? "pos" : "neg"}>{f(show.open)}</b>
                <i>H</i><b className={up ? "pos" : "neg"}>{f(show.high)}</b>
                <i>L</i><b className={up ? "pos" : "neg"}>{f(show.low)}</b>
                <i>C</i><b className={up ? "pos" : "neg"}>{f(show.close)}</b>
              </span>
              <span className={up ? "pos" : "neg"}>
                {chg >= 0 ? "+" : ""}{f(chg)} ({chg >= 0 ? "+" : ""}{chgPct.toFixed(3)}%)
              </span>
              {showChandelier && show.stop != null && (
                <span className="stoptag">
                  <i>CE</i>
                  <b className={show.stopDir > 0 ? "pos" : "neg"}>{f(show.stop)}</b>
                </span>
              )}
            </>
          )}
        </div>
        <div ref={mainBox} className="chart-canvas" />
        {pending && anchor && (
          <div className={`sig-chip ${pending.direction > 0 ? "buy" : "sell"}`
                          + (anchor.flip ? " flip" : "")}
               style={{ left: anchor.x, top: anchor.y }}>
            <button className="sig-take" onClick={onTake}
                    title={`Place a ${pending.action} order for ${pendingLots} lots`}>
              {pending.action} {pendingLots}
            </button>
            <button className="sig-x" onClick={onDismiss} aria-label="Dismiss signal">✕</button>
          </div>
        )}
      </div>
      {oscIds.map((id) => (
        <div className="chart-pane osc" key={id}>
          <div className="chart-legend osc-legend">
            <span className="osc-name">
              {overlaySpecs.find((sp) => sp.id === id)?.label ?? id}
            </span>
          </div>
          <div
            className="chart-canvas"
            ref={(el) => {
              if (el) oscBoxes.current.set(id, el);
              else oscBoxes.current.delete(id);
            }}
          />
        </div>
      ))}
    </div>
  );
}
