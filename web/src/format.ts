import type { ClueType } from "./types";

export function km(v: number | null | undefined): string {
  if (v == null) return "—";
  if (v < 1) return `${Math.round(v * 1000)} m`;
  if (v < 10) return `${v.toFixed(1)} km`;
  return `${Math.round(v).toLocaleString("en-US")} km`;
}

export function area(v: number | null | undefined): string {
  if (v == null) return "—";
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)} million km²`;
  if (v >= 1e4) return `${Math.round(v / 1e3).toLocaleString("en-US")}k km²`;
  return `${Math.round(v).toLocaleString("en-US")} km²`;
}

export function scale(km2: number | null | undefined): string {
  if (km2 == null) return "";
  if (km2 > 3e6) return "continent";
  if (km2 > 1.5e5) return "country";
  if (km2 > 5e3) return "region";
  if (km2 > 60) return "city";
  return "neighbourhood";
}

export const TYPE_COLORS: Record<ClueType, string> = {
  metadata: "#ffffff",
  text: "#ff3b5c",
  phone: "#ff3b5c",
  plate: "#ff8a3d",
  landmark: "#ffd23f",
  building: "#b98cff",
  vegetation: "#4ade80",
  road_marking: "#f5f5f5",
  vehicle: "#38bdf8",
  flag: "#ff8a3d",
  reflection: "#67e8f9",
  terrain: "#a3a3a3",
  other: "#94a3b8",
};

export const TYPE_NAMES: Record<ClueType, string> = {
  metadata: "Location data",
  text: "Text",
  phone: "Phone number",
  plate: "Plate",
  landmark: "Landmark",
  building: "Architecture",
  vegetation: "Vegetation",
  road_marking: "Road markings",
  vehicle: "Vehicle",
  flag: "Flag",
  reflection: "Reflection",
  terrain: "Terrain",
  other: "Street furniture",
};

/** Camera altitude (globe radii) that frames a credible area. */
export function altitudeFor(km2: number | null | undefined, minAlt = 0.06): number {
  if (!km2) return 2.2;
  const side = Math.sqrt(km2); // km
  const alt = (side / 6371) * 2.4;
  return Math.max(minAlt, Math.min(2.6, alt));
}
