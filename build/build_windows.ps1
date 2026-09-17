$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

if (-not (Test-Path "tools\yt-dlp.exe")) {
    & "$PSScriptRoot\bootstrap_tools.ps1"
}

python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pytest

Remove-Item -Recurse -Force "dist\LinkGrabStudio" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "build\pyinstaller" -ErrorAction SilentlyContinue

python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --name "LinkGrabStudio" `
    --distpath "dist" `
    --workpath "build\pyinstaller" `
    --specpath "build\pyinstaller" `
    --add-data "$ProjectRoot\tools;tools" `
    --paths "$ProjectRoot" `
    "run_app.py"

$AppExe = Join-Path $ProjectRoot "dist\LinkGrabStudio\LinkGrabStudio.exe"
if (-not (Test-Path $AppExe)) {
    throw "Build failed: LinkGrabStudio.exe was not created"
}

Write-Host "Portable build ready: $AppExe"

$IsccCandidates = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
)
$Iscc = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($Iscc) {
    & $Iscc "$PSScriptRoot\installer.iss"
    Write-Host "Installer build completed."
} else {
    Write-Warning "Inno Setup 6 not found. Portable build is still available."
}
