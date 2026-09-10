# TTB Label Verification

AI-powered alcohol label verification take-home. Full design and rationale in
[`CLAUDE.md`](CLAUDE.md) (Section 2 is the technical design; Section 3 is the list of
implementation pitfalls each rule is built and tested against).

**Where it is now**

- **Phase 0 — done.** Verification core: fixture corpus, the rules engine, real Tesseract
  OCR, the health-warning checks W-1..W-4, accuracy gates. CLI: `python -m ttbverify`.
- **Phase 1 — in progress.** FastAPI service + a React UI: single-label (upload → result
  → split-pane review, design 2.5) **and batch** (ZIP + `manifest.csv` → pre-flight
  reconciliation → streamed queue → work the exception rows). Still to come: degradation
  preprocessing, CI, and deployment.

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
python -m fixtures.generate           # render the clean 16-label corpus + ground truth
python -m fixtures.realistic          # (re)render the realistic corpus — needs system fonts
python -m fixtures.boldness           # (re)render the W-4 boldness calibration corpus
pytest                                # 171 tests: unit + golden + realistic + boldness + API + batch
python report.py                      # accuracy + latency for both corpora; review overlays
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

Open <http://127.0.0.1:8000> and pick **Check one label** or **Upload a batch**.

*Single label* — enter the declared fields, drop the image(s), press **Verify label**. A
clean result offers **Approve**; anything else opens the split-pane **review screen** —
checks on the left (needs-attention first), the label on the right with the active field's
region boxed and a zoomed crop beneath it, per-item decisions in the agent's own words. The
footer's **Approve** unlocks once every review item is resolved.

*Batch* — download the blank manifest, fill it in, zip it with the images, drop the ZIP. A
**pre-flight** screen reconciles the manifest against the archive (missing/orphan images,
duplicate serials, values that won't parse) before anything is verified. Confirm, and
results **stream into a queue** with `FAIL`/`REVIEW` sorted to the top; **Review** walks the
exception rows through the same split-pane with next/prev nav. Decisions export to CSV.

For frontend development with hot reload, run the API on `:8000` and Vite separately:

```bash
cd web && npm run dev                # http://127.0.0.1:5173, proxies /api to :8000
```

### API

| Method & path | Purpose |
|---|---|
| `POST /api/verify` | single label: declared fields JSON + image uploads → `{session_id, result, images}` |
| `GET/POST /api/sessions/{id}[/decisions\|/finalize\|/images/{i}]` | single-label review + resolve |
| `GET /api/manifest-template.csv` | blank manifest (UTF-8 with BOM) |
| `POST /api/verify/batch` | upload a ZIP → pre-flight reconciliation report |
| `POST /api/verify/batch/{id}/start` | begin processing (bounded pool; per-row isolation) |
| `GET /api/verify/batch/{id}/events` | SSE: one event per row + progress + done |
| `GET /api/verify/batch/{id}` | full batch state (polling fallback) |
| `GET/POST /api/verify/batch/{id}/rows/{serial}[/…]` | per-row review + resolve |
| `GET /api/verify/batch/{id}/export.csv` | decisions CSV |
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
| W-4 boldness — confidence-gated auto-confirm (stroke weight vs the statement's own regular text) | done |
| Word-level diff of a non-compliant warning statement | done |
| `NOT_DECLARED` (no application value) distinct from `UNREADABLE` (couldn't read it) | done |
| Multi-image applications (front / back) — checks run across all images (F-08) | done |
| Per-stage latency measured and reported (N-03) | done |
| **FastAPI service** — `POST /api/verify`, session store, decisions, finalize | done |
| **React UI** — single-label form + result + split-pane review (design 2.5) | done |
| **Batch** — ZIP + `manifest.csv`, pre-flight reconciliation (F-10), streamed queue, per-row review (F-05, 5.4) | done |
| **Realistic fixture corpus** — colour / serif / borders / boxed & rotated warnings / photos | done |
| Conditional VLM fallback behind an interface, with a working `NullVlm` (design 2.4) | interface + Null path done; Claude adapter wired, recorded-cassette test to come |
| CI, container, deploy | not yet |
| Degradation-set preprocessing (deskew / perspective correction) | fixtures exist (realistic `loose` cases); preprocessing not yet |

## Measured on the fixture corpus

Real Tesseract 5.4, `NullVlm`, 16 labels (front+back where applicable), on a Windows laptop:

```
false approvals              0          (gated — must be 0)
expectation mismatches       0          (every check matches checked-in ground truth)
warning-statement recall     1.0        (every warning defect fixture is caught)
latency  p50 / p95           ~410 ms / ~420 ms   (budget 5000 ms, N-01)
review rate                  2.3%       (reported, not gated; was 9.9% before W-4 auto-confirm)
```

`report.py` also burns the review-overlay boxes into `out/overlay_*.png` — the same
`CheckResult.box` coordinates the split-pane review screen draws.

### Realistic corpus

The clean corpus above is black text on white — it proves the rules but barely stresses
OCR. `fixtures/realistic.py` renders 16 labels that look like real ones: colour grounds and
gradients, framed borders, Copperplate / Baskerville / slab-serif display faces, a
medallion, a barcode, ABV + net contents in one field of vision, and the government warning
as a small justified block, ruled into a box, or (one case) rotated onto a side panel. Half
the set then gets a *photo of the bottle* pass — rotation, keystone, a lighting vignette,
blur, JPEG compression.

Cases are graded **`exact`** (styling only — every check must match ground truth, like the
clean corpus) and **`loose`** (degraded — a clean field may soften to `REVIEW`/`UNREADABLE`,
but a genuine defect must never read `PASS`). The gate that never relaxes: **zero false
approvals** across the whole set.

```
exact-grade cases matching ground truth   9 / 9
false approvals (all 16 cases)             0
latency p95                                ~630 ms
```

Building this corpus caught four real robustness bugs (prominence filter overfit to clean
sizes, no cross-line matching for wrapped brand names, W-2 counting the barcode number that
follows the warning, an OCR TSV decode crash on non-Latin bytes) — all now fixed. The
remaining `loose`-case gaps are all rotation / perspective / low light, i.e. the
degradation-set preprocessing (deskew) that's still to come.

### W-4 boldness calibration corpus

`fixtures/boldness.py` renders 50 matched warning headers — 6 font families × regular/bold ×
two sizes × clean/degraded, plus a heavy-display and a thin-light adversarial — to calibrate
and gate the W-4 auto-confirm (see the design note above).

```
regular headers ever auto-PASSed          0     (the hard gate)
W-4 auto-FAILs                             0     (it only PASSes or REVIEWs)
decidable cases correct                    25/25
decidable auto-decide rate                 48%   (reported, not gated)
```

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

**W-4 (bold header) is confidence-gated, not always-review.** An *absolute* ink-density
threshold is confounded — all-caps text reads denser than mixed-case regardless of weight —
so W-4 instead compares `GOVERNMENT WARNING` against the **regular-weight remainder of the
same statement** (same family, same size, guaranteed present). The estimator is a stroke
thickness (2·area/perimeter, height-normalized, on a 4× upscale so a 1–2 px stroke isn't
lost to quantization). Calibrated on `fixtures/boldness.py` — 6 families × regular/bold × 2
sizes × clean/degraded, plus adversarial cases — regular headers land at 1.29–1.46× the
body, genuine bold at 1.64×+. W-4 **auto-PASSes only above 1.55×** (well clear of the gap);
anything short is `REVIEW` with the ratio shown; it **never auto-FAILs**. On the matched
corpus: 0 regular headers ever auto-PASS, and ~48% of the clean same-family set
auto-decides. Effect on the clean corpus: review rate 9.9% → 2.3%, and a fully compliant
label verifies straight to `PASS`.

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

- W-4 boldness auto-confirms only the confidently-bold case; everything else is human review. It never auto-FAILs. ~48% of clean same-family headers auto-decide on the calibration corpus.
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
  app.py          FastAPI app: single-label routes, static web/dist; includes the batch router
  sessions.py     in-memory, TTL-swept session store (N-05)
  manifest.py     CSV manifest parse + pre-flight reconciliation (design 3.4)
  batch.py        in-memory batch store; queue ordering (design 5.4)
  routes_batch.py ZIP upload, /start, SSE /events, per-row review, CSV export
  schemas.py      request/response models
web/
  src/screens/    Home · SingleLabelForm · ResultScreen · ReviewScreen (+ LabelViewer) ·
                  DoneScreen · BatchUpload · BatchPreflight · BatchQueue
fixtures/
  generate.py     renders the clean 16-label corpus + ground truth -> cases.json
  realistic.py    renders the realistic corpus (colour/serif/borders/photos) -> cases_realistic.json
  boldness.py     matched bold/not-bold warning headers for W-4 calibration -> cases_boldness.json
tests/            unit (normalize, parsers, warning, rules) + golden + realistic + API contract
report.py         accuracy + latency for both corpora; renders review-overlay PNGs
```
