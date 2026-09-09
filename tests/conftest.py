"""Shared test helpers.

No test here touches the network, and only the corpus/golden test touches the
`tesseract` binary (skipped when it isn't installed).
"""

from __future__ import annotations

import pytest

from ttbverify.models import BoundingBox
from ttbverify.ocr import OcrPage, OcrWord


def make_page(text: str, *, index: int = 0, role: str | None = None,
              conf: float = 96.0, word_height: int = 20, x0: int = 40,
              y0: int = 40, line_height: int = 30) -> OcrPage:
    """Build an OcrPage from text. Newlines start a new line; words get sequential
    boxes so downstream box math has something non-degenerate to work with."""
    words: list[OcrWord] = []
    y = y0
    for line_no, raw_line in enumerate(text.split("\n"), start=1):
        x = x0
        for tok in raw_line.split():
            w = max(8, 11 * len(tok))
            words.append(OcrWord(
                text=tok, conf=conf,
                box=BoundingBox(x, y, w, word_height),
                line=line_no, block=1, par=1,
            ))
            x += w + 10
        y += line_height
    width = max((wd.box.right for wd in words), default=x0) + x0
    height = y + y0
    return OcrPage(words=words, width=width, height=height, index=index,
                   role=role, engine="fake")


@pytest.fixture(scope="session")
def tesseract_or_skip():
    from ttbverify.ocr import TesseractOcr

    if not TesseractOcr.is_available():
        pytest.skip("tesseract binary not installed")
    return TesseractOcr()
