# Vanishing-line mode (no MoGe)

Use when MoGe isn't installed (e.g. some Macs), or for architectural renders with **lens shift** (perfectly vertical
verticals = 2-point perspective). MoGe assumes a centred lens; this mode handles the shift.

## 1. Pick lines
Make a pixel grid to read coordinates:
`mark_placement.py -- --image scene.jpg --out work/grid.jpg --grid 50`
Look at it and write `work/lines.json`, with **full-resolution pixel** endpoints `[x1, y1, x2, y2]`:
- `x`: 2–4 long edges along one horizontal room direction (floor/wall junctions, table edges, window sills).
- `y`: 2–4 long edges along the perpendicular horizontal direction.
- `z`: 2+ vertical edges (door frames, wall corners). Leave it out or keep it if they're perfectly vertical in the
  image; then the camera is treated as level with lens shift.

Longer and more widely separated lines give a more accurate result. Avoid curved or lens-distorted edges near frame borders.

```json
{
  "x": [[262, 556, 1180, 630], [640, 445, 940, 455]],
  "y": [[1180, 630, 1275, 780], [255, 75, 0, 20]],
  "z": [[262, 80, 262, 556], [1185, 0, 1180, 630]],
  "camera_height": 1.5,
  "room": {"ceiling_height": 2.8},
  "planes": [
    {"type": "wall", "axis": "y", "floor_pixel": [700, 590]},
    {"type": "horizontal", "height": 0.76, "polygon": [[632, 440], [940, 448], [940, 470], [632, 458]]}
  ]
}
```
`planes` describes what to build the proxy room from (the floor is always there): `wall` = the wall whose base passes
through `floor_pixel` (axis `x` = wall perpendicular to world X, `y` = to world Y); `horizontal` = a level surface
(table/counter) at `height`, limited to the image `polygon`.

## 2. Solve
`solve_scene.py -- --image scene.jpg --lines work/lines.json --out work [--ref "x1,y1,x2,y2=2.1"]`
Then continue exactly as in image mode (check_camera.jpg, locate, build). `camera_height` (or `--ref`) sets the
scale. Without depth, scale comes only from that, so measure something real.
