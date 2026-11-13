"""Procedural emblems and number plates for the BMW M5 (G90) model.

Every public builder returns ONE joined mesh object with material slots, built
to the same convention so it can be dropped onto the body:

* local origin at the centre of the BACK face,
* visible / outward normal along local +X,
* width along local +Y (text reads towards +Y when looked at from +X),
* height along local +Z, real-world metres.

Internally everything is authored in a "design" frame (u right, v up, w out of
the page) and permuted to (x, y, z) = (w, u, v) at the very end.

    roundel(diameter)                 BMW roundel, real geometry
    m_badge(height, style)            ///M5 badge with the three M stripes
    license_plate(text, seals)        EU / German plate in a gloss-black holder
    text_mesh(text, height, depth)    generic bevelled lettering helper

Run ``python3 -m m5g90.emblems [out.png]`` for a preview sheet.
"""
import math
import os

import bpy
import bmesh
import numpy as np

from . import materials as M
from . import util

# ---------------------------------------------------------------------------
# fonts
# ---------------------------------------------------------------------------
_FONT_DIRS = ("/usr/share/fonts/opentype/inter", "/usr/share/fonts/truetype/liberation",
              "/usr/share/fonts/truetype/dejavu")
FONT_SANS_BOLD = "LiberationSans-Bold.ttf"      # roundel letters, 'D' on the plate
FONT_HEAVY = "Inter-Black.otf"                  # M badge
FONT_DISPLAY = "Inter-Bold.otf"                 # default for text_mesh
FONT_PLATE = "DejaVuSansMono-Bold.ttf"          # stand-in for FE-Schrift


def _font_path(name):
    if name is None:
        name = FONT_DISPLAY
    if os.path.isabs(name) and os.path.exists(name):
        return name
    for d in _FONT_DIRS:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None  # falls back to Blender's built-in Bfont


# ---------------------------------------------------------------------------
# emblem specific materials (the common ones come from materials.py)
# ---------------------------------------------------------------------------
def _mat_enamel(name, color, rough=0.12):
    return M.principled(name, color=color, roughness=rough, coat=1.0, coat_roughness=0.02)


def mat_roundel_blue():
    return _mat_enamel("Emblem_Blue", (0.0, 0.14, 0.52))


def mat_roundel_white():
    return _mat_enamel("Emblem_White", (0.82, 0.83, 0.84))


def mat_roundel_black():
    return _mat_enamel("Emblem_Black", (0.004, 0.004, 0.005), rough=0.08)


def mat_m_light_blue():
    return _mat_enamel("M_Stripe_LightBlue", (0.015, 0.36, 0.78))


def mat_m_dark_blue():
    return _mat_enamel("M_Stripe_DarkBlue", (0.008, 0.022, 0.20))


def mat_m_red():
    return _mat_enamel("M_Stripe_Red", (0.72, 0.012, 0.010))


def mat_plate_white():
    return M.principled("Plate_White_Reflective", color=(0.86, 0.86, 0.84), roughness=0.38,
                        coat=0.5, coat_roughness=0.15)


def mat_plate_black():
    return M.principled("Plate_Black", color=(0.006, 0.006, 0.006), roughness=0.32)


def mat_plate_blue():
    return M.principled("Plate_EU_Blue", color=(0.0, 0.035, 0.42), roughness=0.35)


def mat_plate_yellow():
    return M.principled("Plate_EU_Yellow", color=(0.95, 0.72, 0.0), roughness=0.4)


def mat_seal_silver():
    return M.principled("Plate_Seal_Silver", color=(0.72, 0.73, 0.75), metallic=0.6, roughness=0.35)


def mat_seal_amber():
    return M.principled("Plate_Seal_Amber", color=(0.62, 0.40, 0.08), roughness=0.4)


# ---------------------------------------------------------------------------
# low level mesh builder (design frame: u right, v up, w out)
# ---------------------------------------------------------------------------
class _Builder:
    def __init__(self):
        self.bm = bmesh.new()
        self.mats = []

    def mat(self, material):
        if material not in self.mats:
            self.mats.append(material)
        return self.mats.index(material)

    def add_arrays(self, verts, faces, material, front_material=None):
        """Append raw geometry (verts (N,3) in design coords, faces as index lists).

        With ``front_material`` the faces looking straight out (+w) get that
        material, everything else (side walls, bevels) gets ``material``.
        """
        mi = self.mat(material)
        fi = self.mat(front_material) if front_material is not None else mi
        bv = [self.bm.verts.new(tuple(map(float, v))) for v in verts]
        new = []
        for f in faces:
            try:
                face = self.bm.faces.new([bv[i] for i in f])
            except ValueError:
                continue
            face.material_index = mi
            face.smooth = True
            new.append(face)
        if fi != mi:
            for face in new:
                face.normal_update()
                if abs(face.normal.z) > 0.985:
                    face.material_index = fi

    def loft(self, rings, material, cap_start=True, cap_end=True, wrap=False, band_mats=None):
        """Skin closed rings (each (n,3)). ``wrap`` connects the last ring back to the first."""
        mi = self.mat(material)
        n = len(rings[0])
        rv = [[self.bm.verts.new(tuple(map(float, p))) for p in ring] for ring in rings]
        nr = len(rv)
        for i in range(nr if wrap else nr - 1):
            a, b = rv[i], rv[(i + 1) % nr]
            m = mi if band_mats is None else self.mat(band_mats[i])
            for j in range(n):
                k = (j + 1) % n
                f = self.bm.faces.new((a[j], a[k], b[k], b[j]))
                f.material_index = m
                f.smooth = True
        if not wrap:
            if cap_start:
                f = self.bm.faces.new(rv[0][::-1])
                f.material_index = mi if band_mats is None else self.mat(band_mats[0])
            if cap_end:
                f = self.bm.faces.new(rv[-1])
                f.material_index = mi if band_mats is None else self.mat(band_mats[-1])
        return rv

    def prism(self, outline, w0, w1, material, bevel=0.0, top_material=None):
        """Extrude a 2D outline (n,2) from w0 to w1 with an optional top chamfer."""
        o = _ccw(np.asarray(outline, dtype=float))

        def ring(pts, w):
            return np.column_stack([pts, np.full(len(pts), w)])

        rings = [ring(o, w0)]
        mats = [material]
        if bevel > 0:
            rings += [ring(o, w1 - bevel), ring(_inset(o, bevel), w1)]
            mats += [material]
        else:
            rings += [ring(o, w1)]
        mats += [top_material or material]
        self.loft(rings, material, band_mats=mats)

    def finish(self, name, sharp_deg=35.0, recenter=False, collection=None):
        bm = self.bm
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        if recenter and bm.verts:
            co = np.array([v.co[:] for v in bm.verts])
            lo, hi = co.min(axis=0), co.max(axis=0)
            off = ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2])
            for v in bm.verts:
                v.co.x -= off[0]
                v.co.y -= off[1]
                v.co.z -= off[2]
        # design (u, v, w) -> object (x, y, z) = (w, u, v): cyclic, keeps handedness
        for v in bm.verts:
            u, vv, w = v.co
            v.co = (w, u, vv)
        lim = math.radians(sharp_deg)
        for e in bm.edges:
            if len(e.link_faces) == 2:
                e.smooth = e.calc_face_angle(0.0) < lim
        for f in bm.faces:
            f.smooth = True
        mesh = bpy.data.meshes.new(name)
        bm.to_mesh(mesh)
        bm.free()
        for m in self.mats:
            mesh.materials.append(m)
        mesh.update()
        obj = bpy.data.objects.new(name, mesh)
        util.link(obj, collection)
        return obj


def _tri_count(obj):
    return sum(len(p.vertices) - 2 for p in obj.data.polygons)


# ---------------------------------------------------------------------------
# text -> geometry
# ---------------------------------------------------------------------------
def _text_raw(text, font, extrude=0.0, bevel=0.0, resolution=5):
    """Evaluate a Blender text object at size 1. Returns (verts (N,3), faces)."""
    cu = bpy.data.curves.new("_emblem_txt", "FONT")
    cu.body = text
    path = _font_path(font)
    fnt = None
    if path:
        fnt = bpy.data.fonts.load(path, check_existing=True)
        cu.font = fnt
    cu.size = 1.0
    cu.resolution_u = resolution
    cu.fill_mode = "BOTH" if extrude > 0 or bevel > 0 else "FRONT"
    cu.extrude = extrude
    cu.bevel_depth = bevel
    cu.bevel_resolution = 1
    cu.offset = -bevel
    ob = bpy.data.objects.new("_emblem_txt", cu)
    bpy.context.scene.collection.objects.link(ob)
    bpy.context.view_layer.update()
    deps = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(deps))
    verts = np.empty(len(me.vertices) * 3, dtype=np.float32)
    me.vertices.foreach_get("co", verts)
    verts = verts.reshape(-1, 3).astype(np.float64)
    faces = [tuple(p.vertices) for p in me.polygons]
    bpy.data.meshes.remove(me)
    bpy.data.objects.remove(ob)
    bpy.data.curves.remove(cu)
    if fnt is not None and fnt.users == 0:
        bpy.data.fonts.remove(fnt)
    return verts, faces


def _text_geo(text, height, depth, font=None, bevel=None, shear=0.0, width=None,
              max_stretch=None, resolution=5):
    """Bevelled lettering in the design frame.

    The glyph bounding box is scaled so its height equals ``height`` (cap height
    for upper-case text), back face at w = 0, front at w = depth, lower-left of
    the bounding box at (0, 0). ``width`` forces the ink width (non-uniform x
    scale, limited by ``max_stretch``). Returns (verts, faces, ink_width).
    """
    flat, _ = _text_raw(text, font, resolution=1)
    lo, hi = flat.min(axis=0), flat.max(axis=0)
    s = height / max(hi[1] - lo[1], 1e-9)
    if bevel is None:
        bevel = min(depth * 0.25, height * 0.02)
    b = bevel / s
    e = max(depth / s / 2.0 - b, 0.0)
    verts, faces = _text_raw(text, font, extrude=e, bevel=b, resolution=resolution)
    verts[:, 0] -= lo[0]
    verts[:, 1] -= lo[1]
    verts *= s
    verts[:, 2] -= verts[:, 2].min()
    ink_w = (hi[0] - lo[0]) * s
    if width is not None:
        fx = width / ink_w
        if max_stretch is not None:
            fx = min(max(fx, 1.0 / max_stretch), max_stretch)
        verts[:, 0] *= fx
        ink_w *= fx
    if shear:
        verts[:, 0] += shear * verts[:, 1]
    return verts, faces, ink_w


def text_mesh(text, height, depth, font=None, name="Text", italic_shear=0.0, material=None,
              collection=None):
    """Bevelled 3D lettering as a mesh object.

    height: bounding-box height of the glyphs (= cap height for capitals), m.
    depth:  thickness along local +X, m.  font: file name or absolute path
    (searched in the system font folders; default Inter Bold).
    italic_shear: x-shear per unit height (0.3 ~ 17 degrees).
    """
    verts, faces, _ = _text_geo(text, height, depth, font=font, shear=italic_shear)
    b = _Builder()
    b.add_arrays(verts, faces, material or M.chrome())
    return b.finish(name, sharp_deg=30.0, recenter=True, collection=collection)


# ---------------------------------------------------------------------------
# 2D outline helpers
# ---------------------------------------------------------------------------
def _rrect(w, h, r, n=8, cx=0.0, cy=0.0):
    """Rounded rectangle outline, counter-clockwise, 4 * (n + 1) points."""
    r = max(min(r, w / 2 - 1e-6, h / 2 - 1e-6), 1e-6)
    pts = []
    for (sx, sy, a0) in ((1, -1, -90), (1, 1, 0), (-1, 1, 90), (-1, -1, 180)):
        ox, oy = cx + sx * (w / 2 - r), cy + sy * (h / 2 - r)
        for i in range(n + 1):
            a = math.radians(a0 + 90.0 * i / n)
            pts.append((ox + r * math.cos(a), oy + r * math.sin(a)))
    return np.array(pts)


def _ccw(poly):
    """Return the polygon with counter-clockwise winding."""
    x, y = poly[:, 0], poly[:, 1]
    area = np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)
    return poly if area > 0 else poly[::-1].copy()


def _inset(poly, d, limit=3.0):
    """Offset a CCW polygon inwards by d (mitred corners)."""
    e = np.roll(poly, -1, axis=0) - poly
    e /= np.maximum(np.linalg.norm(e, axis=1, keepdims=True), 1e-12)
    n = np.column_stack([-e[:, 1], e[:, 0]])          # inward normal of edge i (i -> i+1)
    n_prev = np.roll(n, 1, axis=0)
    k = 1.0 + np.sum(n * n_prev, axis=1, keepdims=True)
    m = (n + n_prev) / np.maximum(k, 2.0 / limit ** 2)
    return poly + d * m


def _stroke(points, width, limit=2.2):
    """Outline (CCW polygon) of an open polyline drawn with a flat pen of ``width``."""
    p = np.asarray(points, dtype=float)
    t = p[1:] - p[:-1]
    t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-12)
    n = np.column_stack([-t[:, 1], t[:, 0]])
    nv = np.vstack([n[:1], n[:-1] + n[1:], n[-1:]])
    dot = np.vstack([[1.0], np.sum(n[:-1] * n[1:], axis=1, keepdims=True), [1.0]])
    nv[1:-1] /= np.maximum(1.0 + dot[1:-1], 2.0 / limit ** 2)
    left = p + nv * width / 2
    right = p - nv * width / 2
    return _ccw(np.vstack([left, right[::-1]]))


def _arc(cx, cy, r, a0, a1, n=12):
    a = np.radians(np.linspace(a0, a1, n))
    return np.column_stack([cx + r * np.cos(a), cy + r * np.sin(a)])


def _ring3(pts2, w):
    return np.column_stack([pts2, np.full(len(pts2), w)])


def _circle(r, n=48, cx=0.0, cy=0.0):
    a = np.linspace(0, 2 * math.pi, n, endpoint=False)
    return np.column_stack([cx + r * np.cos(a), cy + r * np.sin(a)])


def _star(r_out, cx, cy, r_in_ratio=0.382):
    pts = []
    for i in range(10):
        a = math.radians(90 + 36 * i)
        r = r_out if i % 2 == 0 else r_out * r_in_ratio
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return np.array(pts)


# ---------------------------------------------------------------------------
# BMW roundel
# ---------------------------------------------------------------------------
def roundel(diameter=0.082, name="Roundel", collection=None):
    """BMW roundel (bonnet 82 mm, boot 74 mm, ...). Thickness ~ 6 mm at 82 mm."""
    R = diameter / 2.0
    k = diameter / 0.082
    t_edge = 0.0036 * k
    dome_h = 0.0021 * k
    seg = 144                       # multiple of 4 -> clean quadrant borders

    def dome(r):
        return t_edge + dome_h * (1.0 - (r / R) ** 2)

    chrome, black = M.chrome(), mat_roundel_black()
    blue, white = mat_roundel_blue(), mat_roundel_white()

    r_q = 0.545 * R                 # blue/white field radius
    r_b0 = 0.580 * R                # black ring inner
    r_b1 = 0.925 * R                # black ring outer
    bead = 0.00016 * k
    lip = 0.00042 * k

    # lathe profile: (radius, w, material of the band that STARTS here)
    prof = []
    for r in np.linspace(0.06 * R, r_q, 9):
        prof.append((r, dome(r), "quad"))
    prof[-1] = (r_q, dome(r_q), chrome)
    prof += [
        (r_q + 0.004 * R, dome(r_q) + bead, chrome),
        (r_b0 - 0.004 * R, dome(r_b0) + bead, chrome),
        (r_b0, dome(r_b0), black),
    ]
    for r in np.linspace(r_b0, r_b1, 9)[1:-1]:
        prof.append((r, dome(r), black))
    prof.append((r_b1, dome(r_b1), chrome))
    # outer chrome rim: rise, flat, rounded shoulder, side wall
    prof += [
        (r_b1 + 0.004 * R, dome(r_b1) + lip * 0.75, chrome),
        (r_b1 + 0.012 * R, dome(r_b1) + lip, chrome),
        (0.965 * R, dome(0.965 * R) + lip, chrome),
    ]
    w_top = dome(0.965 * R) + lip
    w_side = t_edge - 0.0012 * k
    for i in range(1, 6):
        a = math.radians(90.0 * i / 5)
        prof.append((0.965 * R + 0.035 * R * math.sin(a),
                     w_side + (w_top - w_side) * math.cos(a), chrome))
    prof.append((R, 0.0, chrome))

    b = _Builder()
    bm = b.bm
    ang = np.linspace(0, 2 * math.pi, seg, endpoint=False)
    cu, sv = np.cos(ang), np.sin(ang)
    rings = []
    for (r, w, _m) in prof:
        rings.append([bm.verts.new((r * cu[j], r * sv[j], w)) for j in range(seg)])

    def quad_mat(j):
        # segment j spans ang[j]..ang[j+1]; quadrant by its mid angle
        mid = (j + 0.5) * 2 * math.pi / seg
        u, v = math.cos(mid), math.sin(mid)
        return blue if (u < 0) == (v > 0) else white   # top-left & bottom-right blue

    for i in range(len(rings) - 1):
        m = prof[i][2]
        for j in range(seg):
            kk = (j + 1) % seg
            f = bm.faces.new((rings[i][j], rings[i][kk], rings[i + 1][kk], rings[i + 1][j]))
            f.material_index = b.mat(quad_mat(j) if m == "quad" else m)
    # centre fan
    c = bm.verts.new((0.0, 0.0, dome(0.0)))
    for j in range(seg):
        kk = (j + 1) % seg
        f = bm.faces.new((c, rings[0][j], rings[0][kk]))
        f.material_index = b.mat(quad_mat(j))
    # back cap
    f = bm.faces.new(rings[-1][::-1])
    f.material_index = b.mat(chrome)

    # thin chrome separators between the quadrants
    hw = 0.007 * R
    for axis in (0, 1):
        srings = []
        for t in np.linspace(-r_q, r_q, 25):
            w0 = dome(abs(t))
            cs = [(t, -hw, w0 - 0.0003 * k), (t, hw, w0 - 0.0003 * k),
                  (t, hw, w0 + 0.00007 * k), (t, -hw, w0 + 0.00007 * k)]
            if axis == 1:
                cs = [(p[1], p[0], p[2]) for p in cs][::-1]
            srings.append(np.array(cs))
        b.loft(srings, chrome)

    # letters B M W bent around the black ring
    r_mid = 0.5 * (r_b0 + r_b1)
    lh = 0.60 * (r_b1 - r_b0)
    ldepth = 0.0006 * k
    for ch, phi0 in (("B", -45.0), ("M", 0.0), ("W", 45.0)):
        verts, faces, ink_w = _text_geo(ch, lh, ldepth, font=FONT_SANS_BOLD,
                                        bevel=0.00008 * k, resolution=4)
        tb = bmesh.new()
        tv = [tb.verts.new(v) for v in verts]
        for fc in faces:
            try:
                tb.faces.new([tv[i] for i in fc])
            except ValueError:
                pass
        # vertical cuts so straight strokes follow the arc after bending
        ncut = 8
        for i in range(1, ncut):
            x = ink_w * i / ncut
            geom = tb.verts[:] + tb.edges[:] + tb.faces[:]
            bmesh.ops.bisect_plane(tb, geom=geom, plane_co=(x, 0, 0), plane_no=(1, 0, 0))
        tb.verts.ensure_lookup_table()
        tb.faces.ensure_lookup_table()
        tb.verts.index_update()
        v2 = np.array([v.co[:] for v in tb.verts])
        f2 = [[v.index for v in fc.verts] for fc in tb.faces]
        tb.free()
        x = v2[:, 0] - ink_w / 2
        y = v2[:, 1] - lh / 2
        rr = r_mid + y
        phi = math.radians(phi0) + x / r_mid
        out = np.column_stack([rr * np.sin(phi), rr * np.cos(phi),
                               t_edge + dome_h * (1 - (rr / R) ** 2) - 0.6 * ldepth + v2[:, 2]])
        b.add_arrays(out, f2, chrome)

    return b.finish(name, sharp_deg=32.0, collection=collection)


# ---------------------------------------------------------------------------
# M5 badge
# ---------------------------------------------------------------------------
def m_badge(height=0.022, name="M5_Badge", style="chrome", text="M5", collection=None):
    """'///M5' badge. ``height`` is the cap height of the lettering.

    style: 'chrome' (bright letters) or 'black' (gloss-black faces with chrome
    edges, as on the G90's grille and boot lid).
    Overall width is about 3.6 x height; thickness ~2.5 mm at 22 mm height.
    """
    h = height
    depth = 0.0025 * h / 0.022
    bev = 0.00035 * h / 0.022
    shear = 0.36
    edge_mat = M.chrome()
    letter_mat = M.gloss_black() if style == "black" else M.chrome()

    b = _Builder()
    x = 0.0
    sw, gap = 0.215 * h, 0.05 * h
    for mat in (mat_m_light_blue(), mat_m_dark_blue(), mat_m_red()):
        outline = np.array([(x, 0.0), (x + sw, 0.0), (x + sw + shear * h, h), (x + shear * h, h)])
        b.prism(outline, 0.0, depth * 0.92, edge_mat, bevel=bev, top_material=mat)
        x += sw + gap
    x += 0.0 * h
    for i, ch in enumerate(text):
        verts, faces, ink_w = _text_geo(ch, h, depth, font=FONT_HEAVY, bevel=bev, shear=shear,
                                        resolution=6)
        verts[:, 0] += x
        b.add_arrays(verts, faces, edge_mat, front_material=letter_mat)
        x += ink_w + 0.11 * h
    return b.finish(name, sharp_deg=30.0, recenter=True, collection=collection)


# ---------------------------------------------------------------------------
# number plate
# ---------------------------------------------------------------------------
def _seal(b, cx, cy, r, w_face, kind):
    """Round registration sticker (flat, a few tenths of a mm of relief)."""
    silver, white, blue, black = mat_seal_silver(), mat_plate_white(), mat_plate_blue(), mat_plate_black()
    w0 = w_face - 0.0002
    if kind == "state":
        b.prism(_circle(r, 48, cx, cy), w0, w_face + 0.00020, silver)
        b.prism(_circle(r * 0.80, 48, cx, cy), w0, w_face + 0.00028, white)
        b.prism(_circle(r * 0.74, 48, cx, cy), w0, w_face + 0.00034, silver)
        # small heraldic shield with blue/white lozenges
        sw_, sh_ = r * 0.78, r * 0.92
        shield = [(-sw_ / 2, sh_ / 2), (-sw_ / 2, -sh_ * 0.12)]
        for i in range(1, 8):
            a = math.pi + math.pi * i / 8
            shield.append((sw_ / 2 * math.cos(a), -sh_ * 0.12 + sh_ * 0.38 * math.sin(a)))
        shield += [(sw_ / 2, -sh_ * 0.12), (sw_ / 2, sh_ / 2)]
        shield = np.array(shield) + (cx, cy)
        b.prism(shield, w0, w_face + 0.00042, white)
        d = sw_ / 4
        for row in range(3):
            for col in range(4):
                if (row + col) % 2:
                    continue
                x0 = cx - sw_ / 2 + col * d
                y0 = cy + sh_ / 2 - (row + 1) * d * 1.15
                loz = np.array([(x0 + d * 0.5, y0), (x0 + d, y0 + d * 0.575),
                                (x0 + d * 0.5, y0 + d * 1.15), (x0, y0 + d * 0.575)])
                b.prism(loz, w0, w_face + 0.00048, blue)
    else:   # periodic-inspection sticker
        amber = mat_seal_amber()
        b.prism(_circle(r, 48, cx, cy), w0, w_face + 0.00020, amber)
        # black marker sector around 12 o'clock
        a = np.radians(np.linspace(60, 120, 9))
        sector = np.vstack([np.column_stack([cx + r * 0.97 * np.cos(a), cy + r * 0.97 * np.sin(a)]),
                            np.column_stack([cx + r * 0.74 * np.cos(a[::-1]),
                                             cy + r * 0.74 * np.sin(a[::-1])])])
        b.prism(sector, w0, w_face + 0.00026, black)
        b.prism(_circle(r * 0.70, 40, cx, cy)[::-1][::-1], w0, w_face + 0.00026, black)
        b.prism(_circle(r * 0.66, 40, cx, cy), w0, w_face + 0.00032, amber)
        verts, faces, ink_w = _text_geo("26", r * 0.52, 0.0003, font=FONT_SANS_BOLD, bevel=0.0,
                                        resolution=3)
        verts[:, 0] += cx - ink_w / 2
        verts[:, 1] += cy - r * 0.26
        verts[:, 2] += w_face + 0.00012
        b.add_arrays(verts, faces, black)


def _fe_glyph(ch, W, H):
    """FE-Schrift-like outline (CCW polygon, box 0..W x 0..H) for the characters of the
    default plate; None for anything else (falls back to the font)."""
    s = 0.125 * H                      # pen width
    h = s / 2
    if ch == "M":
        sm = 0.90 * s
        c, e = 0.50 * H, 0.18 * H
        d = c - e
        return np.array([(0, 0), (sm, 0), (sm, H - d), (W / 2, e), (W - sm, H - d), (W - sm, 0),
                         (W, 0), (W, H), (W - sm, H), (W / 2, c), (sm, H), (0, H)])
    if ch == "E":
        a, m = 0.96 * W, 0.80 * W
        return np.array([(0, 0), (a, 0), (a, s), (s, s), (s, (H - s) / 2), (m, (H - s) / 2),
                         (m, (H + s) / 2), (s, (H + s) / 2), (s, H - s), (a, H - s), (a, H),
                         (0, H)])
    if ch == "1":
        xs = 0.50 * W
        xr = xs + s
        return np.array([(0.14 * W, 0), (W, 0), (W, s), (xr, s), (xr, H), (xs - 0.06 * W, H),
                         (0.04 * W, 0.70 * H), (0.04 * W + 0.62 * s, 0.70 * H - 0.80 * s),
                         (xs, 0.80 * H), (xs, s), (0.14 * W, s)])
    if ch == "7":
        xb = 0.26 * W
        return np.array([(0, H - 2.0 * s), (s, H - 2.0 * s), (s, H - s), (W - 1.30 * s, H - s),
                         (xb, 0), (xb + 1.10 * s, 0), (W, H - 0.85 * s), (W, H), (0, H)])
    if ch == "5":
        x0, x1, y0, y1 = h, W - h, h, H - h
        ym = 0.585 * H
        r = (ym - y0) / 2
        xc = x1 - r
        pts = [(0.93 * W, y1), (x0, y1), (x0, ym)]
        pts += list(_arc(xc, y0 + r, r, 90, -90, 15))
        pts += [(0.02 * W, y0)]
        return _stroke(pts, s)
    if ch == "0":
        x0, x1, y0, y1 = h, W - h, h, H - h
        r = 0.44 * (x1 - x0)
        pts = list(_arc(x1 - r, y1 - r, r, 38, 90, 6))             # top-right, after the slit
        pts += list(_arc(x0 + r, y1 - r, r, 90, 180, 9))
        pts += list(_arc(x0 + r, y0 + r, r, 180, 270, 9))
        pts += list(_arc(x1 - r, y0 + r, r, 270, 360, 9))
        pts += list(_arc(x1 - r, y1 - r, r, 0, 16, 3))              # up to the slit
        return _stroke(pts, s)
    return None


def license_plate(text="M MM 5017E", name="Plate", seals=2, holder=True, collection=None):
    """German EU number plate 520 x 110 mm in a gloss-black holder.

    text: 'CITY LETTERS NUMBERS', blank separated; the seals go after the first
    group. seals: 2 (rear: inspection + state seal) or 1 (front: state seal).
    With the holder the object is 529 x 122.5 x 12 mm; the origin is on the holder's
    back face, behind the centre of the plate itself.
    """
    W, H, T = 0.520, 0.110, 0.003
    r_c = 0.010
    white, black = mat_plate_white(), mat_plate_black()
    b = _Builder()

    w_back = 0.0
    if holder:
        hb, hrim = 0.0065, 0.0118
        side, top, bot = 0.0045, 0.0045, 0.0080
        ow, oh = W + 2 * side, H + top + bot
        ocy = (top - bot) / 2
        iw, ih = W + 0.0012, H + 0.0012
        gb = M.gloss_black()
        rings = [
            _ring3(_rrect(ow - 0.003, oh - 0.003, r_c + 0.004, cy=ocy), 0.0),
            _ring3(_rrect(ow, oh, r_c + 0.005, cy=ocy), 0.0015),
            _ring3(_rrect(ow, oh, r_c + 0.005, cy=ocy), hrim - 0.0018),
            _ring3(_rrect(ow - 0.0012, oh - 0.0012, r_c + 0.0045, cy=ocy), hrim - 0.0005),
            _ring3(_rrect(ow - 0.0036, oh - 0.0036, r_c + 0.0035, cy=ocy), hrim),
            _ring3(_rrect(iw + 0.0030, ih + 0.0030, r_c + 0.0015), hrim),
            _ring3(_rrect(iw + 0.0008, ih + 0.0008, r_c + 0.0005), hrim - 0.0007),
            _ring3(_rrect(iw, ih, r_c), hrim - 0.0020),
            _ring3(_rrect(iw, ih, r_c), hb),
        ]
        b.loft(rings, gb)
        w_back = hb

    w_face = w_back + T
    # plate blank
    b.loft([
        _ring3(_rrect(W, H, r_c), w_back),
        _ring3(_rrect(W, H, r_c), w_face - 0.0005),
        _ring3(_rrect(W - 0.001, H - 0.001, r_c - 0.0005), w_face),
    ], white)

    # embossed black border
    emb = 0.0010
    bo0, bo1 = 0.0030, 0.0068      # inset of the border's outer / inner edge
    ro0, ro1 = r_c - bo0, r_c - bo1
    b.loft([
        _ring3(_rrect(W - 2 * bo0, H - 2 * bo0, ro0), w_face - 0.0002),
        _ring3(_rrect(W - 2 * bo0 - 0.0005, H - 2 * bo0 - 0.0005, ro0), w_face + emb),
        _ring3(_rrect(W - 2 * bo1 + 0.0005, H - 2 * bo1 + 0.0005, ro1), w_face + emb),
        _ring3(_rrect(W - 2 * bo1, H - 2 * bo1, ro1), w_face - 0.0002),
    ], black, wrap=True)

    # blue EU band (printed: almost flush)
    band_w = 0.042
    x0, x1 = -W / 2 + bo1 - 0.0002, -W / 2 + bo1 + band_w
    hh = H / 2 - bo1 + 0.0002
    rb = max(ro1, 0.002)
    pts = [(x1, -hh)]
    for i in range(9):
        a = math.radians(270 - 90 * i / 8)
        pts.append((x0 + rb + rb * math.cos(a), -hh + rb + rb * math.sin(a)))
    for i in range(9):
        a = math.radians(180 - 90 * i / 8)
        pts.append((x0 + rb + rb * math.cos(a), hh - rb + rb * math.sin(a)))
    pts.append((x1, hh))
    b.prism(np.array(pts)[::-1], w_face - 0.0002, w_face + 0.00018, mat_plate_blue())
    bcx = (x0 + x1) / 2
    yellow = mat_plate_yellow()
    for i in range(12):
        a = math.radians(30 * i)
        b.prism(_star(0.0021, bcx + 0.0105 * math.cos(a), 0.021 + 0.0105 * math.sin(a)),
                w_face, w_face + 0.00034, yellow)
    verts, faces, ink_w = _text_geo("D", 0.019, 0.0005, font=FONT_SANS_BOLD, bevel=0.0,
                                    resolution=5)
    verts[:, 0] += bcx - ink_w / 2
    verts[:, 1] += -0.037
    verts[:, 2] += w_face - 0.00012
    b.add_arrays(verts, faces, white)

    # characters ------------------------------------------------------------
    groups = text.split()
    ch_h = 0.075
    ch_w = 0.0390                   # "Mittelschrift" width, needed for 8 characters
    gap = 0.0078
    seal_slot = 0.052
    space = 0.020
    thin = 0.017                    # gap in front of a letter suffix such as the 'E'
    # split a trailing mixed group like '5017E' into digits + suffix without a gap
    items = []                      # ('char', c) | ('seal',) | ('space',)
    for gi, g in enumerate(groups):
        if gi == 1:
            items.append(("seal",))
        elif gi > 1:
            items.append(("space",))
        for ci, c in enumerate(g):
            if ci and c.isalpha() and g[ci - 1].isdigit():
                items.append(("thin",))
            items.append(("char", c))
    glyphs = {}      # char -> ('poly', outline, width) | ('mesh', verts, faces, width)
    for it in items:
        if it[0] == "char" and it[1] not in glyphs:
            c = it[1]
            cw = ch_w * (0.80 if c in "1I" else 1.0)
            poly = _fe_glyph(c, cw, ch_h)
            if poly is not None:
                glyphs[c] = ("poly", poly, cw)
            else:
                v, f, w = _text_geo(c, ch_h, 0.0016, font=FONT_PLATE, bevel=0.00035,
                                    width=cw, max_stretch=1.6, resolution=5)
                glyphs[c] = ("mesh", v, f, w)
    # total run length
    total, prev = 0.0, None
    for it in items:
        if it[0] == "char":
            if prev == "char":
                total += gap
            total += glyphs[it[1]][-1]
        elif it[0] == "seal":
            total += seal_slot
        else:
            total += space if it[0] == "space" else thin
        prev = it[0]
    left = x1 + 0.007
    right = W / 2 - bo1 - 0.006
    avail = right - left
    fx = min(1.0, avail / total)
    cur = left + (avail - total * fx) / 2
    prev = None
    seal_x = None
    for it in items:
        if it[0] == "char":
            if prev == "char":
                cur += gap * fx
            g = glyphs[it[1]]
            w = g[-1]
            if g[0] == "poly":
                o = g[1] * (fx, 1.0) + (cur, -ch_h / 2)
                b.prism(o, w_face - 0.0004, w_face + emb, black, bevel=0.00035)
            else:
                v = g[1].copy()
                v[:, 0] = v[:, 0] * fx + cur
                v[:, 1] += -ch_h / 2
                v[:, 2] += w_face - 0.0006
                b.add_arrays(v, g[2], black)
            cur += w * fx
        elif it[0] == "seal":
            seal_x = cur + seal_slot * fx / 2
            cur += seal_slot * fx
        else:
            cur += (space if it[0] == "space" else thin) * fx
        prev = it[0]

    if seal_x is not None and seals:
        rs = min(0.0215, seal_slot * fx / 2 - 0.0035)
        if seals >= 2:
            _seal(b, seal_x, 0.0232, rs, w_face, "inspection")
            _seal(b, seal_x, -0.0232, rs, w_face, "state")
        else:
            _seal(b, seal_x, -0.0125, min(rs * 1.08, 0.0225), w_face, "state")

    return b.finish(name, sharp_deg=30.0, collection=collection)


# ---------------------------------------------------------------------------
# standalone preview
# ---------------------------------------------------------------------------
def _preview(path=None):
    import sys
    import tempfile
    if path is None:
        path = os.path.join(os.environ.get("M5G90_SCRATCH", tempfile.gettempdir()),
                            "emblems_preview.png")
    util.reset_scene()
    objs = [
        (roundel(0.082, "Roundel_82"), (0.0, -0.20, 0.36)),
        (roundel(0.074, "Roundel_74"), (0.0, -0.08, 0.36)),
        (m_badge(0.022, "M5_Badge_Grille", "chrome"), (0.0, 0.07, 0.375)),
        (m_badge(0.028, "M5_Badge_Rear", "black"), (0.0, 0.07, 0.33)),
        (text_mesh("M5", 0.03, 0.003, name="Text_Demo", italic_shear=0.3), (0.0, 0.20, 0.36)),
        (license_plate(name="Plate_Rear", seals=2), (0.0, 0.0, 0.215)),
        (license_plate(name="Plate_Front", seals=1), (0.0, 0.0, 0.075)),
    ]
    # backing panel in body colour so chrome has something to reflect
    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(-0.001, 0, 0.225),
                                     rotation=(0, math.radians(90), 0))
    panel = bpy.context.active_object
    panel.scale = (0.45, 0.66, 1)
    panel.data.materials.append(M.car_paint())
    for o, loc in objs:
        o.location = loc
        print(f"{o.name:18s} tris={_tri_count(o):6d} dims(m)="
              f"{tuple(round(d, 4) for d in o.dimensions)}")
    util.preview_light_rig(strength=0.45, world=0.18)
    util.preview_render(path, (1.75, 0.10, 0.28), (0.0, 0.0, 0.22), lens=85,
                        res=(1800, 1200), samples=48)
    base, ext = os.path.splitext(path)
    util.preview_render(base + "_closeup" + ext, (0.62, -0.02, 0.40), (0.0, -0.02, 0.355),
                        lens=85, res=(1800, 520), samples=48)
    print("preview:", path)
    return path


if __name__ == "__main__":
    import sys
    _preview(sys.argv[1] if len(sys.argv) > 1 else None)
