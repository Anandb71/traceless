import numpy as np

from traceless.defense.inpaint import blur, glyph_mask, portrait_blur, soften


def _sign():
    img = np.full((60, 200, 3), 230, np.uint8)  # light board
    for x in (20, 50, 80):
        img[20:40, x : x + 10] = 20  # dark letters
    return img


def test_glyph_mask_finds_letters_not_board():
    img = _sign()
    m = glyph_mask(img, (10, 10, 190, 50))
    assert m[30, 25] and m[30, 55]
    assert not m[15, 150]


def test_blur_stays_local():
    img = _sign()
    m = np.zeros(img.shape[:2], bool)
    m[20:40, 20:90] = True
    out = blur(img, m)
    assert (out[:, 150:] == img[:, 150:]).all()


def test_soften_reduces_local_contrast():
    rng = np.random.default_rng(0)
    img = rng.integers(0, 255, (50, 50, 3), dtype=np.uint8)
    m = np.zeros((50, 50), bool)
    m[10:40, 10:40] = True
    out = soften(img, m)
    assert out[15:35, 15:35].std() < img[15:35, 15:35].std()


def test_portrait_blur_keeps_person_pixel_identical():
    rng = np.random.default_rng(1)
    img = rng.integers(0, 255, (80, 80, 3), dtype=np.uint8)
    keep = np.zeros((80, 80), bool)
    keep[20:60, 30:50] = True
    out = portrait_blur(img, keep)
    assert (out[keep] == img[keep]).all()
    assert out[~keep].std() < img[~keep].std()
