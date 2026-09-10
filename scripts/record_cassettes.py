"""Record (or inspect) the model replies the test suite replays.

Why this exists: the AI paths in CLAUDE.md 2.9 have to be testable, and no test
in this project is allowed to open a socket — determinism, and the standing proof
of the no-egress path (N-06). So the live API is called *here*, deliberately, by
a person, and the replies are committed under `fixtures/cassettes/`.

    python scripts/record_cassettes.py            # what's recorded, what's missing
    python scripts/record_cassettes.py --record   # call the API to fill the gaps

`--record` needs `ANTHROPIC_API_KEY`. Nothing in `pytest` or CI runs this.

**It records by running the real pipeline.** Building a request list by hand here
would be a second implementation of "what does the pipeline ask for", and the
cassette key covers the prompt, the schema and the image bytes — so the moment
the two drifted, every recording would silently stop matching. Instead the
scenario comes from `fixtures.cassette_application()` and the requests come from
`verify()` itself.

Note that a cassette miss stops the fallback for that label (a miss degrades
exactly like a firewalled call), so filling gaps by hand is iterative: run this,
author the printed key, run it again.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fixtures import cassette_application
from ttbverify.ai.client import CASSETTE_DIR, AiRequest, CassetteAi, ClaudeAi
from ttbverify.ocr import NullOcr
from ttbverify.pipeline import verify


class Watching:
    """Wraps a client and reports every request the pipeline actually makes."""

    def __init__(self, inner):
        self.inner = inner
        self.seen: list[tuple[AiRequest, bool]] = []

    @property
    def available(self) -> bool:
        return True

    @property
    def model(self) -> str:
        return self.inner.model

    def complete(self, request: AiRequest):
        result = self.inner.complete(request)
        self.seen.append((request, result.ok))
        return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--record", action="store_true",
                    help="call the live API for anything not already recorded")
    args = ap.parse_args()

    live = None
    if args.record:
        live = ClaudeAi()
        if not live.available:
            print(f"cannot record: {live.unavailable_reason}")
            return 1

    client = Watching(CassetteAi(CASSETTE_DIR, record_with=live))
    # NullOcr on purpose: with no OCR every field is UNREADABLE, so the fallback
    # is asked for everything and the recording covers the widest request.
    verify(cassette_application(), NullOcr(), ai=client, timeout_ms=None)

    if not client.seen:
        print("the pipeline made no model calls for this scenario")
        return 0
    missing = 0
    for request, ok in client.seen:
        state = "recorded" if ok else "MISSING "
        missing += 0 if ok else 1
        images = ", ".join(Path(p).name for p in request.images)
        print(f"{request.fingerprint()}  {state}  {request.kind}  {images}")
    print(f"\n{len(client.seen)} call(s), {missing} missing. "
          f"Cassettes: {CASSETTE_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
