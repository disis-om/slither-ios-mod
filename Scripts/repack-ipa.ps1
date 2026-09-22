<#
.SYNOPSIS
    Repack the edited app bundle in extracted\ back into an installable IPA.

.DESCRIPTION
    An IPA is a plain ZIP whose root contains a single Payload\ directory.
    This script zips extracted\Payload into dist\<name>.ipa and writes a
    SHA-256 hash file next to it, mirroring the packaging step used by the
    Wyrm iOS CI workflow.

    The output is intentionally UNSIGNED. The stale _CodeSignature directory
    and embedded.mobileprovision are dropped by default because any edit to
    the bundle invalidates them; esign / AltStore / Sideloadly re-sign on
    install. Pass -KeepSignature to leave them in place.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File Scripts\repack-ipa.ps1
    powershell -ExecutionPolicy Bypass -File Scripts\repack-ipa.ps1 -Name slither-mod-v1
#>
[CmdletBinding()]
param(
    [string] $Name,
    [switch] $KeepSignature,
    [switch] $SkipChecks
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$root     = Split-Path -Parent $PSScriptRoot
$payload  = Join-Path $root 'extracted\Payload'
$distDir  = Join-Path $root 'dist'

if (-not (Test-Path $payload)) {
    throw "Payload not found at $payload. Unpack the source IPA into extracted\ first."
}

if (-not $SkipChecks) {
    # mod-ui\ is the source of truth for the menu pages, and the contract test
    # catches an edit that would install but not run. Pass -SkipChecks to pack
    # the bundle exactly as it sits on disk.
    & python (Join-Path $PSScriptRoot 'check-mod-ui-js.py')
    if ($LASTEXITCODE -ne 0) { throw 'mod menu JavaScript does not parse' }

    & node (Join-Path $root 'Tests/mod_ui_logic_test.js')
    if ($LASTEXITCODE -ne 0) { throw 'mod menu logic test failed' }

    & python (Join-Path $PSScriptRoot 'patch-mod-menu.py')
    if ($LASTEXITCODE -ne 0) { throw 'patch-mod-menu.py failed' }

    & python (Join-Path $root 'Tests/bundle_contract_test.py')
    if ($LASTEXITCODE -ne 0) { throw 'bundle contract test failed' }
}

if (-not $Name) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $Name  = "slither-ios-repack-$stamp"
}
if ($Name -notmatch '\.ipa$') { $Name = "$Name.ipa" }

# Stage a clean copy so the working tree in extracted\ is never mutated.
$stage = Join-Path ([System.IO.Path]::GetTempPath()) ("ipa-stage-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stage -Force | Out-Null
try {
    Copy-Item -Path $payload -Destination (Join-Path $stage 'Payload') -Recurse -Force

    if (-not $KeepSignature) {
        Get-ChildItem -Path (Join-Path $stage 'Payload') -Filter '_CodeSignature' -Recurse -Directory |
            ForEach-Object { Remove-Item -Path $_.FullName -Recurse -Force }
        Get-ChildItem -Path (Join-Path $stage 'Payload') -Filter 'embedded.mobileprovision' -Recurse -File |
            ForEach-Object { Remove-Item -Path $_.FullName -Force }
    }

    if (-not (Test-Path $distDir)) { New-Item -ItemType Directory -Path $distDir -Force | Out-Null }
    $out = Join-Path $distDir $Name
    if (Test-Path $out) { Remove-Item -Path $out -Force }

    # Write entries by hand: ZipFile::CreateFromDirectory on Windows PowerShell
    # emits backslash separators, which iOS installers reject.
    $zip = [System.IO.Compression.ZipFile]::Open($out, [System.IO.Compression.ZipArchiveMode]::Create)
    try {
        $prefix = (Resolve-Path $stage).Path.TrimEnd('\') + '\'
        Get-ChildItem -Path $stage -Recurse -File | ForEach-Object {
            $entry = $_.FullName.Substring($prefix.Length).Replace('\', '/')
            [void][System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $zip, $_.FullName, $entry, [System.IO.Compression.CompressionLevel]::Optimal)
        }
    }
    finally { $zip.Dispose() }

    $hash = (Get-FileHash -Path $out -Algorithm SHA256).Hash.ToLower()
    $size = (Get-Item $out).Length
    "$hash  $Name" | Out-File -FilePath "$out.sha256" -Encoding ascii

    Write-Host ""
    Write-Host "Packed : $out"
    Write-Host "Size   : $([math]::Round($size / 1MB, 2)) MB"
    Write-Host "SHA256 : $hash"
    Write-Host "Signed : no - re-sign with esign / AltStore / Sideloadly before installing."
    Write-Host ""
}
finally {
    Remove-Item -Path $stage -Recurse -Force -ErrorAction SilentlyContinue
}
