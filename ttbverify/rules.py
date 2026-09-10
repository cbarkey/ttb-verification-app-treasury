"""The rules engine: declared application values vs. what OCR read off the label.

Pure comparison over `LabelApplication` + `list[OcrPage]`. No I/O, no OCR calls
here — that keeps it fast (design 6.1: ~20 ms) and trivially testable.

Two design points enforced here:

  * **Prominence + tiering (design 3.2).** Brand and class/type are display text.
    Matching them against *any* text on the label produces false approvals — a
    fine-print bottler statement can contain the declared brand while the real,
    prominent brand is something else. So genuine fine print is dropped by
    height, and the remaining lines are tiered by *position*: the first line
    block is the brand, everything below it is the class/type tier. The brand
    check only ever sees the brand block. Producer/origin are *expected* in fine
    print and are matched against all text.

  * **Governing principle.** A field that couldn't be read is UNREADABLE; a field
    with no declared value is NOT_DECLARED. Neither is ever a silent PASS.
"""

from __future__ import annotations

import re

from dataclasses import dataclass

from ttbverify.models import (
    BoundingBox,
    CheckResult,
    LabelApplication,
    Outcome,
)
from ttbverify.normalize import MatchResult, compare
from ttbverify.ocr import MIN_WORD_CONF, OcrPage, OcrWord
from ttbverify.parsers import parse_abv, parse_net_contents

# Prominence + tiering (design 3.2).
#
# Brand and class/type are display text; a fine-print bottler line that happens
# to contain the declared brand must not be accepted as the brand. Earlier
# versions thresholded on OCR bounding-box height as a proxy for type size — but
# that is font-fragile (Copperplate-style faces render short caps, so a big
# display brand can measure a *smaller* box than a smaller-point class line).
#
# Instead we tier by *position*: drop genuine fine print by height, then in
# reading order the first surviving line block is the brand and everything below
# it is the class/type tier. The brand check only ever sees the brand block, so
# it structurally cannot match (or point at) the class line, and a fine-print
# occurrence of the declared brand still can't clear the fine-print cutoff.

# A line shorter than this fraction of the page's tallest line is fine print
# (a bottler statement, the warning) and never counts as brand or class/type.
_FINE_PRINT_FRACTION = 0.45

# ABV numeric bands (design 2.3, 3.5): exact by default, near-miss to REVIEW.
ABV_EXACT_EPS = 0.05
ABV_NEAR_MISS = 0.5

# Net contents: compared as millilitres, with a small relative tolerance.
NET_EXACT_REL = 0.01
NET_NEAR_REL = 0.05

_NUM = r"\d+(?:[.,]\d+)?"
_ABV_TOKEN = re.compile(rf"^{_NUM}%$|^{_NUM}%?(?:alc|abv)", re.IGNORECASE)
_PROOF_TOKEN = re.compile(rf"^{_NUM}$|proof", re.IGNORECASE)
_NET_UNIT = re.compile(r"^(ml|cl|l|litre|liter|oz|fl|floz)\.?$", re.IGNORECASE)


# --------------------------------------------------------------------------
# text location helpers
# --------------------------------------------------------------------------

def _iter_lines(words: list[OcrWord]):
    """Yield lists of words grouped by (block, par, line), preserving order."""
    cur_key = None
    bucket: list[OcrWord] = []
    for w in words:
        key = (w.block, w.par, w.line)
        if key != cur_key and bucket:
            yield bucket
            bucket = []
        cur_key = key
        bucket.append(w)
    if bucket:
        yield bucket


def _rank(m: MatchResult) -> tuple[int, float]:
    order = {Outcome.PASS: 3, Outcome.REVIEW: 2, Outcome.FAIL: 1}
    return (order[m.outcome], m.similarity)


@dataclass
class Location:
    match: MatchResult
    box: BoundingBox | None
    page_index: int
    page_role: str | None
    observed: str
    mean_conf: float


def _line_h(line: list[OcrWord]) -> int:
    return max(w.box.height for w in line)


def _prominent_lines(page: OcrPage) -> list[list[OcrWord]]:
    """The page's lines in reading order with genuine fine print dropped."""
    lines = [ln for ln in _iter_lines(page.words) if ln]
    if len(lines) < 2:
        return lines
    cutoff = _FINE_PRINT_FRACTION * max(_line_h(ln) for ln in lines)
    return [ln for ln in lines if _line_h(ln) >= cutoff]


def _tier_groups(page: OcrPage, tier: str, want: int) -> list[list[OcrWord]]:
    """Word groups on `page` to window-search for a display field.

    tier == "brand"   -> the first prominent line; if the declared brand has more
                         words than that line holds it likely wrapped, so also
                         fold in the next line — but only if the two together
                         don't overshoot the declared length (that guards against
                         folding a fanciful-name or class line into the brand).
    tier == "subhead" -> each prominent line *below* the first, on its own.
    """
    plines = _prominent_lines(page)
    if not plines:
        return []
    if tier == "brand":
        block = list(plines[0])
        if (len(plines) > 1 and len(plines[0]) < want
                and len(plines[0]) + len(plines[1]) <= want + 1):
            block += plines[1]
        return [block]
    return [list(ln) for ln in plines[1:]]


def _locate_text(
    pages: list[OcrPage], declared: str, *, tier: str | None
) -> Location | None:
    """Best matching window of consecutive words for `declared`.

    `tier` restricts the search to a display region ("brand" / "subhead"); `None`
    searches all text (producer, origin — expected in fine print). Returns None
    when there is no candidate text at all (→ UNREADABLE upstream).

    On a FAIL for a tiered field the best window is often a stray fragment; the
    box/observed then fall back to the tier's own region so the agent sees the
    text that was actually compared, with the outcome unchanged.
    """
    want = max(1, len(declared.split()))
    best: Location | None = None
    fallback: tuple[int, str | None, BoundingBox, str] | None = None

    for page in pages:
        if not page.words:
            continue
        groups = (list(_iter_lines(page.words)) if tier is None
                  else _tier_groups(page, tier, want))
        if not groups or not any(groups):
            continue
        if tier is not None and fallback is None:
            flat = [w for g in groups for w in g]
            if flat:
                fallback = (page.index, page.role,
                            BoundingBox.enclosing(w.box for w in flat),
                            " ".join(w.text for w in flat))

        for group in groups:
            for start in range(len(group)):
                for length in range(1, min(want + 1, len(group) - start) + 1):
                    window = group[start : start + length]
                    text = " ".join(w.text for w in window)
                    m = compare(declared, text)
                    if best is None or _rank(m) > _rank(best.match):
                        best = Location(
                            match=m,
                            box=BoundingBox.enclosing(w.box for w in window),
                            page_index=page.index, page_role=page.role,
                            observed=text,
                            mean_conf=sum(w.conf for w in window) / len(window),
                        )

    if best is None:
        return None
    if best.match.outcome is Outcome.FAIL and fallback is not None:
        pi, pr, box, text = fallback
        return Location(best.match, box, pi, pr, text, best.mean_conf)
    return best


def _locate_pattern(
    pages: list[OcrPage], token_re: re.Pattern[str]
) -> tuple[BoundingBox | None, int, str | None, str]:
    """Find the first word matching `token_re`; return a box around its whole
    OCR line (block/par/line), which is the natural unit to highlight."""
    for page in pages:
        for w in page.words:
            if not token_re.search(w.text):
                continue
            key = (w.block, w.par, w.line)
            line = [x for x in page.words if (x.block, x.par, x.line) == key]
            return (
                BoundingBox.enclosing(x.box for x in line),
                page.index, page.role,
                " ".join(x.text for x in line),
            )
    return (None, 0, None, "")


def _full_text(pages: list[OcrPage]) -> str:
    return "\n".join(p.text for p in pages)


# --------------------------------------------------------------------------
# individual field checks
# --------------------------------------------------------------------------

def _text_field_check(
    check_id: str,
    label: str,
    declared: str | None,
    pages: list[OcrPage],
    *,
    tier: str | None,
) -> CheckResult:
    if declared is None or not declared.strip():
        return CheckResult(check_id, label, Outcome.NOT_DECLARED,
                           detail="No value declared on the application.")

    loc = _locate_text(pages, declared, tier=tier)
    if loc is None:
        where = "in the display text" if tier is not None else "anywhere on the label"
        return CheckResult(check_id, label, Outcome.UNREADABLE, declared=declared,
                           detail=f"Couldn't read text to compare {where}.")

    if loc.match.outcome is not Outcome.PASS and loc.mean_conf < MIN_WORD_CONF:
        return CheckResult(check_id, label, Outcome.UNREADABLE, declared=declared,
                           observed=loc.observed, box=loc.box,
                           image_index=loc.page_index, image_role=loc.page_role,
                           detail="Matching text was read with low confidence.")

    return CheckResult(
        check_id, label, loc.match.outcome,
        declared=declared, observed=loc.observed, tier=loc.match.tier,
        box=loc.box, image_index=loc.page_index, image_role=loc.page_role,
        detail=loc.match.detail,
        evidence={"similarity": round(loc.match.similarity, 3)},
    )


def _abv_check(app: LabelApplication, pages: list[OcrPage]) -> list[CheckResult]:
    text = _full_text(pages)
    label_reading = parse_abv(text)
    box, pidx, prole, _ = _locate_pattern(pages, _ABV_TOKEN)
    common = dict(image_index=pidx, image_role=prole, box=box)
    checks: list[CheckResult] = []

    # --- alcohol content ---
    if app.alcohol_content is None or not app.alcohol_content.strip():
        checks.append(CheckResult("abv", "Alcohol content", Outcome.NOT_DECLARED,
                                  detail="No alcohol content declared."))
    else:
        declared = parse_abv(app.alcohol_content)
        if declared.abv is None:
            checks.append(CheckResult("abv", "Alcohol content", Outcome.REVIEW,
                                      declared=app.alcohol_content,
                                      detail="Declared alcohol content couldn't be parsed."))
        elif label_reading.abv is None:
            checks.append(CheckResult("abv", "Alcohol content", Outcome.UNREADABLE,
                                      declared=app.alcohol_content, **common,
                                      detail="No alcohol content found on the label."))
        else:
            gap = abs(declared.abv - label_reading.abv)
            if gap <= ABV_EXACT_EPS:
                outcome, detail = Outcome.PASS, f"{label_reading.abv:g}% matches."
            elif gap <= ABV_NEAR_MISS:
                outcome = Outcome.REVIEW
                detail = (f"Declared {declared.abv:g}%, label reads "
                          f"{label_reading.abv:g}% - near miss, needs a human call.")
            else:
                outcome = Outcome.FAIL
                detail = (f"Declared {declared.abv:g}%, label reads "
                          f"{label_reading.abv:g}%.")
            checks.append(CheckResult(
                "abv", "Alcohol content", outcome,
                declared=f"{declared.abv:g}%", observed=f"{label_reading.abv:g}%",
                **common, detail=detail,
                evidence={"declared_abv": declared.abv, "label_abv": label_reading.abv},
            ))

    # --- proof / ABV consistency (only when proof is printed on the label) ---
    if label_reading.proof is not None:
        pbox, ppidx, pprole, _ = _locate_pattern(pages, _PROOF_TOKEN)
        pcommon = dict(image_index=ppidx, image_role=pprole, box=pbox)
        if label_reading.abv is None:
            checks.append(CheckResult("proof", "Proof / ABV consistency", Outcome.REVIEW,
                                      observed=f"{label_reading.proof:g} proof", **pcommon,
                                      detail="Proof printed but ABV not read - can't verify 2x."))
        elif label_reading.proof_consistent:
            checks.append(CheckResult("proof", "Proof / ABV consistency", Outcome.PASS,
                                      observed=f"{label_reading.proof:g} proof", **pcommon,
                                      detail=f"{label_reading.proof:g} proof = 2 x "
                                             f"{label_reading.abv:g}%."))
        else:
            checks.append(CheckResult(
                "proof", "Proof / ABV consistency", Outcome.FAIL,
                observed=f"{label_reading.proof:g} proof", **pcommon,
                detail=(f"{label_reading.proof:g} proof != 2 x {label_reading.abv:g}% "
                        f"(expected {2 * label_reading.abv:g})."),
                evidence={"proof": label_reading.proof, "abv": label_reading.abv},
            ))

    return checks


def _net_contents_check(app: LabelApplication, pages: list[OcrPage]) -> CheckResult:
    if app.net_contents is None or not app.net_contents.strip():
        return CheckResult("net_contents", "Net contents", Outcome.NOT_DECLARED,
                           detail="No net contents declared.")

    declared = parse_net_contents(app.net_contents)
    label = parse_net_contents(_full_text(pages))
    box, pidx, prole, _ = _locate_pattern(pages, _NET_UNIT)
    common = dict(image_index=pidx, image_role=prole, box=box)

    if declared.milliliters is None:
        return CheckResult("net_contents", "Net contents", Outcome.REVIEW,
                           declared=app.net_contents,
                           detail="Declared net contents couldn't be parsed.")
    if label.milliliters is None:
        return CheckResult("net_contents", "Net contents", Outcome.UNREADABLE,
                           declared=app.net_contents, **common,
                           detail="No net contents found on the label.")

    rel = abs(declared.milliliters - label.milliliters) / declared.milliliters
    declared_str = f"{declared.quantity:g} {declared.unit}"
    label_str = f"{label.quantity:g} {label.unit}"
    if rel <= NET_EXACT_REL:
        outcome = Outcome.PASS
        detail = f"{label_str} = {declared_str} ({label.milliliters:g} mL)."
    elif rel <= NET_NEAR_REL:
        outcome = Outcome.REVIEW
        detail = f"Declared {declared_str}, label reads {label_str} - close, needs review."
    else:
        outcome = Outcome.FAIL
        detail = f"Declared {declared_str} ({declared.milliliters:g} mL), label reads {label_str} ({label.milliliters:g} mL)."
    return CheckResult("net_contents", "Net contents", outcome,
                       declared=declared_str, observed=label_str, **common,
                       detail=detail,
                       evidence={"declared_ml": declared.milliliters,
                                 "label_ml": label.milliliters})


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def evaluate(
    app: LabelApplication, pages: list[OcrPage], *, ocr_available: bool = True
) -> list[CheckResult]:
    """All non-warning field checks. Warning checks live in `ttbverify.warning`."""
    if not ocr_available or all(not p.words for p in pages):
        reason = ("OCR unavailable — no automated comparison performed."
                  if not ocr_available else
                  "Nothing readable on the submitted image(s).")
        specs = [
            ("brand", "Brand name", app.brand_name),
            ("class_type", "Class / type", app.class_type),
            ("abv", "Alcohol content", app.alcohol_content),
            ("net_contents", "Net contents", app.net_contents),
            ("producer", "Producer name", app.applicant_name),
            ("origin", "Country of origin", app.origin),
        ]
        return [
            CheckResult(cid, label,
                        Outcome.NOT_DECLARED if declared in (None, "") else Outcome.UNREADABLE,
                        declared=declared, detail=reason)
            for cid, label, declared in specs
        ]

    checks: list[CheckResult] = [
        _text_field_check("brand", "Brand name", app.brand_name, pages,
                          tier="brand"),
        _text_field_check("class_type", "Class / type", app.class_type, pages,
                          tier="subhead"),
    ]
    checks.extend(_abv_check(app, pages))
    checks.append(_net_contents_check(app, pages))
    checks.append(
        _text_field_check("producer", "Producer name", app.applicant_name, pages,
                          tier=None)
    )
    checks.append(
        _text_field_check("origin", "Country of origin", app.origin, pages,
                          tier=None)
    )
    return checks
