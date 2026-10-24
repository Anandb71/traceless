import type { AttackResult, SessionState } from "../types";
import { TYPE_COLORS, TYPE_NAMES, area, km } from "../format";
import { streetAttack, streetMatch } from "../street";

const pending = (what: string) => <div className="pending">{what}</div>;

export function ZeroPanel({ st }: { st: SessionState | null }) {
  const ex = st?.exif;
  if (!ex) return pending("Reading the file…");
  return (
    <div className="zero">
      <div className="kicker">Clue zero · the file itself</div>
      {ex.has_gps ? (
        <>
          <h2>
            Your photo carries its own GPS coordinates<span className="red">.</span>
          </h2>
          <p className="big">
            {st?.privacy?.precise && ex.gps ? `${ex.gps.lat.toFixed(5)}, ${ex.gps.lon.toFixed(5)} — ` : ""}
            {ex.gps_region}
          </p>
        </>
      ) : (
        <h2>No GPS in this file.</h2>
      )}
      <div className="stamp-row">
        <span className={`stamp ${ex.stripped ? "on" : ""}`}>STRIPPED</span>
        <span className="muted">
          {ex.fields.length} metadata field{ex.fields.length === 1 ? "" : "s"} removed{ex.camera ? ` · ${ex.camera}` : ""}. Attackers only ever see pixels.
        </span>
      </div>
      <p className="quote">“Most apps strip this. Nobody strips the picture.”</p>
    </div>
  );
}

export function AttackPanel({ st, frame, frames }: { st: SessionState | null; frame: number; frames: number }) {
  if (!st?.attacks) return pending("Attacking the pixels…");
  const done = frames > 0 && frame >= frames - 1;
  if (st.already_safe && done) {
    const b = best(st.attacks);
    return (
      <div className="goodnews">
        <div className="kicker">Good news</div>
        <h2>This one is already hard to place.</h2>
        <p>
          Closest attacker: {b ? `${km(b.distance_km)} off (${b.attacker_name})` : "no guess"} · search area{" "}
          {area(b?.credible_area_km2)}. Nothing here pins you down within {st.radius_km} km.
        </p>
      </div>
    );
  }
  return (
    <div className="attackers">
      <div className="kicker">The stalker's AIs · pixels only</div>
      {st.attacks.map((a) => (
        <AttackerRow key={a.attacker_id} a={a} />
      ))}
      {st.street_coverage?.available && streetAttack(st) && !streetMatch(st) && (
        <div className="nomatch">
          No street-level match among {st.street_coverage.n_images.toLocaleString()} street photos (coverage {st.street_coverage.radius_km} km).
        </div>
      )}
      {!frames && <div className="pending small">measuring which clues matter…</div>}
    </div>
  );
}

function AttackerRow({ a, before }: { a: AttackResult; before?: AttackResult }) {
  const tag = `${a.offline ? "offline" : "cloud"} · ${a.family}${a.adaptive ? " · adaptive" : ""}`;
  if (a.status !== "ok")
    return (
      <div className="arow dim">
        <span className="aname">{a.attacker_name}</span>
        <span className="atag">{tag}</span>
        <span className="aval">{a.status === "skipped" ? "not configured" : a.status}</span>
      </div>
    );
  const miss = a.within_radius !== true; // no guess at all also counts as a miss
  return (
    <div className={`arow ${miss ? "miss" : "hit"}`}>
      <span className="aname">{a.attacker_name}</span>
      <span className="atag">{tag}</span>
      <span className="aval">
        {before && before.distance_km != null && <s>{km(before.distance_km)}</s>}
        {a.distance_km == null ? (a.error ?? "no guess") : km(a.distance_km)}
      </span>
    </div>
  );
}

export function CluesPanel({ st, highlight }: { st: SessionState | null; highlight?: string | null }) {
  const clues = st?.clues ?? [];
  const measured = clues.filter((c) => c.contribution);
  if (!measured.length) return pending("Measuring each clue by ablation…");
  const max = Math.max(0.05, ...measured.map((c) => Math.abs(c.contribution!.gain)));
  const top = measured.find((c) => c.contribution!.rank === 1);
  return (
    <div className="clues">
      <div className="kicker">Which clues gave you away · measured by ablation (GeoCLIP)</div>
      {top && top.contribution!.gain > 0.01 && (
        <p className="headline">
          {top.label} alone cut the search area from <b>{area(top.contribution!.area_without_km2)}</b> to <b>{area(top.contribution!.area_with_km2)}</b>.
        </p>
      )}
      <div className="bars">
        {clues.map((c) => {
          const g = c.contribution?.gain ?? 0;
          return (
            <div key={c.id} className={`bar ${c.contribution ? "" : "dim"} ${highlight === c.id ? "hl" : ""}`}>
              <span className="bnum" style={{ background: TYPE_COLORS[c.type] }}>
                {c.index}
              </span>
              <span className="blabel">
                {c.label}
                <small>{TYPE_NAMES[c.type]}</small>
              </span>
              <span className="btrack">
                <i style={{ width: `${(Math.max(0, g) / max) * 100}%`, background: TYPE_COLORS[c.type] }} />
              </span>
              <span className="bval">{c.contribution ? `×${Math.pow(10, g).toFixed(g > 1 ? 0 : 1)}` : c.possible_only ? "precaution" : "—"}</span>
            </div>
          );
        })}
      </div>
      <div className="foot">×N = how many times larger the 90% search area gets when that clue alone is erased.</div>
    </div>
  );
}

export function ErasePanel({ st }: { st: SessionState | null }) {
  const d = st?.defense;
  if (!d || !st?.protected) return pending("Erasing clues and re-attacking…");
  const q = d.rounds[d.rounds.length - 1]?.quality;
  const byFix = d.actions.reduce<Record<string, number>>((m, a) => ((m[a.fix] = (m[a.fix] ?? 0) + 1), m), {});
  return (
    <div className="erase">
      <div className="kicker">Erase · least destructive fix per clue</div>
      <h2>The clues dissolve. The moment stays.</h2>
      <div className="fixes">
        {Object.entries(byFix).map(([k, v]) => (
          <span key={k} className="fix">
            {v} × {k === "inpaint" ? "inpainted (LaMa)" : k === "blur" ? "blurred" : k === "soften" ? "softened" : k}
          </span>
        ))}
      </div>
      {q && (
        <div className="qrow">
          <span>
            <b>{q.pct_pixels_changed.toFixed(1)}%</b> pixels changed
          </span>
          <span>
            SSIM <b>{q.ssim?.toFixed(3) ?? "—"}</b>
          </span>
          <span>
            LPIPS <b>{q.lpips?.toFixed(3) ?? "—"}</b>
          </span>
          <span>
            face pixels changed <b>{q.face_pixels_changed}</b>
          </span>
        </div>
      )}
    </div>
  );
}

export function ReattackPanel({ st }: { st: SessionState | null }) {
  const d = st?.defense;
  if (!d) return pending("Re-attacking…");
  const last = d.rounds[d.rounds.length - 1];
  const before = new Map((st?.attacks ?? []).map((a) => [a.attacker_id, a]));
  before.set("geoclip-adaptive", before.get("geoclip")!);
  before.set("cloud-adaptive", before.get("cloud")!);
  return (
    <div className="attackers">
      <div className="kicker">
        Re-attack · different AIs, one told it was edited · round {last?.round}/{d.max_rounds}
      </div>
      {last?.attacks.map((a) => (
        <AttackerRow key={a.attacker_id} a={a} before={before.get(a.attacker_id)} />
      ))}
      <p className={`verdict ${d.reached_target ? "ok" : "warn"}`}>{d.verdict}</p>
    </div>
  );
}

export function best(rs: AttackResult[]): AttackResult | undefined {
  return rs.filter((r) => r.status === "ok" && r.distance_km != null).sort((a, b) => a.distance_km! - b.distance_km!)[0];
}
