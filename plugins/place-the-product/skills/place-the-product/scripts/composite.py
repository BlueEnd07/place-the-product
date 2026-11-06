"""Assemble the four deliverables from the product / shadow renders (image mode).

Usually called by render_outputs.py. Standalone (re-grade without re-rendering), with Blender's Python:
    blender -b --factory-startup -P composite.py -- --plate room.jpg --product out/passes/x_product.exr --without out/passes/x_without.exr --with out/passes/x_with.exr \
                              --out out --name x [--blur 0.6] [--grain auto|0|0.01] [--occlusion mask.png] [--gain 1,1,1]

Outputs (straight alpha, sRGB):
    <name>_1_product.png          product only, transparent background, no shadow       (RGBA 16-bit)
    <name>_2_shadow.png           shadow only (contact + cast shadow, bounce), transparent (RGBA 16-bit)
    <name>_3_product_shadow.png   product + its shadow, transparent background            (RGBA 16-bit)
    <name>_4_composite.png/.jpg   full composite over the scene image                     (RGB)
    <name>_shadow_multiply.png    bonus: the shadow as a white-background multiply layer  (RGB 16-bit)
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ptp_geo as G  # noqa: E402


def estimate_grain(plate_srgb):
    """Per-channel noise sigma of the plate (display space), measured in flat areas."""
    p = plate_srgb[..., :3]
    box = (G.gaussian_blur(p, 1.0))
    hp = p - box
    gy = np.abs(np.diff(box, axis=0, append=box[-1:]))
    gx = np.abs(np.diff(box, axis=1, append=box[:, -1:]))
    grad = (gx + gy).mean(-1)
    flat = grad < np.percentile(grad, 30)
    if flat.sum() < 100:
        return np.zeros(3)
    return 1.4826 * np.median(np.abs(hp[flat]), axis=0)


def straight(rgb, a):
    return np.where(a[..., None] > 1e-6, rgb / np.maximum(a[..., None], 1e-6), 0.0)


def run(plate_path, product_exr, shadow_exr, out_dir, name, finish=None, report=None, base_exr=None, with_exr=None):
    finish = finish or {}
    P, _ = G.read_image(product_exr)
    H, W = P.shape[:2]
    mult = None
    if base_exr and with_exr:
        # differential rendering: surfaces rendered without (C0) and with (C1) the product
        C0, _ = G.read_image(base_exr)
        C1, _ = G.read_image(with_exr)
        cov = np.clip(C0[..., 3], 0, 1)
        ratio = C1[..., :3] / np.maximum(C0[..., :3], 1e-5)
        ratio = np.where((C0[..., :3] > 1e-4) & (cov[..., None] > 1e-3), ratio, 1.0)
        mult = 1.0 + (ratio - 1.0) * cov[..., None]       # fade out at the edge of the proxy surfaces
        mult = np.clip(mult, 0.0, 4.0).astype(np.float32)
        dark = np.clip(1.0 - G.luminance(np.minimum(mult, 1.0)), 0, 1)
        S = np.dstack([np.zeros((H, W, 3), np.float32), dark])  # shadow as black + alpha
    else:
        S, _ = G.read_image(shadow_exr)
    plate, srgb = G.read_image(plate_path)
    plate = plate[..., :3] if plate.shape[2] >= 3 else np.repeat(plate, 3, 2)
    if plate.shape[:2] != (H, W):
        plate = G.resize_area(plate, H, W)
    plate_lin = G.srgb_to_linear(plate) if srgb else plate
    plate_srgb = plate if srgb else G.linear_to_srgb(plate)

    Prgb, Pa = P[..., :3].astype(np.float32), P[..., 3].astype(np.float32)
    Srgb, Sa = S[..., :3].astype(np.float32), np.clip(S[..., 3].astype(np.float32), 0, 1)

    gain = np.array(finish.get("product_gain", [1, 1, 1]), dtype=np.float32)
    Prgb = Prgb * gain
    sat = float(finish.get("product_saturation", 1.0))
    if abs(sat - 1) > 1e-3:
        L = G.luminance(Prgb)[..., None]
        Prgb = L + (Prgb - L) * sat
    sd = float(finish.get("shadow_density", 1.0))
    if abs(sd - 1) > 1e-3:
        Sa = np.clip(Sa * sd, 0, 1)

    if mult is not None and abs(sd - 1) > 1e-3:
        mult = np.clip(1.0 + (mult - 1.0) * sd, 0, 4)
    blur = float(finish.get("blur_px", 0.0))
    if blur > 0.05:
        Prgb = G.gaussian_blur(Prgb, blur)
        Pa = G.gaussian_blur(Pa, blur)
        Srgb = G.gaussian_blur(Srgb, blur)
        Sa = G.gaussian_blur(Sa, blur)
        if mult is not None:
            mult = G.gaussian_blur(mult, blur)

    occ_path = finish.get("occlusion_mask")
    if occ_path:
        occ, _ = G.read_image(occ_path)
        occ = occ[..., 0] if occ.ndim == 3 else occ
        if occ.shape != (H, W):
            occ = G.resize_area(occ[..., None], H, W)[..., 0]
        occ = np.clip(occ, 0, 1)
        keep = 1 - occ
        Prgb *= keep[..., None]
        Pa *= keep
        Srgb *= keep[..., None]
        Sa *= keep
        if mult is not None:
            mult = 1.0 + (mult - 1.0) * keep[..., None]

    # --- composite in linear light
    if mult is not None:
        bg = plate_lin * mult  # exact differential composite (shadow + bounce + reflections)
    else:
        bg = plate_lin * (1 - Sa[..., None]) + Srgb
    comp = Prgb + (1 - Pa[..., None]) * bg
    comp_srgb = G.linear_to_srgb(comp)

    # --- grain: match the plate's noise on the product
    g = finish.get("grain", "auto")
    sigma = estimate_grain(plate_srgb) if g == "auto" else np.full(3, float(g or 0))
    rng = np.random.default_rng(7)
    noise = None
    if sigma.max() > 1e-4:
        n = rng.standard_normal((H, W, 1)).astype(np.float32)
        noise = n * sigma[None, None, :] * 0.8 + rng.standard_normal((H, W, 3)).astype(np.float32) * sigma * 0.6
        comp_srgb = comp_srgb + noise * Pa[..., None]

    os.makedirs(out_dir, exist_ok=True)
    o1 = os.path.join(out_dir, f"{name}_1_product.png")
    o2 = os.path.join(out_dir, f"{name}_2_shadow.png")
    o3 = os.path.join(out_dir, f"{name}_3_product_shadow.png")
    o4 = os.path.join(out_dir, f"{name}_4_composite.png")
    o4j = os.path.join(out_dir, f"{name}_4_composite.jpg")
    om = os.path.join(out_dir, f"{name}_shadow_multiply.png")

    p_srgb = G.linear_to_srgb(straight(Prgb, Pa))
    if noise is not None:
        p_srgb = p_srgb + noise
    G.write_image(o1, np.dstack([p_srgb, Pa]), bits=16)
    G.write_image(o2, np.dstack([G.linear_to_srgb(straight(Srgb, Sa)), Sa]), bits=16)
    A3 = Pa + (1 - Pa) * Sa
    rgb3 = Prgb + (1 - Pa[..., None]) * Srgb
    s3 = G.linear_to_srgb(straight(rgb3, A3))
    if noise is not None:
        s3 = s3 + noise * (Pa / np.maximum(A3, 1e-6))[..., None]
    G.write_image(o3, np.dstack([s3, A3]), bits=16)
    G.write_image(o4, comp_srgb, bits=8)
    G.write_image(o4j, comp_srgb, bits=8, quality=95)
    mul_img = np.minimum(mult, 1.0) if mult is not None else np.repeat((1 - Sa)[..., None], 3, 2) + Srgb
    G.write_image(om, mul_img, bits=16)  # multiply layer: stored as plain factors (white = unchanged)

    # --- QC numbers
    qc = {}
    if Pa.max() > 0.5:
        m = Pa > 0.98
        ys, xs = np.nonzero(Pa > 0.5)
        qc["product_px_box"] = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
        qc["product_mean_luma_srgb"] = round(float(G.luminance(G.linear_to_srgb(straight(Prgb, Pa))[m]).mean()), 3) if m.any() else None
        # plate brightness in a ring around the product
        pad = max(4, int(0.25 * (xs.max() - xs.min())))
        y0, y1 = max(0, ys.min() - pad), min(H, ys.max() + pad)
        x0, x1 = max(0, xs.min() - pad), min(W, xs.max() + pad)
        ring = np.zeros((H, W), bool)
        ring[y0:y1, x0:x1] = True
        ring &= Pa < 0.02
        qc["surround_mean_luma_srgb"] = round(float(G.luminance(plate_srgb[ring]).mean()), 3) if ring.any() else None
        qc["product_clipped_fraction"] = round(float((comp[m] > 0.999).any(-1).mean()), 4) if m.any() else None
    qc["shadow_max_density"] = round(float(Sa.max()), 3)
    qc["shadow_area_px"] = int((Sa > 0.05).sum())
    qc["plate_grain_sigma_srgb"] = [round(float(v), 4) for v in sigma]
    outs = {"product": o1, "shadow": o2, "product_shadow": o3, "composite": o4, "composite_jpg": o4j, "shadow_multiply": om}
    if "product_px_box" in qc:
        outs["qc_sheet"] = qc_sheet(os.path.join(out_dir, f"{name}_qc_sheet.jpg"), o4, [o1, o2, o3], qc["product_px_box"])
    return outs, qc


def _checker(a):
    yy, xx = np.mgrid[0:a.shape[0], 0:a.shape[1]]
    ck = (((yy // 8) + (xx // 8)) % 2) * 0.25 + 0.6
    return a[..., :3] * a[..., 3:4] + (1 - a[..., 3:4]) * ck[..., None]


def qc_sheet(out_path, composite_path, rgba_paths, box, width=1600):
    """One review image: full composite on top, then zoomed crops of composite + transparent outputs."""
    comp, _ = G.read_image(composite_path)
    comp = comp[..., :3]
    H, W = comp.shape[:2]
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    side = max(bw, bh) * 2.2 + 16
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    X0, Y0 = int(max(0, cx - side / 2)), int(max(0, cy - side / 2))
    X1, Y1 = int(min(W, cx + side / 2)), int(min(H, cy + side / 2))
    tiles = [comp[Y0:Y1, X0:X1]]
    for p in rgba_paths:
        a, _ = G.read_image(p)
        if a.shape[2] < 4:
            a = np.dstack([a[..., :3], np.ones(a.shape[:2])])
        if a.shape[:2] != (H, W):
            a = G.resize_nearest(a, H, W)
        tiles.append(_checker(a[Y0:Y1, X0:X1]))
    tw = width // len(tiles)
    th = int(round(tw * (Y1 - Y0) / max(1, X1 - X0)))
    row = np.concatenate([G.resize_nearest(t, th, tw) if t.shape[0] < th else G.resize_area(t, th, tw) for t in tiles], 1)
    top_h = int(round(width * H / W))
    top = G.resize_area(comp, top_h, width) if W > width else G.resize_nearest(comp, top_h, width)
    # mark the crop on the overview
    from solve_scene import draw_line
    s = width / W
    for a_, b_ in (((X0, Y0), (X1, Y0)), ((X1, Y0), (X1, Y1)), ((X1, Y1), (X0, Y1)), ((X0, Y1), (X0, Y0))):
        draw_line(top, (a_[0] * s, a_[1] * s), (b_[0] * s, b_[1] * s), (1.0, 0.2, 0.6), 2)
    sheet = np.concatenate([top, np.ones((6, width, 3), np.float32), row[:, :width] if row.shape[1] >= width else
                            np.pad(row, ((0, 0), (0, width - row.shape[1]), (0, 0)), constant_values=1)], 0)
    G.write_image(out_path, sheet, quality=90)
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plate", required=True)
    ap.add_argument("--product", required=True)
    ap.add_argument("--shadow", help="shadow-catcher RGBA pass (alternative to --without/--with)")
    ap.add_argument("--without", help="differential: proxy surfaces rendered WITHOUT the product (x_without.exr)")
    ap.add_argument("--with", dest="with_", help="differential: proxy surfaces rendered WITH the product (x_with.exr)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default="placement")
    ap.add_argument("--blur", type=float, default=0.0)
    ap.add_argument("--grain", default="auto")
    ap.add_argument("--occlusion")
    ap.add_argument("--gain", default="1,1,1")
    ap.add_argument("--saturation", type=float, default=1.0)
    ap.add_argument("--shadow-density", type=float, default=1.0)
    a = ap.parse_args(G.script_argv())
    finish = {"blur_px": a.blur, "grain": a.grain if a.grain == "auto" else float(a.grain), "occlusion_mask": a.occlusion,
              "product_gain": [float(v) for v in a.gain.split(",")], "product_saturation": a.saturation,
              "shadow_density": a.shadow_density}
    outs, qc = run(a.plate, a.product, a.shadow, a.out, a.name, finish, base_exr=a.without, with_exr=a.with_)
    print(json.dumps({"outputs": outs, "qc": qc}, indent=2))


if __name__ == "__main__":
    main()
