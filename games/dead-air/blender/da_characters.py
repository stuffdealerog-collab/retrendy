"""STRELKA — original R6-style avatars (classic 6-part Roblox rig) in the
emo / grunge street look: hood up, messy fringe, mask, crossbody bag.

Rig = the classic R6 hierarchy: Torso (root joint) > Head, Left Arm, Right Arm,
Left Leg, Right Leg — same part names and the same joint pivots as Roblox R6
(1 stud = 0.3 m here), so animation maps 1:1 onto R6 Motor6Ds.
Character faces -Y, Z up, the character's left is +X.

All textures are generated here: nothing is copied from the Roblox catalog.
"""
import math
import os
import random

import bmesh
import bpy
import numpy as np
from mathutils import Euler, Matrix, Vector

import da_common as C

PIVOTS = {
    "Root": (0, 0, 0),
    "Torso": (0, 0, 0.9),
    "Head": (0, 0, 1.2),
    "Left Arm": (0.3, 0, 1.05),
    "Right Arm": (-0.3, 0, 1.05),
    "Left Leg": (0.15, 0, 0.6),
    "Right Leg": (-0.15, 0, 0.6),
}
PARENTS = {"Torso": "Root", "Head": "Torso", "Left Arm": "Torso", "Right Arm": "Torso",
           "Left Leg": "Torso", "Right Leg": "Torso"}
R6_PARTS = ["Torso", "Head", "Left Arm", "Right Arm", "Left Leg", "Right Leg"]

A = 256
REGIONS = {  # x, y, w, h in atlas pixels (y down)
    "torso_front": (0, 0, 96, 96), "torso_back": (96, 0, 96, 96), "torso_side": (192, 0, 48, 96),
    "arm": (0, 96, 48, 96), "leg": (48, 96, 48, 96), "leg_front": (96, 96, 48, 96),
    "face": (144, 96, 96, 96), "decal": (192, 192, 64, 64),
}
SW = 16


def make_armature(name, collection):
    arm_data = bpy.data.armatures.new(name + "_Rig")
    arm = bpy.data.objects.new(name, arm_data)
    collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    ebs = {}
    for bname, piv in PIVOTS.items():
        eb = arm_data.edit_bones.new(bname)
        eb.head = piv
        eb.tail = (piv[0], piv[1], piv[2] + 0.1)
        eb.roll = 0.0
        ebs[bname] = eb
    for child, parent in PARENTS.items():
        ebs[child].parent = ebs[parent]
        ebs[child].use_connect = False
    bpy.ops.object.mode_set(mode="OBJECT")
    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
    arm_data.display_type = "STICK"
    return arm


# ---------------------------------------------------------------------------
# Painted textures
# ---------------------------------------------------------------------------
def _rgb(h):
    return np.array([c * 255 for c in C.hex_rgb(h)], np.float32)


def _tup(h, k=1.0):
    return tuple(int(min(255, c * k)) for c in _rgb(h))


def cloth(w, h, base, seed, folds=0.10, edge=0.22, grad=0.16, noise=0.025):
    """Shaded fabric: soft diagonal folds, darker hems and edges, fine weave."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    u, v = x / w, y / h
    s = np.zeros((h, w), np.float32)
    for _ in range(5):
        ang = rng.uniform(-1.1, 1.1)
        f = rng.uniform(1.2, 3.4)
        ph = rng.uniform(0, 6.28)
        s += np.sin((u * math.cos(ang) + v * math.sin(ang) * 1.3) * f * 6.28 + ph
                    + 1.5 * np.sin(v * rng.uniform(2, 5) + ph)) * rng.uniform(0.4, 1.0)
    s = s / 3.0 * folds
    s += (0.5 - v) * grad
    ex = np.minimum(u, 1 - u) * w
    s -= edge * np.clip(1 - ex / (w * 0.16), 0, 1) ** 1.6
    s += rng.normal(0, noise, (h, w))
    out = _rgb(base)[None, None, :] * (1.0 + s[..., None])
    return out.clip(0, 255)


def rib(img, y0, y1, k=0.82, step=3):
    img[y0:y1] *= 0.93
    img[y0:y1, ::step] *= k
    img[y0:y0 + 1] *= 0.6
    return img


def to_pil(a):
    from PIL import Image
    return Image.fromarray(a.clip(0, 255).astype(np.uint8))


def face_tex(skin, style, ink_hex="#16131a"):
    """Simple flat face in the classic spirit (own drawings)."""
    from PIL import Image, ImageDraw
    S = 4
    w = 96 * S
    sk = _tup(skin)
    img = Image.new("RGB", (w, w), sk)
    d = ImageDraw.Draw(img)
    ink = _tup(ink_hex)
    ey = 46 * S
    for sx, cx in ((-1, 34 * S), (1, 62 * S)):
        if style == "tired":
            d.ellipse((cx - 6 * S, ey - 5 * S, cx + 6 * S, ey + 7 * S), fill=ink)
            d.rectangle((cx - 8 * S, ey - 7 * S, cx + 8 * S, ey - 1 * S), fill=sk)
            d.line((cx - 8 * S, ey - 1 * S, cx + 8 * S, ey - 1 * S + sx * 2 * S), fill=ink, width=2 * S)
            d.arc((cx - 8 * S, ey + 2 * S, cx + 8 * S, ey + 13 * S), 20, 160, fill=_tup(skin, 0.72), width=S)
            d.ellipse((cx - 3 * S, ey + 0 * S, cx - 1 * S, ey + 2 * S), fill=(255, 255, 255))
        elif style == "angry":
            d.ellipse((cx - 5 * S, ey - 5 * S, cx + 5 * S, ey + 6 * S), fill=ink)
            d.ellipse((cx - 3 * S, ey - 3 * S, cx - 1 * S, ey - 1 * S), fill=(255, 255, 255))
            d.line((cx - sx * 10 * S, ey - 15 * S, cx + sx * 8 * S, ey - 8 * S), fill=ink, width=3 * S)
        elif style == "smirk":
            d.ellipse((cx - 5 * S, ey - 6 * S, cx + 5 * S, ey + 6 * S), fill=ink)
            d.ellipse((cx - 3 * S, ey - 4 * S, cx - 1 * S, ey - 2 * S), fill=(255, 255, 255))
            d.line((cx - 8 * S, ey - 13 * S + (sx > 0) * 3 * S, cx + 8 * S, ey - 13 * S - (sx > 0) * 2 * S),
                   fill=ink, width=2 * S)
        else:  # blank
            d.ellipse((cx - 6 * S, ey - 8 * S, cx + 6 * S, ey + 8 * S), fill=ink)
            d.ellipse((cx - 4 * S, ey - 6 * S, cx - 1 * S, ey - 3 * S), fill=(255, 255, 255))
    my = 70 * S
    if style == "smirk":
        d.arc((36 * S, my - 12 * S, 66 * S, my + 4 * S), 20, 150, fill=ink, width=2 * S)
    elif style == "angry":
        d.arc((38 * S, my - 2 * S, 58 * S, my + 12 * S), 200, 340, fill=ink, width=2 * S)
    elif style == "blank":
        d.line((44 * S, my, 52 * S, my), fill=ink, width=2 * S)
    return np.array(img.resize((96, 96), Image.LANCZOS)).astype(np.float32)


def text_patch(w, h, bg, text, fg, size=18, font="DejaVuSans-Bold.ttf"):
    from PIL import Image, ImageDraw, ImageFont
    S = 3
    img = Image.new("RGB", (w * S, h * S), _tup(bg))
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/" + font, size * S)
    bb = d.textbbox((0, 0), text, font=f)
    d.text(((w * S - (bb[2] - bb[0])) / 2 - bb[0], (h * S - (bb[3] - bb[1])) / 2 - bb[1]), text, font=f,
           fill=_tup(fg))
    return np.array(img.resize((w, h), Image.LANCZOS)).astype(np.float32)


class Atlas:
    def __init__(self, name, swatches):
        self.name = name
        self.img = np.zeros((A, A, 3), np.float32)
        self.emit = np.zeros((A, A, 3), np.float32)
        self.sw = [s[0] for s in swatches]
        for i, (_, hx, em) in enumerate(swatches):
            cx, cy = (i % 12) * SW, 192 + (i // 12) * SW
            self.img[cy:cy + SW, cx:cx + SW] = _rgb(hx)
            if em:
                self.emit[cy:cy + SW, cx:cx + SW] = _rgb(hx) * em

    def put(self, region, arr, emit=None):
        x, y, w, h = REGIONS[region]
        assert arr.shape[0] == h and arr.shape[1] == w, (region, arr.shape)
        self.img[y:y + h, x:x + w] = arr
        if emit is not None:
            self.emit[y:y + h, x:x + w] = emit

    def region_uv(self, region, u, v):
        x, y, w, h = REGIONS[region]
        m = 0.6
        u, v = min(1, max(0, u)), min(1, max(0, v))
        return ((x + m + u * (w - 2 * m)) / A, 1 - (y + h - m - v * (h - 2 * m)) / A)

    def swatch_uv(self, name, n=4):
        i = self.sw.index(name)
        cx, cy = (i % 12) * SW + SW / 2, 192 + (i // 12) * SW + SW / 2
        r = 3
        q = [(cx - r, cy + r), (cx + r, cy + r), (cx + r, cy - r), (cx - r, cy - r)]
        q = [(px / A, 1 - py / A) for px, py in q]
        return (q * ((n + 3) // 4))[:n]

    def save(self):
        p1 = C.save_png(self.img.clip(0, 255).astype(np.uint8), os.path.join(C.TEX, f"{self.name}_atlas.png"))
        p2 = C.save_png(self.emit.clip(0, 255).astype(np.uint8), os.path.join(C.TEX, f"{self.name}_emit.png"))
        return p1, p2


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------
class R6Builder:
    def __init__(self, name, atlas):
        self.name, self.at = name, atlas
        self.parts = {p: {"v": [], "f": [], "uv": [], "smooth": []} for p in R6_PARTS}

    def _face(self, part, pts, uv, smooth=False):
        P = self.parts[part]
        i = len(P["v"])
        P["v"].extend([tuple(p) for p in pts])
        P["f"].append(tuple(range(i, i + len(pts))))
        P["uv"].append(uv)
        P["smooth"].append(smooth)

    def frustum(self, part, z0, z1, b, t, color, cx=0.0, cy=0.0, top_off=(0, 0), tex=None,
                colors=None, M=None, skip=()):
        """Box/frustum. tex: {'y-': region,...}; sides without a region use a flat swatch."""
        bw, bd, tw, td = b[0] / 2, b[1] / 2, t[0] / 2, t[1] / 2
        ox, oy = top_off
        B = [(cx - bw, cy - bd, z0), (cx + bw, cy - bd, z0), (cx + bw, cy + bd, z0), (cx - bw, cy + bd, z0)]
        T = [(cx + ox - tw, cy + oy - td, z1), (cx + ox + tw, cy + oy - td, z1),
             (cx + ox + tw, cy + oy + td, z1), (cx + ox - tw, cy + oy + td, z1)]
        sides = {"y-": [B[0], B[1], T[1], T[0]], "x+": [B[1], B[2], T[2], T[1]],
                 "y+": [B[2], B[3], T[3], T[2]], "x-": [B[3], B[0], T[0], T[3]],
                 "z+": [T[0], T[1], T[2], T[3]], "z-": [B[3], B[2], B[1], B[0]]}
        W_, D_ = max(b[0], t[0]), max(b[1], t[1])
        bx0, bx1, by0, by1 = cx - W_ / 2, cx + W_ / 2, cy - D_ / 2, cy + D_ / 2
        for side, pts in sides.items():
            if side in skip:
                continue
            if tex and side in tex:
                uv = []
                for (x, y, z) in pts:
                    v = (z - z0) / (z1 - z0)
                    if side == "y-":
                        u = (x - bx0) / (bx1 - bx0)
                    elif side == "y+":
                        u = (bx1 - x) / (bx1 - bx0)
                    elif side == "x+":
                        u = (y - by0) / (by1 - by0)
                    else:
                        u = (by1 - y) / (by1 - by0)
                    uv.append(self.at.region_uv(tex[side], u, v))
            else:
                uv = self.at.swatch_uv((colors or {}).get(side, color))
            if M is not None:
                pts = [tuple(M @ Vector(p)) for p in pts]
            self._face(part, pts, uv)

    def box(self, part, lo, hi, color, **kw):
        w, d = hi[0] - lo[0], hi[1] - lo[1]
        self.frustum(part, lo[2], hi[2], (w, d), (w, d), color, cx=(lo[0] + hi[0]) / 2,
                     cy=(lo[1] + hi[1]) / 2, **kw)

    def rbox(self, part, pivot, size, color, rot=(0, 0, 0), taper=(1, 1), **kw):
        M = Matrix.Translation(pivot) @ Euler([math.radians(a) for a in rot], "XYZ").to_matrix().to_4x4()
        self.frustum(part, 0, size[2], (size[0], size[1]), (size[0] * taper[0], size[1] * taper[1]),
                     color, M=M, **kw)

    def head(self, skin, r=0.1875, z0=1.2, z1=1.575, n=20, face="face"):
        """Classic rounded head: a cylinder with bevel rings top and bottom.
        The face texture wraps the front half."""
        prof = [(0.62, 0.0), (0.90, 0.045), (1.0, 0.14), (1.0, 0.86), (0.90, 0.955), (0.62, 1.0)]
        h = z1 - z0
        half = n // 2

        def pt(i, k):                       # i = 0 at front (-Y); +i turns towards +X
            a = 2 * math.pi * i / n
            rr, t = prof[k]
            return (r * rr * math.sin(a), -r * rr * math.cos(a), z0 + h * t)

        for i in range(-half, half):
            for k in range(len(prof) - 1):
                idx = [(i, k), (i + 1, k), (i + 1, k + 1), (i, k + 1)]
                pts = [pt(*q) for q in idx]
                if -n / 4 <= i < n / 4:
                    uvs = [self.at.region_uv(face, 0.5 + q[0] / (n / 2), prof[q[1]][1]) for q in idx]
                else:
                    uvs = self.at.swatch_uv(skin)
                self._face("Head", pts, uvs, smooth=True)
        for k, rev in ((0, True), (len(prof) - 1, False)):
            ring = [pt(i, k) for i in range(n)]
            self._face("Head", ring[::-1] if rev else ring, self.at.swatch_uv(skin, n), smooth=True)

    def shell(self, part, center, radii, color, inner, opening=52, open_axis=(0, -1, -0.12),
              lat0=0, lat1=128, n=18, m=9, tex=None, thick=0.93):
        """Hood / cap / hair cap: an ellipsoid shell with an optional face opening, dark inside."""
        ax = Vector(open_axis).normalized()
        cx, cy, cz = center

        def pt(i, j, s=1.0):
            th = 2 * math.pi * i / n
            ph = math.radians(lat0 + (lat1 - lat0) * j / m)
            d = Vector((math.sin(ph) * math.sin(th), -math.sin(ph) * math.cos(th), math.cos(ph)))
            return d, (cx + radii[0] * d.x * s, cy + radii[1] * d.y * s, cz + radii[2] * d.z * s)

        for i in range(n):
            for j in range(m):
                q = [pt(i, j), pt(i + 1, j), pt(i + 1, j + 1), pt(i, j + 1)]
                dmid = sum((a[0] for a in q), Vector()) / 4
                if opening and dmid.length > 1e-6 and dmid.normalized().dot(ax) > math.cos(math.radians(opening)):
                    continue
                pts = [a[1] for a in q]
                if tex:
                    uv = [self.at.region_uv(tex, 0.5 + 0.46 * a[0].x, 0.5 + 0.46 * a[0].z) for a in q]
                else:
                    uv = self.at.swatch_uv(color)
                self._face(part, pts[::-1], uv[::-1], smooth=True)
                if opening:
                    ipts = [pt(i, j, thick)[1], pt(i + 1, j, thick)[1], pt(i + 1, j + 1, thick)[1],
                            pt(i, j + 1, thick)[1]]
                    self._face(part, ipts, self.at.swatch_uv(inner), smooth=True)

    def spikes(self, part, color, color2, seed, origin=(0, -0.02, 1.42), count=22, front=True,
               length=(0.16, 0.26), droop=0.75):
        """Messy hair: wedges fanning out of the hood / scalp, tips drooping."""
        rnd = random.Random(seed)
        for k in range(count):
            th = rnd.uniform(-1.25, 1.25) if front else rnd.uniform(-math.pi, math.pi)
            el = rnd.uniform(0.15, 1.15)
            d = Vector((math.sin(th) * math.cos(el), -math.cos(th) * math.cos(el), math.sin(el)))
            base = Vector(origin) + Vector((d.x * 0.15, d.y * 0.155, d.z * 0.13))
            tip_dir = (d + Vector((0, -0.25 if front else 0.0, -droop))).normalized()
            L = rnd.uniform(*length)
            w = rnd.uniform(0.045, 0.075)
            M = Matrix.Translation(base) @ tip_dir.to_track_quat("Z", "Y").to_matrix().to_4x4()
            self.frustum(part, 0, L, (w, w * 0.6), (w * 0.12, w * 0.1), color if k % 3 else color2, M=M)

    def finish(self, collection, mat):
        arm = make_armature(self.name, collection)
        objs = []
        for part, P in self.parts.items():
            me = bpy.data.meshes.new(f"{self.name}_{part}")
            me.from_pydata(P["v"], [], P["f"])
            me.materials.append(mat)
            uvl = me.uv_layers.new(name="UVMap")
            k = 0
            for poly, fuv, sm in zip(me.polygons, P["uv"], P["smooth"]):
                poly.use_smooth = sm
                for j in range(poly.loop_total):
                    uvl.data[k].uv = fuv[j]
                    k += 1
            me.update()
            bm = bmesh.new(); bm.from_mesh(me)
            bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
            bm.to_mesh(me); bm.free()
            ob = bpy.data.objects.new(f"{self.name}_{part}", me)
            collection.objects.link(ob)
            vg = ob.vertex_groups.new(name=part)
            vg.add(list(range(len(me.vertices))), 1.0, "REPLACE")
            ob.parent = arm
            mod = ob.modifiers.new("Armature", "ARMATURE")
            mod.object = arm
            objs.append(ob)
        arm["strelka_character"] = self.name
        return arm, objs


def char_material(name, atlas_path, emit_path, emit_strength=3.0):
    base = C.load_image(atlas_path)
    emit = C.load_image(emit_path)
    mat = C.tex_mat(f"{name}_Mat", base, emit, emit_strength=emit_strength, rough=0.72, fog=0.0)
    for n in mat.node_tree.nodes:
        if n.type == "TEX_IMAGE":
            n.interpolation = "Linear"
    return mat


# ---------------------------------------------------------------------------
# Body kit
# ---------------------------------------------------------------------------
def body(b, skin):
    t = {"y-": "torso_front", "y+": "torso_back", "x+": "torso_side", "x-": "torso_side"}
    b.box("Torso", (-0.3, -0.15, 0.6), (0.3, 0.15, 1.2), "cloth_top", tex=t,
          colors={"z-": "cloth_dark", "z+": "cloth_top"})
    for s, S in ((1, "Left"), (-1, "Right")):
        ax = s * 0.45
        ta = {k: "arm" for k in ("y-", "y+", "x+", "x-")}
        b.box(f"{S} Arm", (ax - 0.148, -0.15, 0.6), (ax + 0.148, 0.15, 1.2), "cloth_top", tex=ta,
              colors={"z-": skin, "z+": "cloth_top"})
        lx = s * 0.15
        tl = {"y-": "leg_front", "y+": "leg", "x+": "leg", "x-": "leg"}
        b.box(f"{S} Leg", (lx - 0.147, -0.15, 0.0), (lx + 0.147, 0.15, 0.6), "cloth_dark", tex=tl,
              colors={"z-": "sole", "z+": "cloth_dark"})


def hood_up(b):
    b.shell("Head", (0, 0.02, 1.405), (0.255, 0.265, 0.245), "cloth_top", "hood_in", opening=50,
            tex="torso_back")
    for k in range(10):          # the hood's drape on the shoulders
        a0, a1 = 2 * math.pi * k / 10, 2 * math.pi * (k + 1) / 10
        r0, r1 = (0.29, 0.19), (0.21, 0.20)
        pts = [(r0[0] * math.sin(a0), -r0[1] * math.cos(a0) + 0.01, 1.185),
               (r0[0] * math.sin(a1), -r0[1] * math.cos(a1) + 0.01, 1.185),
               (r1[0] * math.sin(a1), -r1[1] * math.cos(a1) + 0.02, 1.275),
               (r1[0] * math.sin(a0), -r1[1] * math.cos(a0) + 0.02, 1.275)]
        uv = [b.at.region_uv("torso_back", 0.2 + 0.06 * (k + (j in (1, 2))), 0.45 + 0.25 * (j > 1))
              for j in range(4)]
        b._face("Torso", pts, uv, smooth=True)


def mask(b, z0=1.215, z1=1.375, r=0.196, span=74):
    n = 8
    for i in range(n):
        a0 = math.radians(-span + 2 * span * i / n)
        a1 = math.radians(-span + 2 * span * (i + 1) / n)
        pts = [(r * math.sin(a0), -r * math.cos(a0), z0), (r * math.sin(a1), -r * math.cos(a1), z0),
               (r * math.sin(a1), -r * math.cos(a1), z1), (r * math.sin(a0), -r * math.cos(a0), z1)]
        uv = [b.at.region_uv("decal", i / n, 0.30), b.at.region_uv("decal", (i + 1) / n, 0.30),
              b.at.region_uv("decal", (i + 1) / n, 0.70), b.at.region_uv("decal", i / n, 0.70)]
        b._face("Head", pts, uv, smooth=True)


def crossbody(b, s=1):
    """Strap from the right shoulder to the left hip (s=1) + a sling bag."""
    for y in (-0.158, 0.158):
        p0 = Vector((-s * 0.27, y, 1.21)); p1 = Vector((s * 0.31, y, 0.68))
        d = p1 - p0
        b.rbox("Torso", tuple(p0), (0.05, 0.012, d.length), "strap",
               rot=(0, math.degrees(math.atan2(d.x, d.z)), 0))
    b.box("Torso", (-s * 0.30 - 0.03, -0.16, 1.195), (-s * 0.30 + 0.07, 0.16, 1.215), "strap")
    b.rbox("Torso", (s * 0.37, -0.04, 0.50), (0.20, 0.30, 0.20), "bag", rot=(8, s * 10, s * 18),
           taper=(0.8, 0.85), colors={"z+": "strap"})
    b.rbox("Torso", (s * 0.47, -0.09, 0.56), (0.02, 0.16, 0.09), "strap", rot=(8, s * 10, s * 18))


def carabiner(b, side=-1):
    x = side * 0.602
    part = "Right Arm" if side < 0 else "Left Arm"
    for dz in (0.0, -0.075):
        z = 0.70 + dz
        for lo, hi in (((x - 0.004, -0.05, z), (x + 0.004, -0.04, z + 0.07)),
                       ((x - 0.004, 0.0, z), (x + 0.004, 0.01, z + 0.07)),
                       ((x - 0.004, -0.05, z + 0.06), (x + 0.004, 0.01, z + 0.07)),
                       ((x - 0.004, -0.05, z), (x + 0.004, 0.01, z + 0.01))):
            b.box(part, lo, hi, "metal")


def paint_hoodie(at, base, seed, zip_=False, strings=True, pocket=True, print_text=None,
                 print_col="#e9e7ee"):
    from PIL import ImageDraw
    f = rib(cloth(96, 96, base, seed), 84, 96)
    im = to_pil(f); d = ImageDraw.Draw(im)
    dark = _tup(base, 0.62)
    lite = tuple(min(255, int(c * 1.5 + 30)) for c in _rgb(base))
    if pocket:
        d.line((24, 82, 30, 56, 66, 56, 72, 82), fill=dark, width=1)
        d.line((30, 56, 26, 70), fill=dark, width=1); d.line((66, 56, 70, 70), fill=dark, width=1)
    if zip_:
        d.line((48, 0, 48, 96), fill=dark, width=2); d.line((49, 0, 49, 96), fill=lite, width=1)
    if strings:
        d.line((41, 0, 40, 30), fill=lite, width=2); d.line((55, 0, 57, 26), fill=lite, width=2)
        d.rectangle((39, 30, 41, 35), fill=(200, 200, 205)); d.rectangle((56, 26, 58, 31), fill=(200, 200, 205))
    f = np.array(im).astype(np.float32)
    if print_text:
        f[32:48, 26:70] = text_patch(44, 16, base, print_text, print_col, size=11)
    at.put("torso_front", f)
    at.put("torso_back", rib(cloth(96, 96, base, seed + 1), 84, 96))
    at.put("torso_side", rib(cloth(48, 96, base, seed + 2, edge=0.3), 84, 96))
    at.put("arm", rib(cloth(48, 96, base, seed + 3, edge=0.3, folds=0.14), 82, 96))


def paint_legs(at, kind, base, seed, skin="#e8d7cf", shoe="#111014", sole="#d9d7df", stripe=None):
    for region, sd in (("leg", seed), ("leg_front", seed + 5)):
        if kind == "shorts":
            a = np.zeros((96, 48, 3), np.float32)
            a[:] = _rgb(skin) * 0.96
            a[0:50] = rib(cloth(48, 50, base, sd, edge=0.3), 43, 50)
            a[66:96] = cloth(48, 30, shoe, sd + 9, edge=0.25, folds=0.05)       # long socks into shoes
            a[66:68] *= 1.5
        else:
            a = cloth(48, 96, base, sd, edge=0.3, folds=0.13)
            if kind == "cargo":
                a[30:50, 4:20] *= 0.86; a[30:31, 4:20] *= 0.6; a[50:51, 4:20] *= 0.6
            a[78:96] = cloth(48, 18, shoe, sd + 9, edge=0.25, folds=0.04)
        a[90:96] = _rgb(sole)
        if region == "leg_front":
            a[82:88, 10:38] = np.minimum(255, a[82:88, 10:38] * 1.6 + 25)        # toe cap / laces
        if stripe:
            a[0:78, 3:6] = _rgb(stripe); a[0:78, 8:11] = _rgb(stripe)
        at.put(region, a)


BASE_SW = [("cloth_top", None, 0), ("cloth_dark", None, 0), ("hood_in", "#0b0a0e", 0), ("sole", "#d9d7df", 0),
           ("hair", "#0d0c10", 0), ("hair2", "#1c1a22", 0), ("mask", "#101014", 0), ("strap", "#141318", 0),
           ("bag", "#1b1a20", 0), ("metal", "#b9b8c2", 0), ("white", "#eceaf0", 0), ("black", "#09080b", 0)]


def _sw(top, dark, skin, extra=()):
    out = [(n, top if n == "cloth_top" else dark if n == "cloth_dark" else h, e) for n, h, e in BASE_SW]
    out.append(("skin", skin, 0))
    out.extend(extra)
    return out


# ---------------------------------------------------------------------------
# The crew
# ---------------------------------------------------------------------------
def build_tikhiy(col):
    """ТИХИЙ — heather-grey hoodie, hood up, mask, sling bag. The quiet one."""
    skin = "#eadbd6"
    at = Atlas("TIKHIY", _sw("#8e8d93", "#77767c", skin))
    paint_hoodie(at, "#8e8d93", 10)
    paint_legs(at, "shorts", "#85848a", 20, skin=skin)
    at.put("face", face_tex(skin, "tired"))
    d = np.zeros((64, 64, 3), np.float32); d[:] = _rgb("#101014")
    d[19:45, 2:62] = text_patch(60, 26, "#101014", "ТИХО", "#e9e7ee", size=17)
    at.put("decal", d)
    b = R6Builder("TIKHIY", at)
    body(b, "skin")
    b.head("skin")
    hood_up(b)
    b.spikes("Head", "hair", "hair2", 4, count=26)
    mask(b)
    crossbody(b, 1)
    carabiner(b, -1)
    return b.finish(col, char_material("TIKHIY", *at.save()))


def build_grach(col):
    """ГРАЧ — black hoodie, hood down, bleached messy hair, cargo pants, pink tape."""
    skin = "#d9c3b6"
    at = Atlas("GRACH", _sw("#1b1a20", "#141318", skin, [("pink", "#ff5fd2", 1.0), ("hairw", "#e6e3ee", 0),
                                                          ("hairw2", "#bdb9c9", 0)]))
    paint_hoodie(at, "#1b1a20", 30, print_text="404", print_col="#ff5fd2")
    paint_legs(at, "cargo", "#4a4952", 40, shoe="#e6e3ee", sole="#ff5fd2")
    f = face_tex(skin, "smirk")
    f[56:62, 60:80] = _rgb("#ff5fd2")            # tape on the cheek
    e = np.zeros((96, 96, 3), np.float32); e[56:62, 60:80] = _rgb("#ff5fd2") * 0.5
    at.put("face", f, e)
    b = R6Builder("GRACH", at)
    body(b, "skin")
    b.head("skin")
    b.shell("Torso", (0, 0.13, 1.20), (0.25, 0.14, 0.13), "cloth_top", "hood_in", opening=0, lat1=180,
            n=12, m=6, tex="torso_back")                                   # hood down
    b.shell("Head", (0, 0.005, 1.44), (0.198, 0.20, 0.15), "hairw", "hairw2", opening=0, lat1=92, n=14, m=5)
    b.spikes("Head", "hairw", "hairw2", 9, origin=(0, 0.0, 1.47), count=44, front=False,
             length=(0.12, 0.22), droop=0.55)
    b.box("Left Arm", (0.30, -0.155, 0.74), (0.60, 0.155, 0.775), "pink")
    return b.finish(col, char_material("GRACH", *at.save()))


def build_zima(col):
    """ЗИМА — two-stripe tracksuit, ushanka, orange soles."""
    skin = "#e6cdbd"
    at = Atlas("ZIMA", _sw("#15141a", "#101014", skin, [("amber", "#ff9a2e", 1.0), ("fur", "#cfccd6", 0),
                                                         ("hat", "#22252e", 0), ("fur_d", "#9a97a6", 0)]))
    paint_hoodie(at, "#15141a", 50, zip_=True, strings=False, pocket=False)
    a = cloth(48, 96, "#15141a", 53, edge=0.3, folds=0.14)
    a[:, 20:23] = _rgb("#eceaf0"); a[:, 26:29] = _rgb("#eceaf0")
    at.put("arm", rib(a, 84, 96))
    paint_legs(at, "pants", "#15141a", 60, shoe="#eceaf0", sole="#ff9a2e", stripe="#eceaf0")
    at.put("face", face_tex(skin, "angry"))
    b = R6Builder("ZIMA", at)
    body(b, "skin")
    b.head("skin")
    b.shell("Head", (0, 0.0, 1.47), (0.215, 0.215, 0.155), "hat", "hood_in", opening=0, lat1=95, n=16, m=6)
    for i in range(7):                                    # fur band over the brow
        a0, a1 = math.radians(-70 + 20 * i), math.radians(-50 + 20 * i)
        r = 0.225
        b._face("Head", [(r * math.sin(a0), -r * math.cos(a0), 1.44), (r * math.sin(a1), -r * math.cos(a1), 1.44),
                         (r * math.sin(a1), -r * math.cos(a1), 1.54), (r * math.sin(a0), -r * math.cos(a0), 1.54)],
                b.at.swatch_uv("fur"), smooth=True)
    for s in (1, -1):                                     # ear flaps, tied loose
        b.frustum("Head", 1.20, 1.50, (0.05, 0.20), (0.05, 0.24), "hat", cx=s * 0.215, cy=0.01,
                  colors={("x-" if s > 0 else "x+"): "fur"})
        b.box("Head", (s * 0.215 - 0.004, -0.01, 1.08), (s * 0.215 + 0.004, 0.0, 1.21), "fur_d")
    b.box("Torso", (-0.16, -0.16, 1.16), (0.16, 0.16, 1.24), "cloth_dark")       # collar
    return b.finish(col, char_material("ZIMA", *at.save()))


def build_mol(col):
    """МОЛЬ — oversized pale zip hoodie, long black hair with a blunt fringe, pink headphones."""
    skin = "#f1e2df"
    at = Atlas("MOL", _sw("#c9c7cf", "#2a2930", skin, [("pink", "#ff5fd2", 1.0), ("pink_d", "#c93aa0", 0)]))
    paint_hoodie(at, "#c9c7cf", 70, zip_=True)
    paint_legs(at, "pants", "#2a2930", 80, shoe="#eceaf0", sole="#ff5fd2")
    at.put("face", face_tex(skin, "blank"))
    b = R6Builder("MOL", at)
    body(b, "skin")
    b.head("skin")
    b.shell("Head", (0, 0.01, 1.435), (0.205, 0.215, 0.165), "hair", "hair2", opening=0, lat1=96, n=16, m=6)
    b.box("Head", (-0.19, -0.205, 1.44), (0.19, -0.17, 1.535), "hair")           # blunt fringe
    b.frustum("Head", 0.92, 1.50, (0.40, 0.09), (0.39, 0.12), "hair", cy=0.165, colors={"y+": "hair2"})
    for s in (1, -1):
        b.frustum("Head", 1.02, 1.50, (0.07, 0.16), (0.06, 0.22), "hair2", cx=s * 0.20, cy=0.03)
        b.box("Head", (s * 0.19 if s > 0 else -0.245, -0.07, 1.30), (0.245 if s > 0 else s * 0.19, 0.07, 1.46),
              "pink_d", colors={("x+" if s > 0 else "x-"): "pink"})
    b.box("Head", (-0.225, -0.025, 1.585), (0.225, 0.025, 1.61), "pink_d")
    b.box("Torso", (-0.17, -0.165, 1.16), (0.17, 0.165, 1.23), "cloth_top")
    return b.finish(col, char_material("MOL", *at.save()))


CAST = {"TIKHIY": build_tikhiy, "GRACH": build_grach, "ZIMA": build_zima, "MOL": build_mol}


def build_character(name, collection=None):
    return CAST[name](collection or bpy.context.scene.collection)
