# Wiki: Operating Conventions

This wiki is a distilled, densely linked layer over the Drive mirror at `../drive/`
(the raw source corpus, refreshed nightly). `../drive/` is READ-ONLY: never edit
files there; all links point one way, wiki -> drive. Wiki files live here and are
versioned in git (repo root = this folder). Batch ingestion follows
`_ingest/PIPELINE.md`.

## Layout

- `sources/`: one summary note per ingested source document, opening with a
  markdown link to the original file in `../drive/`
- `concepts/`: one note per concept (idea, intervention, method, open question)
- `entities/`: one note per entity (organization, person, program, tool, place)
- `index.md`: global table of contents, grouped by theme
- `log.md`: append-only log: date, files changed, one-line why
- `_ingest/`: pipeline spec, ledger, concept index, staging (not knowledge; safe to ignore in Obsidian)

## Naming

- Filenames are Title Case, human-readable, no trailing punctuation
  (e.g. `Philanthropic derisking.md`). The filename is the wikilink target.
- Every note's frontmatter carries a stable kebab-case `uid` that never changes
  even if the title/filename is edited.

## Frontmatter schema (every note)

```yaml
---
type: atomic          # atomic | moc | source-archive
title: <human-readable title>
uid: <stable-kebab-slug>
created: <YYYY-MM-DD>    # when THIS NOTE was written
modified: <YYYY-MM-DD>   # bump on any edit, including link weaves
source:                  # provenance: original drive/ path(s) this note draws from
  - <../drive/...>
source_modified: <YYYY-MM-DD>   # when the SOURCE DOCUMENT last changed
source_author: <email or name>  # who owns the source document
authority: normal        # authoritative | normal | superseded
audience: unknown        # internal | external | unknown
genre: document          # document | ai-notes
supersedes: []           # uids this note replaces
superseded_by: <uid>     # set when a later note replaces this one
aliases: []              # synonyms; used for link resolution and dedupe
tags: []
status: clean            # clean | conflict
---
```

`created` and `source_modified` are different dates and are often years apart.
`created` says when the note was written; `source_modified` says how old the
underlying claim is. Precedence always uses `source_modified`.

The provenance fields come from the team manifest, which records them per
document at selection time. Copy them across rather than inferring them, and
leave a field out entirely rather than guessing at it.

## Atomicity (grain rule)

Atomic = one concept someone would plausibly link to from another note. NOT one
idea per paragraph. A major scoping doc typically yields 15-30 notes, not 150.
If a note grows past ~150 lines, split it.

## Linking

- Interlink aggressively with [[wikilinks]], woven inline into sentence syntax,
  not dumped as lists. A short `## Related notes` footer is allowed only when no
  inline spot reads naturally.
- Links are reciprocal: if A links to B, ensure B references A somewhere.
- When a new note connects to an older note, edit the older note to add the link
  and bump its `modified` date.
- Check `_ingest/concept-index.json` (and targeted ripgrep) for candidate link
  targets. Never load the whole vault into context.

## House rules (organisation-specific, highest priority)

- **No fabrication.** Never invent facts, numbers, quotes, or citations not in
  the source. Preserve real links verbatim. Every empirical claim cites its
  source note via wikilink; the source note links to the original drive/ file.
- Flag evidence strength (RCT vs observational vs expert estimate vs internal
  BOTEC) wherever the source distinguishes it. Flag low-confidence numbers.
- Contradictions are flagged, never silently resolved: set `status: conflict` on
  both notes and insert a `> [!warning] Conflict` callout naming both claims and
  sources. A human resolves. The precedence rules below are the ONLY exceptions,
  and each one requires the two sources to be versions of the same document.
- American spelling. No em-dashes anywhere. Percentages as %, large figures as
  $XM / $XB. Metric units.

## Precedence: which source wins

Not every disagreement is a genuine conflict. Most are the same document at two
points in time. Apply these in order, and stop at the first that fits.

1. **Same document, later version.** If two sources are recognisably the same
   document (same title stem, or one names the other) and one is later by
   `source_modified` or version marker, the later one wins. Write the claim from
   the newer source, add the older note's uid to `supersedes`, set
   `superseded_by` on the older note, and keep the older note rather than
   deleting it. Do NOT set `status: conflict`. Say so in one line:
   `> Updated by <newer source> on <date>; the earlier figure was <x>.`

2. **A human's notes over a machine transcript.** Where `genre: ai-notes`
   disagrees with a document, follow the document and cite the transcript only
   for colour. Never let a transcript overturn a written decision.

3. **Internal over external.** An `audience: external` copy is usually a
   simplified version of an internal document. On matters of fact, follow the
   internal one and note the external framing if it differs materially.

4. **Authoritative sources settle ties.** If one source is `authority:
   authoritative` and the other is not, follow it and record the other as a
   dissenting view in the same note, naming who holds it. This is a tie-break
   between comparable sources, never a licence to drop the disagreement.

5. **Everything else is a real conflict.** Two current documents, comparable
   standing, incompatible claims: flag it as above and let a human decide. When
   in doubt, this rule applies. Escalating is cheap; a wrong silent merge is not.

Never apply precedence across genuinely different subjects, and never use it to
resolve a disagreement about evidence, where both findings should stand with
their methods and dates recorded.

## Bookkeeping

- `_ingest/concept-index.json`: uid -> {path, title, aliases, tags, sources}.
  Update whenever a note is created, renamed, merged, or gains aliases.
- `_ingest/ledger.json`: every processed source file (path + SHA-256) and the
  notes it produced. Sources with unchanged hashes are skipped on rerun.
- Git: never edit existing notes without a clean baseline commit; commit after
  each ingestion batch with message `ingest: <scope> <date>`.

## Health checks (lint)

When asked to "lint the wiki", scan for: contradictions between notes; orphan
pages with no inbound links; synonym/duplicate topics to merge (use aliases);
dead links to `../drive/` paths that no longer exist; frontmatter schema
violations; em-dashes.
