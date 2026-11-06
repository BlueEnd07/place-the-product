"""Inspect a product .blend without changing it: size, units, objects, materials + a 4-view sheet.

    blender -b --factory-startup -P inspect_product.py -- --blend product.blend --out work/product_views.png [--collection NAME]
          [--front-axis -Y] [--dimensions "W,D,H" --unit mm]   # compare against the real size, 0 = unknown

The sheet shows the product seen from -Y, +X, +Y, -X (left to right), solid shading.
Use it to decide `product.front_axis` in the job: the axis the product's FRONT faces (default "-Y").
Also prints what will be imported (cameras and lights in the product file are skipped by default).
"""
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ptp_geo as G  # noqa: E402


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--blend", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--collection")
    ap.add_argument("--size", type=int, default=420)
    ap.add_argument("--front-axis", default="-Y")
    ap.add_argument("--dimensions", help='real size "W,D,H" (use 0 for unknown), e.g. "86,40,86"')
    ap.add_argument("--unit", default="mm")
    ap.add_argument("--scale-mode", default="uniform", choices=["uniform", "per_axis"])
    a = ap.parse_args(G.script_argv())
    bpy.ops.wm.open_mainfile(filepath=os.path.abspath(a.blend))
    sc = bpy.context.scene
    us = sc.unit_settings
    objs = list(bpy.data.collections[a.collection].all_objects) if a.collection else list(sc.objects)
    dg = bpy.context.evaluated_depsgraph_get()
    mins, maxs = np.full(3, np.inf), np.full(3, -np.inf)
    rows = []
    for o in objs:
        r = {"name": o.name, "type": o.type, "hide_render": o.hide_render,
             "materials": [s.material.name for s in getattr(o, "material_slots", []) if s.material]}
        if o.type in ("MESH", "CURVE", "SURFACE", "META", "FONT", "CURVES") and not o.hide_render:
            oe = o.evaluated_get(dg)
            for c in oe.bound_box:
                p = np.array(oe.matrix_world @ Vector(c))
                mins, maxs = np.minimum(mins, p), np.maximum(maxs, p)
        rows.append(r)
    scale = us.scale_length if us.system != "NONE" else 1.0
    size = (maxs - mins) * scale
    info = {"file": os.path.abspath(a.blend), "scenes": [s.name for s in bpy.data.scenes],
            "collections": [c.name for c in bpy.data.collections],
            "unit_system": us.system, "unit_scale_length": us.scale_length,
            "bbox_min": (mins * scale).round(4).tolist(), "bbox_max": (maxs * scale).round(4).tolist(),
            "size_m": size.round(4).tolist(), "objects": rows,
            "skipped_on_import": [r["name"] for r in rows if r["type"] in ("CAMERA", "LIGHT")],
            "render_engine": sc.render.engine}
    warn = []
    if max(size) > 5 or max(size) < 0.005:
        warn.append(f"largest dimension {max(size):.4f} m looks wrong for a product - check units/scale")
    if abs(mins[2] * scale) > 0.02 * max(size):
        warn.append("product base is not at z=0 in its file (fine - placement uses the bounding box)")
    wdh = G.preframe_dims(size, a.front_axis)
    info["size_seen_from_front_m"] = {"width": round(wdh[0], 4), "depth": round(wdh[1], 4), "height": round(wdh[2], 4)}
    if a.dimensions:
        w_, d_, h_ = [float(v) for v in a.dimensions.split(",")]
        spec = {"width": w_ or None, "depth": d_ or None, "height": h_ or None, "unit": a.unit}
        k, rep = G.size_correction(wdh, spec, a.scale_mode)
        info["size_check"] = rep
        if rep.get("warning"):
            warn.append(rep["warning"])
        f = float(np.median(k))
        if abs(f - 1) > 0.02:
            warn.append(f"model is {1 / f:.3g}x the real size -> put the dimensions in job.product.dimensions "
                        f"(scale factor {f:.4g} will be applied)")
    info["warnings"] = warn

    # 4-view sheet with workbench
    for o in list(sc.objects):
        if o not in objs:
            o.hide_render = True
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.display.shading.light = "STUDIO"
    sc.display.shading.color_type = "MATERIAL"
    sc.display.shading.show_cavity = True
    sc.render.film_transparent = False
    sc.render.resolution_x = sc.render.resolution_y = a.size
    sc.render.resolution_percentage = 100
    c = Vector(((mins + maxs) / 2).tolist())
    R = float(max(size / max(scale, 1e-9))) * 1.6 + 1e-3
    cd = bpy.data.cameras.new("ptp_inspect")
    cd.type = "ORTHO"
    cd.ortho_scale = R
    cam = bpy.data.objects.new("ptp_inspect", cd)
    sc.collection.objects.link(cam)
    sc.camera = cam
    tiles = []
    tmp = os.path.splitext(os.path.abspath(a.out))[0]
    for i, d in enumerate([(0, -1, 0.25), (1, 0, 0.25), (0, 1, 0.25), (-1, 0, 0.25)]):
        dv = Vector(d).normalized()
        cam.location = c + dv * R * 3
        cam.rotation_euler = (-dv).to_track_quat("-Z", "Y").to_euler()
        sc.render.image_settings.file_format = "PNG"
        sc.render.filepath = f"{tmp}_v{i}.png"
        bpy.ops.render.render(write_still=True)
        img, _ = G.read_image(sc.render.filepath)
        tiles.append(img[..., :3])
        os.remove(sc.render.filepath)
    sheet = np.concatenate(tiles, 1)
    # label strip: tick marks 1..4 = from -Y, +X, +Y, -X
    G.write_image(a.out, sheet)
    info["views"] = {"file": os.path.abspath(a.out), "order_left_to_right": ["seen from -Y (default front)", "seen from +X", "seen from +Y", "seen from -X"]}
    print("PTP_PRODUCT_INFO " + json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
