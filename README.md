<img src="assets/icon.svg" width="64" height="64" alt="">

# Place the product: a Claude Code plugin

Give Claude a product `.blend` and a picture of a room, either a photo or an architectural render. Then say where
the product should go: "on the console table" or "on the wall left of the door", or mark a dot or box on the image.
Claude matches the camera, places the product at real size, and matches the light, shadows and grain.

**You get:**

| File | Contents |
|---|---|
| `<name>.blend` | Matched camera, the placed product, proxy surfaces, lights (textures packed) |
| `<name>_1_product.png` | Product only, transparent background, no shadow |
| `<name>_2_shadow.png` | Shadow only, transparent |
| `<name>_3_product_shadow.png` | Product + shadow, transparent |
| `<name>_4_composite.png/.jpg` | The final image |
| `<name>_shadow_multiply.png` | Bonus: the shadow as a Photoshop "Multiply" layer |

All images match the room image's pixel size, so they stack directly in Photoshop.

## How it works
1. **Camera match.** [MoGe-3](https://github.com/microsoft/MoGe) estimates the lens and a real-scale 3D surface of
   the room from the single image. The skill then finds gravity, the wall directions and the floor height. You check it
   on an overlay (floor grid and 1 m posts drawn onto your image).
   - No MoGe? It falls back to vanishing lines, fSpy-style.
   - Have the architect's `.blend`? It uses their real camera, geometry and lights instead (scene mode).
2. **Placement.** Your dot or box is turned into a point on the real surface (table top, wall, floor). The product
   sits flush, faces the room, and its size comes from the product file.
3. **Light match.** The visible room is rebuilt and used as a light source, so the product picks up the room's real
   colours and reflections. Claude adds sun, window or lamp lights where the image shows directional light. One
   calibration step sets the brightness so the table or wall comes out at a believable reflectance.
4. **Shadows.** Differential rendering: the room surfaces are rendered with and without the product, and the change
   between them is applied to your image. That's the contact shadow, cast shadow and bounce, with nothing else touched.
5. **Finish and QC.** Grain and softness are matched to the image. Claude reviews a QC sheet after every preview and
   iterates before the final render.

## Requirements
- Claude Code (desktop app or terminal)
- Blender 4.2 or newer (tested on 4.5 and 5.2)
- For MoGe: an NVIDIA GPU is strongly recommended (about 7 s per image; CPU works, slowly), plus `git` and
  [`uv`](https://docs.astral.sh/uv/). The setup downloads about 3 GB once.
  - macOS: MoGe-3 isn't supported upstream. The setup installs MoGe-2 (best effort), and vanishing-line mode always works.

## Install
**Option A: plugin (recommended).** In Claude Code:
```
/plugin marketplace add "<path to this folder>"
/plugin install place-the-product@place-the-product-marketplace
```
Then set up MoGe once: `powershell -ExecutionPolicy Bypass -File plugins\place-the-product\skills\place-product\setup\setup_moge.ps1`
(Mac/Linux: `bash plugins/place-the-product/skills/place-product/setup/setup_moge.sh`). Claude will also offer to
run it the first time it's needed.

**Option B: copy the skill.** Run `install-windows.ps1` (right-click > Run with PowerShell) or `bash install-mac.sh`.

**Check the install:** ask Claude to "run the place-product self-test", or run
```
blender -b --factory-startup -P plugins/place-the-product/skills/place-product/selftest/selftest.py -- --out %TEMP%\ptp_selftest
```
It builds a synthetic room with a known camera, runs the whole pipeline and prints `SELFTEST PASSED`.

## Using it
> Place `D:\products\keus_switch_4m.blend` on the wall right of the bed in `D:\renders\bedroom_03.jpg`, at switch height.

> Put the speaker (`speaker.blend`) on the console table in `living.png`. The box is roughly x 770–800, y 405–452.

> Here's the architect's scene `villa_living.blend`. Place `panel.blend` next to the door.

Claude asks for anything missing, shows you the proposed placement and the camera check, iterates on previews, and
hands over the files.

**Tips for the best results**
- Product files: real-world scale (metres), finished materials, front facing −Y (otherwise just tell Claude which way).
- Arch renders: tell Claude the camera's field of view or focal length + sensor, or send the scene file.
- Photos: the more floor and wall edges are visible, the better the camera match.

## Layout
```
.claude-plugin/marketplace.json
plugins/place-the-product/
  .claude-plugin/plugin.json
  skills/place-product/
    SKILL.md                  workflow Claude follows
    references/               job schema, lighting guide, troubleshooting, vanishing-line mode
    scripts/                  moge_infer, solve_scene, locate, analyze_light, inspect_product,
                              mark_placement, build_scene, render_outputs, composite, ptp_geo
    setup/                    setup_moge.ps1 / setup_moge.sh
    selftest/                 synthetic test room + end-to-end test
```
