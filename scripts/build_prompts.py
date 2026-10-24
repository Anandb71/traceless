"""Precompute CLIP ViT-L/14 text embeddings for the clue vocabulary.

The text tower (~0.5 GB fp32) is streamed into RAM via HTTP range requests and
discarded afterwards; only a ~100 KB .npz is written. Output:
backend/traceless/data/clip_prompts.npz  (committed, so setup never needs this).
"""

from __future__ import annotations

import json
import struct
import sys
import tempfile
from pathlib import Path

import httpx
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from fetch_models import CLIP_URL, _get_range  # noqa: E402
from traceless.clues.vocab import CLASSES, TEMPLATES  # noqa: E402

REPO = "https://huggingface.co/openai/clip-vit-large-patch14/resolve/main/"
OUT = ROOT / "backend" / "traceless" / "data" / "clip_prompts.npz"


def main() -> None:
    from transformers import CLIPTextConfig, CLIPTextModelWithProjection, CLIPTokenizer

    with httpx.Client(follow_redirects=True, timeout=120) as c:
        n = struct.unpack("<Q", _get_range(c, CLIP_URL, 0, 7))[0]
        header = json.loads(_get_range(c, CLIP_URL, 8, 8 + n - 1))
        base = 8 + n
        keys = [k for k in header if k.startswith(("text_model.", "text_projection.")) and header[k]["dtype"] == "F32"]
        sd = {}
        for k in keys:
            a, b = header[k]["data_offsets"]
            arr = np.frombuffer(_get_range(c, CLIP_URL, base + a, base + b - 1), dtype=np.float32)
            sd[k] = torch.from_numpy(arr.reshape(header[k]["shape"]).copy())
        with tempfile.TemporaryDirectory() as td:
            for f in ("vocab.json", "merges.txt", "tokenizer_config.json", "special_tokens_map.json"):
                r = c.get(REPO + f)
                r.raise_for_status()
                Path(td, f).write_bytes(r.content)
            tok = CLIPTokenizer.from_pretrained(td)
    cfg = CLIPTextConfig(hidden_size=768, intermediate_size=3072, num_attention_heads=12,
                         num_hidden_layers=12, projection_dim=768, hidden_act="quick_gelu",
                         max_position_embeddings=77)
    model = CLIPTextModelWithProjection(cfg)
    missing, unexpected = model.load_state_dict(sd, strict=False)
    missing = [m for m in missing if "position_ids" not in m]
    assert not missing and not unexpected, (missing, unexpected)
    model.eval()
    names, embs = [], []
    with torch.no_grad():
        for name, (_role, prompts) in CLASSES.items():
            texts = [t.format(p) for p in prompts for t in TEMPLATES]
            x = tok(texts, padding=True, return_tensors="pt")
            e = model(**x).text_embeds
            e = torch.nn.functional.normalize(e, dim=-1).mean(0)
            embs.append(torch.nn.functional.normalize(e, dim=0).numpy())
            names.append(name)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUT, names=np.array(names), embs=np.stack(embs).astype(np.float32))
    print(f"ok  {OUT} ({len(names)} classes)")


if __name__ == "__main__":
    main()
