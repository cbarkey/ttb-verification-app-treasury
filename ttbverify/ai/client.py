"""The one place this project talks to a model (DESIGN.md 2.9).

Three callers sit on top of this — `vision.py`, `brief.py`, `notice.py` — and
none of them decides a compliance verdict. What this module is responsible for is
the *wiring*, which is where the engineering actually is:

  * **structured output, never string-scraping.** Every request carries a JSON
    schema and is issued as a forced tool call, so the model returns an object,
    not prose to be regexed. The reply is validated against that schema before
    anything downstream sees it; a malformed reply is treated as no reply.
  * **an explicit timeout**, because N-01 is a hard 5 s budget and a hung socket
    must not become an agent staring at a spinner.
  * **a pinned model id**, so a verdict-adjacent reading doesn't silently change
    underneath the corpus when a default moves.
  * **prompts in version control** (`ai/prompts/*.txt`) rather than buried in
    f-strings, so a change to what we ask is a reviewable diff.
  * **graceful degradation.** Every failure — no key, no package, firewalled,
    timed out, malformed, rate-limited — returns `AiResult.failed(...)`. Callers
    get "no answer", never an exception, and the deterministic result stands.

`NullAi` is the default and is what the whole test suite runs on, which is what
keeps N-06 provable: the pipeline has to work with no network and no key, because
Marcus's firewall is a fact of the deployment, not an edge case.
"""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

# Pinned deliberately. See the module docstring — this is not a place for
# "whatever the SDK defaults to today".
DEFAULT_MODEL = "claude-sonnet-5"

# Per-call wall clock.
DEFAULT_TIMEOUT_S = 12.0

# The design (2.4) reserved 2500 ms for the vision fallback and this was 3.0 to
# fit inside it. **Measured against the real API, that budget is wrong**: three
# calls on one label image took 2.4 s, 3.2 s and 6.8 s, so a 3 s timeout fails
# roughly half the time, and a fallback that usually times out is not a feature.
#
# Raised to 10 s with the tension stated rather than hidden: a label that needs
# this call has *already* blown the interactive budget in the only sense that
# matters to an agent, because the alternative is bouncing it back to the
# applicant and waiting days for a new photograph (Jenny Park). N-01's 5 s
# applies to the normal path, where no model call happens at all — and the
# pipeline still reports the overrun in `notes` when it occurs.
VISION_TIMEOUT_S = 10.0

_PROMPT_DIR = Path(__file__).parent / "prompts"

# Recorded replies the test suite replays. Committed, alongside frozen copies
# of the images they were recorded against — see scripts/record_cassettes.py.
CASSETTE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "cassettes"


def load_env_file(path: str | os.PathLike[str] = ".env") -> list[str]:
    """Read `KEY=value` lines from a `.env` file into the environment.

    Returns the names it set — **never the values**, so a caller can log what was
    configured without printing a key.

    **Call this from a process entrypoint only, never from `create_app()` or
    library code.** No test in this project may touch the network (N-06, and it
    is the standing proof of the no-egress path). `create_app()` runs in the test
    suite, so loading a developer's real key there would silently turn every API
    test into a live billed call against Anthropic. The seam is deliberate: the
    app finds a key because `python -m service` put one in the environment, not
    because importing the app reads files off disk.

    Existing environment variables win, so a real `ANTHROPIC_API_KEY` in the
    shell is not clobbered by a stale file. Hand-rolled rather than pulling in
    `python-dotenv`: this is fifteen lines and the dependency surface is
    something this project argues about on purpose.
    """
    file = Path(path)
    if not file.is_file():
        return []
    loaded: list[str] = []
    for raw in file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if not key or key in os.environ:
            continue
        os.environ[key] = value
        loaded.append(key)
    return loaded


def prompt(name: str, **params: Any) -> str:
    """Load a prompt template from `ai/prompts/` and fill in its parameters.

    Templates use `{{name}}` rather than `str.format` braces so that JSON
    examples inside a prompt don't have to be escaped.
    """
    text = (_PROMPT_DIR / f"{name}.txt").read_text(encoding="utf-8")
    for key, value in params.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text.strip()


# --------------------------------------------------------------------------
# request / result
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class AiRequest:
    """One model call. `kind` names the use (2.9's A / B / C) for logs and cassettes."""

    kind: str
    prompt: str
    schema: dict[str, Any]
    tool_name: str = "report"
    images: tuple[str, ...] = ()
    max_tokens: int = 1024
    timeout_s: float = DEFAULT_TIMEOUT_S

    def fingerprint(self) -> str:
        """Stable id for this request — the cassette key.

        Includes the image bytes, so re-rendering a fixture invalidates its
        recording rather than silently replaying a stale answer.
        """
        h = hashlib.sha256()
        h.update(self.kind.encode("utf-8"))
        h.update(b"\0")
        h.update(self.prompt.encode("utf-8"))
        h.update(b"\0")
        h.update(json.dumps(self.schema, sort_keys=True).encode("utf-8"))
        for path in self.images:
            h.update(b"\0")
            try:
                h.update(hashlib.sha256(Path(path).read_bytes()).digest())
            except OSError:
                h.update(b"missing")
        return h.hexdigest()[:32]


@dataclass(frozen=True)
class AiResult:
    """What came back. `ok` is the only thing a caller should branch on."""

    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    model: str = ""
    source: str = "null"  # null | claude | cassette
    elapsed_ms: float = 0.0
    error: str | None = None

    @staticmethod
    def failed(error: str, *, model: str = "", source: str = "null",
               elapsed_ms: float = 0.0) -> AiResult:
        return AiResult(ok=False, model=model, source=source,
                        elapsed_ms=elapsed_ms, error=error)


class AiClient(Protocol):
    @property
    def available(self) -> bool: ...

    @property
    def model(self) -> str: ...

    def complete(self, request: AiRequest) -> AiResult: ...


# --------------------------------------------------------------------------
# schema validation
# --------------------------------------------------------------------------

class SchemaError(ValueError):
    pass


def validate(value: Any, schema: dict[str, Any], path: str = "$") -> Any:
    """Validate against the small JSON-Schema subset these prompts use.

    Deliberately hand-rolled rather than pulling in `jsonschema`: the schemas are
    ours, they use object/array/string/number/boolean and `required`, and N-06 is
    easier to argue with a smaller dependency surface. Raises `SchemaError`; the
    caller turns that into "no answer", never into a crash.
    """
    kind = schema.get("type")
    if kind == "object":
        if not isinstance(value, dict):
            raise SchemaError(f"{path}: expected an object, got {type(value).__name__}")
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if value.get(key) is None:
                raise SchemaError(f"{path}.{key}: required")
        out = {}
        for key, sub in props.items():
            if key in value and value[key] is not None:
                out[key] = validate(value[key], sub, f"{path}.{key}")
        return out
    if kind == "array":
        if not isinstance(value, list):
            raise SchemaError(f"{path}: expected an array")
        item = schema.get("items", {})
        max_items = schema.get("maxItems")
        if max_items is not None and len(value) > max_items:
            raise SchemaError(f"{path}: at most {max_items} items")
        return [validate(v, item, f"{path}[{i}]") for i, v in enumerate(value)]
    if kind == "string":
        if not isinstance(value, str):
            raise SchemaError(f"{path}: expected a string")
        enum = schema.get("enum")
        if enum and value not in enum:
            raise SchemaError(f"{path}: {value!r} not one of {enum}")
        max_len = schema.get("maxLength")
        return value[:max_len] if max_len else value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SchemaError(f"{path}: expected a number")
        return float(value)
    if kind == "boolean":
        if not isinstance(value, bool):
            raise SchemaError(f"{path}: expected a boolean")
        return value
    return value


# --------------------------------------------------------------------------
# implementations
# --------------------------------------------------------------------------

class NullAi:
    """Answers nothing. The default, and the standing proof of N-06.

    Every test in the suite runs against this, so "the whole pipeline works with
    no network and no key" is asserted continuously rather than claimed.
    """

    available = False
    model = ""
    name = "null"
    unavailable_reason = "no model configured (no ANTHROPIC_API_KEY)"

    def complete(self, request: AiRequest) -> AiResult:
        return AiResult.failed("no model configured")


class ClaudeAi:
    """Anthropic implementation. Constructed only when a key is present.

    Structured output is a forced tool call: the schema is handed over as the
    tool's `input_schema` and `tool_choice` pins it, so the reply arrives as a
    validated-shape object instead of prose that has to be parsed out of a code
    fence.
    """

    name = "claude"

    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL,
                 timeout_s: float = DEFAULT_TIMEOUT_S):
        self._model = model
        self._timeout_s = timeout_s
        self._client = None
        self._why: str | None = None
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            self._why = "ANTHROPIC_API_KEY is not set"
            return
        try:
            import anthropic
        except ImportError:
            self._why = "the `anthropic` package is not installed"
            return
        self._client = anthropic.Anthropic(api_key=key, timeout=timeout_s,
                                           max_retries=1)

    @property
    def available(self) -> bool:
        return self._client is not None

    @property
    def model(self) -> str:
        return self._model

    @property
    def unavailable_reason(self) -> str | None:
        return self._why

    def complete(self, request: AiRequest) -> AiResult:
        if self._client is None:
            return AiResult.failed(self._why or "unavailable", source=self.name)

        started = time.perf_counter()
        content: list[dict[str, Any]] = []
        for path in request.images:
            try:
                media_type = mimetypes.guess_type(path)[0] or "image/png"
                data = base64.standard_b64encode(Path(path).read_bytes()).decode("ascii")
            except OSError as exc:
                return AiResult.failed(f"cannot read image: {exc}", model=self._model,
                                       source=self.name)
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": media_type, "data": data}})
        content.append({"type": "text", "text": request.prompt})

        try:
            message = self._client.messages.create(
                model=self._model,
                max_tokens=request.max_tokens,
                timeout=request.timeout_s,
                tools=[{
                    "name": request.tool_name,
                    "description": "Return the requested fields.",
                    "input_schema": request.schema,
                }],
                tool_choice={"type": "tool", "name": request.tool_name},
                messages=[{"role": "user", "content": content}],
            )
        except Exception as exc:  # noqa: BLE001 — every failure degrades the same way
            return AiResult.failed(f"{type(exc).__name__}: {exc}", model=self._model,
                                   source=self.name,
                                   elapsed_ms=(time.perf_counter() - started) * 1000)

        elapsed = (time.perf_counter() - started) * 1000
        raw = next((b.input for b in message.content
                    if getattr(b, "type", None) == "tool_use"), None)
        if raw is None:
            return AiResult.failed("model returned no structured output",
                                   model=self._model, source=self.name,
                                   elapsed_ms=elapsed)
        try:
            data = validate(raw, request.schema)
        except SchemaError as exc:
            return AiResult.failed(f"reply failed schema validation: {exc}",
                                   model=self._model, source=self.name,
                                   elapsed_ms=elapsed)
        return AiResult(ok=True, data=data, model=self._model, source=self.name,
                        elapsed_ms=elapsed)


class CassetteAi:
    """Replays recorded replies from disk. How model-backed paths get tested.

    Keyed by `AiRequest.fingerprint()`, which covers the prompt, the schema and
    the image bytes — so editing a prompt or regenerating a fixture invalidates
    the recording instead of quietly replaying a stale answer.

    A miss is a *failure*, not an exception: an un-recorded request degrades
    exactly the way a firewalled one does, so the no-answer path gets exercised
    by every test that doesn't have a cassette for what it asked.

    Pass `record_with=ClaudeAi()` to fill gaps from the live API and write them
    out (see `scripts/record_cassettes.py`). Nothing in the test suite does that,
    and nothing in CI can.
    """

    name = "cassette"

    def __init__(self, directory: str | os.PathLike[str],
                 record_with: AiClient | None = None):
        self.directory = Path(directory)
        self._record_with = record_with

    @property
    def available(self) -> bool:
        return True

    @property
    def model(self) -> str:
        return DEFAULT_MODEL

    def path_for(self, request: AiRequest) -> Path:
        return self.directory / request.kind / f"{request.fingerprint()}.json"

    def complete(self, request: AiRequest) -> AiResult:
        path = self.path_for(request)
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not payload.get("ok", True):
                return AiResult.failed(payload.get("error", "recorded failure"),
                                       model=payload.get("model", DEFAULT_MODEL),
                                       source=self.name)
            try:
                data = validate(payload.get("data", {}), request.schema)
            except SchemaError as exc:
                return AiResult.failed(f"recorded reply failed validation: {exc}",
                                       source=self.name)
            return AiResult(ok=True, data=data, model=payload.get("model", DEFAULT_MODEL),
                            source=self.name)

        if self._record_with is None or not self._record_with.available:
            return AiResult.failed(f"no cassette for {request.kind}/"
                                   f"{request.fingerprint()}", source=self.name)

        live = self._record_with.complete(request)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "kind": request.kind,
            "model": live.model,
            "ok": live.ok,
            "error": live.error,
            "data": live.data,
            "recorded_from": "live API",
            "prompt": request.prompt,
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return live


def make_default_client() -> AiClient:
    """`ClaudeAi` when a key and the SDK are both present, else `NullAi`.

    Note the direction of the default: absence of a key is the *normal* state
    here, not a misconfiguration.
    """
    claude = ClaudeAi()
    return claude if claude.available else NullAi()
