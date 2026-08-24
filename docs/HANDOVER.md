# Drive-to-Markdown Knowledge Vault: Handover

Everything needed to replicate the knowledge vault setup for another Google
account (e.g. a second Google account): a nightly one-way mirror of that
account's Drive as markdown, optionally followed by the AI-built linked wiki.

## What it captures

For whichever Google account signs in during setup:

- **My Drive** (everything the account owns)
- **Every shared drive the account is a member of** (auto-discovered, including ones joined later)
- **Shared with me** (files shared directly with the account), with exact
  duplicates of shared-drive content removed automatically

You only ever get what the account can already open. The Google grant is
read-only; nothing in Drive can be modified by this pipeline.

## Part 1: the Drive mirror (scripts, no AI needed)

1. Copy this folder to the target machine. Requirements: Windows 10/11 with
   winget, Python 3.10+.
2. Open PowerShell in `pipeline\` and run:

   ```powershell
   powershell -ExecutionPolicy Bypass -File setup.ps1 -VaultPath "$env:USERPROFILE\Documents\SecondVault" -RemoteName "gdrive-second"
   ```

   Use a distinct `-VaultPath` and `-RemoteName` per account. On a machine that
   already runs a vault for another account, this keeps sign-ins, vaults, and
   scheduled tasks fully separate.
3. Sign in with the target account in the browser window and click Allow
   (read-only).

First sync runs immediately; a nightly refresh is registered in Task Scheduler.
Google Docs arrive as native markdown; Office/PDF files get converted `.md`
siblings. Media, archives, and files over 50 MB are skipped (edit
`excludes.txt` to change). Details in `pipeline\README.md`.

## Part 2: the linked wiki (optional, requires Claude Code)

The mirror alone is already AI-searchable. The wiki layer distills it into
atomic, wikilinked notes browsable in Obsidian. It is built by Claude Code
following the two documents in `wiki-conventions\`:

- `wiki-CLAUDE.md`: the conventions (note grain, frontmatter schema, linking
  and tagging rules, evidence-integrity house rules). Copy it to
  `<vault>\wiki\CLAUDE.md`.
- `PIPELINE.md`: the phased batch process (triage -> parallel atomization ->
  serial linking -> conflict scan). Copy to `<vault>\wiki\_ingest\PIPELINE.md`
  alongside `triage.py`.

To run it: open Claude Code in the vault folder and ask it to run the ingestion
pipeline per `wiki\_ingest\PIPELINE.md`, scoped to one folder of the mirror at
a time. Budget expectation from the reference run: a ~460-file shared drive consumed
roughly 35-40M tokens end to end, spread across several 5-hour usage windows
(the pipeline resumes cleanly after every quota pause). Start with the triage
step; it stops for human approval before anything expensive runs.

## Cautions

- Treat Drive as the source of truth: never edit files under `<vault>\drive\`
  (the nightly sync overwrites them). Own notes go in `<vault>\notes\`, wiki
  notes in `<vault>\wiki\`.
- "Shared with me" mirrors of another org's content should be treated with the
  same confidentiality as the originals; the vault is a local copy on this
  machine only.
- rclone's built-in Google client ID retires during 2026; when sign-in stops
  working, follow https://rclone.org/drive/#making-your-own-client-id and re-run
  setup.
