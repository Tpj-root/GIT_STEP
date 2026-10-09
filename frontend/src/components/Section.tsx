import { useEffect, useState, type ReactNode } from "react";

const KEY = "step-terminal.sections.v1";

function load(): Record<string, boolean> {
  try { return JSON.parse(localStorage.getItem(KEY) ?? "{}"); } catch { return {}; }
}
function save(s: Record<string, boolean>) {
  try { localStorage.setItem(KEY, JSON.stringify(s)); } catch { /* private mode */ }
}

interface Props {
  id: string;
  title: string;
  badge?: ReactNode;
  defaultOpen?: boolean;
  /** Force open regardless of stored state — used when arming AUTO, so the
   *  parameters that just went live can never be hidden behind a collapsed
   *  header. */
  forceOpen?: boolean;
  children: ReactNode;
}

export function Section({ id, title, badge, defaultOpen = true, forceOpen, children }: Props) {
  const [open, setOpen] = useState<boolean>(() => load()[id] ?? defaultOpen);

  useEffect(() => { if (forceOpen) setOpen(true); }, [forceOpen]);

  const toggle = () => {
    const next = !open;
    setOpen(next);
    save({ ...load(), [id]: next });
  };

  return (
    <>
      <button className="sec-head sec-toggle" onClick={toggle} aria-expanded={open}
              title={open ? `Collapse ${title}` : `Expand ${title}`}>
        <span className="caret" aria-hidden>{open ? "▾" : "▸"}</span>
        <span className="sec-title">{title}</span>
        {badge}
      </button>
      {open && children}
    </>
  );
}
