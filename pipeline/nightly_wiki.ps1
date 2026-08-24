# Nightly wiki refresh: keep the distilled wiki in step with the Drive mirror.
#
# Runs AFTER the nightly Drive sync. Detects new and changed source documents,
# adds a slice of the archive backlog, and ingests a capped number of documents
# via Claude Code in headless mode. Skips entirely (spending nothing) when there
# is no work.
#
# Safety and cost controls:
#   - hard cap on documents per night (-MaxDocs, default 12)
#   - skips archives from the live path, plus People and Culture, comp, hiring,
#     candidate and donor-profiling material (never ingested)
#   - stops on any spend-limit or auth failure and logs it, rather than retrying
#   - commits to git, so every night is revertible
#
# Register with:
#   powershell -ExecutionPolicy Bypass -File nightly_wiki.ps1 -Register

param(
    [string]$VaultPath = "$env:USERPROFILE\Documents\MyVault",
    [int]$MaxDocs = 12,
    [string]$Model = "sonnet",
    [string]$RunAt = "03:15",
    [switch]$Register,
    [switch]$DryRun
)

$wiki = Join-Path $VaultPath "wiki"
$log  = Join-Path $VaultPath ("_pipeline\logs\wiki-nightly-{0}.log" -f (Get-Date -Format yyyy-MM-dd))
New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null

function Log($msg) {
    $line = "{0}  {1}" -f (Get-Date -Format "HH:mm:ss"), $msg
    $line | Tee-Object -FilePath $log -Append
}

if ($Register) {
    $self = $MyInvocation.MyCommand.Path
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$self`" -VaultPath `"$VaultPath`" -MaxDocs $MaxDocs" `
        -WorkingDirectory (Join-Path $VaultPath "wiki")
    $trigger  = New-ScheduledTaskTrigger -Daily -At $RunAt
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Hours 2)
    Register-ScheduledTask -TaskName "the organisation-Wiki-Nightly" -Action $action -Trigger $trigger `
        -Settings $settings -Description "Nightly incremental ingestion into the the organisation wiki" -Force | Out-Null
    Write-Host "Registered 'the organisation-Wiki-Nightly' for $RunAt (after the 2:00 AM Drive sync), cap $MaxDocs docs/night."
    return
}

Log "=== nightly wiki refresh start ==="

# 1. Detect what changed in the mirror (free, deterministic)
python (Join-Path $wiki "_ingest\detect_changes.py") 2>&1 | Tee-Object -FilePath $log -Append

# 2. Choose tonight's capped batch: live changes first, then an archive slice
python (Join-Path $wiki "_ingest\pick_batch.py") $MaxDocs 2>&1 | Tee-Object -FilePath $log -Append
if ($LASTEXITCODE -eq 3) {
    Log "nothing to ingest tonight; spending nothing"
    Log "=== done ==="
    return
}

$tonight = Get-Content (Join-Path $wiki "_ingest\tonight.txt") -ErrorAction SilentlyContinue
if (-not $tonight) { Log "no batch file; exiting"; return }
Log ("batch: {0} documents" -f $tonight.Count)

if ($DryRun) { Log "dry run, stopping before ingestion"; return }

# 3. Ingest via Claude Code, headless
$docList = ($tonight | ForEach-Object { "- $_" }) -join "`n"
$prompt = @"
You are running one incremental ingestion pass on this wiki. Work carefully; you are the only writer.

Read first: $wiki\CLAUDE.md (conventions: frontmatter schema, naming, atomicity grain, linking, house rules) and $wiki\_ingest\concept-index.json.

Ingest these source documents from the read-only mirror at $VaultPath\drive\ :
$docList

For each document:
1. Read it in full. Strip operational noise.
2. Write atomic notes at the conventions grain (one reusable, linkable concept or entity per note; a modest memo yields 5-10, NOT one per paragraph), plus ONE source summary note in sources/.
3. DEDUPE FIRST: check concept-index.json by uid, title and alias before creating anything. If an equivalent note exists, MERGE into it (union source lists and aliases, bump modified) rather than creating a near-duplicate. Prefer merging over proliferation.
4. Weave [[wikilinks]] inline both ways, and add the note to index.md under a fitting theme.
5. If a document is archive material, mark its notes: add 'archive' and 'stale' to tags, set status: archived, and open the body with a callout line: "> [!warning] Archived source, not current. Ingested $(Get-Date -Format yyyy-MM-dd)."
6. SENSITIVITY: if a document assesses or profiles a named individual, or contains compensation, candidate, or donor wealth data, do NOT atomize it. Write nothing for it and note the skip.
7. Append one line per document to log.md dated $(Get-Date -Format yyyy-MM-dd), and record it in _ingest/ledger.json with its sha256 so it is not reprocessed.

HARD RULES: never modify anything under $VaultPath\drive (read-only). Never lose facts or evidence-strength flags. Flag contradictions with a conflict callout and status: conflict rather than resolving them. No em-dashes. No fabrication.

Do NOT run git. This script commits your work for you after you finish.
Print a one-paragraph summary of what you ingested, merged, and skipped.
"@

Log "invoking Claude Code (model: $Model) with cwd=$wiki"
# Must run with the vault as the working directory. Scheduled tasks start in
# C:\WINDOWS\system32, and Claude Code sandboxes file access to its working
# directory tree, so from there it cannot read the vault at all.
Push-Location $wiki
try {
    $out = $prompt | claude -p --model $Model --permission-mode acceptEdits --add-dir $VaultPath 2>&1
} finally {
    Pop-Location
}
$out | Tee-Object -FilePath $log -Append | Out-Null

if ($out -match "spend limit|usage limit|rate limit|quota") {
    Log "STOPPED: hit a usage or spend limit. No retry tonight; tomorrow's run resumes from the ledger."
} elseif ($out -match "Invalid API key|authentication|not logged in") {
    Log "STOPPED: Claude authentication problem. Sign in interactively, then the next run recovers."
}

# 4. Bookkeeping: mark the batch processed so it never re-queues, then reindex,
#    lint, and commit. Marking happens here rather than relying on the agent,
#    because a document can be correctly processed with zero notes produced.
python (Join-Path $wiki "_ingest\mark_processed.py") 2>&1 | Tee-Object -FilePath $log -Append
python (Join-Path $wiki "_ingest\reindex.py") 2>&1 | Tee-Object -FilePath $log -Append
python (Join-Path $wiki "_ingest\lint.py") 2>&1 | Tee-Object -FilePath $log -Append
git -C $wiki add -A 2>$null
git -C $wiki commit -m "nightly: bookkeeping $(Get-Date -Format yyyy-MM-dd)" --quiet 2>$null

Log "=== done ==="
