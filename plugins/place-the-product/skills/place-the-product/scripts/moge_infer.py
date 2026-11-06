"""Run MoGe on the scene image and save a geometry file for solve_scene.py.

Runs inside the MoGe Python environment (see setup_moge.ps1 / setup_moge.sh), NOT inside Blender.

    <moge-python> moge_infer.py --image room.jpg --out work/geo.npz [--version v3|v2] [--fov-x 60]

Writes geo.npz with:
    points    (H, W, 3) float32  metric camera-space points, OpenCV axes (x right, y down, z forward)
    normal    (H, W, 3) float32  camera-space normals (OpenCV axes), facing the camera
    mask      (H, W)    bool     valid pixels
    intrinsics (3, 3)   float32  normalised intrinsics (fx/W, fy/H, cx/W, cy/H)
    image_size (2,)     int32    original image width, height
The maps are at analysis resolution (long side <= --max-size); intrinsics are resolution-free.
"""
import argparse
import json
import os
import sys
import time

import numpy as np

MODELS = {
    "v3": ["Ruicheng/moge-3-vitl", "Ruicheng/moge-3-vitg"],
    "v2": ["Ruicheng/moge-2-vitl-normal", "Ruicheng/moge-2-vitb-normal"],
}


def load_image(path, max_size):
    from PIL import Image, ImageOps
    im = Image.open(path)
    im = ImageOps.exif_transpose(im).convert("RGB")
    W, H = im.size
    s = min(1.0, max_size / max(W, H))
    if s < 1.0:
        im = im.resize((round(W * s), round(H * s)), Image.LANCZOS)
    return np.asarray(im).astype(np.float32) / 255.0, (W, H)


def normals_from_points(points, mask):
    """Fallback normals from the point map (cross product of neighbours)."""
    dx = np.zeros_like(points)
    dy = np.zeros_like(points)
    dx[:, 1:-1] = points[:, 2:] - points[:, :-2]
    dy[1:-1, :] = points[2:, :] - points[:-2, :]
    n = np.cross(dy, dx)  # OpenCV axes: x right, y down -> faces the camera (-z)
    n /= np.linalg.norm(n, axis=-1, keepdims=True) + 1e-9
    n[n[..., 2] > 0] *= -1  # make every normal face the camera
    n[~mask] = 0
    return n.astype(np.float32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--version", default="v3", choices=["v3", "v2"])
    ap.add_argument("--model", default=None, help="HF repo id or local .pt (overrides --version default)")
    ap.add_argument("--fov-x", type=float, default=None, help="known horizontal FOV in degrees (arch renders often know this)")
    ap.add_argument("--max-size", type=int, default=1600)
    ap.add_argument("--device", default=None)
    ap.add_argument("--fp16", action="store_true")
    args = ap.parse_args()

    import torch
    mps = getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available()
    device = args.device or ("cuda" if torch.cuda.is_available() else "mps" if mps else "cpu")
    if device == "cpu":
        print("WARNING: no CUDA GPU found, running on CPU (slow, a few minutes).", file=sys.stderr)

    if args.version == "v3":
        from moge.model.v3 import MoGeModel
    else:
        from moge.model.v2 import MoGeModel

    candidates = [args.model] if args.model else MODELS[args.version]
    model, used, err = None, None, None
    for name in candidates:
        try:
            model = MoGeModel.from_pretrained(name).to(device).eval()
            used = name
            break
        except Exception as e:  # noqa: BLE001
            err = e
            print(f"could not load {name}: {e}", file=sys.stderr)
    if model is None:
        raise SystemExit(f"No MoGe model could be loaded: {err}")

    img, (W0, H0) = load_image(args.image, args.max_size)
    t = torch.tensor(img, dtype=torch.float32, device=device).permute(2, 0, 1)
    t0 = time.time()
    with torch.no_grad():
        kw = dict(use_fp16=args.fp16)
        if args.fov_x:
            kw["fov_x"] = args.fov_x
        out = model.infer(t, **kw)
    dt = time.time() - t0

    points = out["points"].float().cpu().numpy().astype(np.float32)
    mask = out["mask"].cpu().numpy().astype(bool) if "mask" in out else np.isfinite(points).all(-1)
    mask &= np.isfinite(points).all(-1)
    points[~mask] = 0
    K = out["intrinsics"].float().cpu().numpy().astype(np.float32)
    if "normal" in out and out["normal"] is not None:
        normal = out["normal"].float().cpu().numpy().astype(np.float32)
        normal[~np.isfinite(normal).all(-1)] = 0
        # MoGe normals are in OpenCV camera space; make sure they face the camera
        flip = (normal * points).sum(-1) > 0
        normal[flip] *= -1
    else:
        normal = normals_from_points(points, mask)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    np.savez_compressed(args.out, points=points, normal=normal, mask=mask, intrinsics=K,
                        image_size=np.array([W0, H0], dtype=np.int32))
    fx, fy = K[0, 0], K[1, 1]
    fov_x = float(np.degrees(2 * np.arctan(0.5 / fx)))
    info = {"model": used, "device": device, "seconds": round(dt, 2), "analysis_size": [img.shape[1], img.shape[0]],
            "image_size": [W0, H0], "fov_x_deg": round(fov_x, 2), "fx_norm": float(fx), "fy_norm": float(fy),
            "cx_norm": float(K[0, 2]), "cy_norm": float(K[1, 2]),
            "valid_fraction": round(float(mask.mean()), 3),
            "depth_range_m": [round(float(np.percentile(points[mask][:, 2], 2)), 2),
                              round(float(np.percentile(points[mask][:, 2], 98)), 2)] if mask.any() else None}
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
