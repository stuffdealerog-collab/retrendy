"""Solid-modelling helpers: build the master solid, cutters that follow its surface,
boolean application and analytic normal restoration."""
import numpy as np
import bpy
import bmesh

from . import util, mesher, geom2d as G


# ---------------------------------------------------------------------------
# view planes: a 2D outline (u, v) lives in one of these and is swept along w
# ---------------------------------------------------------------------------
def to3d(view, uv, w):
    uv = np.asarray(uv, float)
    w = np.broadcast_to(np.asarray(w, float), uv.shape[:-1])
    u, v = uv[..., 0], uv[..., 1]
    if view == "side":            # looking along Y: u = x, v = z
        return np.stack([u, w, v], -1)
    if view == "top":             # looking along Z: u = x, v = y
        return np.stack([u, v, w], -1)
    return np.stack([w, u, v], -1)   # front / rear, looking along X: u = y, v = z


# default sweep ranges (outside -> inside) for surface following
RANGES = {
    ("side", +1): (1.25, 0.25), ("side", -1): (-1.25, -0.25),
    ("top", +1): (1.70, 0.45),
    ("front", +1): (2.70, 0.9), ("rear", -1): (-2.95, -1.2),
}


def first_hit(F, view, uv, w_out, w_in, n=160, nb=22):
    """First point where the ray w_out -> w_in enters the solid. NaN where it misses."""
    uv = np.asarray(uv, float)
    ws = np.linspace(w_out, w_in, n)
    idx = np.full(len(uv), -1)
    for i, w in enumerate(ws):
        p = to3d(view, uv, w)
        inside = F(p[:, 0], p[:, 1], p[:, 2]) < 0
        idx = np.where((idx < 0) & inside, i, idx)
    hit = idx > 0
    lo = ws[np.maximum(idx - 1, 0)]          # outside
    hi = ws[np.maximum(idx, 0)]              # inside
    for _ in range(nb):
        mid = 0.5 * (lo + hi)
        p = to3d(view, uv, mid)
        inside = F(p[:, 0], p[:, 1], p[:, 2]) < 0
        hi = np.where(inside, mid, hi)
        lo = np.where(inside, lo, mid)
    w = 0.5 * (lo + hi)
    return np.where(hit, w, np.nan)


# ---------------------------------------------------------------------------
# master solid
# ---------------------------------------------------------------------------
def build_master(body, h, name="Master", bounds=None, spine_x=(-2.0, 1.72), spine_z=0.62,
                 F=None, relax=0):
    from . import params as P
    F = F or body.F
    bounds = bounds or ((P.X_REAR - 0.06, P.X_FRONT + 0.06), (1.08,), (0.08, 1.30))
    v, q = mesher.mesh_half(F, bounds, h, spine_x=spine_x, spine_z=spine_z)
    V, Q = mesher.mirror_full(v, q)
    if relax:
        V = mesher.relax(F, V, Q, iters=relax)
    obj = util.mesh_from_arrays(name, V, Q)
    return obj


# ---------------------------------------------------------------------------
# cutters
# ---------------------------------------------------------------------------
def _solid_from_caps(name, pa, pb, tris, mat=None):
    """Closed solid from two vertex layers sharing one triangulation."""
    n = len(pa)
    faces = [tuple(t) for t in tris] + [tuple(n + i for i in t[::-1]) for t in tris]
    # boundary edges of the triangulation -> side walls
    cnt = {}
    for t in tris:
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            cnt[(a, b)] = cnt.get((a, b), 0) + 1
    for (a, b) in list(cnt):
        if (b, a) not in cnt:
            faces.append((b, a, a + n, b + n))
    obj = util.new_mesh_object(name, np.vstack([pa, pb]), faces, smooth=False)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(obj.data)
    bm.free()
    if mat is not None:
        obj.data.materials.append(mat)
    return obj


def prism(name, poly, view, w0, w1, mat=None, edge=0.02):
    """Straight extrusion of a shapely polygon between w0 and w1 along the view axis."""
    objs = []
    for part in G.simple_parts(poly):
        pts, tris, _ = G.triangulate(part, edge=edge, inner=1e9)
        objs.append(_solid_from_caps(name, to3d(view, pts, w0), to3d(view, pts, w1), tris, mat))
    return util.join(objs, name)


def follow(name, body, poly, view, sign, depth, proud=0.05, edge=0.008, inner=None, mat=None,
           F=None, const_floor=None):
    """Cutter whose floor follows the body surface at `depth` below it.

    view/sign pick the side the outline is projected from (e.g. 'side', +1 = left
    flank).  The lid sits `proud` outside the surface.  Returns a list of solids
    (one per simple part) - they are applied one after another.
    """
    F = F or body.F
    w_out, w_in = RANGES[(view, sign)]
    d = 1.0 if w_out > w_in else -1.0
    objs = []
    for part in G.simple_parts(poly):
        pts, tris, _ = G.triangulate(part, edge=edge, inner=inner)
        w = first_hit(F, view, pts, w_out, w_in)
        if np.all(np.isnan(w)):
            continue
        if np.any(np.isnan(w)):               # outline hangs over the silhouette
            good = ~np.isnan(w)
            from scipy.spatial import cKDTree
            _, j = cKDTree(pts[good]).query(pts[~good])
            w[~good] = w[good][j]
        top = to3d(view, pts, w + d * proud)
        floor_w = (w - d * depth) if const_floor is None else np.full_like(w, const_floor)
        objs.append(_solid_from_caps(name, top, to3d(view, pts, floor_w), tris, mat))
    return objs


def skin(name, body, poly, view, sign, offset=0.0, edge=0.008, inner=None, mat=None, F=None,
         thickness=0.0):
    """Surface patch: the outline projected onto the body, optionally offset along the
    normal and given a real thickness inwards (crisp rim, analytic normals on both faces)."""
    F = F or body.F
    w_out, w_in = RANGES[(view, sign)]
    objs = []
    for part in G.simple_parts(poly):
        pts, tris, _ = G.triangulate(part, edge=edge, inner=inner)
        w = first_hit(F, view, pts, w_out, w_in)
        good = ~np.isnan(w)
        if not good.any():
            continue
        if not good.all():
            from scipy.spatial import cKDTree
            _, j = cKDTree(pts[good]).query(pts[~good])
            w[~good] = w[good][j]
        p = to3d(view, pts, w)
        n = body.grad(p[:, 0], p[:, 1], p[:, 2])
        p = p + n * offset
        tn = np.cross(p[tris[:, 1]] - p[tris[:, 0]], p[tris[:, 2]] - p[tris[:, 0]])
        flip = (tn * n[tris[:, 0]]).sum(1) < 0
        t = np.where(flip[:, None], tris[:, ::-1], tris)
        nv = len(p)
        if not thickness:
            o = util.mesh_from_arrays(name, p, t)
            o.data.normals_split_custom_set_from_vertices(n.astype(np.float32))
        else:
            verts = np.vstack([p, p - n * thickness])
            faces = [tuple(x) for x in t] + [tuple(nv + i for i in x[::-1]) for x in t]
            cnt = set()
            for x in t:
                cnt.update(((x[0], x[1]), (x[1], x[2]), (x[2], x[0])))
            rim = [(b_, a_, a_ + nv, b_ + nv) for (a_, b_) in cnt if (b_, a_) not in cnt]
            o = util.new_mesh_object(name, verts, faces + rim, smooth=True)
            me = o.data
            nt = len(t)
            sharp = np.zeros(len(me.edges), bool)
            ev = np.empty(len(me.edges) * 2, np.int32)
            me.edges.foreach_get("vertices", ev)
            ev = ev.reshape(-1, 2)
            rim_v = np.zeros(2 * nv, bool)
            for q in rim:
                rim_v[list(q)] = True
            same_layer = (ev[:, 0] < nv) == (ev[:, 1] < nv)
            sharp = rim_v[ev[:, 0]] & rim_v[ev[:, 1]] & same_layer
            me.edges.foreach_set("use_edge_sharp", sharp)
            me.update()
            nl = len(me.loops)
            cn = np.empty(nl * 3, np.float32)
            me.corner_normals.foreach_get("vector", cn)
            cn = cn.reshape(-1, 3)
            lv = np.empty(nl, np.int32)
            me.loops.foreach_get("vertex_index", lv)
            n2 = np.vstack([n, -n]).astype(np.float32)
            cap = np.arange(nl) < nt * 6           # loops of the two triangle layers come first
            cn[cap] = n2[lv[cap]]
            me.normals_split_custom_set(cn.tolist())
        if mat is not None:
            o.data.materials.append(mat)
        objs.append(o)
    return util.join(objs, name)


# ---------------------------------------------------------------------------
# booleans
# ---------------------------------------------------------------------------
def boolean(obj, cutters, op="DIFFERENCE", solver="MANIFOLD", keep=False):
    """Apply cutter(s) to obj. Cutter materials are transferred to the cut faces."""
    if cutters is None:
        return obj
    if not isinstance(cutters, (list, tuple)):
        cutters = [cutters]
    for c in cutters:
        if c is None:
            continue
        n0 = len(obj.data.polygons)
        for slv in (solver, "EXACT"):
            mod = obj.modifiers.new("Bool", "BOOLEAN")
            mod.operation = op
            mod.solver = slv
            mod.object = c
            try:
                mod.material_mode = "TRANSFER"
            except Exception:
                pass
            util.set_active(obj)
            bpy.ops.object.modifier_apply(modifier=mod.name)
            if len(obj.data.polygons) != n0 or op != "DIFFERENCE":
                break
        if not keep:
            bpy.data.objects.remove(c, do_unlink=True)
    return obj


def restore_normals(obj, body, tol=2e-4, F=None, grad=None):
    """Analytic normals on the original skin, smooth cut walls, sharp edge in between."""
    F = F or body.F
    grad = grad or body.grad
    me = obj.data
    nv, nl, npoly = len(me.vertices), len(me.loops), len(me.polygons)
    co = np.empty(nv * 3, np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3).astype(np.float64)
    lv = np.empty(nl, np.int32)
    me.loops.foreach_get("vertex_index", lv)
    ls = np.empty(npoly, np.int32)
    lt = np.empty(npoly, np.int32)
    me.polygons.foreach_get("loop_start", ls)
    me.polygons.foreach_get("loop_total", lt)
    cen = np.empty(npoly * 3, np.float32)
    me.polygons.foreach_get("center", cen)
    cen = cen.reshape(-1, 3).astype(np.float64)
    fnorm = np.empty(npoly * 3, np.float32)
    me.polygons.foreach_get("normal", fnorm)
    fnorm = fnorm.reshape(-1, 3)
    on_v = np.abs(F(co[:, 0], co[:, 1], co[:, 2])) < tol
    loop_poly = np.repeat(np.arange(npoly), lt)
    g = grad(co[:, 0], co[:, 1], co[:, 2]).astype(np.float32)
    gc = grad(cen[:, 0], cen[:, 1], cen[:, 2])
    Fc = F(cen[:, 0], cen[:, 1], cen[:, 2])
    align = (fnorm * gc).sum(1)
    # class 2: original skin; class 1: recess floors that run parallel to the skin;
    # class 0: cut walls / cavity
    on_f = np.minimum.reduceat(on_v[lv].astype(np.int8), ls).astype(bool)
    on_f &= (np.abs(Fc) < tol) & (align > 0.5)
    floor = (~on_f) & (align > 0.90) & (np.abs(Fc) < 0.03)
    cls = np.where(on_f, 2, np.where(floor, 1, 0)).astype(np.int8)
    me.polygons.foreach_set("use_smooth", np.ones(npoly, bool))
    attr = me.attributes.get("skin") or me.attributes.new("skin", "BOOLEAN", "FACE")
    attr.data.foreach_set("value", on_f)
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    for e in bm.edges:
        lf = e.link_faces
        if len(lf) == 2:
            a, b = cls[lf[0].index], cls[lf[1].index]
            if a != b:
                e.smooth = False
            elif a == 0:
                e.smooth = e.calc_face_angle(0.0) < 0.6
            else:
                e.smooth = True
    bm.to_mesh(me)
    bm.free()
    me.update()
    cn = np.empty(nl * 3, np.float32)
    me.corner_normals.foreach_get("vector", cn)
    cn = cn.reshape(-1, 3)
    skin_loop = (cls > 0)[loop_poly]
    cn[skin_loop] = g[lv[skin_loop]]
    me.normals_split_custom_set(cn.tolist())
    return on_f
