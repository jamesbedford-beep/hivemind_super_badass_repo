# the organisation's Drive -> Markdown vault sync
# One-way mirror of My Drive, all shared drives, and 'Shared with me' into a
# local markdown-first vault, then:
#   1. dedupe.py  - drops 'Shared with me' copies that duplicate shared-drive content
#   2. convert.py - converts remaining docx/pptx/xlsx/pdf to .md siblings
# The Drive grant is read-only: this script can never modify anything in Google Drive.

param(
    [string]$VaultPath = "$env:USERPROFILE\Documents\MyVault",
    [string]$RemoteName = "gdrive"
)

# Locate rclone: PATH first, then the winget install location
$rclone = (Get-Command rclone -ErrorAction SilentlyContinue).Source
if (-not $rclone) {
    $rclone = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Rclone*" -Recurse -Filter rclone.exe -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $rclone) { throw "rclone not found. Run setup.ps1 first." }

$pipeline = Split-Path -Parent $MyInvocation.MyCommand.Path
$dest = Join-Path $VaultPath "drive"
$log  = Join-Path $VaultPath "_pipeline\logs\sync-$(Get-Date -Format yyyy-MM-dd).log"
New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null

$flags = @(
    "--drive-export-formats", "md,xlsx,pptx",
    "--exclude-from", (Join-Path $pipeline "excludes.txt"),
    "--max-size", "50M",
    "--drive-skip-dangling-shortcuts",
    "--fast-list",
    "--log-file", $log,
    "--log-level", "INFO"
)

"=== Sync started $(Get-Date -Format o) ===" | Out-File $log -Append -Encoding utf8

# My Drive
& $rclone sync "${RemoteName}:" (Join-Path $dest "My Drive") @flags

# Shared drives (enumerated live, so newly created shared drives appear automatically)
$drives = & $rclone backend drives "${RemoteName}:" | ConvertFrom-Json
foreach ($d in $drives) {
    $name = $d.name -replace '[\\/:*?"<>|]', '_'
    & $rclone sync "${RemoteName},team_drive=$($d.id):" (Join-Path $dest $name) @flags
}

# Shared with me (files shared directly with this account)
& $rclone sync "${RemoteName},shared_with_me=true:" (Join-Path $dest "Shared with me") @flags

# Drop 'Shared with me' copies that duplicate shared-drive content
python (Join-Path $pipeline "dedupe.py") $dest | Out-File $log -Append -Encoding utf8

# Convert docx/pptx/xlsx/pdf to markdown siblings
python (Join-Path $pipeline "convert.py") $dest | Out-File $log -Append -Encoding utf8

"=== Sync finished $(Get-Date -Format o) ===" | Out-File $log -Append -Encoding utf8
