"""FROZEN core interfaces for TRACELESS.

Every module (attackers, clue finders, defense loop, API, web app) speaks these
types. The web app mirrors them in web/src/types.ts — change both together.

Conventions
- Boxes are normalized to the image: x, y, w, h in [0, 1], origin top-left.
- Coordinates are WGS84 degrees. Distances are great-circle km.
- Probability distributions live on an H3 grid (see traceless.geo).
- Every number here is measured in this run (or by the bench scripts); fields
  that are approximations say so in their docstring.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"

# --------------------------------------------------------------------------- #
# Primitives
# --------------------------------------------------------------------------- #


class Box(BaseModel):
    """Axis-aligned box, normalized to image width/height."""

    x: float
    y: float
    w: float
    h: float

    def to_px(self, width: int, height: int) -> tuple[int, int, int, int]:
        x0 = max(0, int(round(self.x * width)))
        y0 = max(0, int(round(self.y * height)))
        x1 = min(width, int(round((self.x + self.w) * width)))
        y1 = min(height, int(round((self.y + self.h) * height)))
        return x0, y0, x1, y1

    @classmethod
    def from_px(cls, x0: float, y0: float, x1: float, y1: float, width: int, height: int) -> "Box":
        return cls(x=x0 / width, y=y0 / height, w=(x1 - x0) / width, h=(y1 - y0) / height)

    def area(self) -> float:
        return max(0.0, self.w) * max(0.0, self.h)

    def iou(self, other: "Box") -> float:
        ix = max(0.0, min(self.x + self.w, other.x + other.w) - max(self.x, other.x))
        iy = max(0.0, min(self.y + self.h, other.y + other.h) - max(self.y, other.y))
        inter = ix * iy
        union = self.area() + other.area() - inter
        return inter / union if union > 0 else 0.0


class LatLon(BaseModel):
    lat: float
    lon: float


ClueType = Literal[
    "metadata",  # clue zero: EXIF GPS / camera data. Never attack input.
    "text",  # sign text, shop names
    "phone",  # phone numbers (country/area codes)
    "plate",  # vehicle plates
    "landmark",
    "building",  # architecture
    "vegetation",
    "road_marking",
    "vehicle",
    "flag",
    "reflection",  # eyes, sunglasses, windows, car bodies, mirrors
    "terrain",  # mountains, coastline, sky/sun
    "other",
]

ClueSource = Literal["exif", "ocr", "detector", "attacker_a", "reflection", "saliency"]

FixKind = Literal["inpaint", "blur", "soften", "strip", "none"]


# --------------------------------------------------------------------------- #
# Clue
# --------------------------------------------------------------------------- #


class Contribution(BaseModel):
    """Measured by ablation: erase ONLY this clue, re-attack, compare.

    area_* are 90% credible areas (km^2); error_* are top-1 distance to truth.
    gain = log10(area_without / area_with): how many orders of magnitude this
    clue alone shrinks the search area. Positive = the clue gives you away.
    """

    attacker_id: str
    area_with_km2: float
    area_without_km2: float
    error_with_km: float | None = None
    error_without_km: float | None = None
    gain: float
    rank: int = 0


class Clue(BaseModel):
    id: str  # stable within a session: "c1", "c2", ...
    index: int  # 1-based number drawn on the photo
    type: ClueType
    label: str  # short, projector-legible: "Shop sign “Boulangerie”"
    description: str = ""  # how it narrows the location
    box: Box
    sources: list[ClueSource] = Field(default_factory=list)
    confidence: float = 0.5
    text: str | None = None  # OCR'd text, if any
    # Reflection rule (truth rule 2): readable only above the measured
    # iris-pixel threshold; otherwise it is a "possible clue" precaution.
    possible_only: bool = False
    iris_px: float | None = None
    protected_overlap: bool = False  # intersects the person (never erased there)
    contribution: Contribution | None = None
    planned_fix: FixKind = "none"


# --------------------------------------------------------------------------- #
# Attack
# --------------------------------------------------------------------------- #


class Hypothesis(BaseModel):
    lat: float
    lon: float
    probability: float
    radius_km: float | None = None  # attacker's own stated uncertainty, if any
    reasoning: str | None = None
    region: str | None = None  # privacy-safe region name, filled server-side


class HexCell(BaseModel):
    h3: str
    p: float


class StreetMatch(BaseModel):
    """Attacker C: one reference street photo matched to the query (UPGRADE.md)."""

    image_id: str
    lat: float
    lon: float
    compass: float | None = None  # camera heading of the reference photo, degrees
    retrieval_score: float  # cosine similarity of global descriptors
    inliers: int  # RANSAC-verified keypoint matches
    url: str  # served path of the reference thumbnail
    source: Literal["mapillary", "commons"]
    attribution: str = ""
    # [[qx, qy, rx, ry], ...] normalized coords in query / reference image (<= 300)
    keypoint_pairs: list[list[float]] = Field(default_factory=list)


class RationaleStep(BaseModel):
    """One line of an attacker's reasoning, linked to the clues it used."""

    text: str
    clue_ids: list[str] = Field(default_factory=list)


AttackerFamily = Literal["retrieval", "vlm", "symbolic", "street"]
AttackStatus = Literal["ok", "failed", "skipped", "timeout"]


class AttackResult(BaseModel):
    attacker_id: str  # "geoclip", "geoclip-zoom", "reader", "cloud", "cloud-adaptive"
    attacker_name: str  # human label shown on screen
    family: AttackerFamily
    offline: bool
    adaptive: bool = False  # told / built to look past edits
    image_variant: str = "original"  # "original" | "protected" | "ablate:<clue>" | ...
    status: AttackStatus = "ok"
    error: str | None = None
    provider: str | None = None  # e.g. "anthropic:claude-...", for cloud
    hypotheses: list[Hypothesis] = Field(default_factory=list)  # ranked, best first
    h3_res: int = 0
    distribution: list[HexCell] = Field(default_factory=list)  # sums to 1 (top cells kept)
    credible_level: float = 0.9
    credible_area_km2: float | None = None  # smallest hex set holding credible_level mass
    top: Hypothesis | None = None
    distance_km: float | None = None  # top-1 to truth (None if no truth)
    within_radius: bool | None = None  # distance_km <= session radius
    clues: list[Clue] = Field(default_factory=list)  # boxes the attacker cited (VLMs)
    street_matches: list[StreetMatch] = Field(default_factory=list)  # Attacker C, best first
    rationale_steps: list[RationaleStep] = Field(default_factory=list)
    latency_ms: int = 0
    calls: int = 1


# --------------------------------------------------------------------------- #
# Defense
# --------------------------------------------------------------------------- #


class DefenseAction(BaseModel):
    clue_id: str
    fix: FixKind
    reason: str
    round: int
    pixels: int = 0  # pixels in the edit mask (after protecting the person)


class Quality(BaseModel):
    lpips: float | None = None  # LPIPS (SqueezeNet) vs original; lower = more similar
    ssim: float | None = None  # SSIM vs original; 1 = identical
    pct_pixels_changed: float  # % pixels whose value changed by > 2/255 in any channel
    pct_pixels_masked: float  # % pixels inside the edit masks
    face_pixels_changed: int = 0  # pixels changed inside protected person/face regions (eyes excluded)


class DefenseRound(BaseModel):
    round: int
    clue_ids: list[str]
    attacks: list[AttackResult]
    all_beyond_radius: bool
    quality: Quality | None = None


class DefensePlan(BaseModel):
    radius_km: float = 25.0
    max_rounds: int = 3
    actions: list[DefenseAction] = Field(default_factory=list)
    protected: list[Box] = Field(default_factory=list)  # faces / people
    rounds: list[DefenseRound] = Field(default_factory=list)
    reached_target: bool = False
    verdict: str = ""  # stated with radius AND attackers (truth rule 4)


# --------------------------------------------------------------------------- #
# Session-level artifacts
# --------------------------------------------------------------------------- #


class ExifReport(BaseModel):
    """Clue zero. Shown, then stripped before any attacker sees the image."""

    has_gps: bool
    gps: LatLon | None = None
    gps_region: str | None = None
    camera: str | None = None
    taken_at: str | None = None
    fields: list[str] = Field(default_factory=list)  # tag names found (what we strip)
    stripped: bool = False


class CollapseFrame(BaseModel):
    """One frame of the real-data collapse: clues restored so far -> distribution."""

    step: int
    restored_clue_ids: list[str]
    attack: AttackResult


class StreetCoverage(BaseModel):
    """What Attacker C can see: street claims are only made inside this."""

    available: bool
    source: Literal["mapillary", "commons", "none"] = "none"
    n_images: int = 0
    radius_km: float = 0.0
    center: LatLon | None = None
    match_threshold: int | None = None  # measured RANSAC-inlier threshold
    note: str = ""


class Truth(BaseModel):
    lat: float
    lon: float
    source: Literal["exif", "owner", "fixture", "proxy"]  # proxy = original consensus guess
    public_landmark: bool = False
