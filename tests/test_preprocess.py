"""Deskew / keystone correction (design 2.9 sequencing, `ttbverify/preprocess.py`).

Two things are being tested here and they are not the same thing:

  * **the estimator** — given a page rotated by a known angle, does it recover
    that angle, and does it leave a straight page alone? Synthetic, fast, no
    tesseract.
  * **the geometry** — a box found in corrected space has to land back on the
    original image, at its original *size*. This is the part that bit: mapping
    all four corners and taking the enclosing box inflates a line's height by
    `width * sin(angle)`, and line height is what `rules._locate_text` uses to
    decide what is fine print. A one-degree correction was enough to turn a
    correctly-read class/type line into a FAIL that way.

Plus one corpus test for the reason the module exists at all: the brand on
`r14_wine_angle` is unreadable at zero degrees and readable after correction.
"""

from __future__ import annotations

import math

import pytest
from PIL import Image, ImageDraw

from ttbverify.models import BoundingBox
from ttbverify.preprocess import (
    MIN_ANGLE,
    Correction,
    detect,
    profile_score,
    warp,
)

# --------------------------------------------------------------------------
# synthetic pages
# --------------------------------------------------------------------------

def text_page(width: int = 800, height: int = 1000, ink: int = 30) -> Image.Image:
    """A page of text-like ink: rows of short dark bars on white.

    Deliberately not real glyphs — the estimator works on the horizontal
    projection profile, so bars exercise exactly the signal it reads, without
    making the test depend on a font being installed.
    """
    img = Image.new("L", (width, height), 255)
    d = ImageDraw.Draw(img)
    y = 60
    while y < height - 60:
        x = 60
        while x < width - 60:
            d.rectangle([x, y, x + 34, y + 14], fill=ink)
            x += 46
        y += 30
    return img


def test_a_straight_page_is_left_alone():
    corr = detect(text_page())
    assert not corr.applied
    assert corr.angle == 0.0 and corr.keystone == 0.0


def test_warp_of_an_unapplied_correction_is_the_identity():
    page = text_page()
    assert warp(page, Correction(0.0, 0.0)) is page


@pytest.mark.parametrize("applied", [-3.0, -1.5, 1.5, 3.0])
def test_it_recovers_the_angle_the_page_was_rotated_by(applied):
    skewed = text_page().rotate(applied, resample=Image.BICUBIC, fillcolor=255)
    corr = detect(skewed)

    # PIL rotates counter-clockwise for a positive angle, so the correction is
    # the negation. Getting this sign wrong doubles the skew instead of removing
    # it, and still reports a plausible-looking angle — hence the explicit test.
    assert corr.applied
    assert corr.angle == pytest.approx(-applied, abs=0.4)


def test_correcting_a_skewed_page_restores_its_profile():
    original = text_page()
    skewed = original.rotate(2.5, resample=Image.BICUBIC, fillcolor=255)
    fixed = warp(skewed, detect(skewed))
    assert profile_score(fixed) > 3 * profile_score(skewed)


def test_a_correction_is_only_applied_when_it_clearly_helps():
    # A page tilted by less than the estimator's own resolution is not worth a
    # resample; nothing should be applied for it.
    barely = text_page().rotate(0.1, resample=Image.BICUBIC, fillcolor=255)
    assert not detect(barely).applied


# --------------------------------------------------------------------------
# geometry: boxes must come back to the original image intact
# --------------------------------------------------------------------------

def test_map_box_preserves_glyph_height_for_a_wide_line():
    """The regression this exists to prevent (design 3.2 depends on line height).

    A 600 px-wide line rotated one degree has an *enclosing* box 10 px taller
    than the line itself — enough to push it under the fine-print cutoff.
    """
    corr = Correction(angle=1.0)
    line = BoundingBox(100, 400, 600, 30)
    mapped = corr.map_box(line, 1000, 1400)
    assert mapped.height == pytest.approx(30, abs=1)
    assert mapped.width == pytest.approx(600, abs=1)


def test_map_box_puts_a_region_back_where_it_came_from():
    """Round trip: mark a spot, rotate the page, correct it, and confirm the
    corrected-space position maps back onto the original mark."""
    # Light bars, one black mark: `_darkest_region` can then pick the mark out
    # without needing OCR to tell it which ink is which.
    original = text_page(ink=150)
    d = ImageDraw.Draw(original)
    d.rectangle([300, 500, 360, 540], fill=0)  # the mark, at a known place

    applied = 2.0
    skewed = original.rotate(applied, resample=Image.BICUBIC, fillcolor=255)
    corr = detect(skewed)
    corrected = warp(skewed, corr)

    found = _darkest_region(corrected, box=BoundingBox(240, 440, 180, 160))
    back = corr.map_box(found, original.width, original.height)
    assert back.left == pytest.approx(300, abs=12)
    assert back.top == pytest.approx(500, abs=12)


def test_a_keystone_does_not_move_the_centre():
    """The keystone is a turn about the vertical centre axis. If it weren't
    centred it would carry a translation, and the search would burn the
    parameter undoing its own drift."""
    corr = Correction(angle=0.0, keystone=0.12)
    x, y = corr.map_point(500.0, 700.0, 1000, 1400)
    assert (x, y) == pytest.approx((500.0, 700.0), abs=0.5)


def test_a_keystone_scales_the_two_sides_differently():
    corr = Correction(angle=0.0, keystone=0.12)
    left = corr.map_box(BoundingBox(60, 700, 100, 30), 1000, 1400)
    right = corr.map_box(BoundingBox(840, 700, 100, 30), 1000, 1400)
    assert left.width != right.width


def _darkest_region(img: Image.Image, box: BoundingBox) -> BoundingBox:
    """Bounding box of the dark pixels inside `box` — a stand-in for "the word
    OCR found here", so the round-trip test doesn't need tesseract."""
    crop = img.crop((box.left, box.top, box.right, box.bottom))
    xs, ys = [], []
    for y in range(crop.height):
        for x in range(crop.width):
            if crop.getpixel((x, y)) < 60:
                xs.append(x)
                ys.append(y)
    assert xs, "expected to find the mark"
    return BoundingBox(box.left + min(xs), box.top + min(ys),
                       max(1, max(xs) - min(xs)), max(1, max(ys) - min(ys)))


# --------------------------------------------------------------------------
# the payoff, on the real fixture
# --------------------------------------------------------------------------

@pytest.mark.corpus
def test_deskew_makes_the_angled_wine_brand_readable(tesseract_or_skip):
    """`r14_wine_angle` is photographed at a keystone plus a rotation. Its brand
    line does not appear in the OCR output at all without correction — this was
    a documented limitation of the build before this module existed."""
    from fixtures import load_realistic_cases
    from ttbverify.models import LabelApplication, Outcome
    from ttbverify.ocr import TesseractOcr
    from ttbverify.pipeline import verify

    case = next(c for c in load_realistic_cases() if c["case_id"] == "r14_wine_angle")
    app = LabelApplication(**case["application"])

    result = verify(app, TesseractOcr(deskew=True))
    brand = next(c for c in result.checks if c.check_id == "brand")
    assert brand.outcome is Outcome.PASS
    assert brand.observed and "DUBOIS" in brand.observed.upper()


@pytest.mark.corpus
def test_deskew_leaves_a_clean_render_untouched(tesseract_or_skip):
    """A generated label is already straight; correcting it would only cost a
    resample. Guards against the estimator drifting into always firing."""
    from ttbverify.ocr import TesseractOcr

    page = TesseractOcr(deskew=True).read(
        "fixtures/images_realistic/r01_whiskey_clean_front.png")
    assert not page.correction.applied


@pytest.mark.corpus
def test_deskew_can_be_switched_off(tesseract_or_skip):
    from ttbverify.ocr import TesseractOcr

    page = TesseractOcr(deskew=False).read(
        "fixtures/images_realistic/r14_wine_angle_front.jpg")
    assert not page.correction.applied


def test_min_angle_is_small_enough_to_matter():
    """A degree of skew is enough to cost OCR whole words, so the floor below
    which nothing is applied has to sit well under that."""
    assert MIN_ANGLE < 0.5
    assert math.isfinite(MIN_ANGLE)
