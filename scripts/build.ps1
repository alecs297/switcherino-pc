param(
    [string]$Python = "py"
)

$ErrorActionPreference = "Stop"

& $Python -m pip install -r requirements.txt -r requirements-build.txt
& $Python -m PyInstaller --clean --noconfirm switcherino-pc.spec

Write-Host ""
Write-Host "Build complete:"
Write-Host "  dist\\switcherino-pc.exe"
