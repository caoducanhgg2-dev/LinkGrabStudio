$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ToolsDir = Join-Path $ProjectRoot "tools"
$TempDir = Join-Path $ProjectRoot "build\temp-tools"

New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null
New-Item -ItemType Directory -Force -Path $TempDir | Out-Null

Write-Host "Downloading yt-dlp..."
Invoke-WebRequest `
    -Uri "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe" `
    -OutFile (Join-Path $ToolsDir "yt-dlp.exe")

Write-Host "Downloading Deno runtime..."
$DenoZip = Join-Path $TempDir "deno.zip"
Invoke-WebRequest `
    -Uri "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip" `
    -OutFile $DenoZip
Expand-Archive -Path $DenoZip -DestinationPath $ToolsDir -Force

Write-Host "Downloading FFmpeg essentials..."
$FfmpegZip = Join-Path $TempDir "ffmpeg.zip"
$FfmpegExtract = Join-Path $TempDir "ffmpeg"
Invoke-WebRequest `
    -Uri "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" `
    -OutFile $FfmpegZip
Expand-Archive -Path $FfmpegZip -DestinationPath $FfmpegExtract -Force
$FfmpegBin = Get-ChildItem -Path $FfmpegExtract -Filter "ffmpeg.exe" -Recurse | Select-Object -First 1
$FfprobeBin = Get-ChildItem -Path $FfmpegExtract -Filter "ffprobe.exe" -Recurse | Select-Object -First 1
if (-not $FfmpegBin -or -not $FfprobeBin) {
    throw "FFmpeg archive does not contain ffmpeg.exe and ffprobe.exe"
}
Copy-Item $FfmpegBin.FullName (Join-Path $ToolsDir "ffmpeg.exe") -Force
Copy-Item $FfprobeBin.FullName (Join-Path $ToolsDir "ffprobe.exe") -Force

& (Join-Path $ToolsDir "yt-dlp.exe") --version
& (Join-Path $ToolsDir "ffmpeg.exe") -version | Select-Object -First 1
& (Join-Path $ToolsDir "deno.exe") --version | Select-Object -First 1
Write-Host "Tools are ready in $ToolsDir"

