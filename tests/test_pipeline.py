"""Pipeline orchestration: degradation path, VLM interface, batch isolation."""

import pytest

from ttbverify.models import Commodity, LabelApplication, Outcome
from ttbverify.ocr import NullOcr
from ttbverify.pipeline import verify, verify_batch
from ttbverify.vlm import NullVlm, VlmField


def _app(images, **kw):
    base = dict(
        serial_number="1", brand_name="OLD TOM DISTILLERY",
        class_type="Kentucky Straight Bourbon Whiskey", commodity=Commodity.SPIRITS,
        alcohol_content="45% Alc./Vol.", net_contents="750 mL",
        applicant_name="Old Tom Distillery, LLC", images=images,
    )
    base.update(kw)
    return LabelApplication(**base)


@pytest.fixture
def a_real_image(tmp_path):
    from PIL import Image

    p = tmp_path / "label.png"
    Image.new("RGB", (400, 300), "white").save(p)
    return str(p)


class TestDegradation:
    def test_null_ocr_never_passes_anything(self, a_real_image):
        result = verify(_app([{"path": a_real_image, "role": "front"}]), NullOcr())
        assert result.ocr_available is False
        assert all(c.outcome is not Outcome.PASS for c in result.checks)
        assert result.verdict in (Outcome.UNREADABLE, Outcome.FAIL)

    def test_missing_image_file_does_not_raise(self, tmp_path):
        result = verify(_app([{"path": str(tmp_path / "nope.png"), "role": "front"}]),
                        NullOcr())
        assert result is not None
        assert any("nope.png" in n for n in result.notes)

    def test_latency_is_measured_and_reported(self, a_real_image):
        result = verify(_app([{"path": a_real_image, "role": "front"}]), NullOcr())
        assert result.elapsed_ms >= 0
        assert "ocr" in result.stage_ms


class TestVlmInterface:
    def test_null_vlm_is_unavailable_and_inert(self):
        vlm = NullVlm()
        assert vlm.available is False
        assert vlm.read_fields("x.png", ["brand"]) == {}

    def test_fallback_runs_comparison_not_blind_pass(self, a_real_image, monkeypatch):
        """A VLM-supplied value still goes through the ladder (design 2.4)."""

        class FakeVlm:
            available = True
            name = "fake"

            def read_fields(self, image_path, fields):
                return {"brand": VlmField("brand", "OLD TOM DISTILLERY", 0.9)}

        result = verify(
            _app([{"path": a_real_image, "role": "front"}]),
            NullOcr(), vlm=FakeVlm(),
        )
        brand = next(c for c in result.checks if c.check_id == "brand")
        assert brand.outcome is Outcome.PASS
        assert brand.evidence.get("source") == "vlm"

    def test_fallback_mismatch_still_fails(self, a_real_image):
        class FakeVlm:
            available = True
            name = "fake"

            def read_fields(self, image_path, fields):
                return {"brand": VlmField("brand", "TOTALLY DIFFERENT BRAND", 0.9)}

        result = verify(
            _app([{"path": a_real_image, "role": "front"}]),
            NullOcr(), vlm=FakeVlm(),
        )
        brand = next(c for c in result.checks if c.check_id == "brand")
        assert brand.outcome is Outcome.FAIL


class TestBatchIsolation:
    def test_one_bad_item_does_not_sink_the_batch(self, a_real_image, tmp_path):
        apps = [
            _app([{"path": a_real_image, "role": "front"}], serial_number="ok1"),
            _app([{"path": str(tmp_path / "missing.png"), "role": "front"}],
                 serial_number="bad"),
            _app([{"path": a_real_image, "role": "front"}], serial_number="ok2"),
        ]
        results = dict(verify_batch(apps, NullOcr()))
        assert set(results) == {"ok1", "bad", "ok2"}
        assert all(not isinstance(r, Exception) for r in results.values())
