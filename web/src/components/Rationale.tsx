import { useEffect, useMemo, useState } from "react";
import type { RationaleStep, SessionState } from "../types";
import { TYPE_NAMES } from "../format";

const CHAR_MS = 22;
const PAUSE_MS = 650;
const KEEP = 6;

/** Lines the attackers actually produced (rationale_steps), with honest offline fallbacks. */
export function rationaleLines(st: SessionState | null): (RationaleStep & { who: string })[] {
  const out: (RationaleStep & { who: string })[] = [];
  for (const a of st?.attacks ?? []) {
    if (a.status !== "ok") continue;
    for (const r of a.rationale_steps ?? []) out.push({ ...r, who: a.attacker_name });
  }
  if (out.length) return out;
  const reader = st?.attacks?.find((a) => a.attacker_id === "reader" && a.status === "ok");
  const textIds = (st?.clues ?? []).filter((c) => ["text", "phone", "plate"].includes(c.type)).map((c) => c.id);
  for (const part of (reader?.top?.reasoning ?? "").split("; ").filter(Boolean)) {
    out.push({ text: part, clue_ids: textIds, who: "The Reader" });
  }
  for (const c of st?.clues ?? []) {
    if (!c.contribution || c.contribution.gain <= 0.005) continue;
    out.push({
      text: `${c.label} — ${c.description || TYPE_NAMES[c.type]}`,
      clue_ids: [c.id],
      who: "tested: erased and re-attacked",
    });
  }
  return out;
}

/** Shot 2: the attackers' reasoning types out beside the globe, synced to clue highlights. */
export default function Rationale({ st, onActive }: { st: SessionState | null; onActive: (ids: string[]) => void }) {
  const lines = useMemo(() => rationaleLines(st), [st]);
  const [idx, setIdx] = useState(0);
  const [chars, setChars] = useState(0);

  useEffect(() => {
    setIdx(0);
    setChars(0);
  }, [lines.length]);

  useEffect(() => {
    if (idx >= lines.length) {
      onActive([]);
      return;
    }
    const line = lines[idx];
    onActive(line.clue_ids);
    if (chars < line.text.length) {
      const t = setTimeout(() => setChars((c) => c + 1), CHAR_MS);
      return () => clearTimeout(t);
    }
    const t = setTimeout(() => {
      setIdx((i) => i + 1);
      setChars(0);
    }, PAUSE_MS);
    return () => clearTimeout(t);
  }, [idx, chars, lines]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!lines.length) return null;
  const start = Math.max(0, idx - KEEP + 1);
  return (
    <div className="rationale">
      <div className="kicker">What the attackers are reading</div>
      {lines.slice(start, Math.min(idx + 1, lines.length)).map((l, k) => {
        const i = start + k;
        const typing = i === idx;
        return (
          <div key={i} className={`rline ${typing ? "typing" : ""}`}>
            <span className="rwho">{l.who}</span>
            <span className="rtext">
              {typing ? l.text.slice(0, chars) : l.text}
              {typing && <i className="caret" />}
            </span>
          </div>
        );
      })}
    </div>
  );
}
