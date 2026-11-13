"""Presentation scene for the BMW M5 (G90) model.

* ``build_studio``  – dark board-formed concrete garage (floor, movable back wall, ceiling),
                      car-centric soft boxes, floor pool and wall-wash spots, daylight variant.
* ``build_cameras`` – nine cameras ``CAM_01`` … ``CAM_09`` matched to the nine reference views.
* ``setup_render`` / ``apply_view`` / ``render_view`` / ``render_all`` – render pipeline.
* ``contact_sheet`` / ``side_by_side`` / ``compare_view`` – PIL sheet composers.

The car is expected in a collection called ``M5_G90`` (car axes: +X forward, +Y left, +Z up,
origin on the ground, mid-wheelbase).  Run ``python3 -m m5g90.scene`` for a self test with a
placeholder car.
"""
import math
import os
import time

import bpy
from mathutils import Vector

from . import util

CAR_COLLECTION = "M5_G90"
STUDIO_COLLECTION = "Studio"
CAMERA_COLLECTION = "Cameras"
ASPECT = (3, 2)
SENSOR = 36.0
CEILING_Z = 4.8
REF_TILE = (1888, 1260)

# ---------------------------------------------------------------------------
# The nine views.  loc / rot (XYZ euler, degrees) / lens (mm, 36 mm sensor) were solved from
# landmarks measured in the 1888x1260 reference tiles (wheel-rim ellipses, tyre contact points,
# number plates, roof line).  ``wall`` = distance of the back wall behind the car origin along
# the horizontal viewing direction (None = no wall), ``env`` = 'studio' | 'daylight',
# ``exposure`` = extra stops, ``lights`` = optional {light name: energy multiplier} overrides.
# ---------------------------------------------------------------------------
VIEWS = {
    1: dict(label="Спереди слева · 3/4", loc=(3.947, 3.506, 0.648), rot=(92.56, 0.0, 138.22),
            lens=25.1, wall=8.5, env="studio", exposure=0.0, lights={"STUDIO_Strip_R": 0.15}),
    2: dict(label="Спереди", loc=(6.948, 0.0, 0.670), rot=(89.74, 0.0, 90.08),
            lens=57.5, wall=9.0, env="studio", exposure=0.0,
            lights={"STUDIO_WallWash": 0.55, "STUDIO_Strip_F": 0.25}),
    3: dict(label="Спереди справа · 3/4", loc=(6.546, -5.441, 0.573), rot=(96.53, 0.0, 48.13),
            lens=44.3, wall=None, env="daylight", exposure=0.0),
    4: dict(label="Левый профиль", loc=(0.889, 17.011, 0.948), rot=(89.06, 0.0, 176.83),
            lens=79.1, wall=18.0, env="studio", exposure=0.0),
    5: dict(label="Сверху", loc=(3.690, 0.507, 4.353), rot=(-2.35, 31.13, -1.15),
            lens=21.8, wall=None, env="studio", exposure=0.0,
            lights={"STUDIO_Top": 0.3, "STUDIO_Pool": 0.8, "STUDIO_Cabin": 1.0}),
    6: dict(label="Правый профиль", loc=(0.916, -35.093, 1.213), rot=(91.22, 0.0, 1.00),
            lens=130.5, wall=None, env="daylight", exposure=0.0),
    7: dict(label="Сзади слева · 3/4", loc=(-9.091, 4.338, 0.863), rot=(90.84, 0.0, -116.19),
            lens=51.7, wall=13.5, env="studio", exposure=0.0, lights={"STUDIO_Strip_R": 0.15}),
    8: dict(label="Сзади", loc=(-10.25, 0.0, 0.700), rot=(90.72, 0.0, -89.97),
            lens=85.0, wall=16.0, env="studio", exposure=0.0, lights={"STUDIO_WallWash": 0.7}),
    9: dict(label="Сзади справа · 3/4", loc=(-7.812, -7.052, 1.110), rot=(89.67, 0.0, -45.66),
            lens=54.2, wall=None, env="daylight", exposure=0.0),
}

QUALITY = {
    #          resolution      spp  adaptive-threshold
    "tiny": ((480, 320), 12, 0.1),          # layout / framing checks only
    "draft": ((960, 640), 24, 0.05),
    "preview": ((1920, 1280), 64, 0.03),
    "final": ((2880, 1920), 300, 0.008),
}


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _coll(name):
    return util.get_collection(name)


def _move_to(obj, coll):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    coll.objects.link(obj)
    return obj


def _nodes(mat):
    return mat.node_tree.nodes, mat.node_tree.links


def _new_mat(name):
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat, False
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    return mat, True


def _ramp(nodes, stops):
    """ColorRamp from [(pos, grey or rgb), ...]."""
    n = nodes.new("ShaderNodeValToRGB")
    el = n.color_ramp.elements
    while len(el) < len(stops):
        el.new(0.5)
    for e, (pos, col) in zip(el, stops):
        e.position = pos
        if not isinstance(col, (tuple, list)):
            col = (col, col, col)
        e.color = (*col[:3], 1.0)
    return n


def _noise(nodes, links, vec, scale, detail=6.0, rough=0.55, distortion=0.0):
    n = nodes.new("ShaderNodeTexNoise")
    n.inputs["Scale"].default_value = scale
    n.inputs["Detail"].default_value = detail
    n.inputs["Roughness"].default_value = rough
    n.inputs["Distortion"].default_value = distortion
    links.new(vec, n.inputs["Vector"])
    return n


def _math(nodes, links, op, a, b=None, clamp=False):
    n = nodes.new("ShaderNodeMath")
    n.operation = op
    n.use_clamp = clamp
    for sock, v in ((n.inputs[0], a), (n.inputs[1], b)):
        if v is None:
            continue
        if isinstance(v, (int, float)):
            sock.default_value = v
        else:
            links.new(v, sock)
    return n.outputs[0]


def _mix_rgb(nodes, links, blend, fac, a, b):
    n = nodes.new("ShaderNodeMix")
    n.data_type = "RGBA"
    n.blend_type = blend
    for sock, v in ((n.inputs["Factor"], fac), (n.inputs["A"], a), (n.inputs["B"], b)):
        if isinstance(v, (int, float)):
            sock.default_value = v
        elif isinstance(v, (tuple, list)):
            sock.default_value = (*v[:3], 1.0)
        else:
            links.new(v, sock)
    return n.outputs["Result"]


# ---------------------------------------------------------------------------
# procedural materials
# ---------------------------------------------------------------------------
def floor_material():
    """Patchy, partly polished concrete floor (object coordinates in metres)."""
    mat, fresh = _new_mat("Studio_Concrete_Floor")
    if not fresh:
        return mat
    nodes, links = _nodes(mat)
    bsdf = nodes["Principled BSDF"]
    tc = nodes.new("ShaderNodeTexCoord")
    vec = tc.outputs["Object"]

    big = _noise(nodes, links, vec, 0.22, 2.0, 0.62, 0.6)        # metre-scale patches
    mid = _noise(nodes, links, vec, 1.7, 3.0, 0.65, 0.3)         # trowel marks / stains
    fine = _noise(nodes, links, vec, 38.0, 2.0, 0.7)             # grain
    speck = nodes.new("ShaderNodeTexVoronoi")                     # aggregate specks
    speck.inputs["Scale"].default_value = 160.0
    links.new(vec, speck.inputs["Vector"])

    patch = _mix_rgb(nodes, links, "MIX", 0.45, big.outputs["Fac"], mid.outputs["Fac"])
    col = _ramp(nodes, [(0.28, 0.075), (0.48, 0.12), (0.62, 0.17), (0.80, 0.24)])
    links.new(patch, col.inputs["Fac"])
    sp = _ramp(nodes, [(0.0, 0.55), (0.10, 1.0)])
    links.new(speck.outputs["Distance"], sp.inputs["Fac"])
    c2 = _mix_rgb(nodes, links, "MULTIPLY", 0.6, col.outputs["Color"], sp.outputs["Color"])
    tint = _mix_rgb(nodes, links, "MULTIPLY", 1.0, c2, (1.0, 0.985, 0.96))
    links.new(tint, bsdf.inputs["Base Color"])

    rough = _ramp(nodes, [(0.30, 0.86), (0.52, 0.66), (0.72, 0.44)])   # worn patches are glossier
    links.new(mid.outputs["Fac"], rough.inputs["Fac"])
    links.new(rough.outputs["Color"], bsdf.inputs["Roughness"])
    bsdf.inputs["Specular IOR Level"].default_value = 0.35

    h = fine.outputs["Fac"]                                          # bump: grain only (cheap)
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.3
    bump.inputs["Distance"].default_value = 0.004
    links.new(h, bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def ground_material():
    """Dark coarse asphalt / volcanic gravel used by the daylight views."""
    mat, fresh = _new_mat("Studio_Asphalt")
    if not fresh:
        return mat
    nodes, links = _nodes(mat)
    bsdf = nodes["Principled BSDF"]
    tc = nodes.new("ShaderNodeTexCoord")
    vec = tc.outputs["Object"]
    big = _noise(nodes, links, vec, 0.15, 3.0, 0.6, 0.4)
    grit = nodes.new("ShaderNodeTexVoronoi")
    grit.inputs["Scale"].default_value = 55.0
    links.new(vec, grit.inputs["Vector"])
    fine = _noise(nodes, links, vec, 140.0, 2.0, 0.7)
    col = _ramp(nodes, [(0.3, 0.020), (0.7, 0.045)])
    links.new(big.outputs["Fac"], col.inputs["Fac"])
    stones = _ramp(nodes, [(0.0, 0.5), (0.25, 1.0), (0.6, 1.6)])
    links.new(grit.outputs["Distance"], stones.inputs["Fac"])
    c = _mix_rgb(nodes, links, "MULTIPLY", 1.0, col.outputs["Color"], stones.outputs["Color"])
    c = _mix_rgb(nodes, links, "MULTIPLY", 1.0, c, (1.0, 0.97, 0.94))
    links.new(c, bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.88
    bsdf.inputs["Specular IOR Level"].default_value = 0.3
    h = _math(nodes, links, "ADD", grit.outputs["Distance"],
              _math(nodes, links, "MULTIPLY", fine.outputs["Fac"], 0.3))
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.9
    bump.inputs["Distance"].default_value = 0.012
    links.new(h, bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def board_concrete_material(name="Studio_Concrete_Boards", vertical=True, brightness=1.0):
    """Board-formed concrete: horizontal plank imprints, panel joints, streaks and pores.

    vertical=True  -> pattern lives in the object's XZ plane (walls)
    vertical=False -> pattern lives in the object's XY plane (ceiling)
    """
    mat, fresh = _new_mat(name)
    if not fresh:
        return mat
    nodes, links = _nodes(mat)
    bsdf = nodes["Principled BSDF"]
    tc = nodes.new("ShaderNodeTexCoord")
    if vertical:
        sep = nodes.new("ShaderNodeSeparateXYZ")
        links.new(tc.outputs["Object"], sep.inputs[0])
        comb = nodes.new("ShaderNodeCombineXYZ")
        links.new(sep.outputs["X"], comb.inputs["X"])
        links.new(sep.outputs["Z"], comb.inputs["Y"])
        vec = comb.outputs[0]
    else:
        vec = tc.outputs["Object"]

    # planks: 3.4 m long, 0.15 m high, thin dark joints
    planks = nodes.new("ShaderNodeTexBrick")
    planks.offset = 0.37
    planks.inputs["Color1"].default_value = (0.47, 0.47, 0.47, 1)
    planks.inputs["Color2"].default_value = (0.60, 0.60, 0.60, 1)
    planks.inputs["Mortar"].default_value = (0.12, 0.12, 0.12, 1)
    planks.inputs["Scale"].default_value = 1.0
    planks.inputs["Mortar Size"].default_value = 0.004
    planks.inputs["Mortar Smooth"].default_value = 0.4
    planks.inputs["Bias"].default_value = 0.0
    planks.inputs["Brick Width"].default_value = 3.4
    planks.inputs["Row Height"].default_value = 0.15
    links.new(vec, planks.inputs["Vector"])

    # formwork panels: 2.5 m x 2.5 m joints
    panels = nodes.new("ShaderNodeTexBrick")
    panels.offset = 0.0
    panels.inputs["Color1"].default_value = (0.9, 0.9, 0.9, 1)
    panels.inputs["Color2"].default_value = (1, 1, 1, 1)
    panels.inputs["Mortar"].default_value = (0.35, 0.35, 0.35, 1)
    panels.inputs["Scale"].default_value = 1.0
    panels.inputs["Mortar Size"].default_value = 0.012
    panels.inputs["Mortar Smooth"].default_value = 0.6
    panels.inputs["Brick Width"].default_value = 5.0
    panels.inputs["Row Height"].default_value = 2.4
    links.new(vec, panels.inputs["Vector"])

    # wood grain along the planks + vertical run-off streaks + cloudy patches
    def stretched(sx, sy):
        mp = nodes.new("ShaderNodeMapping")
        mp.inputs["Scale"].default_value = (sx, sy, 1.0)
        links.new(vec, mp.inputs["Vector"])
        return mp.outputs[0]

    grain = _noise(nodes, links, stretched(1.2, 70.0), 1.0, 2.0, 0.7, 0.4)
    streak = _noise(nodes, links, stretched(3.0, 0.25), 1.0, 2.0, 0.6, 0.3)
    cloud = _noise(nodes, links, vec, 0.35, 2.0, 0.65, 0.5)
    pores = nodes.new("ShaderNodeTexVoronoi")
    pores.inputs["Scale"].default_value = 22.0
    links.new(vec, pores.inputs["Vector"])
    pore_mask = _ramp(nodes, [(0.0, 0.25), (0.045, 1.0)])
    links.new(pores.outputs["Distance"], pore_mask.inputs["Fac"])

    cl = _ramp(nodes, [(0.25, 0.45), (0.75, 1.0)])
    links.new(cloud.outputs["Fac"], cl.inputs["Fac"])
    st = _ramp(nodes, [(0.3, 0.6), (0.7, 1.0)])
    links.new(streak.outputs["Fac"], st.inputs["Fac"])
    gr = _ramp(nodes, [(0.3, 0.75), (0.7, 1.0)])
    links.new(grain.outputs["Fac"], gr.inputs["Fac"])
    c = _mix_rgb(nodes, links, "MULTIPLY", 1.0, planks.outputs["Color"], panels.outputs["Color"])
    c = _mix_rgb(nodes, links, "MULTIPLY", 1.0, c, cl.outputs["Color"])
    c = _mix_rgb(nodes, links, "MULTIPLY", 0.8, c, st.outputs["Color"])
    c = _mix_rgb(nodes, links, "MULTIPLY", 0.7, c, gr.outputs["Color"])
    c = _mix_rgb(nodes, links, "MULTIPLY", 0.8, c, pore_mask.outputs["Color"])
    b = 0.34 * brightness
    c = _mix_rgb(nodes, links, "MULTIPLY", 1.0, c, (b, b * 0.99, b * 0.97))
    links.new(c, bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.82
    bsdf.inputs["Specular IOR Level"].default_value = 0.25

    h = _math(nodes, links, "MULTIPLY", planks.outputs["Fac"], -1.0)           # joints recessed
    h = _math(nodes, links, "ADD", h, _math(nodes, links, "MULTIPLY", panels.outputs["Fac"], -1.5))
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.6
    bump.inputs["Distance"].default_value = 0.004
    links.new(h, bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


# ---------------------------------------------------------------------------
# world (studio black <-> daylight sky, switched with one value node)
# ---------------------------------------------------------------------------
def _build_world():
    scene = bpy.context.scene
    world = bpy.data.worlds.get("Studio_World")
    if world is None:
        world = bpy.data.worlds.new("Studio_World")
        world.use_nodes = True
        nt = world.node_tree
        nt.nodes.clear()
        out = nt.nodes.new("ShaderNodeOutputWorld")
        dark = nt.nodes.new("ShaderNodeBackground")
        dark.name = "StudioBG"
        dark.inputs["Color"].default_value = (0.010, 0.011, 0.013, 1)
        dark.inputs["Strength"].default_value = 1.0
        sky = nt.nodes.new("ShaderNodeTexSky")
        sky.name = "Sky"
        for typ in ("MULTIPLE_SCATTERING", "NISHITA", "HOSEK_WILKIE"):
            try:
                sky.sky_type = typ
                break
            except TypeError:
                continue
        for attr, val in (("sun_elevation", math.radians(34.0)), ("sun_rotation", math.radians(100.0)),
                          ("sun_size", math.radians(1.2)), ("sun_intensity", 1.0),
                          ("aerosol_density", 0.6), ("ozone_density", 2.0), ("altitude", 300.0)):
            try:
                setattr(sky, attr, val)
            except (AttributeError, TypeError):
                pass
        day = nt.nodes.new("ShaderNodeBackground")
        day.name = "DayBG"
        day.inputs["Strength"].default_value = 0.11
        nt.links.new(sky.outputs[0], day.inputs["Color"])
        mix = nt.nodes.new("ShaderNodeMixShader")
        mix.name = "EnvMix"
        mix.inputs[0].default_value = 0.0
        nt.links.new(dark.outputs[0], mix.inputs[1])
        nt.links.new(day.outputs[0], mix.inputs[2])
        nt.links.new(mix.outputs[0], out.inputs["Surface"])
    scene.world = world
    return world


# ---------------------------------------------------------------------------
# studio
# ---------------------------------------------------------------------------
def _plane_object(name, verts, mat, coll):
    obj = util.new_mesh_object(name, verts, [(0, 1, 2, 3)], collection=coll, smooth=False)
    obj.data.materials.append(mat)
    return obj


def _area(name, size, loc, target, energy, coll, color=(1, 1, 1), spread=math.radians(180)):
    ld = bpy.data.lights.new(name, "AREA")
    ld.shape = "RECTANGLE"
    ld.size, ld.size_y = size
    ld.energy = energy
    ld.color = color
    try:
        ld.spread = spread
    except AttributeError:
        pass
    ob = bpy.data.objects.new(name, ld)
    ob.location = loc
    coll.objects.link(ob)
    util.look_at(ob, target)
    ob.visible_camera = False          # never show the fixtures themselves
    return ob


def _spot(name, loc, target, energy, cone_deg, blend, coll, radius=0.5, color=(1, 1, 1)):
    ld = bpy.data.lights.new(name, "SPOT")
    ld.energy = energy
    ld.spot_size = math.radians(cone_deg)
    ld.spot_blend = blend
    ld.shadow_soft_size = radius
    ld.color = color
    ob = bpy.data.objects.new(name, ld)
    ob.location = loc
    coll.objects.link(ob)
    util.look_at(ob, target)
    return ob


def build_studio(collection=None):
    """Create the garage, lights and world.  Idempotent.  Returns {name: object}."""
    coll = collection or _coll(STUDIO_COLLECTION)
    if "STUDIO_Floor" in bpy.data.objects:
        return {o.name: o for o in bpy.data.objects if o.name.startswith("STUDIO_")}
    _build_world()

    s = 400.0
    floor = _plane_object("STUDIO_Floor", [(-s, -s, 0), (s, -s, 0), (s, s, 0), (-s, s, 0)],
                          floor_material(), coll)
    c = 70.0
    ceiling = _plane_object("STUDIO_Ceiling",
                            [(-c, -c, 0), (-c, c, 0), (c, c, 0), (c, -c, 0)],
                            board_concrete_material("Studio_Concrete_Ceiling", vertical=False,
                                                    brightness=0.5), coll)
    ceiling.location = (0, 0, CEILING_Z)
    # back wall: local XZ plane facing local -Y, re-positioned per view by apply_view()
    w = 70.0
    wall = _plane_object("STUDIO_Wall",
                         [(-w, 0, 0), (w, 0, 0), (w, 0, CEILING_Z), (-w, 0, CEILING_Z)],
                         board_concrete_material("Studio_Concrete_Wall", vertical=True), coll)
    wall.location = (0, 12, 0)

    # --- car-centric soft boxes (only light the car: see _link_lights) --------------------
    lights = []
    lights.append(_area("STUDIO_Top", (7.6, 1.8), (0.2, 0, 3.9), (0.2, 0, 0), 45, coll))
    for sgn, tag in ((1, "L"), (-1, "R")):
        lights.append(_area(f"STUDIO_Strip_{tag}", (11.0, 3.2), (0.3, sgn * 5.6, 3.3),
                            (0, 0, 0.7), 300, coll))
        lights.append(_area(f"STUDIO_Low_{tag}", (9.0, 0.5), (0, sgn * 5.4, 0.45),
                            (0, 0, 0.45), 30, coll))
    lights.append(_area("STUDIO_Strip_F", (4.6, 0.8), (6.2, 0, 2.3), (0, 0, 0.7), 150, coll))
    lights.append(_area("STUDIO_Strip_B", (4.6, 0.8), (-6.4, 0, 2.3), (0, 0, 0.8), 150, coll))
    # warm courtesy light inside the cabin, only switched on for the top view
    lights.append(_area("STUDIO_Cabin", (1.3, 0.9), (-0.35, 0, 1.36), (-0.35, 0, 0.5), 22, coll,
                        color=(1.0, 0.86, 0.72)))

    # --- environment lights (floor pool, wall wash) ----------------------------------------
    _spot("STUDIO_Pool", (0, 0, CEILING_Z - 0.25), (0, 0, 0), 3800, 104, 1.0, coll, radius=0.9)
    wash = _area("STUDIO_WallWash", (5.5, 0.5), (0, 9.5, 0.35), (0, 12, 1.5), 400, coll,
                 spread=math.radians(110))
    wash.visible_glossy = False
    # --- daylight variant: the sky texture carries the sun; nothing else needed -----------
    link_lights_to_car()
    return {o.name: o for o in bpy.data.objects if o.name.startswith("STUDIO_")}


def link_lights_to_car():
    """Restrict the soft boxes to the car collection so they do not wash the floor / wall."""
    car = bpy.data.collections.get(CAR_COLLECTION)
    for ob in bpy.data.objects:
        if (ob.type == "LIGHT" and ob.data.type == "AREA" and ob.name.startswith("STUDIO_")
                and ob.name != "STUDIO_WallWash"):
            try:
                ob.light_linking.receiver_collection = car
            except AttributeError:
                pass
    # the ceiling spot only paints the pool on the floor (the car still shadows it):
    # its mirror image in the clear coat would burn out bonnet, roof and glass
    pool = bpy.data.objects.get("STUDIO_Pool")
    studio = bpy.data.collections.get(STUDIO_COLLECTION)
    if pool is not None and studio is not None:
        try:
            pool.light_linking.receiver_collection = studio
        except AttributeError:
            pass


# ---------------------------------------------------------------------------
# cameras
# ---------------------------------------------------------------------------
def build_cameras(collection=None):
    """Create CAM_01 … CAM_09.  Returns {1: object, …, 9: object}."""
    coll = collection or _coll(CAMERA_COLLECTION)
    cams = {}
    for n, v in VIEWS.items():
        name = f"CAM_{n:02d}"
        cam = bpy.data.objects.get(name)
        if cam is None:
            cam = bpy.data.objects.new(name, bpy.data.cameras.new(name))
            coll.objects.link(cam)
        cam.location = v["loc"]
        cam.rotation_euler = [math.radians(a) for a in v["rot"]]
        cd = cam.data
        cd.type = "PERSP"
        cd.sensor_fit = "HORIZONTAL"
        cd.sensor_width = SENSOR
        cd.lens = v["lens"]
        cd.clip_start = 0.1
        cd.clip_end = 2000.0
        cams[n] = cam
    return cams


def _view_dir(n):
    """Horizontal unit vector the camera of view n looks along."""
    cam = bpy.data.objects[f"CAM_{n:02d}"]
    d = cam.matrix_world.to_quaternion() @ Vector((0, 0, -1))
    d.z = 0.0
    if d.length < 1e-4:
        return Vector((1, 0, 0))
    return d.normalized()


def apply_view(n):
    """Make view n current: active camera, wall / wall-wash placement, environment, exposure."""
    scene = bpy.context.scene
    v = VIEWS[n]
    cam = bpy.data.objects.get(f"CAM_{n:02d}") or build_cameras()[n]
    scene.camera = cam
    bpy.context.view_layer.update()
    studio = v["env"] == "studio"
    objs = bpy.data.objects
    wall, ceil = objs.get("STUDIO_Wall"), objs.get("STUDIO_Ceiling")
    wash, pool = objs.get("STUDIO_WallWash"), objs.get("STUDIO_Pool")
    if wall is not None:
        d = _view_dir(n)
        use_wall = studio and v["wall"] is not None
        wall.hide_render = wall.hide_viewport = not use_wall
        if use_wall:
            # keep the wall centred on the optical axis, perpendicular to the view
            p = d * v["wall"]
            wall.location = (p.x, p.y, 0.0)
            wall.rotation_euler = (0, 0, math.atan2(d.y, d.x) - math.pi / 2)
            if wash is not None:
                # floor-level strip washing the wall from 2.6 m in front of it
                q = d * (v["wall"] - 2.6)
                wash.location = (q.x, q.y, 0.35)
                util.look_at(wash, (p.x, p.y, 1.5))
        if wash is not None:
            wash.hide_render = wash.hide_viewport = not use_wall
    mult = v.get("lights", {})
    for ob in objs:
        if not ob.name.startswith("STUDIO_") or ob.type != "LIGHT":
            continue
        if ob is not wash:
            ob.hide_render = ob.hide_viewport = not studio
        if "base_energy" not in ob:
            ob["base_energy"] = ob.data.energy
        ob.data.energy = ob["base_energy"] * mult.get(
            ob.name, 0.0 if ob.name == "STUDIO_Cabin" else 1.0)
    if ceil is not None:
        ceil.hide_render = ceil.hide_viewport = not studio
    floor = objs.get("STUDIO_Floor")
    if floor is not None:
        floor.data.materials[0] = floor_material() if studio else ground_material()
    world = scene.world
    if world and world.node_tree and "EnvMix" in world.node_tree.nodes:
        world.node_tree.nodes["EnvMix"].inputs[0].default_value = 0.0 if studio else 1.0
    scene.view_settings.exposure = _BASE_EXPOSURE[v["env"]] + v.get("exposure", 0.0)
    link_lights_to_car()
    return cam


_BASE_EXPOSURE = {"studio": 0.0, "daylight": -0.2}


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------
def setup_render(quality="draft", engine="CYCLES"):
    """Configure the render engine, sampling, resolution and colour management."""
    scene = bpy.context.scene
    res, spp, thr = QUALITY[quality]
    r = scene.render
    r.resolution_x, r.resolution_y = res
    r.resolution_percentage = 100
    r.image_settings.file_format = "PNG"
    r.image_settings.color_mode = "RGB"
    r.film_transparent = False
    r.threads_mode = "AUTO"
    if engine == "CYCLES":
        r.engine = "CYCLES"
        c = scene.cycles
        c.device = "CPU"
        c.samples = spp
        c.use_adaptive_sampling = True
        c.adaptive_threshold = thr
        c.use_denoising = True
        try:
            c.denoiser = "OPENIMAGEDENOISE"
            c.denoising_input_passes = "RGB_ALBEDO_NORMAL"
            c.denoising_prefilter = "FAST" if quality == "draft" else "ACCURATE"
        except (TypeError, AttributeError):
            pass
        c.max_bounces = 8
        c.diffuse_bounces = 2
        c.glossy_bounces = 5
        c.transmission_bounces = 10
        c.transparent_max_bounces = 10
        c.volume_bounces = 0
        c.caustics_reflective = False
        c.caustics_refractive = False
        c.sample_clamp_indirect = 6.0
        c.blur_glossy = 0.5
        c.filter_width = 1.5
    else:
        try:
            r.engine = engine
            scene.eevee.taa_render_samples = max(16, spp)
        except (TypeError, AttributeError):
            pass
    vs = scene.view_settings
    for vt in ("AgX", "Filmic", "Standard"):
        try:
            vs.view_transform = vt
            break
        except TypeError:
            continue
    for look in ("AgX - Medium High Contrast", "Medium High Contrast", "AgX - Base Contrast", "None"):
        try:
            vs.look = look
            break
        except TypeError:
            continue
    vs.gamma = 1.0
    return scene


def render_view(n, path, quality="draft"):
    """Render reference view n (1..9) to ``path`` (PNG).  Returns the path."""
    scene = setup_render(quality)
    if "STUDIO_Floor" not in bpy.data.objects:
        build_studio()
    if f"CAM_{n:02d}" not in bpy.data.objects:
        build_cameras()
    apply_view(n)
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return path


def render_all(outdir, quality="draft", views=range(1, 10)):
    os.makedirs(outdir, exist_ok=True)
    paths = []
    for n in views:
        t = time.time()
        p = os.path.join(outdir, f"view_{n:02d}.png")
        render_view(n, p, quality)
        print(f"[scene] view {n:02d} ({quality}) rendered in {time.time() - t:.1f} s -> {p}")
        paths.append(p)
    return paths


# ---------------------------------------------------------------------------
# PIL sheets
# ---------------------------------------------------------------------------
_FONT_DIRS = ("/usr/share/fonts/opentype/inter", "/usr/share/fonts/truetype/dejavu",
              "/usr/share/fonts/truetype/liberation")
_FONTS = {
    "bold": ("Inter-Bold.otf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"),
    "semi": ("Inter-SemiBold.otf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"),
    "regular": ("Inter-Regular.otf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"),
    "light": ("Inter-Light.otf", "DejaVuSans-ExtraLight.ttf", "LiberationSans-Regular.ttf"),
}


def _font(kind, size):
    from PIL import ImageFont
    for fname in _FONTS[kind]:
        for d in _FONT_DIRS:
            p = os.path.join(d, fname)
            if os.path.exists(p):
                return ImageFont.truetype(p, int(round(size)))
    return ImageFont.load_default()


def _fit_tile(img, size):
    """Centre-crop/resize an image to exactly ``size`` (cover)."""
    from PIL import Image
    tw, th = size
    w, h = img.size
    sc = max(tw / w, th / h)
    img = img.resize((max(tw, round(w * sc)), max(th, round(h * sc))), Image.LANCZOS)
    x0 = (img.size[0] - tw) // 2
    y0 = (img.size[1] - th) // 2
    return img.crop((x0, y0, x0 + tw, y0 + th))


def _view_number(path, default):
    import re
    m = re.search(r"(\d+)(?=\D*$)", os.path.splitext(os.path.basename(path))[0])
    n = int(m.group(1)) if m else default
    return n if n in VIEWS else default


def contact_sheet(paths, out_path, title="BMW M5", subtitle="G90", page="02 / 02",
                  section="ЭКСТЕРЬЕР  /  3D-МОДЕЛЬ", width=6000, footer_left=None,
                  footer_right="3D-МОДЕЛЬ · BLENDER"):
    """3x3 sheet in the layout of the user's reference sheet (6000x4700 at width=6000)."""
    from PIL import Image, ImageDraw
    k = width / 6000.0
    S = lambda v: int(round(v * k))  # noqa: E731
    page_bg, ink, mute, blue = (243, 242, 238), (27, 31, 40), (88, 92, 102), (26, 92, 150)
    sheet = Image.new("RGB", (S(6000), S(4700)), page_bg)
    d = ImageDraw.Draw(sheet)
    # header
    f_title = _font("bold", S(124))
    d.text((S(120), S(52)), title, font=f_title, fill=ink)
    tw = d.textlength(title, font=f_title)
    d.text((S(120) + tw + S(44), S(80)), subtitle, font=_font("regular", S(92)), fill=mute)
    d.text((S(120), S(222)), section, font=_font("semi", S(40)), fill=mute)
    f_page = _font("regular", S(62))
    d.text((S(5880) - d.textlength(page, font=f_page), S(64)), page, font=f_page, fill=ink)
    cnt = f"{len(paths)} РАКУРСОВ"
    f_small = _font("regular", S(34))
    d.text((S(5880) - d.textlength(cnt, font=f_small), S(226)), cnt, font=f_small, fill=mute)
    d.line([(S(120), S(300)), (S(5880), S(300))], fill=(200, 199, 194), width=max(1, S(3)))
    # tiles
    xs, ys = (120, 2056, 3992), (348, 1760, 3172)
    tile = (S(1888), S(1260))
    f_num, f_cap, f_id = _font("bold", S(40)), _font("regular", S(40)), _font("regular", S(18))
    for i, p in enumerate(paths[:9]):
        n = _view_number(p, i + 1)
        x, y = S(xs[i % 3]), S(ys[i // 3])
        sheet.paste(_fit_tile(Image.open(p).convert("RGB"), tile), (x, y))
        d.text((x, y + tile[1] + S(26)), f"{n:02d}", font=f_num, fill=blue)
        d.text((x + S(90), y + tile[1] + S(26)), VIEWS[n]["label"], font=f_cap, fill=ink)
        tag = f"CAM_{n:02d} · {VIEWS[n]['lens']:.0f} mm"
        d.text((x + tile[0] - d.textlength(tag, font=f_id), y + tile[1] + S(80)), tag,
               font=f_id, fill=mute)
    # footer
    d.line([(S(120), S(4572)), (S(5880), S(4572))], fill=(200, 199, 194), width=max(1, S(3)))
    f_foot = _font("regular", S(27))
    left = footer_left or ("Рендер: Blender Cycles · процедурная модель BMW M5 (G90)\n"
                           "Левый и правый борт указаны по ходу автомобиля.")
    for j, line in enumerate(left.split("\n")):
        d.text((S(120), S(4600) + j * S(46)), line, font=f_foot, fill=mute)
    dims = f"{sheet.size[0]} × {sheet.size[1]} PX"
    d.text((S(5880) - d.textlength(dims, font=f_foot), S(4600)), dims, font=f_foot, fill=mute)
    d.text((S(5880) - d.textlength(footer_right, font=f_foot), S(4646)), footer_right,
           font=f_foot, fill=mute)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    sheet.save(out_path)
    return out_path


def _ref_path(ref_dir, n):
    for pat in (f"v{n:02d}.png", f"view_{n:02d}.png", f"{n:02d}.png", f"v{n:02d}.jpg"):
        p = os.path.join(ref_dir, pat)
        if os.path.exists(p):
            return p
    return None


def compare_view(n, ref_dir, render_path, out_path, mode="side", tile_width=1416, alpha=0.5):
    """One view: reference next to the render (mode='side'), 50/50 blend ('blend'), or the
    render's edges drawn over the reference ('edges') – handy for checking proportions."""
    from PIL import Image, ImageChops, ImageFilter, ImageOps
    tile = (tile_width, round(tile_width * REF_TILE[1] / REF_TILE[0]))
    ref = _fit_tile(Image.open(_ref_path(ref_dir, n)).convert("RGB"), tile)
    ren = _fit_tile(Image.open(render_path).convert("RGB"), tile)
    if mode == "blend":
        out = Image.blend(ref, ren, alpha)
    elif mode == "edges":
        e = ren.convert("L").filter(ImageFilter.GaussianBlur(1.2)).filter(ImageFilter.FIND_EDGES)
        e = ImageOps.autocontrast(e.point(lambda v: 0 if v < 10 else min(255, v * 6)))
        yellow = Image.merge("RGB", (e, e, Image.new("L", tile, 0)))
        out = ImageChops.lighter(ref, yellow)
    else:
        out = Image.new("RGB", (tile[0] * 2 + 12, tile[1]), (20, 20, 22))
        out.paste(ref, (0, 0))
        out.paste(ren, (tile[0] + 12, 0))
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    out.save(out_path)
    return out_path


def side_by_side(ref_dir, paths, out_path, tile_width=1200):
    """Comparison sheet: for every view the reference tile (left) next to our render (right),
    two pairs per row so the tiles stay large."""
    from PIL import Image, ImageDraw
    tile = (tile_width, round(tile_width * REF_TILE[1] / REF_TILE[0]))
    gap, pad, cap_h, head = 10, 40, 56, 110
    cols = 2
    rows = math.ceil(len(paths) / cols)
    pair_w = tile[0] * 2 + gap
    W = pad + cols * (pair_w + pad)
    Hh = head + rows * (tile[1] + cap_h + pad // 2) + pad
    sheet = Image.new("RGB", (W, Hh), (243, 242, 238))
    d = ImageDraw.Draw(sheet)
    d.text((pad, 28), "BMW M5 G90 — референс / 3D-модель", font=_font("bold", 50), fill=(27, 31, 40))
    f_num, f_cap = _font("bold", 30), _font("regular", 30)
    for i, p in enumerate(paths):
        n = _view_number(p, i + 1)
        x = pad + (i % cols) * (pair_w + pad)
        y = head + (i // cols) * (tile[1] + cap_h + pad // 2)
        rp = _ref_path(ref_dir, n)
        if rp:
            sheet.paste(_fit_tile(Image.open(rp).convert("RGB"), tile), (x, y))
        sheet.paste(_fit_tile(Image.open(p).convert("RGB"), tile), (x + tile[0] + gap, y))
        d.text((x, y + tile[1] + 10), f"{n:02d}", font=f_num, fill=(26, 92, 150))
        d.text((x + 60, y + tile[1] + 10), VIEWS[n]["label"] + "   (слева референс, справа модель)",
               font=f_cap, fill=(27, 31, 40))
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    sheet.save(out_path)
    return out_path


# ---------------------------------------------------------------------------
# self test with a placeholder car (NOT part of the API)
# ---------------------------------------------------------------------------
def _placeholder_car():
    import numpy as np
    from . import materials as M
    from . import params as P
    coll = util.get_collection(CAR_COLLECTION)

    def interp(x, pts):
        xs, ys = zip(*sorted(pts))
        return np.interp(x, xs, ys)

    top = [(-2.708, 0.80), (-2.66, 1.00), (-2.2, 1.05), (-1.6, 1.05), (0.85, 1.02), (1.2, 0.97),
           (2.2, 0.80), (2.34, 0.70), (2.388, 0.55)]
    bot = [(-2.708, 0.70), (-2.62, 0.32), (-2.3, 0.20), (2.1, 0.17), (2.33, 0.22), (2.388, 0.45)]
    half = [(-2.708, 0.55), (-2.66, 0.82), (-2.45, 0.93), (-1.5, 0.975), (0.0, 0.95), (1.5, 0.983),
            (2.1, 0.93), (2.3, 0.80), (2.388, 0.55)]
    nx, nt = 120, 64
    xs = -2.708 + (np.cos(np.linspace(np.pi, 0, nx)) * 0.5 + 0.5) * P.LENGTH
    t = np.linspace(0, 2 * np.pi, nt, endpoint=False)
    se = lambda v, e: np.sign(v) * np.abs(v) ** e  # noqa: E731
    body = np.zeros((nx, nt, 3))
    for i, x in enumerate(xs):
        zt, zb, w = interp(x, top), interp(x, bot), interp(x, half)
        end = min(1.0, (x - P.X_REAR + 0.004) / 0.05, (P.X_FRONT + 0.004 - x) / 0.05)
        end = max(end, 0.0) ** 0.5
        zc, hz = (zt + zb) / 2, (zt - zb) / 2 * max(end, 0.02)
        body[i, :, 0] = x
        body[i, :, 1] = w * max(end, 0.02) * se(np.cos(t), 0.35)
        body[i, :, 2] = zc + hz * se(np.sin(t), 0.35)
    ob = util.grid_object("PH_Body", body, coll, close_v=True)
    ob.data.materials.append(M.car_paint())

    roof = [(-2.15, 1.04), (-1.55, 1.36), (-1.0, 1.47), (-0.3, 1.51), (0.15, 1.42), (0.85, 1.02)]
    gx = np.linspace(-2.15, 0.85, 60)
    gt = np.linspace(0, np.pi, 40)
    gh = np.zeros((60, 40, 3))
    for i, x in enumerate(gx):
        zr = interp(x, roof)
        wb = interp(x, [(-2.15, 0.60), (-1.5, 0.78), (0.3, 0.80), (0.85, 0.74)])
        gh[i, :, 0] = x
        gh[i, :, 1] = wb * se(np.cos(gt), 0.45) * (1 - 0.22 * np.sin(gt) ** 2)
        gh[i, :, 2] = 1.0 + (zr - 1.0) * se(np.sin(gt), 0.45)
    og = util.grid_object("PH_Greenhouse", gh, coll)
    og.data.materials.append(M.gloss_black())

    for name, x, y, z, tyre in (("FL", P.AXLE_F_X, P.WHEEL_F_Y, P.WHEEL_F_Z, P.TYRE_F),
                                ("FR", P.AXLE_F_X, -P.WHEEL_F_Y, P.WHEEL_F_Z, P.TYRE_F),
                                ("RL", P.AXLE_R_X, P.WHEEL_R_Y, P.WHEEL_R_Z, P.TYRE_R),
                                ("RR", P.AXLE_R_X, -P.WHEEL_R_Y, P.WHEEL_R_Z, P.TYRE_R)):
        rad = P.tyre_radius(tyre)
        bpy.ops.mesh.primitive_cylinder_add(radius=rad, depth=tyre["width"], vertices=64,
                                            location=(x, y, z), rotation=(math.pi / 2, 0, 0))
        w = bpy.context.active_object
        w.name = f"PH_Tyre_{name}"
        w.data.materials.append(M.rubber())
        _move_to(w, coll)
        bpy.ops.mesh.primitive_cylinder_add(radius=tyre["rim_in"] * 0.0127 + 0.018, depth=0.02,
                                            vertices=64, rotation=(math.pi / 2, 0, 0),
                                            location=(x, y + math.copysign(tyre["width"] / 2, y), z))
        r = bpy.context.active_object
        r.name = f"PH_Rim_{name}"
        r.data.materials.append(M.aluminium())
        _move_to(r, coll)
    for sgn in (1, -1):
        bpy.ops.mesh.primitive_cube_add(size=1, location=(0.62, sgn * 1.0, 1.07))
        m = bpy.context.active_object
        m.scale = (0.22, 0.16, 0.13)
        m.name = "PH_Mirror"
        m.data.materials.append(M.gloss_black())
        _move_to(m, coll)
    for x, z in ((P.X_FRONT + 0.004, 0.45), (-2.70, 0.73)):
        bpy.ops.mesh.primitive_cube_add(size=1, location=(x, 0, z))
        pl = bpy.context.active_object
        pl.scale = (0.02, 0.52, 0.11)
        pl.name = "PH_Plate"
        pl.data.materials.append(M.principled("PH_PlateWhite", color=(0.8, 0.8, 0.8), roughness=0.4))
        _move_to(pl, coll)
    return coll


def _selftest(outdir, quality="draft", views=range(1, 10), ref_dir=None):
    util.reset_scene()
    _placeholder_car()
    build_studio()
    build_cameras()
    paths = render_all(outdir, quality, views)
    sheet = contact_sheet(paths, os.path.join(outdir, "contact_sheet.png"), width=3000)
    out = [sheet]
    if ref_dir and os.path.isdir(ref_dir):
        out.append(side_by_side(ref_dir, paths, os.path.join(outdir, "comparison.png"), tile_width=900))
    return paths, out


if __name__ == "__main__":
    import sys
    import tempfile
    _scratch = os.environ.get("M5_SCENE_OUT") or os.path.join(tempfile.gettempdir(),
                                                              "m5g90_scene_selftest")
    _ref = os.environ.get("M5_REF_DIR", "")
    _q = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in QUALITY else "draft"
    _views = [int(a) for a in sys.argv[2:]] or range(1, 10)
    t0 = time.time()
    _paths, _sheets = _selftest(_scratch, _q, _views, _ref)
    print(f"[scene] done in {time.time() - t0:.1f} s:", *_sheets)
