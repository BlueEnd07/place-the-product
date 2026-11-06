"""Draw a proposed placement (dot or box) and a pixel ruler on the scene image, to agree on it before building.

    blender -b --factory-startup -P mark_placement.py -- --image room.jpg --out work/placement.jpg [--box x0,y0,x1,y1] [--px x,y] [--grid 100]

--grid draws labelled-by-position tick lines every N pixels so you (and the user) can read coordinates off the image.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ptp_geo as G  # noqa: E402
from solve_scene import draw_line  # noqa: E402


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--box", action="append", default=[])
    ap.add_argument("--px", action="append", default=[])
    ap.add_argument("--grid", type=int, default=0)
    a = ap.parse_args(G.script_argv())
    img, srgb = G.read_image(a.image)
    img = img[..., :3] if img.shape[2] >= 3 else np.repeat(img, 3, 2)
    vis = (img if srgb else G.linear_to_srgb(img)).copy()
    H, W = vis.shape[:2]
    if a.grid:
        for x in range(0, W, a.grid):
            draw_line(vis, (x, 0), (x, H - 1), (0.2, 0.9, 1.0) if x % (a.grid * 5) else (1.0, 1.0, 0.2), 1)
        for y in range(0, H, a.grid):
            draw_line(vis, (0, y), (W - 1, y), (0.2, 0.9, 1.0) if y % (a.grid * 5) else (1.0, 1.0, 0.2), 1)
    lw = max(2, int(round(max(W, H) / 600)))
    for b in a.box:
        x0, y0, x1, y1 = [float(v) for v in b.split(",")]
        for p0, p1 in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
            draw_line(vis, p0, p1, (1.0, 0.15, 0.55), lw)
    for p in a.px:
        x, y = [float(v) for v in p.split(",")]
        r = 6 * lw
        draw_line(vis, (x - r, y), (x + r, y), (1.0, 0.15, 0.55), lw)
        draw_line(vis, (x, y - r), (x, y + r), (1.0, 0.15, 0.55), lw)
    G.write_image(a.out, vis, quality=90)
    print("marked:", os.path.abspath(a.out), f"(image {W}x{H})")


if __name__ == "__main__":
    main()
