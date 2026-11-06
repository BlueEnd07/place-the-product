#!/usr/bin/env bash
# Installs the place-the-product skill into ~/.claude/skills and (optionally) sets up MoGe.
#   bash install-mac.sh
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
DST="$HOME/.claude/skills/place-the-product"
mkdir -p "$DST"
cp -R "$HERE/plugins/place-the-product/skills/place-the-product/." "$DST/"
echo "Installed skill to $DST"
[ -d /Applications/Blender.app ] || command -v blender >/dev/null || echo "Note: Blender not found. Install Blender 4.2+ from blender.org."
if [ ! -f "$HOME/.place-the-product/moge_python.txt" ]; then
  read -r -p "Set up MoGe now? (downloads ~3 GB; on Mac uses MoGe-2) [y/N] " ans
  case "$ans" in [yY]*) bash "$DST/setup/setup_moge.sh" ;; *) echo "Skipped. Without MoGe the skill uses vanishing-line camera matching." ;; esac
fi
echo "Restart Claude Code, then ask: 'place this product in this image' or type /place-the-product."
