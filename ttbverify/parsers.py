"""Numeric field parsing: alcohol content (ABV + proof) and net contents.

Design 3.5: these fields are compared as *numbers*, not strings. `750 mL`,
`750ML` and `0.75 L` are equal; `45% Alc./Vol.`, `ALC 45% BY VOL` and `45% ABV`
all parse to the same value. Proof, when present, is checked against ABV
(`proof == 2 x ABV`) — pure arithmetic, a real and cheap rejection reason.

All parsers are pure functions over already-extracted text. They return `None`
for the value when nothing parseable is found; the caller decides whether that is
`UNREADABLE` (expected a value, could not read it) or `NOT_DECLARED` (no
application value in the first place).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --- Alcohol content -------------------------------------------------------

# A percentage figure: 45%, 45.5 %, 5%.
_PERCENT = re.compile(r"(\d{1,2}(?:\.\d{1,2})?)\s*%")
# Words that mark a percentage as an *alcohol* percentage rather than anything
# else printed on the label.
_ALC_CONTEXT = re.compile(r"\b(?:alc|abv|vol|alcohol)\b", re.IGNORECASE)
# Proof: "90 proof", "90 PROOF", "90°".
_PROOF = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*(?:proof\b|°)", re.IGNORECASE)

# Proof is 2 x ABV by definition; labels round. Allow half-a-point of rounding
# slack in each direction, no more (design 3.5).
PROOF_TOLERANCE = 1.01


@dataclass(frozen=True)
class AbvReading:
    """What a label's alcohol statement says, parsed.

    Spans are character offsets into the source text, so a caller can point
    at the figure it read rather than just reporting a number.
    """

    abv: float | None
    proof: float | None
    abv_span: tuple[int, int] | None = None
    proof_span: tuple[int, int] | None = None

    @property
    def proof_consistent(self) -> bool | None:
        """None when there is nothing to compare (need both abv and proof)."""
        if self.abv is None or self.proof is None:
            return None
        return abs(self.proof - 2 * self.abv) <= PROOF_TOLERANCE


def parse_abv(text: str) -> AbvReading:
    """Pull ABV and proof out of free text.

    Handles the phrasings that actually appear on labels — `45% Alc./Vol.`,
    `ALC 45% BY VOL`, `45% ABV`, `Alc. 45% by Vol.`, `90 proof`, `90°`.

    A percentage alone is not enough: labels carry other percentages (juice
    content, for one), so where several appear the one in alcohol *context*
    wins. Returns an empty reading rather than raising — an unparseable
    declaration is a `REVIEW` upstream, not a crash.
    """
    if not text:
        return AbvReading(None, None)

    percents = list(_PERCENT.finditer(text))
    abv: float | None = None
    abv_span: tuple[int, int] | None = None

    if len(percents) == 1:
        abv = float(percents[0].group(1))
        abv_span = percents[0].span()
    elif percents:
        # Multiple percentages on the label — pick the one closest to an alcohol
        # context word ("alc" / "abv" / "vol" / "alcohol").
        contexts = [m.start() for m in _ALC_CONTEXT.finditer(text)]
        best: tuple[float, re.Match[str]] | None = None
        for m in percents:
            if not contexts:
                break
            dist = min(abs(c - m.start()) for c in contexts)
            if dist <= 24 and (best is None or dist < best[0]):
                best = (dist, m)
        if best is not None:
            abv = float(best[1].group(1))
            abv_span = best[1].span()

    proof_match = _PROOF.search(text)
    proof = float(proof_match.group(1)) if proof_match else None
    proof_span = proof_match.span() if proof_match else None

    return AbvReading(abv, proof, abv_span, proof_span)


# --- Net contents --------------------------------------------------------

# unit token -> millilitres per unit
_UNIT_ML = {
    "ml": 1.0,
    "milliliter": 1.0,
    "milliliters": 1.0,
    "millilitre": 1.0,
    "millilitres": 1.0,
    "cl": 10.0,
    "centiliter": 10.0,
    "centiliters": 10.0,
    "centilitre": 10.0,
    "centilitres": 10.0,
    "l": 1000.0,
    "liter": 1000.0,
    "liters": 1000.0,
    "litre": 1000.0,
    "litres": 1000.0,
    "floz": 29.5735,
    "fluidounce": 29.5735,
    "fluidounces": 29.5735,
    "pt": 473.176,
    "pint": 473.176,
    "pints": 473.176,
}

_NET = re.compile(
    r"(\d+(?:\.\d+)?)\s*"
    r"(ml|milliliters?|millilitres?|cl|centiliters?|centilitres?|"
    r"l|liters?|litres?|fl\.?\s*oz\.?|fluid\s+ounces?|pints?|pt)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NetContentsReading:
    """A net-contents statement, normalized to millilitres for comparison."""

    milliliters: float | None
    quantity: float | None = None
    unit: str | None = None
    span: tuple[int, int] | None = None


def _canonical_unit(raw: str) -> str:
    return re.sub(r"[^a-z]", "", raw.lower())


def to_milliliters(quantity: float, unit: str) -> float | None:
    """Convert to millilitres, or None for a unit we do not recognise.

    Comparing net contents as strings would fail `750 mL` against `0.75 L`,
    which is the same bottle (design 3.5). Everything becomes millilitres and
    the comparison is numeric.
    """
    factor = _UNIT_ML.get(_canonical_unit(unit))
    return None if factor is None else factor * quantity


def parse_net_contents(text: str) -> NetContentsReading:
    """Parse a quantity + unit out of free text (`750 mL`, `0.75 L`, `12 fl oz`).

    Returns an empty reading when nothing parses, which upstream turns into
    `REVIEW` — never a mismatch against a value we failed to understand.
    """
    if not text:
        return NetContentsReading(None)
    m = _NET.search(text)
    if not m:
        return NetContentsReading(None)
    quantity = float(m.group(1))
    unit_raw = m.group(2)
    ml = to_milliliters(quantity, unit_raw)
    return NetContentsReading(ml, quantity, _canonical_unit(unit_raw), m.span())
