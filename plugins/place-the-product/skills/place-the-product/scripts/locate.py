"""Pixel -> 3D helpers on a solved scene (run through Blender: blender -b --factory-startup -P <script> -- <args>).

  blender -b --factory-startup -P locate.py -- --work work --px 812,455 [--px 900,470 ...]   world point + surface for each pixel
  blender -b --factory-startup -P locate.py -- --work work --measure 640,300,640,560         metric distance between two pixels
  blender -b --factory-startup -P locate.py -- --work work --sun-from-shadow 700,300:720,580 object-point pixel : its shadow pixel
                                                                        -> direction TO the sun/key light
Pixels are in full plate resolution. Output is JSON.
"""
import argparse
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ptp_geo as G  # noqa: E402


class World:
    def __init__(self, work):
        self.scene = G.load_json(os.path.join(work, "scene.json"))
        z = np.load(os.path.join(work, "world.npz"))
        self.P = z["points"].astype(np.float64)
        self.N = z["normals"].astype(np.float64)
        self.M = z["mask"].astype(bool)
        self.Hs, self.Ws = self.M.shape
        self.W, self.H = self.scene["image_size"]
        self.cam = G.Camera.from_scene(self.scene)

    def to_grid(self, x, y):
        return (int(np.clip(y * self.Hs / self.H, 0, self.Hs - 1)), int(np.clip(x * self.Ws / self.W, 0, self.Ws - 1)))

    def point(self, x, y):
        gy, gx = self.to_grid(x, y)
        if self.M[gy, gx]:
            return self.P[gy, gx]
        # nearest valid
        ys, xs = np.nonzero(self.M)
        i = np.argmin((ys - gy) ** 2 + (xs - gx) ** 2)
        return self.P[ys[i], xs[i]]

    def local_plane(self, x, y, radius_px=None, thresh=None):
        """Fit the surface around a pixel. Returns dict with point, normal, kind, plane (n, d), region mask."""
        gy, gx = self.to_grid(x, y)
        r = radius_px or max(6, int(0.03 * max(self.Ws, self.Hs)))
        y0, y1 = max(0, gy - r), min(self.Hs, gy + r + 1)
        x0, x1 = max(0, gx - r), min(self.Ws, gx + r + 1)
        win = self.P[y0:y1, x0:x1][self.M[y0:y1, x0:x1]]
        p0 = self.point(x, y)
        dist = np.linalg.norm(p0 - self.cam.C)
        thresh = thresh or max(0.004, 0.004 * dist)
        n_hint = self.N[gy, gx] if self.M[gy, gx] else None
        n, d, inl = G.fit_plane_ransac(win, thresh=thresh, normal_hint=n_hint, hint_tol_deg=35 if n_hint is not None else None)
        if n is None:
            n = n_hint if n_hint is not None else np.array([0, 0, 1.0])
            d = n @ p0
        # face the camera
        if n @ (self.cam.C - p0) < 0:
            n, d = -n, -d
        up = np.array([0, 0, 1.0])
        tilt = math.degrees(math.acos(np.clip(abs(n @ up), 0, 1)))
        kind = "other"
        if tilt < 15:
            kind = "horizontal"
            n = up if n[2] > 0 else -up
        elif tilt > 75:
            kind = "wall"
            h = np.array([n[0], n[1], 0.0]); h /= np.linalg.norm(h)
            # snap to room axes if close
            for ax in (np.array([1.0, 0, 0]), np.array([0, 1.0, 0])):
                if abs(h @ ax) > math.cos(math.radians(12)):
                    h = ax * np.sign(h @ ax)
            n = h
        # plane through the robust centre of inliers near the pixel
        if inl is not None and inl.sum() > 10:
            d = float(np.median(win[inl] @ n))
        else:
            d = float(n @ p0)
        # exact point under the pixel on that plane
        Q, t = self.cam.intersect_plane([[x, y]], n, d)
        return {"pixel": [x, y], "point": Q[0].tolist(), "normal": n.tolist(), "plane_d": d, "kind": kind,
                "tilt_from_horizontal_deg": round(tilt, 1), "distance_from_camera_m": round(float(t[0]), 3),
                "height_above_floor_m": round(float(Q[0][2]), 3)}

    def support_region(self, n, d, seed_px, thresh=None, normal_tol_deg=20):
        """Grid mask of the connected surface on plane (n, d) that contains seed_px."""
        dist = np.abs(self.P @ n - d)
        tol = thresh or 0.012
        cam_d = np.linalg.norm(self.P - self.cam.C, axis=-1)
        on = self.M & (dist < np.maximum(tol, 0.006 * cam_d)) & ((self.N @ n) > math.cos(math.radians(normal_tol_deg)))
        gy, gx = self.to_grid(*seed_px)
        if not on[gy, gx]:
            # nearest on-plane pixel to the seed
            ys, xs = np.nonzero(on)
            if not len(ys):
                return on
            i = np.argmin((ys - gy) ** 2 + (xs - gx) ** 2)
            gy, gx = ys[i], xs[i]
        return G.flood_fill(on, (gy, gx))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--px", action="append", default=[])
    ap.add_argument("--measure")
    ap.add_argument("--sun-from-shadow", help="obj_x,obj_y:shadow_x,shadow_y  (object point must stand on a surface you also click below it? no - uses depth)")
    a = ap.parse_args(G.script_argv())
    w = World(a.work)
    out = {}
    if a.px:
        out["points"] = []
        for s in a.px:
            x, y = [float(v) for v in s.split(",")]
            out["points"].append(w.local_plane(x, y))
    if a.measure:
        x1, y1, x2, y2 = [float(v) for v in a.measure.split(",")]
        p, q = w.point(x1, y1), w.point(x2, y2)
        out["measure"] = {"a": p.tolist(), "b": q.tolist(), "distance_m": round(float(np.linalg.norm(p - q)), 3),
                          "vertical_m": round(float(abs(p[2] - q[2])), 3)}
    if a.sun_from_shadow:
        o, s = a.sun_from_shadow.split(":")
        ox, oy = [float(v) for v in o.split(",")]
        sx, sy = [float(v) for v in s.split(",")]
        po, ps = w.point(ox, oy), w.point(sx, sy)
        d = po - ps
        d /= np.linalg.norm(d)
        out["to_light_direction"] = d.round(4).tolist()
        out["elevation_deg"] = round(math.degrees(math.asin(np.clip(d[2], -1, 1))), 1)
        out["azimuth_deg"] = round(math.degrees(math.atan2(d[1], d[0])), 1)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
