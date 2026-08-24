# Vault Ingestion Pipeline

Batch-ingests the Drive mirror into the wiki. Based on the community
"Obsidian Vault Ingestion Pipeline" spec, amended per project decisions of
2026-07-18. Conventions (frontmatter, naming, linking, house rules) live in
`../CLAUDE.md` and are not repeated here.

## Config (pinned)

- `SOURCE_DIR`: `C:\Users\you\Documents\MyVault\drive\<scope>` (per-run scope, e.g. one shared drive)
- `VAULT_ROOT`: `C:\Users\you\Documents\MyVault\wiki`
- `CONCURRENCY`: 8 parallel subagents in Phase 1
- `APPLY_MODE`: `review` for the first ~20 documents of a corpus, then `auto`
  with a git commit per sector (diff review at full scale is impractical;
  git revert is the safety net)

## Global invariants

- **Git snapshot first.** Repo root is `wiki\` ONLY (never the 2.9 GB drive
  mirror). Clean baseline commit before any run; commit per sector during runs.
- **`../drive/` is read-only.** Phase 2 edits wiki notes only.
- **Idempotent.** `_ingest/ledger.json` records every source (path + SHA-256)
  and notes produced. Unchanged hashes are skipped on rerun; this is also the
  nightly-update mechanism.
- **No fabrication** (see CLAUDE.md house rules; highest priority).
- **Never load the whole vault into context.** Use `_ingest/concept-index.json`
  plus targeted ripgrep.

## Phase 0: Discovery, triage, snapshot — STOP FOR APPROVAL

1. Enumerate every `.md` under SOURCE_DIR (native exports AND `.docx.md`-style
   conversion siblings). Hash each. Refresh ledger.
2. **Triage every file into tiers** (the corpus is not clean):
   - `ingest`: substantive strategy/scoping/evidence/decision docs
   - `summarize-only`: transcripts and very large files (>300 KB): produce ONE
     source summary note each, read in chunks, no full atomization
   - `skip`: DEPRECATED_* files, trivial files (<2 KB), scraps, duplicate
     conversion siblings whose original is also ingested, pure logistics
     (agendas, scheduling), spreadsheet conversions with no prose
3. Git snapshot.
4. Print the plan: counts and full file list per tier, estimated notes,
   estimated token cost, APPLY_MODE. **Stop for one human confirmation.**

## Phase 1: Parallel atomization (SAFE to parallelize)

Fan out up to CONCURRENCY subagents, one source file per subagent. Each:

1. Reads exactly one source file (chunked if large). Never reads the vault.
2. Strips operational noise (signatures, reply chains, boilerplate, nav chrome).
3. Deconstructs into atomic notes at the CLAUDE.md grain (one linkable concept
   per note, 15-30 for a major doc, NOT one idea per paragraph), plus one
   source summary note for `sources/`.
4. Rewrites in a direct, plain voice preserving technical precision and all
   evidence-strength distinctions. No fabrication.
5. Writes ONLY to its private staging folder `_ingest/staging/<source-slug>/`
   with full frontmatter, `status: clean`, and NO links yet.
6. Emits `_ingest/manifests/<source-slug>.json`: notes created + raw candidate
   link terms for Phase 2.

No promotion to the wiki in this phase. No editing pre-existing files. Zero
write contention by construction.

## Phase 2: Merge, dedupe, stitch (SERIAL — single coordinator)

Work in batches (~15-25 staged sources per batch) to stay inside context; use
the concept index, not full-vault reads. Per batch:

1. **Promote and dedupe.** Match staged notes against the concept index by
   title, alias, and semantic equivalence. Merge duplicates (union `source`
   lists, collect aliases, keep clearest phrasing); otherwise promote as-is.
2. **Weave bidirectional links inline** per CLAUDE.md linking rules.
3. **Cascade into older notes**: add reciprocal links to pre-existing notes,
   bump their `modified`. (Write-contention-prone; hence serial.)
4. Update concept-index.json, ledger, index.md, log.md. Git commit per sector.

In `review` mode: write proposed changes, produce a diff, stop for approval
before applying.

## Phase 3: Conflict detection (flag, never overwrite)

Scan notes touched this run (not the whole vault) for contradictions against
their link neighborhoods. On conflict: `status: conflict` on both notes +
`> [!warning] Conflict` callout naming both claims and sources. Never pick a
winner silently.

## Phase 4: Report

Notes created / merged / edited, links added, conflicts flagged, tier counts
processed vs skipped, `git diff --stat`, ledger and index locations. Offer to
commit as `ingest: <scope> <date>`.
