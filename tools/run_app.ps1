$ErrorActionPreference = "Stop"

$pythonExe = Resolve-Path (Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe")
$appPath = Resolve-Path (Join-Path $PSScriptRoot "..\app\main.py")

& $pythonExe $appPath
exit $LASTEXITCODE
