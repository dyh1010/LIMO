param(
    [Parameter(Mandatory = $true)]
    [string]$OutputDir,
    [Parameter(Mandatory = $true)]
    [string]$InputDir,
    [double]$OpeningHeightRatio = 0.62,
    [double]$OpeningMarginRatio = 0.0
)

$ErrorActionPreference = 'Stop'
function Convert-ToWslPath([string]$Path) {
    $fullPath = [IO.Path]::GetFullPath($Path)
    $drive = $fullPath.Substring(0, 1).ToLowerInvariant()
    $rest = $fullPath.Substring(2).Replace('\', '/')
    return "/mnt/$drive$rest"
}

New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$stdoutPath = Join-Path $OutputDir 'offline_dual_detector.stdout.log'
$stderrPath = Join-Path $OutputDir 'offline_dual_detector.stderr.log'
$pidPath = Join-Path $OutputDir 'offline_dual_detector.windows.pid'
$wslOutputDir = Convert-ToWslPath $OutputDir
$wslInputDir = Convert-ToWslPath $InputDir
$worker = '/home/dyh/robotics/workspaces/limo_cleanup_ws/scripts/run_offline_perception_worker.sh'
$bottleModel = '/mnt/c/Users/DYH/Desktop/limo_graphtest/models/nongfu_yolov8n_best.pt'
$binModel = '/mnt/c/Users/DYH/Desktop/limo_graphtest/models/trash_bin_yolov8n_best.pt'

$arguments = @(
    '-d', 'Ubuntu-22.04', '--', $worker,
    '--input-dir', $wslInputDir,
    '--bottle-model', $bottleModel,
    '--bin-model', $binModel,
    '--opening-height-ratio', $OpeningHeightRatio.ToString('0.00', [Globalization.CultureInfo]::InvariantCulture),
    '--opening-margin-ratio', $OpeningMarginRatio.ToString('0.00', [Globalization.CultureInfo]::InvariantCulture),
    '--output-dir', $wslOutputDir
)

$process = Start-Process -FilePath 'wsl.exe' -ArgumentList $arguments `
    -WindowStyle Hidden -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath -PassThru
Set-Content -LiteralPath $pidPath -Value $process.Id -Encoding ASCII
Write-Output "started windows_pid=$($process.Id) stdout=$stdoutPath stderr=$stderrPath"
