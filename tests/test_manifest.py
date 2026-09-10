"""Unit tests for CSV manifest parsing + pre-flight reconciliation (design 3.4)."""

from __future__ import annotations

from service.manifest import (
    REQUIRED_COLUMNS,
    blank_template,
    parse_manifest,
    reconcile,
)

_GOOD = (
    "serial_number,brand_name,class_type,commodity,alcohol_content,net_contents,image_files\n"
    "100001,OLD TOM DISTILLERY,Kentucky Straight Bourbon Whiskey,spirits,45% Alc./Vol.,750 mL,f1.jpg;b1.jpg\n"
    "100002,STONEBRIDGE CELLARS,California Chardonnay,wine,13% Alc./Vol.,750 mL,f2.jpg\n"
).encode()


def test_parses_rows_and_splits_image_files():
    rows, missing = parse_manifest(_GOOD)
    assert missing == []
    assert [r.serial_number for r in rows] == ["100001", "100002"]
    assert rows[0].image_names == ["f1.jpg", "b1.jpg"]
    assert rows[0].fields["commodity"] == "spirits"
    assert all(r.ok for r in rows)


def test_missing_required_column_is_reported():
    bad = _GOOD.replace(b"commodity,", b"")
    rows, missing = parse_manifest(bad)
    assert "commodity" in missing
    assert set(missing).issubset(set(REQUIRED_COLUMNS))
    assert rows == []


def test_bad_commodity_and_empty_fields_flag_the_row():
    csv = (
        "serial_number,brand_name,class_type,commodity,image_files\n"
        "100003,,Some Type,fizzy,f3.jpg\n"
    ).encode()
    rows, missing = parse_manifest(csv)
    assert missing == []
    assert not rows[0].ok
    joined = "; ".join(rows[0].row_errors)
    assert "brand_name is empty" in joined
    assert "fizzy" in joined


def test_reconcile_flags_missing_and_orphan_images():
    rows, _ = parse_manifest(_GOOD)
    report = reconcile(rows, ["f1.jpg", "b1.jpg", "extra.jpg"])  # f2.jpg absent
    assert report.rows_missing_images[0]["serial"] == "100002"
    assert report.rows_missing_images[0]["missing"] == ["f2.jpg"]
    assert report.unreferenced_images == ["extra.jpg"]
    assert report.can_proceed is True                # row 100001 is still fine
    assert [r.serial_number for r in report.ok_rows] == ["100001"]


def test_reconcile_flags_duplicate_serials():
    dup = _GOOD + b"100001,DUPE BRAND,Type,wine,,,f9.jpg\n"
    rows, _ = parse_manifest(dup)
    report = reconcile(rows, ["f1.jpg", "b1.jpg", "f2.jpg", "f9.jpg"])
    assert report.duplicate_serials == ["100001"]


def test_reconcile_flags_unparseable_declared_values():
    csv = (
        "serial_number,brand_name,class_type,commodity,alcohol_content,net_contents,image_files\n"
        "100010,BRAND,Type,spirits,TBD,a jug,f.jpg\n"
    ).encode()
    rows, _ = parse_manifest(csv)
    report = reconcile(rows, ["f.jpg"])
    fields = {u["field"] for u in report.unparseable_values}
    assert fields == {"alcohol_content", "net_contents"}


def test_no_ok_rows_means_cannot_proceed():
    rows, _ = parse_manifest(_GOOD)
    report = reconcile(rows, [])  # no images at all
    assert report.can_proceed is False
    assert report.ok_rows == []


def test_blank_template_has_a_bom_and_all_columns():
    tpl = blank_template()
    assert tpl.startswith(b"\xef\xbb\xbf")           # Excel-friendly BOM
    header = tpl.decode("utf-8-sig").splitlines()[0]
    for col in REQUIRED_COLUMNS:
        assert col in header
