"""Attacker C (offline, symbolic): "The Reader".

A completely different family from GeoCLIP: it reads every piece of text in
the photo (OCR) and reasons like a human sleuth — place names against a
gazetteer (GeoNames, 26k cities), writing systems, diacritics, phone country
codes, web domains, currency symbols. It never looks at pixels otherwise, so
it is blind to architecture and vegetation, and sharp on signs.
"""

from __future__ import annotations

import math
import re
import time
import unicodedata
from collections import defaultdict

import numpy as np
from PIL import Image

from ..clues.ocr import TextLine, read_text
from ..geo import Distribution, gazetteer
from ..schemas import AttackResult, Hypothesis
from .base import AttackContext, Attacker, finalize

# Writing system -> candidate countries (weight split across them).
SCRIPTS: list[tuple[str, tuple[int, int], list[str]]] = [
    ("Hangul", (0xAC00, 0xD7AF), ["KR"]),
    ("Japanese kana", (0x3040, 0x30FF), ["JP"]),
    ("Thai", (0x0E00, 0x0E7F), ["TH"]),
    ("Greek", (0x0370, 0x03FF), ["GR", "CY"]),
    ("Hebrew", (0x0590, 0x05FF), ["IL"]),
    ("Georgian", (0x10A0, 0x10FF), ["GE"]),
    ("Armenian", (0x0530, 0x058F), ["AM"]),
    ("Devanagari", (0x0900, 0x097F), ["IN", "NP"]),
    ("Bengali", (0x0980, 0x09FF), ["BD", "IN"]),
    ("Tamil", (0x0B80, 0x0BFF), ["IN", "LK"]),
    ("Khmer", (0x1780, 0x17FF), ["KH"]),
    ("Lao", (0x0E80, 0x0EFF), ["LA"]),
    ("Myanmar", (0x1000, 0x109F), ["MM"]),
    ("Ethiopic", (0x1200, 0x137F), ["ET", "ER"]),
    ("Cyrillic", (0x0400, 0x04FF), ["RU", "UA", "BY", "BG", "RS", "KZ", "MK"]),
    ("Arabic", (0x0600, 0x06FF), ["SA", "EG", "AE", "MA", "IR", "PK", "IQ", "JO"]),
    ("Han characters", (0x4E00, 0x9FFF), ["CN", "TW", "HK", "JP", "SG"]),
]

DIACRITICS: dict[str, list[str]] = {
    "ñ": ["ES", "MX", "AR", "CO", "CL", "PE"],
    "ß": ["DE", "AT", "CH"],
    "ä": ["DE", "AT", "FI", "SE"],
    "ö": ["DE", "AT", "SE", "FI", "TR", "HU"],
    "ü": ["DE", "AT", "CH", "TR"],
    "ç": ["FR", "PT", "TR", "BR"],
    "ã": ["PT", "BR"],
    "õ": ["PT", "BR", "EE"],
    "ø": ["NO", "DK"],
    "å": ["NO", "SE", "DK", "FI"],
    "æ": ["NO", "DK"],
    "ł": ["PL"],
    "ą": ["PL"],
    "ę": ["PL"],
    "ő": ["HU"],
    "ű": ["HU"],
    "ğ": ["TR"],
    "ş": ["TR", "RO"],
    "ı": ["TR"],
    "ř": ["CZ"],
    "ů": ["CZ"],
    "č": ["CZ", "SK", "HR", "SI"],
    "ț": ["RO"],
    "ă": ["RO", "VN"],
    "đ": ["VN", "HR"],
    "ơ": ["VN"],
    "ư": ["VN"],
    "è": ["FR", "IT"],
    "à": ["FR", "IT"],
    "é": ["FR", "ES", "PT"],
}

CURRENCY: dict[str, list[str]] = {
    "€": ["DE", "FR", "IT", "ES", "NL", "PT", "AT", "BE", "IE", "GR", "FI"],
    "£": ["GB"],
    "¥": ["JP", "CN"],
    "₩": ["KR"],
    "₹": ["IN"],
    "₽": ["RU"],
    "₺": ["TR"],
    "₫": ["VN"],
    "฿": ["TH"],
    "₱": ["PH"],
    "zł": ["PL"],
    "kč": ["CZ"],
}

# Shop / street vocabulary that betrays a language (weak country evidence).
LEXICON: dict[str, list[str]] = {
    **{w: ["ES", "MX", "AR", "CO", "CL", "PE"] for w in (
        "cerveceria", "cervecería", "jamoneria", "jamonería", "restaurante", "panaderia",
        "panadería", "farmacia", "calle", "avenida", "tienda", "carniceria", "pescaderia",
        "zapateria", "ferreteria", "libreria", "peluqueria", "abierto", "salida", "plaza")},
    **{w: ["FR", "BE", "CH", "CA"] for w in (
        "boulangerie", "pharmacie", "boucherie", "patisserie", "pâtisserie", "librairie",
        "tabac", "rue", "épicerie", "fromagerie", "sortie", "ouvert", "fermé")},
    **{w: ["DE", "AT", "CH"] for w in (
        "bäckerei", "apotheke", "straße", "strasse", "metzgerei", "ausgang", "eingang",
        "geöffnet", "kiosk", "friseur", "buchhandlung", "sparkasse", "bahnhof", "platz")},
    **{w: ["IT"] for w in (
        "pizzeria", "gelateria", "trattoria", "tabaccheria", "farmacia", "via", "osteria",
        "macelleria", "panificio", "uscita", "aperto", "chiuso")},
    **{w: ["NL", "BE"] for w in ("bakkerij", "apotheek", "straat", "uitgang", "winkel")},
    **{w: ["PT", "BR"] for w in ("padaria", "farmácia", "rua", "saída", "loja", "aberto")},
    **{w: ["PL"] for w in ("apteka", "piekarnia", "ulica", "sklep", "wyjście")},
    **{w: ["US"] for w in ("drugstore", "liquor", "deli", "diner", "pharmacy", "realty", "zip")},
    **{w: ["GB", "IE"] for w in ("chemist", "takeaway", "newsagent", "pub", "estate agents")},
}

STOP = {
    "main", "royal", "super", "center", "centre", "union", "market", "street", "city",
    "bank", "hotel", "cafe", "restaurant", "pizza", "sale", "open", "store", "shop",
    "finance", "promise", "consumer", "station", "parking", "exit", "entrance", "food",
    "coffee", "house", "home", "garden", "park", "plaza", "mall", "taxi", "police",
    "pharmacy", "apotheke", "farmacia", "lotteria", "dry", "beer", "wine", "best", "good",
    "victoria", "florence", "mobile", "orange", "nice", "bath", "reading", "temple", "lincoln", "jackson", "washington", "franklin", "madison", "clinton", "salem", "marion",
    "cervecería", "cerveceria", "cafeteria", "restaurante", "paradise", "paraiso", "jamon",
    "liberty", "independence", "grand", "venus", "aurora", "crystal", "diamond", "golden",
}

TLD_RE = re.compile(r"\.(co\.[a-z]{2}|com\.[a-z]{2}|[a-z]{2})(?:/|\b)", re.I)
PHONE_CC_RE = re.compile(r"(?:\+|00)\s?(\d{1,3})[\s\-.(]")
WORD_RE = re.compile(r"[^\W\d_][\w'’\-]*", re.U)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower().strip(" .,:;!?\"'()[]")
    return s


def _is_cjk(ch: str) -> bool:
    o = ord(ch)
    return 0x3040 <= o <= 0x30FF or 0x4E00 <= o <= 0x9FFF or 0xAC00 <= o <= 0xD7AF


class _NameIndex:
    """name -> city indices, built once from the gazetteer."""

    def __init__(self) -> None:
        gaz = gazetteer()
        idx: dict[str, list[int]] = defaultdict(list)
        for i, (name, alts) in enumerate(zip(gaz.names, gaz.alternates)):
            idx[_norm(name)].append(i)
            if not alts:
                continue
            for a in alts.split(","):
                a = a.strip()
                if not a:
                    continue
                if any(_is_cjk(c) for c in a):
                    if len(a) >= 2:
                        idx[_norm(a)].append(i)
                elif len(a) >= 5 and not a.isascii():
                    idx[_norm(a)].append(i)
        self.idx = dict(idx)
        self.tld = {c["tld"].lstrip(".").lower(): iso for iso, c in gaz.countries.items() if c["tld"]}
        self.phone: dict[str, list[str]] = defaultdict(list)
        for iso, c in gaz.countries.items():
            for p in c["phone"].replace("+", "").split(" and "):
                p = p.split("-")[0].strip()
                if p.isdigit():
                    self.phone[p].append(iso)
        self.country_names = {_norm(c["name"]): iso for iso, c in gaz.countries.items()}


_INDEX: _NameIndex | None = None


def name_index() -> _NameIndex:
    global _INDEX
    if _INDEX is None:
        _INDEX = _NameIndex()
    return _INDEX


def analyze_text(lines: list[TextLine]) -> tuple[dict[str, float], dict[int, float], list[str]]:
    """Return (country scores, city scores, evidence strings)."""
    ix = name_index()
    gaz = gazetteer()
    country: dict[str, float] = defaultdict(float)
    city: dict[int, float] = defaultdict(float)
    evidence: list[str] = []
    text_all = " ".join(l.text for l in lines)
    low = text_all.lower()

    # 1. writing systems
    for label, (a, b), ccs in SCRIPTS:
        n = sum(1 for ch in text_all if a <= ord(ch) <= b)
        if n >= 2:
            w = min(3.0, 1.0 + math.log2(n)) / len(ccs) ** 0.5
            for cc in ccs:
                country[cc] += w
            evidence.append(f"{label} on signs")
    # 2. diacritics / currency
    for ch, ccs in {**DIACRITICS, **CURRENCY}.items():
        if ch in low:
            for cc in ccs:
                country[cc] += 1.0 / len(ccs) ** 0.5
            evidence.append(f"“{ch}” in text")
    # 2b. language-revealing vocabulary
    hits_lex = set()
    for w in WORD_RE.findall(low):
        w = _norm(w)
        if w in LEXICON and w not in hits_lex:
            hits_lex.add(w)
            ccs = LEXICON[w]
            for cc in ccs:
                country[cc] += 1.2 / len(ccs) ** 0.5
            evidence.append(f"the word “{w}”")
    # 3. web domains
    for m in TLD_RE.finditer(low):
        tld = m.group(1).split(".")[-1]
        if tld in ix.tld and tld not in ("co", "tv", "io", "me"):
            country[ix.tld[tld]] += 3.0
            evidence.append(f".{m.group(1)} web address")
    # 4. phone country codes
    for m in PHONE_CC_RE.finditer(text_all):
        code = m.group(1)
        for k in (code, code[:2], code[:1]):
            if k in ix.phone:
                for cc in ix.phone[k]:
                    country[cc] += 3.0 / len(ix.phone[k])
                evidence.append(f"phone code +{k}")
                break
    # 5. place names (Latin n-grams; CJK substrings)
    for ln in lines:
        words = [_norm(w) for w in WORD_RE.findall(ln.text)]
        for n in (3, 2, 1):
            for i in range(len(words) - n + 1):
                gram = " ".join(words[i : i + n])
                if gram in STOP or len(gram) < 4:
                    continue
                if gram in ix.country_names:
                    country[ix.country_names[gram]] += 3.0
                    evidence.append(f"“{gram.title()}” (country name)")
                for ci in ix.idx.get(gram, [])[:20]:
                    pop = gaz.pop[ci]
                    if n == 1 and (len(gram) < 5 or pop < 50_000):
                        continue
                    city[ci] = max(city[ci], math.log10(max(pop, 10)) * (1 + 0.5 * (n - 1)) * ln.score)
        cjk = "".join(ch if _is_cjk(ch) else " " for ch in ln.text)
        for run in cjk.split():
            for L in (4, 3, 2):
                for i in range(len(run) - L + 1):
                    sub = run[i : i + L]
                    for ci in ix.idx.get(sub, [])[:10]:
                        if gaz.pop[ci] >= 100_000:
                            city[ci] = max(city[ci], math.log10(gaz.pop[ci]) * 1.2 * ln.score)
    for ci, s in list(city.items()):
        city[ci] = s + 0.8 * country.get(gaz.cc[ci], 0.0)
    if city:
        best = sorted(city.items(), key=lambda kv: -kv[1])[:3]
        for ci, _ in best:
            evidence.append(f"“{gaz.names[ci]}” matches a place name")
    return dict(country), dict(city), list(dict.fromkeys(evidence))


def hypotheses_from(country: dict[str, float], city: dict[int, float]) -> list[Hypothesis]:
    gaz = gazetteer()
    hyps: list[Hypothesis] = []
    city_mass = 0.7 if city else 0.0
    if city:
        top = sorted(city.items(), key=lambda kv: -kv[1])[:5]
        z = np.array([s for _, s in top])
        w = np.exp(z - z.max())
        w /= w.sum()
        for (ci, _s), p in zip(top, w):
            hyps.append(Hypothesis(lat=float(gaz.lat[ci]), lon=float(gaz.lon[ci]),
                                   probability=float(p * city_mass), radius_km=15.0,
                                   reasoning=f"place name “{gaz.names[ci]}”"))
    if country:
        top_c = sorted(country.items(), key=lambda kv: -kv[1])[:4]
        z = np.array([s for _, s in top_c])
        w = np.exp(z - z.max())
        w /= w.sum()
        for (cc, _), pc in zip(top_c, w):
            idx = [i for i, c in enumerate(gaz.cc) if c == cc]
            if not idx:
                continue
            idx = sorted(idx, key=lambda i: -gaz.pop[i])[:300]
            pops = gaz.pop[idx].astype(float)
            pops /= pops.sum()
            mass = (1 - city_mass) * pc
            for i, pp in zip(idx, pops):
                if pp * mass < 1e-5:
                    continue
                hyps.append(Hypothesis(lat=float(gaz.lat[i]), lon=float(gaz.lon[i]),
                                       probability=float(pp * mass), radius_km=30.0,
                                       reasoning=f"text suggests {gaz.countries.get(cc, {}).get('name', cc)}"))
    return hyps


class ReaderAttacker(Attacker):
    id = "reader"
    name = "The Reader (offline OCR sleuth)"
    family = "symbolic"
    offline = True

    def attack(self, img: Image.Image, ctx: AttackContext, lines: list[TextLine] | None = None) -> AttackResult:
        t0 = time.time()
        try:
            if lines is None:
                lines = read_text(img)
            country, city, evidence = analyze_text(lines)
            hyps = hypotheses_from(country, city)
        except Exception as e:
            return self.failed(ctx, f"{type(e).__name__}: {e}", t0=t0)
        res = self._result(image_variant=ctx.variant, latency_ms=int((time.time() - t0) * 1000))
        if not hyps:
            res.error = "nothing readable to go on"
            return res
        dist = Distribution.from_hypotheses(hyps, samples=40_000)
        res.hypotheses = hyps
        res = finalize(res, dist, ctx)
        # keep the list short for the UI; reasoning on the top one = evidence summary
        res.hypotheses = res.hypotheses[:5]
        if res.top is not None:
            res.top.reasoning = "; ".join(evidence[:6])
        return res
