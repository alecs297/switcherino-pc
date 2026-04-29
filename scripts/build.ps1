param(
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot "venv\Scripts\python.exe"

if ([string]::IsNullOrWhiteSpace($Python)) {
    if (Test-Path $venvPython) {
        $Python = $venvPython
    }
    else {
        $Python = "py"
    }
}

& $Python -m pip install -r requirements.txt -r requirements-build.txt
& $Python -m PyInstaller --clean --noconfirm switcherino-pc.spec

Write-Host ""
Write-Host "Build complete:"
Write-Host "  dist\\switcherino-pc.exe"
