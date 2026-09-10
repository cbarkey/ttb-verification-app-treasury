"""Pipeline orchestration: degradation path, the vision cap, batch isolation."""

import pytest

from ttbverify.ai.client import NullAi
from ttbverify.models import Commodity, LabelApplication, Outcome
from ttbverify.ocr import NullOcr
from ttbverify.pipeline import verify, verify_batch


def _app(images, **kw):
    base = {
        "serial_number": "1", "brand_name": "OLD TOM DISTILLERY",
        "class_type": "Kentucky Straight Bourbon Whiskey", "commodity": Commodity.SPIRITS,
        "alcohol_content": "45% Alc./Vol.", "net_contents": "750 mL",
        "applicant_name": "Old Tom Distillery, LLC", "images": images,
    }
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


class TestVisionFallbackIsCappedAtReview:
    """CLAUDE.md 2.9: a model-sourced reading can only ever produce REVIEW.

    Not PASS, and not FAIL either. These two tests are the whole safety argument
    for letting a nondeterministic component near a compliance tool, so they
    assert the cap directly rather than through a verdict that happens to agree.
    """

    def test_null_client_is_unavailable_and_inert(self):
        ai = NullAi()
        assert ai.available is False
        assert ai.complete(None if False else _dummy_request()).ok is False

    def test_a_reading_that_matches_is_still_only_review(self, a_real_image):
        """The tempting bug: the text matches, so pass it. That would put "zero
        false approvals" at the mercy of a model."""
        result = verify(
            _app([{"path": a_real_image, "role": "front"}]),
            NullOcr(), ai=_ai_reading("brand", "OLD TOM DISTILLERY"),
        )
        brand = next(c for c in result.checks if c.check_id == "brand")
        assert brand.outcome is Outcome.REVIEW
        assert brand.observed == "OLD TOM DISTILLERY"
        assert brand.evidence.get("source") == "vision_model"
        assert brand.evidence.get("capped_at_review") is True

    def test_a_reading_that_mismatches_is_also_only_review(self, a_real_image):
        """The other half: the model does not get to reject a label either. It
        did not read this reliably enough for OCR to manage it, so its verdict is
        a question for a human, in both directions."""
        result = verify(
            _app([{"path": a_real_image, "role": "front"}]),
            NullOcr(), ai=_ai_reading("brand", "TOTALLY DIFFERENT BRAND"),
        )
        brand = next(c for c in result.checks if c.check_id == "brand")
        assert brand.outcome is Outcome.REVIEW

    def test_the_comparison_still_runs_and_is_shown(self, a_real_image):
        """Advisory, not decisive: the agent gets told what the rule would have
        said, which is more useful than a bare string."""
        result = verify(
            _app([{"path": a_real_image, "role": "front"}]),
            NullOcr(), ai=_ai_reading("brand", "old tom distillery"),
        )
        brand = next(c for c in result.checks if c.check_id == "brand")
        assert "capitalization" in brand.detail.lower()
        assert "read by vision model" in brand.detail

    def test_a_failing_client_leaves_the_field_unreadable(self, a_real_image):
        """Timeout, firewall, malformed reply, no key — all the same path, and
        none of them upgrade anything (design 2.4 failure table)."""
        class Failing:
            available = True
            model = "x"

            def complete(self, request):
                from ttbverify.ai.client import AiResult
                return AiResult.failed("timed out")

        result = verify(
            _app([{"path": a_real_image, "role": "front"}]), NullOcr(), ai=Failing(),
        )
        brand = next(c for c in result.checks if c.check_id == "brand")
        assert brand.outcome is Outcome.UNREADABLE
        assert any("Vision fallback unavailable" in n for n in result.notes)

    def test_one_call_per_image_not_one_per_field(self, a_real_image):
        """2.9: the model is looking at the whole label either way. Asking six
        times costs six round trips inside a 5 s budget for no more information."""
        requests = []

        class Counting:
            available = True
            model = "stub-model"

            def complete(self, request):
                requests.append(request)
                from ttbverify.ai.client import AiResult
                return AiResult(ok=True, source="stub", model=self.model, data={
                    "fields": [
                        {"name": "brand", "text": "OLD TOM DISTILLERY"},
                        {"name": "class_type", "text": "Kentucky Straight Bourbon Whiskey"},
                        {"name": "abv", "text": "45% Alc./Vol."},
                    ]
                })

        result = verify(
            _app([{"path": a_real_image, "role": "front"}]), NullOcr(), ai=Counting(),
        )
        assert len(requests) == 1
        assert {c.check_id for c in result.checks
                if c.evidence.get("source") == "vision_model"} == {
            "brand", "class_type", "abv"}

    def test_a_second_image_is_only_consulted_for_what_is_still_missing(
            self, a_real_image):
        asked = []

        class PerImage:
            available = True
            model = "stub-model"

            def complete(self, request):
                asked.append(request.prompt)
                from ttbverify.ai.client import AiResult
                fields = ([{"name": "brand", "text": "OLD TOM DISTILLERY"}]
                          if len(asked) == 1 else
                          [{"name": "producer", "text": "Old Tom Distillery, LLC"}])
                return AiResult(ok=True, source="stub", model=self.model,
                                data={"fields": fields})

        verify(
            _app([{"path": a_real_image, "role": "front"},
                  {"path": a_real_image, "role": "back"}]),
            NullOcr(), ai=PerImage(),
        )
        assert len(asked) == 2
        assert "brand" in asked[0]
        assert "brand" not in asked[1]  # already answered by the front

    def test_numeric_fields_are_in_scope(self, a_real_image):
        """ABV and net contents were out of scope in the dormant version. A
        photo too dark to read a brand is too dark to read an ABV."""
        result = verify(
            _app([{"path": a_real_image, "role": "front"}]),
            NullOcr(), ai=_ai_reading("abv", "45% Alc./Vol. (90 Proof)"),
        )
        abv = next(c for c in result.checks if c.check_id == "abv")
        assert abv.outcome is Outcome.REVIEW
        assert "45" in abv.detail


def _dummy_request():
    from ttbverify.ai.client import AiRequest
    return AiRequest(kind="vision_fields", prompt="", schema={"type": "object"})


def _ai_reading(check_id: str, text: str):
    """A client that returns one reading, in the shape the real schema produces."""
    from ttbverify.ai.client import AiResult

    class Stub:
        available = True
        model = "stub-model"

        def complete(self, request):
            return AiResult(ok=True, source="stub", model=self.model, data={
                "fields": [{"name": check_id, "text": text, "confidence": 0.82}]
            })

    return Stub()


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
