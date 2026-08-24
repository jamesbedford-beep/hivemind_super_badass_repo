# Wrapper for access_manifest.py.
#
# Why this exists: Microsoft Store Python virtualizes %APPDATA%, so an rclone
# process spawned from Python reads a redirected copy of rclone.conf and may not
# see your real remotes. PowerShell is not virtualized, so we fetch the OAuth
# token here and pass it in.
#
# Usage:
#   .\access_manifest.ps1 -Vault "C:\Users\me\Documents\MyVault" `
#                         -Email teammate@example.org -Remote gdrive -Out katie-manifest.txt

param(
    [Parameter(Mandatory = $true)][string]$Vault,
    [string]$Email,
    [string]$Remote = "gdrive",
    [string]$MemberOf = "",
    [string]$Out = "manifest.txt",
    [switch]$NoVerifyFiles
)

$rclone = (Get-Command rclone -ErrorAction SilentlyContinue).Source
if (-not $rclone) {
    $rclone = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Rclone*" -Recurse -Filter rclone.exe -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $rclone) { throw "rclone not found" }

$py = Join-Path $PSScriptRoot "access_manifest.py"
$args = @("--vault", $Vault, "--out", $Out, "--remote", $Remote)
if ($MemberOf) { $args += @("--member-of", $MemberOf) }
if ($NoVerifyFiles) { $args += "--no-verify-files" }

if ($Email) {
    # Touch the remote so rclone refreshes and persists a current access token.
    & $rclone lsd "${Remote}:" --max-depth 1 | Out-Null
    $dump = & $rclone config dump | ConvertFrom-Json
    if (-not $dump.$Remote) {
        throw "remote '$Remote' not found in rclone config. Available: $($dump.PSObject.Properties.Name -join ', ')"
    }
    $token = ($dump.$Remote.token | ConvertFrom-Json).access_token
    if (-not $token) { throw "no access token for remote '$Remote'" }
    $args += @("--email", $Email, "--token", $token)

    if (-not $NoVerifyFiles) {
        # Build the file-id index here, not in Python: rclone launched from Store
        # Python reads a redirected rclone.conf and cannot see the right remotes.
        $idxPath = [System.IO.Path]::ChangeExtension($Out, "idindex.json")
        $index = @{}
        $drives = & $rclone backend drives "${Remote}:" | ConvertFrom-Json
        foreach ($d in $drives) {
            Write-Host "  indexing $($d.name)..."
            # Same --drive-export-formats as the sync, so Google Docs are listed
            # as .md exactly like the mirror. Without this they appear as .docx
            # and no mirror path matches.
            $json = & $rclone lsjson "${Remote},team_drive=$($d.id):" -R --files-only --no-modtime --no-mimetype `
                --drive-export-formats "md,xlsx,pptx"
            $files = $json | ConvertFrom-Json
            $index[$d.name] = @($files | ForEach-Object { @{ Path = $_.Path; ID = $_.ID } })
        }
        # Vaults whose notes derive from My Drive / Shared with me (the personal-Drive case,
        # per README) have no shared-drive membership to check -- access is
        # per-file. Index these two pseudo-drives too, keyed to match the top-level
        # segment access_manifest.py's wiki_sources() extracts from each note's
        # source: path, so file_access() can verify them the same way as team-drive
        # files. My Drive files are owned by this account (permissions.list works).
        # Shared with me files are owned by others; file_access() will correctly
        # come back unresolved for those (README's documented limitation), not
        # wrongly granted.
        Write-Host "  indexing My Drive..."
        $myDriveJson = & $rclone lsjson "${Remote}:" -R --files-only --no-modtime --no-mimetype `
            --drive-export-formats "md,xlsx,pptx"
        $myDriveFiles = $myDriveJson | ConvertFrom-Json
        $index["My Drive"] = @($myDriveFiles | ForEach-Object { @{ Path = $_.Path; ID = $_.ID } })

        Write-Host "  indexing Shared with me..."
        $sharedJson = & $rclone lsjson "${Remote}:" --drive-shared-with-me -R --files-only --no-modtime --no-mimetype `
            --drive-export-formats "md,xlsx,pptx"
        $sharedFiles = $sharedJson | ConvertFrom-Json
        $index["Shared with me"] = @($sharedFiles | ForEach-Object { @{ Path = $_.Path; ID = $_.ID } })

        $index | ConvertTo-Json -Depth 5 -Compress | Set-Content $idxPath -Encoding utf8
        $args += @("--id-index", $idxPath)
    }
}

python $py @args
