from traceless.schemas import AttackResult, Box, Clue, DefensePlan


def test_box_px_roundtrip():
    b = Box.from_px(10, 20, 110, 70, 200, 100)
    assert b.to_px(200, 100) == (10, 20, 110, 70)
    assert abs(b.iou(b) - 1) < 1e-9


def test_models_roundtrip_json():
    c = Clue(id="c1", index=1, type="text", label="Sign", box=Box(x=0, y=0, w=0.1, h=0.1))
    a = AttackResult(attacker_id="geoclip", attacker_name="GeoCLIP", family="retrieval", offline=True)
    p = DefensePlan()
    for m in (c, a, p):
        assert type(m).model_validate_json(m.model_dump_json()) == m
