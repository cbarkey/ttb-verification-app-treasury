# CLAUDE.md — TTB Label Verification: Project Brief, Design, and Build Guidance

**Read this before changing anything.** It is the single source of truth for this project:
(1) the original take-home brief verbatim, (2) the technical design derived from it, (3)
implementation guidance and the pitfalls that actually bit, and (4) a build log of what
exists today and why it is the way it is.

**This is no longer a greenfield repo.** There is a working codebase, 232 passing tests,
three fixture corpora with per-field ground truth, and a running web app. Section 6 is the
current state; Sections 3–5 are how to work on it without re-breaking things that have
already been broken once.

Whenever a decision here seems arbitrary, it probably isn't — the rationale is included. If
you want to deviate, that's fine, but re-read the "why" first. Several of the sharpest
lessons in Section 3 were learned the expensive way.

---

## How to use this document

1. **Working on the code?** Section 6 first (what exists), then Section 5 (how to run it and
   the invariants not to break), then Section 3 (the pitfalls) for whatever you're touching.
2. **Trying to understand a decision?** Section 2 is the design of record. Where the build
   diverged from it, Section 6 says so and why.
3. **Adding a rule or a fixture?** Section 3.8 is not optional reading. Outcome-only tests
   have already let two real defects through this project; every new check needs a test that
   asserts *what it read*, not just what it decided.
4. **Wondering where the AI is?** Section 2.9. Short version: three uses, none of which
   decide compliance, and a model-sourced reading is capped at `REVIEW`.
5. **Keep this file current.** It's the project's memory. When you make a decision worth
   preserving — or discover that advice in here is wrong — write it down here, and correct
   the stale guidance in place rather than leaving both versions standing.

---

## Section 1 — The original take-home brief (verbatim)

> ### Take-Home Project: AI-Powered Alcohol Label Verification App
>
> #### Project Background & Stakeholder Context
>
> The following document contains notes from our discovery sessions with the Compliance
> Division, along with technical requirements for the prototype. We've included stakeholder
> feedback to give you context on how this tool will be used.
>
> #### Interview Notes: Sarah Chen, Deputy Director of Label Compliance
> *Conducted Tuesday, 3:15 PM — Sarah was running late from her daughter's school play
> rehearsal*
>
> "Thanks for meeting with me. Sorry about the delay—my daughter's playing the lead in her
> school's production of Annie next week and rehearsals have been crazy. Anyway, let me tell
> you about what we're dealing with here.
>
> So the TTB reviews about 150,000 label applications a year. Our team of 47 agents handles
> all of them. Back in the 80s—before my time—they actually had over 100 agents, but budget
> cuts, you know how it goes. We've been doing things basically the same way since the COLA
> system went online in 2003. That was a big upgrade from paper forms, believe it or not.
>
> The actual review process is pretty straightforward. An agent pulls up an application,
> looks at the label artwork, and checks that what's on the label matches what's in the
> application. Brand name matches? Check. ABV is correct? Check. Government warning is
> there? Check. It takes maybe 5-10 minutes per application for a simple one, longer if
> there are issues.
>
> Here's the thing though—and this is what got leadership interested in AI—a lot of what we
> do is just... matching. Like literally just making sure the number on the form is the same
> as the number on the label. My agents spend half their day doing what's essentially data
> entry verification. It's not that they can't do more complex analysis, it's that they're
> drowning in routine stuff.
>
> Oh, I should mention—we tried a pilot with the scanning vendor last year. Disaster. The
> system would take 30, 40 seconds sometimes to process a single label. Our agents just went
> back to doing it by eye because they could do five labels in the time it took the machine
> to do one. If we can't get results back in about 5 seconds, nobody's going to use it. We
> learned that the hard way.
>
> What else... The agents really vary in their tech comfort level. Dave's been here since
> the Clinton administration and still prints his emails. Meanwhile, Jenny's fresh out of
> college and probably could have built this tool herself. We need something my mother could
> figure out—she's 73 and just learned to video call her grandkids last year, if that gives
> you a benchmark. Half our team is over 50. Clean, obvious, no hunting for buttons.
>
> One more thing that came up in our last team meeting—during peak season, we get these big
> importers who dump 200, 300 label applications on us at once. Right now we literally have
> to process them one at a time. If there was some way to handle batch uploads, that would be
> huge. Janet from our Seattle office has been asking about this for years."
>
> #### Interview Notes: Marcus Williams, IT Systems Administrator
> *Coffee chat, Thursday morning*
>
> "Sarah probably gave you the business side. Let me fill you in on some of the technical
> landscape.
>
> Our current infrastructure is... well, it's government infrastructure, let's leave it at
> that. We're on Azure now after the migration in 2019. That was a whole thing—don't get me
> started on the FedRAMP certification process. Took 18 months just for the paperwork.
>
> The COLA system is built on .NET, though there's been talk about modernizing it for years.
> We had a contractor come in last summer to do an assessment and they quoted us $4.2 million
> for a full rebuild. That went nowhere, obviously.
>
> For this prototype, we're not looking to integrate with COLA directly—that's a whole
> different beast with its own authorization requirements. Think of this as a standalone
> proof-of-concept that could potentially inform future procurement decisions. If it works
> well, maybe we look at how to incorporate it into the workflow. But that's years away,
> realistically.
>
> Security-wise, we'd need to be careful with any production deployment—there's PII
> considerations, document retention policies, the usual federal compliance stuff. But for a
> prototype? Just don't do anything crazy. We're not storing anything sensitive for this
> exercise.
>
> Oh, and our network blocks outbound traffic to a lot of domains, so keep that in mind if
> you're thinking about cloud APIs. During the scanning vendor pilot, half their features
> didn't work because our firewall blocked connections to their ML endpoints. Classic."
>
> #### Interview Notes: Dave Morrison, Senior Compliance Agent (28 years)
> *Brief hallway conversation*
>
> "Look, I'll be honest, I've seen a lot of these 'modernization' projects come and go.
> Remember the automated phone system they put in back in 2008? Supposed to reduce call
> volume. We ended up with more calls because nobody could figure out how to navigate it.
>
> The thing about label review is there's nuance. You can't just pattern match everything.
> Like, I had one last week where the brand name was 'STONE'S THROW' on the label but
> 'Stone's Throw' in the application. Technically a mismatch? Sure. But it's obviously the
> same thing. You need judgment.
>
> That said, I'm not against new tools. If something can help me get through my queue
> faster, great. Just don't make my life harder in the process. I spend enough time fighting
> with COLA as it is."
>
> #### Interview Notes: Jenny Park, Junior Compliance Agent (8 months)
> *Teams call, Friday afternoon*
>
> "I'm so excited you're working on this! When I started here, I was kind of shocked at how
> manual everything is. Like, I literally have a printed checklist on my desk that I go
> through for every label. Brand name—check with my eyes. ABV—check with my eyes. Warning
> statement—check with my eyes. It's 2024!
>
> The one thing I'd say is the warning statement check is actually trickier than it sounds.
> It has to be exact. Like, word-for-word, and the 'GOVERNMENT WARNING:' part has to be in
> all caps and bold. Sarah probably mentioned this but people try to get creative with the
> warning all the time. Smaller font, different wording, burying it in tiny text. I caught
> one last month where they used 'Government Warning' in title case instead of all caps.
> Rejected.
>
> Also—and this is maybe out of scope for a prototype—but it would be amazing if the tool
> could handle images that aren't perfectly shot. I've seen labels that are photographed at
> weird angles, or the lighting is bad, or there's glare on the bottle. Right now if an agent
> can't read the label they just reject it and ask for a better image. But if AI could handle
> some of that..."
>
> #### Technical Requirements
>
> You are free to use any programming languages, frameworks, or libraries you prefer. We
> want to see what kind of engineering, design, and integration decisions you make.
>
> #### Additional Context
>
> **About TTB Label Requirements.** For reference, TTB requires specific information on
> alcohol beverage labels. The exact requirements vary by beverage type (beer, wine,
> distilled spirits) but common elements include:
> - Brand name
> - Class/type designation
> - Alcohol content (with some exceptions for certain wine/beer)
> - Net contents
> - Name and address of bottler/producer
> - Country of origin for imports
> - Government Health Warning Statement (mandatory on all alcohol beverages)
>
> We encourage you to review TTB's guidelines at ttb.gov for additional context on label
> requirements.
>
> **Sample Label.** Your app should handle labels containing information like the example
> below.
>
> Example Distilled Spirits Label Fields:
> - Brand Name: "OLD TOM DISTILLERY"
> - Class/Type: "Kentucky Straight Bourbon Whiskey"
> - Alcohol Content: "45% Alc./Vol. (90 Proof)"
> - Net Contents: "750 mL"
> - Government Warning: [Standard government warning text]
>
> We encourage you to create or source additional test labels—AI image generation tools work
> well for this.
>
> #### Deliverables
> 1. **Source Code Repository** (GitHub or similar) — all source code, README with setup and
>    run instructions, brief documentation of approach, tools used, assumptions made.
> 2. **Deployed Application URL** — working prototype we can access and test.
>
> #### Evaluation Criteria
> - Correctness and completeness of core requirements
> - Code quality and organization
> - Appropriate technical choices for the scope
> - User experience and error handling
> - Attention to requirements
> - Creative problem-solving
>
> We understand this is time-constrained. A working core application with clean code is
> preferred over ambitious but incomplete features. Document any trade-offs or limitations.
>
> Questions? Reach out for clarification—though we also value how you fill in gaps
> independently.

**End of verbatim brief.** Everything below is derived from it, not part of it — the
"Technical Requirements" section above is deliberately thin, and most of the real
requirements are embedded in the interview transcripts as anecdotes rather than stated as
specs. Section 2.1 traces each one back to its source.

---

## Section 2 — Technical design

> **Scope posture.** This is a prototype. The brief says plainly that a working core with
> clean code beats ambitious-but-incomplete. Where this document lists something as a
> stretch or a Phase 1 nice-to-have, that means *cut it without hesitation* if the core
> isn't solid. The things that are not negotiable are in 2.1 and the testing section (7).

> **This section is the design of record, written before the build.** It is still accurate
> except where marked **As built** below. Section 6 has the current state; Section 3 has the
> places where the design's own advice turned out to be wrong.

### 2.1 Requirements

Traced to source. **(D)** marks requirements *derived* from an anecdote rather than stated
outright in the "Technical Requirements" section.

#### Core — must work

| ID | Requirement | Source |
|----|-------------|--------|
| F-01 | Accept label image(s) + declared application field values; return a per-field verification result. | Core brief |
| F-02 | Verify brand name, class/type, alcohol content, net contents, and the health warning statement. Producer name/address and country of origin where declared. | "Additional Context" |
| F-03 | Brand/class/producer comparisons tolerate case, punctuation, and whitespace variance. | Dave Morrison — `STONE'S THROW` **(D)** |
| F-04 | Health warning verified against exact statutory text, including that `GOVERNMENT WARNING` is uppercase. Title case is a rejection. | Jenny Park **(D)** |
| F-05 | Batch upload of 200–300 label/application pairs in one submission. | Sarah Chen **(D)** |
| F-06 | A third outcome between pass and fail — *needs human review* — plus a review screen that shows the agent the field and the image region side by side (see 2.5). | Dave Morrison, "you need judgment" **(D)** |
| F-07 | Unreadable images reported as a distinct outcome ("request a better image"), never as a compliance failure. | Jenny Park **(D)** |
| F-08 | One application may carry multiple label images (front / back / neck). Field checks run across all of them. | TTB F 5100.31 reality — the warning is usually on the back label **(D)** |
| F-09 | Every finding is explainable: show the text read off the label and where on the image it came from. | Dave Morrison, "don't make my life harder" **(D)** |
| F-10 | Batch manifests validated *before* processing, with a reconciliation summary the agent confirms. | Error handling is an explicit evaluation criterion **(D)** |

#### Non-functional

| ID | Requirement |
|----|-------------|
| N-01 | **Single-label interactive path: p95 end-to-end ≤ 5 s**, upload complete → result rendered. Hard threshold; the prior vendor pilot died at 30–40 s. |
| N-02 | **Batch: 5 s is not the per-batch budget.** Target ≥ 2 labels/sec sustained (a 300-item batch in roughly 2.5–5 min). First results stream to the UI within ~5 s so the agent starts working while the tail processes. This is a deliberate reinterpretation: the source anecdote describes an agent waiting on *one* label, not a batch. |
| N-03 | Measured latency shown in the UI. Builds trust with a team burned once already. |
| N-04 | Operable without training by a low-technology-comfort user: one obvious primary action per screen, large targets, plain-language outcomes, no raw confidence scores on the default view. |
| N-05 | No storage of uploaded images or application data beyond the session. In-memory only. |
| N-06 | Any external model dependency is behind an interface with a working no-network fallback. |
| N-07 | Ships as a container. Azure is the natural target given TTB's infrastructure, but any host that meets N-01 is acceptable for the prototype. |

#### Deliberately not built

Named here so the README can say so out loud rather than looking like oversights:

- COLA integration, auth, user accounts, audit logging, persistence.
- Full TTB rule coverage — standards of identity, standards of fill, appellations, allergen
  statements. This tool checks *declared-vs-label consistency* plus the health warning. It
  is not a regulatory rules engine.
- Type-size / characters-per-inch legibility measurement. TTB's own certificate states that
  TTB does not review labels for type size or characters per inch; the industry member
  remains responsible. Out of scope, and worth a sentence in the README because it shows the
  reading was done.
- Bulk analytics, dashboards, historical reporting, user preferences, settings pages.

### 2.2 Input contract

Not specified in the brief. Modelled on the real artifact: **TTB Form 5100.31**,
"Application for and Certification/Exemption of Label/Bottle Approval," filed through COLAs
Online. Using the form's actual field names and its 14-digit TTB ID as a key costs nothing
and grounds the prototype in the domain.

#### Canonical schema

Everything converges here. The rules engine only ever sees this — every ingestion path
(UI form, JSON, CSV manifest) is an adapter that produces this shape, which keeps the rules
engine pure and testable.

```
LabelApplication
  ttb_id: str | None            # 14-digit; primary key when present
  serial_number: str            # fallback key, with permit_number
  permit_number: str | None
  brand_name: str
  fanciful_name: str | None
  class_type: str
  alcohol_content: str | None   # stored raw as declared; parsed downstream
  net_contents: str | None
  applicant_name: str | None
  applicant_address: str | None
  origin: str | None
  commodity: "wine" | "malt" | "spirits"
  images: [ImageRef]            # 1..n
```

**Declared fields are optional by design.** Alcohol content and net contents are not
structured fields on every COLA record. A missing declared value produces `NOT_DECLARED —
no comparison made`, never a failure. Asserting a mismatch against a value the applicant
never declared is a false rejection, and false rejections are the thing agents will not
forgive.

#### Ingestion paths

| Path | Use | Phase |
|------|-----|-------|
| **UI form** | Single label. Agent types or pastes declared values, drops image(s). | 0 |
| **JSON** `POST /verify` | Canonical API contract. What the tests target. | 0 |
| **ZIP: `manifest.csv` + images** | Batch. | 1 |
| `ApplicationSource` interface with a `COLAAdapter` stub | Not implemented. Exists so the README can point at exactly where a future integration plugs in. | doc only |

#### Batch packaging

A single ZIP — `manifest.csv` at the root, images alongside. Browsers handle a 300-file
multi-select badly, and one atomic upload is far easier to explain than "select all your
files."

Pairing is by **explicit column**, not filename convention:

```csv
serial_number,brand_name,class_type,alcohol_content,net_contents,image_files
100001,OLD TOM DISTILLERY,Kentucky Straight Bourbon Whiskey,45% Alc./Vol.,750 mL,front_001.jpg;back_001.jpg
```

Convention-based matching (`100001_front.jpg`) looks elegant and breaks the moment an
export tool renames something. The explicit column also gives multi-image support (F-08)
for free.

> **As built:** the sample above omits `commodity`, but `LabelApplication` requires it and
> there is no safe default — so the real required columns are `serial_number, brand_name,
> class_type, commodity, image_files`, with the rest optional. `GET /api/manifest-template.csv`
> emits the full header (UTF-8 with a BOM, so Excel opens it cleanly).

#### Pre-flight reconciliation (F-10)

Before any OCR runs, validate and show the agent a confirmation screen:

- missing or unreadable required columns
- rows referencing images not present in the ZIP
- images present with no manifest row
- duplicate serial numbers
- declared values that can't be parsed (e.g. an ABV field containing `TBD`)

Takes well under a second and means nobody watches 300 labels process only to find row 12
was broken. Also ships a **"download blank manifest"** button emitting a template CSV as
UTF-8 with a BOM so Excel opens it cleanly.

### 2.3 Verification semantics

#### Outcome states

| State | Meaning | UI label |
|-------|---------|----------|
| `PASS` | Matches within the field's tolerance. | Matches |
| `REVIEW` | Plausible but not confident, or a call the machine shouldn't make alone. | Needs your review |
| `FAIL` | Definite mismatch or missing mandatory element. | Does not match |
| `UNREADABLE` | OCR confidence too low, or field not located. | Can't read — request better image |
| `NOT_DECLARED` | No application value to compare against. | Not declared |

`UNREADABLE` is never collapsed into `FAIL` (F-07).

**Governing principle, stated once and enforced everywhere: never emit `PASS` for a check
that was not actually performed.** False approvals are the expensive error — a compliance
tool that rubber-stamps something it didn't check has real regulatory consequences. False
review requests only cost an agent a glance.

#### Normalization ladder — brand, class/type, producer, origin

First tier that matches wins; the tier that fired is recorded so the UI can say *"matched
after ignoring capitalization"* rather than just "pass" (F-09).

1. **Exact** (whitespace-collapsed only) → `PASS`
2. **Case-folded** → `PASS` *(the `STONE'S THROW` case)*
3. **Punctuation / whitespace normalized** — curly vs straight apostrophes, `&` vs `and`,
   collapsed spaces, trailing `LLC` / `Inc.` / `Co.` → `PASS`
4. **Fuzzy similarity** (normalized Levenshtein or equivalent): similarity ≥ 0.92 →
   `REVIEW`; below → `FAIL`

Four tiers, not more. Token-sort and diacritic folding are additions to make only if the
fixture corpus shows they're needed — don't build them speculatively.

#### Alcohol content

- Parse ABV from free text: `45% Alc./Vol.`, `ALC 45% BY VOL`, `45% ABV`, `Alc. 45% by Vol.`
- If proof is present, assert `proof == 2 × ABV`. Cheap to check, real rejection reason.
- Compare numerically, **exact match by default**. Per-commodity tolerances exist in the
  regulations, but a prototype asserting specific tolerance values it hasn't verified is
  worse than one that flags a near-miss for human review. Near-misses go to `REVIEW`, and
  the README should say why.

#### Net contents

Parse quantity + unit, normalize to millilitres, compare numerically — so `750 mL`,
`750ML`, and `0.75 L` all pass. Standards-of-fill validation is out of scope; the parsed
value is surfaced.

#### Health warning statement

Reference text (27 CFR 16.21) — **this exact text, do not paraphrase it**:

> GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink alcoholic
> beverages during pregnancy because of the risk of birth defects. (2) Consumption of
> alcoholic beverages impairs your ability to drive a car or operate machinery, and may cause
> health problems.

| Check | Rule | Catches |
|-------|------|---------|
| **W-1 Presence** | Statement located on any of the application's images. Absent → `FAIL`. | Missing warning |
| **W-2 Text fidelity** | Word-exact against reference after whitespace collapse only. Any substitution, omission, or insertion → `FAIL`, with a word-level diff. **Caveat:** real OCR makes character-level errors, so a naive word-exact comparison against OCR output will produce false rejections on clean labels. Use a two-band comparison — a token that's *close* to the reference (e.g. similarity ≥ ~0.75) is probably OCR noise and should downgrade the check to `REVIEW`, not `FAIL`; a token that's genuinely different is a real `FAIL`. Build a test with deliberately noisy OCR-like input to catch this before it becomes a production false-rejection bug. | Creative rewording |
| **W-3 Casing** | `GOVERNMENT WARNING` must be all caps. Title case → `FAIL`. | Jenny's title-case rejection |
| **W-4 Boldness** | **Superseded — see 3.4.** The original rule was "route to human review, always, never auto-decide"; the reasoning (a density threshold is confounded by capitalization) is right but the conclusion was too pessimistic. **As built:** the header is measured against the statement's *own* regular-weight text, which removes the confound. It auto-PASSes only when confidently heavier, and **never auto-FAILs** — everything short of confident still goes to a human with the measurement and a crop. | Non-bold warning header |

**Implementation constraint:** the OCR path must preserve original casing and expose
per-word bounding boxes. A pipeline that lowercases on ingest cannot satisfy W-3 or the
highlighting needed for the review screen. This constrains the OCR engine and how you call
it — see Section 3.1.

### 2.4 Architecture

```
   Browser ──► Web UI (React)
               • single label   • batch queue   • review split-pane
                     │ HTTP / SSE
               API (FastAPI, async)
               POST /verify · POST /verify/batch · GET /verify/batch/{id}/events
                     │
               Pipeline (per label, async)
               ingest → preprocess → OCR → extract → [VLM fallback] → rules → result
```

#### Latency budget — single label, p95

| Stage | Work | Budget |
|-------|------|--------|
| Ingest | EXIF orientation, format/size validation, decode | 100 ms |
| Preprocess | Deskew, contrast normalization, resize to OCR-optimal DPI | 250 ms |
| OCR | Local engine — word boxes, per-word confidence, casing preserved | 1200 ms |
| Extraction | Field location, warning-block anchoring | 250 ms |
| VLM fallback | **Conditional** — only on low confidence or unlocated fields | 0 ms typical / 2500 ms worst |
| Rules | Pure comparison functions, no I/O | 20 ms |
| Assembly | Serialization, overlay coordinates | 30 ms |
| | **Typical** | **~1.9 s** |
| | **Worst case with fallback** | **~4.4 s** |

This budget is why the design is local-OCR-first with a *conditional* vision model. Calling
a VLM on every label spends the entire budget on one network round trip and leaves nothing
for batch throughput (N-02).

#### Components

- **OCR:** Tesseract or PaddleOCR, chosen by a bake-off against the fixture corpus.
  Criteria: casing preservation, word-level boxes and confidences, CPU latency. Record the
  bake-off results in the README — a measured choice reads far better than an asserted one.
- **VLM fallback:** hosted vision model, behind an interface with a no-op implementation so
  the system runs degraded with no outbound network (N-06). Also what the tests use — no
  test should ever touch the real network.
- **Backend:** Python + FastAPI suggested (matches the async/streaming needs cleanly), but
  any stack that hits the latency budget is fine. `asyncio` for I/O, a bounded worker pool
  for CPU-bound OCR, a per-label timeout that returns a partial result rather than hanging.
- **Frontend:** React suggested. Three screens — single, batch, review. No settings page.
- **Deploy:** Docker container.

> **As built:** OCR is Tesseract (bake-off in the README — PaddleOCR pulls ~50 packages and a
> runtime model download for no gain on clean renders). Backend is FastAPI; batch processing
> uses a daemon thread + `ThreadPoolExecutor(4)` rather than asyncio (Section 6 says why).
> Frontend is React + Vite + Tailwind, four screens (home, single, batch, review). The VLM
> fallback is built but dormant — wiring it in is the next work, see Section 6.
> Container and deploy are **not** done.

#### Batch

Submission returns a `batch_id` immediately; results stream over SSE (or equivalent) as
each label completes, so the table populates progressively (N-02). Per-label failures are
isolated — one corrupt image never fails the batch.

#### Failure behavior

Error handling is an explicit evaluation criterion, so specify it rather than improvise it:

| Condition | Behavior |
|-----------|----------|
| VLM unreachable / firewalled | Log once, continue OCR-only. Affected fields → `REVIEW`, reason "automated check unavailable". Never `PASS` on an unperformed check. |
| OCR confidence below floor | `UNREADABLE` for that field, region still shown to the agent. |
| Per-label timeout | Partial result, unfinished fields → `REVIEW`, elapsed time displayed. |
| Corrupt / unsupported file | Rejected at ingest, plain-language message naming the file. |
| Malformed manifest | Caught at pre-flight (2.2), nothing processes. |

### 2.5 Human review experience

The most important screen in the product, and the direct answer to Dave's "you need
judgment." Everything else is plumbing that feeds it.

#### Entry point

The result screen leads with a plain-language verdict and a single primary action:

- **All checks passed** → "Looks good — 6 of 6 checks passed." Primary action: *Approve*.
- **Anything needs attention** → "3 items need your review." Primary action: **Review**.
- **Image unreadable** → "Couldn't read this label." Primary action: *Request a better
  image*.

One button. No hunting (N-04). The agent never has to decide *which* control opens the
review.

#### Review screen — split pane

```
┌───────────────────────────────┬─────────────────────────────┐
│  CHECKS                       │  LABEL                      │
│                               │                             │
│  ▸ 3 need review              │   ┌───────────────────┐     │
│                               │   │                   │     │
│  ● Brand name        REVIEW   │   │   label image     │     │
│      Application: Stone's     │   │   with the active │     │
│        Throw                  │   │   field's region  │     │
│      Label:  STONE'S THROW    │   │   boxed + dimmed  │     │
│      [ Same product ] [ Not ] │   │   elsewhere       │     │
│                               │   │                   │     │
│  ● Warning: bold?    REVIEW   │   └───────────────────┘     │
│  ● Net contents      REVIEW   │   ┌───────────────────┐     │
│                               │   │  zoomed crop of   │     │
│  ▸ 3 passed          ⌄        │   │  the active field │     │
│                               │   └───────────────────┘     │
│                               │   front · back              │
├───────────────────────────────┴─────────────────────────────┤
│   Approve            Reject           Request better image  │
└─────────────────────────────────────────────────────────────┘
```

- **Left:** the checks. Items needing attention are listed first and expanded. Passed
  checks are collapsed behind a count — available, not in the way.
- **Right:** the label image, with the active check's region boxed and the rest of the
  image dimmed, plus a zoomed crop underneath. Small print is the whole problem; a crop
  beats a magnifier control.
- **Selection is two-way.** Clicking a check highlights its region. Clicking a region on the
  image selects that check.
- **Multiple images (F-08)** are tabs — *front · back*. Selecting a check switches to the
  image the field was found on automatically.

#### Per-item decision

Each `REVIEW` item gets two large buttons in the agent's own language, not the machine's:

| Item type | Buttons |
|-----------|---------|
| Fuzzy text match | **Same product** / **Not a match** |
| Warning boldness (W-4) | **Bold enough** / **Not bold** |
| ABV near-miss | **Accept** / **Reject** |

Resolving an item collapses it and advances to the next. When none remain, the footer's
primary action becomes live. `FAIL` items are shown with the evidence but are not
agent-resolvable — the warning-statement diff is displayed word-by-word against the
reference so the agent can see exactly which word broke it.

#### Batch review

The batch table sorts `FAIL` and `REVIEW` to the top — that's the agent's real queue. A
**Review** button on each such row opens the same split-pane screen with next/prev
navigation and a "4 of 12" counter, so an agent can work the exception queue without
returning to the table between items. Rows that passed cleanly need no interaction at all —
that's the actual time saving.

Decisions are session-scoped and in-memory (N-05), exportable as CSV at the end.

#### Not built

No annotation tools, no free-text notes, no reviewer assignment, no re-running with
adjusted thresholds, no side-by-side of two labels. Every one of those is a plausible v2 and
none of them is what's being evaluated.

### 2.6 Testing strategy

Not specified in the brief, which makes it a differentiator — it gets a first-class README
section, not an afterthought. It stays proportionate to a prototype, though: don't build a
test pyramid more elaborate than the application it's testing.

#### Fixture corpus — generated, not collected

Test labels should be **generated programmatically** (e.g. PIL/SVG → PNG) so ground truth
is exact and the corpus is version-controlled, diffable, and regenerable.

1. **Clean set** — synthetic labels across beer / wine / spirits with known field values,
   including front+back pairs where the warning lives on the back.
2. **Mutation set** — one deliberate defect each, every one mapped to a rule: brand case
   variance (must `PASS`), brand genuinely different (must `FAIL`), ABV mismatch, proof
   inconsistent with ABV, net contents unit variance vs value mismatch, warning missing /
   reworded / title-cased.
3. **Degradation set** — rotation, mild perspective skew, blur, low light, JPEG artifacts.

A few AI-generated photographic labels can serve as a smoke set with looser assertions. CI
gates on the generated corpus, not the smoke set.

#### Layers

| Layer | What | Network |
|-------|------|---------|
| **Unit** | Normalization ladder, ABV/proof parser, unit conversion, warning differ, casing rule. Pure functions, milliseconds. | none |
| **Golden** | Fixture image → full pipeline → result JSON vs a checked-in expectation. Diffs are reviewable. | stubbed |
| **Integration** | Batch isolation, timeout path, VLM-unreachable degradation, manifest pre-flight rejections. | stubbed |
| **Contract** | API schemas, error shapes, SSE event ordering. | none |
| **Performance** | N-01 and N-02 asserted as tests, not claimed in prose. | none |
| **Smoke E2E** | A handful of end-to-end paths: upload → result, review → resolve → approve, batch streaming. Not a full E2E suite. | local |

> **As built — one layer is missing from this table, and it is the most important one.**
> *Per-field reading*: for every label, assert what each check actually **read** and from
> which image, not just the verdict it returned. The layers above are all outcome-shaped, and
> outcome-shaped tests let two real defects through this project. See 3.8.
>
> Also as built: **Smoke E2E is not automated** — the UI flows were driven and screenshotted
> by hand during development. **Performance** is asserted as a p95 gate in the corpus tests
> rather than as its own layer. **Integration** is folded into the API/batch contract tests.

#### Determinism

No test should touch the network. Stub or record/replay any VLM calls — deterministic CI,
and it doubles as proof of the no-egress path (N-06). Seed any random image generation.

#### Accuracy gates

Have your test runner emit a per-rule confusion matrix over the corpus and gate on two
numbers:

- **False approval rate — must be 0.** Approving a non-compliant label is the failure with
  regulatory consequences. This is the single most important number in the project.
- **Warning-statement recall — must be 1.0** on the mutation set.

**Review rate** is worth reporting but not gating — a high review rate is a usability
problem, not a correctness one, and that trade-off belongs in the README rather than hidden
behind a threshold.

#### CI

Suggested pipeline: lint → typecheck → unit → integration → golden → accuracy report → perf
smoke → build container. Put a coverage floor on the rules and parsing modules specifically,
not the whole repo.

### 2.7 Delivery plan

#### Phase 0 — Rough prototype

**Goal:** prove the latency budget and that the warning checks work, before building any UI.

- Single label only. Minimal UI or CLI is fine.
- Fixture generator first — clean + mutation sets, before any pipeline code.
- Normalization ladder and ABV/proof parser, fully unit-tested.
- OCR bake-off, measured, not assumed.
- Warning checker: W-1, W-2, W-3 at minimum.
- **Exit criteria:** single-label p95 under 5 s on the fixture set; zero false approvals;
  the `STONE'S THROW` case passes; the title-case warning case fails.

#### Phase 1 — Deployed application

- API service; batch endpoint with streaming.
- **The review screen (2.5) — the priority of this phase.**
- Multi-image support (F-08), manifest + pre-flight validation (2.2).
- VLM fallback behind its interface, no-network path tested.
- Degradation set and the preprocessing to handle it.
- Full test layers, accuracy report, CI.
- Containerized, deployed, public URL.
- README: setup and run instructions, approach, tools used, OCR bake-off results, testing
  strategy, assumptions, trade-offs, known limitations.

**Cut order if time runs short:** CSV export → degradation set → property-based tests →
smoke E2E → batch. **The review screen and the warning checks are never cut** — they are the
two things this brief actually cares about.

> **As built:** nothing on the cut list was cut except *property-based tests* and *automated
> smoke E2E*. Batch shipped in full, including CSV export. Still outstanding from the Phase 1
> list: the degradation set's **preprocessing** (the fixtures exist, the deskew doesn't), CI,
> and the container + deployment. The VLM fallback is built behind its interface with the
> no-network path tested, but is not yet wired in — that is the next work (Section 6).

### 2.8 Trade-offs and assumptions to carry into the README

1. **Local OCR first, vision model conditionally.** Trades some accuracy on difficult images
   for the headroom N-01 and N-02 require. A VLM-per-label design is more accurate and
   cannot hold 5 s under batch load. Where AI *is* used, and the reasoning for keeping it out
   of every regulatory verdict, is 2.9.
2. **5 s is per-label interactive latency, not per-batch.** The source anecdote describes an
   agent waiting on one label. Batch is specified as throughput with streamed results.
3. **Tuned toward false reviews over false approvals.** Agents will see items flagged that
   were fine. That's the correct direction for a regulatory check, and it should be
   measured, not just asserted.
4. **Bold detection auto-confirms only the confidently-bold case and never rejects.**
   Measured against the statement's own regular-weight text; anything short of confident is a
   human-review item. See 3.4.
5. **ABV compared exactly; near-misses go to review.** The prototype shouldn't assert
   tolerance values it hasn't verified against current regulation.
6. **Missing declared values produce no comparison, not a failure.**
7. **No persistence.** Satisfies N-05 and keeps the prototype out of the retention/PII
   conversation entirely.
8. **Not a complete TTB rules engine.** Application-to-label consistency plus the health
   warning. Standards of identity, standards of fill, appellations, allergens, and type-size
   measurement are out of scope and should be named as such, not silently ignored.

### 2.9 Where AI fits

> **Design, not yet built.** Written after the Phase 1 build, before implementing. Section 6
> tracks status.

The brief is titled *AI-Powered Alcohol Label Verification*, and it would be easy to satisfy
that literally — put a model call on every verification and call it done. That would be the
wrong build. The core checks are deliberately rules-based (2.3, 3.x), because for a
regulatory tool three properties matter more than model capability:

- **Determinism.** The same label must produce the same verdict every time. A model doesn't
  guarantee that.
- **Latency.** N-01 is a hard 5 s and the whole architecture (2.4) is arranged around keeping
  a network round-trip off the per-label path. The last vendor died at 30–40 s.
- **Defensibility.** "The wording differs at word 34: the statute says *machinery*, the label
  says *a boat*" is an answer an auditor can check. "The model flagged it" is not.

So AI goes where it adds capability the deterministic system genuinely lacks, and nowhere
else. Three places, none of which decide compliance.

#### The three uses

| Use | Fires | Decides a verdict? | Serves |
|-----|-------|--------------------|--------|
| **A. Vision fallback for unreadable fields** | only when a field is still `UNREADABLE` after preprocessing | **No** — can only turn `UNREADABLE` into `REVIEW` | Jenny Park: "images that aren't perfectly shot" |
| **B. Batch triage brief** | once, after a batch completes | No — the queue table stays the record | Sarah Chen: 200–300 labels dumped at once (F-05) |
| **C. Draft rejection language** | on demand, per flagged item | No — the decision is already made | Sarah Chen: "agents drowning in routine stuff" |

**A — Vision fallback.** When OCR can't read or locate a field, call a vision model on that
image for the fields still missing (one call per image, not per field) rather than returning
`UNREADABLE` immediately. This is the one class of problem — glare, blur, bad lighting —
that classical OCR structurally cannot handle and a VLM can.

**The cap, and it is the whole safety argument: a model-sourced reading can only ever produce
`REVIEW`.** Not `PASS`, and not `FAIL` either. The model's sole power is to convert *"I can't
read this"* into *"here's what it appears to say — please confirm."* Reasons:

- **It keeps "zero false approvals" a property of the deterministic system.** That number is
  gated in CI against corpora we can actually run; a nondeterministic component that could
  mint a `PASS` puts a provable property back into the merely-likely category.
- **It makes network dependence benign.** With a key: `REVIEW` plus a reading. Without one:
  `UNREADABLE`. Both route to a human; neither approves. The verdict never flips between
  approved and not-approved based on whether Marcus's firewall let the call through.
- **It still delivers the value.** Jenny's actual complaint is that an unreadable label gets
  *bounced back to the applicant*, costing days. Turning that into a one-glance confirmation
  is most of the win; turning it into a silent auto-approve is the risky remainder.

A model-supplied value is still run through the same normalization ladder and the same
parsers — the model supplies a *reading*, the rules still do the *judging* — but the outcome
is clamped to `REVIEW` regardless of what the ladder concludes.

**B — Batch triage brief.** After a batch finishes, send the *structured findings* (serials,
verdicts, per-check outcomes, declared vs observed) — **not the images** — and get back a
short brief: *"31 of the 40 exceptions are the same ABV rounding pattern from one importer's
submission — handle them as a group. 6 are missing warning statements. 3 are unreadable
photos."* One call per batch, so cost and latency are negligible and N-01 is untouched
(it fires after processing completes). A `groupby` gets perhaps 70% of this; the
cross-cutting pattern-spotting and the framing is the part it doesn't. **The brief is prose
above the table; the table remains the record.** If the call fails, the brief is simply
absent and nothing else changes.

**C — Draft rejection language.** Agents write rejection notices by hand. Given findings the
rules engine already produced — including the word-level warning diff — draft the notice.
Behind a button, so it costs nothing unless used, and the output is copy-to-clipboard text
the agent edits and owns.

#### What is deliberately *not* AI, and why

| | Why not |
|---|---|
| Brand / class / producer / origin matching | The normalization ladder is deterministic, explainable, and already correct. A model here trades auditability for nothing. |
| W-2 warning wording | A word-exact statutory check. Reading the statute through a paraphrasing-capable model is the single most dangerous place to put nondeterminism. |
| W-3 casing | Trivially deterministic. |
| W-4 boldness | The strongest alternative candidate, and declined on purpose. A VLM is genuinely good at "is this header visually heavier?" — but that is a *judgment*, not a *reading*, so it can't be validated the way a reading can, and the stroke-weight ratio (3.4) is already auditable and calibrated. |
| ABV / proof / net contents | Pure arithmetic over a parser. |

#### Sequencing — deskew before the model

**Preprocessing lands first.** The degraded fixtures fail mostly on rotation and keystone,
which a deterministic transform fixes in tens of milliseconds. Wiring the model in first
would spend a 2.5 s nondeterministic network call papering over a problem solved locally, it
would fire far more often than it should, and we would have no way to tell how much of its
apparent value was just missing deskew. The model handles the **residual** — glare, blur,
genuinely bad light.

#### Budget and failure behaviour

- **Single label:** one vision call, only on `UNREADABLE` fields, ~2.5 s worst case — the
  slot already reserved in the 2.4 latency table. Typical path: no call at all.
- **Batch:** bounded concurrency shared with the OCR pool, plus a per-batch call cap. Past
  the cap, remaining unreadable fields stay `UNREADABLE` and the brief says so. A pathological
  batch must not stall N-02 throughput.
- **Timeout, error, no key, or firewalled:** log once, degrade to the deterministic result.
  Affected fields stay `UNREADABLE`. Never `PASS` on an unperformed check.
- **Malformed model output:** schema validation rejects it; treated as no answer.

#### Testing — no network, ever

`NullVlm` stays the default, so the existing suite is untouched and N-06 remains provable.

- **Recorded cassettes.** A `CassetteVlm` replays committed JSON responses keyed by request.
  Record once against the real API, commit, replay in CI. No test ever opens a socket.
- **Per-field ground truth applies to model readings too (3.8).** A model-supplied value is
  still a *reading*; cassette-backed cases get `expect_observed` entries and are asserted the
  same way as OCR readings.
- Gates specific to this work:
  1. a model-sourced reading **never** yields `PASS` or `FAIL` — always `REVIEW`;
  2. timeout / error / malformed output leaves the field `UNREADABLE`, never upgraded;
  3. batch rows are byte-identical with and without the brief;
  4. the whole pipeline still passes with no network and no key.

#### Attribution in the UI

An agent must always be able to tell which findings a model touched.

- A check whose reading came from the model is labelled in the review row — *"read by vision
  model — confirm"* — with the model id, alongside the existing `evidence.source`.
- The result screen notes when the model was consulted at all.
- The batch brief is visibly labelled as generated and advisory, sitting above the table
  rather than inside it.

#### Engineering standard for the model calls

Competence here is in the wiring, not the call count: structured output with schema
validation (never string-scraping), an explicit timeout, a pinned model id, prompts kept in
version control rather than buried in f-strings, graceful degradation to the deterministic
path, and deterministic tests. Two or three uses wired to that standard say more than a dozen
decorative ones.

#### The sentence this is all in service of

> AI is used in three places, none of which decide compliance. A vision model reads fields
> classical OCR can't — and a model-sourced reading can raise an item to human review, never
> to approved. An LLM writes the batch triage brief and drafts rejection language from
> findings the rules engine already produced. Every regulatory verdict comes from
> deterministic code, so every one of them can be explained to an auditor by pointing at the
> exact word that didn't match the statute.

---

## Section 3 — Implementation guidance and known pitfalls

Every pitfall below is now **implemented and guarded by a test** — this section is a map of
where the sharp edges are, not a to-do list. Two of them (3.2 and 3.4) originally gave advice
that turned out to be *wrong*; those are corrected in place, with the original reasoning kept
so the correction makes sense. Don't re-implement the superseded versions.

3.8 is the most important entry and was learned last.

### 3.1 OCR must return word-level boxes, confidences, and original casing

Don't use an OCR call that returns plain text. You need, per word: the text (unmodified
casing), a bounding box, and a confidence score. For Tesseract specifically, this means
using its TSV output mode, not the default text output — the default throws away boxes and
confidence. Whatever engine you choose, confirm this before writing anything downstream of
it, because if the engine lowercases on ingest, the W-3 casing check and the review-screen
highlighting are both impossible to build correctly later.

**Test this directly:** OCR a label with a known mixed-case string and assert the returned
text preserves the case, and that each word has a plausible non-zero-area box.

### 3.2 A brand match must be a *line*, not a fragment — and never guess which line

**The pitfall:** if you search the entire label's OCR output for the declared brand name
string, you will get false approvals. A label can legitimately contain the *producer's*
name in small print (a bottler statement) that happens to match or nearly match the
*declared brand*, especially when a label's real brand is different from its producer name.
An unrestricted whole-label search will find that small-print occurrence and report a brand
match — even though the actual, prominent brand printed on the label is something else
entirely. This is a genuine false approval, not an edge case: build a fixture for exactly
this (a label whose large-type brand is clearly wrong, but whose fine print elsewhere
happens to contain a string that fuzzy-matches the declared brand) and confirm your
implementation reports `FAIL`, not `PASS`.

**The fix that does NOT work — two versions of it were built and both were wrong.** The
tempting move is to decide which text is "display type" by size: keep only text whose line
height clears some ratio of the largest text on the label, or (worse) declare the first big
line to be the brand. Both are font- and layout-dependent:

* **Box height is not type size.** Copperplate-style faces render short caps, so a 72 px
  display brand can measure a *smaller* OCR bounding box than a 44 px Georgia class/type
  line. On `r05_brand_decoy` this made the brand check return the class/type line verbatim.
* **Position assumes a layout.** "The first prominent line is the brand" breaks on the same
  label, where a small `ESTABLISHED 1897` tagline clears the cutoff and lands first.

**The fix that works** (`rules._locate_text`): search *every* run of consecutive words on
every page, and gate the match on how it sits in its line rather than on how big it is. A
display match is admissible only if it

1. covers at least `_DISPLAY_MIN_COVERAGE` (0.6) of its own line — a brand *is* a line;
   "Old Tom Distillery" inside "Produced by … under license from Old Tom Distillery,
   Bardstown, Kentucky" is three words of a twelve-word sentence — and
2. isn't fine print (`_FINE_PRINT_FRACTION`, 0.45 of the page's tallest line) — a second,
   independent guard.

Coverage is the load-bearing signal and it's font-free and layout-free. The result carries a
status: `matched`, `only_in_fine_print` (FAIL, and the box points at the buried occurrence so
the agent can see the decoy), or `not_found` (FAIL, `observed` is `None`). **On a FAIL the
tool must never invent what the label "probably" says** — an earlier version guessed and
confidently reported `ESTABLISHED 1897` as a brand.

Fixtures: `brand_mismatch` (clean corpus) and `r05_brand_decoy` (realistic) both plant the
declared brand in the bottler statement while the prominent brand is something else.

### 3.3 The warning-wording check needs two bands, not exact match

**The pitfall:** comparing OCR'd label text against the reference warning text with a plain
`==` (even after normalizing whitespace) will produce false rejections on clean, compliant
labels, because OCR makes small character-level errors on real text (misreading "and" as
"aud", dropping a period, etc.). If you gate `FAIL` on any character difference at all, a
perfectly compliant label will fail the check whenever OCR stumbles on one character.

**The fix:** compare word by word. If a label word is *close* to the corresponding
reference word (some similarity threshold, tuned empirically — something in the
neighborhood of "one or two characters different" rather than "a different word entirely")
but not identical, treat it as probable OCR noise and downgrade that check to `REVIEW`
rather than `FAIL`. If a word is genuinely different — a real substitution, not a plausible
misread — that's a `FAIL`, and you should show a word-level diff so the agent can see
exactly which word broke it. Build fixtures for both: a clean label passed through a
noise-injection step (swap a couple of characters) should land on `REVIEW` at worst, never
silently `PASS` and never wrongly `FAIL`; a label with an actual reworded sentence should
`FAIL`.

### 3.4 Bold detection: compare against the statement's own regular text, and only ever auto-PASS

**The pitfall, worth understanding before you build this:** the obvious approach is some
kind of stroke-weight or ink-density heuristic — measure how much of the bounding box of
"GOVERNMENT WARNING" is dark pixels versus the surrounding body text, and threshold on the
ratio. This looks like it works on a first pass. It does not actually work, because **capital
letters are inherently denser than lowercase letters regardless of font weight** — so a
genuinely bold header and a plain, non-bold, all-caps header both measure meaningfully
denser than the mixed-case body text around them. The signal you're trying to measure
(boldness) is confounded with a signal you're not trying to measure (capitalization), and
they cannot be cleanly separated with a simple density ratio. If you build this and tune a
threshold against a small fixture set, it will look like it's working — and then fail
silently on a case the fixture set didn't cover, which is exactly the failure mode this
whole project is trying to avoid.

**That diagnosis is right; the original conclusion — "never auto-decide, route every warning
to a human" — was too pessimistic and has been superseded.** Sending an agent to eyeball the
boldness of every compliant label is bad UX, and it was ~2/3 of all review items.

**What actually works** (`warning.assess_boldness`): the confound is *capitalization*, so
remove it by comparing like with like. Don't measure the header against an absolute
threshold or against the mixed-case body — measure it against **the regular-weight remainder
of the same statement**, which is guaranteed present, in the same family and at the same
size. The estimator is a stroke thickness (`2 * ink area / ink perimeter`), height-normalized,
computed on a 4x upscale so a 1–2 px stroke isn't lost to quantization, and aware of
light-on-dark labels.

Calibrated on `fixtures/boldness.py` — 50 matched cases, 6 families x regular/bold x 2 sizes
x clean/degraded, plus a heavy-display and a thin-light adversarial — regular headers land at
1.29–1.46x the body and genuine bold at 1.64x and up. `_BOLD_CONFIRM_RATIO = 1.55` sits in
that gap.

**The asymmetry is the important part: W-4 auto-PASSes or it REVIEWs. It never auto-FAILs.**
A false approval is the expensive error; a false review costs a glance. So "confidently
heavier" is a verdict the machine may reach alone, and everything else — including
"probably not bold" — goes to a human with the measurement attached. On the calibration set:
0 regular headers ever auto-PASS, 25/25 decidable cases correct, ~48% auto-decided.

If you widen the confirm band, the gate that must not move is *0 regular headers auto-PASSed*
across all 50 cases.

### 3.5 Net contents and ABV need numeric comparison, not string comparison

`750 mL`, `750ML`, and `0.75 L` should all be treated as equal — parse to a common unit
(millilitres is the natural choice) and compare numbers, not strings. Same logic for ABV:
different label phrasings (`45% Alc./Vol.`, `ALC 45% BY VOL`, `45% ABV`) should all parse to
the same numeric value before comparison. Also check proof against ABV where both are
present (`proof == 2 × ABV`) — this is a real, common, and cheap-to-catch rejection reason,
and a good example of a check that's pure arithmetic and needs no fuzzy matching at all.

### 3.6 Missing declared values are not failures

If the application doesn't declare a value for a field (this is legitimate — not every
field is structured/mandatory on every COLA record), the check for that field should report
`NOT_DECLARED`, and nothing else. Do not fall through to comparing against an empty string,
which will read as a mismatch and produce a false `FAIL`.

### 3.7 The batch pipeline must isolate per-item failures

One corrupted image or malformed row in a 300-item batch must never take down the whole
batch. Each item should be processed independently (isolate exceptions per item), and a
single item's failure should surface as that item's own `UNREADABLE`/error state in the
results table, with everything else completing normally.

### 3.8 Asserting outcomes is not testing — assert what each check *read*

**This is the one that cost the most, and it is the reason 3.2 stayed broken through two
rewrites.** The accuracy gates asserted verdict strings — `brand: FAIL`, `abv: PASS` — and
nothing else. That is far weaker than it looks, because **a verdict can be right for entirely
the wrong reason**, and the suite cannot tell the difference. Two real defects sat there
green for days:

* `r05_brand_decoy`'s brand name was rendered *off the edge of the label*. The generator
  centred display text without a width check, so `x` went negative and `IRONWOOD RESERVE` was
  drawn across the border. Tesseract never saw it. The case still "passed": `brand: FAIL` was
  the expected verdict, and the brand did fail — because it was invisible, not because it
  mismatched.
* The brand and class/type checks were reading each other's lines. Same verdicts, same green
  suite.

**The fix, and the standard for anything added from here:**

1. **Ground truth records what the label says, per field, and on which image.** Every
   generated case carries `expect_observed`: `{check_id: {status, text, printed, image}}`
   with status `matched` / `only_in_fine_print` / `not_found`. The generators emit it — they
   drew the label, so they know.
2. **`tests/test_field_reading.py` asserts the pipeline against it** — currently 28
   undegraded labels x 7 categories. Text is compared through the normalization ladder so
   OCR noise is tolerated; the *image index* is asserted exactly.
3. **The generators audit their own output.** `fixtures.audit_corpus()` runs after rendering:
   every field the ground truth claims is printed must be legible in that image's OCR, or
   generation exits non-zero. A test proves the audit actually fires, so it can't rot into a
   no-op.
4. **Degraded fixtures are exempt from text assertions** (some fields genuinely can't be read
   through a keystone) but are still bound by the no-false-approval gates. Pinning current
   behaviour there would just bake in the limitation.

**Don't add a corpus, a fixture, or a check without all four.** `report.py` prints the same
per-field table, so the evidence is visible without running pytest.

---

## Section 4 — Environment

Built and verified on **Windows 11, Python 3.13** in `.venv`, **Tesseract 5.4** installed with
`winget install UB-Mannheim.TesseractOCR`. Nothing is Windows-specific; the OCR wrapper finds
the binary on `PATH`, via `TESSERACT_CMD`, or at the standard install location on each OS.

```bash
python -m venv .venv && .venv\Scriptsctivate     # source .venv/bin/activate elsewhere
pip install -r requirements-dev.txt
cd web && npm install && npm run build && cd ..     # frontend -> web/dist
```

- **Runtime deps** (`requirements.txt`): Pillow, FastAPI, uvicorn, python-multipart, and
  `anthropic` (only used if a key is present — see the VLM note in Section 6).
- **Dev** (`requirements-dev.txt`): adds pytest and httpx. `ruff` is used for linting but is
  deliberately not pinned as a dependency.
- **No test touches the network**, ever. That's both determinism and the standing proof of the
  no-egress fallback (N-06). Tests that need the `tesseract` binary are marked `corpus` and
  skip cleanly without it.

## Section 5 — Working on this codebase

```bash
python -m fixtures.generate      # clean corpus  -> fixtures/images/ + cases.json
python -m fixtures.realistic     # realistic corpus (needs system fonts)
python -m fixtures.boldness      # W-4 calibration corpus
pytest                           # 232 tests
python report.py                 # all gates + the per-field reading table + overlays
python -m service                # the web app on http://127.0.0.1:8000
python -m ttbverify --demo brand_mismatch     # single label from the CLI
```

`report.py` exits non-zero if any gate fails, so it doubles as a pre-commit check.

**Where things live**

| | |
|---|---|
| `ttbverify/` | the verification core — pure, no I/O except `ocr.py`. `rules.py` is the field engine, `warning.py` is W-1..W-4, `pipeline.py` orchestrates. |
| `service/` | FastAPI. `app.py` (single label + static), `routes_batch.py` + `batch.py` + `manifest.py` (batch). In-memory stores only. |
| `web/src/screens/` | the three screens. `ReviewScreen` is shared by the single-label and batch paths. |
| `fixtures/` | the three generators and their committed ground truth. |
| `samples/` | ready-made batch ZIPs for trying the app. |

**Invariants — breaking any of these is a bug, not a trade-off**

1. **Never emit `PASS` for a check that wasn't actually performed.** OCR unavailable,
   confidence below floor, field not located → `UNREADABLE` or `REVIEW`. Never a silent pass.
2. **Zero false approvals** on every corpus. This is the one gated number that never relaxes.
3. **`NOT_DECLARED` ≠ `UNREADABLE` ≠ `FAIL`.** Nothing declared is not a mismatch (3.6).
4. **Never guess which line is which field** (3.2), and never invent `observed` text on a FAIL.
5. **Every check needs a test that asserts what it read**, not just what it decided (3.8).
6. **W-4 auto-PASSes or REVIEWs; it never auto-FAILs** (3.4).

---

## Section 6 — Build log (kept current as the project's memory)

### Where it stands

Phase 0 and most of Phase 1 are done. `python -m fixtures.generate && python -m
fixtures.realistic && python -m fixtures.boldness && pytest && python report.py` reproduces
everything below from scratch.

| | |
|---|---|
| Verification core | brand, class/type, ABV, proof, net contents, producer, origin + W-1..W-4 |
| Interfaces | CLI (`python -m ttbverify`), FastAPI service, React UI (single label **and** batch) |
| Corpora | clean 17 cases · realistic 16 · W-4 boldness 50 — all with per-field ground truth |
| Tests | **232**: field-reading 58, boldness 29, realistic 27, parsers 23, corpus 21, normalize 19, rules 12, warning 12, manifest 8, batch API 8, API 8, pipeline 7 |
| Gates (all green) | 0 false approvals · 0 expectation mismatches · every field reads its own text · warning recall 1.0 · 0 regular headers auto-PASS W-4 |
| Latency | clean p50/p95 ~458/463 ms · realistic p95 ~721 ms (budget 5000 ms, N-01) |
| Review rate | 3.3% (reported, not gated) |

**Not built:** degradation preprocessing (deskew / perspective), CI, container, deployment.
The VLM interface exists but is dormant — 2.9 is the design for wiring it in; "AI / LLM"
below tracks status.

### Decisions and tunables to preserve

- **Check IDs are short slugs** — `brand`, `class_type`, `abv`, `proof`, `net_contents`,
  `producer`, `origin`, `warn_present`, `warn_text`, `warn_case`, `warn_bold`. They key the
  review-screen rows, the CSV export and the overlay tags. `proof` is its own check, emitted
  only when proof is actually printed on the label.
- **Verdict precedence** (`models._VERDICT_ORDER`): FAIL > UNREADABLE > REVIEW > PASS >
  NOT_DECLARED. `VerificationResult.verdict` is the worst outcome present.
- **Display admissibility** (`rules`): `_DISPLAY_MIN_COVERAGE = 0.6`, `_FINE_PRINT_FRACTION =
  0.45`. See 3.2 — do not replace these with a type-size or line-position heuristic.
- **Fuzzy tier** `normalize.FUZZY_REVIEW_THRESHOLD = 0.92`; **OCR confidence floor**
  `ocr.MIN_WORD_CONF = 45`; OCR upscales to 1600 px wide before recognition.
- **W-2 OCR-noise floor** `warning._OCR_NOISE_FLOOR = 0.75`, aligned with
  `difflib.SequenceMatcher` over casefolded, punctuation-stripped tokens, so an omitted or
  inserted word reports as exactly that instead of cascading. Trailing tokens past the end of
  the reference are dropped — otherwise a barcode number printed under the warning counts as
  "extra words" and fails a compliant label.
- **W-4** `warning._BOLD_CONFIRM_RATIO = 1.55` on a 4x upscale. See 3.4.
- **Numeric bands**: ABV exact ≤ 0.05, near-miss ≤ 0.5 → REVIEW, else FAIL. Net contents
  ≤ 1% → PASS, ≤ 5% → REVIEW, else FAIL. `parsers.PROOF_TOLERANCE = 1.01` allows half a point
  of label rounding.
- **`_rank` breaks ties on *literal* (pre-normalization) similarity.** When the same value
  appears twice and both normalize to a match, the more literal one wins — that points the
  producer check at the bottler statement rather than the brand line on labels where the
  distillery is also the brand.
- **OCR bake-off**: Tesseract over PaddleOCR. Paddle pulls ~50 packages plus a runtime model
  download (which fights N-06) for no accuracy gain on clean renders. Revisit only for the
  degradation set. Writeup in the README.
- **Batch manifests require a `commodity` column** — the design's sample manifest (2.2) omits
  it, but `LabelApplication` needs it and there is no safe default.
- **Batch processing runs in a plain daemon thread** plus a `ThreadPoolExecutor(4)`, *not* an
  asyncio task: a bare `create_task` background job does not progress between `TestClient`
  requests, and detached tasks can be garbage-collected mid-run. The SSE endpoint polls the
  mutating batch state.
- **Generator gotchas**, both of which shipped broken once: `Sheet.wrapped()` must place each
  word at an explicit x with real inter-word gaps (touching words OCR as one space-less
  token), and all centred display text must shrink to fit (text drawn past the margin is
  invisible to OCR). `fixtures.audit_corpus()` now catches both.

### History (chronological; superseded entries marked)

1. **Phase 0** — verification core, CLI, Tesseract via TSV, clean corpus, accuracy gates.
   90 tests.
2. **Single-label web path** (§2.5 priority) — FastAPI + the split-pane review screen.
3. **Realistic corpus** (`143ee1a`, `7aed4a0`) — colour, serif display faces, framed borders,
   boxed/rotated warnings, photo degradation. Caught four real bugs: W-2 counting
   post-warning text, no cross-line matching for wrapped brands, an OCR TSV decode crash on
   non-cp1252 bytes, and the first prominence overfit.
4. **W-4 confidence-gated boldness** (`3e1a3cb`) — replaced "always REVIEW". Review rate
   9.9% → 2.3%.
5. **Batch, full scope** — manifest + pre-flight reconciliation, streamed queue, per-row
   review reusing the same split-pane, CSV export. 171 tests.
6. **Per-field reading tests + display admissibility** (`b61e977`) — the most important
   correction in the project; see 3.2 and 3.8. 232 tests.

> **Superseded — do not resurrect.** `rules.PROMINENCE = 0.55` (a fraction of the tallest
> word); then `BRAND_PROMINENCE = 1.8` / `SUBHEAD_PROMINENCE = 0.9` (multiples of the median
> word height); then `_blocks()` merging adjacent similar-height lines with a "most prominent
> line" fallback on FAIL; then first-prominent-line tiering. All four were attempts to guess
> which line is the brand from geometry. All four were wrong, in ways only the per-field
> reading tests exposed. `_locate_text` no longer guesses.

### AI / LLM — the next piece of work

**The design is 2.9.** Read it before writing any of this. Summary of the decision and where
the code stands today:

- **Scope: three uses, none decides compliance.** (A) a vision fallback that may only convert
  `UNREADABLE` → `REVIEW`, never to `PASS` or `FAIL`; (B) a batch triage brief, advisory,
  one call per batch; (C) on-demand draft rejection language. Everything else stays
  deterministic, and 2.9 lists what was deliberately excluded and why — including W-4
  boldness, which is the strongest alternative candidate and was declined on purpose.
- **This reverses an earlier decision, deliberately.** The VLM was kept dormant because
  `UNREADABLE` → "request a better image" is already the correct answer, Marcus's firewall
  breaks cloud calls, a round trip eats the 5 s budget, and deterministic verdicts are easier
  to defend. The brief is titled *AI-Powered Alcohol Label Verification*, which is fair to
  read as expecting a model in the loop rather than only a seam where one could go. **The old
  reasoning didn't evaporate — it became the constraints in 2.9.**
- **Sequencing: deskew lands first.** The degraded fixtures fail mostly on rotation and
  keystone, which a deterministic transform fixes in tens of milliseconds. Wiring the model
  in first would use an expensive nondeterministic call to paper over a solved problem and
  make its value impossible to measure. The model handles the residual.

**What exists today** (`ttbverify/vlm.py`, `pipeline._apply_vlm_fallback`): a `VlmClient`
protocol, `NullVlm` (the default, used by every test, and the standing proof of N-06), and a
`ClaudeVlm` adapter gated on `ANTHROPIC_API_KEY`. The fallback retries only OCR-`UNREADABLE`
*text* fields and runs any model value back through the normalization ladder.

**What that needs to become:**

1. the `REVIEW` cap — today a model reading can reach `PASS` through the ladder, which 2.9
   forbids;
2. numeric fields (`abv`, `net_contents`) in scope — currently only the four text fields are;
3. one call per image for all missing fields, not one per field;
4. structured output with schema validation, an explicit timeout, a pinned model id, and
   prompts in version control;
5. `CassetteVlm` + committed responses so this is testable with no network, and
   `expect_observed` entries so model readings are held to 3.8 like any other reading;
6. batch policy — bounded concurrency and a per-batch call cap that degrades to plain
   `UNREADABLE`;
7. UI attribution — "read by vision model — confirm", with the model id;
8. uses B and C, which don't exist at all yet.

### Still to do

Priority order: **degradation-set preprocessing** (deskew / perspective correction — the
realistic `loose` cases are already the fixtures for it) → **wire in the model per 2.9** → CI
→ container + deploy. Preprocessing comes first on purpose: it is deterministic, cheap, and
fixes most of what currently reads as `UNREADABLE`, so the model is measured against the
residual rather than against a problem we hadn't bothered to solve. Deploy (with the user): frontend likely on **Vercel**, backend container
on **Render/Fly**; the user is handling the accounts.

Web-UI polish deferred: the zoom crop for the full warning block is necessarily small; the
right pane has whitespace below the image on wide screens; no keyboard nav between review
items yet.
