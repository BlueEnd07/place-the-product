"""Shared geometry / image helpers for place-the-product.

Pure numpy (+ OpenImageIO for image IO), so it runs inside Blender's bundled Python
(`<blender>/<ver>/python/bin/python`) and inside Blender itself.

Conventions
-----------
* Image pixels: x right, y down, origin top-left, in FULL plate resolution unless stated.
* "cv" camera space: OpenCV axes (x right, y down, z forward) - what MoGe outputs.
* World: Blender axes, metres, Z up, floor at z=0, camera above the origin.
* R_wc (3x3): world_vector = R_wc @ cv_vector.   Camera centre C (3,).
"""
import json
import math
import os

import numpy as np

F_CV_TO_BL = np.diag([1.0, -1.0, -1.0])  # cv camera axes -> Blender camera-local axes


# ------------------------------------------------------------------ image IO
def read_image(path):
    """Return float32 (H, W, C) and a flag telling whether the file is display-referred (sRGB)."""
    import OpenImageIO as oiio
    inp = oiio.ImageInput.open(path)
    if inp is None:
        raise IOError(f"cannot open image {path}: {oiio.geterror()}")
    spec = inp.spec()
    px = inp.read_image(format="float")
    inp.close()
    px = np.asarray(px, dtype=np.float32)
    if px.ndim == 2:
        px = px[..., None]
    ext = os.path.splitext(path)[1].lower()
    linear_file = ext in (".exr", ".hdr")
    orient = spec.get_int_attribute("Orientation", 1)
    if orient and orient != 1:
        px = _apply_exif_orientation(px, orient)
    return px, (not linear_file)


def _apply_exif_orientation(px, o):
    if o == 2: return px[:, ::-1]
    if o == 3: return px[::-1, ::-1]
    if o == 4: return px[::-1]
    if o == 5: return np.transpose(px, (1, 0, 2))
    if o == 6: return np.transpose(px, (1, 0, 2))[:, ::-1]
    if o == 7: return np.transpose(px, (1, 0, 2))[::-1, ::-1]
    if o == 8: return np.transpose(px, (1, 0, 2))[::-1]
    return px


def write_image(path, px, bits=8, quality=95, straight_alpha=True):
    """px float (H, W, C) already in the encoding wanted for the file (sRGB for png/jpg).
    straight_alpha=False for premultiplied data (e.g. EXR passes that composite.py reads back)."""
    import OpenImageIO as oiio
    px = np.ascontiguousarray(px, dtype=np.float32)
    H, W = px.shape[:2]
    C = 1 if px.ndim == 2 else px.shape[2]
    ext = os.path.splitext(path)[1].lower()
    if ext in (".exr",):
        fmt = "half"
    elif bits == 16 and ext in (".png", ".tif", ".tiff"):
        fmt = "uint16"
    else:
        fmt = "uint8"
    spec = oiio.ImageSpec(W, H, C, fmt)
    if ext in (".jpg", ".jpeg"):
        spec.attribute("Compression", f"jpeg:{quality}")
    if C == 4:
        spec.alpha_channel = 3
        if straight_alpha:
            spec.attribute("oiio:UnassociatedAlpha", 1)  # we hand over straight (un-premultiplied) alpha
    out = oiio.ImageOutput.create(path)
    if out is None:
        raise IOError(f"cannot create {path}: {oiio.geterror()}")
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    out.open(path, spec)
    if fmt != "half":
        px = np.clip(px, 0.0, 1.0)
    out.write_image(px)
    out.close()


def srgb_to_linear(c):
    c = np.clip(c, 0.0, None)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4).astype(np.float32)


def linear_to_srgb(c):
    c = np.clip(c, 0.0, None)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055).astype(np.float32)


def luminance(rgb):
    return rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722


def resize_nearest(a, H, W):
    h, w = a.shape[:2]
    yi = np.clip(((np.arange(H) + 0.5) * h / H).astype(int), 0, h - 1)
    xi = np.clip(((np.arange(W) + 0.5) * w / W).astype(int), 0, w - 1)
    return a[yi][:, xi]


def resize_bilinear(a, H, W):
    h, w = a.shape[:2]
    y = np.clip((np.arange(H) + 0.5) * h / H - 0.5, 0, h - 1)
    x = np.clip((np.arange(W) + 0.5) * w / W - 0.5, 0, w - 1)
    y0 = np.floor(y).astype(int); x0 = np.floor(x).astype(int)
    y1 = np.minimum(y0 + 1, h - 1); x1 = np.minimum(x0 + 1, w - 1)
    fy = (y - y0).astype(np.float32); fx = (x - x0).astype(np.float32)
    if a.ndim == 3:
        fy = fy[:, None, None]; fx = fx[None, :, None]
    else:
        fy = fy[:, None]; fx = fx[None, :]
    top = a[y0][:, x0] * (1 - fx) + a[y0][:, x1] * fx
    bot = a[y1][:, x0] * (1 - fx) + a[y1][:, x1] * fx
    return (top * (1 - fy) + bot * fy).astype(np.float32)


def resize_area(a, H, W):
    """Box-filter downscale, bilinear upscale, without extra deps."""
    h, w = a.shape[:2]
    if H >= h and W >= w:
        return resize_bilinear(a, H, W)
    if H >= h or W >= w:
        return resize_nearest(a, H, W)
    ys = (np.arange(H + 1) * h / H).astype(int)
    xs = (np.arange(W + 1) * w / W).astype(int)
    c = np.cumsum(np.cumsum(np.pad(a.astype(np.float64), ((1, 0), (1, 0)) + ((0, 0),) * (a.ndim - 2)), 0), 1)
    tot = c[ys[1:]][:, xs[1:]] - c[ys[:-1]][:, xs[1:]] - c[ys[1:]][:, xs[:-1]] + c[ys[:-1]][:, xs[:-1]]
    area = ((ys[1:] - ys[:-1])[:, None] * (xs[1:] - xs[:-1])[None, :]).astype(np.float64)
    if a.ndim == 3:
        area = area[..., None]
    return (tot / area).astype(np.float32)


def gaussian_blur(a, sigma):
    if sigma <= 0.05:
        return a
    r = max(1, int(math.ceil(sigma * 3)))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    out = a.astype(np.float32)
    for axis in (0, 1):
        pad = [(0, 0)] * out.ndim
        pad[axis] = (r, r)
        p = np.pad(out, pad, mode="edge")
        acc = np.zeros_like(out)
        for i, kv in enumerate(k):
            sl = [slice(None)] * out.ndim
            sl[axis] = slice(i, i + out.shape[axis])
            acc += kv * p[tuple(sl)]
        out = acc
    return out


# ------------------------------------------------------------------ camera
class Camera:
    """Pinhole camera in world space. Pixel coordinates refer to (W, H)."""

    def __init__(self, fx, fy, cx, cy, W, H, R_wc, C):
        self.fx, self.fy, self.cx, self.cy = float(fx), float(fy), float(cx), float(cy)
        self.W, self.H = int(W), int(H)
        self.R_wc = np.asarray(R_wc, dtype=np.float64)
        self.C = np.asarray(C, dtype=np.float64)

    @classmethod
    def from_scene(cls, scene, W=None, H=None):
        cam = scene["camera"]
        W0, H0 = scene["image_size"]
        W = W or W0
        H = H or H0
        k = cam["intrinsics_norm"]
        return cls(k["fx"] * W, k["fy"] * H, k["cx"] * W, k["cy"] * H, W, H,
                   np.array(cam["R_wc"]), np.array(cam["location"]))

    def project(self, P):
        P = np.atleast_2d(np.asarray(P, dtype=np.float64))
        pc = (P - self.C) @ self.R_wc  # = R_wc^T (P - C)
        z = pc[:, 2]
        x = self.fx * pc[:, 0] / z + self.cx
        y = self.fy * pc[:, 1] / z + self.cy
        return np.stack([x, y], -1), z

    def ray(self, px):
        px = np.atleast_2d(np.asarray(px, dtype=np.float64))
        d = np.stack([(px[:, 0] - self.cx) / self.fx, (px[:, 1] - self.cy) / self.fy, np.ones(len(px))], -1)
        d = d @ self.R_wc.T
        return d / np.linalg.norm(d, axis=1, keepdims=True)

    def intersect_plane(self, px, n, d):
        """Ray from pixel(s) with plane n.X = d. Returns points (N,3) and t."""
        r = self.ray(px)
        n = np.asarray(n, dtype=np.float64)
        denom = r @ n
        t = (d - self.C @ n) / np.where(np.abs(denom) < 1e-9, 1e-9, denom)
        return self.C + r * t[:, None], t


def blender_camera_params(scene):
    """Lens / sensor / shift / matrix for a Blender camera from scene.json."""
    W, H = scene["image_size"]
    k = scene["camera"]["intrinsics_norm"]
    horizontal = W >= H
    if horizontal:
        lens = k["fx"] * 36.0
    else:
        lens = k["fy"] * 36.0
    m = max(W, H)
    shift_x = (0.5 - k["cx"]) * W / m
    shift_y = (k["cy"] - 0.5) * H / m
    R = np.array(scene["camera"]["R_wc"]) @ F_CV_TO_BL
    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = scene["camera"]["location"]
    return {"lens": float(lens), "sensor_fit": "HORIZONTAL" if horizontal else "VERTICAL", "sensor": 36.0,
            "shift_x": float(shift_x), "shift_y": float(shift_y), "matrix_world": M.tolist()}


# ------------------------------------------------------------------ orientation from normals
def fibonacci_sphere(n):
    i = np.arange(n) + 0.5
    phi = np.arccos(1 - 2 * i / n)
    th = math.pi * (1 + 5 ** 0.5) * i
    return np.stack([np.cos(th) * np.sin(phi), np.sin(th) * np.sin(phi), np.cos(phi)], -1)


def estimate_up(normals_cv, max_tilt_deg=75.0, seed=0):
    """Gravity 'up' in cv camera coords from a set of unit surface normals (N,3).

    Indoor scenes: floors/tables/ceilings are perpendicular to up, walls contain it.
    Returns (up, confidence dict)."""
    rng = np.random.default_rng(seed)
    N = normals_cv[np.linalg.norm(normals_cv, axis=1) > 0.5]
    if len(N) > 15000:
        N = N[rng.choice(len(N), 15000, replace=False)]
    D = fibonacci_sphere(4000)
    D = D[D @ np.array([0, -1.0, 0]) > math.cos(math.radians(max_tilt_deg))]
    dots = np.abs(N @ D.T)  # (N, nd)
    horiz = (dots > math.cos(math.radians(6))).sum(0)
    vert = (dots < math.sin(math.radians(4))).sum(0)
    score = horiz + 0.5 * vert
    up = D[np.argmax(score)]
    for it in range(6):
        c = np.abs(N @ up)
        h = N[c > math.cos(math.radians(10 - it))]
        v = N[c < math.sin(math.radians(8 - it))]
        A = np.zeros((3, 3))
        if len(h):
            A += h.T @ h / len(h)
        if len(v):
            A -= 0.5 * v.T @ v / len(v)
        w, V = np.linalg.eigh(A)
        new = V[:, np.argmax(w)]
        if new @ up < 0:
            new = -new
        up = new / np.linalg.norm(new)
    if up[1] > 0:
        up = -up
    c = np.abs(N @ up)
    info = {"horizontal_fraction": float((c > math.cos(math.radians(8))).mean()),
            "vertical_fraction": float((c < math.sin(math.radians(8))).mean()),
            "camera_pitch_deg": float(math.degrees(math.asin(np.clip(-up[2], -1, 1)))),
            "camera_roll_deg": float(math.degrees(math.atan2(up[0], -up[1])))}
    return up, info


def estimate_manhattan_x(normals_cv, up):
    """Dominant wall direction -> world X axis (cv coords), the one closest to camera right."""
    e1 = np.array([1.0, 0, 0]) - up[0] * up
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(up, e1)
    N = normals_cv[np.abs(normals_cv @ up) < math.sin(math.radians(12))]
    N = N[np.linalg.norm(N, axis=1) > 0.5]
    conf = 0.0
    theta0 = 0.0
    if len(N) > 50:
        a = np.arctan2(N @ e2, N @ e1)
        z = np.exp(4j * a).mean()
        conf = float(abs(z))
        theta0 = float(np.angle(z) / 4)
    if conf < 0.15:  # no clear walls: align X with camera right
        theta0, conf = 0.0, 0.0
    # choose among theta0 + k*90deg the one closest to camera right (theta=0)
    cands = [theta0 + k * math.pi / 2 for k in range(4)]
    theta = min(cands, key=lambda t: abs(math.atan2(math.sin(t), math.cos(t))))
    X = math.cos(theta) * e1 + math.sin(theta) * e2
    return X / np.linalg.norm(X), {"wall_alignment_confidence": round(conf, 3),
                                   "room_yaw_vs_camera_deg": round(math.degrees(theta), 2)}


def estimate_floor_height(points_cv, normals_cv, up, bin_m=0.02):
    """Height (p.up) of the floor = lowest well supported upward-facing plane. None if not visible."""
    face_up = (normals_cv @ up) > math.cos(math.radians(14))
    h = points_cv[face_up] @ up
    if len(h) < 200:
        return None, {"floor_visible": False}
    lo, hi = np.percentile(h, 0.5), np.percentile(h, 99.5)
    bins = np.arange(lo - bin_m, hi + 2 * bin_m, bin_m)
    hist, edges = np.histogram(h, bins)
    need = max(150, 0.03 * len(h))
    # smooth with neighbours
    hs = hist + np.r_[0, hist[:-1]] + np.r_[hist[1:], 0]
    idx = np.where(hs >= need)[0]
    if not len(idx):
        return None, {"floor_visible": False}
    c = 0.5 * (edges[idx[0]] + edges[idx[0] + 1])
    sel = np.abs(h - c) < 0.05
    floor_h = float(np.median(h[sel]))
    # list other horizontal levels (tables, counters...) for the report
    levels = []
    peaks = [i for i in range(1, len(hs) - 1) if hs[i] >= need and hs[i] >= hs[i - 1] and hs[i] >= hs[i + 1]]
    for i in peaks:
        z = 0.5 * (edges[i] + edges[i + 1]) - floor_h
        if z > 0.08 and all(abs(z - l["z"]) > 0.06 for l in levels):
            levels.append({"z": round(float(z), 3), "support_px": int(hs[i])})
    return floor_h, {"floor_visible": True, "floor_support_px": int(sel.sum()), "horizontal_levels_above_floor": levels[:8]}


# ------------------------------------------------------------------ planes / regions
def fit_plane_ransac(P, iters=300, thresh=0.01, seed=0, normal_hint=None, hint_tol_deg=None):
    """Return (n, d, inlier_mask) with n.X = d, n unit."""
    rng = np.random.default_rng(seed)
    P = np.asarray(P, dtype=np.float64)
    best = (None, None, np.zeros(len(P), bool))
    if len(P) < 3:
        return best
    for _ in range(iters):
        s = P[rng.choice(len(P), 3, replace=False)]
        n = np.cross(s[1] - s[0], s[2] - s[0])
        nn = np.linalg.norm(n)
        if nn < 1e-9:
            continue
        n /= nn
        if normal_hint is not None and hint_tol_deg is not None:
            if abs(n @ normal_hint) < math.cos(math.radians(hint_tol_deg)):
                continue
        d = n @ s[0]
        inl = np.abs(P @ n - d) < thresh
        if inl.sum() > best[2].sum():
            best = (n, d, inl)
    n, d, inl = best
    if n is None:
        return best
    Q = P[inl]
    c = Q.mean(0)
    _, _, Vt = np.linalg.svd(Q - c, full_matrices=False)
    n = Vt[2]
    if normal_hint is not None and n @ normal_hint < 0:
        n = -n
    d = n @ c
    inl = np.abs(P @ n - d) < thresh
    return n, d, inl


def flood_fill(mask, seed_yx, max_iter=4000):
    """Connected component of `mask` containing seed (4-connectivity), numpy only."""
    reg = np.zeros_like(mask)
    y, x = seed_yx
    if not mask[y, x]:
        return reg
    reg[y, x] = True
    for _ in range(max_iter):
        g = reg.copy()
        g[1:] |= reg[:-1]
        g[:-1] |= reg[1:]
        g[:, 1:] |= reg[:, :-1]
        g[:, :-1] |= reg[:, 1:]
        g &= mask
        if g.sum() == reg.sum():
            break
        reg = g
    return reg


def grid_mesh(points, valid, uv_size, step=1, max_edge_ratio=0.05, cam_center=None):
    """Triangulate a (H, W, 3) point grid. Returns verts (V,3), faces (F,3) int, uvs (V,2).

    Faces whose edges jump in depth (relative to distance from camera) are dropped,
    so foreground objects don't get glued to the background."""
    P = points[::step, ::step]
    M = valid[::step, ::step]
    h, w = M.shape
    Hs, Ws = uv_size
    ys, xs = np.mgrid[0:h, 0:w]
    u = (xs * step + 0.5) / Ws
    v = 1.0 - (ys * step + 0.5) / Hs
    idx = -np.ones((h, w), dtype=np.int64)
    idx[M] = np.arange(M.sum())
    verts = P[M]
    uvs = np.stack([u[M], v[M]], -1)
    dist = np.linalg.norm(P - (cam_center if cam_center is not None else 0), axis=-1)

    a = idx[:-1, :-1]; b = idx[:-1, 1:]; c = idx[1:, :-1]; d = idx[1:, 1:]
    da = dist[:-1, :-1]; db = dist[:-1, 1:]; dc = dist[1:, :-1]; dd = dist[1:, 1:]
    lim = max_edge_ratio * np.minimum.reduce([da, db, dc, dd]) * max(step, 1)

    def ok(*pairs):
        r = np.ones(a.shape, bool)
        for p1, p2 in pairs:
            r &= np.linalg.norm(p1 - p2, axis=-1) < lim * 1.5 + 1e-6
        return r

    Pa, Pb, Pc, Pd = P[:-1, :-1], P[:-1, 1:], P[1:, :-1], P[1:, 1:]
    m1 = (a >= 0) & (b >= 0) & (c >= 0) & ok((Pa, Pb), (Pb, Pc), (Pa, Pc))
    m2 = (b >= 0) & (d >= 0) & (c >= 0) & ok((Pb, Pd), (Pd, Pc), (Pb, Pc))
    f1 = np.stack([a[m1], c[m1], b[m1]], -1)
    f2 = np.stack([b[m2], c[m2], d[m2]], -1)
    faces = np.concatenate([f1, f2], 0)
    return verts.astype(np.float32), faces.astype(np.int64), uvs.astype(np.float32)


# ------------------------------------------------------------------ colour temperature
def kelvin_to_rgb(k):
    """Approximate linear-ish RGB for a blackbody colour temperature (Tanner Helland fit), max channel = 1."""
    t = max(1000.0, min(40000.0, float(k))) / 100.0
    if t <= 66:
        r = 255.0
        g = 99.4708025861 * math.log(t) - 161.1195681661
        b = 0.0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307
    else:
        r = 329.698727446 * ((t - 60) ** -0.1332047592)
        g = 288.1221695283 * ((t - 60) ** -0.0755148492)
        b = 255.0
    rgb = np.clip(np.array([r, g, b]) / 255.0, 0, 1)
    rgb = srgb_to_linear(rgb)
    return (rgb / rgb.max()).tolist()


def rgb_to_kelvin(rgb_lin):
    """Inverse of kelvin_to_rgb by search (for reporting white balance)."""
    rgb = np.asarray(rgb_lin, dtype=np.float64)
    rgb = rgb / max(rgb.max(), 1e-6)
    best, bk = 1e9, 6500
    for k in range(1500, 15001, 50):
        c = np.array(kelvin_to_rgb(k))
        e = np.sum((np.log(c + 1e-3) - np.log(rgb + 1e-3)) ** 2)
        if e < best:
            best, bk = e, k
    return bk


UNIT_TO_M = {"m": 1.0, "cm": 0.01, "mm": 0.001, "in": 0.0254, "inch": 0.0254, "ft": 0.3048}


def preframe_dims(dims_xyz, front_axis="-Y"):
    """File bbox size (x, y, z) -> (width, depth, height) as seen from the product's front."""
    x, y, z = [float(v) for v in dims_xyz]
    return (y, x, z) if front_axis in ("+X", "-X") else (x, y, z)


def size_correction(model_wdh, spec=None, mode="uniform", plain_scale=None):
    """Scale factors (width, depth, height) that make the model match real dimensions.

    model_wdh: model size in metres as (width, depth, height) seen from the front.
    spec: {"width": 120, "depth": 45, "height": 180, "unit": "mm"} - any subset of the three.
    mode: "uniform" (keep proportions; factor from the given dimensions) or "per_axis" (stretch each given axis).
    Returns (factors[3], report dict)."""
    model = np.maximum(np.asarray(model_wdh, dtype=np.float64), 1e-9)
    rep = {"model_size_m": {a: round(float(model[i]), 5) for i, a in enumerate(["width", "depth", "height"])}}
    if plain_scale and not spec:
        k = np.full(3, float(plain_scale))
        rep.update(mode="plain", factor=float(plain_scale))
    elif spec:
        unit = UNIT_TO_M.get(str(spec.get("unit", "mm")).lower())
        if unit is None:
            raise ValueError(f"unknown unit {spec.get('unit')!r}; use one of {sorted(UNIT_TO_M)}")
        axes = ["width", "depth", "height"]
        given = {i: float(spec[a]) * unit for i, a in enumerate(axes) if spec.get(a) not in (None, "", 0)}
        if not given:
            raise ValueError("product.dimensions has none of width/depth/height")
        ratios = {i: v / model[i] for i, v in given.items()}
        r = np.array(list(ratios.values()))
        if mode == "per_axis":
            fill = float(np.median(r))
            k = np.array([ratios.get(i, fill) for i in range(3)])
        else:
            k = np.full(3, float(np.median(r)))
        spread = float(r.max() / r.min() - 1) if len(r) > 1 else 0.0
        rep.update(mode=mode, target_m={axes[i]: round(v, 5) for i, v in given.items()},
                   factors=k.round(5).tolist(), proportion_mismatch=round(spread, 4))
        if mode == "uniform" and spread > 0.03:
            rep["warning"] = (f"The given dimensions disagree with the model's proportions by {spread:.0%}. "
                              "Check width/depth/height (width = side to side seen from the front) and front_axis, "
                              "or use scale_mode 'per_axis' if the model really is out of proportion.")
    else:
        k = np.ones(3)
        rep.update(mode="none")
    rep["final_size_m"] = {a: round(float(model[i] * k[i]), 5) for i, a in enumerate(["width", "depth", "height"])}
    return k, rep


def script_argv():
    """CLI args whether run as `python x.py args` or `blender -b -P x.py -- args`."""
    import sys
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1:]
    if any(s.endswith("blender") or s.endswith("blender.exe") for s in sys.argv[:1]):
        return []
    return sys.argv[1:]


def load_json(p):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(p, obj):
    os.makedirs(os.path.dirname(os.path.abspath(p)) or ".", exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
