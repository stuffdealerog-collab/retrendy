"""Procedural interior of the BMW M5 (G90): M sport seats, rear bench, dashboard with the
curved display, steering wheel, centre console, door cards, carpet and parcel shelf.

Everything is built in car coordinates (+X forward, +Y car-left, +Z up, origin on the ground
mid-wheelbase), left-hand drive, and stays inside ``params.CABIN``.

    from m5g90 import interior
    objs = interior.build_interior(collection)

Run ``python3 -m m5g90.interior`` to build it standalone and write preview renders.
"""
import math
import os

import bpy
import bmesh
import numpy as np

from . import materials as M
from . import params as P
from . import util

C = P.CABIN


# ---------------------------------------------------------------------------
# small maths helpers
# ---------------------------------------------------------------------------
def _spow(x, p):
    return np.sign(x) * np.abs(x) ** p


def _sstep(a, b, x):
    t = np.clip((np.asarray(x, dtype=float) - a) / (b - a), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _lerp(a, b, t):
    return a + (b - a) * t


def _v(*a):
    return np.array(a, dtype=float)


def _unit(v):
    v = np.asarray(v, dtype=float)
    return v / np.linalg.norm(v)


def _interp_table(x, table):
    """Piecewise-linear lookup in a list of (x, v0, v1, ...) rows -> array of values."""
    t = np.asarray(table, dtype=float)
    return np.array([np.interp(x, t[:, 0], t[:, i]) for i in range(1, t.shape[1])])


# ---------------------------------------------------------------------------
# mesh helpers
# ---------------------------------------------------------------------------
def _ring_mesh(name, rings, mats, mat_fn=None, coll=None, subsurf=2, cap=True,
               close_u=False, render_levels=None, attrs=None):
    """Mesh from stacked closed rings ``rings[nu, nv, 3]`` (closed along v).

    mat_fn(i, k) -> material slot for the quad between ring i,i+1 and segment k,k+1.
    Open ends are closed with an n-gon (material slot ``mat_fn(-1, 0)`` / ``mat_fn(nu, 0)``).
    """
    rings = np.asarray(rings, dtype=float)
    nu, nv = rings.shape[:2]
    verts = rings.reshape(-1, 3)
    faces, fm = [], []
    for i in range(nu if close_u else nu - 1):
        i1 = (i + 1) % nu
        for k in range(nv):
            k1 = (k + 1) % nv
            faces.append((i * nv + k, i1 * nv + k, i1 * nv + k1, i * nv + k1))
            fm.append(mat_fn(i, k) if mat_fn else 0)
    if cap and not close_u:
        faces.append(tuple(range(nv - 1, -1, -1)))
        fm.append(mat_fn(-1, 0) if mat_fn else 0)
        faces.append(tuple((nu - 1) * nv + k for k in range(nv)))
        fm.append(mat_fn(nu, 0) if mat_fn else 0)
    obj = util.new_mesh_object(name, verts, faces, coll, smooth=True)
    for m in mats:
        obj.data.materials.append(m)
    obj.data.polygons.foreach_set("material_index", [int(min(max(v, 0), len(mats) - 1)) for v in fm])
    for an, av in (attrs or {}).items():
        at = obj.data.attributes.new(an, "FLOAT", "POINT")
        at.data.foreach_set("value", np.asarray(av, dtype=np.float32).ravel())
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    if subsurf:
        mod = obj.modifiers.new("Subsurf", "SUBSURF")
        mod.levels = subsurf
        mod.render_levels = render_levels or subsurf
    return obj


def _slab(name, origin, A, T, N, stations, mats, coll=None, nseg=24, subsurf=2,
          render_levels=3):
    """Padded, bolstered cushion.

    Local frame: A along the length, T across the width, N the padded ("top") side.
    stations: rows of (s, w, ht, hb, b, c, ci, n)
        s  position along A              w  half width along T
        ht/hb thickness on the top/back  b  extra height of the side bolsters
        c  offset of the section along N ci centre-insert fraction of the width (0 = none)
        n  super-ellipse exponent
    Two point attributes are written for the two-tone leather shader: ``ins`` (> 0 inside
    the centre insert / on the back shell) and ``len`` (distance along A, drives the pleats).
    """
    origin, A, T, N = (np.asarray(a, dtype=float) for a in (origin, A, T, N))
    th = np.arange(nseg) * 2.0 * math.pi / nseg
    cs, sn = np.cos(th), np.sin(th)
    rings, ins, ln = [], [], []
    for st in stations:
        s, w, ht, hb, b, c, ci, n = (list(st) + [0.0, 0.0, 0.5, 3.0][len(st) - 4:])[:8]
        t = w * _spow(cs, 2.0 / n)
        q = np.where(sn > 0, ht, hb) * _spow(sn, 2.0 / n)
        frac = np.abs(t) / max(w, 1e-6)
        q = q + np.where(sn > 0, b * _sstep(0.42, 0.88, frac) * _sstep(0.0, 0.45, sn), 0.0)
        ring = (origin[None, :] + A[None, :] * s + T[None, :] * t[:, None]
                + N[None, :] * (c + q)[:, None])
        rings.append(ring)
        ins.append(np.where(sn > -1e-6, ci - frac, 0.30))
        ln.append(np.full(nseg, s))
    return _ring_mesh(name, rings, mats, None, coll, subsurf, render_levels=render_levels,
                      attrs={"ins": np.array(ins), "len": np.array(ln)})


def _rbox(name, centre, size, mat, coll=None, bevel=0.012, segments=3, rot=None):
    """Rounded box (Bevel modifier kept live)."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co.x *= size[0]
        v.co.y *= size[1]
        v.co.z *= size[2]
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    mesh.polygons.foreach_set("use_smooth", [True] * len(mesh.polygons))
    obj = bpy.data.objects.new(name, mesh)
    util.link(obj, coll)
    obj.location = centre
    if rot is not None:
        obj.rotation_euler = rot
    obj.data.materials.append(mat)
    if bevel:
        mod = obj.modifiers.new("Bevel", "BEVEL")
        mod.width = min(bevel, 0.49 * min(size))
        mod.segments = segments
        mod.limit_method = "ANGLE"
        mod.harden_normals = True
    return obj


def _cyl(name, p0, p1, r0, mat, coll=None, r1=None, n=40, mats=None, cap_slot=0):
    """Cylinder / cone frustum between two points."""
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    r1 = r0 if r1 is None else r1
    a = _unit(p1 - p0)
    ref = _v(0, 0, 1) if abs(a[2]) < 0.9 else _v(1, 0, 0)
    u = _unit(np.cross(a, ref))
    w = np.cross(a, u)
    th = np.arange(n) * 2 * math.pi / n
    circ = np.cos(th)[:, None] * u[None, :] + np.sin(th)[:, None] * w[None, :]
    rings = np.stack([p0 + circ * r0, p1 + circ * r1])
    obj = _ring_mesh(name, rings, mats or [mat], lambda i, k: cap_slot if (i < 0 or i > 0) else 0,
                     coll, subsurf=0)
    util.shade_smooth(obj, 40)
    return obj


# ---------------------------------------------------------------------------
# materials
# ---------------------------------------------------------------------------
def _mats():
    return dict(
        orange=M.leather_orange(),
        black=M.leather_black(),
        plastic=M.interior_plastic(),
        carpet=M.carpet(),
        screen=M.screen(),
        gloss=M.gloss_black(),
        alu=M.aluminium(),
        carbon=M.carbon(),
        red=M.principled("Interior_M_Red", color=(0.60, 0.01, 0.01), roughness=0.4),
        ambient=M.principled("Interior_Ambient_Light", color=(0.9, 0.3, 0.1),
                             emission=(1.0, 0.25, 0.06), emission_strength=1.5),
        seat=_two_tone_leather("Seat_Leather_TwoTone", (0.50, 0.14, 0.03), (0.014, 0.014, 0.015)),
        ui=M.principled("Display_UI_Glow", color=(0, 0, 0), emission=(0.25, 0.55, 1.0),
                        emission_strength=2.5),
        ui_red=M.principled("Display_UI_Red", color=(0, 0, 0), emission=(1.0, 0.12, 0.05),
                            emission_strength=2.5),
        ui_map=M.principled("Display_UI_Map", color=(0, 0, 0), emission=(0.10, 0.22, 0.26),
                            emission_strength=1.2),
    )


def _two_tone_leather(name, outer, insert, pleat=0.045):
    """Leather whose colour follows the ``ins`` point attribute (insert where ins > 0), with
    soft pleats across the insert driven by the ``len`` attribute."""
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = M.principled(name, color=outer, roughness=0.55, sheen=0.2)
    nt = mat.node_tree
    b = nt.nodes["Principled BSDF"]
    a_ins = nt.nodes.new("ShaderNodeAttribute")
    a_ins.attribute_name = "ins"
    edge = nt.nodes.new("ShaderNodeMapRange")
    edge.interpolation_type = "SMOOTHSTEP"
    edge.inputs["From Min"].default_value = -0.012
    edge.inputs["From Max"].default_value = 0.012
    nt.links.new(a_ins.outputs["Fac"], edge.inputs["Value"])
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.inputs["A"].default_value = (*outer, 1)
    mix.inputs["B"].default_value = (*insert, 1)
    nt.links.new(edge.outputs["Result"], mix.inputs["Factor"])
    nt.links.new(mix.outputs["Result"], b.inputs["Base Color"])
    # pleats + seam groove
    a_len = nt.nodes.new("ShaderNodeAttribute")
    a_len.attribute_name = "len"
    mul = nt.nodes.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    mul.inputs[1].default_value = 2 * math.pi / pleat
    nt.links.new(a_len.outputs["Fac"], mul.inputs[0])
    sine = nt.nodes.new("ShaderNodeMath")
    sine.operation = "SINE"
    nt.links.new(mul.outputs[0], sine.inputs[0])
    ab = nt.nodes.new("ShaderNodeMath")
    ab.operation = "ABSOLUTE"
    nt.links.new(sine.outputs[0], ab.inputs[0])
    pw = nt.nodes.new("ShaderNodeMath")
    pw.operation = "POWER"
    pw.inputs[1].default_value = 0.35
    nt.links.new(ab.outputs[0], pw.inputs[0])
    inner = nt.nodes.new("ShaderNodeMapRange")           # pleats only well inside the insert
    inner.inputs["From Min"].default_value = 0.02
    inner.inputs["From Max"].default_value = 0.07
    nt.links.new(a_ins.outputs["Fac"], inner.inputs["Value"])
    back = nt.nodes.new("ShaderNodeMath")                # ... and not on the back shell (ins=0.3)
    back.operation = "LESS_THAN"
    back.inputs[1].default_value = 0.295
    nt.links.new(a_ins.outputs["Fac"], back.inputs[0])
    msk = nt.nodes.new("ShaderNodeMath")
    msk.operation = "MULTIPLY"
    nt.links.new(inner.outputs["Result"], msk.inputs[0])
    nt.links.new(back.outputs[0], msk.inputs[1])
    hgt = nt.nodes.new("ShaderNodeMix")
    hgt.data_type = "FLOAT"
    hgt.inputs["A"].default_value = 1.0
    nt.links.new(msk.outputs[0], hgt.inputs["Factor"])
    nt.links.new(pw.outputs[0], hgt.inputs["B"])
    seam = nt.nodes.new("ShaderNodeMath")                # groove along the insert border
    seam.operation = "ABSOLUTE"
    nt.links.new(a_ins.outputs["Fac"], seam.inputs[0])
    seam2 = nt.nodes.new("ShaderNodeMapRange")
    seam2.inputs["From Min"].default_value = 0.0
    seam2.inputs["From Max"].default_value = 0.012
    nt.links.new(seam.outputs[0], seam2.inputs["Value"])
    tot = nt.nodes.new("ShaderNodeMath")
    tot.operation = "MULTIPLY"
    nt.links.new(hgt.outputs["Result"], tot.inputs[0])
    nt.links.new(seam2.outputs["Result"], tot.inputs[1])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.6
    bump.inputs["Distance"].default_value = 0.004
    nt.links.new(tot.outputs[0], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    return mat


# ---------------------------------------------------------------------------
# seats
# ---------------------------------------------------------------------------
def _front_seat(tag, y, m, coll):
    fs = C["front_seat"]
    hx, hz = fs["hx"], fs["hz"]
    seat_mats = [m["seat"]]
    objs = []

    # --- cushion -----------------------------------------------------------
    ca = math.radians(11.0)
    A = _v(math.cos(ca), 0, math.sin(ca))
    N = _v(-math.sin(ca), 0, math.cos(ca))
    T = _v(0, 1, 0)
    O = _v(hx - 0.155, y, hz - 0.160)
    #        s      w      ht     hb     b      c      ci    n
    cushion = [
        (0.000, 0.150, 0.022, 0.030, 0.000, 0.000, 0.30, 2.6),
        (0.025, 0.235, 0.045, 0.055, 0.020, 0.000, 0.36, 3.0),
        (0.130, 0.262, 0.050, 0.060, 0.058, -0.004, 0.40, 3.2),
        (0.270, 0.266, 0.050, 0.060, 0.060, -0.004, 0.44, 3.2),
        (0.390, 0.262, 0.050, 0.060, 0.045, 0.000, 0.52, 3.2),
        (0.480, 0.255, 0.048, 0.058, 0.022, 0.002, 0.62, 3.0),
        (0.525, 0.240, 0.040, 0.050, 0.006, 0.000, 0.66, 2.8),
        (0.545, 0.160, 0.022, 0.030, 0.000, -0.004, 0.66, 2.6),
    ]
    objs.append(_slab(f"Seat_{tag}_Cushion", O, A, T, N, cushion, seat_mats, coll))

    # --- backrest with integrated head restraint ----------------------------
    r = math.radians(21.0)
    A = _v(-math.sin(r), 0, math.cos(r))
    N = _v(math.cos(r), 0, math.sin(r))
    O = _v(hx - 0.200, y, hz - 0.105)
    top = (fs["top_z"] - O[2]) / math.cos(r) - 0.012
    k = top / 0.86
    back = [
        (0.000, 0.150, 0.025, 0.035, 0.000, 0.000, 0.36, 2.6),
        (0.035, 0.238, 0.045, 0.052, 0.020, 0.000, 0.36, 3.0),
        (0.170, 0.258, 0.050, 0.058, 0.072, 0.008, 0.31, 3.2),
        (0.320, 0.252, 0.050, 0.058, 0.070, 0.004, 0.31, 3.2),
        (0.440, 0.262, 0.050, 0.058, 0.062, -0.004, 0.40, 3.2),
        (0.530, 0.268, 0.048, 0.056, 0.050, -0.008, 0.52, 3.0),
        (0.600, 0.236, 0.046, 0.054, 0.024, -0.006, 0.54, 2.8),
        (0.650, 0.168, 0.044, 0.050, 0.006, 0.000, 0.50, 2.6),
        (0.700, 0.140, 0.044, 0.048, 0.000, 0.010, 0.56, 2.6),
        (0.770, 0.142, 0.048, 0.048, 0.000, 0.016, 0.60, 2.8),
        (0.830, 0.128, 0.042, 0.044, 0.000, 0.016, 0.52, 2.6),
        (0.860, 0.075, 0.022, 0.026, 0.000, 0.014, 0.30, 2.4),
    ]
    back = [(s * k,) + tuple(rest) for s, *rest in back]
    objs.append(_slab(f"Seat_{tag}_Backrest", O, A, T, N, back, seat_mats, coll))

    # --- base, side trims, rails -------------------------------------------
    fz = C["floor_z"]
    objs.append(_rbox(f"Seat_{tag}_Base", (hx + 0.09, y, fz + 0.075), (0.46, 0.44, 0.13),
                      m["plastic"], coll, bevel=0.03))
    for s in (-1, 1):
        objs.append(_rbox(f"Seat_{tag}_SideTrim_{'L' if s > 0 else 'R'}",
                          (hx + 0.06, y + s * 0.262, hz - 0.165), (0.50, 0.03, 0.11),
                          m["plastic"], coll, bevel=0.014,
                          rot=(0, -math.radians(8), 0)))
    # hinge cover
    objs.append(_cyl(f"Seat_{tag}_Recliner", (hx - 0.19, y - 0.275, hz - 0.11),
                     (hx - 0.19, y + 0.275, hz - 0.11), 0.045, m["plastic"], coll))
    return objs


def _rear_bench(m, coll):
    rs = C["rear_seat"]
    hx, hz = rs["hx"], rs["hz"]
    seat_mats = [m["seat"]]
    objs = []
    ys = np.array([-0.690, -0.672, -0.610, -0.560, -0.500, -0.400, -0.300, -0.250, -0.200, -0.150,
                   -0.085, -0.045, 0.0])
    ys = np.concatenate([ys, -ys[-2::-1]])

    def seat_profile(y):
        """(height add, centre-insert fraction) across the bench: two outer seats + centre."""
        a = abs(y)
        outer = _sstep(0.52, 0.66, a)                         # outer bolster
        inner = _sstep(0.30, 0.19, a) * _sstep(0.04, 0.13, a)  # bolsters beside the middle seat
        bump = 0.045 * outer + 0.030 * inner
        ci = (0.64 * _sstep(0.205, 0.255, a) * _sstep(0.605, 0.555, a)
              + 0.50 * _sstep(0.095, 0.045, a))
        return float(bump), float(ci)

    # cushion: lofted along Y, section in the X/Z plane
    cx = hx + 0.085
    cush = []
    for y in ys:
        bump, ci = seat_profile(y)
        end = abs(y) > 0.68
        w = 0.20 if end else 0.262
        cush.append((y, w, (0.030 if end else 0.052) + bump, 0.045 if end else 0.075,
                     0.0, 0.0, 0.0 if end else ci, 3.0))
    ca = math.radians(9.0)
    T = _v(math.cos(ca), 0, math.sin(ca))
    N = _v(-math.sin(ca), 0, math.cos(ca))
    objs.append(_slab("RearSeat_Cushion", _v(cx, 0, hz - 0.165), _v(0, 1, 0), T, N, cush,
                      seat_mats, coll, nseg=24))

    # backrest
    b0 = _v(hx - 0.170, 0, hz - 0.120)
    b1 = _v(rs["back_x"] + 0.070, 0, rs["top_z"] - 0.065)
    Tb = _unit(b1 - b0)
    half = 0.5 * np.linalg.norm(b1 - b0)
    mid = 0.5 * (b0 + b1)
    Nb = _v(Tb[2], 0, -Tb[0])
    back = []
    for y in ys:
        bump, ci = seat_profile(y)
        end = abs(y) > 0.68
        back.append((y, half * (0.80 if end else 1.0), (0.028 if end else 0.045) + 0.8 * bump,
                     0.035 if end else 0.045, 0.0, 0.0, 0.0 if end else ci, 3.2))
    objs.append(_slab("RearSeat_Backrest", mid, _v(0, 1, 0), Tb, Nb, back, seat_mats, coll,
                      nseg=24))

    # head restraints
    for tag, y, dz, w in (("L", 0.40, 0.0, 0.118), ("R", -0.40, 0.0, 0.118), ("C", 0.0, -0.035, 0.105)):
        O = b1 + _v(0.012, y, -0.035 + dz)
        hr = [
            (0.000, w * 0.55, 0.020, 0.022, 0, 0.0, 0.5, 2.6),
            (0.020, w, 0.040, 0.040, 0, 0.0, 0.62, 3.0),
            (0.085, w, 0.044, 0.040, 0, 0.004, 0.62, 3.0),
            (0.135, w * 0.92, 0.038, 0.036, 0, 0.006, 0.55, 2.8),
            (0.155, w * 0.50, 0.018, 0.020, 0, 0.006, 0.4, 2.4),
        ]
        objs.append(_slab(f"RearSeat_Headrest_{tag}", O, Tb, _v(0, 1, 0), Nb, hr, seat_mats, coll,
                          nseg=20))

    # riser under the bench and the wall behind the backrest
    fz = C["floor_z"]
    objs.append(_rbox("RearSeat_Riser", (hx - 0.11, 0, fz + 0.065), (0.62, 1.40, 0.13),
                      m["carpet"], coll, bevel=0.02))
    return objs


# ---------------------------------------------------------------------------
# dashboard, display, steering wheel
# ---------------------------------------------------------------------------
def _dashboard(m, coll):
    objs = []
    cowl, rear, top = C["cowl_x"], C["dash_rear_x"], C["dash_top_z"]
    hw = 0.700
    # section in the X/Z plane (x, z, plan-sweep weight), counter-clockwise from the cowl
    prof = [
        (cowl - 0.004, top - 0.022, 1.00),
        (cowl - 0.030, top - 0.012, 1.00),
        (cowl - 0.130, top - 0.006, 0.92),
        (cowl - 0.250, top - 0.022, 0.72),
        (rear + 0.070, top - 0.046, 0.50),
        (rear + 0.034, top - 0.058, 0.42),     # rear lip of the dash top
        (rear + 0.022, top - 0.068, 0.40),
        (rear + 0.018, top - 0.100, 0.40),     # fascia
        (rear + 0.022, top - 0.200, 0.40),
        (rear + 0.030, top - 0.228, 0.40),     # knee roll
        (rear + 0.062, top - 0.246, 0.42),
        (rear + 0.072, top - 0.300, 0.42),     # glovebox face
        (rear + 0.090, top - 0.420, 0.45),
        (rear + 0.110, top - 0.450, 0.48),
        (rear + 0.240, top - 0.468, 0.62),
        (cowl - 0.004, top - 0.470, 1.00),
    ]
    prof = np.array(prof)
    ys = np.concatenate([[-hw], np.linspace(-hw + 0.008, hw - 0.008, 23), [hw]])
    rings = []
    for y in ys:
        u = y / hw
        sweep = 0.105 * u * u                       # the cowl follows the windscreen in plan
        end = 0.6 if abs(u) > 0.995 else 1.0
        x = prof[:, 0] - sweep * prof[:, 2]
        z = prof[:, 1].copy()
        # driver-side binnacle swell on the top surface
        swell = 0.012 * math.exp(-((y - C["steering"]["y"]) / 0.22) ** 2)
        z[2:5] += swell * np.array([0.6, 1.0, 0.7])
        cx, cz = x.mean(), z.mean()
        x = cx + (x - cx) * (0.96 if end < 1 else 1.0)
        z = cz + (z - cz) * (0.93 if end < 1 else 1.0)
        rings.append(np.stack([x, np.full_like(x, y), z], axis=1))

    def mat_fn(i, k):
        return 0 if k in (0, 1, 2, 3, 4, 5, 15) else 1

    objs.append(_ring_mesh("Dashboard", rings, [m["black"], m["plastic"]], mat_fn, coll, subsurf=2))

    # decor / interaction bar across the fascia, with an ambient light line
    def band(name, z0, z1, depth, mat, x_off):
        yy = np.linspace(-hw + 0.03, hw - 0.03, 25)
        rr = []
        for y in yy:
            u = y / hw
            xf = rear + 0.022 + x_off - 0.105 * u * u * 0.40
            rr.append([(xf, y, z0), (xf, y, z1), (xf + depth, y, z1), (xf + depth, y, z0)])
        o = _ring_mesh(name, rr, [mat], None, coll, subsurf=0)
        util.shade_smooth(o, 40)
        return o

    objs.append(band("Dash_DecorBar", top - 0.150, top - 0.108, 0.02, m["carbon"], -0.004))
    objs.append(band("Dash_AmbientLine", top - 0.158, top - 0.152, 0.02, m["ambient"], -0.003))

    # air vents (centre + outer)
    for tag, y, w in (("C", -0.02, 0.26), ("L", 0.60, 0.11), ("R", -0.60, 0.11), ("P", -0.37, 0.24)):
        u = y / hw
        objs.append(_rbox(f"Dash_Vent_{tag}", (rear + 0.030 - 0.042 * u * u, y, top - 0.195),
                          (0.02, w, 0.028), m["gloss"], coll, bevel=0.006))

    # ---- curved display: instrument cluster + control display in one glass panel ----
    sy = C["steering"]["y"]
    y0, y1 = sy + 0.215, sy - 0.515
    yy = np.linspace(y0, y1, 25)
    zc, hh, th = top + 0.012, 0.066, 0.009
    def frame(y):
        d = max(0.0, (sy - 0.10) - y)
        x = rear + 0.070 - 0.30 * d * d            # wraps towards the driver
        nrm = _unit(_v(-1.0, -0.60 * d, 0.18))      # screen normal (faces the driver)
        up = _unit(_v(0.18, 0, 1.0))
        return _v(x, y, zc), nrm, up

    rr = []
    bz = 0.008                                      # bezel
    for y in yy:
        c, nrm, up = frame(y)
        e = 0.6 if (y == yy[0] or y == yy[-1]) else 1.0
        h = hh * (0.85 if e < 1 else 1.0)
        rr.append([c + nrm * th + up * h, c + nrm * th + up * (h - bz), c + nrm * th - up * (h - bz),
                   c + nrm * th - up * h, c - nrm * th - up * h, c - nrm * th + up * h])
    disp = _ring_mesh("Dash_CurvedDisplay", rr, [m["screen"], m["gloss"]],
                      lambda i, k: 0 if (k == 1 and 1 <= i < len(yy) - 2) else 1, coll, subsurf=0)
    b = disp.modifiers.new("Bevel", "BEVEL")
    b.width, b.segments, b.limit_method = 0.003, 2, "ANGLE"
    util.shade_smooth(disp, 50)
    objs.append(disp)

    # glowing UI: two gauge arcs in the cluster, a map tile and a status strip in the centre display
    def ui_strip(name, ya, yb, v0, v1, mat, n=12):
        rs = []
        for y in np.linspace(ya, yb, n):
            c, nrm, up = frame(y)
            p = c + nrm * (th + 0.0007)
            rs.append([p + up * v1, p + up * v0, p + up * v0 - nrm * 0.0004, p + up * v1 - nrm * 0.0004])
        o = _ring_mesh(name, rs, [mat], None, coll, subsurf=0)
        util.shade_smooth(o, 40)
        return o

    objs.append(ui_strip("Dash_UI_Map", sy - 0.185, sy - 0.395, -0.046, 0.046, m["ui_map"]))
    objs.append(ui_strip("Dash_UI_Widget", sy - 0.405, sy - 0.495, -0.046, 0.046, m["ui_map"], 6))
    objs.append(ui_strip("Dash_UI_Status", sy - 0.185, sy - 0.495, 0.050, 0.053, m["ui"]))
    c0, nrm0, up0 = frame(sy)
    for tag, dy, mat in (("L", 0.092, m["ui"]), ("R", -0.062, m["ui_red"])):
        cc_ = c0 + nrm0 * (th + 0.0007) + _v(0, dy, 0)
        ang = np.radians(np.linspace(-35, 215, 41))
        rs = []
        for a_ in ang:
            dirv = _v(0, 1, 0) * math.cos(a_) + up0 * math.sin(a_)
            rs.append([cc_ + dirv * 0.046, cc_ + dirv * 0.050, cc_ + dirv * 0.050 - nrm0 * 0.0004,
                       cc_ + dirv * 0.046 - nrm0 * 0.0004])
        o = _ring_mesh(f"Dash_UI_Gauge_{tag}", rs, [mat], None, coll, subsurf=0)
        util.shade_smooth(o, 40)
        objs.append(o)
    # display foot
    objs.append(_rbox("Dash_DisplayFoot", (rear + 0.075, sy - 0.15, top - 0.050),
                      (0.035, 0.52, 0.05), m["plastic"], coll, bevel=0.01))

    # rear-view mirror on the screen header
    objs.append(_rbox("RearViewMirror", (0.335, 0.0, C["roof_z"] - 0.105), (0.03, 0.24, 0.065),
                      m["gloss"], coll, bevel=0.012, rot=(0, math.radians(-12), 0)))
    objs.append(_cyl("RearViewMirror_Stem", (0.36, 0, C["roof_z"] - 0.09), (0.44, 0, C["roof_z"] - 0.035),
                     0.012, m["plastic"], coll))
    return objs


def _steering_wheel(m, coll):
    st = C["steering"]
    rk = math.radians(st["rake_deg"])
    ctr = _v(st["x"], st["y"], st["z"])
    ey = _v(0, 1, 0)
    eu = _v(math.sin(rk), 0, math.cos(rk))        # wheel "up"
    ea = _v(-math.cos(rk), 0, math.sin(rk))       # towards the driver
    R_out = st["diameter"] / 2
    ra, rb = 0.0155, 0.0185                        # rim section (radial, axial)
    R = R_out - ra
    rim_off = 0.028                                # rim sits proud of the spokes
    objs = []

    def rim_point(phi):
        a, b = R * math.cos(phi), R * math.sin(phi)
        lim = -0.80 * R
        if b < lim:                                # flattened bottom
            b = lim + (b - lim) * 0.30
        return a, b

    nu, nv = 96, 16
    rings = []
    for i in range(nu):
        phi = 2 * math.pi * i / nu
        a, b = rim_point(phi)
        a2, b2 = rim_point(phi + 1e-3)
        tx, ty = a2 - a, b2 - b
        ln = math.hypot(tx, ty)
        nx, ny = ty / ln, -tx / ln                 # outward in-plane normal
        grip = 1.0 + 0.10 * math.exp(-((abs(math.cos(phi)) - 0.94) / 0.10) ** 2)  # thumb grips
        ring = []
        for k in range(nv):
            t = 2 * math.pi * k / nv
            ro, ax = ra * grip * math.cos(t), rb * grip * math.sin(t)
            p = ctr + ey * (a + nx * ro) + eu * (b + ny * ro) + ea * (rim_off + ax)
            ring.append(p)
        rings.append(ring)

    def rim_mat(i, k):
        phi = 2 * math.pi * (i + 0.5) / nu
        return 1 if abs(phi - math.pi / 2) < 0.055 else 0

    rim = _ring_mesh("SteeringWheel_Rim", rings, [m["black"], m["red"]], rim_mat, coll,
                     subsurf=0, cap=False, close_u=True)
    objs.append(rim)

    # spokes (slabs running from the hub to the rim)
    def spoke(name, a0, b0, a1, b1, w0, w1, mat):
        p0 = ctr + ey * a0 + eu * b0 + ea * 0.004
        p1 = ctr + ey * a1 + eu * b1 + ea * (rim_off - 0.002)
        A = p1 - p0
        L = np.linalg.norm(A)
        A = A / L
        T = _unit(np.cross(ea, A))
        N = np.cross(A, T)
        sts = [
            (0.0, w0 * 0.8, 0.008, 0.012, 0, 0, 0, 3),
            (0.02, w0, 0.010, 0.014, 0, 0, 0, 3),
            (L * 0.55, 0.5 * (w0 + w1), 0.009, 0.012, 0, 0, 0, 3),
            (L - 0.01, w1, 0.008, 0.010, 0, 0, 0, 3),
            (L + 0.004, w1 * 0.8, 0.006, 0.008, 0, 0, 0, 3),
        ]
        return _slab(name, p0, A, T, N, sts, [mat], coll, nseg=12, subsurf=1,
                     render_levels=2)

    objs.append(spoke("SteeringWheel_Spoke_L", 0.045, -0.006, R - 0.004, -0.012, 0.030, 0.021, m["gloss"]))
    objs.append(spoke("SteeringWheel_Spoke_R", -0.045, -0.006, -(R - 0.004), -0.012, 0.030, 0.021, m["gloss"]))
    objs.append(spoke("SteeringWheel_Spoke_B1", 0.016, -0.045, 0.027, -0.80 * R + 0.004, 0.011, 0.009, m["alu"]))
    objs.append(spoke("SteeringWheel_Spoke_B2", -0.016, -0.045, -0.027, -0.80 * R + 0.004, 0.011, 0.009, m["alu"]))

    # hub pad
    hub = [
        (-0.062, 0.040, 0.012, 0.020, 0, 0, 0, 2.6),
        (-0.050, 0.058, 0.022, 0.034, 0, 0, 0, 3.0),
        (-0.005, 0.072, 0.026, 0.040, 0, 0, 0, 3.2),
        (0.038, 0.066, 0.024, 0.036, 0, 0, 0, 3.0),
        (0.052, 0.044, 0.012, 0.020, 0, 0, 0, 2.6),
    ]
    objs.append(_slab("SteeringWheel_Hub", ctr, eu, ey, ea, hub, [m["black"]], coll,
                      nseg=16, subsurf=2))
    objs.append(_cyl("SteeringWheel_Roundel", ctr + ea * 0.022, ctr + ea * 0.030, 0.021, m["alu"], coll))
    # red M1/M2 buttons
    for s in (-1, 1):
        c = ctr + ey * s * 0.058 + eu * 0.040 + ea * 0.022
        objs.append(_cyl(f"SteeringWheel_M{1 if s > 0 else 2}", c, c + ea * 0.012, 0.010, m["red"], coll, n=20))
    # shift paddles
    for s in (-1, 1):
        c = ctr + ey * s * 0.115 + eu * 0.030 - ea * 0.012
        objs.append(_rbox(f"SteeringWheel_Paddle_{'L' if s > 0 else 'R'}", c, (0.006, 0.075, 0.05),
                          m["carbon"], coll, bevel=0.003, rot=(0, -rk, 0)))
    # column and shroud
    objs.append(_cyl("SteeringColumn", ctr - ea * 0.01, ctr - ea * 0.20, 0.050, m["plastic"], coll, r1=0.062))
    return objs


# ---------------------------------------------------------------------------
# centre console
# ---------------------------------------------------------------------------
def _console(m, coll):
    cc = C["console"]
    hw, tz, fz = cc["width"] / 2, cc["top_z"], C["floor_z"]
    objs = []
    # top height along x (front joins the dash)
    xs = [cc["x0"] + 0.02, cc["x0"], 0.50, 0.40, 0.28, 0.10, -0.10, -0.30, cc["x1"] - 0.04, cc["x1"] - 0.06]
    tops = [tz + 0.17, tz + 0.17, tz + 0.105, tz + 0.045, tz + 0.012, tz, tz, tz, tz, tz - 0.02]
    rings = []
    for i, (x, t) in enumerate(zip(xs, tops)):
        e = 0.8 if i in (0, len(xs) - 1) else 1.0
        w = hw * e
        wb = (hw + 0.035) * e          # the console flares out towards the floor
        rings.append([(x, -wb, fz - 0.01), (x, -wb, fz + 0.15), (x, -w, t - 0.05), (x, -w, t - 0.004),
                      (x, -w + 0.02, t), (x, w - 0.02, t), (x, w, t - 0.004), (x, w, t - 0.05),
                      (x, wb, fz + 0.15), (x, wb, fz - 0.01)])
    body = _ring_mesh("Console_Body", rings, [m["black"], m["plastic"]],
                      lambda i, k: 0 if k in (2, 3, 4, 5, 6) else 1, coll, subsurf=2)
    objs.append(body)

    # gloss control island with selector, iDrive controller and start button
    objs.append(_rbox("Console_ControlPanel", (0.185, 0.0, tz + 0.004), (0.30, 0.165, 0.012),
                      m["gloss"], coll, bevel=0.005))
    objs.append(_rbox("Console_GearSelector", (0.255, 0.035, tz + 0.020), (0.045, 0.032, 0.022),
                      m["gloss"], coll, bevel=0.007))
    objs.append(_cyl("Console_iDrive", (0.125, -0.012, tz + 0.008), (0.125, -0.012, tz + 0.030), 0.029,
                     m["alu"], coll, r1=0.026))
    objs.append(_cyl("Console_StartButton", (0.275, -0.040, tz + 0.008), (0.275, -0.040, tz + 0.016), 0.013,
                     m["red"], coll, n=24))
    for k, x in enumerate((0.075, 0.105, 0.135, 0.165)):
        objs.append(_rbox(f"Console_Button_{k}", (x, 0.050, tz + 0.011), (0.022, 0.03, 0.004),
                          m["plastic"], coll, bevel=0.0015))
    # sloping cup-holder / charging tray cover ahead of it
    objs.append(_rbox("Console_CupholderCover", (0.435, 0.0, tz + 0.070), (0.150, 0.165, 0.010),
                      m["gloss"], coll, bevel=0.004, rot=(0, -math.atan2(0.105, 0.16), 0)))
    # split armrest lid
    arm = [
        (0.000, hw * 0.70, 0.016, 0.014, 0, 0, 0, 3.0),
        (0.020, hw - 0.004, 0.030, 0.022, 0, 0, 0, 3.4),
        (0.170, hw - 0.002, 0.034, 0.022, 0, 0, 0, 3.4),
        (0.320, hw - 0.004, 0.030, 0.022, 0, 0, 0, 3.4),
        (0.340, hw * 0.70, 0.016, 0.014, 0, 0, 0, 3.0),
    ]
    objs.append(_slab("Console_Armrest", _v(cc["x1"] - 0.03, 0, tz + 0.016), _v(1, 0, 0), _v(0, 1, 0),
                      _v(0, 0, 1), arm, [m["orange"]], coll, nseg=20))
    # rear vent panel
    objs.append(_rbox("Console_RearVents", (cc["x1"] - 0.062, 0, tz - 0.12), (0.012, 0.16, 0.10),
                      m["gloss"], coll, bevel=0.004))
    return objs


# ---------------------------------------------------------------------------
# door cards
# ---------------------------------------------------------------------------
def _door_outer_y(x):
    """Outer limit of the trim (below shoulder height) along the cabin."""
    return 0.738 - 0.045 * _sstep(0.25, 0.90, x) - 0.020 * _sstep(-0.70, -1.30, x)


def _door_card(tag, side, x0, x1, m, coll, front):
    fz, bz = C["floor_z"], C["belt_z"]
    n = 13
    xs = np.linspace(x0, x1, n)
    xs = np.concatenate([[x0 + 0.004], xs[1:-1], [x1 - 0.004]]) if x0 > x1 else xs
    rings = []
    L = abs(x1 - x0)
    for i, x in enumerate(xs):
        s = abs(x - x0) / L
        yo = float(_door_outer_y(x))
        yb = min(yo, 0.698)                            # at the belt and above
        arm = float(_sstep(0.10, 0.24, s) * _sstep(0.97, 0.80, s))   # armrest fades at the ends
        pull = 0.006 * arm
        e = 0.5 if i in (0, len(xs) - 1) else 1.0
        tk = 0.034 * e                                 # trim thickness
        # (y inboard offset from the outer skin, z)
        sec = [
            (0.000, fz),
            (0.000, 0.62),
            (0.000, 0.90),
            (yo - yb, bz - 0.004),
            (yo - yb + tk * 0.9, bz - 0.004),
            (yo - yb + tk + 0.004, bz - 0.050),
            (tk + 0.010, 0.840),
            (tk + 0.008 - pull, 0.765),
            (tk + 0.012 + 0.058 * arm, 0.716),
            (tk + 0.016 + 0.066 * arm, 0.690),
            (tk + 0.010 + 0.040 * arm, 0.655),
            (tk + 0.006, 0.610),
            (tk + 0.004, 0.450),
            (tk + 0.018, fz + 0.050),
            (tk + 0.016, fz),
        ]
        rings.append([(x, side * (yo - dy), z) for dy, z in sec])

    def mat_fn(i, k):
        if k in (4, 5, 6):
            return 1      # orange upper roll
        if k in (7, 8, 9):
            return 0      # black leather armrest
        return 2          # plastic

    objs = [_ring_mesh(f"DoorCard_{tag}", rings, [m["black"], m["orange"], m["plastic"]], mat_fn, coll,
                       subsurf=2)]

    # decor strip + ambient line under the shoulder, door pull, speaker grille
    sgn = 1.0 if x1 > x0 else -1.0
    xa, xb = x0 + sgn * 0.14 * L, x0 + sgn * 0.90 * L
    for nm, z0, z1, mat, dy in (("Decor", 0.775, 0.806, m["carbon"], 0.046),
                                ("Ambient", 0.768, 0.773, m["ambient"], 0.047)):
        rr = []
        for x in np.linspace(xa, xb, 9):
            y = side * (float(_door_outer_y(x)) - dy)
            rr.append([(x, y, z0), (x, y, z1), (x, y + side * 0.012, z1), (x, y + side * 0.012, z0)])
        o = _ring_mesh(f"DoorCard_{tag}_{nm}", rr, [mat], None, coll, subsurf=0)
        util.shade_smooth(o, 40)
        objs.append(o)
    xm = x0 + sgn * 0.42 * L
    objs.append(_rbox(f"DoorCard_{tag}_Handle", (xm, side * (float(_door_outer_y(xm)) - 0.055), 0.742),
                      (0.11, 0.012, 0.022), m["alu"], coll, bevel=0.005))
    xsps = x0 + sgn * (0.16 if front else 0.20) * L
    objs.append(_cyl(f"DoorCard_{tag}_Speaker",
                     (xsps, side * (float(_door_outer_y(xsps)) - 0.036), 0.50),
                     (xsps, side * (float(_door_outer_y(xsps)) - 0.046), 0.50), 0.075, m["alu"], coll))
    return objs


# ---------------------------------------------------------------------------
# floor, parcel shelf
# ---------------------------------------------------------------------------
def _floor(m, coll):
    fz = C["floor_z"]
    xs = np.concatenate([np.linspace(C["cowl_x"] - 0.016, 0.70, 6), np.linspace(0.62, -1.26, 20)])
    ys = np.linspace(-0.74, 0.74, 31)
    Pts = np.zeros((len(xs), len(ys), 3))
    for i, x in enumerate(xs):
        ramp = 0.24 * _sstep(0.70, C["cowl_x"] - 0.016, x)            # toe board
        for j, y in enumerate(ys):
            lim = float(_door_outer_y(x)) - 0.006
            yy = float(np.clip(y, -lim, lim))
            tunnel = 0.13 * _sstep(0.19, 0.09, abs(yy))       # transmission tunnel
            Pts[i, j] = (x, yy, fz + max(ramp, tunnel))
    fl = util.grid_object("Floor_Carpet", Pts, coll)
    fl.data.materials.append(m["carpet"])
    sol = fl.modifiers.new("Solidify", "SOLIDIFY")
    sol.thickness = 0.02
    sol.offset = -1.0
    # normals up
    bm = bmesh.new()
    bm.from_mesh(fl.data)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    if sum(f.normal.z for f in bm.faces) < 0:
        bmesh.ops.reverse_faces(bm, faces=bm.faces)
    bm.to_mesh(fl.data)
    bm.free()
    objs = [fl]

    # floor mats (slightly raised, black)
    for tag, x, y, sx in (("FL", 0.45, 0.42, 0.42), ("FR", 0.45, -0.42, 0.42),
                          ("RL", -0.40, 0.42, 0.30), ("RR", -0.40, -0.42, 0.30)):
        objs.append(_rbox(f"FloorMat_{tag}", (x, y, fz + 0.004), (sx, 0.40, 0.008), m["plastic"], coll,
                          bevel=0.003))
    # pedals
    for tag, y, w, h in (("Brake", 0.34, 0.11, 0.06), ("Throttle", 0.21, 0.05, 0.14)):
        objs.append(_rbox(f"Pedal_{tag}", (0.80, y, fz + 0.16), (0.012, w, h), m["alu"], coll,
                          bevel=0.004, rot=(0, math.radians(-35), 0)))
    objs.append(_rbox("Pedal_Footrest", (0.82, 0.60, fz + 0.15), (0.012, 0.08, 0.20), m["alu"], coll,
                      bevel=0.004, rot=(0, math.radians(-40), 0)))
    return objs


def _parcel_shelf(m, coll):
    ps = C["parcel_shelf"]
    xs = np.linspace(ps["x0"] + 0.03, ps["x1"], 10)
    ys = np.linspace(-1, 1, 15)
    Pts = np.zeros((len(xs), len(ys), 3))
    for i, x in enumerate(xs):
        s = (x - xs[0]) / (xs[-1] - xs[0])
        hw = _lerp(0.665, 0.555, s ** 1.3)
        for j, u in enumerate(ys):
            Pts[i, j] = (x + 0.07 * s * u * u, hw * u, ps["z"] + 0.012 * s)
    sh = util.grid_object("ParcelShelf", Pts, coll)
    sh.data.materials.append(m["carpet"])
    sol = sh.modifiers.new("Solidify", "SOLIDIFY")
    sol.thickness = 0.03
    sol.offset = -1.0
    bm = bmesh.new()
    bm.from_mesh(sh.data)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    if sum(f.normal.z for f in bm.faces) < 0:
        bmesh.ops.reverse_faces(bm, faces=bm.faces)
    bm.to_mesh(sh.data)
    bm.free()
    objs = [sh]
    # speaker grilles on the shelf
    for s in (-1, 1):
        objs.append(_cyl(f"ParcelShelf_Speaker_{'L' if s > 0 else 'R'}",
                         (ps["x0"] - 0.22, s * 0.40, ps["z"] + 0.002),
                         (ps["x0"] - 0.22, s * 0.40, ps["z"] + 0.010), 0.075, m["plastic"], coll))
    # bulkhead between the bench and the boot
    objs.append(_rbox("RearBulkhead", (ps["x0"] + 0.012, 0, 0.5 * (C["floor_z"] + ps["z"])),
                      (0.03, 1.36, ps["z"] - C["floor_z"]), m["carpet"], coll, bevel=0.01))
    return objs


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------
def build_interior(collection=None):
    """Build the whole interior in car coordinates. Returns the list of created objects."""
    coll = collection or util.get_collection("Interior")
    m = _mats()
    fs = C["front_seat"]
    objs = []
    objs += _floor(m, coll)
    objs += _front_seat("Driver", fs["y"], m, coll)
    objs += _front_seat("Passenger", -fs["y"], m, coll)
    objs += _rear_bench(m, coll)
    objs += _dashboard(m, coll)
    objs += _steering_wheel(m, coll)
    objs += _console(m, coll)
    objs += _door_card("FL", 1, 0.86, -0.20, m, coll, True)
    objs += _door_card("FR", -1, 0.86, -0.20, m, coll, True)
    objs += _door_card("RL", 1, -0.27, -1.25, m, coll, False)
    objs += _door_card("RR", -1, -0.27, -1.25, m, coll, False)
    objs += _parcel_shelf(m, coll)
    return objs


def stats(objs):
    """(triangle count, bbox min, bbox max, max |y| at/above the belt) after modifiers."""
    dg = bpy.context.evaluated_depsgraph_get()
    tris, lo, hi, ybelt = 0, np.full(3, 1e9), np.full(3, -1e9), 0.0
    for o in objs:
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        me.calc_loop_triangles()
        tris += len(me.loop_triangles)
        co = np.empty(len(me.vertices) * 3, dtype=np.float32)
        me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3).astype(float)
        mw = np.array(o.matrix_world)
        co = co @ mw[:3, :3].T + mw[:3, 3]
        lo, hi = np.minimum(lo, co.min(0)), np.maximum(hi, co.max(0))
        up = co[co[:, 2] >= C["belt_z"] - 1e-4]
        if len(up):
            ybelt = max(ybelt, float(np.abs(up[:, 1]).max()))
        ev.to_mesh_clear()
    return tris, lo, hi, ybelt


def _main():
    out = os.environ.get(
        "M5_INTERIOR_OUT",
        "/tmp/claude-0/-home-user-retrendy/5aa83e46-098e-5875-8c45-c37256300496/scratchpad/interior")
    os.makedirs(out, exist_ok=True)
    util.reset_scene()
    objs = build_interior()
    bpy.context.view_layer.update()
    tris, lo, hi, ybelt = stats(objs)
    print(f"objects {len(objs)}  triangles {tris}")
    print("bbox min", np.round(lo, 3), "max", np.round(hi, 3), " max|y| at/above belt", round(ybelt, 3))
    res, spp = (1200, 760), int(os.environ.get("M5_SPP", "28"))
    util.preview_render(os.path.join(out, "top.png"), (-0.2, 0.0, 6.5), (-0.2, 0.0, 0.6), lens=70,
                        res=res, samples=spp)
    util.preview_render(os.path.join(out, "front34.png"), (3.2, 2.6, 3.0), (-0.1, 0.0, 0.7), lens=60,
                        res=res, samples=spp)
    util.preview_render(os.path.join(out, "side.png"), (-0.2, 6.0, 1.3), (-0.2, 0.0, 0.75), lens=75,
                        res=res, samples=spp)
    util.preview_render(os.path.join(out, "driver.png"), (-0.75, 0.05, 1.22), (0.55, 0.30, 0.90), lens=24,
                        res=res, samples=spp)


if __name__ == "__main__":
    _main()
