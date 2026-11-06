---
name: place-the-product
description: Place a real product (.blend at real-world scale, with its materials) into a photo or architectural render of a room — wall, table, floor, shelf — matching the image's camera, perspective, scale, light, shadows and grain. Delivers a .blend plus four images - product only (transparent, no shadow), shadow only, product + shadow, and the full composite. Uses MoGe monocular geometry (or vanishing lines) to match the camera, or the architect's own Blender scene when available. Use when someone wants to put / place / composite / insert a product into an interior image, render, room photo or scene, or asks for a product-in-context / in-situ shot.
---

# Place the product

Put a real product into a real (or rendered) room so it looks like it was there when the image was made.
You drive Blender headless with the scripts in `scripts/`. Every step writes files you can look at; **look at them**.
Do not guess what an image shows; open it with the Read tool.

## What you deliver (always all of these)

| File | What it is |
|---|---|
| `<name>.blend` | New scene: matched camera, the product placed, proxy surfaces, lights (packed, opens anywhere) |
| `<name>_1_product.png` | Product only, transparent background, **no shadow** (RGBA 16-bit) |
| `<name>_2_shadow.png` | Shadow only (cast + contact shadow), transparent (RGBA 16-bit) |
| `<name>_3_product_shadow.png` | Product + its shadow, transparent background (RGBA 16-bit) |
| `<name>_4_composite.png` / `.jpg` | Final image: product and shadow in the scene |
| `<name>_shadow_multiply.png` | Bonus: the shadow as a Photoshop "Multiply" layer (white = unchanged) |

All four images share one pixel size (the final resolution chosen, e.g. 4K, with the scene image's aspect ratio), so
they stack in Photoshop with no alignment needed.

## Setup (once per machine)

1. **Blender 4.2+**. Find it:
   - Windows: `Get-ChildItem "C:\Program Files\Blender Foundation" -Directory`, then use `...\Blender X.Y\blender.exe`. Pick the newest.
   - macOS: `/Applications/Blender.app/Contents/MacOS/Blender`
   - Linux: `which blender`

   Below, `BLENDER` means that path. Every script runs as
   `"BLENDER" -b --factory-startup --python-exit-code 1 -P <skill>/scripts/<script>.py -- <args>`.
   Always pass `--factory-startup`, because users' add-ons break background runs.
2. **MoGe** (camera and 3D geometry from one image; needs an NVIDIA GPU for speed): check whether
   `~/.place-the-product/moge_python.txt` exists. If it doesn't, run `setup/setup_moge.ps1` (Windows) or
   `bash setup/setup_moge.sh` (Mac/Linux) and tell the user it downloads ~3 GB once. If MoGe can't be installed,
   use vanishing-line mode (see [references/vanishing_lines.md](references/vanishing_lines.md)).
3. Optional health check: `"BLENDER" -b --factory-startup -P <skill>/selftest/selftest.py -- --out <tmp folder>`.
   It should print `SELFTEST PASSED`.

## Workflow

Make a job folder next to the inputs (e.g. `<scene name>_<product>/`) with `work/` and `out/`. Never modify
the user's source files. The scripts only read them.

### 1. Intake: get these four things, ask only for what's missing
- **Product**: a `.blend` with finished materials, ideally at real-world scale. Ask which collection it's in if the file
  has several things. **Always ask for the real size** (width × depth × height, with units) unless the user has given it
  or you can confirm it otherwise. It's the only reliable check on the file's scale.
- **Scene**: an image (photo or render) **or** the architect's scene file. A `.blend` with a camera means **scene mode** (best):
  use it. For other formats (.max, .skp, .c4d, V-Ray/Corona), ask for the **camera's horizontal FOV** or focal length +
  sensor width and use image mode with `--fov-x`.
- **Where**: a text description ("on the console, left of the lamp"), a dot (x,y) or a box (x0,y0,x1,y1) in image pixels.
  For a text description, choose the box yourself. Make it about the size you expect the product to appear (start from
  its real size and the scene scale). Draw it with `mark_placement.py` (add `--grid 100` to read coordinates) and show
  the user the marked image before building. A box is better than a dot: it pins the position and checks scale.
- **Name** for the outputs (short, no spaces).

### 2. Check the product
```
"BLENDER" -b --factory-startup -P scripts/inspect_product.py -- --blend product.blend --out work/product_views.png
```
Add `--front-axis <axis> --dimensions "W,D,H" --unit mm` once you know the real size (0 = unknown dimension).
Read the JSON (size in metres, `size_seen_from_front_m`, units, objects) and **look at** `product_views.png`
(seen from -Y, +X, +Y, -X).
- **Size check.** Compare the model with the real size:
  - Within ~2%: fine, no scaling.
  - Clearly off (cm/mm/inch export, 10×, 100×, 1000×, or just wrong): put the real size in the job and the product is
    rescaled at build time. The source file is never touched.
    `"product": {"blend": "...", "dimensions": {"width": 86, "depth": 40, "height": 86, "unit": "mm"}}`
    Width is side to side as seen from the front, depth is front to back, height is vertical. Any subset works; one
    dimension is enough for uniform scaling. Units: mm, cm, m, in, ft.
  - No real size is available and the model size looks implausible: **stop and ask** for height, width and depth.
    Don't guess a scale.
  - `size_check.warning` (given dimensions disagree with the model's proportions by >3%): first suspect swapped
    width/depth or a wrong `front_axis`, and ask the user. Use `"scale_mode": "per_axis"` (stretches each given axis)
    only if the user confirms the model itself is out of proportion.
  - Tell the user the scaling you applied, e.g. "model was 10× too big; scaled to 110 × 110 × 166 mm".
- `front_axis`: the side whose view shows the product's front (logo, buttons, grille). Default `-Y`.
- Wall products (switches, panels, sconces): the **back** must be the side that goes against the wall, i.e. the
  opposite of `front_axis`.

### 3. Match the camera (image mode)
```
"<moge_python>" scripts/moge_infer.py --image scene.jpg --out work/geo.npz [--fov-x 63.5]
"BLENDER" -b --factory-startup -P scripts/solve_scene.py -- --image scene.jpg --geo work/geo.npz --out work
```
`<moge_python>` is the path stored in `~/.place-the-product/moge_python.txt`. Pass `--fov-x` whenever the FOV is
known (arch renders, EXIF focal length ÷ sensor). It removes the biggest error source.

**Look at `work/check_camera.jpg`.** The yellow/green grid must lie flat on the floor and run parallel to the walls,
the blue 1 m posts must be vertical and parallel to real verticals, and the magenta horizon should sit at eye level.
Then sanity-check the scale in the printed JSON:
- `camera_height_m`: eye-level photo 1.2–1.7 m; arch renders often 1.2–1.6 m; standing-on-a-ladder shots higher.
- `horizontal_levels_above_floor`: tables ≈ 0.72–0.78, counters ≈ 0.85–0.95, beds/sofa seats ≈ 0.4–0.5.
- Measure something known with `scripts/locate.py -- --work work --measure x1,y1,x2,y2` (door height ≈ 2.0–2.1 m,
  kitchen counter 0.9 m, tile size).

If the scale is off, re-run solve with `--ref "x1,y1,x2,y2=<metres>"` (or `--camera-height`). The product has true
size, so a wrong scene scale shows up directly as a wrong product size.

### 4. Read the light
```
"BLENDER" -b --factory-startup -P scripts/analyze_light.py -- --work work --target-px <x,y of placement>
```
Look at `work/light_hints.jpg` **and** the original image, then decide (details in
[references/lighting.md](references/lighting.md)):
- **Key**: where do the existing shadows in the image point, and how sharp are they? Sharp, directional shadows mean
  `sun` (through a window) or a small spot. Soft, diffuse ones mean a large `area` light at the window, or no key at
  all (overcast/indirect).
  `locate.py --sun-from-shadow objX,objY:shadowX,shadowY` turns an object point and its shadow into a direction.
- **Practicals**: lamps or spots near the product that would visibly light it.
- **Colour**: `kelvin` per light (daylight 5000–6500, tungsten 2700–3200, LED 3000–4000).
- **`calibrate.target_albedo`**: your estimate of the support surface's true reflectance (white paint 0.75–0.85, light
  oak 0.35–0.45, walnut 0.1–0.15, white marble 0.7, concrete 0.25–0.35, black stone 0.05). It sets the overall light level.

The room itself is rebuilt from the image and lights the product automatically (bounce, reflections, colour). Add
explicit lights only for what the reconstruction can't carry: directional sun or keys, and clipped light sources.

### 5. Build and the 720p check render
Write `job.json` (full schema: [references/job_schema.md](references/job_schema.md)), e.g.:
```json
{
  "name": "speaker_console",
  "image": "scene.jpg",
  "work_dir": "work",
  "output_dir": "out",
  "product": {"blend": "product.blend", "front_axis": "-Y"},
  "placement": {"box": [770, 405, 800, 452], "surface": "auto", "orient": "room"},
  "lights": [{"type": "sun", "to_light": [-0.8, -0.1, 0.6], "strength": 3, "angle_deg": 1.5, "kelvin": 5200}],
  "calibrate": {"target_albedo": 0.4},
  "finish": {"blur_px": 0.0, "grain": "auto"},
  "render": {"samples": 300, "preview_samples": 64, "final_resolution": "4k", "time_budget_s": 120}
}
```
```
"BLENDER" -b --factory-startup --python-exit-code 1 -P scripts/build_scene.py -- --job job.json
"BLENDER" -b --factory-startup --python-exit-code 1 -P scripts/render_outputs.py -- --blend out/<name>.blend --preview
```
`--preview` always renders at **720p** (long side 1280 px, aspect kept) with 64 samples in about 5–15 s on a GPU.
Never start with a full-size render.
Read the build report: `surface.kind` (horizontal/wall), `box_fit.*_ratio_box_over_product` (≈1 means the scale
agrees with the box; 1.3 or 0.7 means the scene scale or the box is wrong, so recheck step 3), and `calibration`
(`implied_surface_albedo`, `light_scale`, plus any note).

### 6. QC loop: look at `out/<name>_preview_qc_sheet.jpg` every time
The top shows the whole frame; the bottom shows a zoomed crop of the composite, product only, shadow only, and
product + shadow. Check, in this order (fix recipes in [references/troubleshooting.md](references/troubleshooting.md)):
1. **Sits on / in the surface**: no floating, no sinking. There's a dark contact line where it touches.
2. **Perspective and scale**: its verticals lean like nearby verticals, and its size is plausible next to known objects.
3. **Shadow direction and softness** match the shadows already in the image.
4. **Brightness and colour**: the product's lit side vs. shadow side matches neighbouring objects; same white balance.
5. **Edges and grain**: the product is no sharper or cleaner than the image (`finish.blur_px` 0.3–1.0 for photos,
   `grain` auto).
6. **Occlusion**: if something in the image sits in front of the product, supply `finish.occlusion_mask`
   (white = in front).

Fix what you can see yourself first: change the job, rebuild, and render the 720p preview again. Tell the user what
you changed and why, in one line each.

**Placement gate (mandatory).** When the 720p preview looks right to you, show it to the user (the composite
`out/<name>_preview_4_composite.jpg` and the QC sheet) and ask them to confirm the placement: position, size,
orientation, light and shadow direction. **Stop and wait for their answer.** If they ask for changes, apply them and
show a new 720p preview. Don't move on until they explicitly approve.

### 7. Final render: ask for the size first
Once the placement is approved, ask: "Placement approved. Render the final in 4K (3840 px wide), or another size
(1080p / 1440p / the image's native size)?" Mention it takes about 1–2 minutes. If the scene image is smaller than
the size they choose, tell them the background will be upscaled: the product and shadow render sharp, but the room
can't gain detail. Render only after they answer:
```
"BLENDER" -b --factory-startup --python-exit-code 1 -P scripts/render_outputs.py -- --blend out/<name>.blend --res 4k
```
`--res`: `720p | 1080p | 1440p | 4k | 8k | native | <long side px>`. Final defaults: 300 samples, GPU (OptiX/CUDA/
HIP/Metal, chosen automatically), adaptive sampling and OpenImageDenoise on, and a **120 s time budget for the whole
render**. The budget is split over the passes with Cycles' per-pass time limit, so it finishes in 1–2 minutes even at 4K.
If the report says `warning_cpu` (no GPU), tell the user: the time limit then costs quality, so offer a longer
`--time-budget` or a smaller size.
Then look at the final QC sheet once more and hand over the list of files, with absolute paths and the resolution. Mention anything the
user should know: assumed scale, a mask you'd recommend, a shadow you couldn't fully match.

## Scene mode (architect's .blend)
Job: `"scene_blend": "arch.blend"` (plus optional `"scene_camera"`, and `"image"` if they also sent their final
render). Skip steps 3–4. Their camera, geometry, materials and lights are used as-is, and the composite is a true
render of their scene with the product in it. The product lands where the dot/box ray hits their geometry. If their
render used another engine or post-processing, render the plate yourself (leave `image` out) so all images match.

## Rules
- Never overwrite inputs. Everything goes to the job folder.
- Always 720p first, the user confirms placement, then ask for the final size (default 4K). Never skip the QC sheet.
- The product's real size is truth: the user's dimensions if given, otherwise the file. Fix scene-scale problems in the
  scene (`--ref`), never by rescaling the product to make the box fit.
- Report numbers that matter (camera height, FOV, scale ratio, light scale) in plain words, not raw JSON.
