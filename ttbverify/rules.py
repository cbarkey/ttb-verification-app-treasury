"""The rules engine: declared application values vs. what OCR read off the label.

Pure comparison over `LabelApplication` + `list[OcrPage]`. No I/O, no OCR calls
here — that keeps it fast (design 6.1: ~20 ms) and trivially testable.

Two design points enforced here:

  * **Display admissibility (design 3.2).** Brand and class/type are display
    text. Matching them against *any* text on the label produces false
    approvals — a fine-print bottler statement can contain the declared brand
    while the real, prominent brand is something else. So a display match must
    be (most of) its own line rather than a fragment inside a longer sentence,
    and must not be fine print. Producer/origin are *expected* in fine print and
    are matched against all text.

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
from ttbverify.normalize import MatchResult, compare, similarity
from ttbverify.ocr import MIN_WORD_CONF, OcrPage, OcrWord
from ttbverify.parsers import parse_abv, parse_net_contents

# Display admissibility (design 3.2).
#
# Earlier versions guessed which *line* was the brand — by OCR bounding-box
# height, then by reading position. Both are wrong: box height is font-dependent
# (Copperplate-style faces render short caps, so a large display brand can
# measure a smaller box than a smaller-point class line) and position assumes a
# layout. Neither is something a compliance tool should bet on.
#
# What actually distinguishes a real brand occurrence from the decoy in a
# bottler statement is *how the match sits in its line*: a brand is (most of) a
# line of its own; "Old Tom Distillery" inside "Distilled by Old Tom Distillery,
# Bardstown, KY" is three words of a twelve-word sentence. That signal is
# font-free and layout-free. Fine print is a second, independent guard.

# A display match must be (most of) its own line — a declared brand found as a
# fragment inside a longer sentence is a bottler statement, not a brand.
_DISPLAY_MIN_COVERAGE = 0.6
# ...and a line shorter than this fraction of the page's tallest line is fine
# print (a bottler statement, the warning) and never counts as display text.
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


_OUTCOME_ORDER = {Outcome.PASS: 3, Outcome.REVIEW: 2, Outcome.FAIL: 1}


def _rank(m: MatchResult, declared: str = "", observed: str = "") -> tuple[float, ...]:
    """Order candidate matches: outcome first, then how well they matched.

    The last key is *literal* similarity, before normalization. It only breaks
    ties — when the same value appears twice and both normalize to a match, take
    the more literal one. On a label whose distillery is also its brand, that
    points the producer check at "Old Tom Distillery, LLC" in the bottler
    statement rather than at "OLD TOM DISTILLERY" in the display type, which is
    the occurrence an agent actually wants boxed.
    """
    literal = similarity(declared.casefold(), observed.casefold()) if declared else 0.0
    return (_OUTCOME_ORDER[m.outcome], m.similarity, literal)


@dataclass
class Location:
    match: MatchResult
    box: BoundingBox | None
    page_index: int
    page_role: str | None
    observed: str | None
    mean_conf: float
    status: str = "matched"   # matched | only_in_fine_print | not_found


def _line_h(line: list[OcrWord]) -> int:
    return max(w.box.height for w in line)


def _page_lines(page: OcrPage) -> list[list[OcrWord]]:
    return [ln for ln in _iter_lines(page.words) if ln]


def _fine_print_cutoff(lines: list[list[OcrWord]]) -> float:
    """Height below which a line counts as fine print on this page."""
    if len(lines) < 2:
        return 0.0
    return _FINE_PRINT_FRACTION * max(_line_h(ln) for ln in lines)


def _windows(lines: list[list[OcrWord]], want: int):
    """Every candidate run of consecutive words as (words, line_word_count,
    line_height). Includes runs that span one line break, so a brand wrapped
    onto a second line is still matchable as a whole.

    `line_height` is the height of the *line*, not of the words in the window —
    a word with no ascender or descender ("Gin") measures short and would
    otherwise drag its whole line below the fine-print cutoff.
    """
    for i, line in enumerate(lines):
        h = _line_h(line)
        for start in range(len(line)):
            for length in range(1, min(want + 1, len(line) - start) + 1):
                yield line[start : start + length], len(line), h
        if i + 1 < len(lines) and len(line) < want:
            nxt = lines[i + 1]
            both = max(h, _line_h(nxt))
            for take in range(1, min(want - len(line) + 1, len(nxt)) + 1):
                yield line + nxt[:take], len(line) + len(nxt), both


def _locate_text(
    pages: list[OcrPage], declared: str, *, display_only: bool
) -> Location | None:
    """Find `declared` on the label.

    Every run of consecutive words on every page is a candidate. For a *display*
    field (brand, class/type) a candidate is only admissible if it is

      * (most of) its own line rather than a fragment buried inside a longer
        sentence, and
      * not fine print.

    That pair is the real content of design 3.2's bottler-statement false
    approval — and unlike anything based on type size it doesn't depend on the
    font or on where the label happens to put things.

    Returns None only when there is no text at all (→ UNREADABLE upstream). A
    returned Location carries a `status`:

      matched             the declared value is on the label (see `match`)
      only_in_fine_print  it *is* there, but buried — boxed so the agent can see
      not_found           it isn't on the label; `observed` is None, never a guess
    """
    want = max(1, len(declared.split()))
    best_adm: Location | None = None
    best_any: Location | None = None
    display_region: tuple[int, str | None, BoundingBox] | None = None
    saw_text = False

    for page in pages:
        lines = _page_lines(page)
        if not lines:
            continue
        saw_text = True
        cutoff = _fine_print_cutoff(lines) if display_only else 0.0

        if display_only and display_region is None:
            shown = [w for ln in lines if _line_h(ln) >= cutoff for w in ln]
            if shown:
                display_region = (page.index, page.role,
                                  BoundingBox.enclosing(w.box for w in shown))

        for window, line_size, line_height in _windows(lines, want):
            text = " ".join(w.text for w in window)
            m = compare(declared, text)
            loc = Location(m, BoundingBox.enclosing(w.box for w in window),
                           page.index, page.role, text,
                           sum(w.conf for w in window) / len(window))
            key = _rank(m, declared, text)
            if best_any is None or key > _rank(best_any.match, declared,
                                               best_any.observed or ""):
                best_any = loc
            if display_only:
                covers_line = len(window) / line_size >= _DISPLAY_MIN_COVERAGE
                is_display = line_height >= cutoff
                if not (covers_line and is_display):
                    continue
            if best_adm is None or key > _rank(best_adm.match, declared,
                                               best_adm.observed or ""):
                best_adm = loc

    if not saw_text:
        return None

    found = (Outcome.PASS, Outcome.REVIEW)
    if best_adm is not None and best_adm.match.outcome in found:
        return best_adm

    if display_only and best_any is not None and best_any.match.outcome in found:
        return Location(
            MatchResult(Outcome.FAIL, "fine_print", best_any.match.similarity,
                        "appears only in small print, not as the label's display text"),
            best_any.box, best_any.page_index, best_any.page_role,
            best_any.observed, best_any.mean_conf, status="only_in_fine_print")

    box = pi = pr = None
    if display_region is not None:
        pi, pr, box = display_region
    return Location(
        MatchResult(Outcome.FAIL, "mismatch", 0.0, "not found on the label"),
        box, pi if pi is not None else 0, pr, None, 0.0, status="not_found")


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
    display_only: bool,
) -> CheckResult:
    if declared is None or not declared.strip():
        return CheckResult(check_id, label, Outcome.NOT_DECLARED,
                           detail="No value declared on the application.")

    loc = _locate_text(pages, declared, display_only=display_only)
    if loc is None:
        return CheckResult(check_id, label, Outcome.UNREADABLE, declared=declared,
                           detail="Nothing readable on the submitted image(s).")

    common = dict(declared=declared, box=loc.box,
                  image_index=loc.page_index, image_role=loc.page_role)

    if loc.status == "not_found":
        # No guessing: we don't claim to know what the label calls this field,
        # only that the declared value isn't there.
        where = "display text" if display_only else "text"
        return CheckResult(check_id, label, Outcome.FAIL, observed=None,
                           detail=f"Not found in the label's {where}.",
                           evidence={"match": "not_found"}, **common)

    if loc.status == "only_in_fine_print":
        return CheckResult(
            check_id, label, Outcome.FAIL, observed=loc.observed, tier="fine_print",
            detail=("Found only in small print, not as the label's display text "
                    "— the prominent text is something else."),
            evidence={"match": "only_in_fine_print",
                      "similarity": round(loc.match.similarity, 3)},
            **common)

    if loc.match.outcome is not Outcome.PASS and loc.mean_conf < MIN_WORD_CONF:
        return CheckResult(check_id, label, Outcome.UNREADABLE, observed=loc.observed,
                           detail="Matching text was read with low confidence.",
                           evidence={"match": "low_confidence"}, **common)

    return CheckResult(
        check_id, label, loc.match.outcome,
        observed=loc.observed, tier=loc.match.tier, detail=loc.match.detail,
        evidence={"match": "matched", "similarity": round(loc.match.similarity, 3)},
        **common,
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
                          display_only=True),
        _text_field_check("class_type", "Class / type", app.class_type, pages,
                          display_only=True),
    ]
    checks.extend(_abv_check(app, pages))
    checks.append(_net_contents_check(app, pages))
    checks.append(
        _text_field_check("producer", "Producer name", app.applicant_name, pages,
                          display_only=False)
    )
    checks.append(
        _text_field_check("origin", "Country of origin", app.origin, pages,
                          display_only=False)
    )
    return checks
