"""Batch endpoint contract tests: ZIP -> pre-flight -> process -> review -> export.

Builds a ZIP in memory from clean-corpus fixture images. Needs tesseract.
"""

from __future__ import annotations

import io
import time
import zipfile

import pytest

from fixtures import load_cases

pytestmark = pytest.mark.corpus


@pytest.fixture(scope="module")
def client(tesseract_or_skip):
    from fastapi.testclient import TestClient

    from service.app import create_app

    return TestClient(create_app())


@pytest.fixture(scope="module")
def cases():
    return {c["case_id"]: c for c in load_cases()}


def _zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _img(case: dict, idx: int = 0) -> bytes:
    with open(case["application"]["images"][idx]["path"], "rb") as fh:
        return fh.read()


def _manifest(lines: list[str]) -> bytes:
    header = ("serial_number,brand_name,class_type,commodity,"
              "alcohol_content,net_contents,image_files")
    return ("\n".join([header, *lines]) + "\n").encode()


@pytest.fixture(scope="module")
def good_batch(client, cases):
    clean = cases["clean_spirits"]
    mismatch = cases["brand_mismatch"]
    archive = _zip({
        "manifest.csv": _manifest([
            "100001,OLD TOM DISTILLERY,Kentucky Straight Bourbon Whiskey,spirits,"
            "45% Alc./Vol.,750 mL,a_front.png;a_back.png",
            "100006,OLD TOM DISTILLERY,Spiced Rum,spirits,40% Alc./Vol.,750 mL,"
            "b_front.png;b_back.png",
        ]),
        "a_front.png": _img(clean, 0),
        "a_back.png": _img(clean, 1),
        "b_front.png": _img(mismatch, 0),
        "b_back.png": _img(mismatch, 1),
    })
    r = client.post("/api/verify/batch",
                    files={"archive": ("batch.zip", archive, "application/zip")})
    assert r.status_code == 200
    return r.json()


def test_preflight_reports_a_clean_manifest(good_batch):
    pf = good_batch["preflight"]
    assert pf["can_proceed"] is True
    assert pf["ok_count"] == 2
    assert pf["blocked_count"] == 0
    assert good_batch["state"] == "ready"


def test_preflight_flags_missing_images_and_orphans(client, cases):
    archive = _zip({
        "manifest.csv": _manifest([
            "200001,BRAND A,Type,wine,,,x_front.png",         # image absent
            "200002,BRAND B,Type,wine,,,y_front.png",
        ]),
        "y_front.png": _img(cases["clean_wine"], 0),
        "loose.png": _img(cases["clean_wine"], 1),            # orphan
    })
    pf = client.post(
        "/api/verify/batch",
        files={"archive": ("b.zip", archive, "application/zip")},
    ).json()["preflight"]
    assert pf["rows_missing_images"][0]["serial"] == "200001"
    assert "loose.png" in pf["unreferenced_images"]
    assert pf["ok_count"] == 1


def test_missing_required_column_blocks_the_batch(client, cases):
    archive = _zip({
        "manifest.csv": (b"serial_number,brand_name,class_type,image_files\n"
                         b"1,B,T,f.png\n"),
        "f.png": _img(cases["clean_beer"], 0),
    })
    body = client.post(
        "/api/verify/batch",
        files={"archive": ("b.zip", archive, "application/zip")},
    ).json()
    assert "commodity" in body["preflight"]["missing_columns"]
    assert body["preflight"]["can_proceed"] is False


def test_process_streams_and_sorts_exceptions_first(client, good_batch):
    bid = good_batch["batch_id"]
    assert client.post(f"/api/verify/batch/{bid}/start").status_code == 202

    deadline = time.time() + 60
    while time.time() < deadline:
        state = client.get(f"/api/verify/batch/{bid}").json()
        if state["state"] == "complete":
            break
        time.sleep(0.3)
    assert state["state"] == "complete"
    assert state["progress"] == {"done": 2, "total": 2, "state": "complete"}

    verdicts = [r["verdict"] for r in state["rows"]]
    assert verdicts[0] == "FAIL"                 # brand_mismatch sorted to the top
    assert "100006" in state["exception_serials"]
    assert "100001" not in state["exception_serials"]


def test_row_review_and_finalize(client, good_batch):
    bid = good_batch["batch_id"]
    row = client.get(f"/api/verify/batch/{bid}/rows/100006").json()
    assert row["verdict"] == "FAIL"
    assert any(c["check_id"] == "brand" and c["outcome"] == "FAIL"
               for c in row["result"]["checks"])

    img = client.get(row["images"][0]["url"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"

    fin = client.post(f"/api/verify/batch/{bid}/rows/100006/finalize",
                      json={"action": "reject"})
    assert fin.status_code == 200
    assert client.get(f"/api/verify/batch/{bid}/rows/100006").json()["finalized"] == "reject"


def test_export_csv_has_bom_and_rows(client, good_batch):
    bid = good_batch["batch_id"]
    r = client.get(f"/api/verify/batch/{bid}/export.csv")
    assert r.status_code == 200
    assert r.content.startswith(b"\xef\xbb\xbf")
    text = r.content.decode("utf-8-sig")
    assert "serial_number" in text.splitlines()[0]
    assert "100001" in text and "100006" in text


def test_events_stream_emits_rows_and_done(client, cases):
    archive = _zip({
        "manifest.csv": _manifest([
            "300001,IRON RIVER BREWING,India Pale Ale,malt,6.2% Alc./Vol.,12 fl oz,f.png",
        ]),
        "f.png": _img(cases["clean_beer"], 0),
    })
    bid = client.post("/api/verify/batch",
                      files={"archive": ("b.zip", archive, "application/zip")}).json()["batch_id"]
    client.post(f"/api/verify/batch/{bid}/start")
    seen_events = set()
    with client.stream("GET", f"/api/verify/batch/{bid}/events") as resp:
        for line in resp.iter_lines():
            if line.startswith("event:"):
                seen_events.add(line.split(":", 1)[1].strip())
            if "event: done" in line or (line.startswith("event:") and line.endswith("done")):
                break
    assert "row" in seen_events and "done" in seen_events


def test_bad_zip_is_rejected(client):
    r = client.post("/api/verify/batch",
                    files={"archive": ("b.zip", b"not a zip", "application/zip")})
    assert r.status_code == 422
