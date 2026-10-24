# TRACELESS UPGRADE: apply on top of the current build

TRACELESS is already being built in this repo. Do NOT restart or rewrite it.
First read the code, DECISIONS.md and the current demo flow, then write
UPGRADE_PLAN.md listing what already exists and what this upgrade adds.
Reuse existing pieces (ablation, H3 distributions, defense loop, QR flow)
instead of rebuilding them. Keep main demoable after every merge, and keep
every existing truth rule.

Goal: make TRACELESS the most visually striking demo in the room, with every
frame driven by real computation, and add a street-level attacker that pins
a photo to the exact corner.

## Time check first
Work out how much time is left before the demo.
- If under 3 hours: do only Attacker C plus shots 4 and 5, then harden.
- Stop adding features 90 minutes before the demo; the last hour is freeze,
  recorded takes and rehearsal.

## Priority order
1. Attacker C (street-level pinpoint)
2. Shots 2, 4, 5
3. Shot 1, then shot 3, then shot 6 polish
4. Extras, in order: LIVE, eye, shadow circle, CLOAK

## 1. Attacker C — street-level pinpoint
- Start NOW as a background job: download Mapillary street photos within
  ~2 km of the venue (<VENUE_LAT>, <VENUE_LON>; token in env
  MAPILLARY_TOKEN), with GPS and compass angle. Report the image count and a
  coverage map. Credit Mapillary (CC BY-SA).
- Index them with a pretrained place-recognition model (e.g., EigenPlaces or
  SALAD) in FAISS. Query → top-k → re-rank with LightGlue keypoint matching +
  RANSAC → best match's GPS is the pinpoint. Pick the inlier threshold for
  "match" by testing; record it.
- Expose the inlier keypoint pairs for the match-lines visual.
- Add Attacker C to the re-attack: after erasure, no candidate may pass the
  threshold.
- Street-match claims only inside coverage; show the covered area and image
  count.
- Time budget: street match ≤ 5 s; pre-warm the model and index.

## 2. The six shots (one lane + one person with taste)
Each shot renders from a ShotState computed by the backend. A clicker
advances shots, and every shot has a PANIC key that plays its recorded take.
Stack: react-three-fiber + three.js, deck.gl GlobeView with extruded H3
hexagons, MapLibre with OpenStreetMap 3D buildings from pre-downloaded
vector tiles of the venue city (PMTiles, so it works offline), GSAP
transitions, bloom post-processing. High contrast for the projector,
60 fps, a caption per shot.
- SHOT 1 — the photo comes alive: monocular depth (e.g., Depth Anything V2)
  → the photo becomes a 3D diorama; a scanning beam sweeps through; clue
  pins light up at their real depths; the GPS "clue zero" card strips.
- SHOT 2 — the hunt: pull out to the globe; glowing hexagon columns show the
  attacker's probability; Attacker A's rationale types live beside it,
  synced to clue highlights; the columns drain into one country, then one
  city (driven by the ablation collapse sequence).
- SHOT 3 — the dive: from orbit into the city's 3D buildings, landing at the
  attacker's best location.
- SHOT 4 — the match: split screen; hundreds of glowing lines connect the
  photo to the matching street photo (real inlier pairs). "Placed X m from
  where you stood."
- SHOT 5 — the erasure: a shader dissolves the erased pixels into particles
  while the inpaint fades in; the match lines snap and fall; the globe
  bursts back across the country; counters animate to the re-attack
  numbers.
- SHOT 6 — safe to post: before/after slider, the numbers, QR to the judge's
  phone.
- Sound: a sonar ping per clue, a low rumble as the globe converges, a
  shatter on erasure.
- Every animation interpolates between real computed states. No decorative
  fake data.

## 3. Extras (only after Attacker C and shots 2, 4, 5 work)
1. LIVE mode: webcam → clue detection at a few Hz with tracking in between →
   live blur → side by side. Attack one frame before and after masking to
   prove it. Never record or store frames.
2. The eye: iris landmarks → iris ellipse → cornea modeled as a spherical
   mirror (Nishino & Nayar corneal imaging) → unwarp the reflection into a
   picture of what she was facing. Only above the tested iris-size
   threshold; use a prepared high-resolution close-up selfie on stage.
3. The shadow circle: when a vertical object and its shadow are clear,
   measure the sun's elevation; with the photo's time, draw the circle on
   the globe where the sun stood at that height (celestial navigation's
   "circle of equal altitude"); intersect it with the other clues.
4. CLOAK: a projected gradient attack on GeoCLIP's image encoder under a
   tight perceptual budget (L∞ + LPIPS) → invisible noise that moves
   Attacker B's guess far away; show the amplified noise as a heatmap;
   report transfer to Attacker A as measured, even if weak. README only
   unless it's striking.

## New truth rules (added to the existing ones)
- Street-level claims only inside the downloaded coverage; always show its
  size.
- CLOAK numbers are reported as measured, including weak transfer.
- LIVE mode never records or stores frames.
- The eye shot never claims more than the pixels support.

## Interfaces to extend (don't break existing fields)
- AttackResult += street_matches [{image_id, lat, lon, inliers,
  keypoint_pairs}], rationale_steps [{text, clue_ids}].
- New ShotState per shot: the exact data the frontend needs to render it.

## New demo script (trim to what's ready; keep the arc)
- 0:00 Hook (the 2019 eye-reflection case); a judge sends a photo from a
  public place, ideally taken near the venue.
- 0:15 Shot 1
- 0:35 Shot 2
- 1:00 Shots 3 + 4: "Placed X m from where you stood."
- 1:25 Measured clue contributions
- 1:35 Shot 5: "Best guess now Y km off. No street match."
- 2:00 The eye (if ready)
- 2:15 LIVE (if ready)
- 2:35 Shot 6
- 2:50 "Share the moment, not the address."
- If the photo can't be placed in the first place: "Good news — this one is
  already hard to place", then a prepared photo.

## Benchmark and README additions
- Street level: held-out photos inside the coverage → recall@1 within 25 m,
  before vs after. Report sizes and failures.
- README: a new hero GIF (diorama scan → globe convergence → match lines →
  erasure burst), Attacker C in the diagram and tables, the extras that
  shipped with their numbers, Mapillary credit.

## Done
- The new demo runs 5 times in a row on the laptop with 5 different photos
  (one indoor, one inside the street coverage) with no restarts.
- Nothing from the existing demo is broken; all existing tests pass.

## Stage direction (applies to demo flow, UI copy and README voice)
- No jargon on stage. Say "this sign gave you away", not "clue
  attribution". The technical depth goes in the README and the Q&A.
- Show one number, not ten: before vs. after distance.
- Cut anything that isn't flawless. Six shots plus four extras in 3 minutes
  is a blur. Keep the scan, the side-by-side reveal, the erase and the
  phone. Add the eye only if it works every time; it's the scariest moment
  because it's the real 2019 story.
- The protected photo has to look good. If the edit looks weird, people
  reject the whole thing instantly. Put the before/after slider on the
  face to show it's untouched.
- Let the judge drive. They pick the photo, they press "Protect", and they
  get it on their phone.
- Show your ethics in one sentence instead of lecturing: "We never show
  exact coordinates on screen."
- Open with a person, not a statistic. Use the 2019 story in one line, or a
  teammate's real experience if there is one. Never invent one.
- End with the future: a labelled mockup of "Protect before posting" in the
  phone's share menu. People want to see it in their own life.
- Make the reveal work beyond the venue. For photos taken elsewhere, look
  up the nearest street photo to the AI's guess live (Mapillary covers
  much of the world) and show it side by side.
