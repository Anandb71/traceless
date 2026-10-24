# UPGRADE_PLAN — what exists, what this upgrade adds

Written 2026-10-25 ~02:50 after reading UPGRADE.md, the code and DECISIONS.md.
**Time check:** build started ~00:45 → 7-hour window ends ~07:45 → **~4.9 h left**
(> 3 h, so the full priority list applies). **Feature freeze 06:15** (90 min before
the demo); the last hour is recorded takes + rehearsal.

## What already exists (reused, not rebuilt)

| piece | where | reuse for the upgrade |
|---|---|---|
| Frozen interfaces (Clue, AttackResult, DefensePlan, …) | `backend/traceless/schemas.py`, `web/src/types.ts` | extended additively: `street_matches`, `rationale_steps` |
| EXIF clue zero (read → show → strip) | `exif.py` | Shot 1's "clue zero card strips" |
| Attackers: GeoCLIP (B), GeoCLIP-adaptive, The Reader (OCR sleuth), Cloud VLM (A, optional) | `attackers/` | Attacker C plugs into the same `Attacker` interface + `attack_all` |
| Clue finder: OCR + ClearCLIP dense map + YuNet faces/eyes + VLM boxes | `clues/` | clue pins for Shot 1, highlights for Shot 2 |
| H3 distributions + 90% credible area | `geo.py` | Shot 2 hexagon columns (already extruded H3 on globe.gl) |
| Ablation contributions + real collapse frames | `ablation.py` | Shot 2 "columns drain into one country, then one city" |
| Defense loop (glyph inpaint, blur, soften, leak search), quality metrics | `defense/`, `metrics.py` | Shot 5 erasure; Attacker C joins the re-attack |
| Session pipeline, presenter-paced web app, PANIC takes, privacy mode | `pipeline.py`, `server.py`, `web/` | shots are new views over the same session state |
| QR upload/download, SIM fixtures, golden tests, bench, iris threshold (96 px) | various | unchanged; street-level bench added |

## What this upgrade adds (priority order)

1. **Attacker C — street-level pinpoint** (`attackers/street.py`, `scripts/build_street_index.py`)
   - Reference set: Mapillary images within ~2 km of the venue (needs `MAPILLARY_TOKEN`
     + venue coords — **asked via DEVIN_BLOCKED**). Fallback that works today:
     geotagged Wikimedia Commons photos around the same point (CC-licensed). Coverage
     (count, radius, source) is always shown; street claims only inside it.
   - Retrieval: EigenPlaces (ResNet-50, 2048-d) global descriptors, cosine top-k
     (numpy; FAISS unnecessary below ~100k images). Re-rank: SuperPoint + LightGlue
     keypoint matching + RANSAC fundamental-matrix inliers. Best match's GPS = pinpoint.
   - "Match" inlier threshold measured on held-out reference images
     (`bench/street_threshold.py` → `data/street_threshold.json`), recorded in DECISIONS.
   - Exposes inlier keypoint pairs (≤300) for the match-lines visual; joins the
     re-attack ("no candidate may pass the threshold" after erasure).
2. **Shots 2, 4, 5** (web): Shot 2 = globe hunt with rationale typing synced to clue
   highlights (Attacker A reasoning when online, The Reader's evidence + measured
   contributions offline); Shot 4 = split-screen match lines from real inlier pairs,
   "Placed X m from where you stood"; Shot 5 = particle dissolve of erased pixels,
   match lines snap and fall, globe bursts, counters animate to re-attack numbers.
   WebAudio-synthesized sound (sonar ping per clue, rumble on convergence, shatter on
   erasure) — no audio assets.
3. **Shot 1** (diorama from monocular depth, Depth Anything V2 Small; scanning beam;
   clue pins at real depths), then **Shot 3** (dive — needs the venue city's offline
   PMTiles; otherwise the globe dive we already have), then Shot 6 polish.
4. **Extras**, only after 1–2 work: LIVE webcam mode, the eye (corneal unwarp, only
   above the measured 96 px iris threshold), shadow circle, CLOAK (PGD on GeoCLIP with
   measured transfer).

## Deviations decided now (logged in DECISIONS.md as they land)
- **Keep globe.gl** (three.js) instead of switching to deck.gl GlobeView: it already
  renders extruded H3 columns from real distributions; rewriting it would cost the
  time Attacker C needs. Bloom/GSAP-style polish is applied within it.
- **numpy instead of FAISS** for the street index (exact search, no extra dependency).
- **Commons fallback** for the street reference set until a Mapillary token + venue are
  provided; the UI labels the source.

## New truth rules (enforced in code)
- Street-level claims only inside the downloaded coverage; the coverage size is shown.
- CLOAK numbers reported as measured, including weak transfer.
- LIVE mode never records or stores frames.
- The eye shot never claims more than the pixels support (96 px threshold).
