import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Box, Clue } from "../types";
import { TYPE_COLORS } from "../format";

export type PhotoMode = "original" | "erasing" | "protected" | "compare";

interface Props {
  src: string;
  protectedSrc?: string;
  maskSrc?: string;
  w: number;
  h: number;
  clues: Clue[];
  visible: Set<string>;
  highlight?: string | string[] | null;
  mode: PhotoMode;
  faces?: Box[];
  showFaces?: boolean;
  scanning?: boolean;
  overlay?: ReactNode;
  onClueClick?: (id: string) => void;
}

export default function PhotoStage(p: Props) {
  const wrap = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [split, setSplit] = useState(50);
  // Stage direction: start the before/after slider on the face — it is untouched.
  const face = p.faces?.[0];
  useEffect(() => {
    if (p.mode === "compare" && face) setSplit(Math.round((face.x + face.w / 2) * 100));
  }, [p.mode, face?.x, face?.w]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      const s = Math.min(el.clientWidth / p.w, el.clientHeight / p.h);
      setSize({ w: Math.floor(p.w * s), h: Math.floor(p.h * s) });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [p.w, p.h]);

  const showProt = p.protectedSrc && p.mode !== "original";
  const hl = new Set(p.highlight == null ? [] : Array.isArray(p.highlight) ? p.highlight : [p.highlight]);
  const boxesOn = p.mode === "original" || p.mode === "erasing";

  const onDrag = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.buttons !== 1 && e.type !== "pointerdown") return;
    const r = e.currentTarget.getBoundingClientRect();
    setSplit(Math.max(0, Math.min(100, ((e.clientX - r.left) / r.width) * 100)));
  };

  return (
    <div className="photo-wrap" ref={wrap}>
      <div className={`photo-frame ${p.scanning ? "scanning" : ""}`} style={{ width: size.w, height: size.h }}>
        <img className="photo-img" src={p.src} alt="your photo" draggable={false} />
        {showProt && (
          <img
            className={`photo-img photo-prot mode-${p.mode}`}
            src={p.protectedSrc}
            alt="protected"
            draggable={false}
            style={p.mode === "compare" ? { clipPath: `inset(0 0 0 ${split}%)` } : undefined}
          />
        )}
        {p.mode === "erasing" && p.maskSrc && (
          <div className="mask-flash" style={{ maskImage: `url(${p.maskSrc})`, WebkitMaskImage: `url(${p.maskSrc})` }} />
        )}
        {p.mode === "erasing" && p.maskSrc && size.w > 0 && (
          <Particles src={p.src} mask={p.maskSrc} w={size.w} h={size.h} />
        )}
        {p.overlay}
        {p.mode === "compare" && (
          <div className="compare" onPointerDown={onDrag} onPointerMove={onDrag}>
            <div className="compare-bar" style={{ left: `${split}%` }}>
              <span>BEFORE</span>
              <i />
              <span>AFTER</span>
            </div>
          </div>
        )}
        {p.showFaces &&
          (p.faces ?? []).map((b, i) => (
            <div key={`f${i}`} className="face-box" style={boxStyle(b)}>
              <span>protected · untouched</span>
            </div>
          ))}
        {p.clues.map((c) => {
          const on = boxesOn && p.visible.has(c.id);
          const col = TYPE_COLORS[c.type] ?? "#fff";
          return (
            <div
              key={c.id}
              className={`clue-box ${on ? "on" : ""} ${hl.has(c.id) ? "hl" : ""} ${
                c.possible_only ? "possible" : ""
              } ${p.mode === "erasing" ? "dissolve" : ""} ${p.onClueClick && on ? "tappable" : ""}`}
              style={{ ...boxStyle(c.box), ["--c" as string]: col }}
              onClick={p.onClueClick && on ? () => p.onClueClick!(c.id) : undefined}
            >
              <span className="clue-num">{c.index}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function boxStyle(b: Box): React.CSSProperties {
  return {
    left: `${b.x * 100}%`,
    top: `${b.y * 100}%`,
    width: `${b.w * 100}%`,
    height: `${b.h * 100}%`,
  };
}

/** Shot 5: erased pixels break into particles that drift away while the inpaint fades in.
 *  Particles are sampled from the ORIGINAL photo only where the real edit mask is set. */
function Particles({ src, mask, w, h }: { src: string; mask: string; w: number; h: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const cv = ref.current;
    if (!cv) return;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    let raf = 0;
    let dead = false;
    const load = (u: string) =>
      new Promise<HTMLImageElement>((res, rej) => {
        const im = new Image();
        im.onload = () => res(im);
        im.onerror = rej;
        im.src = u;
      });
    Promise.all([load(src), load(mask)])
      .then(([im, mk]) => {
        if (dead) return;
        const off = document.createElement("canvas");
        off.width = w;
        off.height = h;
        const o = off.getContext("2d")!;
        o.drawImage(im, 0, 0, w, h);
        const pix = o.getImageData(0, 0, w, h).data;
        o.clearRect(0, 0, w, h);
        o.drawImage(mk, 0, 0, w, h);
        const mpx = o.getImageData(0, 0, w, h).data;
        let area = 0;
        for (let i = 0; i < mpx.length; i += 4) if (mpx[i] > 127) area++;
        const step = Math.max(2, Math.ceil(Math.sqrt(area / 14000)));
        const ps: number[] = []; // x, y, vx, vy, r, g, b, life
        for (let y = 0; y < h; y += step) {
          for (let x = 0; x < w; x += step) {
            const i = (y * w + x) * 4;
            if (mpx[i] <= 127) continue;
            const ang = Math.random() * Math.PI * 2;
            const sp = 0.3 + Math.random() * 1.6;
            ps.push(x, y, Math.cos(ang) * sp + 0.6, Math.sin(ang) * sp - 1.1, pix[i], pix[i + 1], pix[i + 2], 0.7 + Math.random() * 0.6);
          }
        }
        const t0 = performance.now();
        const D = 2300;
        const tick = (t: number) => {
          const k = (t - t0) / D;
          ctx.clearRect(0, 0, w, h);
          if (k >= 1) return;
          const hold = Math.max(0, Math.min(1, (k - 0.08) / 0.92)); // brief hold = original pixels
          for (let j = 0; j < ps.length; j += 8) {
            const life = ps[j + 7];
            const a = Math.max(0, 1 - hold / life);
            if (a <= 0) continue;
            const e = hold * hold * 140;
            const x = ps[j] + ps[j + 2] * e;
            const y = ps[j + 1] + ps[j + 3] * e;
            ctx.fillStyle = `rgba(${ps[j + 4]},${ps[j + 5]},${ps[j + 6]},${a})`;
            const s = step * (1 - hold * 0.5);
            ctx.fillRect(x, y, s, s);
          }
          raf = requestAnimationFrame(tick);
        };
        raf = requestAnimationFrame(tick);
      })
      .catch(() => {
        /* CSS crossfade remains as the fallback */
      });
    return () => {
      dead = true;
      cancelAnimationFrame(raf);
    };
  }, [src, mask, w, h]);
  return <canvas ref={ref} className="particles" width={w} height={h} />;
}
