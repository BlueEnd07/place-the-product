#!/usr/bin/env bash
# Installs Microsoft MoGe for place-the-product (Linux / macOS).
#   bash setup_moge.sh
# Linux + NVIDIA: full MoGe-3.  macOS: MoGe-3 is not supported upstream (Triton); this installs MoGe-2
# without the MoGe-3 extras and runs on Apple GPU (mps) or CPU. Use `--version v2` with moge_infer.py there.
# If this fails on your machine, the skill still works in vanishing-line mode (no MoGe).
set -e
HOME2="${PTP_HOME:-$HOME/.place-the-product}"
SRC="$HOME2/moge-src"
mkdir -p "$HOME2"
command -v git >/dev/null || { echo "git not found"; exit 1; }
command -v uv >/dev/null || { echo "uv not found. Install: curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1; }
if [ -d "$SRC/.git" ]; then git -C "$SRC" pull --ff-only; else git clone --depth 1 https://github.com/microsoft/MoGe.git "$SRC"; fi
cd "$SRC"
if [ "$(uname)" = "Darwin" ]; then
  uv venv --python 3.11 .venv
  PY="$SRC/.venv/bin/python"
  uv pip install --python "$PY" torch torchvision
  uv pip install --python "$PY" --no-deps -e .
  uv pip install --python "$PY" click "numpy>=2" opencv-python-headless scipy pillow matplotlib trimesh huggingface-hub requests tqdm \
    "utils3d_moge @ git+https://github.com/EasternJournalist/utils3d-moge.git@62f09d58509485564e24d5d9f6aac9ee9ebc0c37" \
    "pipeline @ git+https://github.com/EasternJournalist/pipeline.git@1c511390d90226c00c101f34b84df26a0f8789b4"
  "$PY" -c "from moge.model.v2 import MoGeModel; MoGeModel.from_pretrained('Ruicheng/moge-2-vitl-normal'); print('MoGe-2 ready (use --version v2)')"
else
  uv sync --python 3.11
  PY="$SRC/.venv/bin/python"
  "$PY" -c "import torch;print('CUDA available:', torch.cuda.is_available())"
  "$PY" -c "from moge.model.v3 import MoGeModel; MoGeModel.from_pretrained('Ruicheng/moge-3-vitl'); print('MoGe-3 ready')" || \
  "$PY" -c "from moge.model.v2 import MoGeModel; MoGeModel.from_pretrained('Ruicheng/moge-2-vitl-normal'); print('MoGe-2 ready (use --version v2)')"
fi
echo "$PY" > "$HOME2/moge_python.txt"
echo "MoGe python: $PY (saved to $HOME2/moge_python.txt)"
