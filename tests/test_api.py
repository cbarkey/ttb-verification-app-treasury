"""Contract tests for the API envelope (design 2.6 'Contract' layer).

Uses the real pipeline; needs the tesseract binary, so these skip without it.
"""

from __future__ import annotations

import json

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


def _post_verify(client, case):
    fields = {k: v for k, v in case["application"].items() if k != "images"}
    files = [
        ("images", (f"img{i}.png", open(im["path"], "rb"), "image/png"))
        for i, im in enumerate(case["application"]["images"])
    ]
    return client.post("/api/verify", data={"application": json.dumps(fields)}, files=files)


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["ocr"] == "available"


def test_verify_returns_session_result_and_images(client, cases):
    r = _post_verify(client, cases["clean_spirits"])
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"]
    assert body["result"]["verdict"] in ("PASS", "REVIEW", "FAIL", "UNREADABLE")
    assert len(body["images"]) == 2
    assert body["images"][0]["role"] == "front"
    # every check that located something carries a box on a real page
    for c in body["result"]["checks"]:
        if c["box"] is not None:
            assert c["image_index"] in (0, 1)
            assert c["box"]["width"] > 0 and c["box"]["height"] > 0


def test_images_are_served_from_the_session(client, cases):
    body = _post_verify(client, cases["clean_wine"]).json()
    got = client.get(body["images"][1]["url"])
    assert got.status_code == 200
    assert got.headers["content-type"] == "image/png"
    assert len(got.content) > 100


def test_review_decision_flow_unlocks_finalize(client, cases):
    body = _post_verify(client, cases["abv_near_miss"]).json()
    sid = body["session_id"]
    review_ids = [c["check_id"] for c in body["result"]["checks"]
                  if c["outcome"] == "REVIEW"]
    assert "abv" in review_ids and "warn_bold" in review_ids

    state = client.get(f"/api/sessions/{sid}").json()
    assert state["can_finalize"] is False
    assert sorted(state["unresolved_review_ids"]) == sorted(review_ids)

    for i, cid in enumerate(review_ids):
        resp = client.post(f"/api/sessions/{sid}/decisions",
                           json={"check_id": cid, "decision": "accept"}).json()
        last = i == len(review_ids) - 1
        assert resp["can_finalize"] is last

    fin = client.post(f"/api/sessions/{sid}/finalize", json={"action": "approve"})
    assert fin.status_code == 200
    assert fin.json()["action"] == "approve"
    assert client.get(f"/api/sessions/{sid}").json()["finalized"] == "approve"


def test_cannot_resolve_a_non_review_check(client, cases):
    body = _post_verify(client, cases["abv_mismatch"]).json()
    sid = body["session_id"]
    r = client.post(f"/api/sessions/{sid}/decisions",
                    json={"check_id": "abv", "decision": "accept"})
    assert r.status_code == 409


def test_verify_rejects_bad_application_json(client, cases):
    files = [("images", ("x.png", open(cases["clean_beer"]["application"]["images"][0]["path"], "rb"), "image/png"))]
    r = client.post("/api/verify", data={"application": "{not json"}, files=files)
    assert r.status_code == 422


def test_verify_rejects_missing_required_field(client, cases):
    r = client.post(
        "/api/verify",
        data={"application": json.dumps({"brand_name": "X", "class_type": "Y",
                                         "commodity": "wine"})},  # no serial_number
        files=[("images", ("x.png", open(cases["clean_beer"]["application"]["images"][0]["path"], "rb"), "image/png"))],
    )
    assert r.status_code == 422


def test_unknown_session_is_404(client):
    assert client.get("/api/sessions/nope").status_code == 404
    assert client.get("/api/sessions/nope/images/0").status_code == 404
