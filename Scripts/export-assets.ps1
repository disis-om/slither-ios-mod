<#
.SYNOPSIS
    Re-export every editable asset out of the bundle's SWF into assets\.

.DESCRIPTION
    Regenerates the browsable asset tree (images, fonts, shapes, sprites, texts
    and the symbol-to-class map). The export is a copy for inspection - nothing
    reads it at runtime. To change an asset, replace it inside the SWF with
    FFDec's -replace, then re-run this script to refresh the view.

    FFDec exits non-zero on this SWF because its DoABC2 tag is an AOT stub it
    cannot parse. The export still completes, so the exit code is ignored and
    the exported file count is checked instead.
#>
[CmdletBinding()]
param(
    [string] $FfdecJar = "$env:USERPROFILE\Downloads\ffdec_26.2.1\ffdec-cli.jar"
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$swf  = Get-ChildItem -Path (Join-Path $root 'extracted\Payload') -Filter '*.swf' -Recurse -Depth 1 |
        Select-Object -First 1

if (-not $swf)              { throw "No .swf found under extracted\Payload." }
if (-not (Test-Path $FfdecJar)) { throw "FFDec not found at $FfdecJar. Pass -FfdecJar <path>." }

$out = Join-Path $root 'assets'
if (Test-Path $out) { Remove-Item -Path $out -Recurse -Force }

Write-Host "Exporting from $($swf.Name) ..."
& java -Xmx8g -jar $FfdecJar -export `
    image,shape,morphshape,sprite,font,sound,binaryData,symbolClass,text `
    $out $swf.FullName 2>&1 | Out-Null

$count = (Get-ChildItem -Path $out -Recurse -File -ErrorAction SilentlyContinue | Measure-Object).Count
if ($count -lt 1) { throw "Export produced no files - check the FFDec path and the SWF." }

Write-Host "Exported $count files to $out"
Get-ChildItem -Path $out -Directory | ForEach-Object {
    $n = (Get-ChildItem -Path $_.FullName -Recurse -File | Measure-Object).Count
    "{0,-14} {1}" -f $_.Name, $n
}
