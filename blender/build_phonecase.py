"""Build the PhoneCaseEdit hero GLB and four QA renders in headless Blender.

The source phone remains untouched.  The imported model is normalised to real
world dimensions and placed inside script-generated vinyl and clear-case parts.
This script intentionally uses only Blender's bundled Python modules.
"""

import argparse
import json
import math
import os
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector


BODY_W = 0.0780
BODY_H = 0.1634
BODY_D = 0.00875
CASE_W = 0.0820
CASE_H = 0.1674
CASE_D = 0.0132
# After source X(depth) -> runtime Y(depth), the inspected +X rear surface is +Y.
BACK_Y = CASE_D / 2
FRONT_Y = -CASE_D / 2


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--qa-dir", required=True)
    p.add_argument("--report", required=True)
    return p.parse_args(argv)


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablocks in (bpy.data.materials, bpy.data.curves, bpy.data.meshes):
        for block in list(datablocks):
            if block.users == 0:
                datablocks.remove(block)


def collection(name):
    c = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(c)
    return c


def move_to(obj, target):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    target.objects.link(obj)


def set_socket(bsdf, names, value):
    for name in names:
        s = bsdf.inputs.get(name)
        if s is not None:
            s.default_value = value
            return True
    return False


def material(name, color, metallic=0.0, roughness=0.35, transmission=0.0, alpha=1.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    set_socket(bsdf, ["Base Color"], color)
    set_socket(bsdf, ["Metallic"], metallic)
    set_socket(bsdf, ["Roughness"], roughness)
    set_socket(bsdf, ["IOR"], 1.47)
    set_socket(bsdf, ["Transmission Weight", "Transmission"], transmission)
    set_socket(bsdf, ["Coat Weight", "Clearcoat"], 1.0 if transmission else 0.15)
    set_socket(bsdf, ["Coat Roughness", "Clearcoat Roughness"], 0.05)
    set_socket(bsdf, ["Alpha"], alpha)
    if transmission:
        if hasattr(m, "surface_render_method"):
            m.surface_render_method = "DITHERED"
        elif hasattr(m, "blend_method"):
            m.blend_method = "BLEND"
        if hasattr(m, "use_screen_refraction"):
            m.use_screen_refraction = True
        m.diffuse_color = (*color[:3], alpha)
    return m


def rounded_box(name, size, location, radius, mat=None, segments=4, coll=None):
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    bevel = obj.modifiers.new("production_bevel", "BEVEL")
    bevel.width = radius
    bevel.segments = segments
    bevel.limit_method = "ANGLE"
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=bevel.name)
    for p in obj.data.polygons:
        p.use_smooth = True
    if mat:
        obj.data.materials.append(mat)
    if coll:
        move_to(obj, coll)
    return obj


def cylinder(name, radius, depth, location, mat=None, vertices=32, coll=None):
    # Default cylinder axis is Z; rotate it so it pierces the phone along Y.
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth,
                                        location=location, rotation=(math.pi / 2, 0, 0))
    obj = bpy.context.object
    obj.name = name
    if mat:
        obj.data.materials.append(mat)
    if coll:
        move_to(obj, coll)
    return obj


def boolean_difference(target, cutter):
    mod = target.modifiers.new("precision_cut", "BOOLEAN")
    mod.operation = "DIFFERENCE"
    mod.solver = "EXACT"
    mod.object = cutter
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.data.objects.remove(cutter, do_unlink=True)


def bbox_world(objects):
    points = [obj.matrix_world @ Vector(corner) for obj in objects if obj.type == "MESH" for corner in obj.bound_box]
    mins = Vector((min(p.x for p in points), min(p.y for p in points), min(p.z for p in points)))
    maxs = Vector((max(p.x for p in points), max(p.y for p in points), max(p.z for p in points)))
    return mins, maxs


def import_and_normalise_phone(path, root, coll):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    imported = [o for o in bpy.data.objects if o not in before]
    imported_meshes = [o for o in imported if o.type == "MESH"]
    if not imported_meshes:
        raise RuntimeError("The source GLB contains no mesh objects")

    # Source axes from inspection: X depth, Y width, Z height. Rotate so the
    # runtime/export convention is X width, Y depth, Z height.
    phone = bpy.data.objects.new("phone_body", None)
    coll.objects.link(phone)
    phone.parent = root
    phone.rotation_euler[2] = math.pi / 2
    for obj in imported:
        if obj.parent is None:
            obj.parent = phone
        move_to(obj, coll)

    bpy.context.view_layer.update()
    mins, maxs = bbox_world(imported_meshes)
    height = maxs.z - mins.z
    phone.scale = (BODY_H / height,) * 3
    bpy.context.view_layer.update()
    mins, maxs = bbox_world(imported_meshes)
    centre = (mins + maxs) / 2
    phone.location -= centre
    bpy.context.view_layer.update()

    # Centre depth and keep the phone inside the clear case.
    mins, maxs = bbox_world(imported_meshes)
    phone.location.y -= (mins.y + maxs.y) / 2
    for obj in imported_meshes:
        obj.name = "phone_part_" + obj.name
        obj.data.name = obj.name + "_mesh"
    return phone, imported_meshes


def make_vinyl(root, coll, mat):
    # A real 0.32 mm slab, sitting between the phone and rear shell.
    vinyl = rounded_box(
        "vinyl_back", (BODY_W - 0.0022, 0.00032, BODY_H - 0.0026),
        (0, BODY_D / 2 + 0.00022, 0), 0.0025, mat, 6, coll
    )
    vinyl.parent = root

    # Three camera lenses plus flash and LiDAR; approximate centres match the
    # inspected source and can be tuned from QA renders without hand modelling.
    holes = [
        (-0.0230, 0.0570, 0.0089),
        (-0.0230, 0.0375, 0.0089),
        (-0.0060, 0.0472, 0.0089),
        (-0.0065, 0.0648, 0.0034),
        (-0.0060, 0.0310, 0.0028),
    ]
    for x, z, r in holes:
        cut = cylinder("vinyl_cut", r, 0.01, (x, vinyl.location.y, z), vertices=32)
        boolean_difference(vinyl, cut)

    # Deterministic planar UV0 for dynamic CanvasTexture use.
    uv = vinyl.data.uv_layers.get("UVMap") or vinyl.data.uv_layers.new(name="UVMap")
    half_w = (BODY_W - 0.0022) / 2
    half_h = (BODY_H - 0.0026) / 2
    for poly in vinyl.data.polygons:
        for li in poly.loop_indices:
            co = vinyl.data.vertices[vinyl.data.loops[li].vertex_index].co
            uv.data[li].uv = ((co.x + half_w) / (2 * half_w), (co.z + half_h) / (2 * half_h))
    return vinyl, holes


def make_case(root, coll, clear_mat, accent_mat, holes):
    parts = []
    rail = 0.00165
    corner = 0.0045

    # Solid transparent rear shell: not a plane and not an empty box.
    back = rounded_box("case_clear_back", (CASE_W, 0.00125, CASE_H),
                       (0, BACK_Y + 0.000625, 0), corner, clear_mat, 6, coll)
    for x, z, r in holes:
        cut = cylinder("case_camera_cut", r + 0.00065, 0.02, (x, BACK_Y, z), vertices=32)
        boolean_difference(back, cut)
    parts.append(back)

    # Four protective rails and a raised front lip.
    parts += [
        rounded_box("case_left_rail", (rail, CASE_D, CASE_H - 0.006),
                    (-CASE_W / 2 + rail / 2, 0, 0), 0.00075, clear_mat, 5, coll),
        rounded_box("case_right_rail", (rail, CASE_D, CASE_H - 0.006),
                    (CASE_W / 2 - rail / 2, 0, 0), 0.00075, clear_mat, 5, coll),
        rounded_box("case_top_rail", (CASE_W - 0.006, CASE_D, rail),
                    (0, 0, CASE_H / 2 - rail / 2), 0.00075, clear_mat, 5, coll),
        rounded_box("case_bottom_left", (0.027, CASE_D, rail),
                    (-0.026, 0, -CASE_H / 2 + rail / 2), 0.00075, clear_mat, 5, coll),
        rounded_box("case_bottom_right", (0.027, CASE_D, rail),
                    (0.026, 0, -CASE_H / 2 + rail / 2), 0.00075, clear_mat, 5, coll),
    ]
    lip_y = FRONT_Y - 0.00035
    parts += [
        rounded_box("case_front_lip_left", (0.0014, 0.0013, CASE_H - 0.005),
                    (-CASE_W / 2 + 0.0007, lip_y, 0), 0.00055, clear_mat, 4, coll),
        rounded_box("case_front_lip_right", (0.0014, 0.0013, CASE_H - 0.005),
                    (CASE_W / 2 - 0.0007, lip_y, 0), 0.00055, clear_mat, 4, coll),
        rounded_box("case_front_lip_top", (CASE_W - 0.005, 0.0013, 0.0014),
                    (0, lip_y, CASE_H / 2 - 0.0007), 0.00055, clear_mat, 4, coll),
        rounded_box("case_front_lip_bottom", (CASE_W - 0.005, 0.0013, 0.0014),
                    (0, lip_y, -CASE_H / 2 + 0.0007), 0.00055, clear_mat, 4, coll),
    ]

    # Separate tactile covers. Bottom gap is the USB-C/speaker opening.
    parts += [
        rounded_box("case_action_button", (0.0011, 0.0055, 0.010),
                    (-CASE_W / 2 - 0.00035, 0.0005, 0.044), 0.00055, accent_mat, 4, coll),
        rounded_box("case_volume_button", (0.0011, 0.0055, 0.024),
                    (-CASE_W / 2 - 0.00035, 0.0005, 0.016), 0.00055, accent_mat, 4, coll),
        rounded_box("case_power_button", (0.0011, 0.0055, 0.027),
                    (CASE_W / 2 + 0.00035, 0.0005, 0.026), 0.00055, accent_mat, 4, coll),
    ]

    # Raised camera protector around the complete camera field.
    bumper = rounded_box("case_camera_guard", (0.0435, 0.0020, 0.0505),
                          (-0.0145, BACK_Y - 0.00055, 0.048), 0.0060, clear_mat, 8, coll)
    for x, z, r in holes:
        cut = cylinder("guard_cut", r + 0.00115, 0.02, (x, bumper.location.y, z), vertices=32)
        boolean_difference(bumper, cut)
    parts.append(bumper)

    case_root = bpy.data.objects.new("case_clear", None)
    coll.objects.link(case_root)
    case_root.parent = root
    for part in parts:
        part.parent = case_root
    return case_root, parts


def add_qa_scene(root, qa_coll):
    floor_mat = material("qa_floor", (0.035, 0.025, 0.022, 1), roughness=0.42)
    floor = rounded_box("QA_floor", (0.55, 0.012, 0.55), (0, 0.12, -0.105), 0.01, floor_mat, 4, qa_coll)
    floor.hide_render = False

    world = bpy.context.scene.world or bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.025, 0.032, 0.045, 1)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.05

    def area(name, loc, energy, size, color):
        data = bpy.data.lights.new(name, "AREA")
        data.energy, data.shape, data.size, data.color = energy, "DISK", size, color
        obj = bpy.data.objects.new(name, data)
        qa_coll.objects.link(obj)
        obj.location = loc
        direction = Vector((0, 0, 0.015)) - obj.location
        obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()

    # Small, off-axis emitters reveal transparent edges without filling the
    # rear shell with a camera-facing white reflection.
    area("QA_key", (-0.16, -0.20, 0.22), 45, 0.070, (1.0, 0.80, 0.65))
    area("QA_rim", (0.18, 0.18, 0.18), 35, 0.050, (0.35, 0.58, 1.0))
    area("QA_fill", (-0.18, 0.12, -0.02), 15, 0.060, (0.75, 0.88, 1.0))

    cam_data = bpy.data.cameras.new("QA_camera")
    cam = bpy.data.objects.new("QA_camera", cam_data)
    qa_coll.objects.link(cam)
    cam.data.lens = 62
    bpy.context.scene.camera = cam
    return cam, floor


def point_camera(cam, location, target=(0, 0, 0)):
    cam.location = location
    cam.rotation_euler = (Vector(target) - cam.location).to_track_quat("-Z", "Y").to_euler()


def mesh_stats(objects):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    tris = verts = 0
    for obj in objects:
        if obj.type != "MESH":
            continue
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        mesh.calc_loop_triangles()
        tris += len(mesh.loop_triangles)
        verts += len(mesh.vertices)
        evaluated.to_mesh_clear()
    return verts, tris


def main():
    args = parse_args()
    out = Path(args.output)
    qa_dir = Path(args.qa_dir)
    report_path = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    qa_dir.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    clear_scene()
    asset_coll = collection("PCE_ASSET")
    qa_coll = collection("PCE_QA")
    root = bpy.data.objects.new("PCE_Hero_Root", None)
    asset_coll.objects.link(root)

    clear = material("PCE_Clear_TPU", (0.92, 0.97, 1.0, 1), roughness=0.075, transmission=0.96, alpha=0.30)
    edge = material("PCE_Clear_Button", (0.80, 0.91, 1.0, 1), roughness=0.12, transmission=0.82, alpha=0.42)
    vinyl_mat = material("PCE_Vinyl_QA_Blue", (0.14, 0.42, 0.82, 1), roughness=0.31)

    phone, phone_meshes = import_and_normalise_phone(Path(args.input), root, asset_coll)
    vinyl, holes = make_vinyl(root, asset_coll, vinyl_mat)
    case, case_parts = make_case(root, asset_coll, clear, edge, holes)
    bpy.context.view_layer.update()

    # Export only the product hierarchy, excluding QA lights/camera/floor.
    bpy.ops.object.select_all(action="DESELECT")
    export_objects = [root, phone, vinyl, case] + phone_meshes + case_parts
    for obj in export_objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = root
    bpy.ops.export_scene.gltf(
        filepath=str(out), export_format="GLB", use_selection=True,
        export_apply=True, export_yup=True, export_materials="EXPORT",
        export_cameras=False, export_lights=False,
    )

    # Eevee 4.0 cannot reliably show scene objects behind a transmissive shell
    # on a headless software renderer. The GLB above already contains physical
    # KHR_materials_transmission; QA renders switch only the in-memory preview
    # to alpha so placement and cut-outs remain visually inspectable.
    for qa_material, qa_alpha in ((clear, 0.16), (edge, 0.24)):
        qa_bsdf = qa_material.node_tree.nodes.get("Principled BSDF")
        set_socket(qa_bsdf, ["Transmission Weight", "Transmission"], 0.0)
        set_socket(qa_bsdf, ["Alpha"], qa_alpha)
        if hasattr(qa_material, "blend_method"):
            qa_material.blend_method = "BLEND"

    cam, floor = add_qa_scene(root, qa_coll)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT" if bpy.app.version >= (4, 2, 0) else "BLENDER_EEVEE"
    scene.render.resolution_x = 900
    scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    try:
        scene.view_settings.look = "AgX - Medium High Contrast"
    except TypeError:
        pass

    views = {
        "01_rear.png": (0.15, 0.30, 0.09),
        "02_rear_close.png": (-0.10, 0.255, 0.10),
        "03_front.png": (0.14, -0.31, 0.065),
        "04_side.png": (0.30, 0.09, 0.055),
    }
    for filename, pos in views.items():
        point_camera(cam, pos, (0, 0, 0.006))
        scene.render.filepath = str(qa_dir / filename)
        bpy.ops.render.render(write_still=True)

    verts, tris = mesh_stats(phone_meshes + [vinyl] + case_parts)
    report = {
        "generator": "PhoneCaseEdit scripted Blender pipeline",
        "source": Path(args.input).name,
        "output": out.name,
        "dimensions_m": {"phone_width": BODY_W, "phone_height": BODY_H, "phone_depth": BODY_D},
        "required_nodes": {"PCE_Hero_Root": True, "phone_body": True, "vinyl_back": True, "case_clear": True},
        "vinyl": {"thickness_m": 0.00032, "uv0": bool(vinyl.data.uv_layers)},
        "case": {"solid_back": True, "front_lip": True, "button_covers": 3, "bottom_port_opening": True, "camera_holes": len(holes)},
        "vertices": verts,
        "triangles": tris,
        "triangle_budget": 50000,
        "triangle_budget_pass": tris < 50000,
        "output_bytes": out.stat().st_size,
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if tris >= 50000:
        raise RuntimeError(f"Triangle budget exceeded: {tris}")


if __name__ == "__main__":
    main()
