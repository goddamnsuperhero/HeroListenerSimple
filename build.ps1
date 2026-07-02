# Build the standalone Windows executable.
# Usage:  .\build.ps1
$ErrorActionPreference = "Stop"
python -m pip install -r requirements-dev.txt
python -m PyInstaller --noconfirm --clean HeroListenerSimple.spec
Write-Host "`nDone -> dist\HeroListenerSimple.exe" -ForegroundColor Green
Write-Host "Reminder: put a .env (with your API key) next to the .exe before running." -ForegroundColor Yellow
