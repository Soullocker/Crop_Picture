param(
    [string]$AppName = "科研图片裁剪"
)

$ErrorActionPreference = "Stop"

$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$mainScript = Resolve-Path (Join-Path $projectRoot "app\main.py")
$iconPath = Join-Path $projectRoot "assets\app_icon.ico"

if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "Virtual environment not found: $venvPython"
}

$args = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--onefile",
    "--name", $AppName
)

if (Test-Path -LiteralPath $iconPath) {
    $args += @("--icon", $iconPath)
    $args += @("--add-data", "$iconPath;assets")
}

$args += $mainScript

& $venvPython @args
