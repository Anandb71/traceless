# DECISIONS — append-only log

Every significant choice, with why. Newest at the bottom. Numbers quoted here
were measured on the build laptop (i5-13450HX, 16 GB, RTX 3050 6 GB, Windows 11).

---

### D1 · Frozen interfaces first
`backend/traceless/schemas.py` (pydantic) is the single source of truth for
`Clue`, `AttackResult`, `DefensePlan` (+ `Contribution`, `Hypothesis`,
`HexCell`, `DefenseRound`, `Quality`, `ExifReport`, `CollapseFrame`, `Truth`).
`web/src/types.ts` mirrors it by hand. Boxes are normalized `[0,1]`, distances
are great-circle km, distributions are H3 cells.

### D2 · Stack
Python 3.12 + FastAPI backend (uv-managed), Vite + React + TypeScript web app,
globe.gl (three.js) for the globe, h3 on both sides. One process serves the API,
the phone pages and the built web app on `:8000`, so the demo is one command.

### D3 · Disk budget forced a lean model plan (3.9 GB free at start)
- CLIP ViT-L/14 (GeoCLIP's backbone) is fetched by **HTTP range requests on the
  safetensors file — vision tower only**, stored fp16 (608 MB). The text tower is
  never stored: `scripts/build_prompts.py` streams it into RAM once to embed the
  clue vocabulary into a 100 KB `.npz`.
- **No separate open-vocabulary detector and no SAM 2.** Deviation from the brief:
  OWL-ViT/GroundingDINO + SAM 2 would add 0.8–1.5 GB. Instead the dense detector
  is **ClearCLIP** (Lan et al., ECCV 2024: q-q attention, no residual/FFN in the
  last block) on the *same* CLIP-L tower GeoCLIP uses — zero extra weights,
  ~1.3 s/photo on CPU. Masks are patch-resolution (14 px at 448), dilated; text
  gets pixel-accurate glyph masks from OCR boxes instead (D9). Logged as the
  main capability trade-off.
- OCR: RapidOCR (PP-OCRv4 ONNX, ~15 MB). Faces/eyes: OpenCV YuNet (230 KB).
- Inpainting: big-lama TorchScript (206 MB), OpenCV Telea as labeled fallback.
- LPIPS with the SqueezeNet backbone (5 MB) instead of AlexNet (233 MB).

### D4 · Own 80-line ViT-L/14 instead of importing `transformers`
`transformers` import cost 45 s cold on this Windows box. The vision tower is
re-implemented in `attackers/clip_vit.py` (HF state-dict compatible) and was
verified **bit-exact** (max abs diff 0.0) against `CLIPVisionModelWithProjection`.
GeoCLIP's location encoder is vendored (MIT) for the same reason; weights still
load from the pip package.

### D5 · int8 dynamic quantization rejected
2× faster on CPU but cosine similarity to fp32 embeddings was only 0.83–0.87 —
it would change the attacker. Not worth it. (GPU fp16 later instead — D12.)

### D6 · Attackers (three families, all honest about what they are)
- **B · GeoCLIP (offline, retrieval)**: sees the whole frame through 3 square
  views (center + both ends of the long axis), probabilities averaged. Top-1 =
  argmax gallery point, as in the GeoCLIP paper's evaluation.
- **B′ · GeoCLIP adaptive (offline)**: *told which pixels were edited*; ignores
  views that are >25% edited and zooms into a 3×3 grid of close-ups of what is
  left. This is our offline "attacker that knows about the defense".
- **C · The Reader (offline, symbolic)**: OCR → place-name gazetteer (GeoNames
  cities15000 + alternate names incl. CJK), writing systems, diacritics,
  shop-vocabulary lexicon, phone country codes, web TLDs, currency symbols.
  A completely different method family — blind to architecture, sharp on signs.
- **A · Cloud VLM (optional)**: Claude (`claude-opus-5-5`, structured outputs,
  effort `low` for latency) with Gemini REST failover; 3 parallel calls → a
  spread; adaptive variant is told the image was edited. Skipped cleanly with no
  key — never the only path.

### D7 · Credible area on one fixed H3 resolution (6, ~36 km² cells)
All before/after areas are comparable because they use the same resolution.
GeoCLIP's 100k gallery points are pre-binned into res-6 cells, so a
distribution + 90% area is one `np.bincount`. VLM/Reader hypotheses are spread
as Gaussians (σ = stated radius / 2) by sampling. Approximation, labeled:
the smallest measurable area is one cell (~36 km²). The globe shows a coarser
display resolution chosen so the credible set fits in ≤2500 hexes.

### D8 · Contributions by ablation, with an exact speed trick
Erase only clue *c* with the same eraser the defense uses → re-attack →
`gain = log10(area_without / area_with)`. GeoCLIP only re-embeds the views the
edit overlaps; cached embeddings are reused for untouched views (exact, not an
approximation). The collapse animation is real: all clues erased → restore the
top 5 one at a time (contribution order) → the rest in one final step; every
frame is a real GeoCLIP attack.

### D9 · Text is erased at the glyph level
LaMa filling whole sign boxes hallucinated letter-like shapes. Instead an Otsu
split inside each OCR box finds the lettering (the class that touches the box
border least is the board), and only the glyphs are inpainted: the sign stays a
sign, it just says nothing. Small text and plates are blurred instead.

### D10 · Big regions are measured, never erased whole
Regions > 10% of the frame (architecture, vegetation, coastline; > 30% for
landmarks/flags) get `planned_fix = none`. First Madrid run inpainted a 22%
"architecture" region and changed 32% of pixels (SSIM 0.81) — the moment was
lost. The loop instead escalates with targeted leak search (D11).

### D11 · Defense loop
R1: erase everything that measurably helped (gain ≥ 0.05) + always-erase types
(text, phones, plates, flags, landmarks) + soften reflections. R2+: remaining
candidates; when none are left, **leak search** (occlude a 4×4 grid on the
*current* image, inpaint the 2 tiles whose removal pushes GeoCLIP furthest).
Final round, if a person is present: **portrait-mode background blur** (person
pixel-identical). Hard 35% repaint budget. The person mask is hard-restored
every round (truth rule 6); `face_pixels_changed` is measured and was 0 on all
fixture runs. If the radius isn't reached we say so, naming the attacker.

### D12 · GPU after all
Mid-build, free disk went from 3.9 GB to 17 GB, so torch was switched to the
CUDA 12.6 build (RTX 3050). Vision tower runs fp16 on GPU, fp32 on CPU;
`TRACELESS_DEVICE=cpu` forces the CPU path, which stays fully supported.

### D13 · Observed limitation worth saying on stage
GeoCLIP's prior strongly favours heavily-photographed places (its gallery is
built from Flickr). After erasing the Eiffel Tower its 90% area grew ×260
(32 → 8,392 km²) but its top-1 stayed in Paris; on the Dotonbori photo the
whole scene is the landmark. We report "target not reached" rather than
over-erasing. Fixture photos come from Wikimedia Commons, some via Flickr, so
retrieval models may have seen near-duplicates; the benchmark (Im2GPS3k) is the
standard held-out set.

### D14 · GPU numbers and warm-up
RTX 3050, fp16 vision tower: 0.017 s per GeoCLIP view (CPU: 0.41 s), cosine
vs CPU fp32 = 1.0000 and identical argmax. LaMa TorchScript re-profiles every
new input shape (~2 s each); disabling the profiling executor gives 0.17 s
steady state. The server warms every model at startup and runs one dummy pass.

### D15 · Retrieval memorization on famous spots (measured, disclosed)
GeoCLIP's 100k gallery has points within 12–52 m of the Osaka, Big Sur and
Cincinnati fixture locations; its top-1 stays at 0.0–0.4 km no matter which
clues we erase (even the all-erased collapse frame). Those scenes are
effectively memorized. We do not over-erase to chase it: the defense reports
"target not reached" and the README says why. Held-out Im2GPS3k is the
honest measurement.

### D16 · Portrait-mode blur is opt-in
On a bench photo it was the only thing that reached the target, at 83% of
pixels changed (LPIPS 0.61, SSIM 0.57). That is not "the moment still looks
the same". Off by default (`TRACELESS_PORTRAIT_BLUR=1` to enable). Leak search
went to a 6×6 grid, 3 tiles/round, 4 rounds: Madrid now reaches the target
with 25.5% pixels changed (SSIM 0.82) vs 31.8% (SSIM 0.77) before.

### D17 · Eye-reflection threshold = 96 px (measured)
`bench/iris_threshold.py` on 6 outdoor fixture scenes, attacker-favourable
simulation (convex-mirror reflection 65% over iris texture, JPEG q85, 4×
upsampling). GeoCLIP recovers the scene's location from the iris alone on
≥50% of scenes from 96 px up (0% at ≤12 px, 17% at 16–48 px, 33% at 64 px);
OCR never read mirrored corneal text at any size. Below 96 px eyes are
"possible reflection" precautions, softened, never claimed readable.

### D18 · SIM fixtures carry GPS EXIF (disclosed in the file)
Wikimedia's resized copies have no EXIF, so `scripts/tag_fixtures.py` writes
each fixture's Commons camera-location coordinates back as GPS EXIF with an
ImageDescription saying so (no fake camera make/model). Portrait and indoor
fixtures stay GPS-free to cover the "no GPS in this file" path.

### D19 · UPGRADE.md accepted; plan in UPGRADE_PLAN.md
Devin committed UPGRADE.md mid-build. Time check at 02:50: ~4.9 h left → full
priority list, feature freeze 06:15. Venue coordinates and MAPILLARY_TOKEN were
not provided (placeholders) → asked via DEVIN_BLOCKED; built against a Commons
reference set meanwhile.

### D20 · Attacker C design
EigenPlaces ResNet-50/2048 (vendored ~30 lines: the hub constructor pulls a second
hub model, CosPlace, only to initialise weights it then overwrites) → exact numpy
cosine top-12 (no FAISS needed below ~100k images) → SuperPoint (1024 kp) +
LightGlue → OpenCV USAC-MAGSAC fundamental matrix (1.5 px) inliers. A match is
claimed only at ≥ T inliers, T measured by `bench/street_threshold.py`
(leave-one-out positives, out-of-coverage negatives); default 60 until measured.
Non-matches return "no street-level match (best N < T)" with no lines drawn.
All checkpoints live under `models/weights/torch` (TORCH_HOME pinned in
`traceless/__init__.py`) so the matcher runs with Wi-Fi off.

### D21 · Defense targets what the street matcher matched
If Attacker C still pins the street after a round, its query-side inlier
keypoints are binned on an 8×8 grid and the densest cells (≤70% of the points,
within the 35% repaint budget, never the person) are inpainted. Measured
evidence, not a heuristic guess.

### D22 · Kept globe.gl instead of deck.gl; shots are views over session state
Rewriting the globe would have cost the time Attacker C needed; globe.gl already
extrudes H3 cells from real distributions. Each "shot" renders from the session
state the backend computes (attacks, collapse frames, street matches, depth),
so every animated value interpolates between computed states.

### D23 · Street-match threshold = 55 inliers (measured)
`bench/street_threshold.py` on the Commons Madrid test index (600 photos): 50
out-of-coverage negatives (fixtures + Im2GPS3k > 50 km away) peak at 45 inliers;
the smallest T above that with ≥95% of leave-one-out claims within 100 m is 55.
At T = 55: 62 claims of 120 queries, precision@100 m 95.2%, recall@1 within
25 m 43%, within 100 m 49%. Commons GPS tags are themselves noisy, so 25 m
recall understates the matcher. Re-measure on the venue index once built.
