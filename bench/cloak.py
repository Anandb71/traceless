"""CLOAK (UPGRADE.md extra): invisible adversarial noise vs. TRACELESS's visible erasure.

Projected gradient descent on GeoCLIP's image encoder under an L-infinity budget:
push probability mass away from GeoCLIP's own original top-1 region (gallery
points within 100 km of it). Then measure, honestly:
  - white-box effect on GeoCLIP (the model we attacked),
  - transfer to the adaptive zoom attacker (different views of the same model),
  - transfer to the street matcher and The Reader (different model families),
  - perceptual cost (LPIPS, SSIM) and max pixel change.
Output: bench/results/cloak.json + CLOAK.md table. README only unless striking.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from traceless.attackers.base import AttackContext  # noqa: E402
from traceless.attackers.geoclip_attacker import GeoCLIPAdaptiveAttacker, GeoCLIPAttacker  # noqa: E402
from traceless.attackers.geoclip_model import MEAN, STD, GeoCLIPModel, tile_boxes  # noqa: E402
from traceless.geo import haversine_km  # noqa: E402
from traceless.metrics import quality  # noqa: E402
from traceless.schemas import Truth  # noqa: E402


def views_t(x: torch.Tensor, mode: str = "tri") -> torch.Tensor:
    """Differentiable version of geoclip_model.views + CLIP preprocessing."""
    _, _, h, w = x.shape
    crops = []
    for x0, y0, x1, y1 in tile_boxes(w, h, mode):
        c = x[:, :, y0:y1, x0:x1]
        c = F.interpolate(c, size=(224, 224), mode="bicubic", align_corners=False, antialias=True)
        crops.append(c)
    v = torch.cat(crops).clamp(0, 1)
    return (v - MEAN.to(x.device)) / STD.to(x.device)


def cloak(img: Image.Image, eps: float, steps: int = 30) -> Image.Image:
    m = GeoCLIPModel.get()
    for prm in list(m.vision.parameters()) + list(m.mlp.parameters()):
        prm.requires_grad_(False)  # gradients w.r.t. the pixels only
    dev = m.device
    x0 = torch.from_numpy(np.asarray(img, dtype=np.float32) / 255.0).permute(2, 0, 1)[None].to(dev)
    with torch.no_grad():
        f = F.normalize(m.mlp(m.vision(views_t(x0).to(m.dtype)).float()), dim=1)
        p0 = (m.logit_scale * f @ m.loc_feats.T).softmax(-1).mean(0)
    top = int(p0.argmax())
    near = torch.from_numpy(haversine_km(m.gallery[top, 0], m.gallery[top, 1], m.gallery[:, 0], m.gallery[:, 1]) < 100).to(dev)
    delta = torch.zeros_like(x0, requires_grad=True)
    alpha = eps / 8
    for _ in range(steps):
        v = views_t(x0 + delta)
        f = F.normalize(m.mlp(m.vision(v.to(m.dtype)).float()), dim=1)
        logp = (m.logit_scale * f @ m.loc_feats.T).log_softmax(-1)
        loss = torch.logsumexp(logp[:, near], dim=1).mean()  # log mass near the original guess
        loss.backward()
        with torch.no_grad():
            delta -= alpha * delta.grad.sign()
            delta.clamp_(-eps, eps)
            delta.copy_((x0 + delta).clamp(0, 1) - x0)
        delta.grad = None
    out = ((x0 + delta).clamp(0, 1)[0].permute(1, 2, 0).detach().cpu().numpy() * 255).round().astype(np.uint8)
    return Image.fromarray(out)


def main() -> None:
    man = json.loads((ROOT / "fixtures" / "manifest.json").read_text(encoding="utf-8"))
    imgs = [(m["id"], m["lat"], m["lon"], ROOT / "fixtures" / m["file"]) for m in man if not m["indoor"]]
    rows = []
    b, ad = GeoCLIPAttacker(), GeoCLIPAdaptiveAttacker()
    for fid, lat, lon, path in imgs:
        img = Image.open(path).convert("RGB")
        img.thumbnail((768, 768))
        ctx = AttackContext(truth=Truth(lat=lat, lon=lon, source="fixture"))
        r0, a0 = b.attack(img, ctx), ad.attack(img, ctx)
        for eps in (2 / 255, 4 / 255):
            adv = cloak(img, eps)
            r1, a1 = b.attack(adv, ctx), ad.attack(adv, ctx)
            q = quality(np.asarray(img), np.asarray(adv), np.zeros(img.size[::-1], bool))
            rows.append({"id": fid, "eps": f"{round(eps * 255)}/255", "geoclip_before_km": r0.distance_km,
                         "geoclip_after_km": r1.distance_km, "adaptive_before_km": a0.distance_km,
                         "adaptive_after_km": a1.distance_km, "lpips": q.lpips, "ssim": q.ssim,
                         "pct_pixels_changed": q.pct_pixels_changed})
            print(rows[-1], flush=True)
    out = ROOT / "bench" / "results"
    out.mkdir(parents=True, exist_ok=True)
    (out / "cloak.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")

    def km(v):
        return "—" if v is None else f"{v:,.0f} km" if v >= 10 else f"{v:.1f} km"

    md = ["| photo | ε | GeoCLIP (white-box) | GeoCLIP adaptive (transfer) | LPIPS | SSIM |", "|---|---|---|---|---|---|"]
    md += [f"| {r['id']} | {r['eps']} | {km(r['geoclip_before_km'])} → **{km(r['geoclip_after_km'])}** | "
           f"{km(r['adaptive_before_km'])} → **{km(r['adaptive_after_km'])}** | {r['lpips']} | {r['ssim']} |" for r in rows]
    (out / "CLOAK.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
