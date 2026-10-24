import { useEffect, useState } from "react";
import { api } from "../api";
import type { Fixture, Health } from "../types";

interface Props {
  health: Health | null;
  fixtures: Fixture[];
  onSession: (id: string) => void;
}

export default function Home({ health, fixtures, onSession }: Props) {
  const [slot, setSlot] = useState<{ token: string; url: string; qr: string } | null>(null);
  const [drag, setDrag] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api.newSlot().then((s) => alive && setSlot(s)).catch(() => setErr("backend not reachable"));
    return () => {
      alive = false;
    };
  }, [health?.base_url]);

  useEffect(() => {
    if (!slot) return;
    const t = setInterval(async () => {
      try {
        const s = await api.slot(slot.token);
        if (s.session) {
          clearInterval(t);
          onSession(s.session);
        }
      } catch {
        /* keep polling */
      }
    }, 700);
    return () => clearInterval(t);
  }, [slot, onSession]);

  const onDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    setDrag(false);
    const f = e.dataTransfer.files?.[0];
    if (f) onSession((await api.upload(f)).id);
  };

  return (
    <div className={`home ${drag ? "drag" : ""}`} onDragOver={(e) => (e.preventDefault(), setDrag(true))} onDragLeave={() => setDrag(false)} onDrop={onDrop}>
      <div className="hero">
        <h1>
          See what a stalker's AI sees in your photo — <em>then make it unplaceable.</em>
        </h1>
        <p className="lede">
          In 2019 a man found a pop idol's home from the reflection in her eyes in a photo she posted. AI geolocation now does it in
          seconds.
        </p>
        <div className="qr-block">
          {slot ? <img className="qr" src={slot.qr} alt="upload QR" /> : <div className="qr ph" />}
          <div>
            <div className="qr-title">Scan to send a photo you'd post</div>
            <div className="qr-url">{slot?.url ?? err ?? "…"}</div>
            <div className="qr-hint">Same Wi-Fi / hotspot · or drop a file here (USB / AirDrop backup)</div>
            <label className="file-btn">
              choose file…
              <input type="file" accept="image/*" hidden onChange={async (e) => e.target.files?.[0] && onSession((await api.upload(e.target.files[0])).id)} />
            </label>
          </div>
        </div>
      </div>
      <div className="sim">
        <div className="sim-title">SIM mode · fixture photos</div>
        <div className="sim-grid">
          {fixtures.map((f) => (
            <button key={f.id} className="sim-item" onClick={async () => onSession((await api.startFixture(f.id)).id)} title={`${f.title} — ${f.author}, ${f.license}`}>
              <img src={f.url} alt={f.title} loading="lazy" />
              <span>
                {f.category.replace("_", " ")}
              </span>
            </button>
          ))}
        </div>
        <div className="keys">→ next · ← back · P panic replay · M exact places · S sound · B benchmark · H home · Shift+W wipe</div>
      </div>
    </div>
  );
}
