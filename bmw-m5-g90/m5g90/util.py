"""Small bpy helpers shared by all modules."""
import math

import bpy
import bmesh
import numpy as np
from mathutils import Vector


def reset_scene():
    """Empty the current file (objects, meshes, materials, ...)."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    return scene


def get_collection(name, parent=None):
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
        (parent or bpy.context.scene.collection).children.link(coll)
    return coll


def link(obj, collection=None):
    coll = collection or bpy.context.scene.collection
    if obj.name not in coll.objects:
        coll.objects.link(obj)
    return obj


def new_mesh_object(name, verts, faces, collection=None, smooth=True, edges=()):
    """Create a mesh object from numpy/py lists. faces may mix tris/quads/ngons."""
    mesh = bpy.data.meshes.new(name)
    verts = np.asarray(verts, dtype=np.float64).reshape(-1, 3)
    mesh.from_pydata(verts.tolist(), list(edges), [list(map(int, f)) for f in faces])
    mesh.update()
    if smooth and len(mesh.polygons):
        mesh.polygons.foreach_set("use_smooth", [True] * len(mesh.polygons))
    obj = bpy.data.objects.new(name, mesh)
    link(obj, collection)
    return obj


def grid_object(name, P, collection=None, close_u=False, close_v=False, smooth=True, flip=False):
    """Mesh from a structured grid of points P[nu, nv, 3] (fast, numpy based)."""
    P = np.asarray(P, dtype=np.float64)
    nu, nv = P.shape[:2]
    iu = np.arange(nu if close_u else nu - 1)
    iv = np.arange(nv if close_v else nv - 1)
    I, J = np.meshgrid(iu, iv, indexing="ij")
    I1 = (I + 1) % nu
    J1 = (J + 1) % nv
    quads = np.stack([I * nv + J, I1 * nv + J, I1 * nv + J1, I * nv + J1], axis=-1).reshape(-1, 4)
    if flip:
        quads = quads[:, ::-1]
    return mesh_from_arrays(name, P.reshape(-1, 3), quads, collection, smooth)


def mesh_from_arrays(name, verts, polys, collection=None, smooth=True):
    """Fast mesh creation from a (N,3) vertex array and a (M,k) index array (k = 3 or 4)."""
    verts = np.ascontiguousarray(verts, dtype=np.float32).reshape(-1, 3)
    polys = np.ascontiguousarray(polys, dtype=np.int32)
    n, k = polys.shape
    mesh = bpy.data.meshes.new(name)
    mesh.vertices.add(len(verts))
    mesh.vertices.foreach_set("co", verts.ravel())
    mesh.loops.add(n * k)
    mesh.loops.foreach_set("vertex_index", polys.ravel())
    mesh.polygons.add(n)
    mesh.polygons.foreach_set("loop_start", np.arange(0, n * k, k, dtype=np.int32))
    mesh.polygons.foreach_set("loop_total", np.full(n, k, dtype=np.int32))
    mesh.update(calc_edges=True)
    mesh.validate()
    if smooth:
        mesh.polygons.foreach_set("use_smooth", np.ones(n, dtype=bool))
    obj = bpy.data.objects.new(name, mesh)
    link(obj, collection)
    return obj


def set_active(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def apply_modifiers(obj):
    """Apply the whole modifier stack of a mesh object."""
    set_active(obj)
    for mod in list(obj.modifiers):
        bpy.ops.object.modifier_apply(modifier=mod.name)
    return obj


def join(objs, name=None):
    objs = [o for o in objs if o is not None]
    if not objs:
        return None
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    if len(objs) > 1:
        bpy.ops.object.join()
    out = bpy.context.view_layer.objects.active
    if name:
        out.name = name
        out.data.name = name
    return out


def shade_smooth(obj, angle_deg=None):
    """Smooth shade; with angle_deg mark edges sharper than that as sharp."""
    mesh = obj.data
    mesh.polygons.foreach_set("use_smooth", [True] * len(mesh.polygons))
    if angle_deg is not None:
        bm = bmesh.new()
        bm.from_mesh(mesh)
        lim = math.radians(angle_deg)
        for e in bm.edges:
            if len(e.link_faces) == 2:
                e.smooth = e.calc_face_angle(0.0) < lim
        bm.to_mesh(mesh)
        bm.free()
    mesh.update()
    return obj


def add_material(obj, mat):
    if mat.name not in obj.data.materials:
        obj.data.materials.append(mat)
    return list(obj.data.materials).index(mat)


def parent_keep(child, parent):
    child.parent = parent
    child.matrix_parent_inverse = parent.matrix_world.inverted()


def mirror_y_copy(obj, name=None, collection=None):
    """Return a mirrored (across the XZ plane) real copy of a mesh object."""
    new = obj.copy()
    new.data = obj.data.copy()
    new.name = name or obj.name + ".R"
    link(new, collection or obj.users_collection[0])
    v = np.empty(len(new.data.vertices) * 3, dtype=np.float32)
    new.data.vertices.foreach_get("co", v)
    v = v.reshape(-1, 3)
    v[:, 1] *= -1
    new.data.vertices.foreach_set("co", v.ravel())
    new.data.flip_normals()
    new.data.update()
    return new


# ---------------------------------------------------------------------------
# quick preview rendering (used while developing individual parts)
# ---------------------------------------------------------------------------
def look_at(obj, target):
    d = Vector(target) - obj.location
    obj.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def setup_cycles(samples=32, res=(1280, 800), denoise=True):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = denoise
    scene.cycles.use_adaptive_sampling = True
    scene.render.resolution_x, scene.render.resolution_y = res
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.threads_mode = "AUTO"
    return scene


def preview_light_rig(strength=1.0, world=0.25):
    """Neutral studio: grey world + large soft boxes. Idempotent."""
    scene = bpy.context.scene
    if scene.world is None:
        scene.world = bpy.data.worlds.new("PreviewWorld")
    w = scene.world
    w.use_nodes = True
    bg = w.node_tree.nodes.get("Background")
    if bg:
        bg.inputs[0].default_value = (world, world, world, 1)
        bg.inputs[1].default_value = 1.0
    if "PV_Key" in bpy.data.objects:
        return
    coll = get_collection("PreviewRig")
    for name, loc, size, power in (
        ("PV_Key", (3.5, 5.0, 5.0), 6.0, 1800),
        ("PV_Fill", (-5.0, -4.0, 3.5), 6.0, 700),
        ("PV_Top", (0.0, 0.0, 6.0), 8.0, 900),
    ):
        ld = bpy.data.lights.new(name, "AREA")
        ld.size = size
        ld.energy = power * strength
        lo = bpy.data.objects.new(name, ld)
        lo.location = loc
        coll.objects.link(lo)
        look_at(lo, (0, 0, 0.5))
    if "PV_Floor" not in bpy.data.objects:
        bpy.ops.mesh.primitive_plane_add(size=60, location=(0, 0, 0))
        fl = bpy.context.active_object
        fl.name = "PV_Floor"
        m = bpy.data.materials.new("PV_FloorMat")
        m.use_nodes = True
        b = m.node_tree.nodes["Principled BSDF"]
        b.inputs["Base Color"].default_value = (0.35, 0.35, 0.36, 1)
        b.inputs["Roughness"].default_value = 0.6
        fl.data.materials.append(m)
        for c in fl.users_collection:
            c.objects.unlink(fl)
        coll.objects.link(fl)


def preview_render(path, cam_loc, target=(0, 0, 0.6), lens=50, res=(1280, 800), samples=32,
                   ortho_scale=None, rig=True):
    """Render the current scene from cam_loc looking at target and save a PNG."""
    scene = setup_cycles(samples, res)
    if rig:
        preview_light_rig()
    cam = bpy.data.objects.get("PV_Cam")
    if cam is None:
        cam = bpy.data.objects.new("PV_Cam", bpy.data.cameras.new("PV_Cam"))
        get_collection("PreviewRig").objects.link(cam)
    cam.location = cam_loc
    look_at(cam, target)
    if ortho_scale:
        cam.data.type = "ORTHO"
        cam.data.ortho_scale = ortho_scale
    else:
        cam.data.type = "PERSP"
        cam.data.lens = lens
    cam.data.clip_start = 0.05
    cam.data.clip_end = 500
    scene.camera = cam
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return path
