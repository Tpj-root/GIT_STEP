/** Display timezone.
 *
 * Deriv epochs are UTC and everything persisted -- the audit log, signal bar
 * epochs, idempotency keys -- stays UTC. Only the DISPLAY is shifted, and every
 * rendered timestamp carries its zone label so a screenshot can never be
 * misread against a log line.
 *
 * IST is a fixed +05:30 with no DST, so a constant offset is exact. Anything
 * with DST would need a real tz database, not an offset.
 */
export type Zone = "IST" | "UTC";

const OFFSET_MIN: Record<Zone, number> = { IST: 330, UTC: 0 };
const KEY = "step-terminal.tz.v1";

export function loadZone(): Zone {
  try {
    const v = localStorage.getItem(KEY);
    return v === "UTC" || v === "IST" ? v : "IST";
  } catch { return "IST"; }
}

export function saveZone(z: Zone) {
  try { localStorage.setItem(KEY, z); } catch { /* private mode */ }
}

/** Shift a UTC epoch so the UTC getters read as wall-clock time in `zone`. */
export function shifted(epoch: number, zone: Zone): Date {
  return new Date((epoch + OFFSET_MIN[zone] * 60) * 1000);
}

const d2 = (n: number) => String(n).padStart(2, "0");
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function hhmm(epoch: number, zone: Zone) {
  const d = shifted(epoch, zone);
  return `${d2(d.getUTCHours())}:${d2(d.getUTCMinutes())}`;
}
export function hhmmss(epoch: number, zone: Zone) {
  const d = shifted(epoch, zone);
  return `${d2(d.getUTCHours())}:${d2(d.getUTCMinutes())}:${d2(d.getUTCSeconds())}`;
}
export function dmy(epoch: number, zone: Zone) {
  const d = shifted(epoch, zone);
  return `${d.getUTCDate()} ${MON[d.getUTCMonth()]}`;
}
export function isMidnight(epoch: number, zone: Zone) {
  const d = shifted(epoch, zone);
  return d.getUTCHours() === 0 && d.getUTCMinutes() === 0;
}
export function fullStamp(epoch: number, zone: Zone) {
  const d = shifted(epoch, zone);
  return `${d2(d.getUTCDate())} ${MON[d.getUTCMonth()]} ${d.getUTCFullYear()} `
       + `${hhmm(epoch, zone)} ${zone}`;
}
