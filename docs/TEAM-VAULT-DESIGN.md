# Team Vault: design

Goal: a team lead curates once, in a GUI, and ships a single downloadable tool
that sets up a complete, access-correct, self-updating knowledge base for every
member of their team.

## The decision everything hangs on

The expensive step is distillation: reading documents and writing notes. In the
reference run that was ~40M tokens for ~700 documents, roughly two months of
analyst reading.

That gives three possible shapes:

| Shape | What ships | Cost per teammate | Freshness | Access correctness |
|---|---|---|---|---|
| A. Recipe only | the manifest + tooling; each machine distils for itself | full distillation each (~40M) | always current | perfect, built from their own Drive |
| B. Frozen pack | a prebuilt wiki, scoped centrally per person | ~zero | stale from day one | correct but recomputed by hand each time |
| C. **Recipe + prebuilt cache, filtered at install** | manifest + prebuilt wiki + tooling | ~zero to install, small nightly | current after first night | perfect, computed on their machine |

**C is the design.** The lead pays distillation once. Each teammate installs,
signs into their own Google account, and the installer keeps only the notes whose
source documents that person can actually open. From then on their copy updates
itself nightly and ingests anything new they can see.

This dissolves the two problems we kept hitting by hand: no central manifest per
recipient, and no scrubbing pass, because the filter runs where the credentials
are.

## What the team lead does

### 1. Connect
Sign in with Google, read-only. The tool lists the shared drives and folders the
lead can see and asks which are in play.

### 2. Curate
Three panes: **Drive tree** (browse and search), **Suggestions** (ranked, with a
reason attached to each), and **the Vault** (the basket). Click or drag to add.
Add a whole folder with one click, then prune.

Suggestions are ranked from signals the tool can compute without a model:

- **Referenced by others**: documents linked or cited from many other documents
- **Recently active**: modified in the last N days, or heavily commented
- **Structurally central**: sits at the top of a folder others hang off
- **Team-shared**: visible to most of the team already, so it is safe and useful
- **Genre**: strategy, scoping, evidence and decision documents score above
  agendas, invitations and logistics (the same triage that skipped ~60% of the
  reference corpus as noise)

Each suggestion shows its reason ("cited by 14 documents", "updated 3 days ago",
"strategy memo"). The lead accepts, rejects or ignores; rejections train nothing
but are remembered so the list stops re-suggesting them.

### 3. Review
The manifest, before anything is spent:

- counts and total text volume, with an **estimated build cost** in tokens and time
- **sensitivity flags** as a blocking gate: anything matching personnel, hiring,
  compensation, candidate or donor-profiling patterns is listed and must be
  explicitly kept or dropped. Default is drop.
- **coverage gaps**: folders with nothing selected, so obvious omissions surface
- **access preview**: for each named teammate, how much of the manifest they will
  actually receive, so the lead sees in advance that (for example) one person
  will get 383 of 401 documents and another 51

### 4. Build
Runs the existing pipeline with live progress: mirror, convert, triage, distil in
parallel, link serially, lint. Resumable, and it stops cleanly on a spend limit
rather than thrashing.

### 5. Ship
Produces one artifact: `TeamVault-Setup.zip`, plus a copy-paste message for the
team. The lead never runs a per-person export again.

## What a teammate does

1. Download, unzip, run one command.
2. Sign in with their own Google account, read-only.
3. The installer resolves which manifest documents they can open, keeps only the
   notes derived from those, and discards the rest before anything is written.
4. It registers their nightly Drive sync and incremental ingestion.
5. It prints where the vault is and how to point Obsidian or an AI assistant at it.

No manifest to request, no scrubbing, nothing to ask the lead for.

## The team manifest

One file, versioned, human-readable:

```json
{
  "team": "Strat-Init",
  "created": "2026-08-14",
  "created_by": "lead@example.org",
  "scopes": ["01_Interventions", "02 External Affairs"],
  "documents": [
    { "path": "01_Interventions/.../Scoping Doc.md",
      "added_by": "suggestion:referenced-by-14",
      "tags": ["strategy", "health"] }
  ],
  "excluded": [
    { "path": ".../Comp Benchmarking/...", "reason": "sensitivity:compensation" }
  ],
  "conventions": "wiki-tooling/WIKI-CONVENTIONS.md",
  "build": { "wiki_version": "2026-08-14", "notes": 2926, "sources": 694 }
}
```

It is the durable artifact. Rebuild from it at any time, diff it to see what a
team's context has become, hand it to another lead as a starting point.

## Technical shape

A local web app, because it needs three things a static page cannot have: Google
OAuth, the local filesystem, and the ability to run the pipeline.

- one command starts a local server and opens the browser
- backend reuses the existing Python and PowerShell pipeline unchanged
- frontend is a single page, no build step, no external services
- all state in the vault folder, so it is portable and inspectable

## Constraints worth stating plainly

- **The lead can only curate what the lead can see.** Teammates may have access
  to documents the lead does not, and those will never be suggested. The tool
  should say so rather than imply the manifest is complete.
- **Sensitivity is not the same as access.** Personal data stays out even when a
  recipient could open the original. The gate in step 3 is not optional.
- **The prebuilt cache ages.** It is correct on install day and then depends on
  the nightly job. If someone leaves the tool closed for a month, they should be
  told their copy is stale rather than silently served old answers.
- **First build is expensive and is the lead's cost.** Everything after is cheap.

## Build order

1. **Manifest format and the installer** (the filtering step). This alone
   replaces the per-person export work.
2. **Curate and Review screens.** Curation with suggestions and the sensitivity
   gate is where the lead's judgment actually lives.
3. **Build screen.** Wraps a pipeline that already works.
4. **Ship.** Packaging plus the message template.

Ship 1 and 2 first: together they remove the manual export and scrub entirely.
