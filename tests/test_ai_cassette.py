"""The vision fallback end to end, replayed from disk (DESIGN.md 2.9).

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

    def test_the_model_reads_the_whole_bottler_statement(self, result):
        """What the live model actually returned, rather than a tidied version.

        Asked for the producer, it gave the entire sentence it is printed in —
        `Distilled and bottled by Rusty Anchor Spirits, Key West, FL` — not the
        bare name. That is a *reading*, which is what was asked for, and it is
        exactly why a reading is capped at REVIEW rather than compared and
        trusted: the agent confirms it against the crop in one glance.
        """
        producer = next(c for c in result.checks if c.check_id == "producer")
        assert producer.outcome is Outcome.REVIEW
        assert "Rusty Anchor Spirits" in (producer.observed or "")

    def test_high_model_confidence_is_carried_but_not_acted_on(self, result):
        """The sharpest form of the cap, and it is real data.

        Every reading in this recording came back at 0.9 or above — the brand at
        0.98 — and every one of them is still REVIEW. There is no confidence at
        which a model reading gets promoted, which is the whole reason a
        nondeterministic component is allowed near this at all.
        """
        from_model = [c for c in result.checks
                      if c.evidence.get("source") == "vision_model"]
        assert from_model
        assert all(c.evidence["model_confidence"] >= 0.9 for c in from_model)
        assert all(c.outcome is Outcome.REVIEW for c in from_model)


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
