"""Gate 3 (CLAUDE.md 2.9): the triage brief changes nothing but the prose.

The brief sits *above* the queue table and the table stays the record. That is
easy to say and easy to break — a summariser that reorders rows, drops one, or
sneaks a hint into a cell has quietly made a model part of the record. So this
asserts the strong version: run the same batch twice, once with a model that
answers and once with none, and require the rows and the CSV export to be
identical.

Runs against the batch machinery directly rather than the HTTP surface: the
property is about `Batch`, and building a ZIP would only add tesseract as a
dependency of a test that has nothing to do with OCR.
"""

from __future__ import annotations

import pytest

from service.batch import Batch, BatchRow
from service.manifest import PreflightReport
from ttbverify.ai.client import AiResult, NullAi, validate
from ttbverify.models import CheckResult, Outcome, VerificationResult


class AnsweringAi:
    available = True
    model = "stub-model"

    def complete(self, request):
        return AiResult(ok=True, model=self.model, source="stub", data=validate({
            "headline": "Two of the three exceptions are the same ABV mismatch.",
            "groups": [{"label": "ABV mismatch", "count": 2,
                        "detail": "Same declared 45% against a 40% label."}],
            "watch_outs": ["Serial 3 needs a fresh photograph."],
        }, request.schema))


def _row(serial: str, line: int, checks: list[CheckResult]) -> BatchRow:
    row = BatchRow(serial_number=serial, line=line,
                   fields={"brand_name": f"Brand {serial}"}, images=[])
    row.status = "done"
    row.result = VerificationResult(application_key=serial, checks=checks,
                                    elapsed_ms=100)
    return row


@pytest.fixture
def batch() -> Batch:
    return Batch(id="b1", preflight=PreflightReport(rows=[]), rows=[
        _row("1", 1, [CheckResult("brand", "Brand name", Outcome.PASS,
                                  declared="A", observed="A")]),
        _row("2", 2, [CheckResult("abv", "Alcohol content", Outcome.FAIL,
                                  declared="45%", observed="40%")]),
        _row("3", 3, [CheckResult("brand", "Brand name", Outcome.UNREADABLE)]),
    ])


def _snapshot(batch: Batch) -> dict:
    """Everything about the batch except the brief itself."""
    payload = batch.to_dict()
    payload.pop("brief", None)
    return payload


def test_the_rows_are_identical_with_and_without_a_brief(batch):
    from ttbverify.ai import brief as triage

    before = _snapshot(batch)
    result, error = triage.summarize(AnsweringAi(), batch.rows_for_brief())
    batch.brief = result.to_dict() if result else None
    assert error is None and batch.brief is not None
    assert _snapshot(batch) == before


def test_the_queue_order_is_not_influenced_by_the_brief(batch):
    from ttbverify.ai import brief as triage

    order_before = [r.serial_number for r in batch.queue_order()]
    result, _ = triage.summarize(AnsweringAi(), batch.rows_for_brief())
    batch.brief = result.to_dict()
    assert [r.serial_number for r in batch.queue_order()] == order_before
    assert batch.exception_serials() == ["2", "3"]


def test_no_model_means_no_brief_and_an_otherwise_identical_batch(batch):
    from ttbverify.ai import brief as triage

    before = _snapshot(batch)
    result, error = triage.summarize(NullAi(), batch.rows_for_brief())
    assert result is None and error is None
    assert batch.to_dict()["brief"] is None
    assert _snapshot(batch) == before


def test_the_brief_never_sees_the_images(batch):
    """Structured findings leave the process; label photographs do not."""
    import json

    payload = json.dumps(batch.rows_for_brief())
    assert "images" not in payload
    assert "\\u00ff" not in payload  # no smuggled binary


def test_the_brief_is_labelled_as_generated_for_the_ui(batch):
    from ttbverify.ai import brief as triage

    result, _ = triage.summarize(AnsweringAi(), batch.rows_for_brief())
    payload = result.to_dict()
    assert payload["generated"] is True and payload["advisory"] is True
    assert payload["model"] == "stub-model"
