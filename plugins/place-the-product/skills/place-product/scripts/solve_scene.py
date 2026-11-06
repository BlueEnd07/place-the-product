"""Solve the camera + metric world frame of the scene image.

Run through Blender (its Python has numpy + OpenImageIO); Blender's bundled python also works:

  MoGe mode (default, recommended):
    blender -b --factory-startup -P solve_scene.py -- --image room.jpg --geo work/geo.npz --out work
  Vanishing-line mode (no MoGe, e.g. on a Mac without CUDA):
    blender -b --factory-startup -P solve_scene.py -- --image room.jpg --lines work/lines.json --out work

Optional scale fixes (MoGe metric scale is typically within ~5-10%):
    --ref "x1,y1,x2,y2=2.10"     two pixels whose real distance is known (metres), e.g. door top/bottom
    --camera-height 1.55         force camera height above the floor
    --scale 1.05                 plain multiplier

Writes:
    work/scene.json        camera (intrinsics, R_wc, location), world frame, diagnostics
    work/world.npz         per-pixel world points / normals / mask (analysis resolution)
    work/check_camera.jpg  plate with the solved floor grid, 1 m posts and horizon drawn on it -> LOOK AT IT
"""
import argparse
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ptp_geo as G  # noqa: E402


# ------------------------------------------------------------------ MoGe path
def solve_from_geo(geo_path, image_size):
    z = np.load(geo_path)
    P = z["points"].astype(np.float64)
    N = z["normal"].astype(np.float64)
    M = z["mask"].astype(bool)
    K = z["intrinsics"].astype(np.float64)
    Hs, Ws = M.shape

    valid = M & (np.linalg.norm(N, axis=-1) > 0.5)
    up, up_info = G.estimate_up(N[valid])
    X, man_info = G.estimate_manhattan_x(N[valid], up)
    Y = np.cross(up, X)
    R_wc = np.stack([X, Y, up], 0)  # rows: world axes in cv coords -> world = R_wc @ cv

    floor_h, floor_info = G.estimate_floor_height(P[valid], N[valid], up)
    warnings = []
    if floor_h is None:
        floor_h = -1.5
        warnings.append("Floor not visible: camera height ASSUMED 1.5 m. Give --camera-height or --ref to fix scale/height.")
    cam_h = -floor_h

    k = {"fx": float(K[0, 0]), "fy": float(K[1, 1]), "cx": float(K[0, 2]), "cy": float(K[1, 2])}
    # square pixels: average focal
    W, H = image_size
    f_px = 0.5 * (k["fx"] * W + k["fy"] * H)
    k["fx"], k["fy"] = f_px / W, f_px / H
    return {
        "P_cv": P, "N_cv": N, "mask": M, "R_wc": R_wc, "cam_h": cam_h, "k": k,
        "diag": {**up_info, **man_info, **floor_info}, "warnings": warnings, "analysis_size": [Ws, Hs],
    }


# ------------------------------------------------------------------ vanishing-line path
def vp_from_lines(lines):
    L = []
    for x1, y1, x2, y2 in lines:
        l = np.cross([x1, y1, 1.0], [x2, y2, 1.0])
        L.append(l / np.linalg.norm(l[:2]))
    L = np.array(L)
    _, _, Vt = np.linalg.svd(L)
    v = Vt[-1]
    return v  # homogeneous


def solve_from_lines(lines_path, image_size):
    """lines.json: {"x": [[x1,y1,x2,y2], ...], "y": [...], "z": [...optional]}  pixel coords (full res).
    x/y = two perpendicular horizontal room directions, z = vertical edges."""
    J = G.load_json(lines_path)
    W, H = image_size
    vx = vp_from_lines(J["x"])
    vy = vp_from_lines(J["y"])
    warnings = []
    if abs(vx[2]) < 1e-9 or abs(vy[2]) < 1e-9:
        raise SystemExit("x or y lines are parallel in the image (one-point perspective). Add lines of another direction or use MoGe.")
    vx = vx[:2] / vx[2]
    vy = vy[:2] / vy[2]
    pp = np.array([W / 2.0, H / 2.0])
    vz = None
    if J.get("z") and len(J["z"]) >= 2:
        vzh = vp_from_lines(J["z"])
        if abs(vzh[2]) > 1e-9 and np.linalg.norm(vzh[:2] / vzh[2] - pp) < 20 * max(W, H):
            vz = vzh[:2] / vzh[2]
    if vz is not None:
        # principal point = orthocentre of the VP triangle
        A = np.array([vz - vy, vz - vx])
        b = np.array([(vz - vy) @ vx, (vz - vx) @ vy])
        try:
            o = np.linalg.solve(A, b)
            if np.linalg.norm(o - pp) < 0.25 * max(W, H):
                pp = o
            else:
                warnings.append("orthocentre far from centre; using image centre")
        except np.linalg.LinAlgError:
            pass
    else:
        # verticals parallel in image: level camera with vertical lens shift (2-point perspective)
        horizon_y = 0.5 * (vx[1] + vy[1])
        pp = np.array([W / 2.0, horizon_y])
        warnings.append("vertical lines parallel: treating as level camera with lens shift (architectural 2-point perspective)")
    f2 = -((vx - pp) @ (vy - pp))
    if f2 <= 0:
        raise SystemExit("Inconsistent vanishing points (x and y not perpendicular?). Check the line sets.")
    f = math.sqrt(f2)
    dx = np.array([vx[0] - pp[0], vx[1] - pp[1], f]); dx /= np.linalg.norm(dx)
    dy = np.array([vy[0] - pp[0], vy[1] - pp[1], f]); dy /= np.linalg.norm(dy)
    dy = dy - (dy @ dx) * dx; dy /= np.linalg.norm(dy)
    up = np.cross(dx, dy)
    if up[1] > 0:  # make Z point up in the image (cv y is down)
        dy = -dy
        up = -up
    # keep X pointing roughly to camera right
    if dx[0] < 0:
        dx, dy = -dx, -dy
    R_wc = np.stack([dx, dy, up], 0)
    k = {"fx": f / W, "fy": f / H, "cx": pp[0] / W, "cy": pp[1] / H}
    cam_h = float(J.get("camera_height", 1.5))
    if "camera_height" not in J:
        warnings.append("camera height ASSUMED 1.5 m (no MoGe depth). Use --ref with a known length to fix the scale.")
    return {"R_wc": R_wc, "cam_h": cam_h, "k": k, "warnings": warnings,
            "diag": {"vp_x": vx.tolist(), "vp_y": vy.tolist(), "vp_z": None if vz is None else vz.tolist(),
                     "principal_point_px": pp.tolist()}}


def synth_points_from_planes(cam, planes, room, Ws, Hs):
    """Ray-cast a simple room (floor + optional walls/levels) to make a pseudo point map for VP mode."""
    ys, xs = np.mgrid[0:Hs, 0:Ws]
    px = np.stack([(xs + 0.5) * cam.W / Ws, (ys + 0.5) * cam.H / Hs], -1).reshape(-1, 2)
    r = cam.ray(px)
    best_t = np.full(len(r), np.inf)
    best_n = np.zeros((len(r), 3))
    cand = [(np.array([0, 0, 1.0]), 0.0, None)]
    cand.append((np.array([0, 0, -1.0]), -float(room.get("ceiling_height", 2.8)), None))
    for p in planes:
        if p["type"] == "wall":
            ax = {"x": 0, "y": 1}[p["axis"]]
            n = np.zeros(3); n[ax] = 1.0
            # through the given floor-junction pixel
            Q, _ = cam.intersect_plane([p["floor_pixel"]], [0, 0, 1.0], 0.0)
            d = Q[0][ax]
            if cam.C[ax] > d:
                cand.append((n, d, None))
            else:
                cand.append((-n, -d, None))
        elif p["type"] == "horizontal":
            poly = np.array(p["polygon"], dtype=np.float64) if p.get("polygon") else None
            cand.append((np.array([0, 0, 1.0]), float(p["height"]), poly))
    for n, d, poly in cand:
        denom = r @ n
        t = (d - cam.C @ n) / np.where(np.abs(denom) < 1e-9, 1e-9, denom)
        ok = (t > 0.05) & (denom < 0)
        if poly is not None:
            ok &= points_in_poly(px, poly)
        upd = ok & (t < best_t)
        best_t[upd] = t[upd]
        best_n[upd] = n
    valid = np.isfinite(best_t)
    Pw = cam.C + r * np.where(valid, best_t, 0)[:, None]
    return Pw.reshape(Hs, Ws, 3), best_n.reshape(Hs, Ws, 3), valid.reshape(Hs, Ws)


def points_in_poly(pts, poly):
    x, y = pts[:, 0], pts[:, 1]
    inside = np.zeros(len(pts), bool)
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        cond = ((y1 > y) != (y2 > y)) & (x < (x2 - x1) * (y - y1) / ((y2 - y1) + 1e-12) + x1)
        inside ^= cond
    return inside


# ------------------------------------------------------------------ overlay
def draw_line(img, p0, p1, color, width=2):
    H, W = img.shape[:2]
    n = int(max(abs(p1[0] - p0[0]), abs(p1[1] - p0[1]), 1)) + 1
    if n > 20000:
        return
    xs = np.linspace(p0[0], p1[0], n)
    ys = np.linspace(p0[1], p1[1], n)
    r = width // 2
    for ox in range(-r, r + 1):
        for oy in range(-r, r + 1):
            xi = np.round(xs + ox).astype(int)
            yi = np.round(ys + oy).astype(int)
            ok = (xi >= 0) & (xi < W) & (yi >= 0) & (yi < H)
            img[yi[ok], xi[ok], :3] = color


def clip_segment_to_front(cam, A, B):
    """Clip a world segment to the part in front of the camera; return pixel endpoints or None."""
    (pa,), (za,) = cam.project(A)[0], cam.project(A)[1]
    (pb,), (zb,) = cam.project(B)[0], cam.project(B)[1]
    near = 0.05
    if za < near and zb < near:
        return None
    if za < near or zb < near:
        t = (near - za) / (zb - za)
        M = np.asarray(A) + t * (np.asarray(B) - np.asarray(A))
        if za < near:
            A = M
        else:
            B = M
        pa = cam.project(A)[0][0]
        pb = cam.project(B)[0][0]
    return pa, pb


def render_check(plate_srgb, cam, world_pts, mask, out_path, diag):
    img = plate_srgb[..., :3].copy() * 0.85
    H, W = img.shape[:2]
    # floor extents from points near the floor
    fl = world_pts[mask & (np.abs(world_pts[..., 2]) < 0.04)]
    if len(fl) > 50:
        x0, x1 = np.percentile(fl[:, 0], [1, 99])
        y0, y1 = np.percentile(fl[:, 1], [1, 99])
    else:
        x0, x1, y0, y1 = -3, 3, 0.5, 6
    cx, cy = cam.C[0], cam.C[1]
    x0, x1 = max(x0, cx - 8), min(x1, cx + 8)
    y0, y1 = max(y0, cy - 8), min(y1, cy + 8)
    step = 0.5
    gx = np.arange(math.floor(x0 / step) * step, x1 + step, step)
    gy = np.arange(math.floor(y0 / step) * step, y1 + step, step)
    for x in gx:
        s = clip_segment_to_front(cam, [x, gy[0], 0], [x, gy[-1], 0])
        if s:
            col = (1.0, 0.25, 0.25) if abs(x) < 1e-6 else (1.0, 0.85, 0.2)
            draw_line(img, s[0], s[1], col, 2 if abs(x) < 1e-6 else 1)
    for y in gy:
        s = clip_segment_to_front(cam, [gx[0], y, 0], [gx[-1], y, 0])
        if s:
            draw_line(img, s[0], s[1], (0.2, 1.0, 0.4), 1)
    # 1 m vertical posts at grid corners
    for x in gx[::2]:
        for y in gy[::2]:
            s = clip_segment_to_front(cam, [x, y, 0], [x, y, 1.0])
            if s and 0 <= s[0][0] < W and 0 <= s[0][1] < H:
                draw_line(img, s[0], s[1], (0.3, 0.7, 1.0), 2)
    # horizon (points far away at camera height)
    fwd = cam.R_wc @ np.array([0, 0, 1.0])
    fwd[2] = 0
    if np.linalg.norm(fwd) > 1e-6:
        fwd /= np.linalg.norm(fwd)
        side = np.cross([0, 0, 1.0], fwd)
        A = cam.C + fwd * 1000 - side * 2000
        B = cam.C + fwd * 1000 + side * 2000
        s = clip_segment_to_front(cam, A, B)
        if s:
            draw_line(img, s[0], s[1], (1.0, 0.3, 1.0), 1)
    G.write_image(out_path, img, quality=90)


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--geo")
    ap.add_argument("--lines")
    ap.add_argument("--out", required=True)
    ap.add_argument("--ref", help='"x1,y1,x2,y2=metres" known distance between two pixels (MoGe mode)')
    ap.add_argument("--camera-height", type=float)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--analysis-size", type=int, default=640, help="long side of world.npz grid in VP mode")
    a = ap.parse_args(G.script_argv())

    plate, is_srgb = G.read_image(a.image)
    H, W = plate.shape[:2]
    plate_srgb = plate if is_srgb else G.linear_to_srgb(plate)
    if plate_srgb.shape[2] == 1:
        plate_srgb = np.repeat(plate_srgb, 3, 2)

    if a.geo:
        s = solve_from_geo(a.geo, (W, H))
        mode = "moge"
    elif a.lines:
        s = solve_from_lines(a.lines, (W, H))
        mode = "lines"
    else:
        raise SystemExit("give --geo (MoGe) or --lines")

    R_wc = s["R_wc"]
    cam_h = s["cam_h"]
    k = s["k"]
    warnings = list(s["warnings"])

    if mode == "moge":
        P = s["P_cv"]
        Hs, Ws = s["mask"].shape
        Pw = P @ R_wc.T
        Pw[..., 2] += cam_h
        Nw = s["N_cv"] @ R_wc.T
        mask = s["mask"]
    else:
        J = G.load_json(a.lines)
        sc = a.analysis_size / max(W, H)
        Ws, Hs = max(2, round(W * sc)), max(2, round(H * sc))
        cam0 = G.Camera(k["fx"] * W, k["fy"] * H, k["cx"] * W, k["cy"] * H, W, H, R_wc, [0, 0, cam_h])
        Pw, Nw, mask = synth_points_from_planes(cam0, J.get("planes", []), J.get("room", {}), Ws, Hs)

    # ---- scale corrections
    scale = a.scale
    cam_world = np.array([0.0, 0.0, cam_h])
    if a.camera_height:
        scale *= a.camera_height / cam_h
    if a.ref:
        pts, L = a.ref.split("=")
        x1, y1, x2, y2 = [float(v) for v in pts.split(",")]
        def sample(x, y):
            xi = int(np.clip(x * Ws / W, 0, Ws - 1)); yi = int(np.clip(y * Hs / H, 0, Hs - 1))
            return Pw[yi, xi]
        d = np.linalg.norm(sample(x1, y1) - sample(x2, y2))
        if d > 1e-6:
            scale *= float(L) / d
    if abs(scale - 1.0) > 1e-9:
        # scale about the floor point under the camera (keeps floor at z=0)
        Pw = Pw * scale
        cam_world = cam_world * scale
        cam_h *= scale

    # world normals: in MoGe mode convert; in VP mode already world
    if mode == "moge":
        Nw = Nw / (np.linalg.norm(Nw, axis=-1, keepdims=True) + 1e-9)
    # R_wc rows are the world axes expressed in cv camera coords, so world = R_wc @ cv.

    scene = {
        "version": 1,
        "mode": mode,
        "image": os.path.abspath(a.image),
        "image_size": [W, H],
        "analysis_size": [Ws, Hs],
        "camera": {
            "intrinsics_norm": k,
            "R_wc": R_wc.tolist(),
            "location": cam_world.tolist(),
            "fov_x_deg": round(math.degrees(2 * math.atan(0.5 / k["fx"])), 3),
            "fov_y_deg": round(math.degrees(2 * math.atan(0.5 / k["fy"])), 3),
        },
        "camera_height_m": round(float(cam_h), 3),
        "scale_applied": scale,
        "diagnostics": s["diag"],
        "warnings": warnings,
    }
    scene["camera"]["blender"] = G.blender_camera_params(scene)

    os.makedirs(a.out, exist_ok=True)
    np.savez_compressed(os.path.join(a.out, "world.npz"), points=Pw.astype(np.float32), normals=Nw.astype(np.float32),
                        mask=mask, image_size=np.array([W, H]))
    # quick extent report
    m = mask
    ext = {"x": np.percentile(Pw[m][:, 0], [2, 98]).round(2).tolist(),
           "y": np.percentile(Pw[m][:, 1], [2, 98]).round(2).tolist(),
           "z": np.percentile(Pw[m][:, 2], [2, 98]).round(2).tolist()} if m.any() else {}
    scene["scene_extent_m"] = ext
    G.save_json(os.path.join(a.out, "scene.json"), scene)

    cam = G.Camera.from_scene(scene)
    render_check(plate_srgb, cam, resize_to(Pw, H, W), resize_to(mask, H, W), os.path.join(a.out, "check_camera.jpg"), scene)

    import json
    print(json.dumps({k2: scene[k2] for k2 in ("mode", "image_size", "camera_height_m", "scale_applied", "warnings", "scene_extent_m")}, indent=2))
    print(json.dumps({"fov_x_deg": scene["camera"]["fov_x_deg"], "lens_mm": round(scene["camera"]["blender"]["lens"], 2),
                      "shift": [round(scene["camera"]["blender"]["shift_x"], 4), round(scene["camera"]["blender"]["shift_y"], 4)],
                      **{kk: (round(v, 3) if isinstance(v, float) else v) for kk, v in scene["diagnostics"].items()}}, indent=2))
    print("check image:", os.path.join(a.out, "check_camera.jpg"))


def resize_to(a, H, W):
    return G.resize_nearest(a, H, W)


if __name__ == "__main__":
    main()
