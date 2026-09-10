"""Render the synthetic label corpus + ground truth.

Run:  python -m fixtures.generate

Produces `fixtures/images/*.png` and `fixtures/cases.json`. Deterministic — no
randomness — so ground truth is exact and the corpus is diffable in git.

Corpus shape (design 2.6):
  * clean set     — beer / wine / spirits, front+back pairs, everything matches
  * mutation set  — one deliberate defect each, every one mapped to a rule
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

from fixtures import CASES_JSON, IMAGES_DIR, REPO_ROOT, audit_corpus
from ttbverify.warning import REFERENCE_WARNING

W, H = 1000, 1360
MARGIN = 80
BLACK, WHITE = (0, 0, 0), (255, 255, 255)

_FONT_DIRS = [
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/liberation",
    "/Library/Fonts",
]
_REGULAR = ["arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf", "Arial.ttf"]
_BOLD = ["arialbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "Arial Bold.ttf"]


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for name in (_BOLD if bold else _REGULAR):
        for d in _FONT_DIRS:
            path = os.path.join(d, name)
            if os.path.isfile(path):
                return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


# --------------------------------------------------------------------------
# tiny layout helpers
# --------------------------------------------------------------------------

class Sheet:
    def __init__(self, height: int = H):
        self.img = Image.new("RGB", (W, height), WHITE)
        self.draw = ImageDraw.Draw(self.img)
        self.y = MARGIN

    def centered(self, text: str, font: ImageFont.FreeTypeFont, gap: int = 24,
                 bold: bool = False) -> None:
        """Centred, shrunk to fit if it would run past the margins.

        Text drawn off the edge of a label is unreadable to OCR and to a person;
        the generator must never emit it.
        """
        size = font.size
        while size > 10:
            bbox = self.draw.textbbox((0, 0), text, font=font)
            if (bbox[2] - bbox[0]) <= W - 2 * MARGIN:
                break
            size -= 2
            font = _font(size, bold=bold)
        bbox = self.draw.textbbox((0, 0), text, font=font)
        x = max(MARGIN, (W - (bbox[2] - bbox[0])) // 2 - bbox[0])
        self.draw.text((x, self.y), text, font=font, fill=BLACK)
        self.y += (bbox[3] - bbox[1]) + gap

    def left(self, text: str, font: ImageFont.FreeTypeFont, gap: int = 16,
             x: int = MARGIN) -> None:
        bbox = self.draw.textbbox((0, 0), text, font=font)
        self.draw.text((x, self.y), text, font=font, fill=BLACK)
        self.y += (bbox[3] - bbox[1]) + gap

    def wrapped(self, runs: list[tuple[str, ImageFont.FreeTypeFont]], gap: int = 10,
                x: int = MARGIN, width: int = W - 2 * MARGIN) -> None:
        """Flow a sequence of (text, font) runs as left-aligned wrapped lines.

        Each word is placed at an explicit x so the rendered spacing matches the
        layout calculation exactly — real gaps between words, which is what OCR
        needs to tokenize the line.
        """
        line: list[tuple[str, ImageFont.FreeTypeFont, float]] = []
        cursor_x = x

        def flush():
            nonlocal line, cursor_x
            max_h = max((self.draw.textbbox((0, 0), t, font=f)[3] for t, f, _ in line),
                        default=0)
            for t, f, lx in line:
                self.draw.text((lx, self.y), t, font=f, fill=BLACK)
            self.y += max_h + gap
            line = []
            cursor_x = x

        for text, fnt in runs:
            space_w = self.draw.textlength(" ", font=fnt)
            for word in text.split(" "):
                if not word:
                    continue
                ww = self.draw.textlength(word, font=fnt)
                gap_before = space_w if line else 0
                if line and cursor_x + gap_before + ww > x + width:
                    flush()
                    gap_before = 0
                cursor_x += gap_before
                line.append((word, fnt, cursor_x))
                cursor_x += ww
        if line:
            flush()

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.img.save(path)


def _warning_runs(mode: str) -> list[tuple[str, ImageFont.FreeTypeFont]]:
    """Return (text, font) runs for the health warning per mutation mode."""
    body = REFERENCE_WARNING.split(": ", 1)[1]  # everything after "GOVERNMENT WARNING: "
    header_font = _font(21, bold=(mode != "nonbold"))
    body_font = _font(21)

    if mode == "titlecase":
        header = "Government Warning:"
    else:
        header = "GOVERNMENT WARNING:"

    if mode == "reworded":
        body = body.replace("operate machinery", "use heavy equipment")
    elif mode == "charnoise":
        body = body.replace("machinery", "machinory")  # simulates an OCR misread

    return [(header + " ", header_font), (body, body_font)]


# --------------------------------------------------------------------------
# case model
# --------------------------------------------------------------------------

@dataclass
class Case:
    case_id: str
    description: str
    commodity: str
    serial: str
    ttb_id: str | None
    # declared application values
    brand: str
    class_type: str
    alcohol_content: str | None
    net_contents: str | None
    applicant_name: str | None
    applicant_address: str | None
    origin: str | None
    expect: dict[str, str]
    # what is actually printed (falls back to declared where None)
    label_brand: str | None = None
    label_class_type: str | None = None
    label_abv_text: str | None = None
    label_net_text: str | None = None
    label_producer_line: str | None = None
    label_origin_text: str | None = None
    fineprint_extra: str | None = None
    warning_mode: str = "compliant"   # compliant|titlecase|reworded|charnoise|nonbold|missing
    single_image: bool = False

    # -- rendering --------------------------------------------------------

    def _front(self) -> Sheet:
        s = Sheet()
        s.y = 120
        s.centered(self.label_brand or self.brand, _font(64, bold=True), gap=30, bold=True)
        s.centered(self.label_class_type or self.class_type, _font(44), gap=60)

        abv = self.label_abv_text
        if abv is None and self.alcohol_content:
            abv = self.alcohol_content
        if abv:
            s.centered(abv, _font(28), gap=18)

        net = self.label_net_text
        if net is None and self.net_contents:
            net = self.net_contents
        if net:
            s.centered(net, _font(28), gap=40)

        if self.label_origin_text:
            s.centered(self.label_origin_text, _font(24), gap=24)

        producer = self.label_producer_line
        if producer is None and self.applicant_name:
            producer = f"Bottled by {self.applicant_name}"
            if self.applicant_address:
                producer += f", {self.applicant_address}"
        if producer:
            s.y = H - 360
            s.wrapped([(producer, _font(18))], gap=8)
        if self.fineprint_extra:
            s.wrapped([(self.fineprint_extra, _font(18))], gap=8)

        if self.single_image and self.warning_mode != "missing":
            s.y = H - 240
            s.wrapped(_warning_runs(self.warning_mode))
        return s

    def _back(self) -> Sheet:
        s = Sheet(height=760)
        s.y = 90
        s.centered(self.label_brand or self.brand, _font(30, bold=True), gap=50, bold=True)
        if self.warning_mode != "missing":
            s.y = 260
            s.wrapped(_warning_runs(self.warning_mode))
        else:
            s.centered("Please enjoy responsibly.", _font(20))
        return s

    def render(self) -> list[dict]:
        images: list[dict] = []
        front_rel = os.path.join("fixtures", "images", f"{self.case_id}_front.png")
        Sheet.save(self._front(), os.path.join(REPO_ROOT, front_rel))
        images.append({"path": front_rel.replace(os.sep, "/"), "role": "front"})
        if not self.single_image:
            back_rel = os.path.join("fixtures", "images", f"{self.case_id}_back.png")
            Sheet.save(self._back(), os.path.join(REPO_ROOT, back_rel))
            images.append({"path": back_rel.replace(os.sep, "/"), "role": "back"})
        return images

    # -- ground truth: what the label actually says, per check ------------

    @property
    def _fine_print(self) -> str:
        producer = self.label_producer_line
        if producer is None and self.applicant_name:
            producer = f"Bottled by {self.applicant_name}"
            if self.applicant_address:
                producer += f", {self.applicant_address}"
        return " ".join(x for x in (producer, self.fineprint_extra) if x)

    def label_facts(self) -> dict:
        """Per-check expectation of *what text the pipeline should read*.

        Verdicts alone can be right for the wrong reason; this pins the reading.
        """
        from fixtures import numeric_facts, text_fact

        front = 0
        printed_abv = self.label_abv_text or self.alcohol_content
        printed_net = self.label_net_text or self.net_contents
        facts = {
            "brand": text_fact(self.brand, self.label_brand or self.brand,
                               front, self._fine_print),
            "class_type": text_fact(self.class_type,
                                    self.label_class_type or self.class_type, front),
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
            "description": self.description,
            "degraded": False,
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
            "expect_observed": self.label_facts(),
        }


# --------------------------------------------------------------------------
# the corpus
# --------------------------------------------------------------------------

_ALL_PASS_WARN = {
    "warn_present": "PASS", "warn_text": "PASS",
    "warn_case": "PASS", "warn_bold": "PASS",   # bold header -> W-4 auto-confirms
}


def _cases() -> list[Case]:
    cases: list[Case] = []

    # 1. clean spirits -----------------------------------------------------
    cases.append(Case(
        case_id="clean_spirits",
        description="Clean distilled-spirits label, front+back, everything matches.",
        commodity="spirits", serial="100001", ttb_id="24001001000001",
        brand="OLD TOM DISTILLERY",
        class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="45% Alc./Vol.", net_contents="750 mL",
        applicant_name="Old Tom Distillery, LLC", applicant_address="Bardstown, KY",
        origin=None,
        label_abv_text="45% Alc./Vol. (90 Proof)",
        expect={
            "brand": "PASS", "class_type": "PASS", "abv": "PASS", "proof": "PASS",
            "net_contents": "PASS", "producer": "PASS", "origin": "NOT_DECLARED",
            **_ALL_PASS_WARN,
        },
    ))

    # 2. clean imported wine --------------------------------------------
    cases.append(Case(
        case_id="clean_wine",
        description="Clean imported-wine label with a declared country of origin.",
        commodity="wine", serial="100002", ttb_id="24001001000002",
        brand="MAISON DUBOIS", class_type="Bordeaux Red Wine",
        alcohol_content="13.5% Alc./Vol.", net_contents="750 mL",
        applicant_name="Maison Dubois Imports", applicant_address="New York, NY",
        origin="France",
        label_origin_text="Product of France",
        expect={
            "brand": "PASS", "class_type": "PASS", "abv": "PASS",
            "net_contents": "PASS", "producer": "PASS", "origin": "PASS",
            **_ALL_PASS_WARN,
        },
    ))

    # 3. clean beer, single image ---------------------------------------
    cases.append(Case(
        case_id="clean_beer",
        description="Clean malt-beverage label, single image, warning on the front.",
        commodity="malt", serial="100003", ttb_id="24001001000003",
        brand="IRON RIVER BREWING", class_type="India Pale Ale",
        alcohol_content="6.2% Alc./Vol.", net_contents="12 fl oz",
        applicant_name="Iron River Brewing Co.", applicant_address="Duluth, MN",
        origin=None, single_image=True,
        expect={
            "brand": "PASS", "class_type": "PASS", "abv": "PASS",
            "net_contents": "PASS", "producer": "PASS", "origin": "NOT_DECLARED",
            **_ALL_PASS_WARN,
        },
    ))

    # 4. undeclared optional fields (design 3.6) -----------------------
    cases.append(Case(
        case_id="undeclared_optionals",
        description="ABV and net contents not declared on the application; printed "
                    "on the label. Must be NOT_DECLARED, never a mismatch.",
        commodity="spirits", serial="100004", ttb_id="24001001000004",
        brand="OLD TOM DISTILLERY",
        class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content=None, net_contents=None,
        applicant_name="Old Tom Distillery, LLC", applicant_address="Bardstown, KY",
        origin=None,
        label_abv_text="45% Alc./Vol. (90 Proof)", label_net_text="750 mL",
        expect={
            "brand": "PASS", "class_type": "PASS", "abv": "NOT_DECLARED",
            "proof": "PASS", "net_contents": "NOT_DECLARED", "producer": "PASS",
            "origin": "NOT_DECLARED", **_ALL_PASS_WARN,
        },
    ))

    # 5. brand case variance — STONE'S THROW (must PASS) --------------
    cases.append(Case(
        case_id="brand_case_variance",
        description="Application 'Stone's Throw', label 'STONE'S THROW'. Case-only "
                    "difference — must PASS at the case-folded tier.",
        commodity="spirits", serial="100005", ttb_id="24001001000005",
        brand="Stone's Throw", class_type="Small Batch Gin",
        alcohol_content="44% Alc./Vol.", net_contents="750 mL",
        applicant_name="Stone's Throw Spirits", applicant_address="Portland, OR",
        origin=None,
        label_brand="STONE'S THROW",
        label_abv_text="44% Alc./Vol. (88 Proof)",
        expect={
            "brand": "PASS", "class_type": "PASS", "abv": "PASS", "proof": "PASS",
            "net_contents": "PASS", "producer": "PASS", "origin": "NOT_DECLARED",
            **_ALL_PASS_WARN,
        },
    ))

    # 6. brand mismatch + fine-print decoy (design 3.2) --------------
    cases.append(Case(
        case_id="brand_mismatch",
        description="Declared brand appears only in the fine-print bottler line; the "
                    "prominent brand on the label is different. Must FAIL — the "
                    "prominence filter must not accept the fine-print occurrence.",
        commodity="spirits", serial="100006", ttb_id="24001001000006",
        brand="OLD TOM DISTILLERY", class_type="Spiced Rum",
        alcohol_content="40% Alc./Vol.", net_contents="750 mL",
        applicant_name="Rusty Anchor Spirits", applicant_address="Key West, FL",
        origin=None,
        label_brand="RUSTY ANCHOR RUM",
        label_abv_text="40% Alc./Vol. (80 Proof)",
        label_producer_line="Distilled by Old Tom Distillery, Bardstown, KY, and "
                            "bottled for Rusty Anchor Spirits, Key West, FL",
        expect={
            "brand": "FAIL", "class_type": "PASS", "abv": "PASS", "proof": "PASS",
            "net_contents": "PASS", "producer": "PASS", "origin": "NOT_DECLARED",
            **_ALL_PASS_WARN,
        },
    ))

    # 7. ABV value mismatch ------------------------------------------
    cases.append(Case(
        case_id="abv_mismatch",
        description="Declared 45% ABV, label prints 40% (internally consistent with "
                    "its 80 proof). ABV check must FAIL.",
        commodity="spirits", serial="100007", ttb_id="24001001000007",
        brand="OLD TOM DISTILLERY",
        class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="45% Alc./Vol.", net_contents="750 mL",
        applicant_name="Old Tom Distillery, LLC", applicant_address="Bardstown, KY",
        origin=None,
        label_abv_text="40% Alc./Vol. (80 Proof)",
        expect={
            "brand": "PASS", "class_type": "PASS", "abv": "FAIL", "proof": "PASS",
            "net_contents": "PASS", "producer": "PASS", "origin": "NOT_DECLARED",
            **_ALL_PASS_WARN,
        },
    ))

    # 8. proof inconsistent with ABV -------------------------------
    cases.append(Case(
        case_id="abv_proof_inconsistent",
        description="Label prints 45% Alc./Vol. but 100 proof (should be 90). "
                    "ABV matches the application; the proof check must FAIL.",
        commodity="spirits", serial="100008", ttb_id="24001001000008",
        brand="OLD TOM DISTILLERY",
        class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="45% Alc./Vol.", net_contents="750 mL",
        applicant_name="Old Tom Distillery, LLC", applicant_address="Bardstown, KY",
        origin=None,
        label_abv_text="45% Alc./Vol. (100 Proof)",
        expect={
            "brand": "PASS", "class_type": "PASS", "abv": "PASS", "proof": "FAIL",
            "net_contents": "PASS", "producer": "PASS", "origin": "NOT_DECLARED",
            **_ALL_PASS_WARN,
        },
    ))

    # 9. ABV near miss -> REVIEW -----------------------------------
    cases.append(Case(
        case_id="abv_near_miss",
        description="Declared 45%, label prints 45.3%. Within the near-miss band — "
                    "routes to REVIEW, not FAIL.",
        commodity="spirits", serial="100009", ttb_id="24001001000009",
        brand="OLD TOM DISTILLERY",
        class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="45% Alc./Vol.", net_contents="750 mL",
        applicant_name="Old Tom Distillery, LLC", applicant_address="Bardstown, KY",
        origin=None,
        label_abv_text="45.3% Alc./Vol. (90 Proof)",
        expect={
            "brand": "PASS", "class_type": "PASS", "abv": "REVIEW", "proof": "PASS",
            "net_contents": "PASS", "producer": "PASS", "origin": "NOT_DECLARED",
            **_ALL_PASS_WARN,
        },
    ))

    # 10. net contents unit variance (must PASS) ------------------
    cases.append(Case(
        case_id="net_unit_variance",
        description="Declared '750 mL', label prints '0.75 L'. Same volume — must PASS.",
        commodity="wine", serial="100010", ttb_id="24001001000010",
        brand="STONEBRIDGE CELLARS", class_type="California Chardonnay",
        alcohol_content="13.0% Alc./Vol.", net_contents="750 mL",
        applicant_name="Stonebridge Cellars", applicant_address="Napa, CA",
        origin=None,
        label_net_text="0.75 L",
        expect={
            "brand": "PASS", "class_type": "PASS", "abv": "PASS",
            "net_contents": "PASS", "producer": "PASS", "origin": "NOT_DECLARED",
            **_ALL_PASS_WARN,
        },
    ))

    # 11. net contents value mismatch ---------------------------
    cases.append(Case(
        case_id="net_mismatch",
        description="Declared '750 mL', label prints '500 mL'. Must FAIL.",
        commodity="wine", serial="100011", ttb_id="24001001000011",
        brand="STONEBRIDGE CELLARS", class_type="California Chardonnay",
        alcohol_content="13.0% Alc./Vol.", net_contents="750 mL",
        applicant_name="Stonebridge Cellars", applicant_address="Napa, CA",
        origin=None,
        label_net_text="500 mL",
        expect={
            "brand": "PASS", "class_type": "PASS", "abv": "PASS",
            "net_contents": "FAIL", "producer": "PASS", "origin": "NOT_DECLARED",
            **_ALL_PASS_WARN,
        },
    ))

    # 12. warning missing --------------------------------------
    cases.append(Case(
        case_id="warning_missing",
        description="No health warning statement on any image. W-1 must FAIL; the "
                    "dependent warning checks must not PASS.",
        commodity="spirits", serial="100012", ttb_id="24001001000012",
        brand="OLD TOM DISTILLERY",
        class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="45% Alc./Vol.", net_contents="750 mL",
        applicant_name="Old Tom Distillery, LLC", applicant_address="Bardstown, KY",
        origin=None, warning_mode="missing",
        label_abv_text="45% Alc./Vol. (90 Proof)",
        expect={
            "brand": "PASS", "class_type": "PASS", "abv": "PASS", "proof": "PASS",
            "net_contents": "PASS", "producer": "PASS", "origin": "NOT_DECLARED",
            "warn_present": "FAIL", "warn_text": "FAIL",
            "warn_case": "FAIL", "warn_bold": "FAIL",
        },
    ))

    # 13. warning reworded -----------------------------------
    cases.append(Case(
        case_id="warning_reworded",
        description="Warning body reworded ('operate machinery' -> 'use heavy "
                    "equipment'). W-2 must FAIL with a word diff.",
        commodity="spirits", serial="100013", ttb_id="24001001000013",
        brand="OLD TOM DISTILLERY",
        class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="45% Alc./Vol.", net_contents="750 mL",
        applicant_name="Old Tom Distillery, LLC", applicant_address="Bardstown, KY",
        origin=None, warning_mode="reworded",
        label_abv_text="45% Alc./Vol. (90 Proof)",
        expect={
            "brand": "PASS", "class_type": "PASS", "abv": "PASS", "proof": "PASS",
            "net_contents": "PASS", "producer": "PASS", "origin": "NOT_DECLARED",
            "warn_present": "PASS", "warn_text": "FAIL",
            "warn_case": "PASS", "warn_bold": "PASS",
        },
    ))

    # 14. warning title-case (Jenny's rejection) -----------
    cases.append(Case(
        case_id="warning_titlecase",
        description="'Government Warning:' in title case instead of all caps. "
                    "W-3 must FAIL; wording itself is unchanged.",
        commodity="spirits", serial="100014", ttb_id="24001001000014",
        brand="OLD TOM DISTILLERY",
        class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="45% Alc./Vol.", net_contents="750 mL",
        applicant_name="Old Tom Distillery, LLC", applicant_address="Bardstown, KY",
        origin=None, warning_mode="titlecase",
        label_abv_text="45% Alc./Vol. (90 Proof)",
        expect={
            "brand": "PASS", "class_type": "PASS", "abv": "PASS", "proof": "PASS",
            "net_contents": "PASS", "producer": "PASS", "origin": "NOT_DECLARED",
            "warn_present": "PASS", "warn_text": "PASS",
            "warn_case": "FAIL", "warn_bold": "REVIEW",
        },
    ))

    # 15. warning char noise -> REVIEW (design 3.3) --------
    cases.append(Case(
        case_id="warning_charnoise",
        description="One character changed in the warning body ('machinery' -> "
                    "'machinory'), simulating an OCR misread. Must land on REVIEW, "
                    "never a silent PASS and never a hard FAIL.",
        commodity="spirits", serial="100015", ttb_id="24001001000015",
        brand="OLD TOM DISTILLERY",
        class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="45% Alc./Vol.", net_contents="750 mL",
        applicant_name="Old Tom Distillery, LLC", applicant_address="Bardstown, KY",
        origin=None, warning_mode="charnoise",
        label_abv_text="45% Alc./Vol. (90 Proof)",
        expect={
            "brand": "PASS", "class_type": "PASS", "abv": "PASS", "proof": "PASS",
            "net_contents": "PASS", "producer": "PASS", "origin": "NOT_DECLARED",
            "warn_present": "PASS", "warn_text": "REVIEW",
            "warn_case": "PASS", "warn_bold": "PASS",
        },
    ))

    # 16. warning non-bold header -------------------------
    cases.append(Case(
        case_id="warning_nonbold",
        description="'GOVERNMENT WARNING:' rendered in a regular (non-bold) weight. "
                    "W-4 must NOT auto-confirm it — falls to REVIEW — while W-2/W-3 "
                    "still PASS.",
        commodity="spirits", serial="100016", ttb_id="24001001000016",
        brand="OLD TOM DISTILLERY",
        class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="45% Alc./Vol.", net_contents="750 mL",
        applicant_name="Old Tom Distillery, LLC", applicant_address="Bardstown, KY",
        origin=None, warning_mode="nonbold",
        label_abv_text="45% Alc./Vol. (90 Proof)",
        expect={
            "brand": "PASS", "class_type": "PASS", "abv": "PASS", "proof": "PASS",
            "net_contents": "PASS", "producer": "PASS", "origin": "NOT_DECLARED",
            "warn_present": "PASS", "warn_text": "PASS",
            "warn_case": "PASS", "warn_bold": "REVIEW",
        },
    ))

    # 17. two independent REVIEW items (ABV near-miss + non-bold header) ---
    cases.append(Case(
        case_id="abv_nearmiss_nonbold",
        description="ABV near-miss and a non-bold warning header on the same label "
                    "— two independent REVIEW items for the review-flow tests.",
        commodity="spirits", serial="100017", ttb_id="24001001000017",
        brand="OLD TOM DISTILLERY",
        class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="45% Alc./Vol.", net_contents="750 mL",
        applicant_name="Old Tom Distillery, LLC", applicant_address="Bardstown, KY",
        origin=None, warning_mode="nonbold",
        label_abv_text="45.3% Alc./Vol. (90 Proof)",
        expect={
            "brand": "PASS", "class_type": "PASS", "abv": "REVIEW", "proof": "PASS",
            "net_contents": "PASS", "producer": "PASS", "origin": "NOT_DECLARED",
            "warn_present": "PASS", "warn_text": "PASS",
            "warn_case": "PASS", "warn_bold": "REVIEW",
        },
    ))

    return cases


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
    print(f"wrote {len(records)} cases -> {os.path.relpath(CASES_JSON, REPO_ROOT)}")
    print(f"images -> {os.path.relpath(IMAGES_DIR, REPO_ROOT)}/")
    _report_audit(problems)


if __name__ == "__main__":
    main()
