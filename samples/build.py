"""Build sample batch ZIPs for trying the batch flow.

    python -m samples.build

Writes two archives next to this file:

  sample_batch_ok.zip      6 rows drawn from the realistic corpus — a mix of
                           PASS / FAIL / REVIEW so the queue is worth looking at.
  sample_batch_issues.zip  a deliberately broken manifest: a row pointing at a
                           missing image, a duplicate serial, values that won't
                           parse, a bad commodity, and an orphan image — so the
                           pre-flight reconciliation screen has something to show.
"""

from __future__ import annotations

import csv
import io
import json
import os
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

_HEADER = [
    "serial_number", "brand_name", "class_type", "commodity",
    "alcohol_content", "net_contents", "applicant_name", "image_files",
]


def _realistic() -> dict[str, dict]:
    with open(os.path.join(ROOT, "fixtures", "cases_realistic.json"), encoding="utf-8") as fh:
        return {c["case_id"]: c["application"] for c in json.load(fh)}


def _img(rel: str) -> bytes:
    with open(os.path.join(ROOT, rel), "rb") as fh:
        return fh.read()


def _manifest(rows: list[list[str]]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(_HEADER)
    w.writerows(rows)
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")


def _write_zip(path: str, manifest: bytes, files: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.csv", manifest)
        for name, data in files.items():
            z.writestr(name, data)
    print(f"wrote {os.path.relpath(path, ROOT)}  ({os.path.getsize(path) // 1024} KB)")


def build_ok() -> None:
    apps = _realistic()
    # (case_id, serial, note)
    picks = [
        ("r01_whiskey_clean", "500001"),   # -> PASS
        ("r02_wine_boxed", "500002"),      # -> PASS
        ("r03_gin_single", "500003"),      # -> PASS (single image)
        ("r05_brand_decoy", "500004"),     # -> FAIL (brand)
        ("r06_abv_mismatch", "500005"),    # -> FAIL (abv)
        ("r09_warn_reworded", "500006"),   # -> FAIL (warn_text)
    ]
    rows, files = [], {}
    for case_id, serial in picks:
        app = apps[case_id]
        names = []
        for _i, ref in enumerate(app["images"]):
            base = os.path.basename(ref["path"])
            names.append(base)
            files[base] = _img(ref["path"])
        rows.append([
            serial, app["brand_name"], app["class_type"], app["commodity"],
            app.get("alcohol_content") or "", app.get("net_contents") or "",
            app.get("applicant_name") or "", ";".join(names),
        ])
    _write_zip(os.path.join(HERE, "sample_batch_ok.zip"), _manifest(rows), files)


def build_issues() -> None:
    apps = _realistic()
    ok = apps["r01_whiskey_clean"]
    ok_names = [os.path.basename(r["path"]) for r in ok["images"]]
    files = {n: _img(r["path"]) for n, r in zip(ok_names, ok["images"], strict=False)}
    files["leftover_neck.png"] = _img(apps["r03_gin_single"]["images"][0]["path"])  # orphan

    rows = [
        # a fine row, so ok_count > 0 and you can still proceed
        ["600001", ok["brand_name"], ok["class_type"], "spirits",
         "45% Alc./Vol.", "750 mL", "Old Tom Distillery, LLC", ";".join(ok_names)],
        # points at an image that isn't in the ZIP
        ["600002", "NORTHWIND RESERVE", "Blended Whiskey", "spirits",
         "43% Alc./Vol.", "750 mL", "Northwind Co.", "northwind_front.png"],
        # duplicate serial number
        ["600001", "DUPLICATE ROW", "Vodka", "spirits",
         "40% Alc./Vol.", "750 mL", "Somebody", ";".join(ok_names)],
        # declared values that won't parse
        ["600003", "TBD BRAND", "Gin", "spirits",
         "TBD", "a jug", "Placeholder LLC", ";".join(ok_names)],
        # commodity that isn't wine / malt / spirits
        ["600004", "MYSTERY CAN", "Hard Seltzer", "seltzer",
         "5% Alc./Vol.", "12 fl oz", "Mystery Bev", ";".join(ok_names)],
    ]
    _write_zip(os.path.join(HERE, "sample_batch_issues.zip"), _manifest(rows), files)


def main() -> None:
    build_ok()
    build_issues()


if __name__ == "__main__":
    main()
