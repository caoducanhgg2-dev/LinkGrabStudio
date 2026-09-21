param(
    [string]$InstallDir = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$PackageRoot = $PSScriptRoot
$PayloadExe = Join-Path $PackageRoot "payload\LinkGrabStudio.exe"
$ManifestPath = Join-Path $PackageRoot "manifest.json"

function Show-Message([string]$Text, [string]$Title = "LinkGrab Studio Update") {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show($Text, $Title) | Out-Null
}

function Select-InstallDirectory {
    Add-Type -AssemblyName System.Windows.Forms
    $Dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $Dialog.Description = "Chon dung thu muc dang chua LinkGrabStudio.exe ma ban thuong mo."
    $Dialog.ShowNewFolderButton = $false
    $DefaultDir = Join-Path $env:LOCALAPPDATA "Programs\LinkGrabStudio"
    if (Test-Path (Join-Path $DefaultDir "LinkGrabStudio.exe")) {
        $Dialog.SelectedPath = $DefaultDir
    }
    $Result = $Dialog.ShowDialog()
    if ($Result -ne [System.Windows.Forms.DialogResult]::OK) {
        throw "Ban chua chon thu muc cai dat. Khong co file nao bi thay doi."
    }
    return $Dialog.SelectedPath
}

try {
    if (-not (Test-Path $PayloadExe) -or -not (Test-Path $ManifestPath)) {
        throw "Goi cap nhat thieu payload hoac manifest.json. Hay giai nen lai toan bo file ZIP."
    }

    $Manifest = Get-Content $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $ActualHash = (Get-FileHash $PayloadExe -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($ActualHash -ne [string]$Manifest.sha256) {
        throw "File cap nhat khong vuot qua kiem tra SHA-256. Khong co file cu nao bi thay doi."
    }

    if (-not $InstallDir) {
        $InstallDir = Select-InstallDirectory
    }
    if (-not $InstallDir -or -not (Test-Path (Join-Path $InstallDir "LinkGrabStudio.exe"))) {
        throw "Thu muc da chon khong co LinkGrabStudio.exe. Hay chay lai va chon dung thu muc."
    }

    $InstallDir = (Resolve-Path $InstallDir).Path
    Add-Type -AssemblyName PresentationFramework
    $Confirm = [System.Windows.MessageBox]::Show(
        "Se cap nhat dung file tai:`n$InstallDir\LinkGrabStudio.exe`n`nNhan Yes de tiep tuc.",
        "Xac nhan LinkGrab Studio $($Manifest.version)",
        [System.Windows.MessageBoxButton]::YesNo,
        [System.Windows.MessageBoxImage]::Question
    )
    if ($Confirm -ne [System.Windows.MessageBoxResult]::Yes) {
        throw "Da huy cap nhat. Khong co file nao bi thay doi."
    }

    if (Get-Process -Name "LinkGrabStudio" -ErrorAction SilentlyContinue) {
        throw "LinkGrab Studio dang chay. Hay dong ung dung roi chay lai cap nhat."
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
            throw "File tam khong khop checksum."
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
        throw "Cap nhat that bai; ban cu da duoc khoi phuc tu dong. Chi tiet: $($_.Exception.Message)"
    }

    Show-Message "Cap nhat LinkGrab Studio $($Manifest.version) thanh cong.`n`nFile da cap nhat:`n$TargetExe`n`nLich su tai va du lieu chong trung duoc giu nguyen." "LinkGrab Studio $($Manifest.version)"
    Start-Process $TargetExe
} catch {
    Show-Message $_.Exception.Message "Khong the cap nhat LinkGrab Studio"
    exit 1
}
