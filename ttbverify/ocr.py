"""OCR behind an interface, with a working no-OCR fallback (N-06).

**Why TSV, not plain text (design 3.1).** The pipeline needs three things per
word that `tesseract`'s default text output throws away:

  1. original casing      -> the W-3 health-warning capitalization check
  2. a bounding box        -> the review-screen region overlay and the W-4 crop
  3. a confidence score    -> distinguishing UNREADABLE ("can't read it") from
                              FAIL ("read it, it's wrong")

So `TesseractOcr` invokes the binary in TSV mode and parses word-level rows. Any
engine swapped in here must preserve those three properties.

`NullOcr` returns no words. It is what the tests use (no test touches a real OCR
binary any more than it touches the network) and it is the degradation path when
`tesseract` is not installed: every downstream check becomes UNREADABLE, never a
silent PASS.

Images are deskewed before recognition (`preprocess.py`) and every box is mapped
back through that correction here, so everything downstream — rules, the W-4
crop, the review overlay — keeps working in the coordinates of the image the
agent actually uploaded.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Protocol

from PIL import Image

from ttbverify.models import BoundingBox
from ttbverify.preprocess import IDENTITY, Correction, prepare

# Word-level confidence floor. Below this a located field is reported UNREADABLE
# rather than compared (design 2.3 failure table).
MIN_WORD_CONF = 45.0

# Upscale small images to roughly this width before OCR — Tesseract is happier
# with larger glyphs and it costs a few milliseconds on synthetic labels.
_OCR_TARGET_WIDTH = 1600


@dataclass
class OcrWord:
    text: str
    conf: float
    box: BoundingBox
    line: int = 0
    block: int = 0
    par: int = 0

    @property
    def height(self) -> int:
        return self.box.height


@dataclass
class OcrPage:
    """OCR output for one image."""

    words: list[OcrWord]
    width: int
    height: int
    index: int = 0
    role: str | None = None
    scale: float = 1.0  # image was resized by this factor before OCR
    engine: str = "null"
    correction: Correction = IDENTITY  # deskew applied before recognition

    @property
    def text(self) -> str:
        """Words joined, with a newline wherever the line number changes."""
        out: list[str] = []
        last_line: tuple[int, int, int] | None = None
        for w in self.words:
            key = (w.block, w.par, w.line)
            if last_line is not None and key != last_line:
                out.append("\n")
            elif out:
                out.append(" ")
            out.append(w.text)
            last_line = key
        return "".join(out)

    @property
    def mean_conf(self) -> float:
        vals = [w.conf for w in self.words if w.conf >= 0]
        return sum(vals) / len(vals) if vals else 0.0

    @property
    def max_word_height(self) -> int:
        return max((w.box.height for w in self.words), default=0)

    def line_text(self, word: OcrWord) -> str:
        key = (word.block, word.par, word.line)
        return " ".join(
            w.text for w in self.words if (w.block, w.par, w.line) == key
        )


class OcrEngine(Protocol):
    def read(self, image_path: str, index: int = 0, role: str | None = None) -> OcrPage:
        ...


def _locate_tesseract() -> str | None:
    env = os.environ.get("TESSERACT_CMD")
    if env and os.path.isfile(env):
        return env
    found = shutil.which("tesseract")
    if found:
        return found
    for candidate in (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        "/usr/bin/tesseract",
        "/usr/local/bin/tesseract",
        "/opt/homebrew/bin/tesseract",
    ):
        if os.path.isfile(candidate):
            return candidate
    return None


def preprocess(image_path: str, *, deskew: bool = True
               ) -> tuple[Image.Image, float, Correction]:
    """EXIF-orient, grayscale, autocontrast, deskew, upscale small images.

    Returns the prepared image, the upscale factor, and the geometric correction
    — the last two are how boxes get mapped back to original-image coordinates.
    """
    return prepare(image_path, target_width=_OCR_TARGET_WIDTH, deskew=deskew)


class TesseractOcr:
    """Shells out to the `tesseract` binary in TSV mode.

    Direct subprocess rather than `pytesseract`: one fewer dependency, and we
    only need the single `image -> TSV` call. `--psm 3` (fully automatic page
    segmentation) suits multi-block label art.
    """

    def __init__(self, cmd: str | None = None, lang: str = "eng", psm: int = 3,
                 deskew: bool = True):
        self.cmd = cmd or _locate_tesseract()
        self.lang = lang
        self.psm = psm
        self.deskew = deskew
        if not self.cmd:
            raise FileNotFoundError(
                "tesseract binary not found. Install it (see README) or set "
                "TESSERACT_CMD, or use NullOcr for the degraded path."
            )

    @staticmethod
    def is_available() -> bool:
        return _locate_tesseract() is not None

    def read(self, image_path: str, index: int = 0, role: str | None = None) -> OcrPage:
        prepared, scale, correction = preprocess(image_path, deskew=self.deskew)
        tmp = None
        try:
            import tempfile

            fd, tmp = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            prepared.save(tmp)
            proc = subprocess.run(
                [self.cmd, tmp, "stdout", "-l", self.lang, "--psm", str(self.psm), "tsv"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",  # Tesseract can emit bytes the OS locale can't decode
                timeout=30,
            )
        finally:
            if tmp and os.path.exists(tmp):
                os.remove(tmp)

        if proc.returncode != 0:
            raise RuntimeError(f"tesseract failed: {proc.stderr.strip()}")

        width = round(prepared.width / scale)
        height = round(prepared.height / scale)
        words = _parse_tsv(proc.stdout, scale)
        if correction.applied:
            # Boxes come out in deskewed space; the agent sees the original image.
            words = [
                OcrWord(w.text, w.conf, correction.map_box(w.box, width, height),
                        w.line, w.block, w.par)
                for w in words
            ]
        return OcrPage(
            words=words,
            width=width,
            height=height,
            index=index,
            role=role,
            scale=scale,
            engine="tesseract",
            correction=correction,
        )


class NullOcr:
    """Returns no words. Test double and no-network / no-binary degradation path."""

    def read(self, image_path: str, index: int = 0, role: str | None = None) -> OcrPage:
        try:
            with Image.open(image_path) as img:
                w, h = img.size
        except OSError:
            w, h = 0, 0
        return OcrPage(words=[], width=w, height=h, index=index, role=role, engine="null")


def _parse_tsv(raw: str, scale: float) -> list[OcrWord]:
    lines = raw.splitlines()
    if not lines:
        return []
    header = lines[0].split("\t")
    try:
        col = {name: header.index(name) for name in (
            "level", "block_num", "par_num", "line_num",
            "left", "top", "width", "height", "conf", "text",
        )}
    except ValueError:
        return []

    out: list[OcrWord] = []
    for row in lines[1:]:
        parts = row.split("\t")
        if len(parts) <= col["text"]:
            continue
        if parts[col["level"]] != "5":  # 5 == word
            continue
        text = parts[col["text"]].strip()
        if not text:
            continue
        try:
            conf = float(parts[col["conf"]])
            left = int(parts[col["left"]]) / scale
            top = int(parts[col["top"]]) / scale
            width = int(parts[col["width"]]) / scale
            height = int(parts[col["height"]]) / scale
        except ValueError:
            continue
        out.append(
            OcrWord(
                text=text,
                conf=conf,
                box=BoundingBox(round(left), round(top), round(width), round(height)),
                line=int(parts[col["line_num"]]),
                block=int(parts[col["block_num"]]),
                par=int(parts[col["par_num"]]),
            )
        )
    return out
