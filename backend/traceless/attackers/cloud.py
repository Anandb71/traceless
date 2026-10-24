"""Attacker A (cloud, optional): a frontier vision model with a strict JSON schema.

- Primary: Anthropic Claude (official SDK, structured outputs).
- Failover: Google Gemini (REST, responseSchema).
- N parallel calls -> a spread of ranked hypotheses -> a probability cloud.
- Adaptive variant: told the photo was edited to hide its location.

Only metadata-stripped, re-encoded JPEGs are ever sent (truth rule 7).
Never the only path: with no key, it reports status "skipped" and the
offline attackers carry the demo.
"""

from __future__ import annotations

import base64
import concurrent.futures as cf
import io
import json
import os
import time

import httpx
from PIL import Image

from ..geo import Distribution
from ..schemas import AttackResult, Box, Clue, Hypothesis
from .base import AttackContext, Attacker, finalize

CLAUDE_MODEL = os.environ.get("TRACELESS_CLAUDE_MODEL", "claude-opus-5-5")
GEMINI_MODEL = os.environ.get("TRACELESS_GEMINI_MODEL", "gemini-2.5-flash")
N_CALLS = int(os.environ.get("TRACELESS_CLOUD_CALLS", "3"))

CLUE_TYPES = [
    "text", "phone", "plate", "landmark", "building", "vegetation", "road_marking",
    "vehicle", "flag", "reflection", "terrain", "other",
]

SCHEMA = {
    "type": "object",
    "properties": {
        "clues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": CLUE_TYPES},
                    "description": {"type": "string"},
                    "how_it_narrows": {"type": "string"},
                    "box": {
                        "type": "object",
                        "properties": {
                            "x": {"type": "number"}, "y": {"type": "number"},
                            "w": {"type": "number"}, "h": {"type": "number"},
                        },
                        "required": ["x", "y", "w", "h"],
                        "additionalProperties": False,
                    },
                },
                "required": ["type", "description", "how_it_narrows", "box"],
                "additionalProperties": False,
            },
        },
        "hypotheses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "lat": {"type": "number"},
                    "lon": {"type": "number"},
                    "probability": {"type": "number"},
                    "radius_km": {"type": "number"},
                    "reasoning": {"type": "string"},
                },
                "required": ["lat", "lon", "probability", "radius_km", "reasoning"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["clues", "hypotheses"],
    "additionalProperties": False,
}

PROMPT = """You are an expert photo geolocator (GeoGuessr world-champion level).
Find every visual clue in this photo that narrows down where it was taken:
sign text, languages and scripts, shop names, phone numbers, plates, landmarks,
architecture, vegetation, road markings, vehicles, flags, terrain, and
anything visible in reflections (eyes, sunglasses, windows, car bodies).
For each clue give a tight bounding box normalized to the image
(x, y = top-left corner, w, h; all in 0..1).
Then give 3-6 ranked location hypotheses with coordinates, a probability
(summing to about 1) and a radius_km you are ~90% sure the true spot is within.
Be as precise as the evidence allows. Coordinates must be numbers."""

ADAPTIVE = """
IMPORTANT: this photo has been deliberately edited to hide its location —
signs, text and landmarks may have been removed or inpainted. Look past the
edits: use whatever survived (architecture, materials, vegetation, light,
road design, street furniture, background skyline) and say where it still
points."""


def _jpeg_b64(img: Image.Image, max_side: int = 1280) -> str:
    im = img.convert("RGB")
    if max(im.size) > max_side:
        im = im.copy()
        im.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88, exif=b"")
    return base64.standard_b64encode(buf.getvalue()).decode()


def _call_claude(b64: str, prompt: str, timeout: float) -> dict:
    import anthropic

    client = anthropic.Anthropic(timeout=timeout, max_retries=0)
    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=8000,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                {"type": "text", "text": prompt},
            ],
        }],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("model declined")
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


def _gemini_schema(s):
    """Gemini responseSchema: OpenAPI subset (no additionalProperties)."""
    if isinstance(s, dict):
        return {k: _gemini_schema(v) for k, v in s.items() if k != "additionalProperties"}
    if isinstance(s, list):
        return [_gemini_schema(x) for x in s]
    return s


def _call_gemini(b64: str, prompt: str, timeout: float) -> dict:
    key = os.environ["GEMINI_API_KEY"]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    body = {
        "contents": [{"parts": [
            {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
            {"text": prompt},
        ]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _gemini_schema(SCHEMA),
            "temperature": 0.7,
        },
    }
    r = httpx.post(url, json=body, headers={"x-goog-api-key": key}, timeout=timeout)
    r.raise_for_status()
    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


def providers() -> list[tuple[str, callable]]:
    out = []
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        out.append((f"anthropic:{CLAUDE_MODEL}", _call_claude))
    if os.environ.get("GEMINI_API_KEY"):
        out.append((f"google:{GEMINI_MODEL}", _call_gemini))
    return out


class CloudAttacker(Attacker):
    id = "cloud"
    name = "Cloud vision AI"
    family = "vlm"
    offline = False
    adaptive = False

    def __init__(self, adaptive: bool = False):
        if adaptive:
            self.id = "cloud-adaptive"
            self.name = "Cloud vision AI — told it was edited"
            self.adaptive = True

    def available(self) -> bool:
        return bool(providers()) and os.environ.get("TRACELESS_OFFLINE", "0") != "1"

    def attack(self, img: Image.Image, ctx: AttackContext) -> AttackResult:
        t0 = time.time()
        if not self.available():
            return self.failed(ctx, "no cloud key / offline mode", status="skipped", t0=t0)
        b64 = _jpeg_b64(img)
        prompt = PROMPT + (ADAPTIVE if self.adaptive else "")
        errors = []
        for name, fn in providers():  # failover in order
            outs: list[dict] = []
            budget = max(5.0, ctx.timeout_s - (time.time() - t0))
            ex = cf.ThreadPoolExecutor(N_CALLS)
            futs = [ex.submit(fn, b64, prompt, budget) for _ in range(N_CALLS)]
            try:
                for f in cf.as_completed(futs, timeout=budget):
                    try:
                        outs.append(f.result())
                    except Exception as e:
                        errors.append(f"{name}: {type(e).__name__}: {str(e)[:120]}")
            except cf.TimeoutError:
                errors.append(f"{name}: timeout")
            finally:
                ex.shutdown(wait=False, cancel_futures=True)  # never block the demo
            if outs:
                return self._build(outs, ctx, name, t0)
        status = "timeout" if errors and all("timeout" in e for e in errors) else "failed"
        return self.failed(ctx, "; ".join(errors) or "no provider", status=status, t0=t0)

    def _build(self, outs: list[dict], ctx: AttackContext, provider: str, t0: float) -> AttackResult:
        hyps: list[Hypothesis] = []
        for o in outs:
            hs = [h for h in o.get("hypotheses", []) if -90 <= h["lat"] <= 90 and -180 <= h["lon"] <= 180]
            z = sum(max(0.0, h["probability"]) for h in hs) or 1.0
            for h in hs:
                hyps.append(Hypothesis(
                    lat=h["lat"], lon=h["lon"],
                    probability=max(0.0, h["probability"]) / z / len(outs),
                    radius_km=max(0.5, min(5000.0, h.get("radius_km") or 25.0)),
                    reasoning=h.get("reasoning", "")[:240],
                ))
        clues = []
        for o in outs[:1]:  # boxes from the first answer (they agree closely)
            for i, c in enumerate(o.get("clues", [])[:12]):
                b = c["box"]
                x, y = min(max(b["x"], 0.0), 1.0), min(max(b["y"], 0.0), 1.0)
                w, h = min(max(b["w"], 0.0), 1.0 - x), min(max(b["h"], 0.0), 1.0 - y)
                if w * h <= 0:
                    continue
                clues.append(Clue(
                    id=f"a{i}", index=0, type=c["type"], label=c["description"][:60],
                    description=c["how_it_narrows"][:200], box=Box(x=x, y=y, w=w, h=h),
                    sources=["attacker_a"], confidence=0.7,
                ))
        res = self._result(
            image_variant=ctx.variant, provider=provider, clues=clues,
            latency_ms=int((time.time() - t0) * 1000), calls=len(outs),
        )
        if not hyps:
            res.error = "model gave no hypotheses"
            return res
        # top-1 = the single highest-probability hypothesis across calls
        res.hypotheses = hyps
        dist = Distribution.from_hypotheses(hyps)
        return finalize(res, dist, ctx)
