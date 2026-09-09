# TTB Label Verification

AI-powered alcohol label verification take-home. Full design and rationale in
[`CLAUDE.md`](CLAUDE.md) (Section 2 is the technical design; Section 3 is the list of
implementation pitfalls each rule is built and tested against).

**Where it is now**

- **Phase 0 — done.** Verification core: fixture corpus, the rules engine, real Tesseract
  OCR, the health-warning checks W-1..W-4, accuracy gates. CLI: `python -m ttbverify`.
- **Phase 1 — in progress.** FastAPI service + a React review UI for the single-label
  path: upload → result → the split-pane review screen (design 2.5), the priority of this
  phase. Still to come: batch upload + streaming, CSV manifest + pre-flight, the
  degradation set, CI, and deployment.

## Setup

Requires **Python 3.11+**, **Pillow**, and the **`tesseract`** binary (v5.x).

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows;  source .venv/bin/activate elsewhere
pip install -r requirements-dev.txt
```

Install Tesseract:

| OS | Command |
|----|---------|
| Windows | `winget install UB-Mannheim.TesseractOCR` |
| macOS | `brew install tesseract` |
| Debian/Ubuntu | `sudo apt install tesseract-ocr` |

The code finds the binary on `PATH`, via `TESSERACT_CMD`, or at the standard install
location. With no Tesseract present the pipeline still runs — in a **degraded mode** where
every check is `UNREADABLE` and nothing is auto-approved (requirement N-06).

## Run — core + tests

```bash
python -m fixtures.generate          # render the 16-label corpus + ground truth
pytest                               # 98 tests: unit + golden/accuracy + API contract
python report.py                     # accuracy + latency report; writes review overlays
```

Verify a single application from the CLI:

```bash
python -m ttbverify --demo brand_mismatch          # a bundled fixture case
python -m ttbverify path/to/application.json        # your own, canonical schema
python -m ttbverify path/to/application.json --json # machine-readable result
```

`application.json` is one object in the canonical schema (design 2.2) — the same shape as
the `"application"` block in `fixtures/cases.json`. Image paths resolve relative to the
JSON file.

## Run — the web app

```bash
# 1. build the frontend once (outputs web/dist, which the API serves)
cd web && npm install && npm run build && cd ..

# 2. start the service
python -m service                    # http://127.0.0.1:8000  (HOST / PORT env vars)
```

Open <http://127.0.0.1:8000>: enter the declared fields, drop the label image(s), press
**Verify label**. A clean result offers **Approve**; anything else opens the split-pane
**review screen** — checks on the left (needs-attention first), the label on the right with
the active field's region boxed and a zoomed crop beneath it, and per-item decisions in the
agent's own words. The footer's **Approve** unlocks once every review item is resolved.

For frontend development with hot reload, run the API on `:8000` and Vite separately:

```bash
cd web && npm run dev                # http://127.0.0.1:5173, proxies /api to :8000
```

### API

| Method & path | Purpose |
|---|---|
| `POST /api/verify` | multipart: declared fields JSON + image uploads → `{session_id, result, images}` |
| `GET /api/sessions/{id}` | full session state (result, decisions, `can_finalize`) |
| `GET /api/sessions/{id}/images/{i}` | the uploaded image (served from memory, N-05) |
| `POST /api/sessions/{id}/decisions` | record `accept` / `reject` on a REVIEW item |
| `POST /api/sessions/{id}/finalize` | `approve` / `reject` / `request_image` |
| `GET /api/health` | OCR availability + engine + active session count |

Interactive docs at `/docs`. No persistence: sessions are in-memory and TTL-swept.

## What works

| Capability | Status |
|---|---|
| Brand / class-type matching via the 4-tier normalization ladder | done |
| Prominence filter so a fine-print brand string isn't a false match (design 3.2) | done |
| ABV parsing across label phrasings; proof-vs-ABV (`proof == 2 × ABV`) consistency | done |
| Net contents with unit normalization (mL / cL / L / fl oz / pt) | done |
| Health warning W-1 presence, W-2 wording (two-band), W-3 capitalization | done |
| W-4 boldness as a human-review item with a density measurement as evidence only | done |
| Word-level diff of a non-compliant warning statement | done |
| `NOT_DECLARED` (no application value) distinct from `UNREADABLE` (couldn't read it) | done |
| Multi-image applications (front / back) — checks run across all images (F-08) | done |
| Per-stage latency measured and reported (N-03) | done |
| **FastAPI service** — `POST /api/verify`, session store, decisions, finalize | done |
| **React review UI** — single-label form, result screen, split-pane review (design 2.5) | done |
| Conditional VLM fallback behind an interface, with a working `NullVlm` (design 2.4) | interface + Null path done; Claude adapter wired, recorded-cassette test to come |
| Batch upload + streaming, CSV manifest + pre-flight, degradation set, CI, container, deploy | not yet |

## Measured on the fixture corpus

Real Tesseract 5.4, `NullVlm`, 16 labels (front+back where applicable), on a Windows laptop:

```
false approvals              0          (gated — must be 0)
expectation mismatches       0          (every check matches checked-in ground truth)
warning-statement recall     1.0        (every warning defect fixture is caught)
latency  p50 / p95           ~406 ms / ~417 ms   (budget 5000 ms, N-01)
review rate                  9.9%       (reported, not gated)
```

`report.py` also burns the review-overlay boxes into `out/overlay_*.png` — the same
`CheckResult.box` coordinates the Phase 1 split-pane review screen will draw.

## Design decisions worth calling out

**OCR is Tesseract via TSV output, not plain text.** The pipeline needs, per word: original
casing (W-3 capitalization check), a bounding box (review overlay, W-4 crop), and a
confidence score (to tell `UNREADABLE` from `FAIL`). Tesseract's default text output throws
all three away; `tesseract … tsv` keeps them. See the OCR bake-off below.

**The warning wording check (W-2) is a two-band comparison, not `==`.** Real OCR makes
character-level errors, so a word-exact match against OCR output produces false rejections
on clean, compliant labels. A token that is *close* to its reference word (similarity ≥
0.75) is treated as probable OCR noise and downgrades the check to `REVIEW`; a token that is
a genuinely different word is a `FAIL` with a word-level diff. Both paths are unit-tested
with deliberately noisy input.

**W-4 (bold header) is never auto-decided.** Ink-density measurement confounds boldness with
capitalization — an all-caps non-bold header reads denser than mixed-case body text
regardless of weight, so a density threshold looks fine in a demo and fails silently on the
case the fixture set didn't cover. W-4 always returns `REVIEW`, with the density ratio shown
as *evidence for a human*, never as a verdict. This is the clearest instance of "the machine
surfaces evidence, the human makes the call."

**Brand/class-type matching is prominence-filtered.** A label can legitimately contain the
producer's name in fine print that fuzzy-matches the *declared brand* even when the actual,
prominent brand is different — an unrestricted whole-label search accepts that as a match
and produces a genuine false approval. `rules.PROMINENCE` restricts brand and class-type
matching to text at least 55% the height of the tallest word on the label. The
`brand_mismatch` fixture exists precisely to hold this line: its declared brand appears only
in the bottler statement, and it must `FAIL`.

**Missing declared values are `NOT_DECLARED`, never `FAIL`.** ABV and net contents aren't
structured fields on every COLA record. Asserting a mismatch against a value the applicant
never declared is a false rejection — the error agents won't forgive.

**Governing principle, enforced everywhere:** never emit `PASS` for a check that wasn't
actually performed. OCR unavailable, confidence below floor, field not located → `UNREADABLE`
or `REVIEW`, never a silent pass.

**No third-party fuzzy-matching dependency.** `normalize.py` uses a ~30-line normalized
Levenshtein ratio. Dependency-free keeps the no-egress fallback honest (N-06) and the unit
layer running in milliseconds.

## OCR bake-off: Tesseract vs PaddleOCR

The design asks for a measured choice, not an asserted one.

| | Tesseract 5.x | PaddleOCR |
|---|---|---|
| Word boxes + per-word confidence + original casing | Yes, via `tsv` output | Yes |
| Install footprint | one ~30 MB system package | ~50 Python packages incl. `paddlepaddle` runtime, `pandas`, `opencv` |
| Runtime model download | none — offline out of the box | downloads detection/recognition models from a remote hub on first use; must be pre-baked into the image to satisfy N-06 |
| p95 latency on this corpus | ~417 ms end-to-end | not measured — see below |
| Accuracy on the Phase 0 corpus | 100% of gates (clean synthetic renders) | expected equal on clean renders |
| Accuracy on skewed / blurred / low-light photos | weaker | stronger — this is Paddle's real advantage |

**Decision: Tesseract for Phase 0.** The Phase 0 corpus is clean synthetic renders where
Tesseract already passes every gate with ~10× latency headroom, and it ships offline in a
lean container with no runtime model fetch. PaddleOCR's robustness to perspective skew,
blur, and glare is real and worth revisiting for the **Phase 1 degradation set** — but there
the better tool may be the conditional VLM pass, which is already in the architecture. The
`OcrEngine` interface (`ttbverify/ocr.py`) is where an alternative engine drops in.

## Known limitations

- W-4 boldness cannot be decided automatically — surfaced as evidence for a human, by design.
- Degradation handling is limited to what Tesseract tolerates natively; no deskew, contrast
  repair beyond autocontrast, or glare mitigation yet (Phase 1).
- ABV is compared exactly, near-misses (≤ 0.5 %) routed to `REVIEW`. Per-commodity
  regulatory tolerances exist and are deliberately **not** asserted — a prototype shouldn't
  claim tolerance values it hasn't verified against current regulation.
- Fixture labels are clean synthetic renders. Photographic labels are Phase 1.
- `warning_charnoise` bakes a single-character change into the rendered image to simulate an
  OCR misread deterministically; genuine OCR noise is otherwise hard to reproduce on demand.
- Not a complete TTB rules engine — this checks declared-vs-label consistency plus the
  health warning. Standards of identity/fill, appellations, allergen statements, and
  type-size measurement are out of scope (and TTB does not review type size itself).

## Layout

```
ttbverify/
  models.py       canonical types + the Outcome enum
  normalize.py    the 4-tier normalization ladder + hand-rolled Levenshtein
  parsers.py      ABV/proof and net-contents parsing with unit conversion
  ocr.py          OcrEngine interface; TesseractOcr (TSV) and NullOcr
  vlm.py          VlmClient interface; NullVlm and ClaudeVlm; make_default_vlm()
  warning.py      health-warning checks W-1..W-4 + the 27 CFR 16.21 reference text
  rules.py        the rules engine (prominence filter lives here)
  pipeline.py     verify() / verify_batch() orchestration with per-stage timing
  cli.py          python -m ttbverify
service/
  app.py          FastAPI: /api/verify, sessions, decisions, finalize; serves web/dist
  sessions.py     in-memory, TTL-swept session store (N-05)
  schemas.py      request/response models
web/
  src/screens/    SingleLabelForm · ResultScreen · ReviewScreen (+ LabelViewer) · DoneScreen
fixtures/
  generate.py     renders 16 synthetic labels + exact ground truth -> cases.json
tests/            unit (normalize, parsers, warning, rules) + golden/accuracy + API contract
report.py         accuracy + latency report; renders review-overlay PNGs
```
