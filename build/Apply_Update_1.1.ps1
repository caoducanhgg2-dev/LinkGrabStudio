param(
    [string]$InstallDir = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$PackageRoot = $PSScriptRoot
$PayloadExe = Join-Path $PackageRoot "payload\LinkGrabStudio.exe"
$ManifestPath = Join-Path $PackageRoot "manifest.json"

function Show-Message([string]$Text, [string]$Title = "LinkGrab Studio 1.1") {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show($Text, $Title) | Out-Null
}

try {
    if (-not (Test-Path $PayloadExe) -or -not (Test-Path $ManifestPath)) {
        throw "Gói cập nhật thiếu payload hoặc manifest.json. Hãy giải nén lại toàn bộ file ZIP."
    }

    $Manifest = Get-Content $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $ActualHash = (Get-FileHash $PayloadExe -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($ActualHash -ne [string]$Manifest.sha256) {
        throw "File cập nhật không vượt qua kiểm tra SHA-256. Không có file cũ nào bị thay đổi."
    }

    if (-not $InstallDir) {
        $Candidates = @(
            (Join-Path $env:LOCALAPPDATA "Programs\LinkGrabStudio"),
            (Split-Path -Parent $PackageRoot),
            $PackageRoot
        )
        $InstallDir = $Candidates |
            Where-Object { Test-Path (Join-Path $_ "LinkGrabStudio.exe") } |
            Select-Object -First 1
    }
    if (-not $InstallDir -or -not (Test-Path (Join-Path $InstallDir "LinkGrabStudio.exe"))) {
        throw "Không tìm thấy LinkGrabStudio.exe. Hãy chạy: CapNhat_1.1.cmd \"D:\duong-dan\LinkGrabStudio\""
    }

    if (Get-Process -Name "LinkGrabStudio" -ErrorAction SilentlyContinue) {
        throw "LinkGrab Studio đang chạy. Hãy đóng ứng dụng rồi chạy lại cập nhật."
    }

    $TargetExe = Join-Path $InstallDir "LinkGrabStudio.exe"
    $DataDir = Join-Path $env:LOCALAPPDATA "LinkGrabStudio"
    $BackupRoot = Join-Path $DataDir "backups"
    $BackupDir = Join-Path $BackupRoot ("before_1.1_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
    New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
    Copy-Item $TargetExe (Join-Path $BackupDir "LinkGrabStudio.exe") -Force

    $StagedExe = "$TargetExe.update-new"
    try {
        Copy-Item $PayloadExe $StagedExe -Force
        $StagedHash = (Get-FileHash $StagedExe -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($StagedHash -ne [string]$Manifest.sha256) {
            throw "File tạm không khớp checksum."
        }
        Move-Item $StagedExe $TargetExe -Force
        $VersionInfo = @{
            version = [string]$Manifest.version
            updated_at = (Get-Date).ToString("o")
            backup_dir = $BackupDir
        } | ConvertTo-Json
        New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
        Set-Content (Join-Path $DataDir "version.json") $VersionInfo -Encoding UTF8
    } catch {
        Remove-Item $StagedExe -Force -ErrorAction SilentlyContinue
        Copy-Item (Join-Path $BackupDir "LinkGrabStudio.exe") $TargetExe -Force
        throw "Cập nhật thất bại; bản cũ đã được khôi phục tự động. Chi tiết: $($_.Exception.Message)"
    }

    Show-Message "Cập nhật LinkGrab Studio 1.1 thành công.`n`nLịch sử tải và dữ liệu chống trùng được giữ nguyên."
    Start-Process $TargetExe
} catch {
    Show-Message $_.Exception.Message "Không thể cập nhật LinkGrab Studio"
    exit 1
}
