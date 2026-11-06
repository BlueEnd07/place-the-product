"""End-to-end self-test on a synthetic room with a KNOWN camera. Run after installing:

    blender -b --factory-startup -P selftest.py -- --out <folder> [--moge-python <path>] [--no-moge]

Without --moge-python it reads ~/.place-the-product/moge_python.txt; with --no-moge it tests vanishing-line mode.
Prints a PASS/FAIL table and leaves every intermediate file in <folder> for inspection (look at *_qc_sheet.jpg).
"""
import json
import math
import os
import subprocess
import sys

import bpy
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)
import ptp_geo as G  # noqa: E402


def run(cmd, label):
    print(f"\n=== {label}\n$ {' '.join(cmd)}", flush=True)
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = "\n".join((p.stdout + p.stderr).strip().splitlines()[-25:])
    print(tail, flush=True)
    if p.returncode != 0:
        raise SystemExit(f"FAILED at step: {label}")
    return p.stdout


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--moge-python")
    ap.add_argument("--no-moge", action="store_true")
    ap.add_argument("--moge-version", default="v3")
    a = ap.parse_args(G.script_argv())
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    blender = bpy.app.binary_path
    B = [blender, "-b", "--factory-startup", "--python-exit-code", "1", "-P"]

    run(B + [os.path.join(HERE, "make_test_assets.py"), "--", out, "--samples", "64"], "make test room + products")
    truth = G.load_json(os.path.join(out, "room_truth.json"))
    work = os.path.join(out, "work")

    moge_py = a.moge_python
    if not moge_py and not a.no_moge:
        f = os.path.join(os.path.expanduser("~"), ".place-the-product", "moge_python.txt")
        if os.path.exists(f):
            moge_py = open(f).read().strip()
    if moge_py and not a.no_moge:
        run([moge_py, os.path.join(SCRIPTS, "moge_infer.py"), "--image", os.path.join(out, "room.jpg"),
             "--out", os.path.join(work, "geo.npz"), "--version", a.moge_version], "MoGe geometry")
        run(B + [os.path.join(SCRIPTS, "solve_scene.py"), "--", "--image", os.path.join(out, "room.jpg"),
                 "--geo", os.path.join(work, "geo.npz"), "--out", work], "solve camera (MoGe)")
        mode = "moge"
    else:
        # vanishing-line mode with lines projected from the true camera (+0.8 px noise)
        M = np.array(truth["matrix_world"])
        W, H = truth["resolution"]
        f = truth["lens_mm"] / 36.0 * W
        cam = G.Camera(f, f, W / 2, H / 2, W, H, M[:3, :3] @ G.F_CV_TO_BL, M[:3, 3])

        def seg(p, q):
            (u, v), _ = cam.project([p, q])
            return [*u, *v]
        rng = np.random.default_rng(1)
        lines = {"x": [seg([-2.5, 4, 0], [1.8, 4, 0]), seg([-0.4, 4, 0.76], [1.0, 4, 0.76]), seg([-2.5, 4, 2.8], [1.5, 4, 2.8])],
                 "y": [seg([2, 1.5, 0], [2, 3.9, 0]), seg([-3, 0.5, 2.8], [-3, 3.5, 2.8]), seg([1.95, 1, 2.75], [1.95, 3.9, 2.75])],
                 "z": [seg([2, 4, 0.1], [2, 4, 2.7]), seg([-3, 4, 0.1], [-3, 4, 2.7])],
                 "camera_height": 1.45}
        for k in lines:
            if k != "camera_height":
                lines[k] = (np.array(lines[k]) + rng.normal(0, 0.8, (len(lines[k]), 4))).tolist()
        # walls + table plane so the synthetic geometry has the console table
        tl = seg([-0.4, 3.48, 0.78], [1.0, 3.48, 0.78]); tr = seg([1.0, 3.92, 0.78], [-0.4, 3.92, 0.78])
        lines["planes"] = [{"type": "wall", "axis": "y", "floor_pixel": seg([0, 4, 0], [0.1, 4, 0])[:2]},
                           {"type": "horizontal", "height": 0.78, "polygon": [tl[:2], tl[2:], tr[:2], tr[2:]]}]
        os.makedirs(work, exist_ok=True)
        G.save_json(os.path.join(work, "lines.json"), lines)
        run(B + [os.path.join(SCRIPTS, "solve_scene.py"), "--", "--image", os.path.join(out, "room.jpg"),
                 "--lines", os.path.join(work, "lines.json"), "--out", work], "solve camera (vanishing lines)")
        mode = "lines"

    scene = G.load_json(os.path.join(work, "scene.json"))
    job = {"name": "selftest_speaker", "image": os.path.join(out, "room.jpg"), "work_dir": work,
           "output_dir": os.path.join(out, "out"), "product": {"blend": os.path.join(out, "speaker.blend")},
           "placement": {"box": [770, 405, 800, 452], "orient": "room"},
           "lights": [], "render": {"samples": 64, "preview_samples": 32}}
    jp = os.path.join(out, "job_selftest.json")
    G.save_json(jp, job)
    run(B + [os.path.join(SCRIPTS, "build_scene.py"), "--", "--job", jp], "build .blend")
    run(B + [os.path.join(SCRIPTS, "render_outputs.py"), "--", "--blend", os.path.join(out, "out", "selftest_speaker.blend")], "render outputs")

    rep = G.load_json(os.path.join(out, "out", "selftest_speaker_build_report.json"))
    rr = G.load_json(os.path.join(out, "out", "selftest_speaker_render_report.json"))
    checks = []
    fov_err = abs(scene["camera"]["fov_x_deg"] - truth["fov_x_deg"])
    checks.append(("field of view error (deg)", round(fov_err, 2), fov_err < 5))
    h_err = abs(scene["camera_height_m"] - truth["camera_height_m"]) / truth["camera_height_m"]
    checks.append(("camera height error", f"{h_err:.1%}", h_err < 0.12 or mode == "lines"))
    base_z = rep["placement"]["location"][2]
    rel = (base_z / scene["camera_height_m"]) / (truth["table_top_z"] / truth["camera_height_m"])
    checks.append(("product base on table top (scale-free ratio, 1 = exact)", round(rel, 3), abs(rel - 1) < 0.1))
    checks.append(("support surface detected as horizontal", rep["placement"]["surface"]["kind"], rep["placement"]["surface"]["kind"] == "horizontal"))
    outs = rr.get("outputs", {})
    exist = all(os.path.exists(outs.get(k, "")) for k in ("product", "shadow", "product_shadow", "composite"))
    checks.append(("4 outputs + blend written", exist and os.path.exists(rr.get("blend", "")), exist))
    qc = rr.get("qc", {})
    checks.append(("contact shadow present (max density)", qc.get("shadow_max_density"), (qc.get("shadow_max_density") or 0) > 0.3))

    # product saved at the wrong scale (10x) + real dimensions -> must land at true size, in the same spot
    wrong = os.path.join(out, "speaker_wrongscale.blend")
    expr = ("import bpy\nfor o in bpy.context.scene.objects:\n    if o.parent is None:\n"
            "        o.scale = (10, 10, 10); o.location = o.location * 10\n"
            f"bpy.ops.wm.save_as_mainfile(filepath={wrong!r})\n")
    run([blender, "-b", "--factory-startup", os.path.join(out, "speaker.blend"), "--python-expr", expr], "make 10x wrong-scale product")
    job2 = dict(job, name="selftest_rescaled",
                product={"blend": wrong, "dimensions": {"width": 110, "depth": 110, "height": 166, "unit": "mm"}})
    jp2 = os.path.join(out, "job_selftest_rescaled.json")
    G.save_json(jp2, job2)
    run(B + [os.path.join(SCRIPTS, "build_scene.py"), "--", "--job", jp2], "build with real dimensions")
    rep2 = G.load_json(os.path.join(out, "out", "selftest_rescaled_build_report.json"))
    ps = rep2["placement"]["product_scaling"]
    same = np.allclose(rep2["product_box_px"], rep["product_box_px"], atol=1.0)
    checks.append(("10x wrong-scale product rescaled from dimensions (model -> final height, m; same pixels)",
                   f"{ps['model_size_m']['height']} -> {ps['final_size_m']['height']}; {same}",
                   abs(ps["final_size_m"]["height"] - 0.166) < 0.002 and same))
    print("\n================ SELFTEST (" + mode + ") ================")
    ok = True
    for name, val, good in checks:
        ok &= bool(good)
        print(f"{'PASS' if good else 'FAIL'}  {name}: {val}")
    print("QC sheet:", outs.get("qc_sheet"))
    print("SELFTEST", "PASSED" if ok else "FAILED")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
