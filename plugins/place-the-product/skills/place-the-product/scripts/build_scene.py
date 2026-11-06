"""Build the placement .blend from a job file.

    blender -b --factory-startup --python-exit-code 1 -P build_scene.py -- --job job.json

Two modes, chosen by the job:
  * image mode  (job has "work_dir" from solve_scene.py): camera + geometry come from the photo/render.
  * scene mode  (job has "scene_blend"): the architect's own Blender scene is used as-is (camera, geometry, lights).

Never modifies the source files: the product and scene are appended/copied into a NEW .blend in output_dir.
See references/job_schema.md for every field.
"""
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ptp_geo as G  # noqa: E402

ROLE = "ptp_role"


# ------------------------------------------------------------------ utils
def log(*a):
    print("[ptp]", *a, flush=True)


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    return ap.parse_args(argv)


def set_enum(obj, prop, *candidates):
    items = [i.identifier for i in obj.bl_rna.properties[prop].enum_items]
    for c in candidates:
        if c in items:
            setattr(obj, prop, c)
            return c
    return None


def setup_device(sc, want="auto"):
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    if want == "cpu":
        return "CPU"
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
    except KeyError:
        return "CPU"
    order = ["OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"] if want == "auto" else [want.upper()]
    for dt in order:
        try:
            prefs.compute_device_type = dt
        except TypeError:
            continue
        try:
            prefs.refresh_devices()
        except AttributeError:
            prefs.get_devices()
        devs = [d for d in prefs.devices if d.type == dt]
        if devs:
            for d in prefs.devices:
                d.use = d.type == dt
            sc.cycles.device = "GPU"
            return dt
    return "CPU"


def render_settings(sc, W, H, job, scene_mode):
    r = job.get("render", {})
    dev = setup_device(sc, r.get("device", "auto"))
    sc.render.resolution_x, sc.render.resolution_y = int(W), int(H)
    sc.render.resolution_percentage = 100
    sc.cycles.samples = int(r.get("samples", 300))
    sc.cycles.use_denoising = True
    sc.cycles.max_bounces = int(r.get("max_bounces", 8))
    sc.render.film_transparent = True
    if not scene_mode:
        set_enum(sc.view_settings, "view_transform", "Standard")
        set_enum(sc.view_settings, "look", "None")
        sc.view_settings.exposure = 0.0
        sc.view_settings.gamma = 1.0
    log("render device:", dev)
    return dev


def tag(obj, role):
    obj[ROLE] = role


def link(obj, coll):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    coll.objects.link(obj)


def get_coll(name, parent=None):
    c = bpy.data.collections.get(name) or bpy.data.collections.new(name)
    if c.name not in [x.name for x in (parent or bpy.context.scene.collection).children]:
        (parent or bpy.context.scene.collection).children.link(c)
    return c


def camera_from_blender(cam_obj, W, H):
    """ptp_geo.Camera from a Blender camera (for scene mode)."""
    cd = cam_obj.data
    fit = cd.sensor_fit
    if fit == "AUTO":
        fit = "HORIZONTAL" if W >= H else "VERTICAL"
    if fit == "HORIZONTAL":
        f_px = cd.lens / cd.sensor_width * W
    else:
        f_px = cd.lens / (cd.sensor_height if cd.sensor_fit == "VERTICAL" else cd.sensor_width) * H
    m = max(W, H)
    cx = W / 2 - cd.shift_x * m
    cy = H / 2 + cd.shift_y * m
    M = cam_obj.matrix_world
    R_bl = np.array([[M[i][j] for j in range(3)] for i in range(3)])
    # remove scale
    R_bl /= np.linalg.norm(R_bl, axis=0, keepdims=True)
    R_wc = R_bl @ G.F_CV_TO_BL
    return G.Camera(f_px, f_px, cx, cy, W, H, R_wc, np.array(M.translation))


# ------------------------------------------------------------------ product
def append_product(pcfg, coll):
    path = os.path.abspath(pcfg["blend"])
    if not os.path.exists(path):
        raise SystemExit(f"product blend not found: {path}")
    want_coll = pcfg.get("collection")
    include_lights = bool(pcfg.get("include_lights", False))
    before_scenes = set(bpy.data.scenes.keys())
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        if want_coll:
            if want_coll not in src.collections:
                raise SystemExit(f"collection '{want_coll}' not in product file. Has: {list(src.collections)}")
            dst.collections = [want_coll]
        else:
            scene_name = pcfg.get("scene") or (src.scenes[0] if src.scenes else None)
            dst.scenes = [scene_name]
    unit_scale = 1.0
    objs = []
    if want_coll:
        c = bpy.data.collections[want_coll] if want_coll in bpy.data.collections else dst.collections[0]
        objs = list(c.all_objects)
    else:
        new_scenes = [s for s in bpy.data.scenes if s.name not in before_scenes]
        s = new_scenes[0]
        unit_scale = s.unit_settings.scale_length if s.unit_settings.system != "NONE" else 1.0
        vl = s.view_layers[0]
        for o in s.objects:
            try:
                visible = not o.hide_render and o.visible_get(view_layer=vl)
            except TypeError:
                visible = not o.hide_render
            if not visible and not (o.type == "EMPTY"):
                continue
            objs.append(o)
    keep = []
    for o in objs:
        if o.type == "CAMERA":
            continue
        if o.type == "LIGHT" and not include_lights:
            continue
        keep.append(o)
    for o in keep:
        link(o, coll)
        tag(o, "product")
    if not want_coll:
        for s in [s for s in bpy.data.scenes if s.name not in before_scenes]:
            w = s.world
            bpy.data.scenes.remove(s)
            if w and w.users == 0:
                bpy.data.worlds.remove(w)
    else:
        # the appended collection itself: unlink, we already relinked objects
        c = bpy.data.collections.get(want_coll)
        if c and c.users == 0:
            pass
    if abs(unit_scale - 1.0) > 1e-6:
        log(f"product file unit scale_length={unit_scale}; applying to keep real-world size")
    return keep, unit_scale


def product_root(objs, coll, unit_scale):
    root = bpy.data.objects.new("PTP_PRODUCT_ROOT", None)
    root.empty_display_type = "ARROWS"
    root.empty_display_size = 0.1
    coll.objects.link(root)
    tag(root, "product_root")
    sel = set(objs)
    # appended objects have no evaluated matrix_world until the depsgraph runs -> evaluate first,
    # otherwise any scale/rotation/offset stored on the product's root objects would be lost
    bpy.context.view_layer.update()
    for o in objs:
        if o.parent is None or o.parent not in sel:
            mw = o.matrix_world.copy()
            o.parent = root
            o.matrix_parent_inverse = Matrix.Identity(4)
            o.matrix_world = mw
    bpy.context.view_layer.update()
    # bbox in product-local (root at identity) space
    dg = bpy.context.evaluated_depsgraph_get()
    mins, maxs = np.full(3, np.inf), np.full(3, -np.inf)
    for o in objs:
        if o.type not in ("MESH", "CURVE", "SURFACE", "META", "FONT", "CURVES", "POINTCLOUD", "VOLUME"):
            continue
        oe = o.evaluated_get(dg)
        for c in oe.bound_box:
            p = np.array(oe.matrix_world @ Vector(c))
            mins = np.minimum(mins, p)
            maxs = np.maximum(maxs, p)
    if not np.isfinite(mins).all():
        raise SystemExit("product has no renderable geometry")
    mins *= unit_scale
    maxs *= unit_scale
    return root, mins, maxs


FRONT_ANGLE = {"-Y": 0.0, "+X": math.pi / 2, "+Y": math.pi, "-X": -math.pi / 2}


def product_matrix(P, front_dir, anchor_local, unit_scale, front_axis="-Y", mount="horizontal", axis_scale=(1, 1, 1)):
    """World matrix for the root so that anchor_local lands on P and the product front faces front_dir (horizontal).
    axis_scale = (width, depth, height) factors from product.dimensions, applied in the front-to--Y frame."""
    pre = Matrix.Rotation(-FRONT_ANGLE.get(front_axis, 0.0), 4, "Z")  # bring product front to -Y
    th = math.atan2(front_dir[1], front_dir[0]) - (-math.pi / 2)
    R = Matrix.Rotation(th, 4, "Z")
    S = Matrix.Scale(unit_scale, 4)
    a = Vector(anchor_local)
    K = Matrix.Diagonal((*[float(v) for v in axis_scale], 1.0))
    return Matrix.Translation(Vector(P)) @ R @ Matrix.Translation(-a) @ K @ pre @ S


def local_bbox_after_pre(mins, maxs, front_axis):
    """bbox (in metres) of the product after the 'front to -Y' pre-rotation."""
    pre = Matrix.Rotation(-FRONT_ANGLE.get(front_axis, 0.0), 3, "Z")
    pts = np.array([[x, y, z] for x in (mins[0], maxs[0]) for y in (mins[1], maxs[1]) for z in (mins[2], maxs[2])])
    pts = np.array([list(pre @ Vector(p)) for p in pts])
    return pts.min(0), pts.max(0)


def anchor_for(mins, maxs, mount):
    c = 0.5 * (mins + maxs)
    if mount == "wall":
        return np.array([c[0], maxs[1], c[2]])  # back face centre (front faces -Y, back at +Y)
    if mount == "ceiling":
        return np.array([c[0], c[1], maxs[2]])
    return np.array([c[0], c[1], mins[2]])  # base centre


# ------------------------------------------------------------------ geometry sources
class ImageGeo:
    def __init__(self, work):
        from locate import World
        self.w = World(work)
        self.cam = self.w.cam
        self.scene = self.w.scene

    def surface(self, px, hint):
        s = self.w.local_plane(px[0], px[1])
        if hint in ("horizontal", "wall") and s["kind"] != hint:
            log(f"WARNING: surface at {px} looks '{s['kind']}' (tilt {s['tilt_from_horizontal_deg']} deg) but job says '{hint}'. Using job.")
            n = np.array([0, 0, 1.0]) if hint == "horizontal" else np.array(s["normal"]) * np.array([1, 1, 0])
            if hint == "wall" and np.linalg.norm(n) < 1e-3:
                v = self.cam.C - np.array(s["point"]); n = np.array([v[0], v[1], 0])
            n = n / np.linalg.norm(n)
            if n @ (self.cam.C - np.array(s["point"])) < 0:
                n = -n
            Q, _ = self.cam.intersect_plane([px], n, float(n @ np.array(s["point"])))
            s.update(kind=hint, normal=n.tolist(), plane_d=float(n @ Q[0]), point=Q[0].tolist())
        return s


class SceneGeo:
    def __init__(self, cam_obj, W, H, exclude):
        self.cam = camera_from_blender(cam_obj, W, H)
        self.exclude = exclude

    def surface(self, px, hint):
        sc = bpy.context.scene
        dg = bpy.context.evaluated_depsgraph_get()
        r = self.cam.ray([px])[0]
        origin = Vector(self.cam.C)
        hit, loc, nrm, _, obj, _ = sc.ray_cast(dg, origin, Vector(r))
        if not hit:
            raise SystemExit(f"pixel {px} does not hit any scene geometry")
        n = np.array(nrm)
        p = np.array(loc)
        if n @ (self.cam.C - p) < 0:
            n = -n
        tilt = math.degrees(math.acos(np.clip(abs(n[2]), 0, 1)))
        kind = hint if hint in ("horizontal", "wall") else ("horizontal" if tilt < 15 else "wall" if tilt > 75 else "other")
        if kind == "horizontal":
            n = np.array([0, 0, 1.0])
        elif kind == "wall":
            n = np.array([n[0], n[1], 0.0]); n /= np.linalg.norm(n)
        return {"pixel": list(px), "point": p.tolist(), "normal": n.tolist(), "plane_d": float(n @ p), "kind": kind,
                "hit_object": obj.name, "height_above_floor_m": round(float(p[2]), 3)}


def room_axes_from_scene():
    return [np.array(v, dtype=float) for v in ([1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0])]


# ------------------------------------------------------------------ placement
def place(job, geo, root, mins, maxs, unit_scale):
    pl = job["placement"]
    front_axis = job["product"].get("front_axis", "-Y")
    lmin, lmax = local_bbox_after_pre(mins, maxs, front_axis)
    pcfg = job["product"]
    k, size_rep = G.size_correction(lmax - lmin, pcfg.get("dimensions"), pcfg.get("scale_mode", "uniform"), pcfg.get("scale"))
    lmin, lmax = lmin * k, lmax * k
    if size_rep.get("warning"):
        log("WARNING:", size_rep["warning"])
    log("product size:", size_rep)
    cam = geo.cam
    hint = pl.get("surface", "auto")

    if "location" in pl:
        P = np.array(pl["location"], dtype=float)
        px, _ = cam.project(P)
        surf = geo.surface(px[0].tolist(), hint)
        surf["point"] = P.tolist()
    else:
        if "box" in pl:
            x0, y0, x1, y1 = pl["box"]
            bottom = [(x0 + x1) / 2, y1 - 0.06 * (y1 - y0)]
            centre = [(x0 + x1) / 2, (y0 + y1) / 2]
            if hint == "wall":
                surf = geo.surface(centre, hint)
            elif hint == "horizontal":
                surf = geo.surface(bottom, hint)
            else:  # table/floor products are the common case: the box bottom rests on the surface
                surf = geo.surface(bottom, "auto")
                if surf["kind"] != "horizontal":
                    surf = geo.surface(centre, "auto")
        else:
            probe = pl["pixel"]
            surf = geo.surface(probe, hint)
        P = np.array(surf["point"])

    mount = pl.get("mount") or ("wall" if surf["kind"] == "wall" else "horizontal")
    n = np.array(surf["normal"])
    anchor = anchor_for(lmin, lmax, mount)

    def front_for(Pp):
        if mount == "wall":
            return np.array([n[0], n[1], 0.0]) / max(1e-9, np.linalg.norm(n[:2]))
        orient = pl.get("orient", "room")
        to_cam = cam.C - Pp
        to_cam[2] = 0
        to_cam /= max(1e-9, np.linalg.norm(to_cam))
        if orient == "camera":
            f = to_cam
        elif orient == "fixed":
            f = np.array([0, -1.0, 0])
        else:  # room-aligned: the room axis closest to facing the camera
            f = max(room_axes_from_scene(), key=lambda ax: ax @ to_cam)
        yaw = math.radians(pl.get("yaw_deg", 0.0))
        c, s = math.cos(yaw), math.sin(yaw)
        return np.array([c * f[0] - s * f[1], s * f[0] + c * f[1], 0.0])

    def corners_world(Pp):
        Mx = product_matrix(Pp, front_for(Pp), anchor, 1.0, "-Y", mount)
        pts = [Mx @ Vector((x, y, z)) for x in (lmin[0], lmax[0]) for y in (lmin[1], lmax[1]) for z in (lmin[2], lmax[2])]
        return np.array([list(p) for p in pts])

    def proj_box(Pp):
        uv, z = cam.project(corners_world(Pp))
        return np.array([uv[:, 0].min(), uv[:, 1].min(), uv[:, 0].max(), uv[:, 1].max()]), z

    report = {}
    if "box" in pl and pl.get("fit_box", True):
        target = np.array(pl["box"], dtype=float)
        tc = np.array([(target[0] + target[2]) / 2, (target[1] + target[3]) / 2])
        if mount == "wall":
            e1 = np.cross([0, 0, 1.0], n); e1 /= np.linalg.norm(e1)
            e2 = np.array([0, 0, 1.0])
        else:
            e1, e2 = np.array([1.0, 0, 0]), np.array([0, 1.0, 0])
        uvp = np.zeros(2)
        for _ in range(25):
            def resid(q):
                b, _ = proj_box(P + q[0] * e1 + q[1] * e2)
                return np.array([(b[0] + b[2]) / 2, (b[1] + b[3]) / 2]) - tc
            r0 = resid(uvp)
            if np.linalg.norm(r0) < 0.3:
                break
            Jm = np.zeros((2, 2))
            h = 0.002
            for i in range(2):
                dq = np.zeros(2); dq[i] = h
                Jm[:, i] = (resid(uvp + dq) - r0) / h
            try:
                step = -np.linalg.lstsq(Jm, r0, rcond=None)[0]
            except np.linalg.LinAlgError:
                break
            if np.linalg.norm(step) > 0.5:
                step *= 0.5 / np.linalg.norm(step)
            uvp = uvp + step
        P = P + uvp[0] * e1 + uvp[1] * e2
        b, _ = proj_box(P)
        bw, bh = target[2] - target[0], target[3] - target[1]
        report["box_fit"] = {"target_box": target.tolist(), "product_box": b.round(1).tolist(),
                             "width_ratio_box_over_product": round(bw / max(1e-6, b[2] - b[0]), 3),
                             "height_ratio_box_over_product": round(bh / max(1e-6, b[3] - b[1]), 3)}

    off = np.array(pl.get("offset_m", [0, 0, 0]), dtype=float)
    P = P + off
    if mount == "wall":
        P = P + n * float(pl.get("gap_m", 0.0))
    else:
        P[2] += float(pl.get("gap_m", 0.0))
    f = front_for(P)
    # apply the pre-rotation + unit scale via the root's matrix
    Mx = product_matrix(P, f, anchor, unit_scale, front_axis, mount, axis_scale=k)
    # anchor was computed in (pre-rotated, metres) space; product_matrix applies pre & scale first, so
    # the translation uses that space too. Done.
    root.matrix_world = Mx
    bpy.context.view_layer.update()
    b, z = proj_box(P)
    report.update({"product_scaling": size_rep, "mount": mount, "surface": surf, "location": P.round(4).tolist(),
                   "front_direction": f.round(3).tolist(), "product_size_m": (lmax - lmin).round(4).tolist(),
                   "projected_box_px": b.round(1).tolist(),
                   "projected_box_fraction_of_frame": round(float((b[2] - b[0]) * (b[3] - b[1]) / (cam.W * cam.H)), 4)})
    if (z <= 0).any():
        report["warning"] = "part of the product is behind the camera"
    return P, mount, surf, report, corners_world(P)


# ------------------------------------------------------------------ image-mode proxies
def plate_image(path):
    img = bpy.data.images.load(path, check_existing=True)
    img.name = "PTP_PLATE"
    ext = os.path.splitext(path)[1].lower()
    try:
        img.colorspace_settings.name = "Linear Rec.709" if ext in (".exr", ".hdr") else "sRGB"
    except TypeError:
        pass
    return img


def make_mesh(name, V, F, UV, coll, smooth=True):
    me = bpy.data.meshes.new(name)
    me.from_pydata(V.tolist(), [], F.tolist())
    me.update()
    uvl = me.uv_layers.new(name="UVMap")
    uvl.data.foreach_set("uv", UV[F].reshape(-1).astype(np.float32))
    if smooth:
        try:
            me.shade_smooth()
        except AttributeError:
            me.polygons.foreach_set("use_smooth", [True] * len(me.polygons))
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    return ob


def plate_tex_nodes(nt, img):
    uv = nt.nodes.new("ShaderNodeUVMap")
    uv.uv_map = "UVMap"
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    tex.extension = "EXTEND"
    tex.interpolation = "Linear"
    nt.links.new(uv.outputs["UV"], tex.inputs["Vector"])
    return tex


def env_material(img, strength):
    m = bpy.data.materials.new("PTP_ENV_plate_emission")
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Strength"].default_value = strength
    tex = plate_tex_nodes(nt, img)
    nt.links.new(tex.outputs["Color"], em.inputs["Color"])
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    return m


def catcher_material(img, ccfg):
    m = bpy.data.materials.new("PTP_CATCHER_surface")
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    b.inputs["Roughness"].default_value = float(ccfg.get("roughness", 0.6))
    if "Specular IOR Level" in b.inputs:
        b.inputs["Specular IOR Level"].default_value = float(ccfg.get("specular", 0.5))
    tex = plate_tex_nodes(nt, img)
    mul = nt.nodes.new("ShaderNodeMix") if bpy.app.version >= (3, 4, 0) else nt.nodes.new("ShaderNodeMixRGB")
    if mul.bl_idname == "ShaderNodeMix":
        mul.data_type = "RGBA"
        mul.blend_type = "MULTIPLY"
        mul.inputs[0].default_value = 1.0
        a_in, b_in, o = mul.inputs[6], mul.inputs[7], mul.outputs[2]
    else:
        mul.blend_type = "MULTIPLY"
        mul.inputs[0].default_value = 1.0
        a_in, b_in, o = mul.inputs[1], mul.inputs[2], mul.outputs[0]
    mul.name = mul.label = "PTP_ALBEDO_SCALE"
    s = float(ccfg.get("albedo_scale", 1.0))
    b_in.default_value = (s, s, s, 1)
    nt.links.new(tex.outputs["Color"], a_in)
    nt.links.new(o, b.inputs["Base Color"])
    nt.links.new(b.outputs["BSDF"], out.inputs["Surface"])
    return m


def set_visibility(ob, camera=True, diffuse=True, glossy=True, transmission=True, shadow=True, volume=True):
    ob.visible_camera = camera
    ob.visible_diffuse = diffuse
    ob.visible_glossy = glossy
    ob.visible_transmission = transmission
    ob.visible_shadow = shadow
    ob.visible_volume_scatter = volume


def build_proxies(job, geo, P, mount, surf, prod_size, img, coll):
    w = geo.w
    Pw, Mk = w.P, w.M
    Hs, Ws = Mk.shape
    ccfg = job.get("catcher", {})
    ecfg = job.get("env", {})
    size = float(np.max(prod_size))
    R = float(ccfg.get("radius_m") or np.clip(4.0 * size, 0.6, 3.0))
    n = np.array(surf["normal"])
    d = float(surf["plane_d"])
    near = Mk & (np.linalg.norm(Pw - P, axis=-1) < R)
    # snap the support surface (connected, on-plane) exactly onto the fitted plane
    support = w.support_region(n, d, surf["pixel"]) & near
    Pc = Pw.copy()
    off = Pc @ n - d
    Pc[support] -= off[support][:, None] * n
    # catcher at finer resolution
    step_c = max(1, int(round(max(Ws, Hs) / 900)))
    Vc, Fc, UVc = G.grid_mesh(np.where(near[..., None], Pc, 0), near, (Hs, Ws), step=step_c, cam_center=w.cam.C)
    catcher = make_mesh("PTP_CATCHER", Vc, Fc, UVc, coll)
    catcher.data.materials.append(catcher_material(img, ccfg))
    catcher.is_shadow_catcher = True
    tag(catcher, "catcher")
    log(f"catcher: radius {R:.2f} m, {len(Fc)} faces, support pixels {int(support.sum())}")

    env = None
    if ecfg.get("enabled", True):
        step_e = max(1, int(round(max(Ws, Hs) / float(ecfg.get("grid", 360)))))
        env_mask = Mk & ~near
        Ve, Fe, UVe = G.grid_mesh(Pw, env_mask, (Hs, Ws), step=step_e, cam_center=w.cam.C)
        env = make_mesh("PTP_ENV", Ve, Fe, UVe, coll)
        env.data.materials.append(env_material(img, float(ecfg.get("strength", 1.0))))
        set_visibility(env, camera=False, shadow=False)
        tag(env, "env")
        log(f"env mesh: {len(Fe)} faces")
    # remember the support region in pixels for calibration probes
    ys, xs = np.nonzero(support)
    probe = None
    if len(ys):
        sx, sy = w.W / Ws, w.H / Hs
        probe = [float(xs.min() * sx), float(ys.min() * sy), float((xs.max() + 1) * sx), float((ys.max() + 1) * sy)]
    mpath = os.path.join(job["output_dir"], f"{job.get('name', 'placement')}_support_mask.npy")
    np.save(mpath, support)
    return catcher, env, {"catcher_radius_m": R, "support_box_px": probe, "support_mask_path": mpath}


def make_world(sc, img_px_lin, wcfg, scene_mode):
    if scene_mode:
        return
    w = bpy.data.worlds.new("PTP_WORLD")
    sc.world = w
    w.use_nodes = True
    bg = next(n for n in w.node_tree.nodes if n.type == "BACKGROUND")
    col = wcfg.get("color")
    if col is None:
        col = img_px_lin.reshape(-1, 3).mean(0).tolist()
    bg.inputs[0].default_value = (*col[:3], 1)
    bg.inputs[1].default_value = float(wcfg.get("strength", 1.0))
    try:
        w.visibility.camera = False
    except AttributeError:
        pass


def make_lights(lights, coll):
    made = []
    for i, L in enumerate(lights or []):
        t = L["type"].upper()
        ld = bpy.data.lights.new(f"PTP_{t}_{i}", t)
        ob = bpy.data.objects.new(L.get("name", f"PTP_{t}_{i}"), ld)
        coll.objects.link(ob)
        tag(ob, "light")
        col = G.kelvin_to_rgb(L["kelvin"]) if "kelvin" in L else L.get("color", [1, 1, 1])
        ld.color = col[:3]
        if t == "SUN":
            d = Vector(L["to_light"]).normalized()
            ob.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
            ld.energy = float(L.get("strength", 3.0))
            ld.angle = math.radians(float(L.get("angle_deg", 1.0)))
            ob.location = Vector(L.get("location", (0, 0, 3)))
        else:
            ob.location = Vector(L["location"])
            ld.energy = float(L.get("power", 100.0))
            if "target" in L:
                ob.rotation_euler = (Vector(L["target"]) - ob.location).to_track_quat("-Z", "Y").to_euler()
            elif "direction" in L:
                ob.rotation_euler = Vector(L["direction"]).to_track_quat("-Z", "Y").to_euler()
            if t == "AREA":
                sz = L.get("size", [0.5, 0.5])
                ld.shape = "RECTANGLE"
                ld.size, ld.size_y = float(sz[0]), float(sz[1] if len(sz) > 1 else sz[0])
                if "spread_deg" in L:
                    ld.spread = math.radians(float(L["spread_deg"]))
            elif t in ("POINT", "SPOT"):
                ld.shadow_soft_size = float(L.get("radius", 0.05))
                if t == "SPOT":
                    ld.spot_size = math.radians(float(L.get("spot_deg", 60)))
                    ld.spot_blend = float(L.get("blend", 0.3))
        ob["ptp_base_energy"] = ld.energy
        made.append(ob)
    return made


def setup_camera_obj(sc, scene, img):
    bp = G.blender_camera_params(scene)
    cd = bpy.data.cameras.new("PTP_CAMERA")
    cd.sensor_fit = bp["sensor_fit"]
    cd.sensor_width = cd.sensor_height = bp["sensor"]
    cd.lens = bp["lens"]
    cd.shift_x, cd.shift_y = bp["shift_x"], bp["shift_y"]
    cd.clip_start, cd.clip_end = 0.01, 500
    cam = bpy.data.objects.new("PTP_CAMERA", cd)
    sc.collection.objects.link(cam)
    cam.matrix_world = Matrix(bp["matrix_world"])
    sc.camera = cam
    cd.show_background_images = True
    bg = cd.background_images.new()
    bg.image = img
    bg.alpha = 1.0
    bg.display_depth = "BACK"
    tag(cam, "camera")
    return cam


# ------------------------------------------------------------------ main
def main():
    a = args()
    job = G.load_json(a.job)
    job_dir = os.path.dirname(os.path.abspath(a.job))

    def P_(p):
        return p if p is None or os.path.isabs(p) else os.path.normpath(os.path.join(job_dir, p))

    for k in ("image", "work_dir", "output_dir", "scene_blend"):
        if job.get(k):
            job[k] = P_(job[k])
    job["product"]["blend"] = P_(job["product"]["blend"])
    if job.get("finish", {}).get("occlusion_mask"):
        job["finish"]["occlusion_mask"] = P_(job["finish"]["occlusion_mask"])
    name = job.get("name", "placement")
    out_dir = job["output_dir"]
    os.makedirs(out_dir, exist_ok=True)
    scene_mode = bool(job.get("scene_blend"))
    report = {"name": name, "mode": "scene" if scene_mode else "image"}

    if scene_mode:
        bpy.ops.wm.open_mainfile(filepath=job["scene_blend"])
        sc = bpy.context.scene
        if job.get("scene_camera"):
            sc.camera = bpy.data.objects[job["scene_camera"]]
        if sc.camera is None:
            raise SystemExit("scene has no active camera; set scene_camera in the job")
        W = int(sc.render.resolution_x * sc.render.resolution_percentage / 100)
        H = int(sc.render.resolution_y * sc.render.resolution_percentage / 100)
        if job.get("image"):
            pimg, _ = G.read_image(job["image"])
            if (pimg.shape[1], pimg.shape[0]) != (W, H):
                log(f"note: plate {pimg.shape[1]}x{pimg.shape[0]} differs from scene render size {W}x{H}; using the plate size")
                W, H = pimg.shape[1], pimg.shape[0]
        for o in sc.objects:
            if ROLE not in o:
                tag(o, "scene")
        render_settings(sc, W, H, job, True)
        report["plate_size"] = [int(W), int(H)]
        coll = get_coll("PTP_PRODUCT")
        objs, us = append_product(job["product"], coll)
        root, mins, maxs = product_root(objs, coll, us)
        geo = SceneGeo(sc.camera, W, H, set(objs))
        P, mount, surf, prep, corners = place(job, geo, root, mins, maxs, us)
        report["placement"] = prep
        lcoll = get_coll("PTP_LIGHTS")
        make_lights(job.get("lights"), lcoll)
        report["proxies"] = {"note": "scene mode: scene objects act as shadow catchers at render time"}
    else:
        scene = G.load_json(os.path.join(job["work_dir"], "scene.json"))
        job["image"] = job.get("image") or scene["image"]
        bpy.ops.wm.read_factory_settings(use_empty=True)
        sc = bpy.context.scene
        sc.name = "PTP"
        W, H = scene["image_size"]
        render_settings(sc, W, H, job, False)
        report["plate_size"] = [int(W), int(H)]
        img = plate_image(job.get("image") or scene["image"])
        cam = setup_camera_obj(sc, scene, img)
        coll = get_coll("PTP_PRODUCT")
        objs, us = append_product(job["product"], coll)
        root, mins, maxs = product_root(objs, coll, us)
        geo = ImageGeo(job["work_dir"])
        P, mount, surf, prep, corners = place(job, geo, root, mins, maxs, us)
        report["placement"] = prep
        pcoll = get_coll("PTP_PROXIES")
        catcher, env, pinfo = build_proxies(job, geo, P, mount, surf, np.array(prep["product_size_m"]), img, pcoll)
        report["proxies"] = pinfo
        plate_px, srgb = G.read_image(job.get("image") or scene["image"])
        plate_lin = G.srgb_to_linear(plate_px[..., :3]) if srgb else plate_px[..., :3]
        make_world(sc, plate_lin, job.get("world", {}), False)
        lcoll = get_coll("PTP_LIGHTS")
        make_lights(job.get("lights"), lcoll)
        sc.render.film_transparent = True

    # product pixel box (for calibration masks / QC)
    uv, _ = geo.cam.project(corners)
    report["product_box_px"] = [float(uv[:, 0].min()), float(uv[:, 1].min()), float(uv[:, 0].max()), float(uv[:, 1].max())]
    meta = {"job": job, "job_path": os.path.abspath(a.job), "report": report}
    sc["ptp"] = json.dumps(meta)
    blend_path = os.path.join(out_dir, f"{name}.blend")
    if job.get("pack", True):
        try:
            bpy.ops.file.pack_all()
        except RuntimeError as e:
            log("pack_all failed (continuing):", e)
    bpy.ops.wm.save_as_mainfile(filepath=blend_path, compress=True)
    G.save_json(os.path.join(out_dir, f"{name}_build_report.json"), report)
    log("saved", blend_path)
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
