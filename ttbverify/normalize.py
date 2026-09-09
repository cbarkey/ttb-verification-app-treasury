"""The normalization ladder for text fields — brand, class/type, producer, origin.

Design 2.3: four tiers, first match wins, and the tier that fired is recorded so
the UI can explain *why* something passed ("matched after ignoring
capitalization") rather than just asserting "pass" (F-09).

  1. Exact          (whitespace collapsed only)          -> PASS
  2. Case-folded                                          -> PASS   (STONE'S THROW)
  3. Punctuation / whitespace / company-suffix normalized -> PASS
  4. Fuzzy similarity  >= 0.92 -> REVIEW ;  below -> FAIL

The fuzzy tier uses a hand-rolled normalized Levenshtein ratio. This is
deliberate (N-06, no-egress fallback): it is ~30 lines, has no dependency, and
keeps the unit layer running in milliseconds. If a fuzzy-matching library is
added later it must remain optional — this module must keep working without it.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from ttbverify.models import Outcome

FUZZY_REVIEW_THRESHOLD = 0.92

# Trailing entity suffixes stripped at tier 3. Kept deliberately short — design
# 2.3 names "LLC / Inc. / Co."; the rest are the uncontroversial neighbours.
_COMPANY_SUFFIXES = {
    "llc", "l.l.c.", "inc", "inc.", "incorporated", "co", "co.", "company",
    "corp", "corp.", "corporation", "ltd", "ltd.", "lp", "l.p.",
}

_CURLY_APOSTROPHES = dict.fromkeys(map(ord, "‘’ʼ′‛"), "'")
_CURLY_QUOTES = dict.fromkeys(map(ord, "“”″"), '"')
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―"), "-")

_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class MatchResult:
    outcome: Outcome
    tier: str          # exact | case | punctuation | fuzzy | mismatch
    similarity: float   # 1.0 for tiers 1-3; computed ratio for fuzzy/mismatch
    detail: str

    @property
    def matched(self) -> bool:
        return self.outcome is Outcome.PASS


def collapse_ws(text: str) -> str:
    return _WS.sub(" ", text).strip()


def casefold(text: str) -> str:
    return collapse_ws(text).casefold()


def punct_norm(text: str) -> str:
    """Tier-3 canonical form: casing, punctuation, and entity suffixes removed.

    Idempotent — `punct_norm(punct_norm(x)) == punct_norm(x)` (design 2.6
    property test).
    """
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_CURLY_APOSTROPHES).translate(_CURLY_QUOTES).translate(_DASHES)
    text = text.replace("&", " and ")
    text = text.casefold()
    # Drop apostrophes entirely (straight ones too) so "stone's" == "stones",
    # and turn any remaining punctuation into spaces.
    text = text.replace("'", "")
    text = re.sub(r"[^\w\s]", " ", text)
    tokens = [t for t in collapse_ws(text).split(" ") if t]
    while tokens and tokens[-1] in _COMPANY_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def levenshtein(a: str, b: str) -> int:
    """Iterative two-row edit distance."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[-1]


def similarity(a: str, b: str) -> float:
    """Normalized Levenshtein ratio in [0, 1]. Two empty strings are identical."""
    if not a and not b:
        return 1.0
    longest = max(len(a), len(b))
    return 1.0 - levenshtein(a, b) / longest


def compare(declared: str, observed: str) -> MatchResult:
    """Walk the ladder. `observed` is text read off the label (F-09)."""
    d_raw, o_raw = collapse_ws(declared), collapse_ws(observed)

    if not o_raw:
        return MatchResult(Outcome.FAIL, "mismatch", 0.0, "nothing read from the label")

    if d_raw == o_raw:
        return MatchResult(Outcome.PASS, "exact", 1.0, "matched exactly")

    if casefold(declared) == casefold(observed):
        return MatchResult(
            Outcome.PASS, "case", 1.0, "matched after ignoring capitalization"
        )

    d_norm, o_norm = punct_norm(declared), punct_norm(observed)
    if d_norm == o_norm:
        return MatchResult(
            Outcome.PASS,
            "punctuation",
            1.0,
            "matched after ignoring punctuation and spacing",
        )

    sim = similarity(d_norm, o_norm)
    if sim >= FUZZY_REVIEW_THRESHOLD:
        return MatchResult(
            Outcome.REVIEW,
            "fuzzy",
            sim,
            f"close but not exact ({sim:.0%} similar) — needs a human check",
        )
    return MatchResult(
        Outcome.FAIL,
        "mismatch",
        sim,
        f"does not match ({sim:.0%} similar)",
    )
