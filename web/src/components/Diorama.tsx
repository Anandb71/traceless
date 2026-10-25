import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { FLAGS } from "../flags";
import type { Clue } from "../types";
import { TYPE_COLORS } from "../format";
import { sound } from "../sound";

/**
 * Shot 1 — the photo comes alive. The photo becomes a relief displaced by the
 * backend's monocular depth map (Depth Anything V2; near = bright). A beam sweeps
 * front-to-back through depth; clue pins sit at the depth measured inside each box.
 * Falls back (onFail) to the flat photo if WebGL or the depth map is unavailable.
 */
interface Props {
  src: string;
  depthSrc: string;
  w: number;
  h: number;
  clues: Clue[];
  scanning: boolean;
  onFail: () => void;
}

const SEG_LONG = 256;
const DISP = 0.32; // displacement as a fraction of the plane height
const EDGE = 0.12; // depth jump that counts as a discontinuity

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((res, rej) => {
    const im = new Image();
    im.crossOrigin = "anonymous";
    im.onload = () => res(im);
    im.onerror = rej;
    im.src = url;
  });
}

const VERT = /* glsl */ `
attribute float aDepth;
varying vec2 vUv;
varying float vDepth;
void main() {
  vUv = uv;
  vDepth = aDepth;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}`;

const FRAG = /* glsl */ `
uniform sampler2D map;
uniform float uBeam;
uniform float uScan;
varying vec2 vUv;
varying float vDepth;
void main() {
  vec3 c = texture2D(map, vUv).rgb;
  float band = exp(-pow((vDepth - uBeam) / 0.035, 2.0));
  float trail = smoothstep(uBeam, uBeam + 0.25, vDepth) * 0.12;
  c = mix(c, c * 0.55, uScan * 0.35);                 // dim the scene a touch while scanning
  c += uScan * (band * vec3(1.0, 0.23, 0.36) * 1.1 + trail * vec3(1.0, 0.3, 0.4));
  gl_FragColor = vec4(c, 1.0);
}`;

export default function Diorama({ src, depthSrc, w, h, clues, scanning, onFail }: Props) {
  const wrap = useRef<HTMLDivElement>(null);
  const pinLayer = useRef<HTMLDivElement>(null);
  const scanRef = useRef(scanning);
  scanRef.current = scanning;
  const cluesRef = useRef<Clue[]>(clues);
  cluesRef.current = clues;
  const [revealed, setRevealed] = useState(0);
  const [gridReady, setGridReady] = useState(0);
  const depthGrid = useRef<{ d: Float32Array; gw: number; gh: number } | null>(null);
  const pinPos = useRef<THREE.Vector3[]>([]);

  // ---- WebGL scene (once per photo) -------------------------------------------------
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      onFail();
      return;
    }
    let dead = false;
    let raf = 0;
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(32, 1, 0.01, 100);
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
    el.appendChild(renderer.domElement);
    const planeH = 1;
    const planeW = (w / h) * planeH;
    let geo: THREE.PlaneGeometry | null = null;
    let mat: THREE.ShaderMaterial | null = null;
    let tex: THREE.Texture | null = null;
    let dist = 2;
    const target = new THREE.Vector3(0, 0, DISP * 0.35);
    const proj = new THREE.Vector3();

    const resize = () => {
      const cw = el.clientWidth || 1;
      const ch = el.clientHeight || 1;
      renderer.setSize(cw, ch, false);
      camera.aspect = cw / ch;
      // fit the plane (plus a little margin for the sway) inside the view
      const fov = (camera.fov * Math.PI) / 180;
      const byH = (planeH * 1.08) / 2 / Math.tan(fov / 2);
      const byW = (planeW * 1.08) / 2 / Math.tan(fov / 2) / camera.aspect;
      dist = Math.max(byH, byW) + DISP * 0.5;
      camera.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    resize();

    Promise.all([loadImage(src), loadImage(depthSrc)])
      .then(([photo, depth]) => {
        if (dead) return;
        // photo texture <= 1024 px
        const tc = document.createElement("canvas");
        const ts = Math.min(1, 1024 / Math.max(photo.width, photo.height));
        tc.width = Math.round(photo.width * ts);
        tc.height = Math.round(photo.height * ts);
        tc.getContext("2d")!.drawImage(photo, 0, 0, tc.width, tc.height);
        tex = new THREE.CanvasTexture(tc);
        tex.colorSpace = THREE.SRGBColorSpace;

        const segX = w >= h ? SEG_LONG : Math.round((SEG_LONG * w) / h);
        const segY = w >= h ? Math.round((SEG_LONG * h) / w) : SEG_LONG;
        const gw = segX + 1;
        const gh = segY + 1;
        const dc = document.createElement("canvas");
        dc.width = gw;
        dc.height = gh;
        const dctx = dc.getContext("2d")!;
        dctx.drawImage(depth, 0, 0, gw, gh);
        const px = dctx.getImageData(0, 0, gw, gh).data;
        const d = new Float32Array(gw * gh);
        for (let i = 0; i < gw * gh; i++) d[i] = px[i * 4] / 255;
        depthGrid.current = { d, gw, gh };
        setGridReady((n) => n + 1);

        geo = new THREE.PlaneGeometry(planeW, planeH, segX, segY);
        const pos = geo.attributes.position as THREE.BufferAttribute;
        const aDepth = new Float32Array(gw * gh);
        for (let iy = 0; iy < gh; iy++) {
          for (let ix = 0; ix < gw; ix++) {
            const i = iy * gw + ix;
            let z = d[i];
            // discontinuities: snap to the farthest neighbour so edges don't stretch into curtains
            let mn = z;
            for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
              const x2 = ix + dx;
              const y2 = iy + dy;
              if (x2 < 0 || y2 < 0 || x2 >= gw || y2 >= gh) continue;
              mn = Math.min(mn, d[y2 * gw + x2]);
            }
            if (!FLAGS.split && z - mn > EDGE) z = mn; // legacy: snap instead of split
            aDepth[i] = z;
            pos.setZ(i, z * DISP * planeH);
          }
        }
        if (FLAGS.split && geo.index) {
          // Split the mesh at depth discontinuities: drop triangles spanning a sharp jump
          // (real measured depth), so foreground and background tear apart, no rubber sheet.
          const idx = geo.index.array;
          const keep: number[] = [];
          for (let t = 0; t < idx.length; t += 3) {
            const a0 = d[idx[t]], a1 = d[idx[t + 1]], a2 = d[idx[t + 2]];
            if (Math.max(a0, a1, a2) - Math.min(a0, a1, a2) <= EDGE) keep.push(idx[t], idx[t + 1], idx[t + 2]);
          }
          geo.setIndex(keep);
          // Blurred copy of the same photo behind the mesh: gaps read as depth of field.
          const bc = document.createElement("canvas");
          bc.width = Math.round(tc.width / 4);
          bc.height = Math.round(tc.height / 4);
          const bctx = bc.getContext("2d")!;
          bctx.filter = "blur(6px) brightness(0.7)";
          bctx.drawImage(tc, 0, 0, bc.width, bc.height);
          const btex = new THREE.CanvasTexture(bc);
          btex.colorSpace = THREE.SRGBColorSpace;
          const back = new THREE.Mesh(
            new THREE.PlaneGeometry(planeW * 1.02, planeH * 1.02),
            new THREE.MeshBasicMaterial({ map: btex }),
          );
          back.position.z = -0.002;
          scene.add(back);
        }
        geo.setAttribute("aDepth", new THREE.BufferAttribute(aDepth, 1));
        pos.needsUpdate = true;
        mat = new THREE.ShaderMaterial({
          uniforms: { map: { value: tex }, uBeam: { value: 1 }, uScan: { value: 0 } },
          vertexShader: VERT,
          fragmentShader: FRAG,
        });
        scene.add(new THREE.Mesh(geo, mat));

        const t0 = performance.now();
        let scanAmt = 0;
        const tick = (t: number) => {
          if (dead) return;
          const s = (t - t0) / 1000;
          const sway = Math.sin(s * 0.35) * ((8 * Math.PI) / 180);
          camera.position.set(Math.sin(sway) * dist, Math.sin(s * 0.23) * 0.04, Math.cos(sway) * dist);
          camera.lookAt(target);
          scanAmt += ((scanRef.current ? 1 : 0) - scanAmt) * 0.05;
          mat!.uniforms.uScan.value = scanAmt;
          mat!.uniforms.uBeam.value = 1.1 - ((s * 0.32) % 1.3); // near (1) -> far (0), looping
          renderer.render(scene, camera);
          // project pins (no allocations: reuse `proj`)
          const layer = pinLayer.current;
          if (layer) {
            const cw = el.clientWidth;
            const ch = el.clientHeight;
            const kids = layer.children;
            for (let i = 0; i < kids.length && i < pinPos.current.length; i++) {
              proj.copy(pinPos.current[i]).project(camera);
              (kids[i] as HTMLElement).style.transform = `translate(${((proj.x + 1) / 2) * cw}px, ${((1 - proj.y) / 2) * ch}px)`;
            }
          }
          raf = requestAnimationFrame(tick);
        };
        raf = requestAnimationFrame(tick);
      })
      .catch(() => {
        if (!dead) onFail();
      });

    return () => {
      dead = true;
      cancelAnimationFrame(raf);
      ro.disconnect();
      geo?.dispose();
      mat?.dispose();
      tex?.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [src, depthSrc, w, h]);

  // ---- clue pins at their measured depth, popping in one by one ---------------------
  const pinned = clues.filter((c) => c.type !== "metadata");
  useEffect(() => {
    if (!pinned.length || !gridReady) return;
    const planeW = w / h;
    const pts: THREE.Vector3[] = [];
    for (const c of pinned) {
      const cx = c.box.x + c.box.w / 2;
      const cy = c.box.y + c.box.h / 2;
      let z = 0.5;
      const g = depthGrid.current;
      if (g) {
        // median depth inside the box
        const x0 = Math.floor(c.box.x * (g.gw - 1));
        const x1 = Math.ceil((c.box.x + c.box.w) * (g.gw - 1));
        const y0 = Math.floor(c.box.y * (g.gh - 1));
        const y1 = Math.ceil((c.box.y + c.box.h) * (g.gh - 1));
        const vals: number[] = [];
        for (let y = y0; y <= y1; y += 2) for (let x = x0; x <= x1; x += 2) vals.push(g.d[y * g.gw + x]);
        if (vals.length) z = vals.sort((a, b) => a - b)[Math.floor(vals.length / 2)];
      }
      pts.push(new THREE.Vector3((cx - 0.5) * planeW, (0.5 - cy) * 1, z * DISP + 0.02));
    }
    pinPos.current = pts;
    setRevealed(0);
    let i = 0;
    const t = setInterval(() => {
      i += 1;
      setRevealed(i);
      sound.ping(1 + i * 0.06);
      if (i >= pts.length) clearInterval(t);
    }, 380);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pinned.map((c) => c.id).join(","), w, h, gridReady]);

  return (
    <div className="diorama">
      <div className="diorama-gl" ref={wrap} />
      <div className="diorama-vignette" />
      <div className="diorama-pins" ref={pinLayer}>
        {pinned.map((c, k) => (
          <div key={c.id} className={`dpin ${k < revealed ? "on" : ""}`} style={{ ["--c" as string]: TYPE_COLORS[c.type] ?? "#fff" }}>
            <span className="dpin-dot">{c.index}</span>
            <span className="dpin-stem" />
          </div>
        ))}
      </div>
      {scanning && <div className="diorama-tag">depth scan · Depth Anything V2</div>}
    </div>
  );
}
