"""STRELKA — post pass: grade, bloom, impact frames, phone HUD, captions, encode.

    python3 post.py <frames_dir> <track.wav> <out.mp4> [--preview N]
"""
import json
import math
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

FD = "/usr/share/fonts/truetype/"
F_TITLE = FD + "liberation/LiberationSans-BoldItalic.ttf"
F_BOLD = FD + "dejavu/DejaVuSans-Bold.ttf"
F_MONO = FD + "dejavu/DejaVuSansMono.ttf"
PINK = (255, 95, 210)
W, H = 1920, 804


def font(path, size):
    return ImageFont.truetype(path, size)


def smooth(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def grade(a):
    lum = a @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    a = lum[..., None] + (a - lum[..., None]) * 0.80                    # pull the colour back
    a = a * np.array([0.98, 0.99, 1.06], np.float32)                     # cooler
    a = np.clip(a, 0, 1)
    a = a * a * (3 - 2 * a) * 0.40 + a * 0.60                            # contrast
    a = np.where(a > 0.7, 0.7 + (a - 0.7) * 0.6, a)                      # soft highlight roll-off
    return a


def bloom(img, amt=0.26):
    a = np.asarray(img, np.float32) / 255
    hi = np.clip(a - 0.66, 0, 1) * 3.0
    b = Image.fromarray((np.clip(hi, 0, 1) * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(9))
    b2 = b.filter(ImageFilter.GaussianBlur(22))
    out = a + (np.asarray(b, np.float32) / 255) * amt + (np.asarray(b2, np.float32) / 255) * amt * 0.6
    return np.clip(out, 0, 1)


def ink_frame(a, seed):
    """Anime-style impact frame: white void, ink contours, pink where it was hot."""
    lum = a @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    gx = np.abs(np.diff(lum, axis=1, prepend=lum[:, :1]))
    gy = np.abs(np.diff(lum, axis=0, prepend=lum[:1]))
    edge = np.clip((gx + gy) * 9.0, 0, 1)
    out = np.ones_like(a)
    out *= (1 - edge)[..., None]
    hot = np.clip((lum - 0.55) * 3, 0, 1)[..., None]
    out = out * (1 - hot * 0.75) + np.array(PINK, np.float32) / 255 * hot * 0.75
    dark = (lum < 0.06)[..., None]
    out = np.where(dark, out * 0.25, out)
    img = Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8))
    d = ImageDraw.Draw(img)
    rng = np.random.default_rng(seed)
    for _ in range(14):                                     # tracking markers
        x, y = int(rng.integers(20, a.shape[1] - 20)), int(rng.integers(20, a.shape[0] - 20))
        s = int(rng.integers(5, 12))
        col = PINK if rng.random() < 0.5 else (20, 16, 24)
        d.line((x - s, y, x + s, y), fill=col, width=1); d.line((x, y - s, x, y + s), fill=col, width=1)
        if rng.random() < 0.35:
            d.ellipse((x - s, y - s, x + s, y + s), outline=PINK, width=2)
    return np.asarray(img, np.float32) / 255


def chroma(a, px):
    if px <= 0:
        return a
    out = a.copy()
    out[:, px:, 0] = a[:, :-px, 0]
    out[:, :-px, 2] = a[:, px:, 2]
    return out


def chrome_text(size_wh, text, fnt, fill_top=(250, 250, 255), fill_bot=(120, 120, 140), stroke=(8, 8, 12),
                glow=None, spacing=0):
    """Y2K chrome italic lettering on a transparent layer."""
    w, h = size_wh
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    bb = d.textbbox((0, 0), text, font=fnt)
    x, y = (w - (bb[2] - bb[0])) // 2 - bb[0], (h - (bb[3] - bb[1])) // 2 - bb[1]
    d.text((x, y), text, font=fnt, fill=255)
    grad = np.zeros((h, w, 4), np.uint8)
    t = np.clip((np.arange(h) - (y + bb[1])) / max(1, (bb[3] - bb[1])), 0, 1)
    band = np.where(t < 0.52, t / 0.52, 1 - (t - 0.52) / 0.48 * 0.75)          # bright horizon line
    for c in range(3):
        grad[..., c] = (fill_bot[c] + (fill_top[c] - fill_bot[c]) * band)[:, None]
    grad[..., 3] = np.asarray(mask)
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    om = Image.new("L", (w, h), 0)
    ImageDraw.Draw(om).text((x, y), text, font=fnt, fill=255, stroke_width=max(2, fnt.size // 22), stroke_fill=255)
    if glow:
        g = om.filter(ImageFilter.GaussianBlur(fnt.size // 5))
        layer.paste(Image.new("RGBA", (w, h), glow + (255,)), (0, 0), g.point(lambda v: int(v * 0.7)))
    layer.paste(Image.new("RGBA", (w, h), stroke + (255,)), (0, 0), om)
    layer.alpha_composite(Image.fromarray(grad))
    return layer


def phone(lines, soft=("Выбор", "Назад"), bars=4, clock="04:04"):
    """A candy-bar phone, ~2005. The game's HUD lives on this screen."""
    w, h = 300, 560
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((8, 8, w - 8, h - 8), 44, fill=(16, 15, 20, 255), outline=(70, 68, 80, 255), width=3)
    d.rounded_rectangle((20, 20, w - 20, h - 20), 36, outline=(255, 140, 40, 255), width=2)
    sx0, sy0, sx1, sy1 = 44, 70, w - 44, 330
    d.rectangle((sx0 - 6, sy0 - 6, sx1 + 6, sy1 + 6), fill=(8, 8, 10, 255))
    d.rectangle((sx0, sy0, sx1, sy1), fill=(196, 222, 226, 255))
    for y in range(sy0, sy1, 3):
        d.line((sx0, y, sx1, y), fill=(186, 212, 217, 255))
    ink = (24, 34, 44, 255)
    fs, fm = font(F_BOLD, 17), font(F_BOLD, 25)
    for i in range(4):                                      # signal bars
        hh = 5 + i * 4
        col = ink if i < bars else (150, 176, 182, 255)
        d.rectangle((sx0 + 8 + i * 8, sy0 + 26 - hh, sx0 + 13 + i * 8, sy0 + 26), fill=col)
    d.text((sx1 - 62, sy0 + 7), clock, font=fs, fill=ink)
    d.line((sx0 + 6, sy0 + 34, sx1 - 6, sy0 + 34), fill=ink, width=2)
    y = sy0 + 46
    for ln in lines:
        d.text((sx0 + 12, y), ln, font=fm, fill=ink)
        y += 34
    d.line((sx0 + 6, sy1 - 34, sx1 - 6, sy1 - 34), fill=ink, width=2)
    d.text((sx0 + 10, sy1 - 28), soft[0], font=fs, fill=ink)
    tw = d.textlength(soft[1], font=fs)
    d.text((sx1 - 10 - tw, sy1 - 28), soft[1], font=fs, fill=ink)
    d.ellipse((w // 2 - 34, 356, w // 2 + 34, 424), fill=(255, 150, 40, 255), outline=(60, 40, 20, 255), width=3)
    d.ellipse((w // 2 - 14, 376, w // 2 + 14, 404), fill=(30, 26, 30, 255))
    for i, x in enumerate((70, w - 70)):
        d.rounded_rectangle((x - 30, 372, x + 30, 406), 10, fill=(34, 32, 40, 255), outline=(255, 140, 40, 255))
    for r in range(3):
        for c in range(3):
            d.rounded_rectangle((62 + c * 62, 440 + r * 34, 114 + c * 62, 466 + r * 34), 8, fill=(30, 28, 36, 255),
                                outline=(60, 58, 70, 255))
    d.rounded_rectangle((w // 2 - 26, 36, w // 2 + 26, 44), 4, fill=(40, 38, 46, 255))
    return im


def run(frames_dir, wav, out_mp4, preview=None):
    meta = json.load(open(os.path.join(frames_dir, "shots.json")))
    fpb, fps, beats = meta["fpb"], meta["fps"], meta["beats"]
    impacts = meta["impacts"]
    total = 1 + beats * fpb - 1
    tmp = os.path.join(frames_dir, "post")
    os.makedirs(tmp, exist_ok=True)
    f_cap, f_big, f_small = font(F_TITLE, 58), font(F_TITLE, 250), font(F_TITLE, 44)
    f_time = font(F_MONO, 30)
    captions = [(9.0, 15.4, "ОНИ ПРИШЛИ ЗА КОЛОНКОЙ"), (16.4, 19.9, "КАЖДЫЙ УДАР — В БИТ"),
                (22.2, 24.4, "БЛОК.  ОТВЕТ."), (26.6, 29.2, "У КОГО КОЛОНКА — ТОГО И ДВОР")]
    cap_layers = {t: chrome_text((W, 110), t, f_cap) for _, _, t in captions}
    title = chrome_text((W, 330), "СТРЕЛКА", f_big, glow=PINK)
    sub = chrome_text((W, 80), "двор на двор  ·  04:04  ·  концепт PvP для Roblox", f_small)
    shukher = chrome_text((W, 330), "ШУХЕР.", font(F_TITLE, 210), fill_top=(255, 90, 100), fill_bot=(120, 20, 40))
    shukher_sub = chrome_text((W, 80), "музыка стихла — все врассыпную", f_small)
    ph_a = phone(["1 новое", "сообщение"], soft=("Читать", "Назад"))
    ph_b = phone(["СТРЕЛКА.", "ДВОР.", "04:04"], soft=("Выбор", "Назад"))
    ph_c = phone(["НЕТ СЕТИ", "", "тихо."], soft=("", "Назад"), bars=0)
    frames = range(1, total + 1) if preview is None else preview
    for f in frames:
        src = os.path.join(frames_dir, f"f_{f:04d}.png")
        if not os.path.exists(src):
            continue
        beat = (f - 1) / fpb
        a = np.asarray(Image.open(src).convert("RGB"), np.float32) / 255
        a = grade(a)
        a = bloom(Image.fromarray((a * 255).astype(np.uint8)))
        # impact frames
        k_imp, since = 0.0, 99
        for (ib, amt) in impacts:
            df = f - (1 + ib * fpb)
            if 0 <= df < 7:
                k_imp, since = amt, int(round(df))
        if since == 0:
            a = ink_frame(a, f)
        elif since == 1:
            a = 1.0 - a * np.array([1.0, 0.9, 0.95], np.float32)
            a = a * 0.9
        elif since < 7:
            a = chroma(a, int(round((7 - since) * 1.4 * k_imp)))
            a = np.clip(a * (1 + 0.10 * k_imp * (7 - since) / 6), 0, 1)
        # beat flash (drop sections)
        if (16 <= beat < 32) or (40 <= beat < 49):
            ph = beat - math.floor(beat)
            a = np.clip(a * (1 + 0.07 * math.exp(-ph * 6)), 0, 1)
        # vignette + grain
        hh, ww = a.shape[:2]
        yy, xx = np.mgrid[0:hh, 0:ww].astype(np.float32)
        v = 1 - 0.42 * (((xx / ww - 0.5) * 1.15) ** 2 + ((yy / hh - 0.5) * 1.3) ** 2) * 2
        a = a * np.clip(v, 0, 1)[..., None]
        a = a + np.random.default_rng(f).normal(0, 0.018, a.shape[:2])[..., None]
        img = Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8)).resize((W, H), Image.LANCZOS).convert("RGBA")
        d = ImageDraw.Draw(img)
        # camcorder clock
        if beat < 40 and since != 0:
            sec = int(beat * 60 / 160)
            d.text((54, 40), f"04:04:{sec:02d}", font=f_time, fill=(235, 235, 240, 210))
            if int(beat * 2) % 2 == 0:
                d.ellipse((30, 49, 44, 63), fill=(255, 60, 70, 230))
        # phone HUD
        def put_phone(ph, k, x=1570):
            y = int(H - 20 - 540 * smooth(k))
            img.alpha_composite(ph, (x, y))
        if 1.2 <= beat < 8:
            k = min(smooth((beat - 1.2) / 0.8), smooth((8 - beat) / 0.5))
            put_phone(ph_a if beat < 3.6 else ph_b, k)
        if 33.2 <= beat < 39.8:
            k = min(smooth((beat - 33.2) / 0.7), smooth((39.8 - beat) / 0.5))
            put_phone(ph_c, k, x=70)
        # captions
        for (b0, b1, text) in captions:
            if b0 <= beat < b1:
                k = min(smooth((beat - b0) / 0.35), smooth((b1 - beat) / 0.3))
                lay = cap_layers[text].copy()
                lay.putalpha(lay.getchannel("A").point(lambda v, k=k: int(v * k)))
                img.alpha_composite(lay, (int((1 - k) * -40), H - 150))
        if 32.5 <= beat < 39.6 and since != 0:
            k = min(smooth((beat - 32.5) / 0.3), smooth((39.6 - beat) / 0.4))
            for lay, y in ((shukher, 200), (shukher_sub, 500)):
                l2 = lay.copy(); l2.putalpha(l2.getchannel("A").point(lambda v, k=k: int(v * k)))
                img.alpha_composite(l2, (0, y))
        if beat >= 40.25:
            k = smooth((beat - 40.25) / 0.25)
            z = 1.0 + 0.25 * (1 - smooth((beat - 40.25) / 0.6))
            t2 = title.resize((int(W * z), int(330 * z)), Image.LANCZOS)
            t2.putalpha(t2.getchannel("A").point(lambda v, k=k: int(v * k)))
            img.alpha_composite(t2, (int((W - t2.width) / 2), int(205 - (t2.height - 330) / 2)))
            if beat >= 42:
                k2 = smooth((beat - 42) / 0.6)
                s2 = sub.copy(); s2.putalpha(s2.getchannel("A").point(lambda v, k=k2: int(v * k)))
                img.alpha_composite(s2, (0, 560))
        # beat ticks: the on-screen metronome the player times against
        if (16 <= beat < 32) or (40 <= beat < 48):
            cur = int(beat) % 4
            ph = beat - math.floor(beat)
            for i in range(4):
                x = W // 2 - 66 + i * 44
                on = i == cur
                s = 13 + (5 * math.exp(-ph * 7) if on else 0)
                col = PINK + (255,) if on else (235, 235, 240, 110)
                d.rectangle((x - s, H - 44 - s, x + s, H - 44 + s), fill=col if on else None, outline=col, width=3)
        if beat > 54:                                       # fade out
            k = smooth((56 - beat) / 2)
            img = Image.blend(Image.new("RGBA", img.size, (0, 0, 0, 255)), img, k)
        img.convert("RGB").save(os.path.join(tmp, f"p_{f:04d}.png"), compress_level=1)
    if preview is not None:
        return tmp
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-start_number", "1",
           "-i", os.path.join(tmp, "p_%04d.png"), "-i", wav, "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-crf", "18", "-preset", "slow", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart",
           out_mp4]
    subprocess.run(cmd, check=True)
    return out_mp4


if __name__ == "__main__":
    args = sys.argv[1:]
    prev = None
    if "--preview" in args:
        i = args.index("--preview")
        prev = [int(x) for x in args[i + 1:]]
        args = args[:i]
    print(run(args[0], args[1], args[2], prev))
