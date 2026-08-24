# Hivemind

Turn a team's Google Drive into a local, AI-readable knowledge base: a nightly
markdown mirror of every document, distilled into short cross-linked notes, kept
current automatically, and shareable so each person receives only what they are
already allowed to see.

**This repository contains the tooling only. No documents, no notes, no
organisation's knowledge.** Each team keeps its own vault privately on its own
machines.

## Why

Asking an AI assistant to search Drive gets you one keyword query at a time and a
few snippets. Mirroring Drive to local markdown lets an assistant grep the whole
corpus in seconds, read entire documents, and follow links between ideas.
Distilling that corpus into linked notes adds what Drive cannot: synthesis across
documents, flagged contradictions, and a browsable graph.

Reading is the expensive part. In the reference run, roughly 40M tokens covered
about 700 documents, comparable to two months of analyst reading. Everyone who
receives the result inherits that work for free.

## Quickstart

Open Claude Code and paste the setup prompt from the
[landing page](https://hivemind-super-badass-repo.pages.dev/), or do it by hand:

```powershell
cd teamvault
python server.py --vault "$env:USERPROFILE\Documents\TeamVault"
```

That starts a local web app and opens your browser. Requires Python 3.10+ and
rclone (`winget install Rclone.Rclone`). Nothing is uploaded anywhere.

## Repository map

| Folder | What it is |
|---|---|
| `teamvault/` | The local web app: connect, curate with ranked suggestions, review, build, ship. Plus `install.py`, which each teammate runs to get their own correctly-scoped copy. |
| `pipeline/` | The Drive mirror. `setup.ps1` authorises, `sync.ps1` runs nightly, converters turn Office and PDF into markdown, `nightly_wiki.ps1` keeps the notes current. |
| `wiki-tooling/` | Building and maintaining the notes: triage, lint, reindex, duplicate detection, change detection, plus `PIPELINE.md` and `WIKI-CONVENTIONS.md`. |
| `export-tooling/` | Sharing a slice safely: check what a person can open in Drive file by file, then build a pack containing only notes derived from those documents. |
| `docs/` | Design, handover and dissemination notes. |
| `index.html` | The landing page, published by Cloudflare Pages. |

## How the knowledge is built

1. **Triage** every file into ingest, summarise, or skip. Stops for human
   approval before anything expensive runs.
2. **Atomise** in parallel, one agent per document, each writing to its own
   staging folder so hundreds can run without colliding.
3. **Link** serially, one writer at a time, because deciding whether a note
   already exists means seeing everything filed so far. This merges duplicates
   and weaves the graph.
4. **Lint and maintain**: rebuild the index, find orphans and dead links, detect
   duplicates, and ingest changed documents nightly.

## The rules the notes follow

- **No fabrication.** Every empirical claim traces to a source document named in
  the note's frontmatter.
- **Evidence strength is flagged.** RCT, observational, expert estimate and
  back-of-envelope figures are labelled, never blended.
- **Contradictions are flagged, not resolved.** Conflicting notes carry
  `status: conflict` and a callout naming both claims. A human decides.
- **One concept per note**, linked rather than duplicated.

## Access and privacy

Two separate tests, and both must pass before anything is shared:

- **Access**: a note ships to someone only if every document it draws on is one
  that person can already open in Drive, checked file by file against Drive's
  own permissions.
- **Sensitivity**: personal material is excluded regardless of access.
  Performance reviews, compensation, hiring and candidate files, and donor
  profiling never enter a shared vault, even when the recipient could open the
  original.

`export-tooling/sensitive-excludes.txt` is a template of patterns. Add the
specific files and names relevant to your organisation in your local copy and
keep that copy out of version control.

## Keep out of this repository

`.gitignore` blocks these, and they should stay blocked:

- vaults, wikis, notes and packs, i.e. anything derived from real documents
- access manifests, which describe who can see what
- the mail layer, which is private to the person who built it
- working files: staging, prompts, per-run indexes

## Known issues

- rclone's shared Google client ID is being retired during 2026. When sign-in
  stops working, create your own client ID (about 10 minutes, link in
  `pipeline/README.md`) and re-run setup.
- Windows only for now: the sync and scheduling scripts are PowerShell.
- Microsoft Store Python virtualises `%APPDATA%`, so rclone is always invoked
  with an explicit `--config` path and decoded as UTF-8.
