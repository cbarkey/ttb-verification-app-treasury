"""Where AI fits: three uses, none of which decide compliance (CLAUDE.md 2.9).

  A. `vision`  — read fields OCR could not. Capped at REVIEW by the pipeline.
  B. `brief`   — triage a finished batch. Prose above the table; table is record.
  C. `notice`  — draft rejection language from findings already produced.

Everything regulatory stays in `rules.py` and `warning.py`, deterministically, so
every verdict can be explained to an auditor by pointing at the exact word that
didn't match the statute. `client.NullAi` is the default and what the tests run
on, which is what makes the no-network path (N-06) a continuously asserted
property rather than a claim.
"""

from ttbverify.ai.client import (
    DEFAULT_MODEL,
    AiClient,
    AiRequest,
    AiResult,
    CassetteAi,
    ClaudeAi,
    NullAi,
    SchemaError,
    make_default_client,
    validate,
)

__all__ = [
    "DEFAULT_MODEL",
    "AiClient",
    "AiRequest",
    "AiResult",
    "CassetteAi",
    "ClaudeAi",
    "NullAi",
    "SchemaError",
    "make_default_client",
    "validate",
]
