#!/usr/bin/env bash
# place-the-product installer (macOS / Linux). Safe to re-run: it updates in place.
#
# One-liner (no clone needed):
#   curl -fsSL https://raw.githubusercontent.com/BlueEnd07/place-the-product/main/install.sh | bash -s -- [--moge] [--skip-moge]
# From a clone:
#   bash install.sh [--moge] [--skip-moge]
#
# Non-interactive runs (agents, piped) never prompt. Last line is machine readable:
#   PTP_INSTALL_OK skill=<path> blender=<path|none> moge=<path|none> method=<plugin|copy>
set -e
REPO="${PTP_REPO:-https://github.com/BlueEnd07/place-the-product.git}"
MOGE=0; SKIP=0
for a in "$@"; do case "$a" in --moge) MOGE=1 ;; --skip-moge) SKIP=1 ;; esac; done
HOME2="${PTP_HOME:-$HOME/.place-the-product}"
mkdir -p "$HOME2"
INTERACTIVE=0; [ -t 0 ] && [ -z "$CI" ] && INTERACTIVE=1

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -n "$HERE" ] && [ -f "$HERE/.claude-plugin/marketplace.json" ]; then
  ROOT="$HERE"
else
  command -v git >/dev/null || { echo "git is required"; exit 1; }
  ROOT="$HOME2/repo"
  if [ -d "$ROOT/.git" ]; then git -C "$ROOT" pull --ff-only; else git clone --depth 1 "$REPO" "$ROOT"; fi
fi
SKILL_SRC="$ROOT/plugins/place-the-product/skills/place-the-product"
echo "Source: $ROOT"

METHOD=copy
SKILL_PATH="$HOME/.claude/skills/place-the-product"
if command -v claude >/dev/null; then
  if claude plugin marketplace list 2>&1 | grep -q place-the-product-marketplace; then
    claude plugin marketplace update place-the-product-marketplace || true
  else
    claude plugin marketplace add "$ROOT" || true
  fi
  if claude plugin install place-the-product@place-the-product-marketplace; then METHOD=plugin; SKILL_PATH="$SKILL_SRC"; fi
fi
if [ "$METHOD" = copy ]; then
  mkdir -p "$SKILL_PATH"
  cp -R "$SKILL_SRC/." "$SKILL_PATH/"
fi
echo "Skill installed ($METHOD): $SKILL_PATH"

BLENDER=none
if command -v blender >/dev/null; then BLENDER="$(command -v blender)"
elif [ -x /Applications/Blender.app/Contents/MacOS/Blender ]; then BLENDER=/Applications/Blender.app/Contents/MacOS/Blender
else echo "WARNING: Blender not found. Install Blender 4.2+ from blender.org."; fi
[ "$BLENDER" != none ] && echo "Blender: $BLENDER"

if [ "$MOGE" = 0 ] && [ "$SKIP" = 0 ] && [ ! -f "$HOME2/moge_python.txt" ] && [ "$INTERACTIVE" = 1 ]; then
  read -r -p "Install MoGe now? (~3 GB; on Mac uses MoGe-2) [y/N] " ans
  case "$ans" in [yY]*) MOGE=1 ;; esac
fi
[ "$MOGE" = 1 ] && bash "$SKILL_SRC/setup/setup_moge.sh"
MOGE_PY=none; [ -f "$HOME2/moge_python.txt" ] && MOGE_PY="$(cat "$HOME2/moge_python.txt")"

echo
echo "Done. Start a NEW Claude Code session, then type /place-the-product or ask 'place this product in this image'."
[ "$MOGE_PY" = none ] && echo "MoGe not installed: re-run with --moge later (or the skill falls back to vanishing-line camera matching)."
echo "PTP_INSTALL_OK skill=$SKILL_PATH blender=$BLENDER moge=$MOGE_PY method=$METHOD"
