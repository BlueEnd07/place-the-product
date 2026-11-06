# job.json reference

Relative paths resolve against the job file's folder. Only `name`, `output_dir`, `product.blend`, `placement`
and one of `work_dir` (image mode) or `scene_blend` (scene mode) are required.

```jsonc
{
  "name": "speaker_console",            // prefix of every output file
  "image": "scene.jpg",                 // the scene image (image mode: required unless in scene.json; scene mode: optional plate)
  "work_dir": "work",                   // image mode: folder with scene.json + world.npz from solve_scene.py
  "scene_blend": null,                  // scene mode: the architect's .blend (opened read-only, saved as a copy)
  "scene_camera": null,                 // scene mode: camera object name (default: the scene's active camera)
  "output_dir": "out",
  "pack": true,                         // pack textures into the .blend so it opens on any machine

  "product": {
    "blend": "product.blend",
    "collection": null,                 // import just this collection (default: every renderable object of the first scene)
    "scene": null,                      // which scene of the product file (default: first)
    "front_axis": "-Y",                 // which local axis the product's FRONT faces: -Y | +Y | -X | +X
    "dimensions": null,                 // real size -> rescale the model: {"width": 86, "depth": 40, "height": 86, "unit": "mm"}
                                        //   width = side to side seen from the front, depth = front to back, height = vertical;
                                        //   any subset; unit mm | cm | m | in | ft
    "scale_mode": "uniform",            // uniform (keep proportions, factor from the given dimensions) | per_axis (stretch each)
    "scale": null,                      // plain multiplier instead of dimensions (e.g. 0.001 for a mm-as-m export)
    "include_lights": false             // keep studio lights that live in the product file (normally no)
  },

  "placement": {
    // exactly one of:
    "box": [x0, y0, x1, y1],            // where it should appear, image pixels (best: also fits position)
    "pixel": [x, y],                    // a point on the supporting surface (base centre / wall centre)
    "location": [x, y, z],              // world metres (from locate.py), for exact re-placement

    "surface": "auto",                  // auto | horizontal | wall   - force when auto picks the wrong one
    "mount": null,                      // horizontal | wall | ceiling (default from the surface)
    "orient": "room",                   // room: square to the walls, front toward camera | camera: face camera exactly | fixed
    "yaw_deg": 0,                       // extra turn around vertical (positive = counter-clockwise from above)
    "offset_m": [0, 0, 0],              // world nudge after placement
    "gap_m": 0.0,                       // lift off the surface (e.g. 0.001 to avoid z-fighting with rough proxies)
    "fit_box": true                     // slide the product on its surface until its projected box centre = box centre
  },

  "catcher": {                          // image mode: proxy surfaces that receive shadow / bounce
    "radius_m": null,                   // default 4x product size, 0.6-3 m. Raise for long, low-sun shadows
    "roughness": 0.6,                   // lower (0.1-0.2) for polished stone / gloss lacquer so the product reflects in it
    "specular": 0.5
  },
  "env": {"enabled": true, "strength": 1.0, "grid": 360},   // rebuilt room (emits the image's own light)
  "world": {"strength": 1.0, "color": null},                 // behind-camera fill; null = average image colour

  "lights": [
    {"type": "sun",   "to_light": [x, y, z], "strength": 3.0, "angle_deg": 1.0, "kelvin": 5500},
    {"type": "area",  "location": [x, y, z], "target": [x, y, z], "size": [w, h], "power": 200, "kelvin": 6000, "spread_deg": 180},
    {"type": "point", "location": [x, y, z], "power": 60, "radius": 0.05, "kelvin": 2800},
    {"type": "spot",  "location": [x, y, z], "target": [x, y, z], "power": 300, "spot_deg": 40, "blend": 0.3, "kelvin": 3000}
  ],                                    // 'color': [r,g,b] instead of kelvin also works; 'name' optional

  "calibrate": {"target_albedo": 0.4, "max_light_scale": 50},  // false = no calibration
  // With lights + target_albedo: all light powers are scaled by one factor so the support surface comes out at that
  // reflectance (energy ratios between lights are kept). Without target_albedo: lights stay as given; the report
  // still prints implied_surface_albedo so you can judge.

  "finish": {
    "blur_px": 0.0,                     // soften product + shadow to the image's sharpness (photos 0.3-1.0)
    "grain": "auto",                    // auto = measure the image's noise and add it to the product; 0 = off
    "occlusion_mask": null,             // PNG, white where image content is IN FRONT of the product
    "product_gain": [1, 1, 1],          // final colour/brightness trim of the product (linear)
    "product_saturation": 1.0,
    "shadow_density": 1.0               // >1 darker, <1 lighter shadow
  },

  "render": {
    "samples": 300,                     // final; adaptive sampling stops earlier where clean
    "preview_samples": 64,              // the 720p check render
    "final_resolution": "4k",           // default for the final when --res isn't given: 720p|1080p|1440p|4k|8k|native|<px>
    "time_budget_s": 120,               // whole final render (all passes); split per pass via Cycles' time limit
    "preview_time_budget_s": 30,
    "noise_threshold": 0.01,            // adaptive sampling (preview: 0.03)
    "device": "auto",                   // auto = OptiX > CUDA > HIP > Metal > oneAPI > CPU
    "max_bounces": 8
  }
}
```

## World coordinates (image mode)
Metres, Z up, floor at z = 0, camera directly above the origin. X/Y follow the room's walls (X is the wall direction
closest to image-right). `locate.py` prints any pixel's world point, so use it to position lights.

## Changing only the finish
`finish` is applied in compositing. To try a different blur/grain/gain without re-rendering, run `composite.py`
directly on `out/passes/<name>_product.exr`, `_without.exr` and `_with.exr`.
