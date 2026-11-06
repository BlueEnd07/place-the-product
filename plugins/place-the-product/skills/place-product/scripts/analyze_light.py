"""Read the lighting of the scene image and draft a light rig (run through Blender: blender -b --factory-startup -P <script> -- <args>).

    blender -b --factory-startup -P analyze_light.py -- --work work [--image room.jpg] [--target-px 785,450]

Finds bright regions (windows, lamps, sun patches), puts them in 3D with the solved geometry, estimates the
white balance, and writes:
    work/light_hints.json   regions + a DRAFT "lights" list you can paste into the job (then edit!)
    work/light_hints.jpg    the image with numbered regions - LOOK AT IT and decide what each region is

The draft is a starting point. Use your eyes: shadow direction/softness in the image decides the key light.
Light power does not need to be right: render_outputs.py calibrates the overall level (calibrate.target_albedo).
"""
import argparse
import json
import math
import os
import sys
from collections import deque

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ptp_geo as G  # noqa: E402
from locate import World  # noqa: E402


def label(mask):
    H, W = mask.shape
    lab = np.zeros((H, W), np.int32)
    n = 0
    for y in range(H):
        for x in range(W):
            if mask[y, x] and not lab[y, x]:
                n += 1
                q = deque([(y, x)])
                lab[y, x] = n
                while q:
                    cy, cx = q.popleft()
                    for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                        if 0 <= ny < H and 0 <= nx < W and mask[ny, nx] and not lab[ny, nx]:
                            lab[ny, nx] = n
                            q.append((ny, nx))
    return lab, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--image")
    ap.add_argument("--target-px", help="x,y of the placement (to rank lights by influence)")
    a = ap.parse_args(G.script_argv())
    w = World(a.work)
    img_path = a.image or w.scene["image"]
    plate, srgb = G.read_image(img_path)
    plate = plate[..., :3] if plate.shape[2] >= 3 else np.repeat(plate, 3, 2)
    lin = G.srgb_to_linear(plate) if srgb else plate
    H, W = lin.shape[:2]
    s = 200.0 / max(W, H)
    h, wd = max(2, int(H * s)), max(2, int(W * s))
    small = G.resize_area(lin, h, wd)
    L = G.luminance(small)
    srgb_small = G.linear_to_srgb(small)
    Ls = G.luminance(srgb_small)

    thr = max(0.85, float(np.percentile(Ls, 98.5)))
    mask = Ls >= thr
    lab, n = label(mask)
    target = None
    if a.target_px:
        tx, ty = [float(v) for v in a.target_px.split(",")]
        target = np.array(w.point(tx, ty))

    regions = []
    for i in range(1, n + 1):
        ys, xs = np.nonzero(lab == i)
        if len(ys) < 4:
            continue
        x0, x1 = xs.min() / s, (xs.max() + 1) / s
        y0, y1 = ys.min() / s, (ys.max() + 1) / s
        col = small[ys, xs].mean(0)
        clipped = float((srgb_small[ys, xs] > 0.98).any(-1).mean())
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        # 3D: sample world points of the region
        pts = np.array([w.point(x / s, y / s) for y, x in zip(ys[:: max(1, len(ys) // 200)], xs[:: max(1, len(xs) // 200)])])
        c3 = np.median(pts, 0)
        surf = w.local_plane(cx, cy)
        n3 = np.array(surf["normal"])
        ext = pts.max(0) - pts.min(0)
        kind = "light source / bright surface"
        if surf["kind"] == "wall" and ext[2] > 0.4:
            kind = "window or opening (on a wall)"
        elif surf["kind"] == "horizontal" and c3[2] < 0.15:
            kind = "sun patch or light pool on the floor"
        elif surf["kind"] == "horizontal" and c3[2] > 1.9:
            kind = "ceiling fixture or skylight"
        elif max(ext) < 0.6:
            kind = "lamp / small fixture"
        r = {"id": len(regions) + 1, "kind_guess": kind, "pixel_box": [round(x0), round(y0), round(x1), round(y1)],
             "pixel_area_fraction": round(len(ys) / (h * wd), 4), "clipped_fraction": round(clipped, 2),
             "mean_linear_rgb": col.round(4).tolist(), "kelvin_estimate": G.rgb_to_kelvin(col),
             "world_center": c3.round(3).tolist(), "world_extent": ext.round(3).tolist(), "surface_normal": n3.round(3).tolist()}
        if target is not None:
            d = c3 - target
            r["distance_to_target_m"] = round(float(np.linalg.norm(d)), 2)
            r["direction_from_target"] = (d / max(1e-6, np.linalg.norm(d))).round(3).tolist()
        regions.append(r)
    regions.sort(key=lambda r: -r["pixel_area_fraction"])
    for i, r in enumerate(regions):
        r["id"] = i + 1

    # white balance of the ambient light: grey-world on bright, unsaturated, unclipped pixels
    sat = (srgb_small.max(-1) - srgb_small.min(-1)) / np.maximum(srgb_small.max(-1), 1e-4)
    sel = (Ls > np.percentile(Ls, 50)) & (Ls < 0.95) & (sat < 0.25)
    wb = small[sel].mean(0) if sel.sum() > 20 else small.reshape(-1, 3).mean(0)

    # draft lights
    draft = []
    floor_patches = [r for r in regions if r["kind_guess"].startswith("sun patch")]
    windows = [r for r in regions if r["kind_guess"].startswith("window")]
    if floor_patches and windows:
        fp, wi = floor_patches[0], windows[0]
        d = np.array(wi["world_center"]) - np.array(fp["world_center"])
        d /= np.linalg.norm(d)
        draft.append({"type": "sun", "to_light": d.round(3).tolist(), "strength": 3.0, "angle_deg": 1.0,
                      "kelvin": 5500, "name": f"sun (window {wi['id']} -> floor patch {fp['id']})"})
    for r in regions[:4]:
        if r["kind_guess"].startswith("sun patch"):
            continue
        c = np.array(r["world_center"])
        nrm = np.array(r["surface_normal"])
        ext = sorted(r["world_extent"], reverse=True)
        size = [max(0.1, ext[0]), max(0.1, ext[1])]
        if r["kind_guess"].startswith("lamp"):
            draft.append({"type": "point", "location": (c + nrm * 0.05).round(3).tolist(), "power": 60, "radius": max(0.03, ext[0] / 2),
                          "kelvin": r["kelvin_estimate"], "name": f"lamp region {r['id']}"})
        else:
            draft.append({"type": "area", "location": (c + nrm * 0.02).round(3).tolist(),
                          "target": (c + nrm).round(3).tolist(), "size": [round(size[0], 2), round(size[1], 2)],
                          "power": 200, "kelvin": r["kelvin_estimate"], "name": f"area from region {r['id']} ({r['kind_guess']})"})
    out = {"image": img_path, "regions": regions,
           "ambient_white_balance": {"mean_linear_rgb": wb.round(4).tolist(), "kelvin_estimate": G.rgb_to_kelvin(wb)},
           "image_mean_luma_srgb": round(float(Ls.mean()), 3),
           "image_p99_luma_srgb": round(float(np.percentile(Ls, 99)), 3),
           "draft_lights": draft,
           "notes": ["Region light is ALREADY in the rebuilt room (env mesh) at its clipped brightness; add a light for "
                     "a region only when it should cast a visible directional shadow or is clipped (much brighter in reality).",
                     "Hard, crisp shadows in the image -> sun or small source; soft, blurry -> large area / overcast.",
                     "Use locate.py --sun-from-shadow to get a key direction from an object and its shadow."]}
    G.save_json(os.path.join(a.work, "light_hints.json"), out)

    # annotated image
    vis = G.linear_to_srgb(lin) * 0.8
    from solve_scene import draw_line
    for r in regions:
        x0, y0, x1, y1 = r["pixel_box"]
        col = (1.0, 0.3, 0.9)
        for p0, p1 in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
            draw_line(vis, p0, p1, col, 3)
        # id as tally marks
        for k in range(r["id"]):
            draw_line(vis, (x0 + 4 + 6 * k, y0 + 4), (x0 + 4 + 6 * k, y0 + 18), (1, 1, 0.2), 2)
    G.write_image(os.path.join(a.work, "light_hints.jpg"), vis, quality=88)
    print(json.dumps({k: out[k] for k in ("ambient_white_balance", "image_mean_luma_srgb", "draft_lights")}, indent=2))
    print(json.dumps([{k: r[k] for k in ("id", "kind_guess", "pixel_box", "clipped_fraction", "kelvin_estimate", "world_center")} for r in regions], indent=1))


if __name__ == "__main__":
    main()
