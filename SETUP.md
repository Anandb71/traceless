# SETUP — demo laptop in ≤ 2 minutes (after the one-time install)

## The 2-minute checklist

| # | do | time |
|---|---|---|
| 1 | Close other GPU jobs (bench, tests). `make demo` | 0:00 |
| 2 | Open the URL it prints (`TRACELESS → http://localhost:NNNN`) in Chrome, F11 | 0:10 |
| 3 | Wait for the **models ready** chip (measured 47 s warm) | ≤ 1:00 |
| 4 | Phone on the same Wi-Fi/hotspot, scan the home-screen QR — page opens | 1:20 |
| 5 | Click the Abergavenny SIM photo, press → once to see it working, then **H** | 2:00 |

If anything misbehaves on stage: **P** replays the recorded take for that step.
Recorded takes for the prepared photo, Madrid and the indoor photo ship in `takes/`.

---

## One-time install (~10 min, needs internet)

Requirements: Python 3.12 + [uv](https://docs.astral.sh/uv/), Node 20+ + pnpm, Git Bash (Windows) or any POSIX shell.

```bash
make setup          # uv sync, fetch model weights (~0.9 GB), build the web app
cp backend/.env.example backend/.env   # optional: add ANTHROPIC_API_KEY / GEMINI_API_KEY
```

What `fetch_models.py` downloads into `models/weights/` (gitignored):

| file | size | what |
|---|---|---|
| `clip-vit-l14-vision-fp16.safetensors` | 608 MB | GeoCLIP's CLIP ViT-L/14 vision tower only (range-requested, text tower skipped) |
| `big-lama.pt` | 206 MB | LaMa inpainting (TorchScript) |
| `cities5000.txt`, `countryInfo.txt`, `admin1CodesASCII.txt` | 15 MB | GeoNames gazetteer (CC-BY 4.0) |
| `face_detection_yunet_2023mar.onnx` | 0.2 MB | YuNet face/eye detector |
| `torch/hub/checkpoints/*` | 165 MB | street matcher (EigenPlaces, SuperPoint, LightGlue) + LPIPS SqueezeNet |
| `depth-anything-v2-small/` | 99 MB | Shot 1 depth (Depth Anything V2 Small) |

### Street coverage for Attacker C (once per venue, needs internet)

```bash
# with MAPILLARY_TOKEN in backend/.env (CC BY-SA street photos, credited on screen):
backend/.venv/Scripts/python scripts/build_street_index.py --lat <venue lat> --lon <venue lon> --radius-km 2 --name venue
# no token: Wikimedia Commons geotagged photos instead
backend/.venv/Scripts/python scripts/build_street_index.py --lat <lat> --lon <lon> --radius-km 2 --name venue --source commons
backend/.venv/Scripts/python bench/street_threshold.py   # re-measure the match threshold on this index
```
Only one index is loaded (the first folder alphabetically under `models/weights/street/`);
remove or rename the `madrid-test` index when the venue index exists. Street-level claims
are only ever made inside the downloaded coverage, whose size is shown on screen.

GeoCLIP's own heads + 100k GPS gallery ship inside the `geoclip` pip package.
GPU is optional: the CUDA 12.6 torch build uses an NVIDIA GPU when present and falls
back to CPU automatically (`TRACELESS_DEVICE=cpu` forces CPU).

## Demo day (≤ 2 minutes)

```bash
make demo           # serves everything on http://localhost:8000 (and the LAN IP)
```

1. Open the URL the server prints (normally `http://localhost:8000`; if that port is
   stuck it falls back to 8001+ and says so) full-screen on the projector (F11). Wait for the
   **models ready** chip (warm-up runs automatically: ~1 min warm, up to ~3–4 min on a cold
   disk cache or if another GPU job is running — start the server well before the demo).
2. Laptop and phones on the same network (a phone hotspot works). The QR on the
   home screen points at the laptop's LAN IP; if it shows `127.0.0.1`, set
   `TRACELESS_HOST=<laptop LAN IP>` in `backend/.env` and restart.
3. Run one SIM photo end-to-end (click a fixture) — this also records a clean
   **take** for the PANIC key.
4. Windows firewall: allow Python on private networks the first time it asks.

## Keys during the demo

| key | action |
|---|---|
| → / Space | next step |
| ← | previous step |
| **P** | PANIC: replay the recorded take for this photo (chip shows "recorded take") |
| M | toggle exact places (owner's OK) vs privacy mode (regions + distances only) |
| B | benchmark screen |
| H / Esc | home (new photo) |
| S | sound on/off |
| Shift+W | wipe every uploaded photo and derived file from the laptop |

## Wi-Fi-off rehearsal

```bash
TRACELESS_OFFLINE=1 make demo
```
Attacker B (GeoCLIP), the adaptive GeoCLIP, The Reader, OCR, the dense detector and
LaMa all run locally; the cloud attacker shows "not configured". Rehearse once like this.

## Troubleshooting

- **Phone can't open the QR link** → not on the same network, or firewall. Use the
  drag-and-drop / "choose file…" backup on the home screen (USB / AirDrop-to-Mac / cable).
- **Something hangs mid-demo** → press **P**.
- **Cleanup after the session** → Shift+W (or `make clean-sessions`).
