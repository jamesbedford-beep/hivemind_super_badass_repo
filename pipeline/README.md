# the organisation Vault Pipeline

Mirrors your Google Drive to a local folder of markdown files, refreshed nightly. The result is a plain-text knowledge base that AI tools (Claude Code, etc.) can search and read directly, and that Obsidian can open as a vault if you want a reading/linking interface. Obsidian itself is optional.

## What it syncs

- **My Drive**: everything you own
- **Shared drives**: every shared drive you're a member of (picked up automatically, including ones you join later)
- **Shared with me**: files shared directly with your account, with exact duplicates of shared-drive content removed automatically

Google Docs export directly to markdown. Sheets and Slides come down as xlsx/pptx, and those (plus uploaded Word/PowerPoint/PDF files) get a markdown sibling generated next to them (for example `report.docx` and `report.docx.md`).

**Skipped**: video, audio, archives, executables, and any file over 50 MB. Edit `excludes.txt` to change this.

## Requirements

- Windows 10/11 with winget (standard on current Windows)
- Python 3.10+ (Microsoft Store version is fine)

## Setup

1. Extract this zip anywhere
2. Open PowerShell in the extracted folder and run:

   ```powershell
   powershell -ExecutionPolicy Bypass -File setup.ps1
   ```

3. When the browser opens, sign in with your Google account and click Allow

That's it. The first sync runs immediately, then repeats nightly at 2:00 AM (or at next wake if the machine is asleep). Your vault lands at `Documents\MyVault`.

Options: `-VaultPath "D:\SomewhereElse"` or `-SyncTime "04:30"` on the setup command.

## The two rules

- **One-way.** Drive is the source of truth. Keep working in Google Docs as normal; changes flow down nightly.
- **Don't edit files under `drive\`.** The next sync overwrites them. Put your own notes in `notes\`, which the sync never touches.

## Access and privacy

- The Google grant is **read-only**: the pipeline cannot modify or delete anything in Drive
- You only get files your account can already open; the pipeline cannot expand your access
- Everything stays on your machine; nothing is uploaded anywhere
- Files shared as "view only, download disabled" cannot be exported and appear as errors in the log (this is expected)

## Known issues

- rclone's built-in Google client ID is being retired during 2026. When it stops working, follow https://rclone.org/drive/#making-your-own-client-id (about 10 minutes) and re-run setup.
- Comments and suggestions in Google Docs do not export
- Scanned PDFs convert poorly (no OCR)
- Complex formatting (nested tables, embedded charts) degrades in markdown

## Using it

- **With Claude Code / AI tools**: point the tool at the vault folder; it's all plain text
- **With Obsidian** (optional): File → Open folder as vault → select `MyVault`
- **Manual sync**: `powershell -ExecutionPolicy Bypass -File "%USERPROFILE%\Documents\MyVault\_pipeline\sync.ps1"`
- **Change schedule**: Task Scheduler → "MyVault-Sync"
- **Uninstall**: delete the "MyVault-Sync" task in Task Scheduler and delete the vault folder
