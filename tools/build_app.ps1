# 此脚本使用带 BOM 的 UTF-8 编码，确保 Windows PowerShell 5.1 正确读取中文。
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
$originalBuildPath = $env:PATH
try {
    # 隔离其他软件的 DLL 搜索目录，避免把 Poppler 等软件的同名 ICU 库误打进 APP。
    $env:PATH = @(
        (Join-Path $projectRoot ".venv\Scripts"),
        (Join-Path $env:SystemRoot "System32"),
        $env:SystemRoot
    ) -join ";"
    & $venvPython @args
    if ($LASTEXITCODE -ne 0) {
        throw "APP 打包失败，退出码：$LASTEXITCODE"
    }
    # 构建成功后实际启动 EXE 自检，避免只检查打包成功而遗漏 DLL 加载失败。
    $exePath = Join-Path $distDir "$AppName.exe"
    $smokeTestProcess = Start-Process -FilePath $exePath -ArgumentList "--self-test" -PassThru -WindowStyle Hidden
    if (-not $smokeTestProcess.WaitForExit(30000)) {
        # Windows PowerShell 5.1 不支持 Kill(true)，使用系统工具结束本次自检进程树。
        & (Join-Path $env:SystemRoot "System32\taskkill.exe") /PID $smokeTestProcess.Id /T /F | Out-Null
        throw "APP 启动检查超时，请检查打包后的 Qt 和 DLL 依赖。"
    }
    if ($smokeTestProcess.ExitCode -ne 0) {
        throw "APP 启动检查失败，退出码：$($smokeTestProcess.ExitCode)"
    }
    Write-Host "APP 打包及启动检查通过：$exePath"
}
finally {
    $env:PATH = $originalBuildPath
    Pop-Location
}
