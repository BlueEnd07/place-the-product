# Installing place-the-product (instructions for AI agents and humans)

If you are an AI coding agent (Claude Code, Codex, Cursor…) and a user gave you this repository's link and asked
you to install it, follow these steps exactly. Don't ask questions unless a step says so. Every step is safe to re-run.

**Repository:** `https://github.com/BlueEnd07/place-the-product`
**Installs:** a Claude Code plugin with one skill, `place-the-product` (invoked as `/place-the-product`).

## Step 1: Check prerequisites (report what's missing; don't install system software silently)
| Need | Check | If missing |
|---|---|---|
| git | `git --version` | Windows `winget install Git.Git`; macOS `xcode-select --install` |
| Claude Code CLI | `claude --version` | Optional. Without it, the skill is copied to `~/.claude/skills/` instead |
| Blender 4.2+ | Windows: `C:\Program Files\Blender Foundation\Blender */blender.exe`; macOS: `/Applications/Blender.app`; Linux: `which blender` | Ask the user to install it from blender.org (Windows: `winget install BlenderFoundation.Blender`) |
| uv | `uv --version` | Needed only for MoGe (step 3). Windows `powershell -c "irm https://astral.sh/uv/install.ps1 \| iex"`, macOS/Linux `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| NVIDIA GPU | `nvidia-smi` | Optional. Without it MoGe runs on CPU (slow) and renders are noisier |

## Step 2: Install the skill (non-interactive)
**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/BlueEnd07/place-the-product/main/install.ps1 | iex"
```
**macOS / Linux:**
```bash
curl -fsSL https://raw.githubusercontent.com/BlueEnd07/place-the-product/main/install.sh | bash -s -- --skip-moge
```
Or, from a clone: `powershell -ExecutionPolicy Bypass -File install.ps1 -SkipMoGe -NoPause` / `bash install.sh --skip-moge`.

If the repository is private, the raw URLs return 404. Clone it with the user's git credentials first
(`git clone https://github.com/BlueEnd07/place-the-product`) and run the installer from the clone.

Success = the last line starts with `PTP_INSTALL_OK` and lists `skill=…`, `blender=…`, `moge=…`, `method=…`.

The installer does this (equivalent manual commands, if you prefer to run them yourself):
```
git clone --depth 1 https://github.com/BlueEnd07/place-the-product ~/.place-the-product/repo
claude plugin marketplace add ~/.place-the-product/repo
claude plugin install place-the-product@place-the-product-marketplace
```
(Inside a Claude Code session, the same thing is `/plugin marketplace add BlueEnd07/place-the-product`, then
`/plugin install place-the-product@place-the-product-marketplace`.)

## Step 3: MoGe (recommended; ask the user first)
MoGe matches the camera and the room's 3D geometry from a single image. It downloads about 3 GB once. **Ask the user**
before running it, then:
- Windows: `powershell -ExecutionPolicy Bypass -File <repo>\install.ps1 -MoGe -NoPause`
- macOS/Linux: `bash <repo>/install.sh --moge`

It writes the MoGe Python path to `~/.place-the-product/moge_python.txt`. If MoGe can't be installed, the skill still
works with vanishing-line camera matching.

## Step 4: Verify (about 1 minute)
```
<blender> -b --factory-startup -P <skill>/selftest/selftest.py -- --out <temp folder>/ptp_selftest
```
`<skill>` is the `skill=` path from step 2; `<blender>` is the `blender=` path. Add `--no-moge` if MoGe isn't installed.
Expect `SELFTEST PASSED`. If a line says FAIL, report it to the user along with the last 30 lines of output.

## Step 5: Tell the user
- It's installed, with the paths from `PTP_INSTALL_OK`.
- **Start a new Claude Code session**, then type `/place-the-product` or say "place this product in this image".
- Whether MoGe and a GPU are available, and what that means for them.

## Updating
Re-run the same installer command. It pulls the latest version and updates the plugin.

## Uninstalling
```
claude plugin uninstall place-the-product@place-the-product-marketplace
claude plugin marketplace remove place-the-product-marketplace
```
Then delete `~/.place-the-product` (MoGe environment and repo clone) and, if it exists, `~/.claude/skills/place-the-product`.
