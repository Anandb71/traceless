import { useEffect, useMemo, useRef } from "react";
import Globe, { type GlobeInstance } from "globe.gl";
import { cellToBoundary, cellToParent, getResolution } from "h3-js";
import { MeshPhongMaterial, Color } from "three";
import type { HexCell } from "../types";
import { altitudeFor } from "../format";

export interface GlobeMarker {
  lat: number;
  lon: number;
  kind: "truth" | "guess";
  label: string;
}

interface Props {
  cells: HexCell[];
  /** where to look + how wide (km²); null = idle spin */
  focus: { lat: number; lon: number; km2: number | null } | null;
  markers: GlobeMarker[];
  /** projector privacy: never zoom closer than this altitude */
  minAltitude: number;
  tone: "threat" | "safe";
  transitionMs?: number;
}

interface Poly {
  id: string;
  p: number;
  geometry: { type: "Polygon"; coordinates: number[][][] };
}

const THREAT = ["#3b0a45", "#7a0f5c", "#c2185b", "#ff3b5c", "#ff8a3d", "#ffd23f"];
const SAFE = ["#06323a", "#0b5563", "#118a8a", "#2ee6a6", "#a7f3d0", "#ecfeff"];

function ramp(stops: string[], t: number): string {
  const x = Math.max(0, Math.min(1, t)) * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(x));
  const a = new Color(stops[i]);
  const b = new Color(stops[i + 1]);
  return `#${a.lerp(b, x - i).getHexString()}`;
}

export default function GlobeView({ cells, focus, markers, minAltitude, tone, transitionMs = 1400 }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const globe = useRef<GlobeInstance | null>(null);
  const camAlt = useRef(2.2);

  // ---- one-time setup ---------------------------------------------------
  useEffect(() => {
    if (!el.current) return;
    const g = new Globe(el.current, { animateIn: true, rendererConfig: { antialias: true, alpha: true } });
    const mat = new MeshPhongMaterial({ color: new Color("#0a1020"), emissive: new Color("#05070d"), shininess: 4 });
    g.globeMaterial(mat)
      .globeImageUrl("/textures/earth-dark.jpg")
      .bumpImageUrl("/textures/earth-topology.png")
      .backgroundColor("rgba(0,0,0,0)")
      .showAtmosphere(true)
      .atmosphereColor("#4f7cff")
      .atmosphereAltitude(0.16)
      .hexPolygonResolution(3)
      .hexPolygonMargin(0.55)
      .hexPolygonUseDots(true)
      .hexPolygonColor(() => "rgba(140,160,200,0.38)")
      .polygonGeoJsonGeometry("geometry")
      .polygonSideColor(() => "rgba(255,59,92,0.18)")
      .polygonStrokeColor(() => false as unknown as string)
      .polygonsTransitionDuration(transitionMs)
      .htmlElementsData([])
      .htmlElement((d: object) => {
        const m = d as GlobeMarker;
        const div = document.createElement("div");
        div.className = `gmark gmark-${m.kind}`;
        div.innerHTML = `<span class="dot"></span><span class="txt">${m.label}</span>`;
        return div;
      });
    fetch("/geo/countries.geojson")
      .then((r) => r.json())
      .then((geo) => g.hexPolygonsData(geo.features));
    const ctl = g.controls();
    ctl.autoRotate = true;
    ctl.autoRotateSpeed = 0.35;
    ctl.enableZoom = true;
    g.pointOfView({ lat: 20, lng: 10, altitude: 2.2 });
    globe.current = g;
    const ro = new ResizeObserver(() => {
      if (!el.current) return;
      g.width(el.current.clientWidth).height(el.current.clientHeight);
    });
    ro.observe(el.current);
    return () => {
      ro.disconnect();
      g._destructor();
      globe.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- distribution cells -------------------------------------------------
  // Aggregate to a resolution that is visible from the camera altitude we will use.
  const viewAlt = focus ? Math.max(minAltitude, altitudeFor(focus.km2)) : 2.2;
  const targetRes = viewAlt >= 1.5 ? 2 : viewAlt >= 0.6 ? 3 : viewAlt >= 0.25 ? 4 : viewAlt >= 0.1 ? 5 : 6;
  const shown: HexCell[] = useMemo(() => {
    const agg = new Map<string, number>();
    for (const c of cells) {
      const r = getResolution(c.h3);
      const k = r > targetRes ? cellToParent(c.h3, targetRes) : c.h3;
      agg.set(k, (agg.get(k) ?? 0) + c.p);
    }
    return [...agg.entries()].map(([h3, p]) => ({ h3, p }));
  }, [cells, targetRes]);

  const polys: Poly[] = useMemo(() => {
    if (!shown.length) return [];
    return shown.map((c) => {
      // h3-js rings are counter-clockwise; d3-geo (three-globe) treats CCW
      // exterior rings as "the whole sphere minus this hex". Close + reverse.
      const ring = cellToBoundary(c.h3, true);
      ring.push(ring[0]);
      ring.reverse();
      return { id: c.h3, p: c.p, geometry: { type: "Polygon", coordinates: [ring] } };
    });
  }, [shown]);

  useEffect(() => {
    const g = globe.current;
    if (!g) return;
    const pmax = Math.max(1e-9, ...polys.map((p) => p.p));
    const stops = tone === "safe" ? SAFE : THREAT;
    const hmax = Math.min(0.1, 0.18 * viewAlt);
    g.polygonCapColor((d: object) => ramp(stops, Math.sqrt((d as Poly).p / pmax)))
      .polygonSideColor(() => (tone === "safe" ? "rgba(46,230,166,0.10)" : "rgba(255,59,92,0.12)"))
      .polygonAltitude((d: object) => 0.003 + hmax * Math.sqrt((d as Poly).p / pmax))
      .polygonsData(polys);
  }, [polys, tone]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- camera ---------------------------------------------------------------
  useEffect(() => {
    const g = globe.current;
    if (!g) return;
    const ctl = g.controls();
    if (!focus) {
      ctl.autoRotate = true;
      camAlt.current = 2.2;
      return;
    }
    ctl.autoRotate = false;
    const alt = Math.max(minAltitude, altitudeFor(focus.km2));
    camAlt.current = alt;
    g.pointOfView({ lat: focus.lat, lng: focus.lon, altitude: alt }, transitionMs);
  }, [focus?.lat, focus?.lon, focus?.km2, minAltitude, transitionMs]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- markers -----------------------------------------------------------------
  useEffect(() => {
    const g = globe.current;
    if (!g) return;
    g.htmlElementsData(markers.map((m) => ({ ...m, lng: m.lon })))
      .htmlLat((d: object) => (d as GlobeMarker).lat)
      .htmlLng((d: object) => (d as GlobeMarker).lon)
      .htmlAltitude(0.01);
  }, [markers]);

  // ---- uncertainty ring: radius of a disk with the measured 90% area ------------
  useEffect(() => {
    const g = globe.current;
    if (!g) return;
    const rings: object[] = markers
      .filter((m) => m.kind === "truth")
      .map((m) => ({ lat: m.lat, lng: m.lon, r: 3, c: "46,230,166", period: 900 }));
    if (focus?.km2) {
      const rdeg = Math.max(0.15, Math.sqrt(focus.km2 / Math.PI) / 111);
      rings.push({ lat: focus.lat, lng: focus.lon, r: rdeg, c: tone === "safe" ? "46,230,166" : "255,59,92", period: 1400 });
    }
    type R = { r: number; c: string; period: number };
    g.ringsData(rings)
      .ringMaxRadius((d: object) => (d as R).r)
      .ringColor((d: object) => (t: number) => `rgba(${(d as R).c},${0.9 * (1 - t)})`)
      .ringRepeatPeriod((d: object) => (d as R).period)
      .ringPropagationSpeed((d: object) => Math.max(0.5, (d as R).r / 1.2));
  }, [focus?.lat, focus?.lon, focus?.km2, markers, tone]); // eslint-disable-line react-hooks/exhaustive-deps

  return <div className="globe" ref={el} />;
}
