"""Build the self-test assets: a synthetic interior photo with a KNOWN camera, plus two test products.

    blender -b --factory-startup -P make_test_assets.py -- <out_dir> [--samples 128]

Writes:
    <out_dir>/room.jpg            the "photo" (1280x854)
    <out_dir>/room_truth.json     ground-truth camera (to score the camera solve)
    <out_dir>/room_scene.blend    the room as a Blender scene (to test scene mode)
    <out_dir>/speaker.blend       table-top product, 0.11 m wide, front = -Y, base at z=0
    <out_dir>/switch.blend        wall product, 0.09 m square plate, front = -Y, back at y=0
"""
import json
import math
import os
import sys

import bpy
from mathutils import Matrix, Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT = os.path.abspath(argv[0] if argv else "selftest_out")
SAMPLES = int(argv[argv.index("--samples") + 1]) if "--samples" in argv else 128
os.makedirs(OUT, exist_ok=True)


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    return bpy.context.scene


def mat(name, color, rough=0.5, metal=0.0, spec=0.5, emission=None, strength=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if emission is not None:
        b.inputs["Emission Color"].default_value = (*emission, 1)
        b.inputs["Emission Strength"].default_value = strength
    return m


def box(name, size, loc, material, coll=None):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    o = bpy.context.object
    o.name = name
    o.scale = size
    bpy.ops.object.transform_apply(scale=True)
    o.data.materials.append(material)
    return o


def set_cycles(sc, samples):
    sc.render.engine = "CYCLES"
    sc.cycles.samples = samples
    sc.cycles.use_denoising = True
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for dt in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
            try:
                prefs.compute_device_type = dt
                prefs.get_devices()
                if any(d.type == dt for d in prefs.devices):
                    for d in prefs.devices:
                        d.use = d.type == dt
                    sc.cycles.device = "GPU"
                    break
            except TypeError:
                continue
    except Exception:
        pass


# ---------------------------------------------------------------- room
sc = reset()
set_cycles(sc, SAMPLES)
sc.render.resolution_x, sc.render.resolution_y = 1280, 854
sc.view_settings.view_transform = "AgX" if "AgX" in [i.identifier for i in sc.view_settings.bl_rna.properties["view_transform"].enum_items] else "Filmic"

floor_m = mat("oak floor", (0.32, 0.2, 0.11), 0.45)
wall_m = mat("warm white wall", (0.78, 0.74, 0.68), 0.9)
wall2_m = mat("sage wall", (0.42, 0.5, 0.42), 0.9)
table_m = mat("walnut table", (0.18, 0.1, 0.05), 0.35)
sofa_m = mat("linen sofa", (0.6, 0.58, 0.52), 0.95)
rug_m = mat("rug", (0.55, 0.45, 0.38), 1.0)
lamp_m = mat("lamp shade", (1, 0.9, 0.75), 0.8, emission=(1, 0.75, 0.45), strength=6)

# room: x in [-3, 2], y in [-1, 4], z in [0, 2.8]; camera looks into the +y corner
box("floor", (5, 6, 0.02), (-0.5, 1, -0.01), floor_m)
box("ceiling", (5, 6, 0.02), (-0.5, 1, 2.81), wall_m)
box("back wall", (5, 0.1, 2.8), (-0.5, 4.05, 1.4), wall_m)
box("side wall", (0.1, 6, 2.8), (2.05, 1, 1.4), wall2_m)
# left wall with a window opening (gap between z=0.9..2.3, y=1.2..2.8)
box("left wall a", (0.1, 6, 0.9), (-3.05, 1, 0.45), wall_m)
box("left wall b", (0.1, 6, 0.5), (-3.05, 1, 2.55), wall_m)
box("left wall c", (0.1, 2.2, 1.4), (-3.05, 0.1 - 1.0, 1.6), wall_m)
box("left wall d", (0.1, 1.2, 1.4), (-3.05, 3.4, 1.6), wall_m)
box("rug", (2.2, 1.6, 0.01), (-0.6, 2.4, 0.005), rug_m)
# console table against the back wall
box("table top", (1.4, 0.45, 0.04), (0.3, 3.7, 0.76), table_m)
for dx in (-0.65, 0.65):
    for dy in (-0.18, 0.18):
        box("table leg", (0.04, 0.04, 0.74), (0.3 + dx, 3.7 + dy, 0.37), table_m)
box("sofa base", (2.0, 0.85, 0.42), (-1.4, 3.4, 0.21), sofa_m)
box("sofa back", (2.0, 0.2, 0.45), (-1.4, 3.75, 0.62), sofa_m)
box("lamp shade", (0.3, 0.3, 0.32), (1.6, 3.6, 1.45), lamp_m)
box("lamp stand", (0.03, 0.03, 1.3), (1.6, 3.6, 0.65), table_m)

sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
sc.collection.objects.link(sun)
sun.data.energy = 4.0
sun.data.angle = math.radians(1.5)
sun.data.color = (1.0, 0.93, 0.82)
sun_dir = Vector((-1.0, 0.25, 0.75)).normalized()  # direction TO the sun (through the window)
sun.rotation_euler = (-sun_dir).to_track_quat("-Z", "Y").to_euler()
win = bpy.data.objects.new("window glow", bpy.data.lights.new("window glow", "AREA"))
sc.collection.objects.link(win)
win.data.shape = "RECTANGLE"
win.data.size, win.data.size_y = 1.6, 1.4
win.data.energy = 250
win.data.color = (0.8, 0.88, 1.0)
win.location = (-3.0, 2.0, 1.6)
win.rotation_euler = Vector((1, 0, 0)).to_track_quat("-Z", "Y").to_euler()
world = bpy.data.worlds.new("sky")
sc.world = world
world.use_nodes = True
bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
bg.inputs[0].default_value = (0.55, 0.7, 1.0, 1)
bg.inputs[1].default_value = 0.6

cam_data = bpy.data.cameras.new("cam")
cam_data.lens = 26.0
cam_data.sensor_width = 36.0
cam_data.sensor_fit = "HORIZONTAL"
cam = bpy.data.objects.new("Camera", cam_data)
sc.collection.objects.link(cam)
cam.location = (1.2, -0.6, 1.45)
target = Vector((-0.4, 3.6, 0.85))
cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
sc.camera = cam

bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "room_scene.blend"))
sc.render.image_settings.file_format = "JPEG"
sc.render.image_settings.quality = 92
sc.render.filepath = os.path.join(OUT, "room.jpg")
bpy.ops.render.render(write_still=True)

truth = {
    "lens_mm": cam_data.lens, "sensor_width_mm": 36.0, "resolution": [1280, 854],
    "fov_x_deg": math.degrees(2 * math.atan(18 / cam_data.lens)),
    "location": list(cam.location), "matrix_world": [list(r) for r in cam.matrix_world],
    "camera_height_m": cam.location.z,
    "notes": "floor at z=0, back wall face at y=4.0, table top at z=0.78, table centre x=0.3",
    "table_top_z": 0.78, "table_center": [0.3, 3.7, 0.78], "back_wall_y": 4.0,
}
json.dump(truth, open(os.path.join(OUT, "room_truth.json"), "w"), indent=2)

# ---------------------------------------------------------------- speaker product
sc = reset()
fabric = mat("speaker fabric", (0.12, 0.12, 0.13), 0.95)
top = mat("speaker top", (0.02, 0.02, 0.02), 0.15)
ring = mat("light ring", (0.9, 0.9, 0.9), 0.3, emission=(0.4, 0.75, 1.0), strength=0.0)
bpy.ops.mesh.primitive_cylinder_add(vertices=96, radius=0.055, depth=0.16, location=(0, 0, 0.08))
body = bpy.context.object
body.name = "speaker body"
body.data.materials.append(fabric)
bpy.ops.object.shade_smooth()
bev = body.modifiers.new("bevel", "BEVEL")
bev.width = 0.006
bev.segments = 4
bpy.ops.mesh.primitive_cylinder_add(vertices=96, radius=0.053, depth=0.006, location=(0, 0, 0.163))
cap = bpy.context.object
cap.name = "speaker top"
cap.data.materials.append(top)
cap.parent = body
cap.matrix_parent_inverse = body.matrix_world.inverted()
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, -0.0552, 0.03))
logo = bpy.context.object
logo.name = "speaker logo"
logo.scale = (0.025, 0.002, 0.006)
logo.data.materials.append(ring)
logo.parent = body
logo.matrix_parent_inverse = body.matrix_world.inverted()
bpy.ops.object.select_all(action="DESELECT")
coll = bpy.data.collections.new("PRODUCT")
sc.collection.children.link(coll)
for o in (body, cap, logo):
    for c in o.users_collection:
        c.objects.unlink(o)
    coll.objects.link(o)
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "speaker.blend"))

# ---------------------------------------------------------------- wall switch product
sc = reset()
plate = mat("switch plate", (0.85, 0.85, 0.83), 0.25)
keys = mat("switch keys", (0.9, 0.9, 0.88), 0.3)
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, -0.005, 0))
p = bpy.context.object
p.name = "switch plate"
p.scale = (0.09, 0.01, 0.09)
bpy.ops.object.transform_apply(scale=True)
bv = p.modifiers.new("bevel", "BEVEL")
bv.width = 0.002
bv.segments = 3
p.data.materials.append(plate)
for i, x in enumerate((-0.021, 0.021)):
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, -0.0115, 0))
    k = bpy.context.object
    k.name = f"switch key {i}"
    k.scale = (0.036, 0.004, 0.07)
    bpy.ops.object.transform_apply(scale=True)
    k.data.materials.append(keys)
    k.parent = p
    k.matrix_parent_inverse = p.matrix_world.inverted()
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "switch.blend"))
print("SELFTEST_ASSETS_OK", OUT)
