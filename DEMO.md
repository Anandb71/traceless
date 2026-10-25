# DEMO — the 3-minute run (presenter script)

Stage rules (UPGRADE.md): no jargon on stage, one number at a time (before vs after
distance), the judge drives, ethics in one sentence. Every number on screen comes from
this run. → advances; compute runs ahead in the background. **P** replays the recorded
take for the current step if anything stalls.

| time | screen | say / do |
|---|---|---|
| 0:00 | Home (QR) | "In 2019 a man found a pop star's home from the reflection in her eyes in a photo she posted." Hand the judge the QR: "Send me a photo you'd post — from a public place." |
| 0:15 | **1 Your file** (3D scan) | The photo comes alive; the scan sweeps; clue pins light up. If GPS: "Your photo carries its own GPS." STRIPPED. "Most apps strip this. Nobody strips the picture." "We never show exact coordinates on screen." |
| 0:35 | **2 The attack** | The cloud collapses country → city. Say only the big number: "Placed **X km** from where you were." |
| 1:00 | **3 The match** (only if a street match passed the measured threshold) | Lines connect your photo to a street photo. "Placed **X m** from where you stood." |
| 1:20 | **4 What gave you away** | "This sign alone gave you away." Hand the judge the clicker / point at **Protect my photo** — *they* press it. |
| 1:35 | **5 Protect** | The clues break apart; the photo stays. "Your face is untouched." |
| 1:50 | **6 Re-attack** | "Different AIs — one told it was edited." Cloud bursts out. "Best guess now **Y km** off." The slider starts on the face: drag it. |
| 2:20 | **7 Safe to post** | Judge scans the QR → protected photo on their phone. One line: before → after distance. |
| 2:35 | **8 Benchmark** (B) | One sentence: "On N public photos, city-level placement dropped from A% to B%." |
| 2:45 | **9 Close** | The share-menu mockup (labelled concept). "Share the moment, not the address." |

## Branches
- **Indoor / already hard to place** → "Good news — this one is already hard to place";
  → skips to the card. Then **H** and run the prepared photo.
- **Target not reached** → read the verdict as written; show the search area growth.
  "We'd rather tell you than wreck your photo."
- **No street match** → step 3 is skipped automatically. Never claim street level outside coverage.
- **Anything hangs** → **P**.

## Before going on stage
- `make demo`, wait for **models ready**; run one SIM photo (records the PANIC take).
- Nothing else on the GPU (no bench, no tests): measured full run ≈ 50 s alone vs 140 s
  with another GPU job — the presenter-paced reveal hides ~50 s, not 140.
- Sound on (S toggles). Privacy mode on (default).
- After the session: **Shift+W** wipes every uploaded photo from the laptop.
