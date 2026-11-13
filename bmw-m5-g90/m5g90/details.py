"""Add-on parts: kidney grille internals, lamp internals, mirrors, spoiler, exhaust,
aerial, plates and badges."""
import math

import numpy as np
import bpy
import bmesh
from mathutils import Matrix, Vector
from shapely.geometry import Polygon, box as sbox
from shapely.ops import unary_union

from . import cut, surf, util, geom2d as G, materials as M, params as P
from .features import (CAM_FRONT, CAM_REAR, CAM_SIDE, unproject, photo, mirror_u, TAIL,
                       PLATE_R, EXHAUST)


def frame_from_normal(n, up=(0, 0, 1)):
    """Rotation matrix with local +X = n, local +Z as close to `up` as possible."""
    x = Vector(n).normalized()
    y = Vector(up).cross(x).normalized()
    z = x.cross(y)
    return Matrix((x, y, z)).transposed()


def place(obj, point, normal, sink=0.0, up=(0, 0, 1)):
    r = frame_from_normal(normal, up)
    obj.matrix_world = Matrix.Translation(Vector(point) - Vector(normal) * sink) @ r.to_4x4()
    return obj


def surface_frame(body, cam, pt):
    p = unproject(body, cam, [pt])[0]
    n = body.grad(p[0], p[1], p[2])
    return p, n


def move_to(obj, coll):
    for c in obj.users_collection:
        c.objects.unlink(obj)
    coll.objects.link(obj)
    return obj


def rounded_box(name, center, half, coll, mat=None, levels=3, taper=None):
    """Soft box: cube cage + Subsurf. taper(v) may reshape cage vertices (unit cube coords)."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=2.0)
    bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=1, use_grid_fill=True)
    for v in bm.verts:
        c = Vector(v.co)
        if taper:
            c = Vector(taper(c))
        v.co = Vector((c.x * half[0], c.y * half[1], c.z * half[2])) + Vector(center)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    coll.objects.link(obj)
    mod = obj.modifiers.new("Subsurf", "SUBSURF")
    mod.levels = mod.render_levels = levels
    util.shade_smooth(obj)
    if mat:
        me.materials.append(mat)
    return obj


def tube(name, p0, p1, r_out, r_in, coll, mat, mat_in=None, seg=48):
    """Hollow tube from p0 to p1 (open towards p1) with a rounded lip."""
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    ax = p1 - p0
    L = np.linalg.norm(ax)
    ax /= L
    a = np.cross(ax, [0, 0, 1.0])
    a /= np.linalg.norm(a)
    b = np.cross(ax, a)
    # profile (s along axis, radius)
    lip = 0.5 * (r_out - r_in)
    prof = [(0.0, r_out * 0.92), (0.01, r_out), (L - lip, r_out)]
    for t in np.linspace(0, math.pi, 7)[1:]:
        prof.append((L - lip + lip * math.sin(t), r_in + lip + lip * math.cos(t)))
    prof += [(L * 0.25, r_in), (0.0, r_in * 0.9)]
    th = np.linspace(0, 2 * math.pi, seg, endpoint=False)
    P_ = np.array([[p0 + ax * s + r * (math.cos(t) * a + math.sin(t) * b) for t in th]
                   for s, r in prof])
    obj = util.grid_object(name, P_, coll, close_v=True)
    obj.data.materials.append(mat)
    if mat_in is not None:
        obj.data.materials.append(mat_in)
        n_in = (len(prof) - 2) * seg
        mi = np.zeros(len(obj.data.polygons), np.int32)
        mi[-2 * seg:] = 1
        obj.data.polygons.foreach_set("material_index", mi)
    return obj


# ---------------------------------------------------------------------------
def kidney_grille(body, feat, coll):
    kid = feat.kidney
    black = M.gloss_black()
    halves = []
    for sgn in (1, -1):
        half = kid.intersection(sbox(0.014, 0, 1, 2) if sgn > 0 else sbox(-1, 0, -0.014, 2))
        halves.append(G.rounded(half, 0.02))
    both = unary_union(halves)
    # proud gloss-black frame
    ring = kid.buffer(0.004).difference(G.offset(both, -0.026))
    o = feat.skin("Kidney_Frame", ring, "front", 1, black, offset=0.004, thickness=0.03, inner=0.01,
                  edge=0.005)
    # illuminated contour ("Iconic Glow")
    glow = G.offset(both, -0.0275).difference(G.offset(both, -0.0320))
    feat.skin("Kidney_Glow", glow, "front", 1, M.principled(
        "Emit_Kidney_Glow", color=(1, 1, 1), emission=(0.9, 0.95, 1.0), emission_strength=1.6),
        offset=0.001, thickness=0.006, inner=0.004, edge=0.004)
    # recessed shutter panel with horizontal slats
    inner = G.offset(both, -0.036)
    feat.skin("Kidney_Panel", inner, "front", 1, black, offset=-0.030, thickness=0.004, inner=0.015)
    x0, z0, x1, z1 = inner.bounds
    slats = []
    for zc in np.linspace(z0, z1, 5)[1:-1]:
        slats.append(sbox(-1, zc - 0.006, 1, zc + 0.006))
    slat = inner.buffer(-0.01).intersection(unary_union(slats))
    feat.skin("Kidney_Slats", slat, "front", 1, black, offset=-0.018, thickness=0.012,
              inner=0.006, edge=0.005)
    # centre bridge between the kidneys
    bridge = kid.intersection(sbox(-0.02, 0, 0.02, 2))
    feat.skin("Kidney_Bridge", bridge, "front", 1, black, offset=0.004, thickness=0.03, inner=0.01,
              edge=0.005)


def tail_internals(body, feat):
    red = M.emit_red(14.0)
    for sgn in (1, -1):
        sfx = "L" if sgn > 0 else "R"
        tail = G.rounded(G.polygon([photo(body, CAM_REAR, s) for s in TAIL]), 0.005)
        inner = G.offset(tail, -0.011)
        bars = []
        for za, zb, ya, yb in ((0.934, 0.951, 0.30, 0.80), (0.876, 0.892, 0.30, 0.84)):
            quad = photo(body, CAM_REAR, [(ya, za), (yb, za + 0.012), (yb, zb + 0.012), (ya, zb)])
            bars.append(Polygon(quad).buffer(0))
        bar = inner.intersection(unary_union(bars))
        if sgn < 0:
            bar = mirror_u(bar)
        feat.skin(f"Tail_Bars_{sfx}", bar, "rear", -1, red, offset=-0.010, thickness=0.006,
                  inner=0.006, edge=0.004)


def headlight_internals(body, coll):
    """Projector modules behind the headlight lenses."""
    lens, ring = M.clear_glass(), M.dark_chrome()
    for sgn in (1, -1):
        for i, (ya, za, r) in enumerate(((0.538, 0.688, 0.021), (0.642, 0.706, 0.021))):
            p = unproject(body, CAM_FRONT, [(ya, za)])[0]
            n = body.grad(p[0], p[1], p[2])
            c = p - n * 0.040
            bpy.ops.mesh.primitive_uv_sphere_add(radius=r, segments=32, ring_count=16,
                                                 location=(c[0], sgn * c[1], c[2]))
            o = bpy.context.active_object
            o.name = f"Projector_{'L' if sgn > 0 else 'R'}{i}"
            util.shade_smooth(o)
            o.data.materials.append(lens)
            move_to(o, coll)
            bpy.ops.mesh.primitive_torus_add(major_radius=r * 1.25, minor_radius=r * 0.28,
                                             major_segments=40, minor_segments=12,
                                             location=(c[0] - 0.004, sgn * c[1], c[2]),
                                             rotation=(0, math.pi / 2, 0))
            t = bpy.context.active_object
            t.name = f"Projector_Ring_{'L' if sgn > 0 else 'R'}{i}"
            util.shade_smooth(t)
            t.data.materials.append(ring)
            move_to(t, coll)


def mirrors(coll):
    carbon, black = M.carbon(), M.gloss_black()
    out = []
    for sgn in (1, -1):
        sfx = "L" if sgn > 0 else "R"

        def shape(c):
            # aero wedge: deep rounded nose forwards, flat face rearwards, thinner inboard
            x, y, z = c
            out_ = y * 0.5 + 0.5                       # 0 inboard .. 1 outboard
            zz = z * (0.80 + 0.20 * out_) + 0.10 * (out_ - 0.5)
            xx = x * (0.80 + 0.20 * out_)
            if x > 0:                                    # round the leading face
                xx *= 1.0 - 0.35 * (abs(z) ** 2 + 0.6 * abs(y) ** 2)
            return (xx - 0.10 * z, y, zz)

        h = rounded_box(f"Mirror_{sfx}", (0.470, sgn * 0.975, 1.082), (0.078, sgn * 0.100, 0.058),
                        coll, levels=3, taper=shape)
        me = h.data
        me.materials.append(carbon)
        me.materials.append(black)
        mi = [1 if (p.normal.x < -0.35 or p.normal.z < -0.55) else 0 for p in me.polygons]
        me.polygons.foreach_set("material_index", mi)
        if sgn < 0:
            me.flip_normals()
        V = [(0.4005, sgn * 0.895, 1.040), (0.4005, sgn * 1.055, 1.046),
             (0.4070, sgn * 1.055, 1.128), (0.4070, sgn * 0.895, 1.114)]
        g = util.new_mesh_object(f"Mirror_Glass_{sfx}", V, [(0, 1, 2, 3) if sgn > 0 else (3, 2, 1, 0)],
                                 coll, smooth=False)
        g.data.materials.append(M.chrome())
        st = rounded_box(f"Mirror_Stalk_{sfx}", (0.575, sgn * 0.880, 1.016),
                         (0.060, sgn * 0.055, 0.011), coll, mat=black, levels=2,
                         taper=lambda c: (c[0] - 0.45 * c[1], c[1], c[2] + 0.9 * c[1]))
        if sgn < 0:
            st.data.flip_normals()
        out += [h, g, st]
    return out


def spoiler(body, feat):
    """Carbon lip along the trailing edge of the boot lid."""
    ys = np.linspace(0.0, 0.662, 60)
    te = np.array([float(body.t_rear(y, 1.05)) for y in ys])       # trailing edge x(y)
    back = np.stack([te - 0.004, ys], -1)
    fwd = np.stack([te + 0.062 - 0.03 * (ys / 0.662) ** 4, ys], -1)
    half = np.vstack([fwd, back[::-1]])
    poly = Polygon(np.vstack([half, (half * [1, -1])[::-1]])).buffer(0)
    poly = G.rounded(poly, 0.008)
    feat.skin("Spoiler_Lip", poly, "top", 1, M.carbon(), offset=0.016, thickness=0.017, inner=0.01,
              edge=0.006)


def exhausts(body, feat, coll):
    dchrome = M.principled("Exhaust_Tip", color=(0.25, 0.25, 0.26), metallic=1.0, roughness=0.18)
    inner = M.matte_black()
    pts = []
    for y, z, r in EXHAUST:
        p = unproject(body, CAM_REAR, [(y, z)])[0]
        pts.append((p, r * 1.02))
    for sgn in (1, -1):
        for i, (p, r) in enumerate(pts):
            x_tip = min(pp[0] for pp, _ in pts) - 0.004
            tube(f"Exhaust_{'L' if sgn > 0 else 'R'}{i}", (x_tip + 0.22, sgn * p[1], p[2] + 0.004),
                 (x_tip, sgn * p[1], p[2]), r, r - 0.007, coll, dchrome, inner)


def aerial(body, coll):
    z = float(body.t_gtop(-1.36, 0.0))

    def shape(c):
        x, y, zz = c
        t = (zz * 0.5 + 0.5)
        return (x * (1 - 0.55 * t) - 0.45 * t, y * (1 - 0.6 * t), zz)

    return rounded_box("Aerial_Fin", (-1.375, 0, z + 0.022), (0.085, 0.030, 0.030), coll,
                       mat=M.gloss_black(), levels=3, taper=shape)


def emblems(body, feat, coll):
    from . import emblems as E
    # roundels
    p, n = surface_frame(body, CAM_FRONT, (0.0, 0.792))
    place(move_to(E.roundel(0.082, "Roundel_Bonnet"), coll), p, n, sink=0.0012, up=(-1, 0, 0.2))
    p, n = surface_frame(body, CAM_REAR, (0.0, 1.002))
    place(move_to(E.roundel(0.078, "Roundel_Boot"), coll), p, n, sink=0.0012)
    # M5 badges
    p, n = surface_frame(body, CAM_REAR, (-0.415, 1.020))
    place(move_to(E.m_badge(0.027, "M5_Badge_Boot", style="black"), coll), p, n, sink=0.0003)
    p = unproject(body, CAM_FRONT, [(0.300, 0.622)])[0]
    b = move_to(E.m_badge(0.020, "M5_Badge_Grille", style="black"), coll)
    place(b, (p[0] - 0.014, p[1], p[2]), (1, 0, 0.05))
    # plates
    p = unproject(body, CAM_REAR, [PLATE_R])[0]
    n = body.grad(p[0], p[1], p[2])
    place(move_to(E.license_plate(name="Plate_Rear", seals=2), coll), p, (n[0], 0, n[2]),
          sink=0.001)
    pf = unproject(body, CAM_FRONT, [(0.0, 0.452)])[0]
    place(move_to(E.license_plate(name="Plate_Front", seals=1), coll),
          (pf[0] - 0.008, 0, pf[2] - 0.062), (1, 0, 0.03))
    # plinth behind the front plate + intake cross bar
    bar = rounded_box("Intake_Bar", (pf[0] - 0.055, 0, pf[2] - 0.062), (0.035, 0.44, 0.060), coll,
                      mat=M.satin_black(), levels=2)
    return bar


def intake_internals(body, feat, coll):
    """Honeycomb backing and vanes inside the big lower intake."""
    mesh_mat = bpy.data.materials.get("Intake_Mesh")
    if mesh_mat is None:
        mesh_mat = M.principled("Intake_Mesh", color=(0.01, 0.01, 0.01), roughness=0.5)
        nt = mesh_mat.node_tree
        bsdf = nt.nodes["Principled BSDF"]
        tc = nt.nodes.new("ShaderNodeTexCoord")
        vor = nt.nodes.new("ShaderNodeTexVoronoi")
        vor.feature = "DISTANCE_TO_EDGE"
        vor.inputs["Scale"].default_value = 70.0
        ramp = nt.nodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.elements[0].position = 0.04
        ramp.color_ramp.elements[1].position = 0.10
        ramp.color_ramp.elements[0].color = (0.03, 0.03, 0.03, 1)
        ramp.color_ramp.elements[1].color = (0, 0, 0, 1)
        nt.links.new(tc.outputs["Object"], vor.inputs["Vector"])
        nt.links.new(vor.outputs["Distance"], ramp.inputs["Fac"])
        nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    g = feat.skin("Intake_Mesh", G.offset(feat.intake, -0.030), "front", 1, mesh_mat, offset=-0.105,
                  inner=0.03)
    x = float(body.t_front(0.0, 0.32)) - 0.115
    out = [g]
    for sgn in (1, -1):
        v = rounded_box(f"Intake_Vane_{'L' if sgn > 0 else 'R'}", (x + 0.055, sgn * 0.300, 0.300),
                        (0.050, 0.009, 0.085), coll, mat=M.gloss_black(), levels=2,
                        taper=lambda c, sgn=sgn: (c[0], c[1] + 4.0 * c[2] * sgn, c[2]))
        out.append(v)
    return out


def build_details(body, shell, feat, coll, quality="draft"):
    feat.coll = coll
    kidney_grille(body, feat, coll)
    tail_internals(body, feat)
    headlight_internals(body, coll)
    spoiler(body, feat)
    mirrors(coll)
    exhausts(body, feat, coll)
    aerial(body, coll)
    intake_internals(body, feat, coll)
    emblems(body, feat, coll)
    feat.log("details")
