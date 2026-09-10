# TTB Label Verification

AI-powered alcohol label verification take-home. Full design and rationale in
[`CLAUDE.md`](CLAUDE.md): Section 2 is the technical design (2.9 is *where the AI fits*),
Section 3 is the list of implementation pitfalls each rule is built and tested against, and
Section 6 is a running build log.

An agent uploads a label image and the application values that were declared for it. The
tool reads the label, compares the two, and returns a per-field verdict with the evidence
behind it — including the region of the image each finding came from.

**Where it is now.** The verification core, the service, both UIs (single label and batch),
deskew preprocessing, and the three AI features are built and tested. Deployment is the
remaining piece.

---

## Where the AI is, and where it deliberately isn't

The brief is titled *AI-Powered Alcohol Label Verification*, so it is worth being precise
rather than vague about this.

**AI is used in three places, none of which decide compliance:**

| | What it does | Decides a verdict? |
|---|---|---|
| **Vision fallback** | When OCR still can't read a field after preprocessing, a vision model is asked what the label says | **No** — the reading is capped at `REVIEW` |
| **Batch triage brief** | After a batch finishes, one call turns the structured findings into "these 31 exceptions are one importer's rounding error; handle them as a group" | No — the queue table stays the record |
| **Draft rejection language** | On demand, turns findings the rules engine already produced into a notice the agent edits and sends | No — the decision is already made |

**Every regulatory verdict comes from deterministic code.** The normalization ladder, the
statutory warning comparison, the capitalization rule, the boldness measurement and all the
numeric comparisons are ordinary code with ordinary tests. That is what makes a finding
explainable to an auditor by pointing at the exact word that didn't match the statute,
rather than at a model.

### The cap, which is the whole safety argument

**A model-sourced reading can only ever produce `REVIEW`.** Not `PASS`, and not `FAIL`
either. The model's only power is to convert *"I can't read this"* into *"here's what it
appears to say — please confirm."*

Verified against the live API, not just asserted: on a deliberately poor photograph, OCR read
only `RUSTY ANCHOR`, the model read `40% ALC./VOL. (80 PROOF)` and `750 mL` at 0.98
confidence, and **both landed at `REVIEW`** despite matching the declared values exactly.

Three consequences worth stating:

- **"Zero false approvals" stays a property of the deterministic system.** It is gated in CI
  against corpora that can be re-run; a nondeterministic component able to mint a `PASS`
  would move a proven property into the merely-likely column.
- **Network dependence is benign.** With a key: `REVIEW` plus a reading. Without one:
  `UNREADABLE`. Both route to a human; neither approves. Whether Marcus Williams' firewall
  let the call through changes the *evidence*, never the *verdict class*.
- **Nothing is auto-approved on a model's say-so**, which is the property that lets this
  anywhere near a regulatory workflow at all.

### Without an API key

The app runs identically minus those three features. That is a **supported configuration,
not a degraded one** — `NullAi` is the default, and it is what the entire test suite runs on,
which is how "works with no network" (N-06) stays continuously asserted instead of claimed.
No test in this repository opens a socket; the model-backed paths replay recorded cassettes.

---

## Setup

Requires **Python 3.11+** and the **`tesseract`** binary (v5.x).

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
every check is `UNREADABLE` and nothing is auto-approved (N-06).

**Optional — the AI features.** Put a key in `.env` at the repo root:

```
ANTHROPIC_API_KEY=sk-ant-...
```

`.env` is read only by `python -m service`, never by `create_app()`, so the test suite can
never pick up a real key and start making live calls. It is in both `.gitignore` and
`.dockerignore`. In a container the variable comes from the platform instead.

## Run — core + tests

```bash
python -m fixtures.generate           # render the clean 17-label corpus + ground truth
python -m fixtures.realistic          # (re)render the realistic corpus — needs system fonts
python -m fixtures.boldness           # (re)render the W-4 boldness calibration corpus
pytest                                # 327 tests
python report.py                      # accuracy + latency for both corpora; review overlays
```

Verify a single application from the CLI:

```bash
python -m ttbverify --demo brand_mismatch           # a bundled fixture case
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
python -m service                     # http://127.0.0.1:8000
```

Or the whole thing in one container, which is what gets deployed:

```bash
docker build -f Dockerfile.vercel -t ttbverify .
docker run --rm -p 8000:80 ttbverify        # http://127.0.0.1:8000
```

The file is named `Dockerfile.vercel` because that is the only name Vercel looks
for; there is deliberately no second copy to drift out of sync, and nothing in it
is Vercel-specific. It listens on `$PORT`, defaulting to 80 to match the
platform, so nothing has to be configured for it to deploy.

One process serves the API and the built React bundle from the same origin — one URL, no
CORS, nothing to configure. Add `-e ANTHROPIC_API_KEY=...` to enable the AI features.

---

## What works

| Capability | Status |
|---|---|
| Brand / class-type matching via the 4-tier normalization ladder | done |
| Display admissibility so a fine-print brand string isn't a false match (design 3.2) | done |
| ABV parsing across label phrasings; proof-vs-ABV (`proof == 2 × ABV`) consistency | done |
| Net contents with unit normalization (mL / cL / L / fl oz / pt) | done |
| Health warning W-1 presence, W-2 wording (two-band), W-3 capitalization | done |
| W-4 boldness — confidence-gated auto-confirm against the statement's own regular text | done |
| Word-level diff of a non-compliant warning statement | done |
| `NOT_DECLARED` (no application value) distinct from `UNREADABLE` (couldn't read it) | done |
| Multi-image applications (front / back) — checks run across all images (F-08) | done |
| Per-stage latency measured and reported (N-03) | done |
| **Deskew / keystone preprocessing** before OCR, applied only when it measurably helps | done |
| **FastAPI service** — `POST /api/verify`, session store, decisions, finalize | done |
| **React UI** — single-label form + result + split-pane review (design 2.5) | done |
| **Batch** — ZIP + `manifest.csv`, pre-flight reconciliation (F-10), streamed queue, per-row review (F-05) | done |
| **Realistic fixture corpus** — colour / serif / borders / boxed & rotated warnings / photos | done |
| **AI: vision fallback, batch brief, drafted notices** — behind one interface, `NullAi` default, cassette-tested | done |
| **Container** — single image, `$PORT`-aware, health-checked, clean SIGTERM shutdown | built and run-tested |
| CI | written, not yet run against a remote |
| Deployment | in progress |

### API

| Route | Purpose |
|---|---|
| `POST /api/verify` | multipart: declared fields + image(s) → result + session |
| `GET /api/sessions/{id}` | session state (result, decisions, what's unresolved) |
| `POST /api/sessions/{id}/decisions` | record an agent's call on one `REVIEW` item |
| `POST /api/sessions/{id}/draft-notice` | AI: draft rejection language for this label |
| `POST /api/sessions/{id}/finalize` | approve / reject / request better image |
| `POST /api/verify/batch` | ZIP upload → pre-flight report |
| `POST /api/verify/batch/{id}/start` | begin processing |
| `GET /api/verify/batch/{id}/events` | SSE: one event per row + progress + done |
| `GET /api/verify/batch/{id}` | full batch state, including the triage brief |
| `GET/POST /api/verify/batch/{id}/rows/{serial}[/…]` | per-row review + resolve + draft notice |
| `GET /api/verify/batch/{id}/export.csv` | decisions CSV |
| `GET /api/health` | OCR + AI availability, engine, model id, active sessions |

Interactive docs at `/docs`. No persistence: sessions are in-memory and TTL-swept (N-05).

---

## Measured on the fixture corpus

Real Tesseract 5.4, `NullAi`, 17 clean labels (front+back where applicable), Windows laptop:

```
false approvals              0            (gated — must be 0)
expectation mismatches       0            (every check matches checked-in ground truth)
every field reads its own text  PASS      (gated — see below)
warning-statement recall     1.0          (every warning defect fixture is caught)
latency  p50 / p95           591 / 606 ms (budget 5000 ms, N-01)
review rate                  3.3%         (reported, not gated; 9.9% before W-4 auto-confirm)
```

Realistic corpus (styled + photographed labels): p95 **962 ms**, 0 false approvals.

`report.py` also burns the review-overlay boxes into `out/overlay_*.png` — the same
`CheckResult.box` coordinates the split-pane review screen draws.

### Per-field reading — the gate that matters most

Outcome strings alone are a weak test. A verdict can be right for the wrong reason: a check
pointing at another check's line, or a fixture whose brand overflowed the label and was never
OCR'd at all, both still produce the expected `FAIL`. Both of those actually happened here and
the outcome gates said nothing.

So every generated case records, per check, **what the label says and which images it says it
on** (`expect_observed`), and `tests/test_field_reading.py` asserts the pipeline against it —
29 undegraded labels × 7 categories. Three statuses:

| status | meaning |
|---|---|
| `matched` | the observed text matches the label's own text (via the normalization ladder, so OCR noise is tolerated) and came from one of the images that actually print it |
| `only_in_fine_print` | the declared value *is* on the label but buried inside a longer statement — must `FAIL`, and the box points at the buried occurrence so the agent can see the decoy (design 3.2) |
| `not_found` | it isn't on the label. `observed` is `None` — the tool says it didn't find it rather than guessing what the label "probably" says |

Two further guards back this up, and both had to be strengthened after they let something
through:

- **The generators audit their own output.** Every field the ground truth claims is printed
  must be legible on one of its images, or generation fails loudly. The audit asks the same
  question the *check* asks: a display field must be legible as a line of its own, a numeric
  field must be recoverable by its parser. An earlier version asked "is this string anywhere
  on the image", which a brand clipped off the edge of the label passes, because it still
  appears inside the bottler statement — the exact defect the audit was written for.
- **The generators verify their own premise.** A fixture whose fonts silently substituted is
  not the fixture it claims to be. Cases that can't be rendered as described are dropped with
  a printed reason rather than quietly becoming a different test (see the boldness corpus).

### Realistic corpus

The clean corpus above is black text on white — it proves the rules but barely stresses
OCR. `fixtures/realistic.py` renders 16 labels that look like real ones: colour grounds and
gradients, framed borders, Copperplate / Baskerville / slab-serif display faces, a
medallion, a barcode, ABV + net contents in one field of vision, and the government warning
as a small justified block, ruled into a box, or (one case) rotated onto a side panel. Half
the set then gets a *photo of the bottle* pass — rotation, keystone, a lighting vignette,
blur, JPEG compression.

### W-4 boldness calibration corpus

`fixtures/boldness.py` renders 50 matched warning headers — 6 font families × regular/bold ×
two sizes × clean/degraded, plus a heavy-display and a thin-light adversarial — to calibrate
and gate the W-4 auto-confirm.

```
regular headers ever auto-PASSed          0     (the hard gate)
W-4 auto-FAILs                             0     (it only PASSes or REVIEWs)
decidable cases correct                    25/25
decidable auto-decide rate                 48%   (reported, not gated)
```

On a machine without the adversarial faces (any stock Linux box) those two cases are dropped
rather than substituted, and the remaining 48 still calibrate the threshold.

---

## Design decisions worth calling out

**OCR is Tesseract via TSV output, not plain text.** The pipeline needs, per word: original
casing (W-3 capitalization check), a bounding box (review overlay, W-4 crop), and a
confidence score (to tell `UNREADABLE` from `FAIL`). Tesseract's default text output throws
all three away; `tesseract … tsv` keeps them. See the OCR bake-off below.

**A brand match must be a *line*, not a fragment — and the tool never guesses which line.**
A label can legitimately contain the producer's name in fine print that matches the
*declared brand* even when the prominent brand is something else; an unrestricted whole-label
search accepts that and produces a genuine false approval. Two attempts to fix it by *type
size* and by *position* were both wrong, because box height is not type size (a Copperplate
display brand can measure shorter than the class/type line beneath it) and position assumes a
layout. What works is how the match sits in its line: a display match must cover most of its
own line, and not be fine print. `brand_mismatch` and `r05_brand_decoy` exist to hold that
line — each plants the declared brand in the bottler statement while the real display brand
is something else, and both must `FAIL`.

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
lost to quantization). Regular headers land at 1.29–1.46× the body, genuine bold at 1.64×+.
W-4 **auto-PASSes only above 1.55×**; anything short is `REVIEW` with the ratio shown; it
**never auto-FAILs**. A false approval is the expensive error; a false review costs a glance.

**Deskew runs before OCR, and only when it measurably helps.** A hand-held photo is rotated
a degree or two and often turned slightly away from the camera, and Tesseract degrades
sharply on both — on one fixture the brand line is simply absent from the OCR output at 0°
and present after a 4° correction. Candidate corrections are *scored* against doing nothing
using the horizontal projection profile, and applied only when they clearly win: 10 of 31
corpus images get one, every clean render gets none. Boxes are mapped back so everything
downstream still works in the coordinates of the image the agent uploaded.

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
| Runtime model download | none — offline out of the box | downloads models from a remote hub on first use; must be pre-baked to satisfy N-06 |
| p95 latency on this corpus | ~600 ms end-to-end | not measured — see below |
| Accuracy on the clean corpus | 100% of gates | expected equal on clean renders |
| Accuracy on skewed / blurred / low-light photos | weaker | stronger — this is Paddle's real advantage |

**Decision: Tesseract.** It passes every gate with ~8× latency headroom and ships offline in
a lean container with no runtime model fetch. Paddle's robustness to skew and blur is real,
but two cheaper things address the same problem here: deterministic deskew, which is ~90 ms
and fixed most of it, and the conditional vision fallback for the residual. The `OcrEngine`
interface (`ttbverify/ocr.py`) is where an alternative engine drops in.

---

## Deployment

One container serves the API and the built frontend from a single origin — one URL for TTB
to open, no CORS, no second service to keep in step.

**Target: Vercel**, using container-image support rather than serverless functions. The OCR
engine is a system binary installed with `apt-get`, which a plain serverless function can't
provide. Vercel auto-detects `Dockerfile.vercel` at the project root and routes all traffic
to the image, so this needs no `vercel.json` — the only configuration is the API key, set as
a project environment variable scoped to Production.

**Azure Container Apps was considered and deliberately not used.** It is the natural fit for
TTB's real infrastructure (Marcus Williams' interview: "we're on Azure now"), and the design
names it for that reason. It isn't used here because deploy-platform choice isn't in the
evaluation criteria, and learning unfamiliar cloud tooling under a time box is a bad trade
against the work that *is* graded. **The container is portable** — the same image runs on
Azure Container Apps, Render or Fly with no code changes, only different platform config.

Known trade-offs, stated rather than discovered:

- **Cold starts.** Idle instances scale to zero after 5 minutes in production (30 seconds on
  preview deployments), so the first request after a gap pays a cold start. Worth naming
  explicitly in a project whose central claim is a 5-second budget: N-01 is about per-label
  processing time, and a cold start is a platform artifact on top of it, not the pipeline
  being slow.
- **No authentication.** This is a standalone prototype with no COLA integration, no accounts
  and no persistence, exactly as scoped. Anyone with the URL can use it — including the AI
  features, which cost money. The deployed instance therefore runs on a capped, disposable
  API key that is revoked once the review window closes.
- **Static IPs / Secure Compute** aren't available for custom container images on Vercel.
  Irrelevant here: nothing in this system needs an allowlisted outbound IP.

## Known limitations

Stated rather than hidden — all of these are live behaviour today.

- **`r14_wine_angle`'s warning wording FAILs.** Deskew recovers the brand on that keystoned
  photo, but OCR still truncates words mid-way through the warning block on the back label.
  It is a compliant label going to a human, not a false approval.
- **`r12_lowlight`'s producer line FAILs.** Blur plus a heavy vignette, not geometry, so
  deskew doesn't help. The vision fallback deliberately doesn't fire here either: it triggers
  only on `UNREADABLE`, never on a `FAIL`, because asking on a `FAIL` would let a model
  *downgrade a rejection to review* — the same power the cap exists to withhold, arriving
  through the back door.
- **W-4 auto-confirms only the confidently-bold case**; everything else is human review, and
  it never auto-FAILs. ~48% of clean same-family headers auto-decide.
- **ABV is compared exactly**, near-misses (≤ 0.5%) routed to `REVIEW`. Per-commodity
  regulatory tolerances exist and are deliberately **not** asserted — a prototype shouldn't
  claim tolerance values it hasn't verified against current regulation.
- **The committed AI cassettes are hand-authored**, not recorded, because the repository was
  built without an API key. Each one says so in a `note` field, and
  `python scripts/record_cassettes.py --record` replaces them with real recordings. What they
  test is unaffected — the request fingerprint, schema validation, the cap, attribution and
  every degradation path are real — but they are not evidence about what the model returns.
- **Fixture corpora are platform-dependent.** The generators use system fonts, so a corpus
  rendered on Linux differs from one rendered on Windows. Both audit clean and pass every
  gate; the images themselves just aren't byte-identical across machines.
- **Not a complete TTB rules engine** — this checks declared-vs-label consistency plus the
  health warning. Standards of identity/fill, appellations, allergen statements, and
  type-size measurement are out of scope (and TTB does not review type size itself).

## Layout

```
ttbverify/
  models.py       canonical types + the Outcome enum
  normalize.py    the 4-tier normalization ladder + hand-rolled Levenshtein
  parsers.py      ABV/proof and net-contents parsing with unit conversion
  preprocess.py   deskew / keystone correction, scored before it is applied
  ocr.py          OcrEngine interface; TesseractOcr (TSV) and NullOcr
  warning.py      health-warning checks W-1..W-4 + the 27 CFR 16.21 reference text
  rules.py        the field engine (display admissibility lives here)
  pipeline.py     verify() / verify_batch(), per-stage timing, the REVIEW cap
  cli.py          python -m ttbverify
  ai/
    client.py     the one place this project talks to a model: schema-validated
                  tool calls, timeout, pinned model, NullAi, cassette replay
    vision.py     use A — read fields OCR could not
    brief.py      use B — the batch triage brief
    notice.py     use C — drafted rejection language
    prompts/      the prompts, as files, in version control
service/
  app.py          FastAPI app: single-label routes, static web/dist, batch router
  sessions.py     in-memory, TTL-swept session store (N-05)
  manifest.py     CSV manifest parse + pre-flight reconciliation
  batch.py        in-memory batch store; queue ordering
  routes_batch.py ZIP upload, /start, SSE /events, per-row review, CSV export
  schemas.py      request/response models
web/
  src/screens/    Home · SingleLabelForm · ResultScreen · ReviewScreen (+ LabelViewer) ·
                  DoneScreen · BatchUpload · BatchPreflight · BatchQueue
  src/components/ AiLabel (attribution) · NoticeDrawer
fixtures/
  generate.py     the clean corpus + ground truth        -> cases.json
  realistic.py    styled + photographed labels           -> cases_realistic.json
  boldness.py     matched bold/not-bold warning headers  -> cases_boldness.json
  cassettes/      recorded model replies + the frozen images they were recorded against
scripts/
  record_cassettes.py  re-record the cassettes against the live API
tests/            unit · per-field reading · golden · realistic · boldness · AI · API · batch
report.py         accuracy + latency for both corpora; renders review-overlay PNGs
Dockerfile.vercel one image: builds the frontend, installs Tesseract, serves both
```
