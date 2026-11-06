"""Render the deliverables from a .blend made by build_scene.py.

    blender -b --factory-startup --python-exit-code 1 -P render_outputs.py -- --blend out/x.blend [--preview]
           [--samples 512] [--no-calibrate] [--scale 0.5]

Image mode:  (optional) light calibration -> product pass + shadow pass (EXR) -> composite.py -> 4 outputs.
Scene mode:  plate (if none given) + full render + product pass + shadow pass, all with the scene's own colour management.

--preview: 720p check render (long side 1280 px), preview samples, files suffixed _preview. Show it to the user
           and get the placement approved before any final render.
--res:     output size: 720p | 1080p | 1440p | 4k | 8k | native | <long side in px>   (final default: job render.final_resolution, 4k)
Time: each run is held to a time budget (final default 120 s total, preview 30 s) by splitting it over the passes
and using Cycles' per-pass time limit + adaptive sampling + denoising on the GPU.
The calibrated light values are saved back into the .blend (so the delivered .blend matches the delivered images).
"""
import argparse
import json
import math
import os
import sys
import time

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ptp_geo as G  # noqa: E402

ROLE = "ptp_role"


def log(*a):
    print("[ptp]", *a, flush=True)


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--blend", required=True)
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--samples", type=int)
    ap.add_argument("--scale", type=float, help="(legacy) resolution multiplier; prefer --res")
    ap.add_argument("--res", help="720p | 1080p | 1440p | 4k | 8k | native | long side in px")
    ap.add_argument("--time-budget", type=float, help="seconds for the whole run (all passes)")
    ap.add_argument("--no-calibrate", action="store_true")
    ap.add_argument("--no-save", action="store_true")
    return ap.parse_args(argv)


PRESETS = {"720p": 1280, "1080p": 1920, "1440p": 2560, "2k": 2048, "4k": 3840, "uhd": 3840, "8k": 7680}


def resolution_for(name, base):
    """Output size keeping the image aspect. Presets give the long side (16:9 4k = 3840x2160)."""
    W, H = base
    n = str(name).lower().strip()
    if n == "native":
        return W, H
    long_side = PRESETS.get(n) or int(float(n))
    s = long_side / max(W, H)
    return max(2, int(round(W * s / 2) * 2)), max(2, int(round(H * s / 2) * 2))


def role(o):
    return o.get(ROLE)


def objs(r):
    return [o for o in bpy.context.scene.objects if role(o) == r]


def set_output(sc, kind):
    ims = sc.render.image_settings
    if hasattr(ims, "media_type"):
        try:
            ims.media_type = "IMAGE"
        except TypeError:
            pass
    if kind == "exr":
        ims.file_format = "OPEN_EXR"
        ims.color_mode = "RGBA"
        ims.color_depth = "32"
    else:
        ims.file_format = "PNG"
        ims.color_mode = "RGBA"
        ims.color_depth = "16"


def do_render(sc, path, kind="exr"):
    set_output(sc, kind)
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return path if os.path.exists(path) else path + (".exr" if kind == "exr" else ".png")


class Saved:
    """Remember object/scene properties and restore them afterwards."""

    def __init__(self):
        self.items = []

    def set(self, obj, attr, val):
        self.items.append((obj, attr, getattr(obj, attr)))
        setattr(obj, attr, val)

    def restore(self):
        for obj, attr, val in reversed(self.items):
            setattr(obj, attr, val)
        self.items = []


# ------------------------------------------------------------------ calibration (image mode)
def white_material():
    m = bpy.data.materials.get("PTP_PROBE_WHITE") or bpy.data.materials.new("PTP_PROBE_WHITE")
    m.use_nodes = True
    b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    b.inputs["Base Color"].default_value = (1, 1, 1, 1)
    b.inputs["Roughness"].default_value = 1.0
    if "Specular IOR Level" in b.inputs:
        b.inputs["Specular IOR Level"].default_value = 0.0
    return m


def calibrate(sc, meta, tmp_dir, plate_lin):
    job = meta["job"]
    rep = meta["report"]
    cal = job.get("calibrate") or {}
    lights = objs("light")
    catcher = next(iter(objs("catcher")), None)
    env = next(iter(objs("env")), None)
    box = rep.get("proxies", {}).get("support_box_px")
    if catcher is None or box is None:
        return {"skipped": "no catcher/support region"}
    H, W = plate_lin.shape[:2]  # support box is in scene-image pixels
    rW = sc.render.resolution_x
    sv = Saved()
    r = sc.render
    sv.set(r, "use_border", True)
    sv.set(r, "use_crop_to_border", True)
    x0, y0, x1, y1 = box
    pad = 0.0
    sv.set(r, "border_min_x", max(0.0, x0 / W - pad))
    sv.set(r, "border_max_x", min(1.0, x1 / W + pad))
    sv.set(r, "border_min_y", max(0.0, 1 - y1 / H - pad))
    sv.set(r, "border_max_y", min(1.0, 1 - y0 / H + pad))
    crop_px = max(1.0, max(x1 - x0, y1 - y0)) * rW / W
    pct = max(5, min(100, int(round(100 * 400 / crop_px))))
    sv.set(r, "resolution_percentage", pct)
    sv.set(sc.cycles, "samples", 64)
    sv.set(sc.cycles, "time_limit", 6.0)
    for o in objs("product") + objs("product_root"):
        sv.set(o, "hide_render", True)
    sv.set(catcher, "is_shadow_catcher", False)
    old_mat = catcher.data.materials[0]
    catcher.data.materials[0] = white_material()

    world_bg = None
    if sc.world and sc.world.use_nodes:
        world_bg = next((n for n in sc.world.node_tree.nodes if n.type == "BACKGROUND"), None)

    for L in lights:  # probe with the job's base energies, so repeated calibration does not compound
        L.data.energy = float(L.get("ptp_base_energy", L.data.energy))
    try:
        # E_env: environment + world only
        for L in lights:
            sv.set(L, "hide_render", True)
        e_env = G.read_image(do_render(sc, os.path.join(tmp_dir, "probe_env.exr")))[0]
        for L in lights:
            L.hide_render = False
        # E_lights: lights only
        e_l = None
        if lights:
            if env:
                sv.set(env, "hide_render", True)
            if world_bg:
                sv.set(world_bg.inputs[1], "default_value", 0.0)
            e_l = G.read_image(do_render(sc, os.path.join(tmp_dir, "probe_lights.exr")))[0]
    finally:
        catcher.data.materials[0] = old_mat
        sv.restore()

    h, w = e_env.shape[:2]
    xa, xb = int(round(x0)), int(round(x1))
    ya, yb = int(round(y0)), int(round(y1))
    crop = plate_lin[ya:yb, xa:xb]
    crop = G.resize_area(crop, h, w)
    # support mask (analysis res) -> crop
    msk = None
    mp = rep.get("support_mask_path")
    if mp and os.path.exists(mp):
        sm = np.load(mp)
        Hs, Ws = sm.shape
        full = G.resize_nearest(sm[..., None].astype(np.float32), H, W)[..., 0]
        msk = G.resize_nearest(full[ya:yb, xa:xb][..., None], h, w)[..., 0] > 0.5
    valid = e_env[..., 3] > 0.99
    if msk is not None:
        valid &= msk
    # skip pixels where the product will sit (the plate there is the bare surface, fine) - keep them
    Lp = G.luminance(crop)
    Ee = G.luminance(e_env[..., :3])
    El = G.luminance(e_l[..., :3]) if e_l is not None else np.zeros_like(Ee)
    valid &= (Lp < 0.98) & (Lp > 0.002)
    if valid.sum() < 50:
        return {"skipped": "too few probe pixels"}
    out = {"probe_pixels": int(valid.sum())}
    target = cal.get("target_albedo")
    scale = 1.0
    if target and e_l is not None:
        lit = valid & (El > 0.25 * np.median(El[valid]))
        s = (Lp[lit] / float(target) - Ee[lit]) / np.maximum(El[lit], 1e-6)
        scale = float(np.median(s))
        if scale <= 0.02:
            out["warning"] = ("The room reconstruction alone already makes this surface brighter than the target albedo "
                              "implies; lights set near zero. Raise target_albedo or lower env strength.")
            scale = 0.02
        lim = cal.get("max_light_scale", 50.0)
        scale = float(np.clip(scale, 0.02, lim))
        for L in lights:
            L.data.energy = float(L.get("ptp_base_energy", L.data.energy)) * scale
        out["light_scale"] = round(scale, 4)
    E = Ee + scale * El
    implied = Lp[valid] / np.maximum(E[valid], 1e-6)
    a_med = float(np.median(implied))
    out["implied_surface_albedo"] = round(a_med, 3)
    out["env_share_of_light"] = round(float(np.median(Ee[valid] / np.maximum(E[valid], 1e-6))), 3)
    # make the catcher's bounce consistent with the plate: albedo = plate / irradiance
    k = float(np.clip(1.0 / max(float(np.median(E[valid])), 1e-4), 0.05, 20.0))
    mat = catcher.data.materials[0]
    node = mat.node_tree.nodes.get("PTP_ALBEDO_SCALE")
    if node is not None:
        kk = min(k, 0.95 / max(float(np.percentile(Lp[valid], 95)), 1e-4))
        sock = node.inputs[7] if node.bl_idname == "ShaderNodeMix" else node.inputs[2]
        sock.default_value = (kk, kk, kk, 1)
        out["catcher_albedo_scale"] = round(kk, 3)
    if a_med > 0.95:
        out["note"] = "implied albedo > 0.95: the rig is too DARK for this surface (raise lights/env)."
    elif a_med < 0.03:
        out["note"] = "implied albedo < 0.03: the rig is too BRIGHT for this surface (lower lights/env)."
    return out


# ------------------------------------------------------------------ main
def main():
    a = args()
    bpy.ops.wm.open_mainfile(filepath=os.path.abspath(a.blend))
    sc = bpy.context.scene
    if "ptp" not in sc:
        raise SystemExit("not a place-the-product .blend (missing scene['ptp'])")
    meta = json.loads(sc["ptp"])
    job = meta["job"]
    name = job.get("name", "placement")
    out_dir = job["output_dir"]
    scene_mode = meta["report"]["mode"] == "scene"
    suffix = "_preview" if a.preview else ""
    pass_dir = os.path.join(out_dir, "passes")
    os.makedirs(pass_dir, exist_ok=True)
    rcfg = job.get("render", {})

    # GPU prefs are not stored in the .blend -> set again
    from build_scene import setup_device
    dev = setup_device(sc, rcfg.get("device", "auto"))
    log("device", dev)

    base_res = (sc.render.resolution_x, sc.render.resolution_y)
    res_name = a.res or ("720p" if a.preview else str(rcfg.get("final_resolution", "4k")))
    if a.scale:
        out_w, out_h = round(base_res[0] * a.scale), round(base_res[1] * a.scale)
    else:
        out_w, out_h = resolution_for(res_name, base_res)
    sc.render.resolution_x, sc.render.resolution_y = out_w, out_h
    sc.render.resolution_percentage = 100
    sc.cycles.samples = a.samples or (int(rcfg.get("preview_samples", 64)) if a.preview else int(rcfg.get("samples", 300)))
    sc.cycles.use_denoising = True
    try:
        sc.cycles.denoiser = "OPENIMAGEDENOISE"
    except TypeError:
        pass
    if hasattr(sc.cycles, "denoising_use_gpu"):
        sc.cycles.denoising_use_gpu = dev != "CPU"
    sc.cycles.use_adaptive_sampling = True
    sc.cycles.adaptive_threshold = float(rcfg.get("preview_noise_threshold", 0.03) if a.preview else rcfg.get("noise_threshold", 0.01))
    budget = a.time_budget or float(rcfg.get("preview_time_budget_s", 30) if a.preview else rcfg.get("time_budget_s", 120))
    n_passes = 3 if not scene_mode else (3 if job.get("image") else 4)
    probe_share = 0.1 if (not scene_mode and not a.no_calibrate and job.get("calibrate", {}) is not False) else 0.0
    per_pass = max(5.0, budget * (1 - probe_share) / n_passes)
    sc.cycles.time_limit = per_pass
    log(f"resolution {out_w}x{out_h} ({res_name}), samples {sc.cycles.samples}, device {dev}, "
        f"time budget {budget:.0f}s -> {per_pass:.0f}s per pass")
    sc.render.film_transparent = True
    t_start = time.time()
    sv = Saved()
    result = {"name": name, "preview": a.preview, "resolution": [out_w, out_h], "resolution_preset": res_name,
              "samples": sc.cycles.samples, "device": dev, "time_budget_s": budget}
    if dev == "CPU":
        result["warning_cpu"] = "No GPU found - rendering on CPU; the time limit will cut samples, so expect more noise."

    if not scene_mode:
        plate_path = job.get("image") or meta["report"].get("image")
        plate, srgb = G.read_image(plate_path)
        plate_lin = G.srgb_to_linear(plate[..., :3]) if srgb else plate[..., :3]
        if not a.no_calibrate and job.get("calibrate", {"auto": True}) is not False:
            result["calibration"] = calibrate(sc, meta, pass_dir, plate_lin)
            log("calibration", result["calibration"])
        catchers = objs("catcher")
        product = objs("product")
        # product pass: catcher invisible to camera (still bounces/reflects)
        for c in catchers:
            sv.set(c, "visible_camera", False)
        p_exr = do_render(sc, os.path.join(pass_dir, f"{name}_product{suffix}.exr"))
        sv.restore()
        # differential pair: proxy surfaces rendered as ordinary surfaces, with and without the product
        seed = sc.cycles.seed
        for c in catchers:
            sv.set(c, "is_shadow_catcher", False)
        for o in product:
            sv.set(o, "visible_camera", False)  # still casts shadows, bounces and reflects
        c1 = do_render(sc, os.path.join(pass_dir, f"{name}_with{suffix}.exr"))
        for o in product + objs("product_root"):
            sv.set(o, "hide_render", True)
        sc.cycles.seed = seed
        c0 = do_render(sc, os.path.join(pass_dir, f"{name}_without{suffix}.exr"))
        sv.restore()
        import composite
        outs, qc = composite.run(plate_path, p_exr, None, out_dir, name + suffix, job.get("finish", {}),
                                 base_exr=c0, with_exr=c1)
        result.update({"outputs": outs, "qc": qc})
    else:
        product = objs("product")
        scene_objs = [o for o in sc.objects if role(o) == "scene"]
        meshes = [o for o in scene_objs if o.type in ("MESH", "CURVE", "SURFACE", "META", "FONT", "CURVES")]
        # plate: user-supplied or rendered without the product
        sv.set(sc.render, "film_transparent", False)
        if job.get("image"):
            plate_path = job["image"]
        else:
            for o in product:
                sv.set(o, "hide_render", True)
            plate_path = do_render(sc, os.path.join(out_dir, f"{name}_0_plate{suffix}.png"), "png")
            sv.restore()
            sv.set(sc.render, "film_transparent", False)
        full = do_render(sc, os.path.join(out_dir, f"{name}_4_composite{suffix}.png"), "png")
        sv.restore()
        for o in meshes:
            sv.set(o, "visible_camera", False)
        p_png = do_render(sc, os.path.join(out_dir, f"{name}_1_product{suffix}.png"), "png")
        sv.restore()
        for o in product:
            sv.set(o, "visible_camera", False)
        for o in meshes:
            sv.set(o, "is_shadow_catcher", True)
        s_png = do_render(sc, os.path.join(out_dir, f"{name}_2_shadow{suffix}.png"), "png")
        sv.restore()
        # product + shadow = product over shadow (display space)
        P, _ = G.read_image(p_png)
        S, _ = G.read_image(s_png)
        Pa, Sa = P[..., 3:4], S[..., 3:4]
        A = Pa + (1 - Pa) * Sa
        rgb = (P[..., :3] * Pa + (1 - Pa) * S[..., :3] * Sa) / np.maximum(A, 1e-6)
        o3 = os.path.join(out_dir, f"{name}_3_product_shadow{suffix}.png")
        G.write_image(o3, np.dstack([rgb, A[..., 0]]), bits=16)
        result["outputs"] = {"plate": plate_path, "composite": full, "product": p_png, "shadow": s_png, "product_shadow": o3}
        ys, xs = np.nonzero(Pa[..., 0] > 0.5)
        if len(ys):
            import composite
            result["outputs"]["qc_sheet"] = composite.qc_sheet(os.path.join(out_dir, f"{name}{suffix}_qc_sheet.jpg"), full,
                                                               [p_png, s_png, o3], [xs.min(), ys.min(), xs.max(), ys.max()])

    result["render_seconds"] = round(time.time() - t_start, 1)
    plate_w = meta["report"].get("plate_size", base_res)[0] if isinstance(meta["report"].get("plate_size"), list) else base_res[0]
    if out_w > plate_w * 1.05 and not scene_mode:
        result["note_upscaled_plate"] = (f"output {out_w}px wide but the scene image is {plate_w}px: the background is upscaled "
                                         "(product and shadow are rendered sharp at full size).")
    if a.preview:
        sc.render.resolution_x, sc.render.resolution_y = base_res  # previews don't change the saved .blend size
    if not a.no_save and not a.preview:
        bpy.ops.wm.save_mainfile()
        result["blend"] = bpy.data.filepath
    elif not a.no_save and "calibration" in result:
        bpy.ops.wm.save_mainfile()  # keep calibrated lights so the next preview starts from them
        result["blend"] = bpy.data.filepath
    G.save_json(os.path.join(out_dir, f"{name}_render_report{suffix}.json"), result)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
