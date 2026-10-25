import { useEffect, useState } from "react";
import { api } from "../api";
import { area, km } from "../format";

interface Arm {
  acc: Record<string, number>;
  median_km: number | null;
  median_area_km2: number | null;
  n: number;
}
interface BenchAttacker {
  name: string;
  before: Arm;
  after: Arm;
}
interface BenchSubset {
  label: string;
  n: number;
  attackers: Record<string, BenchAttacker>;
  quality: { lpips_mean: number | null; ssim_mean: number | null; pct_changed_median: number | null };
}
interface BenchResult {
  available: boolean;
  dataset: string;
  date: string;
  radius_km: number;
  thresholds_km: number[];
  subsets: BenchSubset[];
  failures: { id: string; error: string }[];
  command: string;
}

const T_NAMES: Record<string, string> = { "1": "street", "25": "city", "200": "region", "750": "country", "2500": "continent" };

export default function Bench() {
  const [b, setB] = useState<BenchResult | null>(null);
  useEffect(() => {
    api.bench().then(setB).catch(() => setB(null));
  }, []);
  if (!b) return <div className="bench pending">Loading benchmark…</div>;
  if (!b.available)
    return (
      <div className="bench">
        <h2>No benchmark run yet</h2>
        <p className="muted">
          Run <code>make bench</code> — results land in bench/results/latest.json and feed this page and the README.
        </p>
      </div>
    );
  const main = b.subsets[0];
  const g = main.attackers["geoclip"];
  return (
    <div className="bench">
      <div className="kicker">
        Benchmark · {b.dataset} · {b.date} · `{b.command}`
      </div>
      {g && (
        <h2 className="bench-head">
          On <b>{main.n}</b> public photos with known locations, city-level placement (≤25 km) dropped from{" "}
          <span className="red">{pct(g.before.acc["25"])}</span> to <span className="teal">{pct(g.after.acc["25"])}</span>; median error went from{" "}
          <span className="red">{km(g.before.median_km)}</span> to <span className="teal">{km(g.after.median_km)}</span>.
        </h2>
      )}
      {b.subsets.map((s) => (
        <div key={s.label} className="bench-sub">
          <div className="sub-title">
            {s.label} · n = {s.n} · LPIPS {s.quality.lpips_mean?.toFixed(3) ?? "—"} · SSIM {s.quality.ssim_mean?.toFixed(3) ?? "—"} · median pixels changed{" "}
            {s.quality.pct_changed_median?.toFixed(1) ?? "—"}%
          </div>
          <table>
            <thead>
              <tr>
                <th>attacker</th>
                {b.thresholds_km.map((t) => (
                  <th key={t}>
                    ≤{t} km
                    <small>{T_NAMES[String(t)]}</small>
                  </th>
                ))}
                <th>median error</th>
                <th>median 90% area</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(s.attackers).map(([id, a]) => (
                <tr key={id}>
                  <td>{a.name}</td>
                  {b.thresholds_km.map((t) => (
                    <td key={t}>
                      <span className="red">{pct(a.before.acc[String(t)])}</span> → <span className="teal">{pct(a.after.acc[String(t)])}</span>
                    </td>
                  ))}
                  <td>
                    {km(a.before.median_km)} → {km(a.after.median_km)}
                  </td>
                  <td>
                    {area(a.before.median_area_km2)} → {area(a.after.median_area_km2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
      {b.failures.length > 0 && <div className="muted">Failures: {b.failures.length} (listed in bench/results/latest.json)</div>}
      <p className="muted">“Can't be placed” = not within {b.radius_km} km, by the attackers listed. No cherry-picking: every photo in the subset is counted.
        The Reader row predates its gazetteer upgrade (cities15000 → cities5000).</p>
    </div>
  );
}

function pct(v: number | undefined) {
  return v == null ? "—" : `${(v * 100).toFixed(1)}%`;
}
