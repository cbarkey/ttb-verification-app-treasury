"""Deskew and mild keystone correction, ahead of OCR (design 2.4, 2.9).

**Why this exists and why it comes before the vision model.** A label
photographed by hand is rotated a degree or two and often turned slightly away
from the camera. Tesseract degrades sharply on both: on the `r14_wine_angle`
fixture the brand line `MAISON DUBOIS` is simply absent from the OCR output at
0 degrees and present after a 4 degree correction. That is a deterministic
problem with a deterministic fix costing tens of milliseconds, and paying a
2.5 s nondeterministic network round trip to paper over it would be both slower
and less honest about where the remaining difficulty is (CLAUDE.md 2.9).

**How the angle is found.** Text lines are alternating bands of ink and paper,
so the horizontal projection profile of a correctly-oriented page swings hard
between rows and flattens as the page rotates. Score a candidate correction by
the mean squared difference between adjacent rows of that profile and take the
best. Two properties make this the right choice here:

  * it needs no numpy, no OpenCV and no Hough transform — `resize((1, h),
    Image.BOX)` *is* the row-mean projection, and Pillow is already a dependency
    (N-06 keeps the dependency surface small on purpose);
  * it is scored on the actual image, so a clean label scores best at zero
    degrees and gets no correction at all. Nothing is applied speculatively.

**Boxes must come back to original coordinates.** The review screen overlays
regions on the image the agent uploaded, and `warning.assess_boldness` crops
from it. So a correction is kept as a 3x3 projective matrix mapping
corrected-space to original-space, and every OCR box is mapped back through it
(`Correction.map_box`) before it leaves `ocr.py`. Downstream code never learns
that a correction happened — which is why nothing else in the pipeline changed
when this landed.

The keystone term is a single projective parameter (a horizontal-axis turn). It
is deliberately not a full four-point unwarp: detecting the label's quadrilateral
reliably needs edge detection this prototype does not have, and the residual —
glare, blur, genuinely bad light — is the vision model's job, not this module's.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PIL import Image, ImageOps

from ttbverify.models import BoundingBox

# Search bounds. Beyond a few degrees an image is not "a slightly crooked photo"
# any more, and a wide search invites spurious optima off label artwork.
MAX_ANGLE = 6.0
MAX_KEYSTONE = 0.24

# Apply a correction only when the profile score improves by at least this much.
# Clean renders sit at ~1.00 and are left untouched; the degraded fixtures score
# 4x-8x. Nothing in between showed up in the corpus, so the threshold is not
# finely balanced — it just has to be clearly above 1.
MIN_GAIN = 1.20

# Corrections smaller than this are noise; applying them costs a resample for
# nothing.
MIN_ANGLE = 0.2
MIN_KEYSTONE = 0.01

_COARSE_WIDTH = 240  # scoring image for the joint (angle, keystone) grid
_FINE_WIDTH = 480  # scoring image for the refinement passes
_SCORE_CROP = 0.84  # centre crop, so borders and vignette don't drive the score


@dataclass(frozen=True)
class Correction:
    """A geometric correction, and the inverse map back to original pixels."""

    angle: float = 0.0  # degrees; positive rotates content clockwise
    keystone: float = 0.0
    gain: float = 1.0  # profile-score ratio vs. doing nothing

    @property
    def applied(self) -> bool:
        return abs(self.angle) >= MIN_ANGLE or abs(self.keystone) >= MIN_KEYSTONE

    def describe(self) -> str:
        bits = []
        if abs(self.angle) >= MIN_ANGLE:
            bits.append(f"rotated {self.angle:+.1f} deg")
        if abs(self.keystone) >= MIN_KEYSTONE:
            bits.append(f"keystone {self.keystone:+.3f}")
        return ", ".join(bits) or "none"

    def to_dict(self) -> dict:
        return {
            "angle": round(self.angle, 2),
            "keystone": round(self.keystone, 4),
            "gain": round(self.gain, 2),
        }

    # -- geometry ------------------------------------------------------

    def matrix(self, width: int, height: int) -> list[list[float]]:
        """3x3 map: a point in corrected space -> the point it was sampled from.

        This is exactly the mapping Pillow's ``Image.PERSPECTIVE`` wants (output
        to input), which is what makes both the warp and the box mapping fall out
        of one matrix.
        """
        a = math.radians(self.angle)
        ca, sa = math.cos(a), math.sin(a)
        cx, cy = width / 2.0, height / 2.0
        m = [
            [ca, -sa, cx - ca * cx + sa * cy],
            [sa, ca, cy - sa * cx - ca * cy],
            [0.0, 0.0, 1.0],
        ]
        if self.keystone:
            # A turn about the *vertical centre axis*: scale varies with distance
            # from the middle of the image, not from its left edge. Centring it
            # matters — an off-centre projective is partly a translation, and the
            # search would spend the parameter undoing its own drift.
            g = self.keystone / max(width, 1)
            k = _matmul(
                _translate(cx, cy),
                _matmul([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [g, 0.0, 1.0]],
                        _translate(-cx, -cy)),
            )
            m = _matmul(m, k)
        return m

    def map_point(self, x: float, y: float, width: int, height: int) -> tuple[float, float]:
        m = self.matrix(width, height)
        w = m[2][0] * x + m[2][1] * y + m[2][2]
        if abs(w) < 1e-9:
            return x, y
        return (
            (m[0][0] * x + m[0][1] * y + m[0][2]) / w,
            (m[1][0] * x + m[1][1] * y + m[1][2]) / w,
        )

    def map_box(self, box: BoundingBox, width: int, height: int) -> BoundingBox:
        """Corrected-space box -> where it sits on the original image.

        **Position is mapped; size is preserved.** The obvious implementation —
        map all four corners and take their enclosing box — is wrong here, and
        subtly so. A rotated rectangle's enclosing box grows by `w * sin(angle)`
        in height, which inflates *long* lines far more than short ones. Line
        height is not decoration downstream: `rules._locate_text` uses it as the
        fine-print test (design 3.2). Corner-mapping at 1 degree was enough to
        push a correctly-read class/type line over that threshold and turn a PASS
        into a FAIL.

        So the centre is mapped through the projective and the side lengths are
        measured along the mapped edges — for a pure rotation that returns the
        original glyph height exactly. The box is then axis-aligned again, which
        leaves it a degree or two off true; at these angles that is a pixel of
        overlay slack, against a category of error that changes verdicts.
        """
        if not self.applied:
            return box
        cx, cy = box.left + box.width / 2.0, box.top + box.height / 2.0
        mid_l = self.map_point(box.left, cy, width, height)
        mid_r = self.map_point(box.left + box.width, cy, width, height)
        mid_t = self.map_point(cx, box.top, width, height)
        mid_b = self.map_point(cx, box.top + box.height, width, height)
        w = math.dist(mid_l, mid_r)
        h = math.dist(mid_t, mid_b)
        ox, oy = self.map_point(cx, cy, width, height)
        return BoundingBox(
            round(ox - w / 2.0),
            round(oy - h / 2.0),
            max(1, round(w)),
            max(1, round(h)),
        )


IDENTITY = Correction()


def _translate(dx: float, dy: float) -> list[list[float]]:
    return [[1.0, 0.0, dx], [0.0, 1.0, dy], [0.0, 0.0, 1.0]]


def _matmul(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    return [[sum(a[i][t] * b[t][j] for t in range(3)) for j in range(3)] for i in range(3)]


def _coeffs(m: list[list[float]]) -> tuple[float, ...]:
    scale = m[2][2] or 1.0
    flat = (m[0][0], m[0][1], m[0][2], m[1][0], m[1][1], m[1][2], m[2][0], m[2][1])
    return tuple(v / scale for v in flat)


def warp(img: Image.Image, corr: Correction, *, resample=Image.BICUBIC) -> Image.Image:
    """Apply a correction. Returns the image unchanged when there's nothing to do."""
    if not corr.applied:
        return img
    fill = 255 if img.mode == "L" else None
    return img.transform(
        img.size,
        Image.PERSPECTIVE,
        _coeffs(corr.matrix(img.width, img.height)),
        resample=resample,
        fillcolor=fill,
    )


def profile_score(img: Image.Image) -> float:
    """Mean squared difference between adjacent rows of the row-mean profile.

    High when text lines are horizontal, low when they are smeared across rows.
    `resize((1, h), BOX)` averages each row in C — this is the whole reason the
    search is fast enough to run on every image.
    """
    w, h = img.size
    if w < 8 or h < 8:
        return 0.0
    inset_x = int(w * (1 - _SCORE_CROP) / 2)
    inset_y = int(h * (1 - _SCORE_CROP) / 2)
    crop = img.crop((inset_x, inset_y, w - inset_x, h - inset_y))
    # `tobytes()` on a 1-px-wide "L" image is the row means, one byte each —
    # cheaper than getdata() and not deprecated.
    rows = crop.resize((1, crop.height), Image.BOX).convert("L").tobytes()
    if len(rows) < 3:
        return 0.0
    return sum((rows[i + 1] - rows[i]) ** 2 for i in range(len(rows) - 1)) / (len(rows) - 1)


def _scoring_image(img: Image.Image, width: int) -> Image.Image:
    g = img if img.mode == "L" else img.convert("L")
    if g.width <= width:
        return g
    return g.resize((width, max(1, round(g.height * width / g.width))), Image.BILINEAR)


def _score(img: Image.Image, angle: float, keystone: float) -> float:
    return profile_score(warp(img, Correction(angle, keystone), resample=Image.BILINEAR))


def _refine(img: Image.Image, best: tuple[float, float, float],
            angle_steps: list[float], keystone_steps: list[float]
            ) -> tuple[float, float, float]:
    """One coordinate-descent pass: angle around the incumbent, then keystone."""
    angle, keystone, score = best
    for a in (angle + d for d in angle_steps):
        if abs(a) > MAX_ANGLE:
            continue
        s = _score(img, a, keystone)
        if s > score:
            angle, score = a, s
    for k in (keystone + d for d in keystone_steps):
        if abs(k) > MAX_KEYSTONE:
            continue
        s = _score(img, angle, k)
        if s > score:
            keystone, score = k, s
    return angle, keystone, score


def detect(img: Image.Image) -> Correction:
    """Find the correction that best straightens the text lines.

    A **joint** coarse grid over (angle, keystone), then coordinate-descent
    refinement. The joint grid is the expensive-looking part and it is not
    optional: rotation and keystone trade off against each other, so descending
    from the rotation-only optimum lands in the wrong basin. On
    `r14_wine_angle` that difference is `Grown on south-facing slopes and aged
    in French oak` versus `'own -facing slopes an aged in Fre' ach o ak`.

    Cost is controlled by resolution instead — the grid runs on a 240 px-wide
    copy where a single transform is a fraction of a millisecond, and only the
    refinement sees 480 px.
    """
    coarse = _scoring_image(img, _COARSE_WIDTH)
    if profile_score(coarse) <= 0:
        return IDENTITY

    best = (0.0, 0.0, 0.0)
    for i in range(-int(MAX_ANGLE), int(MAX_ANGLE) + 1):
        for j in (-2, -1, 0, 1, 2):
            a, k = i * 1.0, j * 0.08
            s = _score(coarse, a, k)
            if s > best[2]:
                best = (a, k, s)

    fine = _scoring_image(img, _FINE_WIDTH)
    base = profile_score(fine)
    if base <= 0:
        return IDENTITY
    best = (best[0], best[1], _score(fine, best[0], best[1]))
    best = _refine(fine, best, [-0.5, -0.25, 0.25, 0.5], [-0.04, -0.02, 0.02, 0.04])
    best = _refine(fine, best, [-0.125, 0.125], [-0.01, 0.01])
    angle, keystone, score = best

    if abs(keystone) < MIN_KEYSTONE:
        keystone = 0.0
    gain = score / base if base else 1.0
    if gain < MIN_GAIN:
        return Correction(0.0, 0.0, gain)
    if abs(angle) < MIN_ANGLE and abs(keystone) < MIN_KEYSTONE:
        return Correction(0.0, 0.0, gain)
    return Correction(angle, keystone, gain)


def prepare(image_path: str, *, target_width: int, deskew: bool = True
            ) -> tuple[Image.Image, float, Correction]:
    """Full pre-OCR chain: EXIF orient, grayscale, autocontrast, deskew, upscale.

    Returns the prepared image, the scale factor applied by the upscale, and the
    correction — the caller needs the last two to put boxes back where the agent
    can see them.
    """
    img = Image.open(image_path)
    img = ImageOps.exif_transpose(img)
    img = img.convert("L")
    img = ImageOps.autocontrast(img)

    corr = detect(img) if deskew else IDENTITY

    scale = 1.0
    if img.width < target_width:
        scale = target_width / img.width
        img = img.resize((round(img.width * scale), round(img.height * scale)),
                         Image.LANCZOS)

    # Warp *after* the upscale, not before. Both orders are geometrically
    # identical — the keystone term is normalized by width, so the correction is
    # resolution-independent — but resampling a 1600 px image loses less of the
    # glyph than resampling a 1000 px one and then enlarging the damage.
    # Measurable: it is the difference between reading OLD TOM DISTILLERY and
    # OLD TOM DISTIELERY on `r11_whiskey_photo`.
    return warp(img, corr), scale, corr
