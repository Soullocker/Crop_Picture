param(
    [string]$InputPath,
    [string]$ImageName,
    [string]$OutputDir,
    [int]$Padding = 8
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$pythonExe = Resolve-Path (Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe")
$scriptPath = Resolve-Path (Join-Path $PSScriptRoot "..\scripts\crop_picture.py")

Write-Host "Crop blank margins from one image"
Write-Host ""
Write-Host "Enter a full image path, or enter a folder path plus an image filename."
Write-Host ""

if (-not $PSBoundParameters.ContainsKey("InputPath") -or [string]::IsNullOrWhiteSpace($InputPath)) {
    $InputPath = Read-Host "Input image path or image folder path"
}

if (-not $PSBoundParameters.ContainsKey("ImageName")) {
    $ImageName = Read-Host "If the previous path is a folder, enter image filename; otherwise press Enter"
}

if (-not $PSBoundParameters.ContainsKey("OutputDir") -or [string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Read-Host "Output folder path"
}

if (-not $PSBoundParameters.ContainsKey("Padding")) {
    $paddingText = Read-Host "Padding pixels, press Enter for 8"
    if (-not [string]::IsNullOrWhiteSpace($paddingText)) {
        $Padding = [int]$paddingText
    }
}

$arguments = @($scriptPath, "--input", $InputPath, "--output", $OutputDir, "--padding", $Padding)
if (-not [string]::IsNullOrWhiteSpace($ImageName)) {
    $arguments += @("--name", $ImageName)
}

& $pythonExe @arguments
exit $LASTEXITCODE
