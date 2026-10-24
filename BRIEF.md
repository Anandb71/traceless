# TRACELESS — Authoritative Brief

You are the lead engineer and creative director of TRACELESS, a Track 2 (Make
the Invisible Visible) entry in an invite-only Devin hackathon judged by top
builders. Your only goal is to win. Make every decision yourself, log it in
DECISIONS.md, and never stop to ask.

## Pitch
"See what a stalker's AI sees in your photo — then make it unplaceable."
A judge hands over a photo they're about to post. TRACELESS shows what an AI
geolocator reads from it: sign text, trees, buildings, road markings,
reflections. A globe shows the guess collapsing from country to city to street
as each clue is found. Then TRACELESS erases those clues, attacks the photo
again with different AIs, and proves it can no longer be placed. The judge
gets the photo back on their own phone, safe to post, with before-and-after
numbers.

## Why it matters (README + 20 seconds of the pitch)
- In 2019 a man in Japan found a pop idol's home from the reflection in her
  eyes in a photo she posted.
- AI geolocation now does this in seconds (e.g., GeoSpy; AI "geoguessing"
  went viral in 2025).
- Stripping location data doesn't help: the picture itself is the leak.
  Defenses exist mainly in research papers. Say "we found no product doing
  this" and cite what you checked.

## Track fit (say this on stage)
Track 2 asks us to help people notice what they normally miss and do
something useful with it — "the interesting part is what happens after
detection." TRACELESS detects the clues, removes them, and proves the removal
worked.

## Win conditions (in order)
1. The room reacts within 30 seconds, on the judge's own photo.
2. Every claim is measured live or by script, so skeptical engineers can't
   poke holes.
3. Zero failures across the 3-minute run on one laptop.
4. A README with a real benchmark, not anecdotes.
5. Visible, documented use of Devin.

## Constraints
- One laptop runs everything (mirrored to a projector). The judge's phone is
  used only to send the photo in and receive the safe photo back.
- 7-hour build; 3-minute live demo.
- Cloud vision models are allowed but never the only path: an offline
  attacker and an offline eraser must work with Wi-Fi off.
- You may have no phone, camera or GPU: SIM mode with fixture photos drives
  everything; HARDWARE_TEST.md lists what humans verify.

## Truth rules (non-negotiable)
1. Location data is clue zero, never attack input. Read the EXIF/GPS, show
   it, strip it before any attacker sees the image. If GPS exists, use it
   only as the answer key for measuring distance error; otherwise the owner
   confirms the true place privately.
2. Eye reflections: only claim to read one when the iris is large enough in
   pixels (find the threshold by testing; record it). Below it, flag
   reflective surfaces (eyes, sunglasses, windows, car bodies, mirrors) as
   "possible clue" and soften them as a labeled precaution.
3. Every number on screen comes from this run or the benchmark scripts.
   Clue contributions are measured by ablation, never invented. Nothing
   hand-typed into the README.
4. "Can't be placed" always means "not within the chosen radius, by the
   attackers we tested", stated with both.
5. No "locate any photo" mode. The app protects a photo you upload; the
   attack is shown as a risk report. Projector privacy mode: distances and
   region names by default; exact coordinates only for public landmarks or
   with the owner's explicit OK.
6. The person in the photo is never altered, except softening eye
   reflections.
7. Photos stay on the laptop, except metadata-stripped copies sent to the
   chosen cloud attacker; delete everything after the session.

## The 3-minute demo
- 0:00 Hook: the 2019 eye-reflection case in one sentence. A judge sends a
  photo from a public place they'd post (QR upload page; AirDrop as backup).
- 0:20 Clue zero: "Your photo carries its own GPS coordinates" (if present) →
  stripped. "Most apps strip this. Nobody strips the picture."
- 0:30 The attack, pixels only: numbered clue boxes pop onto the photo while
  the globe's cloud collapses country → city → street. Readout: "placed X km
  from where you were."
- 1:10 Which clues gave you away: each clue's measured contribution ("this
  sign alone cut the area from 3 million km² to 40 km²").
- 1:30 Erase: clues dissolve; the moment still looks the same; the face is
  untouched.
- 1:50 Re-attack with two different AIs, one offline and one told the photo
  was edited: the cloud bursts back out. "Best guess now Y km off."
- 2:20 Safe to post: QR → the judge downloads the protected photo to their
  own phone. Card: before/after distance, area growth, % of pixels changed,
  location data stripped.
- 2:35 Benchmark: "On N public photos with known locations, street-level
  placement dropped from A% to B%; median error went from C to D km."
- 2:50 Close: "Share the moment, not the address."
- If the judge's photo can't be placed in the first place (e.g., indoors):
  show "Good news — this one is already hard to place" with its numbers,
  then run a prepared outdoor photo. The failure becomes a feature.

## The attack (the "stalker's AI")
- Attacker A (cloud; two providers for failover): a frontier vision model
  with a strict JSON schema — clues [{id, type, description, box, how it
  narrows location}] and ranked location hypotheses [{lat, lon, probability,
  reasoning}]; repeat a few calls to get a spread → a probability cloud.
- Attacker B (offline, different model family): GeoCLIP (open-source
  GPS-retrieval model) on the laptop → top-k coordinates with probabilities.
- Adaptive attacker for the re-attack: Attacker A told the image was edited
  to hide its location.
- Clue finding: OCR for signs, shop names, phone numbers and plates; an
  open-vocabulary detector + SAM 2 for buildings, landmarks, vegetation, road
  markings, vehicles, flags and reflective surfaces; merge with Attacker A's
  boxes.
- Contribution by ablation: mask one clue → re-attack → change in 90%
  credible area and distance error. Build the collapse sequence by starting
  from an all-clues-erased image and restoring clues one at a time in
  contribution order (Attacker B for speed; label which attacker drives the
  animation).
- Distributions live on an H3 hexagon grid; credible area = the area of the
  smallest hexagon set holding 90% of the probability.

## The defense
- Per clue, use the least destructive fix: inpaint (LaMa, local) for signs,
  landmarks and distinctive objects; blur small text and plates; soften
  reflections. The face region is protected.
- Loop: erase the top clues → re-attack with A, B and the adaptive attacker →
  stop when every attacker misses by more than the chosen radius (default
  25 km, city level) or after K rounds; if the target can't be reached, say
  so.
- Quality: LPIPS and SSIM vs the original, % of pixels changed, and a
  before/after slider.

## Look
- The globe is the hero: real data drives every frame of the collapse and the
  burst. Dark, cinematic, legible on a projector.
- Numbered clue boxes, colored by type, each linked to its contribution bar.
- A smooth dissolve for erasure; counters animate between real values.
- A final card designed to be screenshotted.

## Benchmark (`make bench` → /bench; numbers feed the README)
- Data: Im2GPS3k (public photos with known locations), as large a subset as
  time allows, plus a "clue-rich" subset (photos with readable text).
- For each attacker, before vs after: accuracy at 1 / 25 / 200 / 750 /
  2500 km (street / city / region / country / continent), median error, 90%
  credible area; plus LPIPS/SSIM, % of pixels changed, and adaptive-attacker
  results.
- Report the subset size actually run and list failures. No cherry-picking.

## Architecture
- Laptop: Python FastAPI backend (EXIF, OCR, detection, SAM 2, GeoCLIP, LaMa,
  metrics, attacker clients, loop orchestrator) + TypeScript web app (QR
  upload, photo canvas, globe, cards).
- Transfer: the laptop serves a QR upload page with a per-session token over
  a shared local network (a phone hotspot works); AirDrop or USB as backup;
  download back by QR.
- Offline mode: Attacker B, LaMa, OCR and SAM 2 all run locally; Attacker A
  is optional.

## Hardening
- Live time budget: attack ≤ 20 s, erase ≤ 10 s, re-attack ≤ 20 s. Pre-warm
  models; run attackers in parallel; provider failover; graceful timeouts.
- One PANIC key per step plays a recorded take. Record clean takes as each
  step starts working.
- SIM mode: 10 fixture photos (teammates' own photos from public places, with
  consent, plus public-domain photos), including an indoor one, with golden
  tests.
- SETUP.md: setup in ≤ 2 minutes; rehearse once with Wi-Fi off.

## README (judges skim it in 2 minutes)
- Hero GIF (globe collapse → erase → burst) and the one-liner.
- Then: the threat (cite the 2019 case and AI geolocation tools), what
  TRACELESS does, a Mermaid diagram of how it works, benchmark tables and
  plots, limitations and ethics (dual use; what it can't stop: a human with
  extra context, other photos, captions), prior art (research papers; "we
  found no product"), "Built with Devin" (lanes, PRs, tests), one-command
  quickstart.

## Build order (main always demoable)
1. Fixtures + EXIF clue zero + offline Attacker B + a simple map → first
   end-to-end attack.
2. Attacker A with schema + clue boxes (OCR, detector, SAM 2) + globe cloud.
3. Defense (LaMa, blur, softening) + re-attack loop + final card + QR
   download.
4. Ablation contributions + the real-data collapse animation.
5. Benchmark (start it in the background as soon as step 3 works).
6. README, fallbacks, projector privacy mode, rehearsals.
Cut from the bottom, but never cut the metadata-free attack, the re-attack
with a different AI, or the before/after numbers.

## Parallel lanes (if you can run several sessions)
A: attack. B: defense + loop. C: frontend + visuals. D: benchmark + README.
E: hardening, SIM mode, demo script.
Freeze interfaces first: Clue, AttackResult (hypotheses, H3 distribution,
credible area, distance to truth), DefensePlan.

## Rules
- Real measurements only; label every approximation.
- Keep main green and demoable; small PRs with tests.
- Done = the full 3-minute demo runs 5 times in a row on the laptop with 5
  different photos, including one indoor photo that takes the "already safe"
  path.
