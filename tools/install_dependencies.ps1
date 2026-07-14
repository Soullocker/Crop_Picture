param()

$ErrorActionPreference = "Stop"

$pluginRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$venvDir = Join-Path $pluginRoot ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$requirements = Resolve-Path (Join-Path $pluginRoot "requirements.txt")

if (-not (Test-Path -LiteralPath $venvPython)) {
    python -m venv $venvDir
}

& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r $requirements
