# Disseminating the knowledge base

**Goal:** never pay to distill the same document twice. The reading and distilling
(~35M tokens for the first drive) is the expensive, irreducible layer. Recipients
should inherit it for free rather than re-running the pipeline.

**Principle:** each person runs the *free* layer themselves (a local Drive mirror,
scripts only, no model tokens). They inherit the *expensive* layer (the distilled,
linked wiki) from a central copy. Exports are deterministic scripts, so each
additional recipient costs effectively nothing.

---

## Two regimes: pick per recipient

**Regime A: same shared-drive access (most internal teammates).**
Share the whole `wiki\` git repo. They run the mirror pipeline on their own Google
account, clone the wiki into it, and every citation and wikilink resolves locally
because all links are relative (`../drive/...`). Updates flow by `git pull`.
Effort: one push, one README. No scrub, no staleness.

**Regime B: partial or different access (external collaborators, restricted
folders, anyone who shouldn't see everything).**
The four-step export below. Produces a frozen, access-correct starter pack.

---

## Regime B: the export, step by step

### Step 1: inventory what the recipient can see

In order of preference:

1. **Drive membership** (covers ~90% of the corpus in three yes/no answers): is
   the recipient a member of 00_Operations, 01_Interventions, 02_External Affairs?
   Check via each shared drive's "Manage members" in Drive, or just ask them.
   Shared-drive files inherit access from membership, so per-file auditing is
   mostly redundant.
2. **A filename list from the recipient** for anything outside those drives
   (their My Drive, items shared directly with them). Ask for *full filenames
   with extensions*, not display titles; it materially improves match rates.

Do NOT attempt a per-file permissions audit of the whole mirror: ~2,900 API calls
to re-answer the same membership question hundreds of times.

### Step 2: match against our mirror

`export.py` intersects their list with the local mirror using fuzzy matching,
because filenames drift: case differences, `Copy of ` prefixes, `.docx.md`
conversion siblings, unicode variants (fullwidth colons/slashes). Output is three
buckets for human review:

- matched (the approved source set S)
- unmatched from their list (they have things we do not, fine)
- ambiguous (one name, several candidate files) -> human picks

### Step 3: select notes by provenance, then scrub

- **Selection rule (strict, the default):** a wiki note ships only if *every*
  entry in its frontmatter `source:` list is in S. This is what prevents leaking
  content derived from documents the recipient cannot see.
- **Optional looser tier:** notes whose sources are mostly-in-S can be listed for
  human review and included case by case. Raises yield when the recipient's
  access is narrow. Off by default.
- **Link scrub:** links between included notes are untouched. Links pointing at
  excluded notes become plain text, never left dangling, because a dead
  `[[Concept Note OpenPhil Confidential]]` still leaks a title.
- **Prose flag:** notes whose body text names an excluded document title get
  flagged for a targeted human skim (minutes, not hours). Mechanical scrubbing
  cannot catch these.

### Step 4: sensitivity gate, then package

- **Always-exclude list, regardless of access:** person assessments, candidate
  and hiring material, compensation data, donor wealth profiling. This is the
  standing exclusion set built during ingestion (`02 People and Culture`, the
  flagged individual documents, plus anything the pipeline's sensitivity
  backstop caught). Access is not the only test; personal data stays out even
  from people who could technically open the source.
- **Package contents:** selected wiki notes, the matched source documents in
  their `drive\...` relative structure (so citations resolve), a starter
  `CLAUDE.md`, and a short README. Zip it.
- **Verify before sending:** dead-link scan must return zero; skim the flagged
  notes; read the count report (notes included/excluded, and why).

---

## Known properties (not bugs)

- **Yield skews toward source summaries and single-document notes.** Richly
  merged entity notes often draw on 10+ sources; under the strict rule, one
  unshared source excludes the whole note. Expect high yield for recipients on
  all three shared drives, lower for narrow access.
- **The export is a snapshot.** It does not update. Re-run the same command to
  refresh a recipient.
- **A human skim is required** on the flagged subset. Do not skip it.

---

## Effort and cost

| Step | Who | Cost |
|---|---|---|
| Build `export.py` (once) | Claude | ~0 tokens (deterministic script) |
| Per recipient: match + select + scrub + package | one command | ~0 tokens |
| Per recipient: review buckets and flagged notes | human | 15-30 min |
| Recipient runs their own mirror | recipient | ~0 tokens (scripts) |

The whole point: the ~35M-token distillation is a sunk, one-time cost. Marginal
cost per additional recipient is a script run and a skim.

---

## Recommended sequence

1. Finish the three-drive wiki (in progress) and its lint pass.
2. Build the orientation layer: per-sector maps of content, a "read these first"
   shortlist, key-decisions log, who's-who, starter questions. A recipient
   handed 2,700 notes needs an on-ramp; this is what makes the pack usable.
3. Build `export.py` with the strict rule plus the always-exclude list.
4. Pilot on one recipient end to end, review what actually shipped, tune.
5. For teams: move to Regime A (shared repo) as the default, keeping Regime B
   for external or restricted cases.

## Longer-term option: let Drive permissions do the filtering

If dissemination becomes routine across many people, the scrub model stops
scaling (you re-derive access control by hand each time). The alternative is to
store wiki notes alongside the shared drive they derive from, so Google's own
membership rules decide who syncs what: no scrub, no staleness, correct by
construction. It requires partitioning the wiki by source drive and inverting the
current "mirror is read-only" principle, so it is a deliberate restructure, not a
quick change. Worth it only if per-recipient exports become frequent.
