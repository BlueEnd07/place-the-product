# Installs Microsoft MoGe (monocular geometry: camera FOV + metric 3D from one image) for place-the-product.
#   powershell -ExecutionPolicy Bypass -File setup_moge.ps1
# Needs: git, uv (https://docs.astral.sh/uv/), an NVIDIA GPU is strongly recommended (CPU works, slowly).
# Result: %USERPROFILE%\.place-the-product\moge-src\.venv  and  %USERPROFILE%\.place-the-product\moge_python.txt
param([string]$Home2 = (Join-Path $env:USERPROFILE ".place-the-product"))
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force $Home2 | Out-Null
$src = Join-Path $Home2 "moge-src"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Write-Host "git not found. Install Git for Windows: winget install Git.Git"; exit 1 }
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Write-Host "uv not found. Install it with:  powershell -ExecutionPolicy ByPass -c `"irm https://astral.sh/uv/install.ps1 | iex`""
  Write-Host "then open a new terminal and run this script again."
  exit 1
}

if (Test-Path (Join-Path $src ".git")) { git -C $src pull --ff-only } else { git clone --depth 1 https://github.com/microsoft/MoGe.git $src }
Push-Location $src
uv sync --python 3.11
$py = Join-Path $src ".venv\Scripts\python.exe"

# CUDA check; older NVIDIA drivers can't run the default cu130 wheels -> try older CUDA builds
$hasNvidia = [bool](Get-Command nvidia-smi -ErrorAction SilentlyContinue)
$cuda = & $py -c "import torch;print(torch.cuda.is_available())"
if ($hasNvidia -and $cuda -ne "True") {
  foreach ($b in @("cu128", "cu126", "cu124")) {
    Write-Host "CUDA not usable with the default build; trying torch $b ..."
    uv pip install --python $py --torch-backend=$b torch torchvision --reinstall
    $cuda = & $py -c "import torch;print(torch.cuda.is_available())"
    if ($cuda -eq "True") { break }
  }
}
Write-Host "CUDA available: $cuda"

# Pre-download weights (MoGe-3 ViT-L, ~1.5 GB; fall back to MoGe-2 if v3 cannot load)
& $py -c "from moge.model.v3 import MoGeModel; MoGeModel.from_pretrained('Ruicheng/moge-3-vitl'); print('MoGe-3 ready')"
if ($LASTEXITCODE -ne 0) {
  Write-Host "MoGe-3 failed to load; preparing MoGe-2 instead (use --version v2)."
  & $py -c "from moge.model.v2 import MoGeModel; MoGeModel.from_pretrained('Ruicheng/moge-2-vitl-normal'); print('MoGe-2 ready')"
}
Pop-Location
Set-Content -Encoding ascii -Path (Join-Path $Home2 "moge_python.txt") -Value $py
Write-Host "MoGe python: $py  (saved to $Home2\moge_python.txt)"
