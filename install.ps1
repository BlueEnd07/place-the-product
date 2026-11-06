# place-the-product installer (Windows). Safe to re-run: it updates in place.
#
# One-liner (no clone needed):
#   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/BlueEnd07/place-the-product/main/install.ps1 | iex"
# From a clone:
#   powershell -ExecutionPolicy Bypass -File install.ps1 [-MoGe] [-SkipMoGe] [-NoPause]
#
#   -MoGe      also install MoGe (camera + 3D from one image; ~3 GB download, NVIDIA GPU recommended)
#   -SkipMoGe  never ask about MoGe
#   -NoPause   don't wait for Enter at the end (agents / CI)
# Non-interactive runs (agents) never prompt. Last line is machine readable:
#   PTP_INSTALL_OK skill=<path> blender=<path|none> moge=<path|none> method=<plugin|copy>
param([switch]$MoGe, [switch]$SkipMoGe, [switch]$NoPause,
      [string]$Repo = "https://github.com/BlueEnd07/place-the-product.git")
$ErrorActionPreference = "Stop"
$nonInteractiveFlag = [bool]([Environment]::GetCommandLineArgs() | Where-Object { $_ -match '^-NonI' })
$interactive = [Environment]::UserInteractive -and -not $NoPause -and -not $env:CI -and -not $nonInteractiveFlag -and
               ($Host.Name -eq "ConsoleHost") -and -not [Console]::IsInputRedirected
$home2 = Join-Path $env:USERPROFILE ".place-the-product"
New-Item -ItemType Directory -Force $home2 | Out-Null

# 1. get the repo (use the folder this script is in, if it is a checkout)
$here = if ($PSScriptRoot) { $PSScriptRoot } else { "" }
if ($here -and (Test-Path (Join-Path $here ".claude-plugin\marketplace.json"))) {
  $root = $here
} else {
  if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "git is required: winget install Git.Git" }
  $root = Join-Path $home2 "repo"
  if (Test-Path (Join-Path $root ".git")) { git -C $root pull --ff-only | Out-Host }
  else { git clone --depth 1 $Repo $root | Out-Host }
}
$skillSrc = Join-Path $root "plugins\place-the-product\skills\place-the-product"
Write-Host "Source: $root"

# 2. install into Claude Code: plugin (preferred) or plain skill copy
$method = "copy"
$skillPath = Join-Path $env:USERPROFILE ".claude\skills\place-the-product"
if (Get-Command claude -ErrorAction SilentlyContinue) {
  $ErrorActionPreference = "Continue"
  $known = (claude plugin marketplace list 2>&1) -join "`n"
  if ($known -match "place-the-product-marketplace") { claude plugin marketplace update place-the-product-marketplace 2>&1 | Out-Host }
  else { claude plugin marketplace add "$root" 2>&1 | Out-Host }
  $ok = $LASTEXITCODE -eq 0
  if ($ok) { claude plugin install place-the-product@place-the-product-marketplace 2>&1 | Out-Host; $ok = $LASTEXITCODE -eq 0 }
  $ErrorActionPreference = "Stop"
  if ($ok) { $method = "plugin"; $skillPath = $skillSrc }
  else { Write-Host "Plugin install failed; falling back to copying the skill." }
}
if ($method -eq "copy") {
  New-Item -ItemType Directory -Force $skillPath | Out-Null
  Copy-Item -Recurse -Force (Join-Path $skillSrc "*") $skillPath
}
Write-Host "Skill installed ($method): $skillPath"

# 3. Blender
$blender = $null
$cmd = Get-Command blender -ErrorAction SilentlyContinue
if ($cmd) { $blender = $cmd.Source }
elseif (Test-Path "C:\Program Files\Blender Foundation") {
  $b = Get-ChildItem "C:\Program Files\Blender Foundation" -Directory | Sort-Object { [version](($_.Name -replace '[^\d.]', '') + '.0') } -Descending |
       ForEach-Object { Join-Path $_.FullName "blender.exe" } | Where-Object { Test-Path $_ } | Select-Object -First 1
  if ($b) { $blender = $b }
}
if (-not $blender) { Write-Host "WARNING: Blender not found. Install Blender 4.2+ (winget install BlenderFoundation.Blender)." }
else { Write-Host "Blender: $blender" }

# 4. MoGe
$mogeTxt = Join-Path $home2 "moge_python.txt"
$doMoGe = $MoGe
if (-not $MoGe -and -not $SkipMoGe -and -not (Test-Path $mogeTxt) -and $interactive) {
  $ans = Read-Host "Install MoGe now? (camera + 3D from one image; ~3 GB, NVIDIA GPU recommended) [y/N]"
  $doMoGe = $ans -match "^[yY]"
}
if ($doMoGe) { & powershell -ExecutionPolicy Bypass -File (Join-Path $skillSrc "setup\setup_moge.ps1") }
$mogePy = if (Test-Path $mogeTxt) { (Get-Content $mogeTxt -Raw).Trim() } else { "none" }

Write-Host ""
Write-Host "Done. Start a NEW Claude Code session, then type /place-the-product or ask 'place this product in this image'."
if ($mogePy -eq "none") { Write-Host "MoGe not installed: run with -MoGe later (or the skill falls back to vanishing-line camera matching)." }
Write-Host "PTP_INSTALL_OK skill=$skillPath blender=$(if ($blender) { $blender } else { 'none' }) moge=$mogePy method=$method"
if ($interactive) { Read-Host "Press Enter to close" | Out-Null }
