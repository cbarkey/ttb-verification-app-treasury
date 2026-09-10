"""The vision fallback end to end, replayed from disk (CLAUDE.md 2.9).

`test_ai.py` covers the pieces with stubs. This runs the *real* path — the real
prompt, the real schema, the real request fingerprint — against committed
recordings, with no socket opened. That is the only way the wiring itself gets
tested: a stub client would happily accept a request the live API would reject.

The setup is deliberately the worst case in the design: **OCR unavailable**, so
every field is `UNREADABLE` and the fallback has everything to do. Which makes
this the sharpest possible test of the cap — if a model-sourced reading could
ever produce a PASS, a label with no OCR at all would come back approved.
"""

from __future__ import annotations

import pytest

from ttbverify.ai.client import CASSETTE_DIR, CassetteAi
from ttbverify.models import Commodity, LabelApplication, Outcome
from ttbverify.ocr import NullOcr
from ttbverify.pipeline import VISION_ATTRIBUTION, verify

FRONT = "fixtures/cassettes/images/lowlight_front.jpg"
BACK = "fixtures/cassettes/images/lowlight_back.jpg"


@pytest.fixture
def cassette_ai():
    ai = CassetteAi(CASSETTE_DIR)
    if not (CASSETTE_DIR / "vision_fields").is_dir():
        pytest.skip("cassettes not present")
    return ai


@pytest.fixture
def application():
    """`r12_lowlight` — the fixture whose producer line survived deskew unread,
    which is precisely the residual 2.9 hands to the model."""
    return LabelApplication(
        serial_number="200012",
        ttb_id="24RIC01000012",
        brand_name="RUSTY ANCHOR",
        class_type="Aged Caribbean Rum",
        commodity=Commodity.SPIRITS,
        alcohol_content="40% Alc./Vol.",
        net_contents="750 mL",
        applicant_name="Rusty Anchor Spirits",
        images=[{"path": FRONT, "role": "front"}, {"path": BACK, "role": "back"}],
    )


@pytest.fixture
def result(application, cassette_ai):
    return verify(application, NullOcr(), ai=cassette_ai)


class TestTheCapHoldsEndToEnd:
    def test_nothing_is_approved_even_though_every_reading_matched(self, result):
        """Every value in the cassette is the label's true text, so every
        comparison succeeds — and not one of them becomes a PASS."""
        from_model = [c for c in result.checks
                      if c.evidence.get("source") == "vision_model"]
        assert from_model, "expected the cassette to answer at least one field"
        assert all(c.outcome is Outcome.REVIEW for c in from_model)
        assert result.verdict is not Outcome.PASS

    def test_the_readings_are_carried_through(self, result):
        brand = next(c for c in result.checks if c.check_id == "brand")
        assert brand.observed == "RUSTY ANCHOR"
        assert brand.outcome is Outcome.REVIEW

    def test_numeric_fields_come_back_too(self, result):
        abv = next(c for c in result.checks if c.check_id == "abv")
        assert abv.outcome is Outcome.REVIEW
        assert "40" in (abv.observed or "")

    def test_the_second_image_is_only_asked_for_what_the_first_missed(self, result):
        """The front recording answers four fields and reports no producer — the
        bottler statement is the least legible thing on that photo. So the back
        label gets asked, and answers. Both halves of "one call per image, for
        what is still missing" run here against the real request builder."""
        producer = next(c for c in result.checks if c.check_id == "producer")
        assert producer.outcome is Outcome.REVIEW
        assert producer.observed == "Rusty Anchor Spirits"
        assert producer.image_index == 1  # read off the back, not the front
        assert producer.image_role == "back"

    def test_low_model_confidence_is_carried_but_not_acted_on(self, result):
        """The producer reading comes back at 0.58. It is recorded as evidence
        and changes nothing about the outcome — there is no confidence at which
        a model reading gets promoted."""
        producer = next(c for c in result.checks if c.check_id == "producer")
        assert producer.evidence["model_confidence"] < 0.6
        assert producer.outcome is Outcome.REVIEW


class TestAttribution:
    def test_every_model_touched_check_says_so(self, result):
        """An agent must always be able to tell which findings a model touched."""
        for check in result.checks:
            if check.evidence.get("source") != "vision_model":
                continue
            assert VISION_ATTRIBUTION in check.detail
            assert check.evidence["model"] == "claude-sonnet-5"
            assert check.evidence["capped_at_review"] is True

    def test_the_result_notes_that_a_model_was_consulted(self, result):
        assert any("vision model" in n.lower() for n in result.notes)
        assert any("never approved automatically" in n for n in result.notes)

    def test_no_overlay_box_is_invented_for_a_model_reading(self, result):
        """The model reports text, not pixels. Drawing a box would be a claim
        about where on the image it read something, which it never told us."""
        for check in result.checks:
            if check.evidence.get("source") == "vision_model":
                assert check.box is None


class TestNoNetwork:
    def test_the_same_label_with_no_model_configured_stays_unreadable(self, application):
        """Gate 4, stated as a comparison: with a key the agent gets a reading to
        confirm, without one they get "can't read it". Neither approves, so the
        firewall changes the evidence, never the verdict class."""
        from ttbverify.ai.client import NullAi

        degraded = verify(application, NullOcr(), ai=NullAi())
        assert all(c.outcome is not Outcome.PASS for c in degraded.checks)
        assert any(c.outcome is Outcome.UNREADABLE for c in degraded.checks)

    def test_an_unrecorded_request_degrades_like_a_firewall(self, application,
                                                            tmp_path):
        empty = CassetteAi(tmp_path)
        out = verify(application, NullOcr(), ai=empty)
        brand = next(c for c in out.checks if c.check_id == "brand")
        assert brand.outcome is Outcome.UNREADABLE
        assert any("Vision fallback unavailable" in n for n in out.notes)
