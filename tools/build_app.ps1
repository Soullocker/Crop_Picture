param(
    [string]$AppName = "Crop_Picture"
)

$ErrorActionPreference = "Stop"

$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$mainScript = Resolve-Path (Join-Path $projectRoot "app\main.py")
$assetsDir = Join-Path $projectRoot "assets"
$pngIconPath = Join-Path $assetsDir "app_icon.png"
$icoIconPath = Join-Path $assetsDir "app_icon.ico"
$buildDir = Join-Path $projectRoot "build"
$distDir = Join-Path $projectRoot "dist"
$generatedIconPath = Join-Path $buildDir "app_icon.ico"

if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "Virtual environment not found: $venvPython"
}

$iconForExe = $null
if (Test-Path -LiteralPath $icoIconPath) {
    $iconForExe = $icoIconPath
} elseif (Test-Path -LiteralPath $pngIconPath) {
    New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
    & $venvPython -c "from PIL import Image; Image.open(r'$pngIconPath').save(r'$generatedIconPath', format='ICO', sizes=[(256, 256)])"
    $iconForExe = $generatedIconPath
}

$args = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--onefile",
    "--name", $AppName,
    "--distpath", $distDir,
    "--workpath", $buildDir,
    "--specpath", $buildDir
)

if ($iconForExe) {
    $args += @("--icon", $iconForExe)
}

if (Test-Path -LiteralPath $pngIconPath) {
    $args += @("--add-data", "$pngIconPath;assets")
}

if (Test-Path -LiteralPath $icoIconPath) {
    $args += @("--add-data", "$icoIconPath;assets")
}

$args += $mainScript

Push-Location $projectRoot
try {
    & $venvPython @args
}
finally {
    Pop-Location
}
