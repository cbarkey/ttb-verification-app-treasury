# CLAUDE.md — TTB Label Verification: Project Brief, Design, and Build Guidance

**Read this entire document before writing any code.** It is the single source of truth for
this project. Nothing has been built yet — there is no existing codebase to discover, no
tests to preserve, no prior commits. You are starting from an empty repository. This
document contains (1) the original take-home brief verbatim, (2) the full technical design
derived from it, and (3) implementation guidance — including several non-obvious pitfalls —
distilled from earlier design exploration. Section 3's guidance describes *how to build
this correctly*, not something already built; treat every algorithm in it as a spec to
implement and test yourself, not as code to trust blindly.

Whenever a decision in this document seems arbitrary, it probably isn't — the rationale is
included. If you want to deviate from something, that's fine, but re-read the "why" first.

---

## How to use this document

1. Read Section 1 (the brief) and Section 2 (the design) in full first.
2. Set up the environment per Section 4.
3. Build in the phase order in Section 2, part 8 — Phase 0 first, a rough prototype, before
   any UI or deployment work. Each phase gets real tests before moving on; testing is not an
   afterthought bolted on at the end.
4. Use Section 3 as a reference while implementing — it flags the specific places where a
   naive implementation will look correct and pass a casual glance, but fail a specific,
   named case. Build the test for that case *before* or *alongside* the implementation, not
   after.
5. Update this file as you go if you make a decision worth preserving for later — it's meant
   to keep growing as the project's memory, the same way it started.

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
| **W-4 Boldness** | **Route to human review in v1, always.** Do not attempt to auto-decide this. See Section 3.4 for why a naive stroke-weight/ink-density heuristic will look plausible in a demo and still be fundamentally unreliable — it's confounded by capitalization itself. Show a cropped image of the warning next to the reference and let a human answer in one glance. | Non-bold warning header |

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

### 2.8 Trade-offs and assumptions to carry into the README

1. **Local OCR first, vision model conditionally.** Trades some accuracy on difficult images
   for the headroom N-01 and N-02 require. A VLM-per-label design is more accurate and
   cannot hold 5 s under batch load.
2. **5 s is per-label interactive latency, not per-batch.** The source anecdote describes an
   agent waiting on one label. Batch is specified as throughput with streamed results.
3. **Tuned toward false reviews over false approvals.** Agents will see items flagged that
   were fine. That's the correct direction for a regulatory check, and it should be
   measured, not just asserted.
4. **Bold detection is a human-review item, not an automated check.** Deliberate — see
   Section 3.4.
5. **ABV compared exactly; near-misses go to review.** The prototype shouldn't assert
   tolerance values it hasn't verified against current regulation.
6. **Missing declared values produce no comparison, not a failure.**
7. **No persistence.** Satisfies N-05 and keeps the prototype out of the retention/PII
   conversation entirely.
8. **Not a complete TTB rules engine.** Application-to-label consistency plus the health
   warning. Standards of identity, standards of fill, appellations, allergens, and type-size
   measurement are out of scope and should be named as such, not silently ignored.

---

## Section 3 — Implementation guidance and known pitfalls

This section is **specification, not delivered code.** It exists because a first
implementation pass of this exact design surfaced specific, non-obvious failure modes.
Build your own implementation and your own tests — but build the test for each pitfall
below *before or alongside* the code that could trigger it, because each one is the kind of
bug that looks fine in a demo and is wrong on a specific, checkable case.

### 3.1 OCR must return word-level boxes, confidences, and original casing

Don't use an OCR call that returns plain text. You need, per word: the text (unmodified
casing), a bounding box, and a confidence score. For Tesseract specifically, this means
using its TSV output mode, not the default text output — the default throws away boxes and
confidence. Whatever engine you choose, confirm this before writing anything downstream of
it, because if the engine lowercases on ingest, the W-3 casing check and the review-screen
highlighting are both impossible to build correctly later.

**Test this directly:** OCR a label with a known mixed-case string and assert the returned
text preserves the case, and that each word has a plausible non-zero-area box.

### 3.2 Brand/class-type matching needs a prominence filter, not just fuzzy matching

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

**The fix:** restrict brand and class/type matching to text above some prominence threshold
— e.g., text whose line height is within some ratio of the largest text height on the
label. Brand names are display type; a match found only in fine print should not count.
Tune the specific ratio against your fixture corpus rather than guessing a number.

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

### 3.4 Bold detection cannot be reliably automated — don't try to threshold it

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

**The fix:** don't try to auto-decide this in v1. Route it to human review every time,
unconditionally, with the cropped warning-header image shown next to the reference so a
person can answer in one glance. This is not a cop-out — it is the single clearest and most
defensible example of "the machine surfaces evidence, the human makes the judgment call,"
and it's worth explicitly calling out in the README as a considered design decision rather
than a gap. If you want to build a density measurement anyway, that's fine — show the
number to the agent as supporting evidence — but never let it alone decide `PASS` or `FAIL`.

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

---

## Section 4 — Environment and getting started

- Language/framework choice is yours (the brief explicitly says so) — Python + FastAPI +
  React is a reasonable default that fits the async/streaming requirements cleanly, but
  don't feel constrained to it.
- If using Tesseract for OCR: `brew install tesseract` (Mac) or
  `sudo apt install tesseract-ocr` (Linux). It needs to be callable in TSV mode — see 3.1.
- Use `pytest` (or your framework's equivalent) from the start; don't bolt tests on later.
- No test should ever require network access — see 2.6's "Determinism" note. This also
  doubles as your proof of the no-egress fallback path (N-06).
- Initialize git and commit early and often; the deliverable is a source repository, and a
  clean, legible commit history is part of "code quality and organization" in the
  evaluation criteria.

## Section 5 — Suggested first session

1. Read this entire document once through.
2. Set up the repo skeleton and environment.
3. Write the fixture generator first (Section 2.6), before any pipeline code — you want
   ground truth to test against from day one.
4. Build the normalization ladder and the ABV/net-contents parsers as pure, fully
   unit-tested functions (Section 2.3), independent of OCR.
5. Wire up OCR (Section 3.1), confirm it preserves casing and returns usable boxes.
6. Build the warning checks (Section 2.3, health warning; Sections 3.3 and 3.4 for the two
   known pitfalls).
7. Assemble the rules engine and pipeline; run the fixture corpus through it; confirm the
   accuracy gates (Section 2.6) before moving to any UI work.
8. Only then start Phase 1 — the review screen (Section 2.5) first, ahead of anything else
   in that phase.

---

## Section 6 — Build log (kept current as the project's memory)

### Phase 0 — complete

Verification core, CLI-driven, real Tesseract OCR. `python -m fixtures.generate && pytest &&
python report.py` reproduces the gates: **0 false approvals, 0 expectation mismatches,
warning recall 1.0, single-label p95 ~417 ms** against the 5000 ms budget. 90 tests.

Environment as built: Windows 11, Python 3.13 in `.venv`, Tesseract 5.4 via
`winget install UB-Mannheim.TesseractOCR`. `requirements.txt` (Pillow + anthropic) /
`requirements-dev.txt` (adds pytest). `ruff` used for linting, not pinned as a dep.

Decisions made during implementation, to preserve:

- **Check IDs are short slugs** (`brand`, `class_type`, `abv`, `proof`, `net_contents`,
  `producer`, `origin`, `warn_present`, `warn_text`, `warn_case`, `warn_bold`). They appear
  in the CLI, the overlay PNGs, and will key the review-screen rows. `proof` is its own
  check, emitted only when proof is printed on the label.
- **`Outcome` verdict precedence** (`models._VERDICT_ORDER`): FAIL > UNREADABLE > REVIEW >
  PASS > NOT_DECLARED. `VerificationResult.verdict` is the worst present.
- **`rules.PROMINENCE = 0.55`** — tuned against the corpus (§3.2). Brand renders at 64 px,
  class/type at 44 px, fine print at 18 px; 0.55 cleanly includes class/type and excludes
  fine print. `brand_mismatch` is the fixture that guards it. Re-run `report.py` if you
  touch this — the false-approval gate depends on it.
- **W-2 OCR-noise floor = 0.75** (`warning._OCR_NOISE_FLOOR`), alignment via
  `difflib.SequenceMatcher` on casefolded, punctuation-stripped tokens so an omitted or
  inserted word shows as exactly that rather than cascading.
- **ABV bands** (`rules`): exact ≤ 0.05, near-miss ≤ 0.5 → REVIEW, else FAIL.
  **Net contents**: ≤ 1% → PASS, ≤ 5% → REVIEW, else FAIL. **Proof tolerance** ±1.01
  (`parsers.PROOF_TOLERANCE`) to allow half-a-point of label rounding.
- **OCR bake-off**: Tesseract chosen over PaddleOCR for Phase 0 — Paddle pulls ~50 packages
  + a runtime model download (fights N-06) for no accuracy gain on clean synthetic renders.
  Revisit for the Phase 1 degradation set, or lean on the VLM pass there. Writeup in README.
- **Fixture generator gotcha**: `Sheet.wrapped()` must place each word at an explicit x with
  real inter-word gaps — an earlier version let words render touching and Tesseract read
  each line as one space-less token. If OCR output suddenly loses spaces, look here first.
- **VLM**: `vlm.py` has the full interface, `NullVlm` (default, used by every test), and
  `ClaudeVlm` (reads `ANTHROPIC_API_KEY`, model `claude-sonnet-5`). `pipeline._apply_vlm_
  fallback` retries only OCR-`UNREADABLE` text fields and still runs the VLM value through
  the normalization ladder — never a blind PASS. Not exercised by Phase 0 tests (no
  network); Phase 1 adds a recorded-cassette test.

### Phase 1 — not started

Priority order per §2.7: review screen (§2.5) → API + batch/streaming → multi-image +
manifest pre-flight → VLM cassette test → degradation set + preprocessing → CI → deploy.
Deploy target (decided with the user): **frontend on Vercel, backend container on
Render/Fly** (Azure Container Apps only if the TTB-infra story is wanted). Stack: React +
Vite + Tailwind.
