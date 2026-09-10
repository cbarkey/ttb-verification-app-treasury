"""The rules engine: declared application values vs. what OCR read off the label.

Pure comparison over `LabelApplication` + `list[OcrPage]`. No I/O, no OCR calls
here — that keeps it fast (design 6.1: ~20 ms) and trivially testable.

Two design points enforced here:

  * **Prominence filter (design 3.2).** Brand and class/type are display type.
    Matching them against *any* text on the label produces false approvals: a
    label's fine-print bottler statement can contain a string that fuzzy-matches
    the declared brand even when the actual, prominent brand is something else.
    So brand/class matching only considers words at least `PROMINENCE` of the
    tallest word on the page. Producer/origin are *expected* in fine print and
    are matched without the filter.

  * **Governing principle.** A field that couldn't be read is UNREADABLE; a field
    with no declared value is NOT_DECLARED. Neither is ever a silent PASS.
"""

from __future__ import annotations

import re
import statistics
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

# Prominence filter (design 3.2), expressed as a multiple of the page's *median*
# word height rather than a fraction of the single tallest word — the latter was
# overfit to the clean corpus and excluded legitimate class/type text on real
# labels, where the brand is 2-3x the size of everything else.
#
#   BRAND_PROMINENCE  — the brand is the biggest thing on the label; a fine-print
#                       bottler line that happens to contain the declared brand
#                       string must not clear this bar.
#   SUBHEAD_PROMINENCE — class/type is a sub-headline: bigger than body/fine
#                        print, but not display-sized. Just needs to beat the
#                        fine print.
BRAND_PROMINENCE = 1.8
SUBHEAD_PROMINENCE = 0.9

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


def _line_window(line: list[OcrWord], want: int) -> list[OcrWord]:
    return line[: want + 2] if len(line) > want + 2 else line


def _blocks(lines: list[list[OcrWord]]) -> list[list[OcrWord]]:
    """Group vertically-adjacent lines so a value wrapped across two lines
    (a long brand name, an address) can still be matched as one run.

    Only merges lines of *similar* height — a wrapped brand's two lines are the
    same size; a brand followed by a smaller class/type line is not, and must
    stay separate so its box doesn't swallow the subhead.
    """
    out: list[list[OcrWord]] = []
    for line in lines:
        if not line:
            continue
        top = min(w.box.top for w in line)
        h = max(w.box.height for w in line)
        if out:
            prev = out[-1]
            prev_bottom = max(w.box.bottom for w in prev)
            prev_h = max(w.box.height for w in prev)
            close = 0 <= top - prev_bottom <= 0.9 * h
            similar = abs(h - prev_h) <= 0.25 * max(h, prev_h)
            if close and similar:
                out[-1].extend(line)
                continue
        out.append(list(line))
    return out


def _prominence_threshold(page: OcrPage, factor: float | None) -> float:
    """Minimum word height to count as prominent on this page.

    `factor` is a multiple of the median word height; `None` means no filter.
    Capped below the tallest word so the display line itself always qualifies,
    and disabled on very sparse pages (nothing to filter there).
    """
    if factor is None or len(page.words) < 5:
        return 0.0
    heights = sorted(w.box.height for w in page.words)
    median = statistics.median(heights)
    return min(median * factor, 0.85 * heights[-1])


def _locate_text(
    pages: list[OcrPage], declared: str, *, prominence: float | None
) -> Location | None:
    """Best matching window of consecutive words for `declared`.

    Returns None when there is no candidate text at all (→ UNREADABLE upstream).

    On a FAIL for a prominence-filtered field, the highest-*similarity* fragment
    is usually noise (a stray word in fine print or the warning block). What the
    agent needs to see is the text that is actually printed prominently — so the
    box/observed fall back to the most prominent candidate line, while the
    outcome stays FAIL.
    """
    want = max(1, len(declared.split()))
    best: Location | None = None
    prominent: tuple[int, int, Location] | None = None  # (height, -top, loc)
    filtered = prominence is not None

    for page in pages:
        if not page.words:
            continue
        threshold = _prominence_threshold(page, prominence)
        prom_lines = [[w for w in ln if w.box.height >= threshold]
                      for ln in _iter_lines(page.words)]
        for cand in _blocks([ln for ln in prom_lines if ln]):
            if not cand:
                continue

            if filtered:
                head = _line_window(cand, want)
                text = " ".join(w.text for w in head)
                loc = Location(
                    match=compare(declared, text),
                    box=BoundingBox.enclosing(w.box for w in head),
                    page_index=page.index, page_role=page.role, observed=text,
                    mean_conf=sum(w.conf for w in head) / len(head),
                )
                key = (max(w.box.height for w in head), -min(w.box.top for w in head))
                if prominent is None or key > prominent[:2]:
                    prominent = (*key, loc)

            for start in range(len(cand)):
                for length in range(1, min(want + 1, len(cand) - start) + 1):
                    window = cand[start : start + length]
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
    if best.match.outcome is Outcome.FAIL and prominent is not None:
        keep = prominent[2]
        return Location(best.match, keep.box, keep.page_index, keep.page_role,
                        keep.observed, keep.mean_conf)
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
    prominence: float | None,
) -> CheckResult:
    if declared is None or not declared.strip():
        return CheckResult(check_id, label, Outcome.NOT_DECLARED,
                           detail="No value declared on the application.")

    loc = _locate_text(pages, declared, prominence=prominence)
    if loc is None:
        where = "in prominent text" if prominence is not None else "anywhere on the label"
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
                          prominence=BRAND_PROMINENCE),
        _text_field_check("class_type", "Class / type", app.class_type, pages,
                          prominence=SUBHEAD_PROMINENCE),
    ]
    checks.extend(_abv_check(app, pages))
    checks.append(_net_contents_check(app, pages))
    checks.append(
        _text_field_check("producer", "Producer name", app.applicant_name, pages,
                          prominence=None)
    )
    checks.append(
        _text_field_check("origin", "Country of origin", app.origin, pages,
                          prominence=None)
    )
    return checks
