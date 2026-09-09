"""Matched bold / not-bold warning-header fixtures for calibrating W-4.

W-4 asks whether the two words "GOVERNMENT WARNING" are set in **bold type**
(27 CFR 16.22). We do not try to prove a font is bold in the abstract — we ask
whether those words are *visually heavier than the regular-weight remainder of
the same statement*, which is guaranteed present, in the same family and size.

This module renders that comparison under controlled conditions: several
families with real regular/bold pairs, two sizes, clean and mildly degraded,
plus adversarial cases (header in a heavy display face, header in a thin light
face). Ground truth per case:

  expect_bold : True  -> the header IS bold
                False -> the header is NOT bold (regular weight, same family)
                None  -> genuinely ambiguous (a heavy display face); the only
                         rule is "must not be auto-PASSed"
  grade       : "decidable" -> clean, ≥15 px, same family: the metric should get
                               this right (PASS when bold, not-FAIL... etc.)
                "review_ok" -> small / degraded / adversarial: REVIEW is a fine
                               answer; a wrong PASS is never fine.

Run:  python -m fixtures.boldness
"""

from __future__ import annotations

import io
import json
import os
import random
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from fixtures import REPO_ROOT
from ttbverify.warning import REFERENCE_WARNING

IMAGES_DIR = os.path.join(REPO_ROOT, "fixtures", "images_boldness")
CASES_JSON = os.path.join(REPO_ROOT, "fixtures", "cases_boldness.json")

_FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
_FALLBACK_DIRS = [
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/liberation",
]

# family label -> (regular file, bold file), Windows names with Linux fallbacks
FAMILIES = {
    "Georgia":   (["georgia.ttf", "DejaVuSerif.ttf"], ["georgiab.ttf", "DejaVuSerif-Bold.ttf"]),
    "Times":     (["times.ttf", "DejaVuSerif.ttf"], ["timesbd.ttf", "DejaVuSerif-Bold.ttf"]),
    "Arial":     (["arial.ttf", "DejaVuSans.ttf"], ["arialbd.ttf", "DejaVuSans-Bold.ttf"]),
    "Calibri":   (["calibri.ttf", "DejaVuSans.ttf"], ["calibrib.ttf", "DejaVuSans-Bold.ttf"]),
    "Verdana":   (["verdana.ttf", "DejaVuSans.ttf"], ["verdanab.ttf", "DejaVuSans-Bold.ttf"]),
    "Bookman":   (["BOOKOS.TTF", "DejaVuSerif.ttf"], ["BOOKOSB.TTF", "DejaVuSerif-Bold.ttf"]),
}
_HEAVY_DISPLAY = ["LATINWD.TTF", "impact.ttf", "DejaVuSans-Bold.ttf"]
_THIN_LIGHT = ["COPRGTL.TTF", "calibril.ttf", "DejaVuSans.ttf"]

_GROUND = (247, 243, 234)
_INK = (28, 24, 20)


def _font(names: list[str], size: int) -> ImageFont.FreeTypeFont:
    for name in names:
        for d in [_FONT_DIR, *_FALLBACK_DIRS]:
            p = os.path.join(d, name)
            if os.path.isfile(p):
                return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


@dataclass
class BCase:
    case_id: str
    family: str
    size: int
    degraded: bool
    expect_bold: bool | None
    grade: str
    header_fonts: list[str]
    body_fonts: list[str]
    note: str = ""

    def _render(self) -> Image.Image:
        W, H = 1000, 560
        img = Image.new("RGB", (W, H), _GROUND)
        rnd = random.Random(7)
        px = img.load()
        for _ in range(W * H // 45):          # faint paper grain
            x, y = rnd.randrange(W), rnd.randrange(H)
            r, g, b = px[x, y]
            j = rnd.randint(-5, 5)
            px[x, y] = (r + j, g + j, b + j)
        d = ImageDraw.Draw(img)

        # a little other label text so OCR segments the page like a real back label
        small = _font(["georgia.ttf", "DejaVuSerif.ttf"], 22)
        d.text((70, 40), "STONEBRIDGE CELLARS", font=_font(
            ["georgiab.ttf", "DejaVuSerif-Bold.ttf"], 26), fill=_INK)
        d.text((70, 84), "750 mL   ·   Napa Valley, California", font=small, fill=_INK)

        header_font = _font(self.header_fonts, self.size)
        body_font = _font(self.body_fonts, self.size)
        header = "GOVERNMENT WARNING:"
        body = REFERENCE_WARNING.split(": ", 1)[1]

        x0, y = 70, 190
        width = W - 140
        space = d.textlength(" ", font=body_font)
        cx = x0
        # header first, inline, then body — wrapped
        runs = [(w, header_font) for w in header.split(" ")] + \
               [(w, body_font) for w in body.split(" ")]
        line_h = int(self.size * 1.7)
        for word, fnt in runs:
            ww = d.textlength(word, font=fnt)
            if cx + ww > x0 + width:
                cx = x0
                y += line_h
            d.text((cx, y), word, font=fnt, fill=_INK)
            cx += ww + space

        img = img.crop((0, 0, W, min(H, y + line_h + 40)))

        if self.degraded:
            img = img.filter(ImageFilter.GaussianBlur(0.6))
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=72)
            buf.seek(0)
            img = Image.open(buf).copy()
        return img

    def to_record(self) -> dict:
        img = self._render()
        ext = "jpg" if self.degraded else "png"
        rel = f"fixtures/images_boldness/{self.case_id}.{ext}"
        os.makedirs(IMAGES_DIR, exist_ok=True)
        img.convert("RGB").save(os.path.join(REPO_ROOT, rel))
        return {
            "case_id": self.case_id,
            "family": self.family,
            "size": self.size,
            "degraded": self.degraded,
            "expect_bold": self.expect_bold,
            "grade": self.grade,
            "note": self.note,
            "image": {"path": rel},
        }


def _cases() -> list[BCase]:
    out: list[BCase] = []
    for fam, (reg, bold) in FAMILIES.items():
        for size in (15, 22):
            for degraded in (False, True):
                grade = "decidable" if (size >= 15 and not degraded) else "review_ok"
                out.append(BCase(
                    case_id=f"b_{fam.lower()}_{size}_{'deg' if degraded else 'clean'}_bold",
                    family=fam, size=size, degraded=degraded,
                    expect_bold=True, grade=grade,
                    header_fonts=bold, body_fonts=reg,
                    note=f"{fam} {size}px header bold, body regular"
                         + (", mild photo" if degraded else ""),
                ))
                out.append(BCase(
                    case_id=f"b_{fam.lower()}_{size}_{'deg' if degraded else 'clean'}_reg",
                    family=fam, size=size, degraded=degraded,
                    expect_bold=False, grade=grade,
                    header_fonts=reg, body_fonts=reg,
                    note=f"{fam} {size}px header regular (NOT bold), body regular"
                         + (", mild photo" if degraded else ""),
                ))

    # adversarial: header in a heavy DISPLAY face, body regular serif. Visually
    # much heavier than the body — reads as bold; auto-PASS is acceptable here.
    out.append(BCase(
        case_id="b_adv_heavy_display", family="LatinWide", size=18, degraded=False,
        expect_bold=True, grade="review_ok",
        header_fonts=_HEAVY_DISPLAY, body_fonts=["georgia.ttf", "DejaVuSerif.ttf"],
        note="Header in a heavy display face — clearly heavier than the body.",
    ))
    # adversarial: header in a THIN light face, body regular -> header lighter than
    # body. Clearly not bold; must never PASS.
    out.append(BCase(
        case_id="b_adv_thin_light", family="Copperplate", size=18, degraded=False,
        expect_bold=False, grade="decidable",
        header_fonts=_THIN_LIGHT, body_fonts=["georgia.ttf", "DejaVuSerif.ttf"],
        note="Header in a thin light face — lighter than the body.",
    ))
    return out


def main() -> None:
    os.makedirs(IMAGES_DIR, exist_ok=True)
    records = [c.to_record() for c in _cases()]
    with open(CASES_JSON, "w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=2)
        fh.write("\n")
    n_dec = sum(1 for r in records if r["grade"] == "decidable")
    print(f"wrote {len(records)} boldness cases ({n_dec} decidable) -> "
          f"{os.path.relpath(CASES_JSON, REPO_ROOT)}")


if __name__ == "__main__":
    main()
