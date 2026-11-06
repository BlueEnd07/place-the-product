# Troubleshooting and fix recipes

| Symptom (in the QC sheet) | Likely cause | Fix |
|---|---|---|
| Product floats above the table, or its base is hidden | Surface height slightly off (MoGe noise at that spot) | `placement.offset_m: [0,0,-0.005]` style nudges; or click a cleaner pixel on the surface; check `surface.kind` |
| Model size wrong in the file (cm/mm export, 10×/100×/1000×) | Units or export scale | `product.dimensions` with the real W/D/H (asks the user if unknown); build report `product_scaling` shows the factor |
| Product too big / small vs. surroundings | Scene scale off (MoGe ±5–10%) or box not drawn to size | `box_fit` ratios ≠ 1 → re-solve with `--ref` on something of known size; then rebuild |
| Product leans differently from nearby verticals | Camera roll/pitch slightly off, or lens shift (arch 2-point perspective) | Check `check_camera.jpg`; give `--fov-x`; for shifted arch renders use vanishing-line mode (handles shift) |
| Wrong surface picked (stuck to the wall behind a table) | Box bottom hit the wall | `placement.surface: "horizontal"`, or move the box bottom onto the table top |
| Product faces the wrong way | `front_axis` wrong, or room/camera orientation | Fix `product.front_axis`; `orient: "camera"`; `yaw_deg` |
| No shadow at all | No key light and soft room, product far from surfaces | Fine if the image has no shadows; otherwise add the key (lighting.md) |
| Shadow cut off with a hard edge | Shadow longer than the catcher radius | `catcher.radius_m` larger |
| Shadow falls through/beyond a table edge oddly | Proxy surface noisy at edges | Usually fine; reduce key `angle_deg` or move the light so the shadow stays on the support |
| Product too bright / too dark vs. neighbours | Calibration target wrong | Change `calibrate.target_albedo`: a higher albedo means less light is needed for the surface to look as it does, so the product gets darker; a lower albedo makes it brighter. Fine trim: `finish.product_gain` |
| Product too contrasty (very dark shadow side) | Key too strong vs. room fill | Lower the key (`strength`/`power`) relative to env, or raise `world.strength` / `env.strength` |
| Product colour cast wrong | Key Kelvin wrong | Adjust `kelvin`; compare white parts of the product to white parts of the image |
| Product looks too sharp / CG | Image is softer/noisier | `finish.blur_px` 0.4–1.0; `grain: "auto"` (already default) |
| Something in the image should be in front of the product | Occlusion | Make a mask (white = in front) at image size → `finish.occlusion_mask` |
| Glossy floor should reflect the product | Catcher too rough | `catcher.roughness: 0.1` |
| Speckles/noise in the shadow | Too few samples | Final render uses `render.samples` (256–512) |
| `check_camera.jpg` grid clearly wrong | MoGe misread (mirror walls, close-ups, no floor visible) | Give `--fov-x`; `--camera-height`; or vanishing-line mode |
| Blender error mentioning add-ons | User add-ons loaded | Always run with `--factory-startup` |
| MoGe runs on CPU / very slow | No CUDA | Re-run setup (it tries older CUDA builds); else wait (CPU ~1–3 min) |

## Real-world sizes for scale checks
Door 2.0–2.1 m high, 0.8–0.9 m wide · Ceiling 2.6–3.2 m (homes), 3–4 m (commercial) · Dining/console table top
0.72–0.78 m · Kitchen counter 0.86–0.92 m · Coffee table 0.4–0.45 m · Sofa seat 0.4–0.45 m, back 0.8–0.9 m ·
Bed top 0.5–0.6 m · Light switch centre 1.1–1.2 m above floor (India: often 1.2–1.35 m) · Socket 0.3 m ·
Floor tiles 0.6 × 0.6 m or 0.8 × 0.8 m · Indian modular switch plate 86 × 86 mm (1-module wide 25 mm).
