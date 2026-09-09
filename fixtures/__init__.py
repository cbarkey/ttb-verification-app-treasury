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


def load_cases() -> list[dict]:
    """Load cases.json, resolving image paths against the repo root."""
    with open(CASES_JSON, encoding="utf-8") as fh:
        cases = json.load(fh)
    for case in cases:
        for img in case["application"]["images"]:
            img["path"] = os.path.join(REPO_ROOT, img["path"])
    return cases
