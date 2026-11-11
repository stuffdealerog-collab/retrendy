"""STRELKA — the district: a post-Soviet courtyard street at 04:04.

Near-monochrome night, sodium-orange practical lights, one kiosk that is still
open. Everything fades into shader fog (da_common.fog_group).
"""
import math
import os
import random

import bpy
import numpy as np
from mathutils import Vector

import da_common as C

WT = os.path.join(C.TEX, "world")
SODIUM = "#ff9a3c"
PINK = "#ff5fd2"


def _img(name, arr):
    return C.load_image(C.save_png(arr, os.path.join(WT, name + ".png")))


def _hex8(h, k=1.0):
    return np.array([min(255, int(round(c * 255 * k))) for c in C.hex_rgb(h)], np.uint8)


# ---------------------------------------------------------------------------
# Textures
# ---------------------------------------------------------------------------
def facade_tex(seed, wall="#3d3a47", lit_ratio=0.2):
    """8x8 bays of a panel block, 16px per bay. Returns (base, emit) images."""
    rng = np.random.default_rng(seed)
    n, c = 8, 16
    base = np.zeros((n * c, n * c, 3), np.uint8)
    emit = np.zeros_like(base)
    w = _hex8(wall)
    for by in range(n):
        for bx in range(n):
            y0, x0 = by * c, bx * c
            tint = 0.9 + 0.2 * rng.random()
            base[y0:y0 + c, x0:x0 + c] = (w * tint).clip(0, 255)
            base[y0, x0:x0 + c] = (w * 0.55).astype(np.uint8)          # panel seams
            base[y0:y0 + c, x0] = (w * 0.55).astype(np.uint8)
            balcony = (bx % 4 == 1)
            wy0, wy1, wx0, wx1 = y0 + 4, y0 + 11, x0 + 4, x0 + 13
            base[wy0 - 1:wy1 + 1, wx0 - 1:wx1 + 1] = (w * 1.25).clip(0, 255)   # frame
            r = rng.random()
            if r < lit_ratio:
                col = [(255, 190, 100), (255, 170, 80), (255, 214, 150), (120, 190, 255),
                       (255, 120, 210), (190, 255, 170)][int(rng.choice(6, p=[.32, .26, .2, .1, .07, .05]))]
                col = np.array(col, np.float32)
                base[wy0:wy1, wx0:wx1] = col
                emit[wy0:wy1, wx0:wx1] = col
                # curtain / silhouette
                if rng.random() < 0.6:
                    k = int(rng.integers(2, 5))
                    base[wy0:wy1, wx0:wx0 + k] = (col * 0.55); emit[wy0:wy1, wx0:wx0 + k] = (col * 0.5)
                base[wy0:wy1, x0 + 8] = (w * 1.1).clip(0, 255); emit[wy0:wy1, x0 + 8] = 0
            else:
                base[wy0:wy1, wx0:wx1] = (14, 13, 22)
                base[wy0:wy1, x0 + 8] = (w * 1.1).clip(0, 255)
            if balcony:
                base[y0 + 11:y0 + 15, x0 + 2:x0 + 15] = (w * 0.75).astype(np.uint8)
                emit[y0 + 11:y0 + 15, x0 + 2:x0 + 15] = 0
    return _img(f"facade{seed}", base), _img(f"facade{seed}_e", emit)


def brick_tex(graffiti=True):
    from PIL import Image, ImageDraw, ImageFont
    W, H = 256, 96
    rng = np.random.default_rng(3)
    a = np.zeros((H, W, 3), np.uint8)
    for y in range(H):
        row = y // 4
        for x in range(W):
            xx = x + (4 if row % 2 else 0)
            mortar = (y % 4 == 0) or (xx % 8 == 0)
            brick_id = (row * 131 + (xx // 8) * 17) % 97
            k = 0.8 + 0.4 * ((brick_id * 37) % 11) / 11
            a[y, x] = (52, 48, 52) if mortar else (np.array((92, 50, 40)) * k).clip(0, 255)
    em = np.zeros_like(a)
    if graffiti:
        img = Image.fromarray(a); d = ImageDraw.Draw(img)
        eimg = Image.fromarray(em); de = ImageDraw.Draw(eimg)
        f1 = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 30)
        f2 = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
        for dd in (d, de):
            dd.fontmode = "1"
        d.text((12, 40), "ЭФИР", font=f1, fill=(240, 236, 244))
        d.text((10, 38), "ЭФИР", font=f1, fill=(255, 95, 210)); de.text((10, 38), "ЭФИР", font=f1, fill=(150, 50, 120))
        d.text((130, 20), "404", font=f1, fill=(20, 16, 22))
        d.text((128, 18), "404", font=f1, fill=(240, 236, 244))
        d.text((196, 60), "НЕ СПИ", font=f2, fill=(255, 154, 60)); de.text((196, 60), "НЕ СПИ", font=f2, fill=(110, 60, 20))
        for (cx, cy, r) in ((112, 62, 9), (232, 30, 12)):
            d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(255, 95, 210), width=2)
            d.line((cx - r - 4, cy, cx + r + 4, cy), fill=(255, 95, 210), width=1)
            d.line((cx, cy - r - 4, cx, cy + r + 4), fill=(255, 95, 210), width=1)
        a, em = np.array(img), np.array(eimg)
        # drips
        for x in (20, 47, 70, 140, 171):
            L = int(rng.integers(6, 22))
            a[70:70 + L, x] = (240, 236, 244)
    return _img("brick", a), _img("brick_e", em)


def asphalt_tex():
    rng = np.random.default_rng(5)
    a = (rng.normal(27, 4, (64, 64, 1)) * np.array([1.0, 0.96, 1.12])).clip(8, 60).astype(np.uint8)
    for _ in range(5):
        x, y = int(rng.integers(0, 64)), int(rng.integers(0, 64))
        for _ in range(26):
            a[y % 64, x % 64] = (12, 11, 16)
            x += int(rng.integers(-1, 2)); y += 1
    return _img("asphalt", a)


def kiosk_tex():
    from PIL import Image, ImageDraw, ImageFont
    W, H = 96, 80
    rng = np.random.default_rng(11)
    img = Image.new("RGB", (W, H), (44, 58, 74)); d = ImageDraw.Draw(img); d.fontmode = "1"
    em = Image.new("RGB", (W, H), (0, 0, 0)); de = ImageDraw.Draw(em); de.fontmode = "1"
    f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 11)
    # sign
    d.rectangle((2, 2, W - 3, 16), fill=(250, 240, 220)); de.rectangle((2, 2, W - 3, 16), fill=(210, 150, 80))
    d.text((6, 3), "ЭФИР 24 ЧАСА", font=f, fill=(190, 30, 60)); de.text((6, 3), "ЭФИР 24 ЧАСА", font=f, fill=(120, 20, 40))
    # window with shelves
    d.rectangle((6, 22, W - 7, 60), fill=(255, 214, 150)); de.rectangle((6, 22, W - 7, 60), fill=(255, 190, 110))
    cols = [(230, 60, 70), (70, 160, 230), (250, 230, 90), (120, 220, 140), (255, 120, 210), (240, 240, 240),
            (250, 140, 40)]
    for sy in (25, 37, 49):
        x = 8
        while x < W - 12:
            w = int(rng.integers(3, 6)); h = int(rng.integers(6, 10))
            c = cols[int(rng.integers(0, len(cols)))]
            d.rectangle((x, sy + 10 - h, x + w - 1, sy + 9), fill=c)
            de.rectangle((x, sy + 10 - h, x + w - 1, sy + 9), fill=tuple(int(v * 0.6) for v in c))
            x += w + 1
        d.line((6, sy + 10, W - 7, sy + 10), fill=(120, 90, 60))
    d.rectangle((40, 50, 56, 60), fill=(30, 26, 34)); de.rectangle((40, 50, 56, 60), fill=(0, 0, 0))   # hatch
    for x in range(6, W - 6, 15):
        d.line((x, 22, x, 60), fill=(60, 70, 84)); de.line((x, 22, x, 60), fill=(0, 0, 0))
    d.rectangle((0, 62, W, H), fill=(36, 46, 60))
    for x in range(0, W, 6):
        d.line((x, 62, x, H), fill=(28, 36, 48))
    return _img("kiosk", np.array(img)), _img("kiosk_e", np.array(em))


def checker_tex():
    a = np.zeros((2, 2, 3), np.uint8)
    a[0, 0] = a[1, 1] = (255, 0, 220)
    return _img("void", a)


def stripe_tex():
    a = np.zeros((4, 16, 3), np.uint8)
    for x in range(16):
        a[:, x] = (225, 40, 50) if (x // 4) % 2 == 0 else (236, 234, 240)
    return _img("stripe", a)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
class World:
    pass


def build_world(sc):
    W = World()
    rnd = random.Random(404)
    col = bpy.data.collections.new("World"); sc.collection.children.link(col)
    mb = C.MeshBuilder()

    asphalt = C.tex_mat("asphalt", asphalt_tex(), rough=0.55)
    asphalt.node_tree.nodes[0].inputs["Specular IOR Level"].default_value = 0.35
    curb = C.flat_mat("curb", "#3b3944")
    dirt = C.flat_mat("dirt", "#17161b")
    concrete = C.flat_mat("concrete", "#45424e")
    conc_d = C.flat_mat("concrete_d", "#26242c")
    metal = C.flat_mat("metal", "#2b3238", rough=0.6)
    rust = C.flat_mat("rust", "#4a2f25")
    black = C.flat_mat("black", "#09080c")
    brick_b, brick_e = brick_tex()
    brick = C.tex_mat("brick", brick_b, brick_e, emit_strength=0.6)
    fac = [C.tex_mat(f"facade{i}", *facade_tex(i, wall=w, lit_ratio=r), emit_strength=2.6)
           for i, (w, r) in enumerate((("#3d3a47", 0.20), ("#35333f", 0.14), ("#443f49", 0.26)))]
    kb, ke = kiosk_tex()
    kiosk = C.tex_mat("kiosk", kb, ke, emit_strength=3.2, pulse=0.25)
    lamp_glow = C.glow_mat("lamp_glow", SODIUM, strength=14.0, pulse=0.9)
    cone = C.glow_mat("lamp_cone", SODIUM, strength=0.9, alpha=0.085, pulse=0.9, fresnel=True,
                      gradient_z=(0.0, 7.2))
    red_glow = C.glow_mat("red_glow", "#ff2a3a", strength=10.0, pulse=1.0)
    car_p = C.flat_mat("car_paint", "#3f5560", rough=0.35, spec=0.4)
    car_g = C.flat_mat("car_glass", "#0d1218", rough=0.1, spec=0.5)
    head_l = C.glow_mat("headlight", "#ffe9b0", strength=5.0)
    door_glow = C.glow_mat("door_glow", "#b8ffd8", strength=4.0, pulse=0.3)

    # --- ground -------------------------------------------------------------------
    X0, X1 = -40.0, 120.0
    mb.quad([(X0, -9, 0), (X1, -9, 0), (X1, 3.6, 0), (X0, 3.6, 0)], asphalt,
            [(X0 / 4, -9 / 4), (X1 / 4, -9 / 4), (X1 / 4, 3.6 / 4), (X0 / 4, 3.6 / 4)])
    mb.quad([(X0, -40, 0), (X1, -40, 0), (X1, -9, 0), (X0, -9, 0)], dirt)
    mb.box((X0, 3.6, 0), (43.0, 6.6, 0.16), curb)
    mb.box((57.0, 3.6, 0), (X1, 6.6, 0.16), curb)
    mb.quad([(X0, 6.6, 0), (X1, 6.6, 0), (X1, 60, 0), (X0, 60, 0)], dirt)
    # road paint
    paint = C.flat_mat("paint", "#8f8c98")
    for x in range(-36, 118, 6):
        mb.box((x, -2.6, 0.0), (x + 2.4, -2.45, 0.012), paint)

    # --- panel blocks (far side) ------------------------------------------------
    def block(x0, x1, y0, y1, h, f, roof=True):
        uv = C.world_uv(24.0, 22.4, rnd.randint(0, 7) / 8, rnd.randint(0, 7) / 8)
        mb.box((x0, y0, 0), (x1, y1, h), fac[f], uv_fn=uv, mats={"z+": conc_d, "z-": conc_d})
        if roof:
            for _ in range(3):
                rx = rnd.uniform(x0 + 2, x1 - 4)
                mb.box((rx, y0 + 2, h), (rx + rnd.uniform(1.5, 3), y0 + 5, h + rnd.uniform(1.2, 2.6)), conc_d)
                mb.box((rx + 0.5, y0 + 2.5, h), (rx + 0.6, y0 + 2.6, h + rnd.uniform(3, 6)), black)

    block(-38, -8, 9, 22, 27, 0)
    block(-4, 34, 7.2, 20, 15, 2)           # five-storey behind the kiosk
    block(60, 104, 8, 22, 27, 1)
    block(10, 60, 34, 48, 36, 0)
    block(-40, 0, 40, 54, 30, 1)
    block(70, 118, 44, 58, 42, 2)
    block(-30, 20, -34, -22, 27, 1)          # behind the camera side
    block(40, 96, -38, -24, 30, 0)

    # --- transformer station: the wall-run wall ---------------------------------
    uvb = lambda side, pts: [((p[0] - 43.0) / 14.0, p[2] / 5.25) for p in pts]
    mb.box((43.0, 3.0, 0), (57.0, 9.0, 5.25), brick, uv_fn=C.world_uv(14.0, 5.25, -43 / 14.0, 0),
           mats={"z+": conc_d})
    mb.box((43.0, 3.0, -7), (57.0, 9.0, 0), black)
    mb.box((42.8, 2.9, 5.25), (57.2, 9.1, 5.5), conc_d)

    # --- kiosk -----------------------------------------------------------------
    kuv = lambda side, pts: [((p[0] - 0.0) / 3.2, p[2] / 2.7) for p in pts]
    mb.box((0.0, 5.0, 0.16), (3.2, 7.0, 2.86), metal, mats={"y-": kiosk},
           uv_fn=lambda side, pts: [((p[0]) / 3.2, (p[2] - 0.16) / 2.7) for p in pts])
    mb.box((-0.2, 4.2, 2.86), (3.4, 7.1, 2.96), conc_d)                    # awning
    W.kiosk_pos = Vector((1.6, 4.9, 1.6))

    # --- garages ("rakushki") ---------------------------------------------------
    for i, gx in enumerate((36.0, 39.2)):
        mb.box((gx, 7.0, 0), (gx + 3.0, 12, 2.4 + 0.2 * i), rust if i else metal)

    # --- lamp posts + wires ------------------------------------------------------
    W.lamps = []
    lamp_xs = [-22, -6, 10, 26, 40, 62, 78, 94]
    for i, lx in enumerate(lamp_xs):
        ly = 5.6
        mb.box((lx - 0.1, ly - 0.1, 0), (lx + 0.1, ly + 0.1, 7.4), concrete)
        mb.box((lx - 0.06, 3.9, 7.25), (lx + 0.06, ly, 7.37), concrete)
        mb.box((lx - 0.16, 3.5, 7.16), (lx + 0.16, 4.1, 7.26), lamp_glow)
        W.lamps.append((lx, 3.8, 7.1))
        # wires to the next pole (3 sagging segments)
        if i + 1 < len(lamp_xs):
            nx = lamp_xs[i + 1]
            for wy, wz in ((5.45, 6.9), (5.75, 6.5)):
                pts = [(lx + (nx - lx) * t, wy, wz - 0.9 * math.sin(math.pi * t)) for t in
                       (0, 0.25, 0.5, 0.75, 1)]
                for a, b in zip(pts, pts[1:]):
                    mb.quad([(a[0], a[1], a[2]), (b[0], b[1], b[2]), (b[0], b[1], b[2] + 0.035),
                             (a[0], a[1], a[2] + 0.035)], black)
    # light cones (fake volumetrics) in a separate object
    cb = C.MeshBuilder()
    for (lx, ly, lz) in [l for l in W.lamps if l[0] in (-6, 10, 26, 62)]:
        n = 8
        for k in range(n):
            a0, a1 = 2 * math.pi * k / n, 2 * math.pi * (k + 1) / n
            r0, r1 = 3.4, 0.2
            cb.quad([(lx + r0 * math.cos(a0), ly + r0 * math.sin(a0) - 0.6, 0.02),
                     (lx + r0 * math.cos(a1), ly + r0 * math.sin(a1) - 0.6, 0.02),
                     (lx + r1 * math.cos(a1), ly + r1 * math.sin(a1), lz),
                     (lx + r1 * math.cos(a0), ly + r1 * math.sin(a0), lz)], cone)
    W.cones = cb.build("LampCones", col)
    W.cones.visible_shadow = False

    # --- bench by the kiosk --------------------------------------------------------
    mb.box((4.6, 4.75, 0.50), (6.5, 5.25, 0.58), rust)
    mb.box((4.6, 5.22, 0.58), (6.5, 5.30, 1.0), rust)
    for bx in (4.75, 6.35):
        mb.box((bx - 0.05, 4.8, 0.16), (bx + 0.05, 5.25, 0.5), black)

    # --- parked car (vault) ------------------------------------------------------
    cx = 36.0
    mb.box((cx - 0.85, -1.2, 0.28), (cx + 0.85, 3.0, 0.82), car_p)
    mb.box((cx - 0.78, 0.3, 0.82), (cx + 0.78, 2.3, 1.32), car_g, top_scale=(0.9, 0.8),
           mats={"z+": car_p})
    for wy in (-0.5, 2.3):
        for sx in (-1, 1):
            mb.box((cx + sx * 0.8 - 0.1, wy - 0.3, 0), (cx + sx * 0.8 + 0.1, wy + 0.3, 0.6), black)
    for sx in (-1, 1):
        mb.box((cx + sx * 0.55 - 0.18, -1.23, 0.55), (cx + sx * 0.55 + 0.18, -1.19, 0.72), head_l)

    # --- plaza: podyezd door, bench, heating pipes -------------------------------
    mb.box((65.2, 7.6, 0), (67.0, 8.05, 2.5), conc_d)
    mb.box((65.5, 7.55, 0.16), (66.7, 7.62, 2.2), door_glow)
    mb.box((64.8, 6.9, 2.5), (67.4, 8.0, 2.65), concrete)
    mb.box((69.0, 5.0, 0.4), (71.2, 5.5, 0.5), rust)
    for bx in (69.2, 71.0):
        mb.box((bx - 0.05, 5.05, 0), (bx + 0.05, 5.45, 0.4), black)
    for px0, px1 in ((-40, 20.5), (27.5, 120)):
        mb.box((px0, -8.2, 0.9), (px1, -7.6, 1.5), C.flat_mat("pipe", "#6d6a70"))
    for px in (20.5, 27.5):
        mb.box((px - 0.3, -8.2, 0.9), (px + 0.3, -7.6, 4.6), C.flat_mat("pipe", "#6d6a70"))
    mb.box((20.2, -8.2, 4.0), (27.8, -7.6, 4.6), C.flat_mat("pipe", "#6d6a70"))
    for px in range(-38, 118, 6):
        if 20 < px < 28:
            continue
        mb.box((px - 0.1, -8.0, 0), (px + 0.1, -7.8, 0.9), black)
    # playground swing silhouette near the camera side
    for sx in (12.0, 15.0):
        mb.box((sx - 0.05, -6.6, 0), (sx + 0.05, -6.5, 2.4), rust)
    mb.box((11.9, -6.6, 2.35), (15.1, -6.5, 2.45), rust)

    # --- rooftop stage for the title shot ----------------------------------------
    RX, RZ = 150.0, 30.0
    mb.box((RX - 14, -6, RZ - 30), (RX + 14, 8, RZ), fac[1], uv_fn=C.world_uv(24, 22.4),
           mats={"z+": conc_d})
    mb.box((RX - 14, -6, RZ), (RX + 14, -5.5, RZ + 0.45), concrete)       # parapet (front)
    mb.box((RX + 3, 2, RZ), (RX + 7, 6, RZ + 2.6), conc_d)
    mb.box((RX - 9, 3, RZ), (RX - 8.9, 3.1, RZ + 7), black)
    for k in range(4):
        mb.box((RX - 9.8, 3.03, RZ + 4.5 + k * 0.6), (RX - 8.1, 3.07, RZ + 4.55 + k * 0.6), black)
    W.roof = Vector((RX, -5.75, RZ + 0.45))
    for (bx0, bx1, by, bh, f) in ((118, 146, 46, 46, 0), (152, 186, 52, 58, 2), (100, 124, 80, 64, 1),
                                 (170, 200, 84, 70, 0)):
        uv = C.world_uv(24.0, 22.4, rnd.randint(0, 7) / 8, rnd.randint(0, 7) / 8)
        mb.box((bx0, by, 0), (bx1, by + 14, bh), fac[f], uv_fn=uv, mats={"z+": conc_d})

    W.static = mb.build("District", col)

    # --- radio tower + moon + stars (no fog: they live in the sky) ---------------
    sk = C.MeshBuilder()
    sil = C.glow_mat("silhouette", "#07060a", strength=1.0)
    TX, TY, TH = 150.0, 130.0, 110.0
    for k in range(11):
        z0, z1 = TH * k / 11, TH * (k + 1) / 11
        w0, w1 = 9 * (1 - k / 12), 9 * (1 - (k + 1) / 12)
        for sx in (-1, 1):
            sk.quad([(TX + sx * w0, TY, z0), (TX + sx * w0 + 0.7, TY, z0), (TX + sx * w1 + 0.7, TY, z1),
                     (TX + sx * w1, TY, z1)], sil)
        sk.quad([(TX - w1, TY, z1 - 0.5), (TX + w1, TY, z1 - 0.5), (TX + w1, TY, z1), (TX - w1, TY, z1)], sil)
        sk.quad([(TX - w0, TY, z0), (TX - w0 + 0.6, TY, z0), (TX + w1, TY, z1), (TX + w1 - 0.6, TY, z1)], sil)
    sk.box((TX - 0.4, TY - 0.4, TH), (TX + 0.4, TY + 0.4, TH + 26), sil)
    sk.box((TX - 1.2, TY - 1.2, TH + 26), (TX + 1.2, TY + 1.2, TH + 28.4), red_glow)
    for tz in (40, 75):
        sk.box((TX - 0.9, TY - 0.9, tz), (TX + 0.9, TY + 0.9, tz + 1.8), red_glow)
    moon = C.glow_mat("moon", "#f3dbe6", strength=1.5)
    mx, my, mz, mr = 118.0, 300.0, 118.0, 34.0
    n = 20
    for k in range(n):
        a0, a1 = 2 * math.pi * k / n, 2 * math.pi * (k + 1) / n
        sk.quad([(mx, my, mz), (mx + mr * math.cos(a0), my, mz + mr * math.sin(a0)),
                 (mx + mr * math.cos(a1), my, mz + mr * math.sin(a1))], moon, [(0, 0), (1, 0), (1, 1)])
    star = C.glow_mat("star", "#d8ccff", strength=2.2)
    for _ in range(260):
        th, ph = rnd.uniform(0, 2 * math.pi), rnd.uniform(0.10, 1.2)
        R = 420
        p = Vector((60 + R * math.cos(th) * math.cos(ph), R * math.sin(th) * math.cos(ph), R * math.sin(ph)))
        s = rnd.choice((0.7, 0.7, 1.0, 1.5))
        right = Vector((-math.sin(th), math.cos(th), 0)) * s
        up = Vector((0, 0, s))
        sk.quad([p - right - up, p + right - up, p + right + up, p - right + up], star)
    W.sky = sk.build("Sky", col)
    W.sky.visible_shadow = False
    W.tower = Vector((TX, TY, TH + 27))

    # broadcast rings on the tower (scale-animated on every bar)
    rm = C.glow_mat("ring", PINK, strength=3.0, alpha=0.5, obj_alpha=True)
    W.rings = []
    for i in range(3):
        rb = C.MeshBuilder()
        n = 28
        for k in range(n):
            a0, a1 = 2 * math.pi * k / n, 2 * math.pi * (k + 1) / n
            r0, r1 = 1.0, 1.06
            rb.quad([(r0 * math.cos(a0), 0, r0 * math.sin(a0)), (r0 * math.cos(a1), 0, r0 * math.sin(a1)),
                     (r1 * math.cos(a1), 0, r1 * math.sin(a1)), (r1 * math.cos(a0), 0, r1 * math.sin(a0))], rm)
        ob = rb.build(f"Ring{i}", col)
        ob.location = W.tower
        ob.visible_shadow = False
        W.rings.append(ob)

    # --- real lights -------------------------------------------------------------
    W.lights = []

    def light(kind, loc, energy, color, **kw):
        ld = bpy.data.lights.new("L", kind)
        ld.energy = energy
        ld.color = C.lin(color)[:3]
        for k, v in kw.items():
            if k != "rot":
                setattr(ld, k, v)
        ob = bpy.data.objects.new("L_" + kind, ld)
        ob.location = loc
        if "rot" in kw:
            ob.rotation_euler = [math.radians(a) for a in kw["rot"]]
        col.objects.link(ob)
        W.lights.append(ob)
        return ob

    for (lx, ly, lz) in W.lamps:
        light("SPOT", (lx, ly, lz - 0.1), 9000, SODIUM, spot_size=math.radians(128), spot_blend=0.55,
              shadow_soft_size=0.25, rot=(8, 0, 0))
    W.kiosk_light = light("AREA", (1.6, 4.55, 1.9), 420, "#ffcf96", size=2.4, rot=(98, 0, 0))
    light("AREA", (66.1, 7.2, 1.6), 260, "#b8ffd8", size=1.2, rot=(95, 0, 0))
    light("AREA", (150.0, -9.5, 33.0), 900, "#8a6cff", size=8.0, rot=(72, 0, 0))    # roof fill
    light("AREA", (150.0, 3.0, 36.5), 1300, PINK, size=6.0, rot=(-40, 0, 0))        # roof rim

    # --- world shader --------------------------------------------------------------
    world = bpy.data.worlds.new("Night")
    sc.world = world
    world.use_nodes = True
    N, L = world.node_tree.nodes, world.node_tree.links
    N.clear()
    out = N.new("ShaderNodeOutputWorld")
    geo = N.new("ShaderNodeNewGeometry")
    sep = N.new("ShaderNodeSeparateXYZ")
    L.new(geo.outputs["Incoming"], sep.inputs[0])
    mr_ = N.new("ShaderNodeMapRange")
    mr_.inputs["From Min"].default_value = -0.02
    mr_.inputs["From Max"].default_value = -0.55
    L.new(sep.outputs["Z"], mr_.inputs["Value"])
    p = N.new("ShaderNodeMath"); p.operation = "POWER"; p.inputs[1].default_value = 0.6
    L.new(mr_.outputs[0], p.inputs[0])
    mix = N.new("ShaderNodeMixRGB")
    fc = N.new("ShaderNodeGroup"); fc.node_tree = C.fog_color_group()
    L.new(p.outputs[0], mix.inputs[0])
    L.new(fc.outputs[0], mix.inputs[1])
    mix.inputs[2].default_value = C.lin("#06040c")
    lp = N.new("ShaderNodeLightPath")
    cam_bg = N.new("ShaderNodeBackground"); L.new(mix.outputs[0], cam_bg.inputs[0])
    amb = N.new("ShaderNodeBackground")
    amb.inputs[0].default_value = C.lin("#2a2a4a"); amb.inputs[1].default_value = 0.16
    amb.name = "Ambient"
    ms = N.new("ShaderNodeMixShader")
    L.new(lp.outputs["Is Camera Ray"], ms.inputs[0])
    L.new(amb.outputs[0], ms.inputs[1]); L.new(cam_bg.outputs[0], ms.inputs[2])
    L.new(ms.outputs[0], out.inputs[0])
    W.world = world
    return W


def build_speaker(sc):
    """КОЛОНКА — the portable speaker everybody is fighting for. Whoever carries it
    picks the track. Two glowing rings + a light that pulses with the beat."""
    col = sc.collection
    root = bpy.data.objects.new("Speaker", None)
    col.objects.link(root)
    body_m = C.flat_mat("spk_body", "#141318", rough=0.45, spec=0.3, fog=0)
    ring_m = C.glow_mat("spk_ring", PINK, strength=10.0, pulse=1.2)
    cone_m = C.flat_mat("spk_cone", "#2a2830", rough=0.6, fog=0)
    mb = C.MeshBuilder()
    n, L, r = 12, 0.26, 0.115
    for k in range(n):
        a0, a1 = 2 * math.pi * k / n, 2 * math.pi * (k + 1) / n
        p = lambda a, x, rr=r: (x, rr * math.cos(a), rr * math.sin(a))
        mb.quad([p(a0, -L), p(a0, L), p(a1, L), p(a1, -L)], body_m)
        for sx in (-1, 1):
            e0, e1 = sx * L, sx * (L + 0.012)
            mb.quad([p(a0, e0, r * 1.04), p(a0, e1, r * 1.04), p(a1, e1, r * 1.04), p(a1, e0, r * 1.04)], ring_m)
            mb.quad([(e1, 0, 0), p(a0, e1, r * 0.92), p(a1, e1, r * 0.92)], cone_m, [(0, 0), (1, 0), (1, 1)])
            mb.quad([p(a0, e1, r * 0.92), p(a0, e1, r * 1.04), p(a1, e1, r * 1.04), p(a1, e1, r * 0.92)], ring_m)
    mb.box((-0.16, -0.02, r), (0.16, 0.02, r + 0.035), body_m)       # handle
    body = mb.build("SpeakerBody", col)
    ld = bpy.data.lights.new("SpeakerLight", "POINT")
    ld.energy = 260; ld.color = C.lin("#ff8fe0")[:3]; ld.shadow_soft_size = 0.2
    lo = bpy.data.objects.new("SpeakerLight", ld); col.objects.link(lo)
    lo.location = (0, 0, 0.22)
    for o in (body, lo):
        o.parent = root
    return root, lo
