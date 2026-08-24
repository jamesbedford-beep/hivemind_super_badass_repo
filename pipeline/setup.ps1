# the organisation Vault Pipeline - one-time setup
# Installs rclone + markitdown, connects your Google account (read-only),
# creates the vault, registers the nightly sync, and runs the first sync.
# Run from an extracted copy of the pipeline zip:
#   powershell -ExecutionPolicy Bypass -File setup.ps1

param(
    [string]$VaultPath = "$env:USERPROFILE\Documents\MyVault",
    [string]$SyncTime = "02:00",
    # Use a distinct RemoteName per Google account (e.g. "gdrive-second") so a
    # second account on the same machine gets its own sign-in and vault.
    [string]$RemoteName = "gdrive"
)

$TaskName = "Vault-Sync-" + (Split-Path $VaultPath -Leaf) + "-" + $RemoteName

$ErrorActionPreference = "Stop"
$src = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "== the organisation Vault pipeline setup =="

# --- rclone ---
$rclone = (Get-Command rclone -ErrorAction SilentlyContinue).Source
if (-not $rclone) {
    Write-Host "Installing rclone via winget..."
    winget install Rclone.Rclone --accept-source-agreements --accept-package-agreements
    $rclone = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Rclone*" -Recurse -Filter rclone.exe -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $rclone) { throw "rclone install failed. Install manually from https://rclone.org/downloads/ and re-run." }
Write-Host "rclone: $rclone"

# --- Python + markitdown ---
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python 3.10+ is required. Install it from the Microsoft Store or https://www.python.org/downloads/ (tick 'Add to PATH'), then re-run."
}
Write-Host "Installing markitdown (document converter)..."
python -m pip install --quiet "markitdown[docx,pptx,xlsx,pdf]"

# --- Vault structure + pipeline files ---
New-Item -ItemType Directory -Force "$VaultPath\drive", "$VaultPath\notes", "$VaultPath\_pipeline\logs" | Out-Null
Copy-Item "$src\sync.ps1", "$src\convert.py", "$src\dedupe.py", "$src\excludes.txt" "$VaultPath\_pipeline\" -Force
Copy-Item "$src\CLAUDE.md" "$VaultPath\CLAUDE.md" -Force  # guidance for AI tools reading the vault

# --- Google Drive connection (browser sign-in, READ-ONLY grant) ---
$remotes = & $rclone listremotes
if ($remotes -notcontains "${RemoteName}:") {
    Write-Host ""
    Write-Host "A browser window will now open. Sign in with the Google account you want to mirror and click Allow."
    Write-Host "The access requested is READ-ONLY: the pipeline can never change anything in your Drive."
    & $rclone config create $RemoteName drive scope=drive.readonly
}

# --- Nightly scheduled task ---
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$VaultPath\_pipeline\sync.ps1`" -VaultPath `"$VaultPath`" -RemoteName `"$RemoteName`""
$trigger  = New-ScheduledTaskTrigger -Daily -At $SyncTime
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 3)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "Nightly one-way sync of Google Drive to local markdown vault ($RemoteName)" -Force | Out-Null
Write-Host "Nightly sync registered for $SyncTime (runs at next wake if the machine is asleep)."

# --- First sync ---
Write-Host ""
Write-Host "Running the first sync now. Depending on Drive size this can take a while..."
& "$VaultPath\_pipeline\sync.ps1" -VaultPath $VaultPath -RemoteName $RemoteName
Write-Host ""
Write-Host "Done. Your vault is at: $VaultPath"
Write-Host "Logs: $VaultPath\_pipeline\logs"
