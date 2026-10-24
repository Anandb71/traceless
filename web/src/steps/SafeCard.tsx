import type { SessionState } from "../types";
import { area, km } from "../format";
import { best } from "./Panels";

export default function SafeCard({ st }: { st: SessionState | null }) {
  if (!st) return null;
  if (st.already_safe) {
    const b = best(st.attacks ?? []);
    return (
      <div className="card">
        <div className="card-main">
          <div className="kicker">Already hard to place</div>
          <div className="card-big">{km(b?.distance_km)}</div>
          <div className="muted">closest AI guess · search area {area(b?.credible_area_km2)}</div>
          <div className="card-grid">
            <Cell k="location data" v={st.exif?.stripped ? "stripped" : "—"} />
            <Cell k="pixels changed" v="0%" />
          </div>
        </div>
      </div>
    );
  }
  const c = st.card;
  if (!c) return <div className="pending">Building your card…</div>;
  const dl = st.protected?.download;
  const url = dl ? `${location.protocol}//${hostFor()}${dl}` : null;
  return (
    <div className="card">
      <div className="card-main">
        <div className="kicker">{c.reached_target ? "Safe to post" : "Safer to post"}</div>
        <div className="card-ba">
          <div>
            <div className="card-big red">{km(c.before_km)}</div>
            <div className="muted">before · {c.before_by}</div>
          </div>
          <div className="arrow">→</div>
          <div>
            <div className="card-big teal">{km(c.after_km)}</div>
            <div className="muted">after · best of {c.attackers.length} attackers</div>
          </div>
        </div>
        <div className="card-grid">
          <Cell k="search area" v={c.area_growth ? `×${c.area_growth >= 10 ? Math.round(c.area_growth).toLocaleString() : c.area_growth.toFixed(1)}` : "—"} />
          <Cell k="pixels changed" v={c.pct_pixels_changed != null ? `${c.pct_pixels_changed.toFixed(1)}%` : "—"} />
          <Cell k="location data" v={c.metadata_stripped ? "stripped" : "—"} />
          <Cell k="face" v={c.face_pixels_changed === 0 ? "untouched" : `${c.face_pixels_changed} px`} />
        </div>
        <div className="verdict-small">{c.verdict}</div>
      </div>
      {url && (
        <div className="card-qr">
          <img src={`/api/qr?data=${encodeURIComponent(url)}`} alt="download QR" />
          <span>scan to download</span>
        </div>
      )}
    </div>
  );
}

function hostFor(): string {
  // phones can't reach "localhost": use the LAN address the backend reported
  const h = (window as unknown as { __BASE__?: string }).__BASE__;
  return h ?? location.host;
}

function Cell({ k, v }: { k: string; v: string }) {
  return (
    <div className="cell">
      <b>{v}</b>
      <span>{k}</span>
    </div>
  );
}
