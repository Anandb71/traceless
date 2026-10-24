// Mirror of backend/traceless/schemas.py (FROZEN interfaces). Change both together.

export interface Box { x: number; y: number; w: number; h: number }

export type ClueType =
  | "metadata" | "text" | "phone" | "plate" | "landmark" | "building" | "vegetation"
  | "road_marking" | "vehicle" | "flag" | "reflection" | "terrain" | "other";

export type FixKind = "inpaint" | "blur" | "soften" | "strip" | "none";

export interface Contribution {
  attacker_id: string;
  area_with_km2: number;
  area_without_km2: number;
  error_with_km: number | null;
  error_without_km: number | null;
  gain: number;
  rank: number;
}

export interface Clue {
  id: string;
  index: number;
  type: ClueType;
  label: string;
  description: string;
  box: Box;
  sources: string[];
  confidence: number;
  text: string | null;
  possible_only: boolean;
  iris_px: number | null;
  protected_overlap: boolean;
  contribution: Contribution | null;
  planned_fix: FixKind;
}

export interface Hypothesis {
  lat: number;
  lon: number;
  probability: number;
  radius_km: number | null;
  reasoning: string | null;
  region: string | null;
}

export interface HexCell { h3: string; p: number }

export interface StreetMatch {
  image_id: string;
  lat: number;
  lon: number;
  compass: number | null;
  retrieval_score: number;
  inliers: number;
  url: string;
  source: "mapillary" | "commons";
  attribution: string;
  /** [[qx, qy, rx, ry], ...] normalized coords in query / reference image */
  keypoint_pairs: number[][];
}

export interface RationaleStep { text: string; clue_ids: string[] }

export interface StreetCoverage {
  available: boolean;
  source: "mapillary" | "commons" | "none";
  n_images: number;
  radius_km: number;
  center: { lat: number; lon: number } | null;
  match_threshold: number | null;
  note: string;
}

export interface AttackResult {
  attacker_id: string;
  attacker_name: string;
  family: "retrieval" | "vlm" | "symbolic" | "street";
  offline: boolean;
  adaptive: boolean;
  image_variant: string;
  status: "ok" | "failed" | "skipped" | "timeout";
  error: string | null;
  provider: string | null;
  hypotheses: Hypothesis[];
  h3_res: number;
  distribution: HexCell[];
  credible_level: number;
  credible_area_km2: number | null;
  top: Hypothesis | null;
  distance_km: number | null;
  within_radius: boolean | null;
  clues: Clue[];
  street_matches: StreetMatch[];
  rationale_steps: RationaleStep[];
  latency_ms: number;
  calls: number;
}

export interface DefenseAction { clue_id: string; fix: FixKind; reason: string; round: number; pixels: number }

export interface Quality {
  lpips: number | null;
  ssim: number | null;
  pct_pixels_changed: number;
  pct_pixels_masked: number;
  face_pixels_changed: number;
}

export interface DefenseRound {
  round: number;
  clue_ids: string[];
  attacks: AttackResult[];
  all_beyond_radius: boolean;
  quality: Quality | null;
}

export interface DefensePlan {
  radius_km: number;
  max_rounds: number;
  actions: DefenseAction[];
  protected: Box[];
  rounds: DefenseRound[];
  reached_target: boolean;
  verdict: string;
}

export interface ExifReport {
  has_gps: boolean;
  gps: { lat: number; lon: number } | null;
  gps_region: string | null;
  camera: string | null;
  taken_at: string | null;
  fields: string[];
  stripped: boolean;
}

export interface CollapseFrame { step: number; restored_clue_ids: string[]; attack: AttackResult }

export interface TruthPublic {
  source: "exif" | "owner" | "fixture" | "proxy";
  public_landmark: boolean;
  region: string;
  lat?: number;
  lon?: number;
}

export interface Card {
  before_km: number | null;
  before_by: string | null;
  after_km: number | null;
  after_by: string | null;
  area_before_km2: number | null;
  area_after_km2: number | null;
  area_growth: number | null;
  pct_pixels_changed: number | null;
  lpips: number | null;
  ssim: number | null;
  face_pixels_changed: number | null;
  metadata_stripped: boolean;
  metadata_fields: number;
  had_gps: boolean;
  reached_target: boolean;
  radius_km: number;
  verdict: string;
  attackers: string[];
}

export type Stage = "queued" | "exif" | "attack" | "clues" | "ablation" | "defense" | "done" | "error";

export interface SessionState {
  schema: string;
  id: string;
  take?: string;
  source: string;
  fixture_id: string | null;
  stage: Stage;
  progress: Record<string, number>;
  timings: Record<string, number>;
  error: string | null;
  radius_km: number;
  privacy: { precise: boolean };
  exif?: ExifReport;
  image?: { w: number; h: number; url: string };
  truth?: TruthPublic | null;
  attacks?: AttackResult[];
  clues?: Clue[];
  faces?: number;
  already_safe?: boolean;
  collapse?: { attacker_id: string; frames: CollapseFrame[]; order: string[] };
  defense?: DefensePlan | null;
  protected?: { url: string; mask_url: string; download: string };
  card?: Card;
  street_coverage?: StreetCoverage;
  depth_url?: string; // Shot 1: 8-bit depth PNG aligned with the photo (near = bright)
}

export interface Health {
  ready: boolean;
  steps: Record<string, number>;
  error: string | null;
  cloud: boolean;
  cloud_providers: string[];
  offline: boolean;
  base_url: string;
  sessions: number;
}

export interface Fixture {
  id: string;
  title: string;
  place: string;
  category: string;
  indoor: boolean;
  public_landmark: boolean;
  license: string;
  author: string;
  url: string;
}
