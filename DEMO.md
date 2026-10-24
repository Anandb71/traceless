# DEMO — the 3-minute run (presenter script)

Every number on screen comes from this run (or `make bench`). Press → to advance;
compute runs ahead in the background, so the pace is yours. **P** at any point
replays the recorded take for that step.

| time | screen | say |
|---|---|---|
| 0:00 | Home (QR) | "In 2019 a man found a pop idol's home from the reflection in her eyes in a photo she posted. AI does that in seconds now. Send me a photo you'd post — from a public place." Judge scans the QR, sends a photo. |
| 0:20 | **1 Clue zero** | If GPS: "Your photo carries its own GPS coordinates." STRIPPED stamp. "Most apps strip this. Nobody strips the picture." If no GPS: "No GPS in this file — but watch." |
| 0:30 | **2 The attack** | Boxes pop onto the photo while the globe's cloud collapses country → city → street (real frames: clues restored one at a time). Read the readout: "Placed **X km** from where you were." Name the attackers: offline GeoCLIP, an OCR sleuth, and (if online) a frontier vision model. |
| 1:10 | **3 What gave you away** | "Each clue measured by erasing it and attacking again: **this sign alone** cut the search area from A to B." |
| 1:30 | **4 Erase** | Clues dissolve. "Signs keep their boards but lose their words. The face is untouched — zero pixels changed." Read % pixels changed + SSIM. |
| 1:50 | **5 Re-attack** | "Now different AIs — one is *told* the photo was edited and only looks at what we didn't touch." Cloud bursts out. "Best guess now **Y km** off." Read the verdict line exactly as written (radius + attackers). |
| 2:20 | **6 Safe to post** | Judge scans the card QR → the protected photo lands on their phone. Card: before/after distance, search-area growth, % pixels changed, location data stripped. |
| 2:35 | **7 Benchmark** (B) | "On N public photos with known locations, city-level placement dropped from A% to B%; median error went from C to D km." (numbers from `bench/results/latest.json`) |
| 2:50 | close | "Share the moment, not the address." |

## Branches
- **Indoor / already hard to place** → step 2 shows *"Good news — this one is already
  hard to place"* with its numbers; → jumps to the card (0% pixels changed). Then press
  **H** and run a prepared outdoor fixture (Madrid shopfront) — the failure becomes a feature.
- **Target not reached** (e.g. a world-famous scene) → say the verdict as written:
  "Not within 25 km for GeoCLIP — the whole scene is the landmark. We tell you instead
  of wrecking your photo." Show the search-area growth on the card.
- **Anything hangs** → **P**.

## Privacy on the projector
Default is privacy mode: region names + distances, no coordinates, globe never zooms
below ~country scale, no "you were here" pin. Public landmarks (and **M**, with the
owner's OK) show exact places. Shift+W wipes the session from the laptop at the end.
