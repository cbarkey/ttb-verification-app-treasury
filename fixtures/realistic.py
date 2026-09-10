"""A second, deliberately *un*-clean fixture corpus.

The `fixtures/generate.py` corpus is black text on white — it proves the rules
but barely stresses OCR or field location. This module renders labels that look
more like the real thing: colour grounds and gradients, framed borders, display
faces (Copperplate / Baskerville / slab serif), a medallion, a barcode block, a
neck band, and the government warning presented the way real labels present it
(a small justified block, sometimes ruled into a box). Half the set then gets a
"photo of a bottle" pass — a few degrees of rotation, a lighting vignette, mild
blur, JPEG compression.

Ground truth is still exact because every pixel is drawn here. Cases are graded:

  * ``exact`` — behaves like the clean corpus; every listed check must match.
  * ``loose`` — realistic degradation may nudge a clean field to REVIEW, and a
    hard-to-read one to UNREADABLE. The invariant that still holds absolutely:
    **no false approvals** — a FAIL/REVIEW ground-truth cell must never land on
    PASS.

Run:  python -m fixtures.realistic
"""

from __future__ import annotations

import contextlib
import json
import os
from dataclasses import dataclass, field
from typing import ClassVar

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from fixtures import REPO_ROOT, audit_corpus
from ttbverify.warning import REFERENCE_WARNING

IMAGES_DIR = os.path.join(REPO_ROOT, "fixtures", "images_realistic")
CASES_JSON = os.path.join(REPO_ROOT, "fixtures", "cases_realistic.json")

_FONT_DIRS = [
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/liberation",
    "/Library/Fonts",
]


def _font(names: list[str], size: int) -> ImageFont.FreeTypeFont:
    for name in names:
        for d in _FONT_DIRS:
            p = os.path.join(d, name)
            if os.path.isfile(p):
                return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


# Font stacks: a Windows face first, then a cross-platform fallback so the
# generator at least runs on Linux/CI (the committed PNGs are the source of truth).
DISPLAY_SERIF = ["COPRGTL.TTF", "BASKVILL.TTF", "georgiab.ttf", "DejaVuSerif-Bold.ttf"]
SLAB = ["ROCKB.TTF", "rockb.ttf", "georgiab.ttf", "DejaVuSerif-Bold.ttf"]
BASKERVILLE = ["BASKVILL.TTF", "pala.ttf", "georgia.ttf", "DejaVuSerif.ttf"]
GILL = ["GILC____.TTF", "calibri.ttf", "trebuc.ttf", "DejaVuSans.ttf"]
BODY_SERIF = ["georgia.ttf", "constan.ttf", "times.ttf", "DejaVuSerif.ttf"]
BODY_SERIF_B = ["georgiab.ttf", "constanb.ttf", "timesbd.ttf", "DejaVuSerif-Bold.ttf"]
BODY_SERIF_I = ["georgiai.ttf", "constani.ttf", "timesi.ttf", "DejaVuSerif-Italic.ttf"]
BODY_SANS = ["calibri.ttf", "arial.ttf", "DejaVuSans.ttf"]


@dataclass(frozen=True)
class Theme:
    bg: tuple
    bg2: tuple           # gradient partner (== bg for flat)
    ink: tuple
    faint: tuple
    accent: tuple
    display: list        # font stack for the brand
    body: list
    body_i: list
    letter_spacing: int  # extra px between display caps


WHISKEY = Theme(
    bg=(244, 234, 214), bg2=(226, 209, 176), ink=(38, 30, 22), faint=(96, 82, 60),
    accent=(122, 90, 46), display=DISPLAY_SERIF, body=BODY_SERIF, body_i=BODY_SERIF_I,
    letter_spacing=8,
)
RUM_DARK = Theme(
    bg=(26, 22, 18), bg2=(14, 12, 10), ink=(238, 228, 205), faint=(170, 156, 128),
    accent=(184, 134, 11), display=SLAB, body=BODY_SERIF, body_i=BODY_SERIF_I,
    letter_spacing=6,
)
WINE = Theme(
    bg=(247, 244, 238), bg2=(238, 232, 220), ink=(26, 24, 22), faint=(110, 100, 92),
    accent=(107, 31, 42), display=BASKERVILLE, body=BODY_SERIF, body_i=BODY_SERIF_I,
    letter_spacing=4,
)
GIN = Theme(
    bg=(238, 242, 244), bg2=(224, 232, 236), ink=(20, 50, 74), faint=(78, 104, 124),
    accent=(20, 50, 74), display=GILL, body=BODY_SANS, body_i=BODY_SERIF_I,
    letter_spacing=10,
)


# --------------------------------------------------------------------------
# rendering primitives
# --------------------------------------------------------------------------

class Sheet:
    def __init__(self, w: int, h: int, theme: Theme, flat: bool = False):
        self.w, self.h, self.t = w, h, theme
        self.img = Image.new("RGB", (w, h), theme.bg)
        if not flat:
            self._gradient()
        self._paper_noise()
        self.d = ImageDraw.Draw(self.img)
        self.y = 0

    def _gradient(self) -> None:
        top, bot = self.t.bg, self.t.bg2
        d = ImageDraw.Draw(self.img)
        for row in range(self.h):
            f = row / max(1, self.h - 1)
            c = tuple(round(top[i] + (bot[i] - top[i]) * f) for i in range(3))
            d.line([(0, row), (self.w, row)], fill=c)

    def _paper_noise(self) -> None:
        import random

        rnd = random.Random(17)
        px = self.img.load()
        for _ in range(self.w * self.h // 40):
            x = rnd.randrange(self.w)
            y = rnd.randrange(self.h)
            r, g, b = px[x, y]
            j = rnd.randint(-6, 6)
            px[x, y] = (max(0, min(255, r + j)), max(0, min(255, g + j)),
                        max(0, min(255, b + j)))

    # -- text helpers --
    #
    # Everything centred goes through _fit(): text that would run past the
    # margins is shrunk until it fits. A label that prints its brand off the
    # edge is unreadable to OCR *and* to a person, and an earlier version of
    # this generator did exactly that — silently.

    MARGIN_X = 60

    def _width(self, text: str, font: ImageFont.FreeTypeFont, spacing: int) -> float:
        return self.d.textlength(text, font=font) + spacing * max(0, len(text) - 1)

    def _fit(self, text: str, stack: list[str], size: int, spacing: int
             ) -> tuple[ImageFont.FreeTypeFont, int]:
        """Largest size (and, if needed, reduced tracking) that fits the label."""
        max_w = self.w - 2 * self.MARGIN_X
        sp = spacing
        while size >= 10:
            font = _font(stack, size)
            if self._width(text, font, sp) <= max_w:
                return font, sp
            if sp > 0:
                sp = max(0, sp - 2)
                continue
            size -= 2
            sp = spacing
        return _font(stack, 10), 0

    def _center_x(self, text: str, font: ImageFont.FreeTypeFont, spacing: int) -> float:
        return max(self.MARGIN_X, (self.w - self._width(text, font, spacing)) / 2)

    def caps(self, text: str, font: ImageFont.FreeTypeFont, *, gap: int,
             spacing: int | None = None, fill=None, y: float | None = None) -> None:
        """Centered display text with optional letter-spacing."""
        sp = self.t.letter_spacing if spacing is None else spacing
        fill = fill or self.t.ink
        yy = self.y if y is None else y
        x = self._center_x(text, font, sp)
        for ch in text:
            self.d.text((x, yy), ch, font=font, fill=fill)
            x += self.d.textlength(ch, font=font) + sp
        asc, desc = font.getmetrics()
        if y is None:
            self.y = yy + asc + desc + gap

    def caps_fit(self, text: str, stack: list[str], size: int, *, gap: int,
                 spacing: int | None = None, fill=None,
                 y: float | None = None) -> None:
        """`caps`, but shrink-to-fit the label width first."""
        sp = self.t.letter_spacing if spacing is None else spacing
        font, sp = self._fit(text, stack, size, sp)
        self.caps(text, font, gap=gap, spacing=sp, fill=fill, y=y)

    def line_center(self, text: str, font: ImageFont.FreeTypeFont, *, gap: int,
                    fill=None, y: float | None = None) -> None:
        fill = fill or self.t.ink
        yy = self.y if y is None else y
        x = max(self.MARGIN_X, (self.w - self.d.textlength(text, font=font)) / 2)
        self.d.text((x, yy), text, font=font, fill=fill)
        asc, desc = font.getmetrics()
        if y is None:
            self.y = yy + asc + desc + gap

    def rule(self, *, inset: int, gap: int, weight: int = 2, dots: bool = False) -> None:
        y = self.y
        if dots:
            x = inset
            while x < self.w - inset:
                self.d.ellipse([x, y, x + 2, y + 2], fill=self.t.accent)
                x += 10
        else:
            self.d.line([(inset, y), (self.w - inset, y)], fill=self.t.accent,
                        width=weight)
        self.y = y + gap

    def frame(self, inset: int, *, double: bool = True) -> None:
        self.d.rectangle([inset, inset, self.w - inset, self.h - inset],
                         outline=self.t.accent, width=3)
        if double:
            self.d.rectangle([inset + 7, inset + 7, self.w - inset - 7,
                              self.h - inset - 7], outline=self.t.accent, width=1)

    def medallion(self, cx: int, cy: int, r: int, top: str, bottom: str) -> None:
        self.d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=self.t.accent, width=3)
        self.d.ellipse([cx - r + 6, cy - r + 6, cx + r - 6, cy + r - 6],
                       outline=self.t.accent, width=1)
        f = _font(self.t.body, 15)
        self.line_center(top, f, gap=0, y=cy - r + 14)
        self.line_center(bottom, f, gap=0, y=cy + r - 30)
        self.d.line([(cx - 14, cy), (cx + 14, cy)], fill=self.t.accent, width=2)

    def barcode(self, x: int, y: int, w: int, h: int) -> None:
        import random

        rnd = random.Random(4)
        cx = x
        while cx < x + w:
            bw = rnd.choice([2, 2, 3, 5])
            if rnd.random() > 0.35:
                self.d.rectangle([cx, y, cx + bw, y + h], fill=(20, 20, 20))
            cx += bw + rnd.choice([2, 3])
        self.d.text((x, y + h + 2), "0 12345 67890 5", font=_font(BODY_SANS, 12),
                    fill=(20, 20, 20))

    def paragraph(self, runs: list[tuple[str, ImageFont.FreeTypeFont]], *,
                  x: int, width: int, gap: int, fill=None, justify: bool = True,
                  y: float | None = None) -> tuple[int, int, int, int]:
        """Flow (text, font) runs into wrapped lines. Returns the bbox drawn."""
        fill = fill or self.t.ink
        yy = self.y if y is None else y
        top = yy
        words: list[tuple[str, ImageFont.FreeTypeFont]] = []
        for text, fnt in runs:
            for w in text.split(" "):
                if w:
                    words.append((w, fnt))

        line: list[tuple[str, ImageFont.FreeTypeFont]] = []
        max_x = x

        def flush(last: bool) -> None:
            nonlocal yy, max_x
            if not line:
                return
            widths = [self.d.textlength(w, font=f) for w, f in line]
            sp = self.d.textlength(" ", font=line[0][1])
            slack = width - sum(widths) - sp * (len(line) - 1)
            extra = 0.0
            if justify and not last and len(line) > 1 and 0 < slack < width * 0.35:
                extra = slack / (len(line) - 1)
            cx = x
            asc, desc = line[0][1].getmetrics()
            for (w, f), ww in zip(line, widths, strict=False):
                self.d.text((cx, yy), w, font=f, fill=fill)
                cx += ww + sp + extra
            max_x = max(max_x, cx - sp - extra)
            yy += asc + desc + 4

        for w, f in words:
            probe = [*line, (w, f)]
            tw = sum(self.d.textlength(x2, font=f2) for x2, f2 in probe)
            tw += self.d.textlength(" ", font=f) * (len(probe) - 1)
            if line and tw > width:
                flush(False)
                line = [(w, f)]
            else:
                line.append((w, f))
        flush(True)
        if y is None:
            self.y = yy + gap
        return (x, top, round(max_x), round(yy))

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.img.save(path)


def warning_runs(theme: Theme, mode: str, size: int = 15):
    body = REFERENCE_WARNING.split(": ", 1)[1]
    header = "Government Warning:" if mode == "titlecase" else "GOVERNMENT WARNING:"
    if mode == "reworded":
        body = body.replace("operate machinery", "operate a boat")
    elif mode == "charnoise":
        body = body.replace("machinery", "machinory")
    hf = _font(BODY_SERIF_B if mode != "nonbold" else BODY_SERIF, size)
    bf = _font(BODY_SERIF, size)
    return [(header + " ", hf), (body, bf)]


# --------------------------------------------------------------------------
# degradation ("a photo of the bottle")
# --------------------------------------------------------------------------

def _vignette(img: Image.Image, strength: float) -> Image.Image:
    mask = Image.new("L", img.size, 0)
    d = ImageDraw.Draw(mask)
    d.ellipse([-img.width * 0.25, -img.height * 0.25,
               img.width * 1.25, img.height * 1.25], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(img.width // 6))
    dark = Image.new("RGB", img.size, (0, 0, 0))
    return Image.composite(img, Image.blend(img, dark, strength), mask)


def _perspective(img: Image.Image, k: float) -> Image.Image:
    """Mild keystone, as if the bottle were turned slightly away from the camera.

    Uses PIL's QUAD transform (no numpy): the output rectangle is sampled from a
    trapezoid of the source — right edge pulled in, so the right side looks
    farther away.
    """
    w, h = img.size
    dx, dy = w * k, h * k * 0.4
    # source quad: UL, LL, LR, UR
    quad = (0, 0,
            0, h,
            w - dx, h - dy,
            w - dx, dy)
    return img.transform((w, h), Image.QUAD, data=quad, resample=Image.BICUBIC,
                         fillcolor=(232, 224, 208))


def degrade(img: Image.Image, *, rotate=0.0, blur=0.0, vignette=0.0, jpeg=0,
            perspective=0.0) -> tuple[Image.Image, str]:
    if perspective:
        # A degenerate quad just means "no keystone on this one"; the fixture is
        # still a valid test of everything else.
        with contextlib.suppress(Exception):
            img = _perspective(img, perspective)
    if rotate:
        img = img.rotate(rotate, resample=Image.BICUBIC, expand=False,
                         fillcolor=(232, 224, 208))
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    if vignette:
        img = _vignette(img, vignette)
    fmt = "png"
    if jpeg:
        import io

        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=jpeg)
        buf.seek(0)
        img = Image.open(buf).copy()
        fmt = "jpg"
    return img, fmt


# --------------------------------------------------------------------------
# case model + layout
# --------------------------------------------------------------------------

_THEMES = {"whiskey": WHISKEY, "rum": RUM_DARK, "wine": WINE, "gin": GIN}


@dataclass
class RCase:
    case_id: str
    grade: str                       # "exact" | "loose"
    commodity: str                   # wine | malt | spirits
    theme: str
    serial: str
    ttb_id: str | None
    brand: str
    class_type: str
    alcohol_content: str | None
    net_contents: str | None
    applicant_name: str | None
    applicant_address: str | None
    origin: str | None
    expect: dict
    label_brand: str | None = None
    label_abv_line: str | None = None
    label_net: str | None = None
    label_origin_text: str | None = None
    producer_line: str | None = None
    fineprint_extra: str | None = None
    warning_mode: str = "compliant"
    warning_style: str = "block"      # block | boxed | sidebar
    single_image: bool = False
    degrade: dict = field(default_factory=dict)
    note: str = ""

    # -- rendering --

    def _t(self) -> Theme:
        return _THEMES[self.theme]

    def _front(self) -> Image.Image:
        t = self._t()
        s = Sheet(1000, 1560 if self.single_image else 1400, t)
        s.frame(40)
        s.y = 96
        s.caps("ESTABLISHED 1897", _font(t.body, 18), gap=8, spacing=6, fill=t.faint)
        s.rule(inset=300, gap=40, dots=True)

        brand = (self.label_brand or self.brand)
        parts = brand.split(" ")
        one_line, _sp = s._fit(brand, t.display, 72, t.letter_spacing)
        # Wrap onto two lines only when a single line would have to shrink a lot,
        # and never strand a 1-2 char word on its own line.
        if one_line.size >= 60 or len(parts) < 3:
            s.caps_fit(brand, t.display, 72, gap=24)
        else:
            best = min(range(1, len(parts)),
                       key=lambda i: abs(len(" ".join(parts[:i])) - len(" ".join(parts[i:]))))
            s.caps_fit(" ".join(parts[:best]), t.display, 72, gap=6)
            s.caps_fit(" ".join(parts[best:]), t.display, 72, gap=24)


        s.rule(inset=260, gap=26)
        s.line_center("Small Batch Reserve", _font(t.body_i, 30), gap=26, fill=t.faint)
        s.caps_fit(self.class_type, t.body, 30, gap=30, spacing=2)

        s.medallion(500, 760, 92, "AGED", "IN OAK")

        # ABV and net contents sit together (TTB "same field of vision").
        abv = self.label_abv_line or self.alcohol_content
        if abv:
            s.caps(abv, _font(t.body, 26), gap=14, spacing=2, y=940)
        net = self.label_net or self.net_contents
        if net:
            s.line_center(net, _font(t.body, 24), gap=0, y=996)

        prod = self.producer_line
        if prod is None and self.applicant_name:
            prod = f"Distilled and bottled by {self.applicant_name}"
            if self.applicant_address:
                prod += f", {self.applicant_address}"
        prod_y = 1120
        if prod:
            s.paragraph([(prod, _font(t.body, 17))], x=140, width=720, gap=6,
                        fill=t.faint, y=prod_y, justify=False)
        if self.label_origin_text:
            s.caps_fit(self.label_origin_text, t.body, 18, gap=6, spacing=3,
                   fill=t.faint, y=prod_y + 60)
        if self.fineprint_extra:
            s.paragraph([(self.fineprint_extra, _font(t.body, 15))], x=120, width=760,
                        gap=6, fill=t.faint, y=prod_y + 110, justify=False)

        if self.single_image and self.warning_mode != "missing":
            self._warning_onto(s, top=1300)
        return s.img

    _BLURB: ClassVar[dict[str, str]] = {
        "wine": "Grown on south-facing slopes and aged in French oak, this wine "
                "shows dark fruit and a long, savoury finish. Unfined. "
                "Enjoy responsibly.",
        "malt": "Brewed in small batches with floor-malted barley and whole-cone "
                "hops, unfiltered and naturally carbonated. Enjoy responsibly.",
        "spirits": "Distilled from a grain mash, matured in charred American oak, "
                   "and bottled without chill filtration. Enjoy responsibly.",
    }

    def _back(self) -> Image.Image:
        t = self._t()
        s = Sheet(1000, 880, t, flat=True)
        s.frame(36, double=False)
        s.y = 70
        s.caps_fit(self.label_brand or self.brand, t.display, 30, gap=26)

        s.paragraph([(self._BLURB[self.commodity], _font(t.body, 17))],
                    x=90, width=820, gap=16, fill=t.faint)

        net = self.label_net or self.net_contents
        if net:
            s.caps(net, _font(t.body, 20), gap=10, spacing=2)
        if self.label_origin_text:
            s.caps(self.label_origin_text, _font(t.body, 17), gap=10, spacing=2,
                   fill=t.faint)
        s.line_center("www.example-distillery.com", _font(BODY_SANS, 15), gap=20,
                      fill=t.faint)

        s.barcode(90, 720, 220, 80)

        if self.warning_mode != "missing":
            if self.warning_style == "sidebar":
                self._warning_sidebar(s)
            else:
                self._warning_onto(s, top=520)
        return s.img

    def _warning_onto(self, s: Sheet, *, top: int) -> None:
        t = self._t()
        runs = warning_runs(t, self.warning_mode, size=15)
        x, width = 300, 620
        if self.warning_style == "boxed":
            box = s.paragraph(runs, x=x + 16, width=width - 32, gap=0, y=top + 14)
            s.d.rectangle([x, top, x + width, box[3] + 12], outline=t.ink, width=1)
        else:
            s.paragraph(runs, x=x, width=width, gap=0, y=top)

    def _warning_sidebar(self, s: Sheet) -> None:
        t = self._t()
        runs = warning_runs(t, self.warning_mode, size=14)
        tmp = Sheet(760, 150, t, flat=True)
        tmp.paragraph(runs, x=10, width=740, gap=0, y=8)
        strip = tmp.img.rotate(90, expand=True)
        s.img.paste(strip, (12, 120))

    def render(self) -> list[dict]:
        os.makedirs(IMAGES_DIR, exist_ok=True)
        out = []
        for role, im in ([("front", self._front())]
                         + ([] if self.single_image else [("back", self._back())])):
            im2, fmt = degrade(im, **self.degrade) if self.degrade else (im, "png")
            rel = f"fixtures/images_realistic/{self.case_id}_{role}.{fmt}"
            im2.convert("RGB").save(os.path.join(REPO_ROOT, rel))
            out.append({"path": rel, "role": role})
        return out

    # -- ground truth: what the label actually says, per check ------------

    @property
    def _fine_print(self) -> str:
        prod = self.producer_line
        if prod is None and self.applicant_name:
            prod = f"Distilled and bottled by {self.applicant_name}"
            if self.applicant_address:
                prod += f", {self.applicant_address}"
        return " ".join(x for x in (prod, self.fineprint_extra) if x)

    def label_facts(self) -> dict:
        """Per-check expectation of *what text the pipeline should read*."""
        from fixtures import numeric_facts, text_fact

        front = 0
        # The back label repeats the brand as a heading (see `_back`), so the
        # brand is printed on both images — pinning index 0 would fail a check
        # that read the back copy, which is a real display line.
        brand_on = [front] if self.single_image else [front, 1]
        printed_abv = self.label_abv_line or self.alcohol_content
        printed_net = self.label_net or self.net_contents
        facts = {
            "brand": text_fact(self.brand, self.label_brand or self.brand,
                               brand_on, self._fine_print),
            "class_type": text_fact(self.class_type, self.class_type, front),
            "producer": text_fact(self.applicant_name, self.applicant_name, front),
            "origin": text_fact(
                self.origin,
                self.origin if (self.label_origin_text and self.origin
                                and self.origin.lower() in self.label_origin_text.lower())
                else None,
                front),
        }
        facts.update(numeric_facts(self.alcohol_content, self.net_contents,
                                   printed_abv, printed_net, front))
        return facts

    def to_record(self) -> dict:
        return {
            "case_id": self.case_id,
            "grade": self.grade,
            "degraded": bool(self.degrade),
            "note": self.note,
            "expect_observed": self.label_facts(),
            "application": {
                "serial_number": self.serial,
                "ttb_id": self.ttb_id,
                "brand_name": self.brand,
                "class_type": self.class_type,
                "commodity": self.commodity,
                "alcohol_content": self.alcohol_content,
                "net_contents": self.net_contents,
                "applicant_name": self.applicant_name,
                "applicant_address": self.applicant_address,
                "origin": self.origin,
                "images": self.render(),
            },
            "expect": self.expect,
        }


# --------------------------------------------------------------------------
# the corpus
# --------------------------------------------------------------------------

_PASS_WARN = {"warn_present": "PASS", "warn_text": "PASS",
              "warn_case": "PASS", "warn_bold": "PASS"}  # bold header -> W-4 auto-confirms
_ALL_PASS = {
    "brand": "PASS", "class_type": "PASS", "abv": "PASS", "proof": "PASS",
    "net_contents": "PASS", "producer": "PASS", "origin": "NOT_DECLARED", **_PASS_WARN,
}


def _cases() -> list[RCase]:
    C: list[RCase] = []

    C.append(RCase(
        case_id="r01_whiskey_clean", grade="exact", commodity="spirits",
        theme="whiskey", serial="200001", ttb_id="24RIC01000001",
        brand="OLD TOM DISTILLERY",
        class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="45% Alc./Vol.", net_contents="750 mL",
        applicant_name="Old Tom Distillery, LLC", applicant_address="Bardstown, KY",
        origin=None, label_abv_line="45% ALC./VOL. (90 PROOF)",
        expect=dict(_ALL_PASS),
        note="Copperplate display, cream gradient, framed, medallion.",
    ))

    C.append(RCase(
        case_id="r02_wine_boxed", grade="exact", commodity="wine",
        theme="wine", serial="200002", ttb_id="24RIC01000002",
        brand="MAISON DUBOIS", class_type="Bordeaux Superieur",
        alcohol_content="13.5% Alc./Vol.", net_contents="750 mL",
        applicant_name="Dubois Imports", applicant_address="New York, NY",
        origin="France", label_origin_text="Product of France",
        warning_style="boxed",
        expect={**_ALL_PASS, "proof": "MISSING", "origin": "PASS"},
        note="Baskerville, burgundy accents, warning ruled into a box.",
    ))

    C.append(RCase(
        case_id="r03_gin_single", grade="exact", commodity="spirits",
        theme="gin", serial="200003", ttb_id="24RIC01000003",
        brand="NORTH PIER", class_type="London Dry Gin",
        alcohol_content="47% Alc./Vol.", net_contents="700 mL",
        applicant_name="North Pier Distilling Co.", applicant_address="Astoria, OR",
        origin=None, single_image=True,
        label_abv_line="47% ALC./VOL. (94 PROOF)",
        expect=dict(_ALL_PASS),
        note="Gill Sans, pale ground, one image.",
    ))

    C.append(RCase(
        case_id="r04_rum_dark", grade="loose", commodity="spirits",
        theme="rum", serial="200004", ttb_id="24RIC01000004",
        brand="RUSTY ANCHOR", class_type="Aged Caribbean Rum",
        alcohol_content="40% Alc./Vol.", net_contents="750 mL",
        applicant_name="Rusty Anchor Spirits", applicant_address="Key West, FL",
        origin=None, label_abv_line="40% ALC./VOL. (80 PROOF)",
        warning_style="boxed", expect=dict(_ALL_PASS),
        note="Light-on-dark: OCR contrast is inverted; autocontrast should cope.",
    ))

    C.append(RCase(
        case_id="r05_brand_decoy", grade="exact", commodity="spirits",
        theme="whiskey", serial="200005", ttb_id="24RIC01000005",
        brand="OLD TOM DISTILLERY", class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="45% Alc./Vol.", net_contents="750 mL",
        applicant_name="Ironwood Spirits Group", applicant_address="Louisville, KY",
        origin=None, label_brand="IRONWOOD RESERVE",
        label_abv_line="45% ALC./VOL. (90 PROOF)",
        producer_line="Produced by Ironwood Spirits Group under license from "
                      "Old Tom Distillery, Bardstown, Kentucky",
        expect={**_ALL_PASS, "brand": "FAIL", "producer": "PASS"},
        note="Prominent brand is IRONWOOD RESERVE; declared brand only in the "
             "licensing line (the 3.2 pitfall, realistically styled).",
    ))

    C.append(RCase(
        case_id="r06_abv_mismatch", grade="exact", commodity="spirits",
        theme="whiskey", serial="200006", ttb_id="24RIC01000006",
        brand="OLD TOM DISTILLERY", class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="45% Alc./Vol.", net_contents="750 mL",
        applicant_name="Old Tom Distillery, LLC", applicant_address="Bardstown, KY",
        origin=None, label_abv_line="43% ALC./VOL. (86 PROOF)",
        expect={**_ALL_PASS, "abv": "FAIL"},
        note="Label under-states declared ABV by two points.",
    ))

    C.append(RCase(
        case_id="r07_proof_bad", grade="exact", commodity="spirits",
        theme="whiskey", serial="200007", ttb_id="24RIC01000007",
        brand="OLD TOM DISTILLERY", class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="45% Alc./Vol.", net_contents="750 mL",
        applicant_name="Old Tom Distillery, LLC", applicant_address="Bardstown, KY",
        origin=None, label_abv_line="45% ALC./VOL. (100 PROOF)",
        expect={**_ALL_PASS, "proof": "FAIL"},
        note="90 proof would match 45%; label says 100.",
    ))

    C.append(RCase(
        case_id="r08_net_mismatch", grade="exact", commodity="wine",
        theme="wine", serial="200008", ttb_id="24RIC01000008",
        brand="STONEBRIDGE CELLARS", class_type="California Chardonnay",
        alcohol_content="13% Alc./Vol.", net_contents="750 mL",
        applicant_name="Stonebridge Cellars", applicant_address="Napa, CA",
        origin=None, label_net="375 mL",
        expect={**_ALL_PASS, "proof": "MISSING", "net_contents": "FAIL"},
        note="Half bottle printed against a 750 mL application.",
    ))

    C.append(RCase(
        case_id="r09_warn_reworded", grade="exact", commodity="spirits",
        theme="whiskey", serial="200009", ttb_id="24RIC01000009",
        brand="OLD TOM DISTILLERY", class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="45% Alc./Vol.", net_contents="750 mL",
        applicant_name="Old Tom Distillery, LLC", applicant_address="Bardstown, KY",
        origin=None, label_abv_line="45% ALC./VOL. (90 PROOF)",
        warning_mode="reworded", warning_style="boxed",
        expect={**_ALL_PASS, "warn_text": "FAIL"},
        note="'operate machinery' replaced with 'operate a boat'.",
    ))

    C.append(RCase(
        case_id="r10_warn_titlecase", grade="exact", commodity="spirits",
        theme="whiskey", serial="200010", ttb_id="24RIC01000010",
        brand="OLD TOM DISTILLERY", class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="45% Alc./Vol.", net_contents="750 mL",
        applicant_name="Old Tom Distillery, LLC", applicant_address="Bardstown, KY",
        origin=None, label_abv_line="45% ALC./VOL. (90 PROOF)",
        warning_mode="titlecase",
        # title-case header is mixed-case, so W-4's caps-vs-caps signal is gone
        # and it can't auto-confirm -> REVIEW (W-3 is the check that FAILs it).
        expect={**_ALL_PASS, "warn_case": "FAIL", "warn_bold": "REVIEW"},
        note="'Government Warning:' in title case.",
    ))

    C.append(RCase(
        case_id="r11_whiskey_photo", grade="loose", commodity="spirits",
        theme="whiskey", serial="200011", ttb_id="24RIC01000011",
        brand="OLD TOM DISTILLERY", class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="45% Alc./Vol.", net_contents="750 mL",
        applicant_name="Old Tom Distillery, LLC", applicant_address="Bardstown, KY",
        origin=None, label_abv_line="45% ALC./VOL. (90 PROOF)",
        degrade={"rotate": 2.4, "blur": 0.7, "vignette": 0.28, "jpeg": 72},
        expect=dict(_ALL_PASS),
        note="r01 shot as a photo. Should still read; a clean field slipping to "
             "REVIEW is tolerated, PASS on a defect is not.",
    ))

    C.append(RCase(
        case_id="r12_lowlight", grade="loose", commodity="spirits",
        theme="rum", serial="200012", ttb_id="24RIC01000012",
        brand="RUSTY ANCHOR", class_type="Aged Caribbean Rum",
        alcohol_content="40% Alc./Vol.", net_contents="750 mL",
        applicant_name="Rusty Anchor Spirits", applicant_address="Key West, FL",
        origin=None, label_abv_line="40% ALC./VOL. (80 PROOF)",
        warning_style="boxed",
        degrade={"rotate": -1.6, "blur": 1.1, "vignette": 0.5, "jpeg": 55},
        expect=dict(_ALL_PASS),
        note="Dark theme + low light. Fields may go UNREADABLE/REVIEW; nothing "
             "unverified may read PASS.",
    ))

    C.append(RCase(
        case_id="r13_warn_sidebar", grade="loose", commodity="spirits",
        theme="whiskey", serial="200013", ttb_id="24RIC01000013",
        brand="OLD TOM DISTILLERY", class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="45% Alc./Vol.", net_contents="750 mL",
        applicant_name="Old Tom Distillery, LLC", applicant_address="Bardstown, KY",
        origin=None, label_abv_line="45% ALC./VOL. (90 PROOF)",
        warning_style="sidebar",
        expect={**_ALL_PASS, "warn_present": "UNREADABLE", "warn_text": "UNREADABLE",
                "warn_case": "UNREADABLE", "warn_bold": "UNREADABLE"},
        note="Warning set vertically on a side panel. No deskew yet, so the "
             "pipeline should fail to locate it -> UNREADABLE, never a silent "
             "pass. Documents the Phase 1 preprocessing gap.",
    ))

    C.append(RCase(
        case_id="r14_wine_angle", grade="loose", commodity="wine",
        theme="wine", serial="200014", ttb_id="24RIC01000014",
        brand="MAISON DUBOIS", class_type="Bordeaux Superieur",
        alcohol_content="13.5% Alc./Vol.", net_contents="750 mL",
        applicant_name="Dubois Imports", applicant_address="New York, NY",
        origin="France", label_origin_text="Product of France",
        warning_style="boxed",
        degrade={"perspective": 0.12, "rotate": 1.2, "vignette": 0.22, "jpeg": 78},
        expect={**_ALL_PASS, "proof": "MISSING", "origin": "PASS"},
        note="Shot at an angle. Keystoned text; tests location robustness.",
    ))

    # 15 — a real defect (ABV mismatch) on a degraded photo: must still not PASS
    C.append(RCase(
        case_id="r15_abv_mismatch_photo", grade="loose", commodity="spirits",
        theme="whiskey", serial="200015", ttb_id="24RIC01000015",
        brand="OLD TOM DISTILLERY", class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="45% Alc./Vol.", net_contents="750 mL",
        applicant_name="Old Tom Distillery, LLC", applicant_address="Bardstown, KY",
        origin=None, label_abv_line="41% ALC./VOL. (82 PROOF)",
        degrade={"rotate": 1.8, "blur": 0.6, "vignette": 0.3, "jpeg": 70},
        expect={**_ALL_PASS, "abv": "FAIL"},
        note="Declared 45%, label 41%, shot as a photo. The mismatch must survive "
             "the degradation — FAIL (or at worst REVIEW/UNREADABLE), never PASS.",
    ))

    # 16 — reworded warning on a lightly degraded photo: must still not PASS
    C.append(RCase(
        case_id="r16_warn_reworded_photo", grade="loose", commodity="spirits",
        theme="whiskey", serial="200016", ttb_id="24RIC01000016",
        brand="OLD TOM DISTILLERY", class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="45% Alc./Vol.", net_contents="750 mL",
        applicant_name="Old Tom Distillery, LLC", applicant_address="Bardstown, KY",
        origin=None, label_abv_line="45% ALC./VOL. (90 PROOF)",
        warning_mode="reworded", warning_style="boxed",
        degrade={"rotate": -1.0, "blur": 0.5, "vignette": 0.2, "jpeg": 76},
        expect={**_ALL_PASS, "warn_text": "FAIL"},
        note="'operate a boat' rewording on a mild photo. warn_text must not PASS.",
    ))

    return C


def _report_audit(problems: list[str]) -> None:
    """A corpus with an illegible field is a broken corpus — say so, loudly."""
    if not problems:
        print("corpus audit: every printed field is legible on its own image")
        return
    print(f"corpus audit FAILED ({len(problems)} problem(s)):")
    for p in problems:
        print("  !! " + p)
    raise SystemExit(1)


def main() -> None:
    os.makedirs(IMAGES_DIR, exist_ok=True)
    records = [c.to_record() for c in _cases()]
    problems = audit_corpus(records)

    with open(CASES_JSON, "w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=2)
        fh.write("\n")
    grades: dict[str, int] = {}
    for r in records:
        grades[r["grade"]] = grades.get(r["grade"], 0) + 1
    print(f"wrote {len(records)} realistic cases {grades} -> "
          f"{os.path.relpath(CASES_JSON, REPO_ROOT)}")
    _report_audit(problems)


if __name__ == "__main__":
    main()
