"""CSV manifest parsing and pre-flight reconciliation for batch upload (design 3.4).

A batch is one ZIP: ``manifest.csv`` at the root, image files alongside. Pairing
is by an explicit ``image_files`` column (``;``-separated filenames), never by
convention — an export tool renaming a file shouldn't silently break pairing.

Pre-flight runs *before any OCR* and hands the agent a reconciliation summary to
confirm: missing columns, rows pointing at absent images, images with no row,
duplicate serial numbers, declared values that won't parse. Nobody should watch
300 labels process only to find row 12 was broken.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from ttbverify.models import Commodity
from ttbverify.parsers import parse_abv, parse_net_contents

REQUIRED_COLUMNS = ["serial_number", "brand_name", "class_type", "commodity", "image_files"]
OPTIONAL_COLUMNS = [
    "ttb_id", "fanciful_name", "alcohol_content", "net_contents",
    "applicant_name", "applicant_address", "origin",
]
ALL_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS


@dataclass
class ManifestRow:
    line: int                       # 1-based row number in the file (excl. header)
    serial_number: str
    fields: dict                    # the canonical-schema field values (no images)
    image_names: list[str]          # filenames from image_files, in order
    row_errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.row_errors


@dataclass
class PreflightReport:
    rows: list[ManifestRow]
    missing_columns: list[str] = field(default_factory=list)
    rows_missing_images: list[dict] = field(default_factory=list)   # {line, serial, missing}
    unreferenced_images: list[str] = field(default_factory=list)
    duplicate_serials: list[str] = field(default_factory=list)
    unparseable_values: list[dict] = field(default_factory=list)    # {line, serial, field, value}
    fatal: str | None = None                                        # e.g. no manifest at all

    @property
    def ok_rows(self) -> list[ManifestRow]:
        blocked = {d["serial"] for d in self.rows_missing_images}
        return [r for r in self.rows if r.ok and r.serial_number not in blocked]

    @property
    def blocked_rows(self) -> list[ManifestRow]:
        ok = {r.serial_number for r in self.ok_rows}
        return [r for r in self.rows if r.serial_number not in ok]

    @property
    def can_proceed(self) -> bool:
        return self.fatal is None and not self.missing_columns and bool(self.ok_rows)

    def to_dict(self) -> dict:
        return {
            "fatal": self.fatal,
            "missing_columns": self.missing_columns,
            "row_count": len(self.rows),
            "ok_count": len(self.ok_rows),
            "blocked_count": len(self.blocked_rows),
            "rows_missing_images": self.rows_missing_images,
            "unreferenced_images": self.unreferenced_images,
            "duplicate_serials": self.duplicate_serials,
            "unparseable_values": self.unparseable_values,
            "row_errors": [
                {"line": r.line, "serial": r.serial_number, "errors": r.row_errors}
                for r in self.rows if r.row_errors
            ],
            "can_proceed": self.can_proceed,
        }


def parse_manifest(csv_bytes: bytes) -> tuple[list[ManifestRow], list[str]]:
    """Parse the manifest. Returns (rows, missing_required_columns)."""
    text = csv_bytes.decode("utf-8-sig", errors="replace")  # tolerate an Excel BOM
    reader = csv.DictReader(io.StringIO(text))
    headers = [h.strip() for h in (reader.fieldnames or [])]
    missing = [c for c in REQUIRED_COLUMNS if c not in headers]
    if missing:
        return [], missing

    rows: list[ManifestRow] = []
    for i, raw in enumerate(reader, start=1):
        raw = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
        serial = raw.get("serial_number", "")
        errors: list[str] = []

        for col in ("serial_number", "brand_name", "class_type"):
            if not raw.get(col):
                errors.append(f"{col} is empty")

        commodity_raw = raw.get("commodity", "").lower()
        try:
            commodity = Commodity(commodity_raw)
        except ValueError:
            commodity = None
            errors.append(
                f"commodity '{raw.get('commodity')}' is not one of wine / malt / spirits"
            )

        image_names = [n.strip() for n in raw.get("image_files", "").split(";") if n.strip()]
        if not image_names:
            errors.append("image_files is empty")

        fields = {
            "serial_number": serial,
            "brand_name": raw.get("brand_name") or "",
            "class_type": raw.get("class_type") or "",
            "commodity": commodity.value if commodity else "spirits",
            "ttb_id": raw.get("ttb_id") or None,
            "fanciful_name": raw.get("fanciful_name") or None,
            "alcohol_content": raw.get("alcohol_content") or None,
            "net_contents": raw.get("net_contents") or None,
            "applicant_name": raw.get("applicant_name") or None,
            "applicant_address": raw.get("applicant_address") or None,
            "origin": raw.get("origin") or None,
        }
        rows.append(ManifestRow(line=i, serial_number=serial, fields=fields,
                                image_names=image_names, row_errors=errors))
    return rows, []


def reconcile(rows: list[ManifestRow], zip_image_names: list[str]) -> PreflightReport:
    """Cross-check the parsed manifest against the images actually in the ZIP."""
    report = PreflightReport(rows=rows)
    present = {name.rsplit("/", 1)[-1] for name in zip_image_names}

    # rows -> images not in the ZIP
    referenced: set[str] = set()
    for r in rows:
        referenced.update(r.image_names)
        missing = [n for n in r.image_names if n not in present]
        if missing:
            report.rows_missing_images.append(
                {"line": r.line, "serial": r.serial_number, "missing": missing})

    # images in the ZIP that no row references
    report.unreferenced_images = sorted(present - referenced)

    # duplicate serial numbers
    seen: dict[str, int] = {}
    for r in rows:
        seen[r.serial_number] = seen.get(r.serial_number, 0) + 1
    report.duplicate_serials = sorted(s for s, n in seen.items() if s and n > 1)

    # declared values that won't parse
    for r in rows:
        av = r.fields.get("alcohol_content")
        if av and parse_abv(av).abv is None:
            report.unparseable_values.append(
                {"line": r.line, "serial": r.serial_number,
                 "field": "alcohol_content", "value": av})
        nc = r.fields.get("net_contents")
        if nc and parse_net_contents(nc).milliliters is None:
            report.unparseable_values.append(
                {"line": r.line, "serial": r.serial_number,
                 "field": "net_contents", "value": nc})

    return report


def blank_template() -> bytes:
    """A starter manifest, UTF-8 **with a BOM** so Excel opens it cleanly (design 3.4)."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(ALL_COLUMNS)
    w.writerow([
        "100001", "OLD TOM DISTILLERY", "Kentucky Straight Bourbon Whiskey",
        "spirits", "front_001.jpg;back_001.jpg",
        "", "", "45% Alc./Vol.", "750 mL", "Old Tom Distillery, LLC", "Bardstown, KY", "",
    ])
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")
