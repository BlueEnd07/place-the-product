# Installs the place-product skill into your personal Claude Code folder and (optionally) sets up MoGe.
# Right-click > Run with PowerShell   (or: powershell -ExecutionPolicy Bypass -File install-windows.ps1)
$src = Join-Path $PSScriptRoot "plugins\place-the-product\skills\place-product"
$dst = Join-Path $env:USERPROFILE ".claude\skills\place-product"
New-Item -ItemType Directory -Force $dst | Out-Null
Copy-Item -Recurse -Force (Join-Path $src "*") $dst
Write-Host "Installed skill to $dst"

if (-not (Test-Path "C:\Program Files\Blender Foundation") -and -not (Get-Command blender -ErrorAction SilentlyContinue)) {
  Write-Host "Note: Blender not found. Install Blender 4.2 or newer from blender.org (or: winget install BlenderFoundation.Blender)."
}
$moge = Join-Path $env:USERPROFILE ".place-the-product\moge_python.txt"
if (-not (Test-Path $moge)) {
  $ans = Read-Host "Set up MoGe now? (camera + 3D from one image; downloads ~3 GB, NVIDIA GPU recommended) [y/N]"
  if ($ans -match "^[yY]") { & powershell -ExecutionPolicy Bypass -File (Join-Path $dst "setup\setup_moge.ps1") }
  else { Write-Host "Skipped. Claude will offer to run setup\setup_moge.ps1 the first time it needs it." }
}
Write-Host "Restart Claude Code, then ask: 'place this product in this image' or type /place-product."
Read-Host "Press Enter to close"
