"""Generated fixture corpus (design 2.6).

`generate.py` renders synthetic labels to `fixtures/images/` with exact ground
truth in `fixtures/cases.json`. Nothing here is collected from the wild — every
field value is known because we drew it.
"""

from __future__ import annotations

import json
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGES_DIR = os.path.join(REPO_ROOT, "fixtures", "images")
CASES_JSON = os.path.join(REPO_ROOT, "fixtures", "cases.json")
REALISTIC_CASES_JSON = os.path.join(REPO_ROOT, "fixtures", "cases_realistic.json")


def _load(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        cases = json.load(fh)
    for case in cases:
        for img in case["application"]["images"]:
            img["path"] = os.path.join(REPO_ROOT, img["path"])
    return cases


def load_cases() -> list[dict]:
    """The clean generated corpus (fixtures/generate.py), paths repo-rooted."""
    return _load(CASES_JSON)


def load_realistic_cases() -> list[dict]:
    """The realistic corpus (fixtures/realistic.py) — colour, serif faces,
    borders, boxed/rotated warnings, and photo degradation. Cases carry a
    ``grade`` of ``exact`` or ``loose``."""
    return _load(REALISTIC_CASES_JSON)
