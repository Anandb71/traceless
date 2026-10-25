"""Cloud attacker: schema handling, failover and graceful skip — no network."""

from PIL import Image
from traceless.attackers import cloud
from traceless.attackers.base import AttackContext
from traceless.schemas import Truth

ANSWER = {
    "clues": [
        {"type": "text", "description": "Shop sign 'Boulangerie'", "how_it_narrows": "French language",
         "box": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.1}},
        {"type": "building", "description": "Haussmann facade", "how_it_narrows": "Paris",
         "box": {"x": 0.9, "y": 0.9, "w": 0.5, "h": 0.5}},  # overflows -> clipped
    ],
    "hypotheses": [
        {"lat": 48.8566, "lon": 2.3522, "probability": 0.7, "radius_km": 5, "reasoning": "Paris"},
        {"lat": 45.764, "lon": 4.8357, "probability": 0.3, "radius_km": 20, "reasoning": "Lyon"},
        {"lat": 999, "lon": 0, "probability": 0.5, "radius_km": 1, "reasoning": "invalid, dropped"},
    ],
}


def _img():
    return Image.new("RGB", (64, 48), (120, 120, 120))


def test_skipped_without_keys(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    r = cloud.CloudAttacker().attack(_img(), AttackContext())
    assert r.status == "skipped"


def test_builds_result_and_fails_over(monkeypatch):
    calls = []

    def broken(b64, prompt, timeout):
        calls.append("claude")
        raise RuntimeError("overloaded")

    def works(b64, prompt, timeout):
        calls.append("gemini")
        assert "edited" in prompt  # adaptive variant is told
        return ANSWER

    monkeypatch.setattr(cloud, "providers", lambda: [("anthropic:test", broken), ("google:test", works)])
    monkeypatch.delenv("TRACELESS_OFFLINE", raising=False)
    ctx = AttackContext(truth=Truth(lat=48.8584, lon=2.2945, source="fixture"), radius_km=25)
    r = cloud.CloudAttacker(adaptive=True).attack(_img(), ctx)
    assert r.status == "ok" and r.provider == "google:test" and r.adaptive
    assert "claude" in calls and "gemini" in calls
    assert r.top is not None and abs(r.top.lat - 48.8566) < 1e-6
    assert r.distance_km is not None and r.distance_km < 10 and r.within_radius
    assert r.credible_area_km2 and r.distribution
    assert all(0 <= c.box.x + c.box.w <= 1.0001 and 0 <= c.box.y + c.box.h <= 1.0001 for c in r.clues)
    assert all(-90 <= h.lat <= 90 for h in r.hypotheses)
