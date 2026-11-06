# For AI agents

- **Asked to install this?** Follow [INSTALL.md](INSTALL.md) step by step. It's written for you: non-interactive
  commands, a machine-readable success line (`PTP_INSTALL_OK …`) and a self-test.
- **Asked to use it** (place a product in an image)? After installing, the workflow lives in
  [plugins/place-the-product/skills/place-the-product/SKILL.md](plugins/place-the-product/skills/place-the-product/SKILL.md).
- **Asked to change it?** Scripts are in `plugins/place-the-product/skills/place-the-product/scripts/` and run inside
  Blender (`blender -b --factory-startup -P <script> -- <args>`). Run `selftest/selftest.py` after any change; it
  must print `SELFTEST PASSED`.
