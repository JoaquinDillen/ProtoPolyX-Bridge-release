$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Remove-Item -LiteralPath (Join-Path $root "dist") -Recurse -Force -ErrorAction SilentlyContinue

python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --windowed `
  --name "URSimProtoTwinBridge" `
  --icon "AppIcon.ico" `
  --add-data "AppIcon.ico;." `
  --hidden-import "bridge" `
  --hidden-import "customtkinter" `
  --hidden-import "rtde_receive" `
  --hidden-import "rtde_control" `
  --hidden-import "prototwin" `
  app.py

Write-Host ""
Write-Host "Build complete:"
Write-Host "  $root\dist\URSimProtoTwinBridge.exe"
Write-Host "Runtime config files are created beside the exe on first run if missing."
