/** Audio alerts, synthesised with Web Audio — no asset files to load, no CSP
 *  surprises, and the tones stay distinguishable at low volume.
 *
 *  Browsers block audio until the user has interacted with the page, so the
 *  context starts suspended and is unlocked on the first real gesture. Until
 *  then `blocked` is true and the UI says so rather than silently not beeping —
 *  an alert you believe is armed but isn't is worse than no alert at all.
 */
export type Tone = "buy" | "sell" | "critical" | "fill" | "reject";

const KEY = "step-terminal.sound.v1";

let ctx: AudioContext | null = null;
let unlocked = false;

export function loadEnabled(): boolean {
  try { return localStorage.getItem(KEY) !== "off"; } catch { return true; }
}
export function saveEnabled(on: boolean) {
  try { localStorage.setItem(KEY, on ? "on" : "off"); } catch { /* private mode */ }
}

function context(): AudioContext | null {
  if (ctx) return ctx;
  const AC = window.AudioContext ?? (window as unknown as
    { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!AC) return null;
  try { ctx = new AC(); } catch { return null; }
  return ctx;
}

/** Call from a real user gesture (click/keydown) to satisfy autoplay policy. */
export async function unlock(): Promise<boolean> {
  const c = context();
  if (!c) return false;
  try {
    if (c.state === "suspended") await c.resume();
    unlocked = c.state === "running";
  } catch { unlocked = false; }
  return unlocked;
}

export function isBlocked(): boolean {
  const c = ctx;
  return !unlocked || !c || c.state !== "running";
}

/** One shaped tone. The attack/release ramps matter: a bare gate on an
 *  oscillator clicks audibly, which reads as a glitch rather than an alert. */
function beep(c: AudioContext, freq: number, start: number,
              dur: number, gain: number, type: OscillatorType = "sine") {
  const osc = c.createOscillator();
  const amp = c.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(freq, start);
  amp.gain.setValueAtTime(0.0001, start);
  amp.gain.exponentialRampToValueAtTime(gain, start + 0.012);
  amp.gain.exponentialRampToValueAtTime(0.0001, start + dur);
  osc.connect(amp).connect(c.destination);
  osc.start(start);
  osc.stop(start + dur + 0.02);
}

const VOICES: Record<Tone, (c: AudioContext, t: number, v: number) => void> = {
  // rising pair — reads as "up" without having to look
  buy: (c, t, v) => { beep(c, 587.33, t, 0.11, v); beep(c, 880.0, t + 0.1, 0.16, v); },
  // falling pair — the mirror of buy
  sell: (c, t, v) => { beep(c, 587.33, t, 0.11, v); beep(c, 392.0, t + 0.1, 0.16, v); },
  // three urgent pulses: auto disarmed, kill switch, feed lost
  critical: (c, t, v) => {
    for (let i = 0; i < 3; i++) beep(c, 988.0, t + i * 0.16, 0.1, v, "square");
  },
  fill: (c, t, v) => beep(c, 1046.5, t, 0.09, v * 0.7),
  reject: (c, t, v) => beep(c, 233.08, t, 0.22, v * 0.8, "sawtooth"),
};

export function play(tone: Tone, volume = 0.16) {
  const c = context();
  if (!c || c.state !== "running") return;      // blocked or unavailable
  try { VOICES[tone](c, c.currentTime + 0.01, volume); } catch { /* audio died */ }
}
