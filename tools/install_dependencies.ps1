param()

$ErrorActionPreference = "Stop"

# 在 APP 项目目录中创建环境并安装依赖。
$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$venvDir = Join-Path $projectRoot ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$requirements = Resolve-Path (Join-Path $projectRoot "requirements.txt")

if (-not (Test-Path -LiteralPath $venvPython)) {
    python -m venv $venvDir
}

& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r $requirements
