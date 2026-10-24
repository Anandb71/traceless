import { useEffect, useMemo, useRef, useState } from "react";
import type { SessionState } from "../types";
import { km } from "../format";
import { streetMatch } from "../street";
import Counter from "../components/Counter";

const MAX_LINES = 160;

/** Shot 4 — the match: query photo vs the matching street photo, joined by real inlier pairs. */
export default function MatchView({ st, precise }: { st: SessionState; precise: boolean }) {
  const sm = streetMatch(st);
  const wrap = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState({ w: 0, h: 0 });
  const [refAR, setRefAR] = useState(4 / 3);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setBox({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const pairs = useMemo(() => {
    const kp = sm?.match.keypoint_pairs ?? [];
    if (kp.length <= MAX_LINES) return kp;
    const step = kp.length / MAX_LINES;
    return Array.from({ length: MAX_LINES }, (_, i) => kp[Math.floor(i * step)]);
  }, [sm]);

  if (!sm || !st.image) return null;
  const { attack, match } = sm;
  const cov = st.street_coverage!;

  // Layout: two images side by side, same height, centered, 4% gap.
  const qAR = st.image.w / st.image.h;
  const gap = box.w * 0.04;
  const hFit = Math.min(box.h, (box.w - gap) / (qAR + refAR));
  const qw = hFit * qAR;
  const rw = hFit * refAR;
  const x0 = (box.w - (qw + gap + rw)) / 2;
  const y0 = (box.h - hFit) / 2;
  const rx0 = x0 + qw + gap;

  return (
    <div className="match">
      <div className="match-head">
        <div className="kicker">Attacker C · street-level match · {attack.attacker_name}</div>
        <h2>
          Placed <span className="red">{<Counter value={attack.distance_km} format={km} />}</span> from where you stood.
        </h2>
        <div className="match-chips">
          <span className="chip">
            {cov.n_images.toLocaleString()} street photos within {cov.radius_km} km · {cov.source}
          </span>
          <span className="chip">{match.inliers} verified keypoint matches (threshold {cov.match_threshold})</span>
          {precise && <span className="chip warn">{match.lat.toFixed(5)}, {match.lon.toFixed(5)}</span>}
        </div>
      </div>
      <div className="match-stage" ref={wrap}>
        {box.w > 0 && (
          <>
            <img className="match-img" src={st.image.url} alt="your photo" style={{ left: x0, top: y0, width: qw, height: hFit }} />
            <img
              className="match-img"
              src={match.url}
              alt="matching street photo"
              onLoad={(e) => setRefAR(e.currentTarget.naturalWidth / Math.max(1, e.currentTarget.naturalHeight))}
              style={{ left: rx0, top: y0, width: rw, height: hFit }}
            />
            <svg className="match-lines" width={box.w} height={box.h}>
              <defs>
                <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
                  <feGaussianBlur stdDeviation="2.2" result="b" />
                  <feMerge>
                    <feMergeNode in="b" />
                    <feMergeNode in="SourceGraphic" />
                  </feMerge>
                </filter>
              </defs>
              {pairs.map(([qx, qy, rx, ry], i) => {
                const ax = x0 + qx * qw;
                const ay = y0 + qy * hFit;
                const bx = rx0 + rx * rw;
                const by = y0 + ry * hFit;
                const len = Math.hypot(bx - ax, by - ay);
                const hue = 330 + (i / Math.max(1, pairs.length)) * 60; // pink -> amber
                return (
                  <g key={i} filter="url(#glow)" style={{ animationDelay: `${(i / pairs.length) * 1.6}s` }} className="mline">
                    <line
                      x1={ax}
                      y1={ay}
                      x2={bx}
                      y2={by}
                      stroke={`hsl(${hue % 360} 100% 62%)`}
                      strokeWidth={1.1}
                      strokeOpacity={0.75}
                      strokeDasharray={len}
                      strokeDashoffset={len}
                      style={{ ["--len" as string]: `${len}` }}
                    />
                    <circle cx={ax} cy={ay} r={2.2} fill="#fff" />
                    <circle cx={bx} cy={by} r={2.2} fill="#fff" />
                  </g>
                );
              })}
            </svg>
            <div className="match-attrib" style={{ left: rx0, top: y0 + hFit + 8, width: rw }}>
              {match.source === "mapillary" ? "Mapillary (CC BY-SA)" : "Wikimedia Commons"}
              {match.attribution ? ` · ${match.attribution}` : ""}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/** Reattack: the pre-erasure match lines drawn on the photo, snapping and falling. */
export function SnapLines({ st }: { st: SessionState }) {
  const sm = streetMatch(st);
  const [gone, setGone] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setGone(true), 2600);
    return () => clearTimeout(t);
  }, []);
  if (!sm || gone) return null;
  const kp = sm.match.keypoint_pairs.slice(0, 120);
  return (
    <svg className="snap-lines" viewBox="0 0 100 100" preserveAspectRatio="none">
      {kp.map(([qx, qy, , ry], i) => (
        <line
          key={i}
          x1={qx * 100}
          y1={qy * 100}
          x2={100}
          y2={ry * 100}
          className="snap"
          style={{ animationDelay: `${0.4 + (i / kp.length) * 1.2}s`, transformOrigin: `${qx * 100}% ${qy * 100}%` }}
        />
      ))}
    </svg>
  );
}
