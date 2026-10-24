# SETUP — demo laptop in ≤ 2 minutes (after the one-time install)

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
| `cities15000.txt`, `countryInfo.txt`, `admin1CodesASCII.txt` | 9 MB | GeoNames gazetteer (CC-BY 4.0) |
| `face_detection_yunet_2023mar.onnx` | 0.2 MB | YuNet face/eye detector |

GeoCLIP's own heads + 100k GPS gallery ship inside the `geoclip` pip package.
GPU is optional: the CUDA 12.6 torch build uses an NVIDIA GPU when present and falls
back to CPU automatically (`TRACELESS_DEVICE=cpu` forces CPU).

## Demo day (≤ 2 minutes)

```bash
make demo           # serves everything on http://localhost:8000 (and the LAN IP)
```

1. Open `http://localhost:8000` full-screen on the projector (F11). Wait for the
   **models ready** chip (≈30 s on first start; warm-up runs automatically).
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
