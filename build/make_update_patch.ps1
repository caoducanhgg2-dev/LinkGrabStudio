param(
    [string]$Version = "1.2.0"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BuiltExe = Join-Path $ProjectRoot "dist\LinkGrabStudio\LinkGrabStudio.exe"
if (-not (Test-Path $BuiltExe)) {
    throw "Chưa có LinkGrabStudio.exe. Hãy chạy build_windows.ps1 -SkipInstaller trước."
}

$PatchRoot = Join-Path $ProjectRoot "dist\update_patch"
$PackageDir = Join-Path $PatchRoot "LinkGrabStudio_Update_$Version"
$PayloadDir = Join-Path $PackageDir "payload"
$OutputZip = Join-Path $ProjectRoot "dist\LinkGrabStudio_Update_$Version.zip"
Remove-Item $PatchRoot -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $OutputZip -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $PayloadDir | Out-Null

Copy-Item $BuiltExe (Join-Path $PayloadDir "LinkGrabStudio.exe") -Force
Copy-Item (Join-Path $PSScriptRoot "Apply_Update_1.1.ps1") $PackageDir -Force
Copy-Item (Join-Path $PSScriptRoot "CapNhat_1.1.cmd") $PackageDir -Force
Copy-Item (Join-Path $PSScriptRoot "HUONG_DAN_CAP_NHAT_1.1.txt") $PackageDir -Force

$Hash = (Get-FileHash (Join-Path $PayloadDir "LinkGrabStudio.exe") -Algorithm SHA256).Hash.ToLowerInvariant()
$Manifest = [ordered]@{
    product = "LinkGrab Studio"
    version = $Version
    minimum_version = "1.0.0-preview.1"
    sha256 = $Hash
    preserves_user_data = $true
    rollback = $true
}
$Manifest | ConvertTo-Json | Set-Content (Join-Path $PackageDir "manifest.json") -Encoding UTF8

Compress-Archive -Path (Join-Path $PackageDir "*") -DestinationPath $OutputZip -CompressionLevel Optimal
$ZipHash = (Get-FileHash $OutputZip -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content (Join-Path $ProjectRoot "dist\SHA256SUMS_UPDATE.txt") "$ZipHash  $(Split-Path $OutputZip -Leaf)" -Encoding ascii
Write-Host "Update patch ready: $OutputZip"
