"""Wheels, tyres and brakes of the BMW M5 (G90).

Front: 285/40 ZR20 on 10.5Jx20, rear: 295/35 ZR21 on 11Jx21, M double-spoke
bicolour rims (five machined V-chevrons over five recessed black spokes),
M carbon-ceramic brakes with gold calipers.

Local wheel frame: the axle is the local Y axis, +Y is the outer face.
Hierarchy per wheel::

    M5_Wheel_FL            (Empty at the wheel centre; rotated 180deg about Z on the right)
      M5_Wheel_FL_Spin     (Empty; rotate about its local Y to spin the wheel)
        tyre, rim, spokes, hub, bolts, cap, brake disc
      caliper, dust shield / upright   (do not rotate)

Mesh datablocks are shared between the left and the right wheel of an axle.

Public API: build_wheel(axle, side, collection=None), build_wheels(collection=None)
"""
import math

import bpy
import bmesh
import numpy as np

from . import params as P
from . import util
from . import materials as M

MM = 0.001
N_GROUPS = 5                    # five V chevrons + five black spokes
V_HALF_ANGLE = math.radians(19.5)   # angular half opening of a chevron at the rim
SPIN_DEG = 111.0                # static pose of the spoke pattern (matches the side photo)


# ---------------------------------------------------------------------------
# materials specific to the wheels
# ---------------------------------------------------------------------------
def _mat_diamond_cut():
    return M.principled("Wheel_DiamondCut", color=(0.86, 0.86, 0.88), metallic=1.0,
                        roughness=0.17, coat=1.0, coat_roughness=0.04)


def _mat_wheel_black():
    return M.principled("Wheel_JetBlack", color=(0.004, 0.004, 0.005), metallic=0.0,
                        roughness=0.10, coat=1.0, coat_roughness=0.03)


def _mat_bolt():
    return M.principled("Wheel_Bolt", color=(0.03, 0.03, 0.032), metallic=1.0, roughness=0.3)


def _mat_roundel_blue():
    return M.principled("Roundel_Blue", color=(0.0, 0.20, 0.62), roughness=0.15, coat=1.0)


def _mat_roundel_white():
    return M.principled("Roundel_White", color=(0.85, 0.85, 0.85), roughness=0.15, coat=1.0)


def _mat_disc_hat():
    return M.principled("Brake_Disc_Hat", color=(0.035, 0.035, 0.038), metallic=1.0, roughness=0.5)


def _mat_disc():
    """Carbon-ceramic friction ring: dark, matt, faintly speckled."""
    name = "Brake_Disc_CarbonCeramic"
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = M.principled(name, color=(0.045, 0.045, 0.047), metallic=0.35, roughness=0.5)
    nt = mat.node_tree
    b = nt.nodes["Principled BSDF"]
    tc = nt.nodes.new("ShaderNodeTexCoord")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 900.0
    noise.inputs["Detail"].default_value = 3.0
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.35
    ramp.color_ramp.elements[0].color = (0.03, 0.03, 0.032, 1)
    ramp.color_ramp.elements[1].position = 0.75
    ramp.color_ramp.elements[1].color = (0.075, 0.075, 0.078, 1)
    nt.links.new(tc.outputs["Object"], noise.inputs["Vector"])
    nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    return mat


def _mat_hole():
    return M.principled("Brake_Disc_Hole", color=(0.002, 0.002, 0.002), roughness=0.9)


def _mat_caliper_logo(i):
    cols = ((0.12, 0.45, 0.85), (0.02, 0.05, 0.30), (0.75, 0.02, 0.02))
    return M.principled("Caliper_Stripe_%d" % i, color=cols[i], roughness=0.3, coat=0.5)


def _mat_tyre(axle):
    """Tyre rubber; the sidewall carries embossed lettering (bump from a packed image)."""
    name = "Rubber_Tyre_%s" % axle
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = M.principled(name, color=(0.011, 0.011, 0.012), roughness=0.72, specular=0.35)
    img = _sidewall_image(axle)
    if img is None:
        return mat
    nt = mat.node_tree
    b = nt.nodes["Principled BSDF"]
    uv = nt.nodes.new("ShaderNodeUVMap")
    uv.uv_map = "UVMap"
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    tex.extension = "REPEAT"
    tex.interpolation = "Cubic"
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.45
    bump.inputs["Distance"].default_value = 0.0008
    # slightly glossier lettering, like moulded text
    rough = nt.nodes.new("ShaderNodeMapRange")
    rough.inputs["From Min"].default_value = 0.0
    rough.inputs["From Max"].default_value = 1.0
    rough.inputs["To Min"].default_value = 0.74
    rough.inputs["To Max"].default_value = 0.60
    nt.links.new(uv.outputs["UV"], tex.inputs["Vector"])
    nt.links.new(tex.outputs["Color"], bump.inputs["Height"])
    nt.links.new(tex.outputs["Color"], rough.inputs["Value"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    nt.links.new(rough.outputs["Result"], b.inputs["Roughness"])
    return mat


SIDEWALL_REPEATS = 3        # how many times the lettering strip wraps around the tyre


def _sidewall_image(axle):
    """Greyscale height map for the sidewall band (text + fine ribs), packed in the .blend."""
    name = "M5_Tyre_Sidewall_%s" % axle
    img = bpy.data.images.get(name)
    if img is not None:
        return img
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageFilter
    except Exception:
        return None
    W, H = 4096, 256
    im = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(im)
    font = small = None
    for path in ("/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            font = ImageFont.truetype(path, 104)
            small = ImageFont.truetype(path, 50)
            break
        except Exception:
            continue
    if font is None:
        font = small = ImageFont.load_default()
    for y in (10, 18, H - 18, H - 10):              # fine concentric ribs framing the band
        d.line([(0, y), (W, y)], fill=140, width=3)
    size = "285/40 ZR20 (108Y) XL" if axle == "F" else "295/35 ZR21 (107Y) XL"
    words = [("M5  SPORT  RADIAL", font, 255), (size, small, 230),
             ("HIGH  PERFORMANCE", font, 255), ("TUBELESS  \u2022  EXTRA LOAD", small, 230)]
    weights = [1.25, 0.75, 1.25, 0.75]
    x0 = 0.0
    for (txt, f, lum), wgt in zip(words, weights):
        slot = W * wgt / sum(weights)
        bb = d.textbbox((0, 0), txt, font=f)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        d.text((x0 + (slot - tw) / 2 - bb[0], (H - th) / 2 - bb[1]), txt, fill=lum, font=f)
        x0 += slot
    im = im.filter(ImageFilter.GaussianBlur(1.3))
    arr = np.asarray(im, dtype=np.float32) / 255.0
    arr = arr[::-1]                       # blender images start at the bottom row
    rgba = np.empty((H, W, 4), dtype=np.float32)
    rgba[..., 0] = rgba[..., 1] = rgba[..., 2] = arr
    rgba[..., 3] = 1.0
    img = bpy.data.images.new(name, W, H, alpha=False, float_buffer=False, is_data=True)
    img.pixels.foreach_set(rgba.ravel())
    img.pack()
    return img


# ---------------------------------------------------------------------------
# low level mesh builders
# ---------------------------------------------------------------------------
class _Builder:
    """Accumulates vertices / faces / material slots for one mesh."""

    def __init__(self):
        self.verts = []
        self.faces = []
        self.mats = []       # material index per face
        self.slots = []      # list of materials
        self.keep = []       # face indices whose winding is authoritative (open decals etc.)
        self.nv = 0

    def slot(self, mat):
        for i, m in enumerate(self.slots):
            if m == mat:
                return i
        self.slots.append(mat)
        return len(self.slots) - 1

    def add(self, verts, faces, mat_idx, keep=False):
        """verts (n,3) array, faces list of index tuples (local), mat_idx int or list.

        keep=True: the winding given is final (not touched by the normal recalculation).
        """
        if keep:
            self.keep.extend(range(len(self.faces), len(self.faces) + len(faces)))
        verts = np.asarray(verts, dtype=np.float64).reshape(-1, 3)
        base = self.nv
        self.verts.append(verts)
        self.nv += len(verts)
        for k, f in enumerate(faces):
            self.faces.append(tuple(int(i) + base for i in f))
            self.mats.append(mat_idx if isinstance(mat_idx, int) else mat_idx[k])

    def mesh(self, name, sharp_deg=35.0, recalc=True):
        me = bpy.data.meshes.new(name)
        v = np.concatenate(self.verts) if self.verts else np.zeros((0, 3))
        me.from_pydata(v.tolist(), [], self.faces)
        me.update()
        for m in self.slots:
            me.materials.append(m)
        me.polygons.foreach_set("material_index", self.mats)
        _finish_mesh(me, sharp_deg, recalc, self.keep)
        return me


def _finish_mesh(me, sharp_deg=35.0, recalc=True, keep=()):
    bm = bmesh.new()
    bm.from_mesh(me)
    if recalc:
        keep = set(keep)
        bmesh.ops.recalc_face_normals(bm, faces=[f for f in bm.faces if f.index not in keep])
    lim = math.radians(sharp_deg)
    for e in bm.edges:
        if len(e.link_faces) == 2:
            e.smooth = e.calc_face_angle(0.0) < lim
    for f in bm.faces:
        f.smooth = True
    bm.to_mesh(me)
    bm.free()
    me.update()


def _lathe(bld, prof, mat_idx, segs=128, closed=True, thetas=None):
    """Revolve the (axial a, radius r) polyline `prof` about the local Y axis.

    mat_idx: int or per-profile-segment list. For outward normals a closed profile
    is traversed clockwise in the (a right, r up) plane; open ones as given.
    """
    prof = np.asarray(prof, dtype=np.float64)
    n = len(prof)
    if closed:
        a, r = prof[:, 0], prof[:, 1]
        area = 0.5 * np.sum(a * np.roll(r, -1) - np.roll(a, -1) * r)
        if area > 0:                     # counter-clockwise -> reverse
            prof = prof[::-1]
            if not isinstance(mat_idx, int):
                mat_idx = list(mat_idx[::-1])
                mat_idx = mat_idx[1:] + mat_idx[:1]
    if thetas is None:
        thetas = np.linspace(0.0, 2 * math.pi, segs, endpoint=False)
    segs = len(thetas)
    c, s = np.cos(thetas), np.sin(thetas)
    V = np.empty((n, segs, 3))
    V[:, :, 0] = prof[:, 1][:, None] * c[None, :]
    V[:, :, 1] = prof[:, 0][:, None]
    V[:, :, 2] = prof[:, 1][:, None] * s[None, :]
    faces, mats = [], []
    nseg = n if closed else n - 1
    for i in range(nseg):
        i1 = (i + 1) % n
        if prof[i, 1] < 1e-9 and prof[i1, 1] < 1e-9:
            continue
        mi = mat_idx if isinstance(mat_idx, int) else mat_idx[i]
        for j in range(segs):
            j1 = (j + 1) % segs
            faces.append((i * segs + j, i1 * segs + j, i1 * segs + j1, i * segs + j1))
            mats.append(mi)
    bld.add(V.reshape(-1, 3), faces, mats)


def _rot_y(pts, ang):
    """Rotate points about local Y so that +X turns towards +Z by `ang`."""
    c, s = math.cos(ang), math.sin(ang)
    out = np.array(pts, dtype=np.float64)
    x, z = out[..., 0].copy(), out[..., 2].copy()
    out[..., 0] = c * x - s * z
    out[..., 2] = s * x + c * z
    return out


def _sweep(bld, path, section_fn, a_face, mat_fn, cap=True, r_max=None):
    """Sweep a cross-section along a 2D path lying in the wheel face.

    path: (n,2) points in the local (X,Z) plane. section_fn(i, t) -> (K,2) array of
    (lateral u, depth d) points; mat_fn(k) -> material index of section segment k.
    The top of the section follows the surface of revolution a = a_face(r)
    (this is what a diamond-turned wheel face is). Corners are mitred.
    """
    path = np.asarray(path, dtype=np.float64)
    n = len(path)
    tang = np.zeros_like(path)
    tang[1:-1] = 0.0
    seg = path[1:] - path[:-1]
    seg /= np.linalg.norm(seg, axis=1)[:, None]
    normals = np.zeros_like(path)
    scale = np.ones(n)
    for i in range(n):
        if i == 0:
            t = seg[0]
        elif i == n - 1:
            t = seg[-1]
        else:
            t = seg[i - 1] + seg[i]
            ln = np.linalg.norm(t)
            t = t / ln
            scale[i] = 1.0 / max(np.dot(t, seg[i]), 0.2)
        normals[i] = (-t[1], t[0])
    cum = np.concatenate([[0], np.cumsum(np.linalg.norm(path[1:] - path[:-1], axis=1))])
    cum /= cum[-1]
    rings = []
    for i in range(n):
        sec = np.asarray(section_fn(i, cum[i]), dtype=np.float64)
        q = path[i][None, :] + normals[i][None, :] * (sec[:, 0] * scale[i])[:, None]
        r = np.linalg.norm(q, axis=1)
        if r_max is not None:                       # trim the sweep on a circle
            over = r > r_max
            q[over] *= (r_max / r[over])[:, None]
            r = np.minimum(r, r_max)
        a = a_face(r) - sec[:, 1]
        rings.append(np.stack([q[:, 0], a, q[:, 1]], axis=1))
    K = len(rings[0])
    V = np.concatenate(rings)
    faces, mats = [], []
    for i in range(n - 1):
        for k in range(K):
            k1 = (k + 1) % K
            faces.append((i * K + k, i * K + k1, (i + 1) * K + k1, (i + 1) * K + k))
            mats.append(mat_fn(k))
    if cap:
        faces.append(tuple(range(K)))
        mats.append(mat_fn(K - 1))
        faces.append(tuple((n - 1) * K + k for k in range(K))[::-1])
        mats.append(mat_fn(K - 1))
    bld.add(V, faces, mats)


def _disc(bld, r0, r1, a, mat_idx, segs=48, sector_mats=None, dome=0.0, r_dome=None):
    """Flat (or slightly domed) annulus / disc at axial position a, facing +Y."""
    th = np.linspace(0, 2 * math.pi, segs, endpoint=False)
    rd = r_dome or r1

    def ring(r):
        aa = a + dome * (1.0 - (r / rd) ** 2)
        return np.stack([r * np.cos(th), np.full(segs, aa), r * np.sin(th)], axis=1)

    faces, mats = [], []
    if r0 <= 1e-9:
        V = np.concatenate([ring(r1), [[0, a + dome, 0]]])
        for j in range(segs):
            faces.append((j, segs, (j + 1) % segs))
            mats.append(mat_idx if sector_mats is None else sector_mats(th[j] + math.pi / segs))
    else:
        V = np.concatenate([ring(r0), ring(r1)])
        for j in range(segs):
            j1 = (j + 1) % segs
            faces.append((j, j1, segs + j1, segs + j))
            mats.append(mat_idx if sector_mats is None else sector_mats(th[j] + math.pi / segs))
    bld.add(V, faces, mats, keep=True)


# ---------------------------------------------------------------------------
# wheel specification
# ---------------------------------------------------------------------------
class _Spec:
    def __init__(self, axle):
        t = P.TYRE_F if axle == "F" else P.TYRE_R
        self.axle = axle
        self.sw = t["width"]                       # section width
        self.Rb = t["rim_in"] * 0.0254 / 2         # bead seat radius
        self.R = P.tyre_radius(t)                  # tyre outer radius
        self.rw = t["rim_width_in"] * 0.0254       # rim width between the flanges
        self.flange = 17.5 * MM
        self.a_out = self.rw / 2 + 11 * MM         # outer face of the outer lip
        self.r_tip = self.Rb + self.flange
        self.r_face = self.Rb - 7 * MM             # where the spokes meet the lip
        self.a_rim = self.a_out - 5.5 * MM         # spoke face height at the rim
        self.dish = (30 if axle == "F" else 37) * MM
        self.r_ring = self.r_tip - 11 * MM         # inner radius of the bright lip ring
        self.r_hub = 77 * MM
        self.r_cap = 28.5 * MM
        self.pcd_r = 56 * MM                       # 5x112
        # brakes (M carbon ceramic)
        if axle == "F":
            self.disc_r, self.disc_ri, self.disc_t, self.disc_a = 0.210, 0.142, 0.038, 0.030
            self.cal_half, self.cal_w = math.radians(34), 0.046
        else:
            self.disc_r, self.disc_ri, self.disc_t, self.disc_a = 0.199, 0.140, 0.030, 0.034
            self.cal_half, self.cal_w = math.radians(24), 0.040

    def a_face(self, r):
        """Axial height of the machined face (a surface of revolution -> concave dish)."""
        r = np.asarray(r, dtype=np.float64)
        s = np.clip((r - 0.030) / (self.r_face - 0.030), 0.0, 1.0)
        a = self.a_rim - self.dish * (1.0 - s) ** 1.35
        # outside r_face the face ramps up to the lip ring
        u = np.clip((r - self.r_face) / (self.r_ring - self.r_face), 0.0, 1.0)
        return a + (self.a_out - 0.3 * MM - self.a_rim) * u * u * (3 - 2 * u)


# ---------------------------------------------------------------------------
# tyre
# ---------------------------------------------------------------------------
def _tyre_profile(sp):
    """Half profile (a>=0) from the tread centre to the bead: arrays a, r, lateral groove depth."""
    R, sw, Rb = sp.R, sp.sw, sp.Rb
    tw = 0.435 * sw                      # half tread width (to where the shoulder starts)
    crown = 4.5 * MM

    def top(a):
        return R - crown * (a / tw) ** 2

    gd = 7.5 * MM                         # main groove depth
    pts = []                              # (a, r, lateral groove depth)
    g1, g2 = 0.105 * sw, 0.31 * sw        # groove centres
    gw = 6.5 * MM                         # half width at the top
    gb = 4.3 * MM                         # half width at the bottom

    def groove(c):
        pts.append((c - gw, top(c - gw), 0))
        pts.append((c - gb, top(c) - gd, 0))
        pts.append((c + gb, top(c) - gd, 0))
        pts.append((c + gw, top(c + gw), 0))

    for a in np.linspace(0, g1 - gw, 4)[:-1]:
        pts.append((a, top(a), 0))
    groove(g1)
    for a in np.linspace(g1 + gw, g2 - gw, 6)[1:-1]:
        pts.append((a, top(a), 0))
    groove(g2)
    # shoulder rib with lateral grooves (depth channel 2)
    ld = 5.0 * MM
    s0 = g2 + gw
    pts.append((s0 + 3.0 * MM, top(s0 + 3 * MM), 0))
    pts.append((s0 + 4.2 * MM, top(s0 + 4.2 * MM), ld))
    for a in np.linspace(s0 + 4.2 * MM, tw, 5)[1:]:
        pts.append((a, top(a), ld))
    # shoulder arc: from (tw, top(tw)) round to the sidewall
    a_sw = sw / 2                          # sidewall max half width
    p0 = np.array([tw, top(tw)])
    p2 = np.array([a_sw - 2.0 * MM, R - 30 * MM])
    p1 = np.array([a_sw - 1.0 * MM, top(tw) - 2.5 * MM])   # control point
    for t in np.linspace(0, 1, 12)[1:]:
        # rational (conic) bezier for a tight, tyre-like shoulder
        w = 1.25
        b0, b1, b2 = (1 - t) ** 2, 2 * t * (1 - t) * w, t ** 2
        p = (b0 * p0 + b1 * p1 + b2 * p2) / (b0 + b1 + b2)
        fade = max(0.0, 1.0 - t / 0.62)
        pts.append((p[0], p[1], ld * fade ** 0.7))
    # sidewall down to the bead (smooth spline through key points)
    r_fl = sp.r_tip
    key = np.array([
        p2,
        [a_sw, R - 0.45 * (R - Rb)],
        [a_sw - 1.2 * MM, R - 0.66 * (R - Rb)],
        [a_sw - 3.0 * MM, r_fl + 19 * MM],
        [sp.a_out + 3.2 * MM, r_fl + 12.5 * MM],      # rim protector rib
        [sp.a_out + 3.6 * MM, r_fl + 8.0 * MM],
        [sp.a_out + 0.5 * MM, r_fl + 3.0 * MM],
        [sp.rw / 2 + 5.0 * MM, r_fl - 1.0 * MM],
        [sp.rw / 2 + 1.0 * MM, r_fl - 8.0 * MM],
    ])
    from scipy.interpolate import PchipInterpolator
    d = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(key, axis=0), axis=1))])
    fa, fr = PchipInterpolator(d, key[:, 0]), PchipInterpolator(d, key[:, 1])
    for u in np.linspace(0, d[-1], 30)[1:]:
        pts.append((float(fa(u)), float(fr(u)), 0))
    arr = np.array(pts)
    # v-range (in arclength) of the lettering band on the sidewall
    band = (R - 0.36 * (R - Rb), r_fl + 24 * MM)
    return arr, band


def _tyre_mesh(sp, name):
    half, band = _tyre_profile(sp)
    # full profile from the inner bead (a<0) over the tread to the outer bead (a>0)
    left = half[::-1].copy()
    left[:, 0] *= -1
    prof = np.concatenate([left, half[1:]])
    a, r, ld = prof[:, 0], prof[:, 1], prof[:, 2]
    n = len(prof)
    # columns: lateral shoulder grooves, slightly variable pitch look via 2 alternating widths
    n_pitch = 72
    pitch = 2 * math.pi / n_pitch
    gwid = 4.6 * MM / sp.R
    eps = 0.8 * MM / sp.R
    cols, deep = [], []
    for k in range(n_pitch):
        t0 = k * pitch
        cols += [t0, t0 + eps, t0 + gwid - eps, t0 + gwid, t0 + gwid + (pitch - gwid) * 0.5]
        deep += [0, 1, 1, 0, 0]
    cols = np.array(cols)
    deep = np.array(deep, dtype=np.float64)
    m = len(cols)
    # skew the tread so that the lateral grooves are slanted (about 14 deg)
    skew = 0.25 / sp.R * np.clip(a, -0.47 * sp.sw, 0.47 * sp.sw)
    TH = cols[None, :] + skew[:, None]
    RR = r[:, None] - ld[:, None] * deep[None, :]
    V = np.empty((n, m, 3))
    V[:, :, 0] = RR * np.cos(TH)
    V[:, :, 1] = a[:, None]
    V[:, :, 2] = RR * np.sin(TH)
    I, J = np.meshgrid(np.arange(n - 1), np.arange(m), indexing="ij")
    J1 = (J + 1) % m
    quads = np.stack([I * m + J, (I + 1) * m + J, (I + 1) * m + J1, I * m + J1], axis=-1)
    quads = quads.reshape(-1, 4)

    me = bpy.data.meshes.new(name)
    me.from_pydata(V.reshape(-1, 3).tolist(), [], quads.tolist())
    me.update()
    # UVs: only the outer and inner sidewall bands map into the lettering image (v in 0..1),
    # everything else is parked on a blank texel row (v = -0.02 -> clamped/blank).
    s = np.concatenate([[0], np.cumsum(np.hypot(np.diff(a), np.diff(r)))])
    v = np.full(n, 0.004)
    for sign in (1, -1):
        sel = (np.sign(a) == sign) & (r <= band[0]) & (r >= band[1])
        if sel.any():
            v[sel] = 0.98 - 0.96 * (band[0] - r[sel]) / (band[0] - band[1])
    uvl = me.uv_layers.new(name="UVMap")
    ucol = np.concatenate([cols, [2 * math.pi]]) / (2 * math.pi)
    uv = np.empty((len(quads), 4, 2))
    Ii, Jj = I.reshape(-1), J.reshape(-1)
    # text reads correctly from outside on the outer sidewall; 2 repeats of the strip
    rep = float(SIDEWALL_REPEATS)
    for c, (di, dj) in enumerate(((0, 0), (1, 0), (1, 1), (0, 1))):
        ii = Ii + di
        uu = ucol[Jj + dj]
        uv[:, c, 0] = np.where(a[ii] > 0, uu, -uu) * rep
        uv[:, c, 1] = v[ii]
    uvl.data.foreach_set("uv", uv.reshape(-1))
    me.materials.append(_mat_tyre(sp.axle))
    _finish_mesh(me, sharp_deg=32.0, recalc=False)
    return me


# ---------------------------------------------------------------------------
# rim (barrel + lip, hub, spokes)
# ---------------------------------------------------------------------------
def _barrel_profile(sp):
    """Closed (a, r) profile of the rim barrel; returns points and 'bright' flags per segment."""
    Rb, rw = sp.Rb, sp.rw
    ao, ai = sp.a_out, -sp.a_out
    rt = sp.r_tip
    hw = rw / 2
    well = Rb - 26 * MM
    wall = Rb - 10 * MM
    pts = [
        # --- outer lip: machined face (bright) --------------------------------
        (hw + 1.0 * MM, rt, 0),                # top of the flange, tyre side
        (ao - 3.2 * MM, rt + 0.6 * MM, 1),     # rounded tip
        (ao - 0.8 * MM, rt - 1.6 * MM, 1),
        (ao, rt - 4.5 * MM, 1),                # outer face (diamond cut ring)
        (ao - 0.3 * MM, sp.r_ring, 1),
        (ao - 0.7 * MM, sp.r_ring - 0.3 * MM, 0),
    ] + [(float(sp.a_face(rr)) - 0.5 * MM, float(rr), 0)   # black ramp down to the spoke face
         for rr in np.linspace(sp.r_ring - 1.5 * MM, sp.r_face, 6)] + [
        # --- inside of the barrel (black) -------------------------------------
        (sp.a_rim - 10 * MM, wall, 0),
        (hw - 40 * MM, wall - 1 * MM, 0),
        (hw - 52 * MM, well + 3 * MM, 0),
        (hw - 58 * MM, well, 0),
        (hw - 112 * MM, well, 0),
        (hw - 120 * MM, well + 4 * MM, 0),
        (hw - 130 * MM, wall, 0),
        (-hw + 10 * MM, wall + 1 * MM, 0),
        (ai + 6 * MM, wall + 4 * MM, 0),
        (ai, Rb, 0),
        (ai, rt - 3 * MM, 0),
        (ai + 3 * MM, rt, 0),
        # --- tyre side (hidden) -----------------------------------------------
        (-hw - 1 * MM, rt, 0),
        (-hw, Rb + 1 * MM, 0),
        (-hw + 22 * MM, Rb, 0),
        (-hw + 30 * MM, Rb - 3 * MM, 0),
        (hw - 128 * MM, Rb - 3 * MM, 0),
        (hw - 118 * MM, well + 9 * MM, 0),
        (hw - 60 * MM, well + 9 * MM, 0),
        (hw - 50 * MM, Rb - 3 * MM, 0),
        (hw - 24 * MM, Rb, 0),
        (hw, Rb + 1 * MM, 0),
    ]
    arr = np.array(pts)
    return arr[:, :2], arr[:, 2].astype(int)


def _v_path(sp, n=14):
    """2D path (local X,Z) of one chevron: rim -> apex -> rim, bisector along +X."""
    r_ap = 93 * MM
    r_end = sp.r_ring + 3.0 * MM
    A = np.array([r_ap, 0.0])
    B1 = r_end * np.array([math.cos(V_HALF_ANGLE), math.sin(V_HALF_ANGLE)])
    B2 = r_end * np.array([math.cos(V_HALF_ANGLE), -math.sin(V_HALF_ANGLE)])
    t = np.linspace(0, 1, n)[:, None]
    arm1 = B1 + (A - B1) * t
    arm2 = A + (B2 - A) * t
    return np.concatenate([arm1, arm2[1:]])


def _rim_mesh(sp, name):
    bld = _Builder()
    bright = bld.slot(_mat_diamond_cut())
    black = bld.slot(_mat_wheel_black())

    # ---- barrel + lip --------------------------------------------------------
    prof, flags = _barrel_profile(sp)
    seg_m = [bright if flags[i] and flags[(i + 1) % len(flags)] else black
             for i in range(len(prof))]
    _lathe(bld, prof, seg_m, segs=160, closed=True)

    # ---- hub -----------------------------------------------------------------
    rr = np.linspace(sp.r_cap + 1.5 * MM, sp.r_hub, 9)
    top = [(float(sp.a_face(r)), float(r)) for r in rr]
    a_edge = float(sp.a_face(sp.r_hub))
    a_in = float(sp.a_face(sp.r_cap))
    top[0] = (top[0][0] + 1.8 * MM, top[0][1])
    top.insert(1, (top[0][0], sp.r_cap + 6.5 * MM))
    top.insert(2, (float(sp.a_face(sp.r_cap + 8.5 * MM)), sp.r_cap + 8.5 * MM))
    top = [t for i, t in enumerate(top) if i < 3 or t[1] > sp.r_cap + 10 * MM]
    hub = ([(a_in - 7 * MM, sp.r_cap), (a_in + 1.3 * MM, sp.r_cap), top[0]] + top[1:] +
           [(a_edge - 2.5 * MM, sp.r_hub + 2.5 * MM), (a_edge - 30 * MM, sp.r_hub + 6 * MM),
            (a_edge - 52 * MM, sp.r_hub - 8 * MM), (a_in - 60 * MM, 0.040),
            (a_in - 7 * MM, 0.040)])
    hb = _Builder()
    hb.slot(_mat_diamond_cut())
    hblack = hb.slot(_mat_wheel_black())
    _lathe(hb, np.array(hub), hblack, segs=120, closed=True)
    hub_me = hb.mesh(name + "_hubtmp", sharp_deg=35)
    hub_me = _cut_lug_holes(sp, hub_me)
    v = np.empty(len(hub_me.vertices) * 3)
    hub_me.vertices.foreach_get("co", v)
    faces = [tuple(p.vertices) for p in hub_me.polygons]
    bld.add(v.reshape(-1, 3), faces, black)
    bpy.data.meshes.remove(hub_me)

    # ---- five machined chevrons ----------------------------------------------
    path = _v_path(sp)
    n_path = len(path)
    D = 27 * MM          # spoke depth
    c = 0.7 * MM         # tiny edge break of the cut face

    def v_section(i, t):
        # arm position 0 at the apex .. 1 at the rim
        s = abs(2 * t - 1)
        w = (12.0 + 2.5 * s) * MM
        if s > 0.86:                                 # foot flaring into the lip
            w += 5 * MM * ((s - 0.86) / 0.14) ** 2
        dr = 3.0 * MM
        return [(-w / 2 + c, 0), (w / 2 - c, 0), (w / 2, c), (w / 2 + dr, D),
                (-w / 2 - dr, D), (-w / 2, c)]

    def v_mat(k):
        return bright if k in (0, 1, 5) else black

    tmp = _Builder()
    tmp.slots = bld.slots
    _sweep(tmp, path, v_section, sp.a_face, v_mat, r_max=sp.r_ring - 0.15 * MM)
    v_verts = np.concatenate(tmp.verts)
    v_faces, v_mats = tmp.faces, tmp.mats

    # ---- five recessed black spokes ------------------------------------------
    rr = np.linspace(66 * MM, sp.r_ring - 2 * MM, 12)
    spath = np.stack([rr, np.zeros_like(rr)], axis=1)
    rec = 5.0 * MM

    def s_section(i, t):
        w = (15 - 4 * t) * MM
        if t < 0.25:                                 # root widening into the hub
            w += 14 * MM * (1 - t / 0.25) ** 2
        ch = 3.2 * MM
        Ds = 30 * MM
        return [(-w / 2 + ch, rec), (w / 2 - ch, rec), (w / 2, rec + ch),
                (w / 2 + 3 * MM, rec + Ds), (-w / 2 - 3 * MM, rec + Ds), (-w / 2, rec + ch)]

    tmp2 = _Builder()
    tmp2.slots = bld.slots
    _sweep(tmp2, spath, s_section, sp.a_face, lambda k: black)
    s_verts = np.concatenate(tmp2.verts)

    # black roots tying each chevron apex into the hub (gives the hub its star shape)
    rr = np.linspace(58 * MM, 104 * MM, 7)
    rpath = np.stack([rr, np.zeros_like(rr)], axis=1)

    def r_section(i, t):
        w = (34 - 16 * t) * MM
        ch = 2.5 * MM
        top = 1.2 * MM + 1.5 * MM * t
        return [(-w / 2 + ch, top), (w / 2 - ch, top), (w / 2, top + ch),
                (w / 2 + 3 * MM, top + 30 * MM), (-w / 2 - 3 * MM, top + 30 * MM),
                (-w / 2, top + ch)]

    tmp3 = _Builder()
    tmp3.slots = bld.slots
    _sweep(tmp3, rpath, r_section, sp.a_face, lambda k: black)
    r_verts = np.concatenate(tmp3.verts)

    for k in range(N_GROUPS):
        ang = 2 * math.pi * k / N_GROUPS
        bld.add(_rot_y(v_verts, ang), v_faces, v_mats)
        bld.add(_rot_y(r_verts, ang), tmp3.faces, tmp3.mats)
        bld.add(_rot_y(s_verts, ang + math.pi / N_GROUPS), tmp2.faces, tmp2.mats)

    return bld.mesh(name, sharp_deg=30)


def _cut_lug_holes(sp, hub_me):
    """Boolean five lug-bolt pockets into the hub mesh; returns a new mesh."""
    obj = bpy.data.objects.new("_hubtmp", hub_me)
    bpy.context.scene.collection.objects.link(obj)
    cb = _Builder()
    ci = cb.slot(_mat_wheel_black())
    a_top = float(sp.a_face(sp.pcd_r)) + 8 * MM
    depth = 38 * MM
    hr = 14.0 * MM
    th = np.linspace(0, 2 * math.pi, 28, endpoint=False)
    for k in range(5):
        ang = 2 * math.pi * (k + 0.5) / 5
        cx, cz = sp.pcd_r * math.cos(ang), sp.pcd_r * math.sin(ang)
        ring_t = np.stack([cx + hr * np.cos(th), np.full(28, a_top), cz + hr * np.sin(th)], 1)
        ring_b = ring_t.copy()
        ring_b[:, 1] = a_top - depth
        faces = [(j, (j + 1) % 28, 28 + (j + 1) % 28, 28 + j) for j in range(28)]
        faces.append(tuple(range(28)))
        faces.append(tuple(range(28, 56))[::-1])
        cb.add(np.concatenate([ring_t, ring_b]), faces, ci)
    cut_me = cb.mesh("_lugcut", sharp_deg=35)
    cut = bpy.data.objects.new("_lugcut", cut_me)
    bpy.context.scene.collection.objects.link(cut)
    mod = obj.modifiers.new("lug", "BOOLEAN")
    mod.operation = "DIFFERENCE"
    mod.object = cut
    mod.solver = "EXACT"
    dg = bpy.context.evaluated_depsgraph_get()
    new_me = bpy.data.meshes.new_from_object(obj.evaluated_get(dg))
    bpy.data.objects.remove(obj)
    bpy.data.objects.remove(cut)
    bpy.data.meshes.remove(cut_me)
    bpy.data.meshes.remove(hub_me)
    return new_me


def _hardware_mesh(sp, name):
    """Lug bolts and valve stem."""
    bld = _Builder()
    bolt = bld.slot(_mat_bolt())
    black = bld.slot(M.satin_black())

    # bolts: hexagonal heads with a collar, sitting at the bottom of the pockets
    a_seat = float(sp.a_face(sp.pcd_r)) + 8 * MM - 38 * MM
    for k in range(5):
        ang = 2 * math.pi * (k + 0.5) / 5
        cx, cz = sp.pcd_r * math.cos(ang), sp.pcd_r * math.sin(ang)
        th6 = np.linspace(0, 2 * math.pi, 6, endpoint=False) + ang
        r6 = 9.8 * MM

        def ring(rad, a, th=th6):
            return np.stack([cx + rad * np.cos(th), np.full(len(th), a), cz + rad * np.sin(th)], 1)

        rings = [ring(r6, a_seat), ring(r6, a_seat + 15 * MM), ring(r6 * 0.82, a_seat + 17 * MM)]
        V = np.concatenate(rings)
        faces = []
        for i in range(2):
            for j in range(6):
                j1 = (j + 1) % 6
                faces.append((i * 6 + j, i * 6 + j1, (i + 1) * 6 + j1, (i + 1) * 6 + j))
        faces.append(tuple(range(12, 18)))
        bld.add(V, faces, bolt)
        # collar
        th = np.linspace(0, 2 * math.pi, 20, endpoint=False)
        V = np.concatenate([ring(12.6 * MM, a_seat, th), ring(12.6 * MM, a_seat + 3 * MM, th),
                            ring(9.0 * MM, a_seat + 3 * MM, th)])
        faces = []
        for i in range(2):
            for j in range(20):
                j1 = (j + 1) % 20
                faces.append((i * 20 + j, i * 20 + j1, (i + 1) * 20 + j1, (i + 1) * 20 + j))
        bld.add(V, faces, bolt)

    # valve stem in one of the chevron windows
    ang = math.radians(8.0)
    er = np.array([math.cos(ang), 0.0, math.sin(ang)])
    et = np.array([-math.sin(ang), 0.0, math.cos(ang)])
    ax = np.array([0.0, 1.0, 0.0])
    base = er * (sp.Rb - 10.5 * MM) + ax * (sp.a_rim - 22 * MM)
    d = (-0.80 * er + 0.60 * ax)                # stem axis: inwards and outwards-facing
    th = np.linspace(0, 2 * math.pi, 14, endpoint=False)
    u = et
    w_ = np.cross(d, u)
    stations = [(0.0, 6.5), (4.0, 6.5), (5.0, 4.2), (20.0, 4.0), (20.0, 5.0), (31.0, 5.0),
                (32.5, 3.8)]
    rings = [base + d * (l * MM) + (rad * MM) * (np.cos(th)[:, None] * u + np.sin(th)[:, None] * w_)
             for l, rad in stations]
    V = np.concatenate(rings)
    faces = []
    for i in range(len(rings) - 1):
        for j in range(14):
            j1 = (j + 1) % 14
            faces.append((i * 14 + j, i * 14 + j1, (i + 1) * 14 + j1, (i + 1) * 14 + j))
    faces.append(tuple(range((len(rings) - 1) * 14, len(rings) * 14)))
    bld.add(V, faces, [bolt if i < 3 * 14 else black for i in range(len(faces))])
    me = bld.mesh(name, sharp_deg=30)
    return me


def _letter_mesh(ch, height):
    """Flat mesh of one glyph (Blender's built-in font), centred, cap height `height`."""
    cu = bpy.data.curves.new("_glyph", "FONT")
    cu.body = ch
    cu.align_x = "CENTER"
    cu.size = 1.0
    ob = bpy.data.objects.new("_glyph", cu)
    bpy.context.scene.collection.objects.link(ob)
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
    bpy.data.objects.remove(ob)
    bpy.data.curves.remove(cu)
    v = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("co", v)
    v = v.reshape(-1, 3)[:, :2].copy()
    faces = [tuple(p.vertices) for p in me.polygons]
    bpy.data.meshes.remove(me)
    if len(v) == 0:
        return v, faces
    lo, hi = v.min(0), v.max(0)
    v -= (lo + hi) / 2
    v *= height / (hi[1] - lo[1])
    return v, faces


def _cap_mesh(sp, name):
    """Centre cap with the BMW roundel (kept upright: it is not parented to the spin empty)."""
    bld = _Builder()
    black = bld.slot(M.principled("Roundel_Black", color=(0.003, 0.003, 0.003), roughness=0.25))
    blue = bld.slot(_mat_roundel_blue())
    white = bld.slot(_mat_roundel_white())
    chrome = bld.slot(M.chrome())
    # black body, chrome bezel, black ring, blue/white quadrants
    a0 = float(sp.a_face(sp.r_cap)) + 0.8 * MM
    rc = sp.r_cap - 0.4 * MM
    cap_prof = [(a0 - 8 * MM, rc), (a0 + 1.6 * MM, rc), (a0 + 2.6 * MM, rc - 1.2 * MM)]
    _lathe(bld, np.array(cap_prof), black, segs=64, closed=False)
    bld.keep.extend(range(len(bld.faces)))
    a_f = a0 + 2.6 * MM
    dome = 1.4 * MM
    r_bez = rc - 1.2 * MM
    r_ring = r_bez - 1.3 * MM
    r_quad = r_ring * 0.62

    def quad_mat(theta):
        q = int((theta % (2 * math.pi)) // (math.pi / 2))
        return blue if q in (0, 2) else white     # blue: top-left as seen from outside

    _disc(bld, r_ring, r_bez, a_f, chrome, segs=64, dome=dome, r_dome=r_bez)
    _disc(bld, r_quad + 0.5 * MM, r_ring, a_f, black, segs=64, dome=dome, r_dome=r_bez)
    _disc(bld, r_quad, r_quad + 0.5 * MM, a_f, chrome, segs=64, dome=dome, r_dome=r_bez)
    _disc(bld, 0.0, r_quad, a_f, blue, segs=64, sector_mats=quad_mat, dome=dome, r_dome=r_bez)
    # BMW lettering on the black ring
    r_txt = (r_quad + r_ring) / 2 + 0.2 * MM
    h_txt = (r_ring - r_quad) * 0.56
    for ch, deg in (("B", 45.0), ("M", 90.0), ("W", 135.0)):
        v2, faces = _letter_mesh(ch, h_txt)
        if not len(v2):
            continue
        t = math.radians(deg)
        er = np.array([math.cos(t), 0.0, math.sin(t)])     # glyph "up"
        et = np.array([-math.sin(t), 0.0, math.cos(t)])    # glyph "right" as seen from outside
        ctr = er * r_txt
        aa = a_f + dome * (1.0 - (r_txt / r_bez) ** 2) + 0.12 * MM
        V = ctr[None, :] + v2[:, :1] * et[None, :] + v2[:, 1:2] * er[None, :]
        V[:, 1] = aa
        bld.add(V, faces, white, keep=True)
    return bld.mesh(name, sharp_deg=30)


# ---------------------------------------------------------------------------
# brakes
# ---------------------------------------------------------------------------
def _disc_mesh(sp, name):
    bld = _Builder()
    disc = bld.slot(_mat_disc())
    hat = bld.slot(_mat_disc_hat())
    hole = bld.slot(_mat_hole())
    ro, ri, t, ac = sp.disc_r, sp.disc_ri, sp.disc_t, sp.disc_a
    af, ab = ac + t / 2, ac - t / 2
    ch = 1.2 * MM
    # friction ring
    ring = [(af, ri), (af, ro - ch), (af - ch, ro), (ab + ch, ro), (ab, ro - ch), (ab, ri)]
    _lathe(bld, np.array(ring), disc, segs=128, closed=True)
    # vent slots on the rim of the ring (dark band)
    _lathe(bld, np.array([(af - 9 * MM, ro + 0.2 * MM), (ab + 9 * MM, ro + 0.2 * MM)]), hole,
           segs=64, closed=False)
    # bell / hat
    a_h = af + 30 * MM
    hatp = [(af - 6 * MM, ri + 4 * MM), (af + 1 * MM, ri + 4 * MM), (af + 3 * MM, ri - 2 * MM),
            (af + 8 * MM, ri - 30 * MM), (a_h - 4 * MM, 0.086), (a_h, 0.082), (a_h, 0.040),
            (a_h - 8 * MM, 0.040), (af - 6 * MM, 0.060)]
    _lathe(bld, np.array(hatp), hat, segs=96, closed=True)
    # floating-mount bobbins around the bell
    nb = 12
    th = np.linspace(0, 2 * math.pi, 10, endpoint=False)
    for k in range(nb):
        ang = 2 * math.pi * k / nb
        r0 = ri + 9 * MM
        cx, cz = r0 * math.cos(ang), r0 * math.sin(ang)
        rad = 5.5 * MM
        V = np.concatenate([
            np.stack([cx + rad * np.cos(th), np.full(10, af + 0.2 * MM), cz + rad * np.sin(th)], 1),
            np.stack([cx + rad * np.cos(th), np.full(10, af + 3.2 * MM), cz + rad * np.sin(th)], 1)])
        faces = [(j, (j + 1) % 10, 10 + (j + 1) % 10, 10 + j) for j in range(10)]
        faces.append(tuple(range(10, 20)))
        bld.add(V, faces, hat)
    # cross-drilled holes (decals, slightly proud of the outer face)
    nrow = 40
    th8 = np.linspace(0, 2 * math.pi, 8, endpoint=False)
    band = ro - ri - 26 * MM
    for k in range(nrow):
        for m in range(4):
            f = m / 3.0
            rr = ri + 17 * MM + band * f
            ang = 2 * math.pi * k / nrow + 0.20 * f + (0.5 * 2 * math.pi / nrow if m % 2 else 0)
            cx, cz = rr * math.cos(ang), rr * math.sin(ang)
            V = np.stack([cx + 1.9 * MM * np.cos(th8), np.full(8, af + 0.25 * MM),
                          cz + 1.9 * MM * np.sin(th8)], 1)
            bld.add(V, [tuple(range(8))[::-1]], hole, keep=True)
    return bld.mesh(name, sharp_deg=30)


def _bent_box(th, rs, az, r_fn=None):
    """Surface quads of a block defined on a (theta, r, a) lattice, bent around the axle.

    th, rs, az: 1D coordinate lists. r_fn(theta, r, a) -> optional remap of r.
    Returns verts (n,3), faces. Meant to be smoothed with a Subsurf modifier.
    """
    nt, nr, na = len(th), len(rs), len(az)
    idx = {}
    verts = []

    def vid(i, j, k):
        key = (i, j, k)
        if key not in idx:
            t, r, a = th[i], rs[j], az[k]
            if r_fn is not None:
                r, a = r_fn(t, r, a, i, j, k)
            idx[key] = len(verts)
            verts.append((r * math.cos(t), a, r * math.sin(t)))
        return idx[key]

    faces = []
    for j in range(nr - 1):
        for k in range(na - 1):
            faces.append((vid(0, j, k), vid(0, j + 1, k), vid(0, j + 1, k + 1), vid(0, j, k + 1)))
            e = nt - 1
            faces.append((vid(e, j, k), vid(e, j, k + 1), vid(e, j + 1, k + 1), vid(e, j + 1, k)))
    for i in range(nt - 1):
        for k in range(na - 1):
            faces.append((vid(i, 0, k), vid(i, 0, k + 1), vid(i + 1, 0, k + 1), vid(i + 1, 0, k)))
            e = nr - 1
            faces.append((vid(i, e, k), vid(i + 1, e, k), vid(i + 1, e, k + 1), vid(i, e, k + 1)))
    for i in range(nt - 1):
        for j in range(nr - 1):
            faces.append((vid(i, j, 0), vid(i + 1, j, 0), vid(i + 1, j + 1, 0), vid(i, j + 1, 0)))
            e = na - 1
            faces.append((vid(i, j, e), vid(i, j + 1, e), vid(i + 1, j + 1, e), vid(i + 1, j, e)))
    return np.array(verts), faces


def _support(lo, hi, n_mid=1, m=0.12):
    """Lattice coordinates with support loops near both ends (controls subsurf roundness)."""
    d = hi - lo
    mid = [lo + d * (i + 1) / (n_mid + 1) for i in range(n_mid)]
    return [lo, lo + d * m] + mid + [hi - d * m, hi]


def _caliper_mesh(sp, name):
    """Fixed caliper centred on theta = 0 (local +X). Subsurf cage."""
    bld = _Builder()
    gold = bld.slot(M.caliper_gold())
    ro = sp.disc_r
    r_in = ro - 66 * MM
    r_out = ro + 15 * MM
    h = sp.cal_half
    a_f = sp.disc_a + sp.disc_t / 2 + 2.5 * MM       # inner side of the outboard half
    a_b = sp.disc_a - sp.disc_t / 2 - 2.5 * MM
    w = sp.cal_w

    def shape(t, r, a, i, j, k):
        # taper the ends: lower outer radius and raise inner radius towards the tips
        u = abs(t) / h
        rr = r
        if r > ro - 20 * MM:
            rr = r - 7 * MM * u ** 3
        else:
            rr = r + 16 * MM * u ** 2.5
        return rr, a

    ths = [-h, -h * 0.93, -h * 0.66, -h * 0.33, 0, h * 0.33, h * 0.66, h * 0.93, h]
    # outboard half
    V, F = _bent_box(ths, _support(r_in, r_out, 2, 0.1), _support(a_f, a_f + w, 1, 0.14), shape)
    bld.add(V, F, gold)
    # inboard half
    V, F = _bent_box(ths, _support(r_in, r_out, 2, 0.1), _support(a_b - w, a_b, 1, 0.14), shape)
    bld.add(V, F, gold)
    # bridges across the disc (two end bridges + centre bridge)
    for c0, c1 in ((-h * 0.98, -h * 0.52), (-h * 0.16, h * 0.16), (h * 0.52, h * 0.98)):
        V, F = _bent_box(_support(c0, c1, 1, 0.12), _support(ro + 3.5 * MM, r_out + 1 * MM, 0, 0.2),
                         _support(a_b - w * 0.6, a_f + w * 0.6, 2, 0.06), shape)
        bld.add(V, F, gold)
    me = bld.mesh(name, sharp_deg=180)
    return me


def _caliper_detail_mesh(sp, name):
    """Hard-surface details on the caliper: piston bosses, logo plate, bolts, pads."""
    bld = _Builder()
    gold = bld.slot(M.caliper_gold())
    dark = bld.slot(M.satin_black())
    steel = bld.slot(_mat_bolt())
    white = bld.slot(_mat_roundel_white())
    stripes = [bld.slot(_mat_caliper_logo(i)) for i in range(3)]
    ro = sp.disc_r
    h = sp.cal_half
    a_face = sp.disc_a + sp.disc_t / 2 + 2.5 * MM + sp.cal_w
    n_p = 3 if sp.axle == "F" else 2
    r_p = ro - 30 * MM
    th = np.linspace(0, 2 * math.pi, 28, endpoint=False)
    pist = np.linspace(-h * 0.62, h * 0.62, n_p)
    radii = [23, 21, 23] if n_p == 3 else [21, 21]
    for ang, pr in zip(pist, radii):
        # boss: local frame around the radial direction
        er = np.array([math.cos(ang), 0, math.sin(ang)])
        et = np.array([-math.sin(ang), 0, math.cos(ang)])
        ctr = er * r_p
        prof = [(pr * MM, a_face - 6 * MM), (pr * MM, a_face + 2.0 * MM),
                ((pr - 2.2) * MM, a_face + 4.2 * MM), (0.0, a_face + 4.2 * MM)]
        rings = []
        for rad, a in prof[:-1]:
            rings.append(ctr[None, :] + rad * (np.cos(th)[:, None] * er + np.sin(th)[:, None] * et)
                         + np.array([0, a, 0]))
        V = np.concatenate(rings)
        faces = []
        for i in range(len(rings) - 1):
            for j in range(28):
                j1 = (j + 1) % 28
                faces.append((i * 28 + j, i * 28 + j1, (i + 1) * 28 + j1, (i + 1) * 28 + j))
        faces.append(tuple(range((len(rings) - 1) * 28, len(rings) * 28)))
        bld.add(V, faces, gold)
    # logo plate with the three M stripes and a white field (on the upper rim of the body)
    r_l0, r_l1 = ro - 6 * MM, ro + 9 * MM
    a_l = a_face + 0.6 * MM
    span = h * 0.36
    cells = [(-span, -span * 0.72, stripes[0]), (-span * 0.72, -span * 0.44, stripes[1]),
             (-span * 0.44, -span * 0.16, stripes[2]), (-span * 0.10, span, white)]
    for t0, t1, mi in cells:
        ts = np.linspace(t0, t1, 4)
        V = []
        for t in ts:
            sk = 0.004 / ro      # slanted stripes
            V.append((r_l0 * math.cos(t - sk * 3), a_l, r_l0 * math.sin(t - sk * 3)))
            V.append((r_l1 * math.cos(t + sk * 3), a_l, r_l1 * math.sin(t + sk * 3)))
        faces = [(2 * i, 2 * i + 2, 2 * i + 3, 2 * i + 1) for i in range(3)]
        bld.add(np.array(V), faces, mi, keep=True)
    # bridge bolts (steel) at the two ends
    th10 = np.linspace(0, 2 * math.pi, 12, endpoint=False)
    for ang in (-h * 0.84, h * 0.84, -h * 0.30, h * 0.30)[: 4 if sp.axle == "F" else 2]:
        er = np.array([math.cos(ang), 0, math.sin(ang)])
        et = np.array([-math.sin(ang), 0, math.cos(ang)])
        ctr = er * (ro + 6 * MM)
        rad = 5.0 * MM
        rings = [ctr + rad * (np.cos(th10)[:, None] * er + np.sin(th10)[:, None] * et)
                 + np.array([0, a, 0]) for a in (a_face - 3 * MM, a_face + 1.6 * MM)]
        V = np.concatenate(rings)
        faces = [(j, (j + 1) % 12, 12 + (j + 1) % 12, 12 + j) for j in range(12)]
        faces.append(tuple(range(12, 24)))
        bld.add(V, faces, steel)
    # brake pads visible in the gaps between the bridges
    a_f = sp.disc_a + sp.disc_t / 2
    for sgn in (1, -1):
        a0 = a_f + 0.4 * MM if sgn > 0 else sp.disc_a - sp.disc_t / 2 - 0.4 * MM
        a1 = a0 + sgn * 9 * MM
        V, F = _bent_box(list(np.linspace(-h * 0.8, h * 0.8, 9)), [ro - 58 * MM, ro + 1 * MM],
                         sorted([a0, a1]))
        bld.add(V, F, dark)
    return bld.mesh(name, sharp_deg=35)


def _upright_mesh(sp, name):
    """Dust shield and hub carrier behind the disc."""
    bld = _Builder()
    dark = bld.slot(M.satin_black())
    ab = sp.disc_a - sp.disc_t / 2
    shield = [(ab - 14 * MM, 0.070), (ab - 14 * MM, sp.disc_r - 8 * MM),
              (ab - 8 * MM, sp.disc_r + 4 * MM), (ab - 9.5 * MM, sp.disc_r + 4 * MM),
              (ab - 15.5 * MM, sp.disc_r - 8 * MM), (ab - 15.5 * MM, 0.070)]
    _lathe(bld, np.array(shield), dark, segs=96, closed=True)
    carrier = [(ab - 150 * MM, 0.0), (ab - 150 * MM, 0.060), (ab - 110 * MM, 0.085),
               (ab - 10 * MM, 0.085), (ab - 10 * MM, 0.0)]
    _lathe(bld, np.array(carrier), dark, segs=48, closed=False)
    return bld.mesh(name, sharp_deg=35)


# ---------------------------------------------------------------------------
# assembly
# ---------------------------------------------------------------------------
def _get_mesh(name, builder):
    me = bpy.data.meshes.get(name)
    if me is None:
        me = builder(name)
        me.name = name
    return me


def _child(name, mesh, parent, coll):
    obj = bpy.data.objects.new(name, mesh)
    coll.objects.link(obj)
    obj.parent = parent
    return obj


def build_wheel(axle, side, collection=None):
    """Build one complete wheel ('F'/'R', 'L'/'R') at its real position. Returns the root."""
    assert axle in ("F", "R") and side in ("L", "R")
    coll = collection or util.get_collection("Wheels")
    sp = _Spec(axle)
    tag = "M5_Wheel_%s%s" % (axle, side)
    pre = "M5_Wheel_%s_" % axle

    root = bpy.data.objects.new(tag, None)
    root.empty_display_type = "PLAIN_AXES"
    root.empty_display_size = 0.15
    coll.objects.link(root)
    x = P.AXLE_F_X if axle == "F" else P.AXLE_R_X
    y = P.WHEEL_F_Y if axle == "F" else P.WHEEL_R_Y
    z = P.WHEEL_F_Z if axle == "F" else P.WHEEL_R_Z
    root.location = (x, y if side == "L" else -y, z)
    if side == "R":
        root.rotation_euler = (0.0, 0.0, math.pi)

    spin = bpy.data.objects.new(tag + "_Spin", None)
    spin.empty_display_type = "CIRCLE"
    spin.empty_display_size = 0.1
    coll.objects.link(spin)
    spin.parent = root
    # local +X of the mesh is a chevron bisector; pose it like in the reference side view.
    # Blender's Y rotation turns +Z towards +X, hence the minus sign.
    pose = SPIN_DEG if side == "L" else 180.0 - SPIN_DEG
    spin.rotation_euler = (0.0, -math.radians(pose), 0.0)

    _child(tag + "_Tyre", _get_mesh(pre + "Tyre", lambda n: _tyre_mesh(sp, n)), spin, coll)
    _child(tag + "_Rim", _get_mesh(pre + "Rim", lambda n: _rim_mesh(sp, n)), spin, coll)
    _child(tag + "_Hardware", _get_mesh(pre + "Hardware", lambda n: _hardware_mesh(sp, n)),
           spin, coll)
    _child(tag + "_Cap", _get_mesh(pre + "Cap", lambda n: _cap_mesh(sp, n)), root, coll)
    _child(tag + "_BrakeDisc", _get_mesh(pre + "BrakeDisc", lambda n: _disc_mesh(sp, n)),
           spin, coll)

    # non-rotating parts. Front caliper trails the axle, rear caliper leads it.
    fixed = bpy.data.objects.new(tag + "_Brake", None)
    fixed.empty_display_size = 0.05
    coll.objects.link(fixed)
    fixed.parent = root
    world_dir = math.pi if axle == "F" else 0.0          # angle of the caliper centre (world XZ)
    local = world_dir if side == "L" else math.pi - world_dir
    fixed.rotation_euler = (0.0, -local, 0.0)
    cal = _child(tag + "_Caliper", _get_mesh(pre + "Caliper", lambda n: _caliper_mesh(sp, n)),
                 fixed, coll)
    sub = cal.modifiers.new("Subsurf", "SUBSURF")
    sub.levels = 2
    sub.render_levels = 2
    _child(tag + "_CaliperDetail",
           _get_mesh(pre + "CaliperDetail", lambda n: _caliper_detail_mesh(sp, n)), fixed, coll)
    _child(tag + "_Upright", _get_mesh(pre + "Upright", lambda n: _upright_mesh(sp, n)),
           fixed, coll)
    return root


def build_wheels(collection=None):
    coll = collection or util.get_collection("Wheels")
    return [build_wheel(a, s, coll) for a in ("F", "R") for s in ("L", "R")]


def triangle_count(root):
    """Evaluated triangle count of one wheel hierarchy."""
    dg = bpy.context.evaluated_depsgraph_get()
    total = 0
    stack = [root]
    while stack:
        o = stack.pop()
        stack.extend(o.children)
        if o.type == "MESH":
            me = o.evaluated_get(dg).to_mesh()
            total += sum(len(p.vertices) - 2 for p in me.polygons)
            o.evaluated_get(dg).to_mesh_clear()
    return total


# ---------------------------------------------------------------------------
# standalone preview
# ---------------------------------------------------------------------------
def _main():
    import os
    import sys
    out = None
    for a in sys.argv[1:]:
        if not a.startswith("-"):
            out = a
    if out is None:
        out = os.path.join(os.environ.get("M5_SCRATCH", "/tmp"), "wheels")
    os.makedirs(out, exist_ok=True)
    util.reset_scene()
    roots = build_wheels()
    bpy.context.view_layer.update()
    for r in roots:
        print(r.name, "triangles:", triangle_count(r))
    util.preview_light_rig(world=0.08)
    fx, rx = P.AXLE_F_X, P.AXLE_R_X
    util.preview_render(os.path.join(out, "front_side.png"), (fx, 3.2, P.WHEEL_F_Z),
                        (fx, 0.9, P.WHEEL_F_Z), lens=110, res=(1000, 1000), samples=48)
    util.preview_render(os.path.join(out, "rear_34.png"), (rx - 1.5, 2.6, 0.75),
                        (rx, 0.9, P.WHEEL_R_Z), lens=85, res=(1000, 1000), samples=48)
    print("previews in", out)


if __name__ == "__main__":
    _main()
