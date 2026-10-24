from traceless.attackers.reader import analyze_text, hypotheses_from
from traceless.clues.ocr import TextLine
from traceless.geo import gazetteer


def L(t):
    return TextLine(t, 0.95, (0, 0, 100, 20))


def test_kana_and_domain_point_to_japan():
    country, city, ev = analyze_text([L("ラーメン 大阪"), L("www.example.co.jp")])
    assert max(country, key=country.get) == "JP"
    assert any("co.jp" in e for e in ev)


def test_city_name_match():
    _, city, _ = analyze_text([L("Welcome to Barcelona")])
    assert "Barcelona" in {gazetteer().names[i] for i in city}


def test_stopwords_do_not_match_cities():
    _, city, _ = analyze_text([L("MAIN STREET PHARMACY")])
    assert not city


def test_nothing_readable_gives_no_hypotheses():
    assert hypotheses_from({}, {}) == []


def test_phone_code():
    country, _, _ = analyze_text([L("Call +44 20 7946 0958")])
    assert "GB" in country
