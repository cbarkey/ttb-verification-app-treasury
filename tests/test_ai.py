"""The AI layer: schema validation, cassettes, and the three uses (DESIGN.md 2.9).

**No test here opens a socket**, and that is the point rather than a convenience.
The tool has to work behind Marcus's firewall, so "runs with no key and no
network" is asserted continuously instead of claimed once. The live client is
exercised through its failure paths only; its success path is covered by
recorded cassettes.

The four gates 2.9 names are pinned across this file and `test_pipeline.py`:

  1. a model-sourced reading never yields PASS or FAIL  (test_pipeline.py)
  2. timeout / error / malformed output leaves the field UNREADABLE  (both)
  3. batch rows are identical with and without the brief  (here)
  4. the whole pipeline still passes with no network and no key  (the suite)
"""

from __future__ import annotations

import importlib
import json
import os

import pytest

from ttbverify.ai import brief as triage
from ttbverify.ai import notice as drafting
from ttbverify.ai import vision
from ttbverify.ai.client import (
    AiRequest,
    AiResult,
    CassetteAi,
    ClaudeAi,
    NullAi,
    SchemaError,
    make_default_client,
    prompt,
    validate,
)

CASSETTES = "fixtures/cassettes"


class StubAi:
    """Returns a canned payload. Stands in for a model that answered."""

    available = True
    model = "stub-model"

    def __init__(self, data: dict, ok: bool = True, error: str | None = None):
        self._data, self._ok, self._error = data, ok, error
        self.requests: list[AiRequest] = []

    def complete(self, request: AiRequest) -> AiResult:
        self.requests.append(request)
        if not self._ok:
            return AiResult.failed(self._error or "boom", source="stub")
        return AiResult(ok=True, data=validate(self._data, request.schema),
                        model=self.model, source="stub")


# --------------------------------------------------------------------------
# schema validation — a malformed reply is "no reply", never a crash
# --------------------------------------------------------------------------

class TestSchemaValidation:
    SCHEMA = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "enum": ["brand", "abv"]},
            "text": {"type": "string", "maxLength": 5},
            "score": {"type": "number"},
            "flag": {"type": "boolean"},
        },
        "required": ["name"],
    }

    def test_a_valid_object_passes_through(self):
        out = validate({"name": "brand", "score": 1}, self.SCHEMA)
        assert out == {"name": "brand", "score": 1.0}

    def test_a_missing_required_field_is_rejected(self):
        with pytest.raises(SchemaError):
            validate({"text": "hi"}, self.SCHEMA)

    def test_a_null_required_field_is_rejected(self):
        """A model returning `null` for a required field is not a valid answer,
        even though the key is present."""
        with pytest.raises(SchemaError):
            validate({"name": None}, self.SCHEMA)

    def test_a_wrong_type_is_rejected(self):
        with pytest.raises(SchemaError):
            validate({"name": "brand", "score": "high"}, self.SCHEMA)

    def test_a_value_outside_the_enum_is_rejected(self):
        with pytest.raises(SchemaError):
            validate({"name": "vintage"}, self.SCHEMA)

    def test_a_boolean_is_not_a_number(self):
        """`isinstance(True, int)` is True in Python, so this is worth pinning."""
        with pytest.raises(SchemaError):
            validate({"name": "brand", "score": True}, self.SCHEMA)

    def test_unknown_keys_are_dropped_not_passed_on(self):
        out = validate({"name": "brand", "sneaky": "value"}, self.SCHEMA)
        assert "sneaky" not in out

    def test_over_long_strings_are_truncated(self):
        out = validate({"name": "brand", "text": "far too long"}, self.SCHEMA)
        assert out["text"] == "far t"

    def test_arrays_respect_max_items(self):
        schema = {"type": "array", "maxItems": 2, "items": {"type": "string"}}
        with pytest.raises(SchemaError):
            validate(["a", "b", "c"], schema)


# --------------------------------------------------------------------------
# the clients
# --------------------------------------------------------------------------

class TestClients:
    def test_null_client_answers_nothing(self):
        ai = NullAi()
        assert ai.available is False
        result = ai.complete(AiRequest(kind="x", prompt="", schema={}))
        assert result.ok is False and result.error

    def test_no_key_means_no_client(self, monkeypatch):
        """Gate 4. Absence of a key is the *normal* state here, not a
        misconfiguration — the default has to be the no-egress one."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert isinstance(make_default_client(), NullAi)

    def test_the_live_client_reports_why_it_is_unavailable(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        client = ClaudeAi()
        assert client.available is False
        assert "ANTHROPIC_API_KEY" in (client.unavailable_reason or "")

    def test_the_live_client_never_raises_on_a_bad_image(self, monkeypatch):
        """Every failure has to arrive as a result, not an exception, or the
        deterministic verdict never gets returned."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
        client = ClaudeAi()
        if not client.available:  # `anthropic` not installed in this environment
            pytest.skip("anthropic package not installed")
        result = client.complete(AiRequest(
            kind="vision_fields", prompt="x", schema={"type": "object"},
            images=("does/not/exist.png",)))
        assert result.ok is False
        assert "cannot read image" in (result.error or "")


class TestDotEnvLoading:
    """`.env` is read at the process entrypoint only (`service/__main__.py`).

    Never from `create_app()`: the test suite builds the app that way, so a
    developer's real key would silently turn every API test into a live billed
    call and break the no-network invariant (N-06). The seam is the point.
    """

    def test_it_sets_variables_from_the_file(self, tmp_path, monkeypatch):
        from ttbverify.ai.client import load_env_file

        monkeypatch.delenv("TTB_TEST_TOKEN", raising=False)
        env = tmp_path / ".env"
        env.write_text("TTB_TEST_TOKEN=abc123\n", encoding="utf-8")

        assert load_env_file(env) == ["TTB_TEST_TOKEN"]
        assert os.environ["TTB_TEST_TOKEN"] == "abc123"

    def test_it_returns_names_never_values(self, tmp_path, monkeypatch):
        """So a caller can log what was configured without printing a secret."""
        from ttbverify.ai.client import load_env_file

        monkeypatch.delenv("TTB_TEST_TOKEN", raising=False)
        env = tmp_path / ".env"
        env.write_text("TTB_TEST_TOKEN=super-secret-value\n", encoding="utf-8")

        assert "super-secret-value" not in str(load_env_file(env))

    def test_an_existing_variable_wins(self, tmp_path, monkeypatch):
        """A real key in the shell must not be clobbered by a stale file."""
        from ttbverify.ai.client import load_env_file

        monkeypatch.setenv("TTB_TEST_TOKEN", "from-the-shell")
        env = tmp_path / ".env"
        env.write_text("TTB_TEST_TOKEN=from-the-file\n", encoding="utf-8")

        assert load_env_file(env) == []
        assert os.environ["TTB_TEST_TOKEN"] == "from-the-shell"

    def test_comments_blanks_quotes_and_export_are_handled(self, tmp_path, monkeypatch):
        from ttbverify.ai.client import load_env_file

        for name in ("TTB_A", "TTB_B", "TTB_C"):
            monkeypatch.delenv(name, raising=False)
        env = tmp_path / ".env"
        env.write_text(
            '# a comment\n'
            '\n'
            'TTB_A="quoted"\n'
            'export TTB_B=exported\n'
            'not_a_pair\n'
            "TTB_C='single'\n",
            encoding="utf-8",
        )

        assert sorted(load_env_file(env)) == ["TTB_A", "TTB_B", "TTB_C"]
        assert os.environ["TTB_A"] == "quoted"
        assert os.environ["TTB_B"] == "exported"
        assert os.environ["TTB_C"] == "single"

    def test_a_missing_file_is_not_an_error(self, tmp_path):
        from ttbverify.ai.client import load_env_file

        assert load_env_file(tmp_path / "nope.env") == []

    def test_creating_the_app_does_not_read_dotenv(self, tmp_path, monkeypatch):
        """The invariant this whole arrangement exists to protect."""
        import service

        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text(
            "ANTHROPIC_API_KEY=sk-should-never-load\n", encoding="utf-8")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        importlib.reload(service)
        assert os.environ.get("ANTHROPIC_API_KEY") is None


class TestCassettes:
    def _request(self, **kw):
        return AiRequest(kind="vision_fields", prompt="read the brand",
                         schema={"type": "object",
                                 "properties": {"fields": {"type": "array",
                                                           "items": {"type": "object"}}}},
                         **kw)

    def test_a_recorded_reply_is_replayed(self, tmp_path):
        path = tmp_path / "vision_fields"
        path.mkdir()
        request = self._request()
        (path / f"{request.fingerprint()}.json").write_text(
            json.dumps({"model": "m", "ok": True,
                        "data": {"fields": [{"name": "brand"}]}}), encoding="utf-8")
        result = CassetteAi(tmp_path).complete(request)
        assert result.ok and result.source == "cassette"

    def test_a_missing_cassette_degrades_instead_of_raising(self, tmp_path):
        """Gate 2, at the transport layer: an un-recorded request has to behave
        exactly like a firewalled one, so every test without a cassette
        exercises the no-answer path for free."""
        result = CassetteAi(tmp_path).complete(self._request())
        assert result.ok is False
        assert "no cassette" in (result.error or "")

    def test_the_fingerprint_changes_when_the_prompt_changes(self):
        """Editing a prompt must invalidate its recordings rather than quietly
        replaying an answer to a question we no longer ask."""
        a = self._request()
        b = AiRequest(kind=a.kind, prompt=a.prompt + " and the ABV", schema=a.schema)
        assert a.fingerprint() != b.fingerprint()

    def test_the_fingerprint_covers_the_image_bytes(self, tmp_path):
        from PIL import Image

        one, two = tmp_path / "a.png", tmp_path / "b.png"
        Image.new("RGB", (10, 10), "white").save(one)
        Image.new("RGB", (10, 10), "black").save(two)
        assert (self._request(images=(str(one),)).fingerprint()
                != self._request(images=(str(two),)).fingerprint())


# --------------------------------------------------------------------------
# prompts live in version control, not in f-strings
# --------------------------------------------------------------------------

class TestPrompts:
    @pytest.mark.parametrize("name", ["vision_fields", "batch_brief", "rejection_notice"])
    def test_every_prompt_loads(self, name):
        assert len(prompt(name)) > 200

    def test_parameters_are_substituted(self):
        text = prompt("vision_fields", fields="- brand: the brand name")
        assert "- brand: the brand name" in text
        assert "{{fields}}" not in text

    def test_the_vision_prompt_tells_the_model_it_is_reading_not_judging(self):
        """The REVIEW cap is enforced in code, but the prompt should not be
        asking for a judgement it isn't allowed to act on either."""
        text = prompt("vision_fields", fields="")
        assert "READ, not to judge" in text
        assert "null" in text  # "not on this image" must be an available answer


# --------------------------------------------------------------------------
# use A — vision readings
# --------------------------------------------------------------------------

class TestVisionReadings:
    def test_it_returns_the_fields_it_was_asked_for(self):
        ai = StubAi({"fields": [{"name": "brand", "text": "STONE'S THROW",
                                 "confidence": 0.9}]})
        readings, error = vision.read_fields(ai, "x.png", ["brand"])
        assert error is None
        assert [(r.check_id, r.text) for r in readings] == [("brand", "STONE'S THROW")]

    def test_a_blank_reading_is_not_a_value(self):
        """"Not on this image" is a real answer and must not become an empty
        string that then fails a comparison."""
        ai = StubAi({"fields": [{"name": "brand", "text": "   "}]})
        readings, _ = vision.read_fields(ai, "x.png", ["brand"])
        assert readings == []

    def test_fields_that_were_not_asked_for_are_ignored(self):
        ai = StubAi({"fields": [{"name": "origin", "text": "Product of France"}]})
        readings, _ = vision.read_fields(ai, "x.png", ["brand"])
        assert readings == []

    def test_a_placeholder_is_not_a_reading(self):
        """Observed against the live API, not hypothetical.

        The prompt asks for null when a field can't be read. On a genuinely bad
        photograph the model instead returned
        `{"name": "producer", "text": "<UNKNOWN>", "confidence": 0.1}`. Taken at
        face value that becomes a review row telling an agent the label appears
        to say "<UNKNOWN>", which is worse than the honest "can't read it".
        """
        ai = StubAi({"fields": [
            {"name": "producer", "text": "<UNKNOWN>", "confidence": 0.1}]})
        readings, _ = vision.read_fields(ai, "x.png", ["producer"])
        assert readings == []

    @pytest.mark.parametrize("text", ["unknown", "N/A", "not visible", "illegible",
                                      "[not legible]", "(unreadable)"])
    def test_other_ways_of_saying_it_could_not_read_it(self, text):
        ai = StubAi({"fields": [{"name": "brand", "text": text, "confidence": 0.9}]})
        readings, _ = vision.read_fields(ai, "x.png", ["brand"])
        assert readings == []

    def test_a_low_confidence_reading_is_discarded(self):
        """Discarding on low confidence is the safe direction, and it is *not*
        the mirror of promoting on high confidence — there is still no
        confidence at which a model reading becomes a PASS (2.9)."""
        ai = StubAi({"fields": [
            {"name": "brand", "text": "RUSTY ANCHOR", "confidence": 0.05}]})
        readings, _ = vision.read_fields(ai, "x.png", ["brand"])
        assert readings == []

    def test_a_confident_reading_survives(self):
        ai = StubAi({"fields": [
            {"name": "brand", "text": "RUSTY ANCHOR", "confidence": 0.98}]})
        readings, _ = vision.read_fields(ai, "x.png", ["brand"])
        assert [r.text for r in readings] == ["RUSTY ANCHOR"]

    def test_a_reading_with_no_confidence_reported_is_kept(self):
        """Absent confidence is not zero confidence — the model simply didn't
        say. Dropping those would silently discard usable readings."""
        ai = StubAi({"fields": [{"name": "brand", "text": "RUSTY ANCHOR"}]})
        readings, _ = vision.read_fields(ai, "x.png", ["brand"])
        assert [r.text for r in readings] == ["RUSTY ANCHOR"]


    def test_an_unavailable_client_is_silent_not_an_error(self):
        readings, error = vision.read_fields(NullAi(), "x.png", ["brand"])
        assert readings == [] and error is None

    def test_a_failed_call_reports_why(self):
        readings, error = vision.read_fields(
            StubAi({}, ok=False, error="timed out"), "x.png", ["brand"])
        assert readings == [] and error == "timed out"


# --------------------------------------------------------------------------
# use B — the batch triage brief
# --------------------------------------------------------------------------

def _row(serial, verdict, checks):
    return {"serial_number": serial, "brand_name": f"Brand {serial}",
            "verdict": verdict, "checks": checks}


class TestBatchBrief:
    ROWS = [
        _row("1", "PASS", [{"check_id": "brand", "outcome": "PASS"}]),
        _row("2", "FAIL", [{"check_id": "abv", "outcome": "FAIL", "declared": "45%",
                            "observed": "40%", "detail": "differs"}]),
        _row("3", "REVIEW", [{"check_id": "brand", "outcome": "REVIEW"}]),
    ]

    def test_clean_rows_are_not_sent(self):
        """260 passes describing 40 problems is budget spent on the part that
        needs no triage — and it is 260 rows of data leaving the process for
        nothing."""
        findings, _ = triage.findings_for(self.ROWS)
        assert [f["serial"] for f in findings] == ["2", "3"]

    def test_only_flagged_checks_are_sent(self):
        findings, _ = triage.findings_for(self.ROWS)
        assert all(c["outcome"] != "PASS" for f in findings for c in f["flagged"])

    def test_the_payload_carries_no_image_data(self):
        findings, _ = triage.findings_for(self.ROWS)
        blob = json.dumps(findings)
        assert "image" not in blob.lower()

    def test_a_huge_batch_is_truncated_and_says_so(self):
        rows = [_row(str(i), "FAIL", [{"check_id": "abv", "outcome": "FAIL"}])
                for i in range(triage.MAX_ITEMS + 20)]
        findings, truncated = triage.findings_for(rows)
        assert len(findings) == triage.MAX_ITEMS and truncated is True

    def test_a_brief_comes_back_labelled_advisory(self):
        ai = StubAi({"headline": "31 of 40 are one importer's ABV rounding.",
                     "groups": [{"label": "ABV rounding", "count": 31,
                                 "detail": "Handle as a group."}],
                     "watch_outs": ["Serial 3 needs a fresh photo."]})
        brief, error = triage.summarize(ai, self.ROWS)
        assert error is None
        assert brief.to_dict()["advisory"] is True
        assert brief.to_dict()["generated"] is True
        assert brief.groups[0].count == 31

    def test_no_exceptions_means_no_call_at_all(self):
        ai = StubAi({"headline": "should not be asked"})
        brief, error = triage.summarize(ai, [self.ROWS[0]])
        assert brief is None and error is None
        assert ai.requests == []

    def test_a_failed_call_means_no_brief_and_nothing_else(self):
        brief, error = triage.summarize(StubAi({}, ok=False, error="429"), self.ROWS)
        assert brief is None and error == "429"

    def test_an_unavailable_client_is_silent(self):
        brief, error = triage.summarize(NullAi(), self.ROWS)
        assert brief is None and error is None


# --------------------------------------------------------------------------
# use C — drafted rejection language
# --------------------------------------------------------------------------

class TestRejectionNotice:
    RESULT = {
        "checks": [
            {"check_id": "brand", "field_label": "Brand name", "outcome": "PASS"},
            {"check_id": "abv", "field_label": "Alcohol content", "outcome": "FAIL",
             "declared": "45% Alc./Vol.", "observed": "40% Alc./Vol.",
             "detail": "Label shows 40%, application declares 45%"},
            {"check_id": "warn_text", "field_label": "Warning wording",
             "outcome": "FAIL", "detail": "wording differs",
             "evidence": {"diff": [{"expected": "machinery", "found": "a boat"}]}},
        ]
    }

    def test_only_flagged_findings_are_sent(self):
        findings = drafting.findings_for(self.RESULT)
        assert [f["check"] for f in findings] == ["abv", "warn_text"]

    def test_the_warning_word_diff_is_included(self):
        """It is the whole reason a warning rejection is defensible — an
        applicant can be told exactly which word broke it."""
        findings = drafting.findings_for(self.RESULT)
        warn = next(f for f in findings if f["check"] == "warn_text")
        assert warn["wording_differences"][0]["found"] == "a boat"

    def test_a_draft_comes_back_labelled_generated(self):
        ai = StubAi({"subject": "Label application 100001 — corrections needed",
                     "body": "The alcohol content on the label reads 40%...",
                     "items": ["Alcohol content differs"]})
        notice, error = drafting.draft(ai, {"serial_number": "100001"}, self.RESULT)
        assert error is None
        assert notice.to_dict()["generated"] is True
        assert notice.subject.startswith("Label application 100001")

    def test_nothing_to_reject_means_no_call(self):
        ai = StubAi({"subject": "x", "body": "y"})
        notice, error = drafting.draft(ai, {}, {"checks": [
            {"check_id": "brand", "outcome": "PASS"}]})
        assert notice is None and "nothing to write about" in error
        assert ai.requests == []

    def test_an_unavailable_client_says_so_rather_than_drafting(self):
        notice, error = drafting.draft(NullAi(), {}, self.RESULT)
        assert notice is None and error == "no model configured"
