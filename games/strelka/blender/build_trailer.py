"""STRELKA — concept trailer. Builds the whole scene procedurally and renders it.

    python3 build_trailer.py --still 150            # one test frame
    python3 build_trailer.py --frames 1 504         # render a range (PNG sequence)
    python3 build_trailer.py --save                 # write ../assets/strelka_trailer.blend

24 fps, 160 BPM -> exactly 9 frames per beat. Every hit below lands on a beat.
"""
import argparse
import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy
from mathutils import Euler, Matrix, Quaternion, Vector

import da_characters as CH
import da_clips as K
import da_common as C
import da_world as WD

FPS, FPB = 24, 9
TOTAL_BEATS = 56


def F(beat):
    return 1 + beat * FPB


# shots: (start beat, name)
IMPACTS = [(19.0, 0.8), (21.0, 1.0), (23.0, 0.5), (24.0, 0.8), (30.0, 1.4), (40.0, 1.0)]


class Mover:
    """Root motion for one character: linear keys, with hard cuts."""

    def __init__(self, arm):
        self.arm = arm
        arm.rotation_mode = "XYZ"

    def key(self, beat, pos, heading=None, cut=False):
        f = F(beat)
        if cut:
            # hold the previous transform until the frame before the cut
            self.arm.keyframe_insert("location", frame=f - 1)
            self.arm.keyframe_insert("rotation_euler", frame=f - 1)
        self.arm.location = (pos[0], pos[1], pos[2] if len(pos) > 2 else 0.0)
        if heading is not None:
            self.arm.rotation_euler = (0, 0, math.radians(heading))
        self.arm.keyframe_insert("location", frame=f)
        self.arm.keyframe_insert("rotation_euler", frame=f)


def keyval(group_name, beat, value, interp="LINEAR"):
    g = bpy.data.node_groups[group_name]
    n = g.nodes["src"]
    n.outputs[0].default_value = value
    n.outputs[0].keyframe_insert("default_value", frame=F(beat))


def build(sc):
    W = WD.build_world(sc)
    spk, spk_light = WD.build_speaker(sc)
    cast = {}
    for name in ("TIKHIY", "GRACH", "ZIMA", "MOL"):
        arm, objs = CH.build_character(name)
        cast[name] = (arm, objs)
    H, G, Z, M = (cast[n][0] for n in ("TIKHIY", "GRACH", "ZIMA", "MOL"))
    pH, pG, pZ, pM = (K.Performer(a, FPB) for a in (H, G, Z, M))
    mH, mG, mZ, mM = (Mover(a) for a in (H, G, Z, M))

    # ------------------------------------------------------------------ S1/S2 (0-16)
    # 04:04. He waits under the lamp, the speaker hums. Three shapes come out of the fog.
    mH.key(0, (8.2, 3.0), 0)
    pH.play("Idle", 0, loops=3.0)                         # 0..12
    pH.pose(13.0, K.Q(t=(2, 0, 0), h=(16, 0, 0), la=(10, 3, 30), ra=(10, 3, 30), ll=(3, 4), rl=(-3, 6, 10)))
    pH.pose(14.2, K.Q(t=(0, 0, 4), h=(-6, 0, 10), la=(10, 3, 30), ra=(10, 3, 30), ll=(3, 4), rl=(-3, 6, 10)))
    pH.pose(15.9, K.Q(t=(0, 0, 6), h=(-8, 0, 14), la=(10, 3, 30), ra=(10, 3, 30), ll=(3, 4), rl=(-3, 6, 10)))
    for mv, pf, y, x0 in ((mG, pG, 1.5, 22.5), (mZ, pZ, 0.2, 23.6), (mM, pM, 2.7, 24.4)):
        mv.key(0, (x0 + 6.0, y), -90)
        mv.key(8, (x0, y), -90)
        mv.key(16, (x0 - 6.4, y), -90)
        pf.play("Walk", 0, loops=8.0)                     # 0..16

    # ------------------------------------------------------------------ S3 (16-32) the fight
    # H in guard at x=10, facing +X.
    mH.key(16, (10.0, 1.5), 90, cut=True)
    pH.pose(16 - 1 / FPB, K.GUARD)
    pH.play("Guard", 16, loops=0.75)                      # ..17.5
    # G rushes in and throws the big swing: wind-up 17, lands 18.
    mG.key(16, (14.2, 1.5), -90, cut=True)
    mG.key(17, (11.55, 1.5), -90)
    pG.pose(16 - 1 / FPB, K.sample("Sprint", 0))
    pG.play("Sprint", 16, loops=0.5)                      # ..17
    pG.play("Haymaker", 17, t1=1.25)                      # hit @18
    # H slips it ON the beat, answers with the one-two: jab 18.5, cross 19.
    pH.play("Slip", 17.5, t1=0.8)                         # peak @18
    pH.play("Dvoika", 18.0, t0=0.38, t1=1.2)              # jab 18.12.. hmm shifted below
    mG.key(18.5, (11.55, 1.5), -90)
    pG.play("Hit", 18.5, t1=0.3)
    pG.play("Stagger", 19.0, t1=1.6)                      # folded 19.9..20.6
    mG.key(19.0, (11.6, 1.5), -90)
    mG.key(19.8, (11.75, 1.5), -90)
    # push kick: chamber 20, lands 21 -> G is off his feet.
    pH.play("PushKick", 20.0, t1=1.8)                     # hit @21, back to guard 21.8
    mG.key(21.0, (12.05, 1.5), -90)
    pG.play("Knockdown", 21.0)                            # ..24 lying
    mG.key(22.0, (13.0, 1.5), -90)
    mG.key(32.0, (13.0, 1.5), -90)
    # Z comes in from the side: swing lands 23 -> blocked. Cross @24 answers.
    mZ.key(16, (15.6, 0.3), -90, cut=True)
    pZ.pose(16 - 1 / FPB, K.GUARD)
    pZ.play("Guard", 16, loops=2.75)                      # ..21.5
    mZ.key(21.3, (15.6, 0.3), -78)
    mZ.key(22.2, (11.75, 1.25), -84)
    pZ.play("Sprint", 21.5, loops=0.25)
    pZ.play("Haymaker", 22.0, t1=1.25)                    # hit @23
    pH.play("Block", 22.5, t1=1.0)                        # up @23
    pH.play("Dvoika", 23.3, t0=0.7, t1=1.2)               # load 23.3, cross lands 23.6?? fixed below
    mZ.key(24.0, (11.75, 1.25), -84)
    pZ.play("Stagger", 24.0, t1=1.6)
    mZ.key(25.0, (12.3, 1.1), -84)
    mZ.key(32.0, (12.3, 1.1), -84)
    pZ.pose(27.0, K.sample("Stagger", 1.6))
    pZ.pose(28.5, K.GUARD)
    pZ.play("Guard", 28.5, loops=1.75)
    # M keeps her distance, then goes for the speaker while they are busy.
    mM.key(16, (16.4, 2.9), -90, cut=True)
    pM.pose(16 - 1 / FPB, K.STAND)
    pM.play("Idle", 16, loops=1.5)                        # ..22
    mM.key(22.0, (16.4, 2.9), -110)
    mM.key(24.2, (13.55, 3.55), -150)
    pM.play("Walk", 22.0, loops=1.1)
    pM.play("PickUp", 24.3)                               # bend 24.9, up 25.9
    mM.key(26.3, (13.55, 3.55), -150)
    mM.key(26.7, (14.2, 3.2), 90)
    pM.play("CarryRun", 26.3, loops=1.5)                  # ..29.3
    mM.key(29.3, (20.4, 2.6), 90)
    mM.key(29.9, (21.9, 2.6), 262)                        # she looks back — too late
    pM.pose(29.9, K.Q(hip=(0, -0.05, 0), t=(-8, 0, 0), h=(-6, 0, 0), la=(60, 30), ra=(150, 20), ll=(16, 5),
                      rl=(-18, 8)))
    pM.play("Knockdown", 30.0)
    mM.key(30.0, (21.9, 2.6), 270)
    mM.key(31.0, (23.3, 2.6), 270)
    mM.key(40.0, (23.3, 2.6), 270)
    # H turns and runs her down: take-off 29, the heel lands on 30.
    pH.play("Sprint", 25.0, loops=2.0)                    # ..29
    mH.key(24.6, (10.3, 1.5), 90)
    mH.key(25.2, (10.6, 1.7), 90)
    mH.key(29.0, (18.9, 2.6), 90)
    mH.key(30.0, (20.55, 2.6), 90)
    pH.play("FlyKick", 29.0, t1=1.8)                      # hit @30, lands 30.8
    mH.key(30.8, (20.6, 2.6), 90)
    # the speaker comes down, he takes it on the shoulder exactly on 32. Silence.
    pH.pose(31.4, K.Q(hip=(0, 0.95, 0), t=(4, 0, 0), h=(-24, 0, 0), la=(10, 10), ra=(150, 10), ll=(10, 4), rl=(-10, 6)))
    pH.pose(32.0, dict(K.SHOULDER, hip=(0.03, 0.95, 0)))

    # ------------------------------------------------------------------ S4 (32-40) ШУХЕР
    pH.pose(33.4, dict(K.SHOULDER, hip=(0.03, 0.95, 0), h=(4, 0, -70), t=(0, -5, -14)))
    pH.pose(34.6, dict(K.SHOULDER, hip=(0.03, 0.95, 0), h=(4, 0, -70), t=(0, -5, -14)))
    mH.key(34.6, (20.6, 2.6), 90)
    mH.key(35.0, (21.5, 2.4), 268, cut=False)
    pH.pose(35.0, dict(K.sample("CarryRun", 0)))
    pH.play("CarryRun", 35.0, loops=2.45)                 # ..39.9
    mH.key(39.9, (10.5, 1.2), 270)
    pG.play("GetUp", 33.0)                                # ..35
    mG.key(35.0, (13.0, 1.5), -90)
    mG.key(35.4, (12.2, 1.9), 0)
    mG.key(39.9, (11.2, -8.5), 190)
    pG.play("Sprint", 35.2, loops=2.3)
    mZ.key(33.0, (12.3, 1.1), -84)
    mZ.key(33.4, (12.3, 1.1), 170)
    mZ.key(39.9, (16.5, -9.0), 160)
    pZ.pose(32.8, K.GUARD)
    pZ.play("Sprint", 33.2, loops=3.3)
    pM.play("GetUp", 34.0)
    mM.key(36.0, (23.3, 2.6), 270)
    mM.key(36.4, (24.2, 2.6), 90)
    mM.key(39.9, (33.0, 3.0), 90)
    pM.play("Sprint", 36.2, loops=1.8)

    # ------------------------------------------------------------------ S5 (40-56) title
    LX = 62.0
    for mv, pf, pos, hd, pose in (
            (mH, pH, (LX, 2.7), 14, K.SHOULDER),
            (mG, pG, (LX - 1.35, 3.5), 28, K.LEAN),
            (mZ, pZ, (LX + 1.5, 3.3), -24, K.SQUAT),
            (mM, pM, (LX + 2.75, 4.1), -30, K.STAND)):
        mv.key(40, pos, hd, cut=True)
        pf.pose(40 - 1 / FPB, pose)
        for b in range(40, 57):
            on = (b % 2 == 0)
            p = dict(pose)
            p["hip"] = (pose["hip"][0], pose["hip"][1], pose["hip"][2] - (0.015 if on else 0.0))
            p["h"] = (pose["h"][0] + (5 if on else 0), pose["h"][1], pose["h"][2])
            pf.pose(b, p)

    # re-time the two Dvoika calls precisely (jab 18.5 / cross 19.0 ; cross 24.0)
    # (handled by clip offsets: Dvoika t0=0.38 @18.0 -> jab key 0.5 lands 18.12 — fix by explicit keys)
    return W, cast, (spk, spk_light)


def fix_dvoika(cast):
    """The jab-cross timings are critical, so key them explicitly on the grid."""
    H = cast["TIKHIY"][0]
    pf = K.Performer(H, FPB)
    keys = K.clip_keys("Dvoika")
    # jab @18.5, load 18.7-18.86, cross @19.0, follow 19.2
    for b, p in keys:
        if 0.38 <= b <= 1.2:
            pf.pose(18.0 + b, p)
    for b, p in keys:
        if 0.7 <= b <= 1.2:
            pf.pose(23.0 + b, p)
    pf.pose(24.6, K.GUARD)


def clean_wrong_keys(cast):
    """Remove the two provisional Dvoika inserts made inside build()."""
    H = cast["TIKHIY"][0]
    bad = set()
    for b, _ in K.clip_keys("Dvoika"):
        if 0.38 <= b <= 1.2:
            bad.add(round(F(18.0 + (b - 0.38)), 3))
        if 0.7 <= b <= 1.2:
            bad.add(round(F(23.3 + (b - 0.7)), 3))
    good = set()
    for b, _ in K.clip_keys("Dvoika"):
        if 0.38 <= b <= 1.2:
            good.add(round(F(18.0 + b), 3))
        if 0.7 <= b <= 1.2:
            good.add(round(F(23.0 + b), 3))
    bad -= good
    for fc in C.iter_fcurves(H.animation_data.action):
        if "pose.bones" not in fc.data_path:
            continue
        for kp in reversed(list(fc.keyframe_points)):
            if round(kp.co[0], 3) in bad:
                fc.keyframe_points.remove(kp)
        fc.update()


# ---------------------------------------------------------------------------
def speaker_track(sc, cast, spk):
    """Bake the speaker: on the ground -> M's hand -> in the air -> H's shoulder."""
    H, M = cast["TIKHIY"][0], cast["MOL"][0]
    spk.rotation_mode = "QUATERNION"
    ground = Vector((13.0, 3.95, 0.125))

    def on_arm(arm):
        pb = arm.pose.bones["Right Arm"]
        rest = arm.data.bones["Right Arm"].matrix_local.to_3x3()
        off = rest.inverted() @ Vector((0.10, 0.0, -0.50))
        return arm.matrix_world @ pb.matrix @ Matrix.Translation(off)

    def setkey(f, loc, quat):
        spk.location = loc
        spk.rotation_quaternion = quat
        spk.keyframe_insert("location", frame=f)
        spk.keyframe_insert("rotation_quaternion", frame=f)

    q0 = Euler((0, 0, math.radians(20))).to_quaternion()
    prevq = q0
    f_pick, f_kick, f_catch, f_cut = int(F(25.4)), int(F(30.0)), int(F(32.0)), int(F(40.0))
    for f in range(1, int(F(TOTAL_BEATS)) + 1):
        sc.frame_set(f)
        if f < f_pick:
            loc, q = ground, q0
        elif f <= f_kick:
            Mx = on_arm(M)
            loc, q = Mx.to_translation(), Mx.to_quaternion() @ Euler((0, math.radians(90), 0)).to_quaternion()
            if f < f_pick + 5:                           # lift off the ground
                k = (f - f_pick) / 5
                loc = ground.lerp(loc, k); q = q0.slerp(q, k)
        elif f < f_catch:
            k = (f - f_kick) / (f_catch - f_kick)
            a = P_KICK
            sc.frame_set(f_catch); b = on_arm(H).to_translation(); sc.frame_set(f)
            loc = a.lerp(b, k) + Vector((0, 0, 2.4 * 4 * k * (1 - k)))
            q = Euler((k * 9.0, k * 5.0, k * 2.0)).to_quaternion()
        else:
            Hx = on_arm(H)
            loc, q = Hx.to_translation(), Hx.to_quaternion() @ Euler((0, math.radians(90), 0)).to_quaternion()
        if f == f_kick:
            globals()["P_KICK"] = loc.copy()
        if prevq.dot(q) < 0:
            q = -q
        prevq = q
        setkey(f, loc, q)


P_KICK = Vector((21.9, 2.6, 1.6))


def cameras(sc):
    """One camera object, keyed per shot. Returns shot list for the post pass."""
    cd = bpy.data.cameras.new("Cam")
    cam = bpy.data.objects.new("Cam", cd)
    sc.collection.objects.link(cam)
    sc.camera = cam
    cd.clip_start, cd.clip_end = 0.05, 2500
    cd.sensor_width = 36
    cam.rotation_mode = "QUATERNION"
    rnd = random.Random(7)
    shots = []
    state = {"q": None}

    def look(beat, loc, tgt, lens, roll=0.0, fstop=None, focus=None, cut=False):
        f = F(beat)
        loc, tgt = Vector(loc), Vector(tgt)
        q = (tgt - loc).to_track_quat("-Z", "Y") @ Euler((0, 0, math.radians(roll))).to_quaternion()
        if state["q"] is not None and not cut and state["q"].dot(q) < 0:
            q = -q
        state["q"] = q
        if cut:
            for path in ("location", "rotation_quaternion"):
                cam.keyframe_insert(path, frame=f - 1)
            cd.keyframe_insert("lens", frame=f - 1)
            cd.dof.keyframe_insert("aperture_fstop", frame=f - 1)
            cd.dof.keyframe_insert("focus_distance", frame=f - 1)
            shots.append(beat)
        cam.location = loc
        cam.rotation_quaternion = q
        cd.lens = lens
        cd.dof.use_dof = True
        cd.dof.aperture_fstop = fstop or 8.0
        cd.dof.focus_distance = focus or (tgt - loc).length
        for path in ("location", "rotation_quaternion"):
            cam.keyframe_insert(path, frame=f)
        cd.keyframe_insert("lens", frame=f)
        cd.dof.keyframe_insert("aperture_fstop", frame=f)
        cd.dof.keyframe_insert("focus_distance", frame=f)

    # S1 establishing: slow push along the street towards the kiosk and the lamp
    look(0, (-3.5, -7.6, 1.05), (7.0, 4.2, 2.3), 26, fstop=4.0, focus=14)
    look(8, (-1.2, -6.6, 1.15), (7.4, 4.0, 2.1), 26, fstop=4.0, focus=13)
    # S2a three silhouettes in the fog (long lens)
    look(8, (6.2, -1.2, 0.75), (20.0, 1.4, 1.15), 80, fstop=2.8, focus=14, cut=True)
    look(12, (6.6, -1.0, 0.75), (18.0, 1.4, 1.15), 80, fstop=2.8, focus=11)
    # S2b close-up: the hood lifts, he looks
    look(12, (8.55, 0.75, 1.30), (8.2, 3.0, 1.38), 60, fstop=2.0, focus=2.1, cut=True)
    look(16 - 1 / FPB, (8.45, 1.05, 1.31), (8.2, 3.0, 1.38), 60, fstop=2.0, focus=1.8)
    # S3a side medium: swing / slip
    look(16, (10.9, -3.3, 1.0), (10.9, 1.5, 1.0), 34, roll=5, fstop=4.0, cut=True)
    look(18.4, (10.6, -3.0, 1.0), (10.8, 1.5, 1.0), 34, roll=5, fstop=4.0)
    # S3b over-the-shoulder punch-in for the one-two
    look(18.4, (9.25, 0.15, 1.33), (11.4, 1.6, 1.22), 50, roll=-7, fstop=2.8, focus=2.3, cut=True)
    look(20.0, (9.35, 0.25, 1.33), (11.6, 1.6, 1.15), 50, roll=-7, fstop=2.8, focus=2.4)
    # S3c low wide: the push kick, G flies
    look(20.0, (11.0, -3.6, 0.32), (11.4, 1.5, 1.0), 26, roll=-9, fstop=5.6, cut=True)
    look(22.0, (11.6, -3.4, 0.32), (12.4, 1.5, 0.8), 26, roll=-9, fstop=5.6)
    # S3d block + cross from the other angle
    look(22.0, (9.3, -2.2, 1.25), (10.9, 1.4, 1.05), 40, roll=6, fstop=4.0, cut=True)
    look(24.6, (9.6, -2.0, 1.25), (11.0, 1.4, 1.05), 40, roll=6, fstop=4.0)
    # S3e the speaker gets lifted
    look(24.6, (15.1, 1.2, 0.42), (13.5, 3.6, 0.85), 35, roll=-5, fstop=2.8, focus=2.9, cut=True)
    look(26.4, (15.0, 1.3, 0.48), (13.6, 3.5, 1.2), 35, roll=-5, fstop=2.8, focus=2.8)
    # S3f chase: side tracking
    look(26.4, (14.6, -4.6, 0.9), (13.4, 2.4, 1.0), 30, roll=3, fstop=5.6, cut=True)
    look(29.3, (19.9, -4.6, 0.9), (19.5, 2.6, 1.0), 30, roll=3, fstop=5.6)
    # S3g low angle: the flying kick, the speaker in the air
    look(29.3, (23.9, -1.4, 0.38), (21.5, 2.6, 1.45), 24, roll=10, fstop=5.6, cut=True)
    look(32.0, (23.6, -1.7, 0.42), (21.3, 2.6, 1.75), 24, roll=10, fstop=5.6)
    # S4 shukher: wide, high, static-ish
    look(32.0, (15.5, -8.2, 3.4), (20.0, 3.0, 2.2), 24, fstop=5.6, cut=True)
    look(40 - 1 / FPB, (15.0, -8.4, 3.2), (19.0, 3.0, 2.0), 24, fstop=5.6)
    # S5 title: low hero angle under the lamp
    look(40, (60.9, -3.4, 0.45), (62.5, 3.2, 1.12), 30, roll=-3, fstop=4.0, focus=6.3, cut=True)
    look(48, (61.2, -2.9, 0.5), (62.5, 3.2, 1.14), 30, roll=-3, fstop=4.0, focus=5.8)
    look(56, (61.3, -2.7, 0.52), (62.5, 3.2, 1.15), 30, roll=-3, fstop=4.0, focus=5.6)
    C.set_interp(cam, "LINEAR")
    # impact shake
    for (b, amt) in IMPACTS:
        for i in range(6):
            f = F(b) + i
            sc.frame_set(int(f))
            cam.location = cam.location + Vector((rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(-1, 1))) \
                * 0.05 * amt * (1 - i / 6)
            cam.keyframe_insert("location", frame=f)
    return cam, shots


def lighting(sc, W, cast, spk_light):
    col = sc.collection

    def area(name, loc, tgt, energy, color, size):
        ld = bpy.data.lights.new(name, "AREA")
        ld.energy, ld.size = energy, size
        ld.color = C.lin(color)[:3]
        ob = bpy.data.objects.new(name, ld)
        ob.location = loc
        ob.rotation_euler = (Vector(tgt) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        col.objects.link(ob)
        return ob

    # movie lights for the fight: cool key from the camera side, hot rim from the lamp side
    area("FightKey", (9.0, -5.5, 3.2), (11.0, 1.5, 1.0), 900, "#9db4ff", 3.0)
    area("FightRim", (13.5, 6.5, 2.6), (11.0, 1.5, 1.1), 1500, "#ff9a3c", 2.0)
    area("FightRim2", (7.0, 5.8, 2.4), (10.5, 1.5, 1.2), 700, "#ff5fd2", 1.5)
    area("ChaseKey", (20.0, -6.0, 3.4), (20.5, 2.6, 1.0), 1100, "#9db4ff", 4.0)
    area("ChaseRim", (24.5, 6.5, 2.8), (21.5, 2.6, 1.2), 1600, "#ff9a3c", 2.0)
    area("FaceKey", (9.6, 0.4, 1.7), (8.2, 3.0, 1.4), 90, "#b8c6ff", 0.8)
    area("TitleKey", (59.5, -3.0, 2.2), (62.3, 3.0, 1.2), 420, "#9db4ff", 2.5)
    area("TitleRim", (64.5, 7.0, 2.6), (62.3, 3.0, 1.3), 1300, "#ff5fd2", 2.0)

    # police strobes: two far lights sweeping red / blue during the shukher beat
    for i, colr in enumerate(("#ff2030", "#2a55ff")):
        ld = bpy.data.lights.new(f"Police{i}", "SPOT")
        ld.color = C.lin(colr)[:3]
        ld.spot_size, ld.spot_blend, ld.shadow_soft_size = math.radians(70), 0.8, 0.5
        ob = bpy.data.objects.new(f"Police{i}", ld)
        ob.location = (46.0, -3.0 + i * 1.2, 2.2)
        ob.rotation_mode = "XYZ"
        col.objects.link(ob)
        for b in [x * 0.25 for x in range(0, int(TOTAL_BEATS * 4) + 1)]:
            on = 32.6 <= b < 40 and (int(b * 2) % 2 == i)
            ld.energy = 260000 if on else 0.0
            ld.keyframe_insert("energy", frame=F(b))
            ob.rotation_euler = (math.radians(86), 0, math.radians(90 + 16 * math.sin(b * 1.7 + i)))
            ob.keyframe_insert("rotation_euler", frame=F(b))
        C.set_interp(ob, "CONSTANT")
        for fc in C.iter_fcurves(ld.animation_data.action):
            for kp in fc.keyframe_points:
                kp.interpolation = "CONSTANT"

    # the beat: every lamp, sign and the speaker breathe with the track
    for b in range(0, TOTAL_BEATS + 1):
        if b < 16:
            amp = 0.18 if b % 2 == 0 else 0.06
        elif b < 32:
            amp = 1.0 if b % 2 == 0 else 0.6
        elif b < 40:
            amp = 0.0
        else:
            amp = 1.0 if b < 49 else 0.25
        keyval(C.PULSE_GROUP, b - 0.12, 0.0 if b >= 16 else 0.02)
        keyval(C.PULSE_GROUP, b, amp)
        keyval(C.PULSE_GROUP, b + 0.55, amp * 0.12)
        spk_light.data.energy = 120 + 900 * amp
        spk_light.data.keyframe_insert("energy", frame=F(b))
        spk_light.data.energy = 120 + 150 * amp
        spk_light.data.keyframe_insert("energy", frame=F(b + 0.55))
    # fog: thicker for the silhouettes, darker for the shukher
    C.fog_color_group(); C.density_group()
    for b, colr, dens in ((0, "#241c33", 0.024), (31.9, "#241c33", 0.024), (32.3, "#120f1c", 0.034),
                          (39.9, "#120f1c", 0.034), (40, "#2a1d3a", 0.026), (56, "#2a1d3a", 0.026)):
        keyval(C.FOGCOL_GROUP, b, C.lin(colr))
        keyval("DA_FogDensity", b, dens)
    # lamps die during the shukher
    for ob in W.lights:
        if ob.data.type == "SPOT":
            e = ob.data.energy
            for b, k in ((0, 1.0), (32.0, 1.0), (32.25, 0.12), (39.9, 0.12), (40.0, 1.0)):
                ob.data.energy = e * k
                ob.data.keyframe_insert("energy", frame=F(b))
    # broadcast rings on the tower: one per bar
    for i, ring in enumerate(W.rings):
        for bar in range(0, TOTAL_BEATS // 4 + 1):
            b0 = bar * 4 + i * 1.3
            ring.scale = (1, 1, 1); ring.color = (1, 1, 1, 0.9)
            ring.keyframe_insert("scale", frame=F(b0)); ring.keyframe_insert("color", frame=F(b0))
            ring.scale = (60, 60, 60); ring.color = (1, 1, 1, 0.0)
            ring.keyframe_insert("scale", frame=F(b0 + 3.9)); ring.keyframe_insert("color", frame=F(b0 + 3.9))


def fx(sc, cast):
    """Impact bursts + punch trails (simple emissive meshes, visible for a few frames)."""
    burst_m = C.glow_mat("fx_burst", "#ffffff", strength=40.0)
    col = sc.collection
    rnd = random.Random(3)
    hits = [(18.5, (10.95, 1.5, 1.28), 0.22), (19.0, (11.05, 1.5, 1.3), 0.42), (21.0, (11.35, 1.5, 1.05), 0.55),
            (23.0, (10.5, 1.42, 1.3), 0.34), (24.0, (11.2, 1.3, 1.32), 0.45), (30.0, (21.75, 2.6, 1.4), 0.75)]
    for b, pos, size in hits:
        mb = C.MeshBuilder()
        n = 11
        for k in range(n):
            a = 2 * math.pi * k / n + rnd.uniform(-0.2, 0.2)
            L = size * rnd.uniform(0.7, 1.6)
            w = size * 0.10
            for plane in range(2):
                d = Vector((math.cos(a), 0, math.sin(a))) if plane == 0 else Vector((0, math.cos(a), math.sin(a)))
                s = Vector((-d.z, 0, d.x)) if plane == 0 else Vector((0, -d.z, d.y))
                c = Vector(pos)
                mb.quad([c + d * size * 0.25 - s * w, c + d * size * 0.25 + s * w, c + d * (size * 0.25 + L)], burst_m,
                        [(0, 0), (1, 0), (1, 1)])
        ob = mb.build(f"Burst_{b}", col)
        ob.visible_shadow = False
        for f, hide in ((F(b) - 1, True), (F(b), False), (F(b) + 3, True)):
            ob.hide_render = hide
            ob.keyframe_insert("hide_render", frame=f)
        ob.scale = (1, 1, 1); ob.keyframe_insert("scale", frame=F(b))
        C.set_interp(ob, "CONSTANT")


def render_settings(sc, quality=1.0):
    sc.render.engine = "CYCLES"
    cy = sc.cycles
    cy.device = "CPU"
    cy.samples = int(9 * quality)
    cy.use_adaptive_sampling = False
    cy.use_denoising = True
    cy.denoiser = "OPENIMAGEDENOISE"
    cy.max_bounces = 2
    cy.diffuse_bounces = 1
    cy.glossy_bounces = 2
    cy.transmission_bounces = 0
    cy.transparent_max_bounces = 6
    cy.sample_clamp_indirect = 3.0
    cy.sample_clamp_direct = 12.0
    cy.use_light_tree = False
    cy.caustics_reflective = cy.caustics_refractive = False
    sc.render.resolution_x, sc.render.resolution_y = 960, 402
    sc.render.resolution_percentage = 100
    sc.render.fps = FPS
    sc.frame_start, sc.frame_end = 1, int(F(TOTAL_BEATS))
    sc.view_settings.view_transform = "AgX"
    try:
        sc.view_settings.look = "AgX - Medium High Contrast"
    except Exception:
        pass
    sc.render.image_settings.file_format = "PNG"
    sc.render.use_persistent_data = True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--still", type=int, nargs="*")
    ap.add_argument("--frames", type=int, nargs=2)
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--out", default=os.path.join(C.OUT, "..", "render"))
    ap.add_argument("--quality", type=float, default=1.0)
    ap.add_argument("--threads", type=int, default=0)
    args = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:])

    C.reset_scene()
    sc = bpy.context.scene
    sc.render.fps = FPS
    W, cast, (spk, spk_light) = build(sc)
    clean_wrong_keys(cast)
    fix_dvoika(cast)
    for arm, _ in cast.values():
        C.set_interp(arm, "LINEAR", "location")
        C.set_interp(arm, "LINEAR", "rotation_euler")
    sc.frame_end = int(F(TOTAL_BEATS))
    speaker_track(sc, cast, spk)
    cam, shots = cameras(sc)
    lighting(sc, W, cast, spk_light)
    fx(sc, cast)
    render_settings(sc, args.quality)
    if args.threads:
        sc.render.threads_mode = "FIXED"
        sc.render.threads = args.threads
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "shots.json"), "w") as fh:
        json.dump({"fps": FPS, "fpb": FPB, "beats": TOTAL_BEATS, "cuts": shots, "impacts": IMPACTS}, fh)
    if args.save:
        bpy.ops.file.pack_all()
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(C.OUT, "strelka_trailer.blend"), compress=True)
    if args.still:
        for f in args.still:
            sc.frame_set(f)
            sc.render.filepath = os.path.join(out, f"still_{f:04d}.png")
            bpy.ops.render.render(write_still=True)
    if args.frames:
        for f in range(args.frames[0], args.frames[1] + 1):
            path = os.path.join(out, f"f_{f:04d}.png")
            if os.path.exists(path):
                continue
            sc.frame_set(f)
            sc.render.filepath = path
            import time as _t; _t0 = _t.time()
            bpy.ops.render.render(write_still=True)
            print(f"FRAME {f} {_t.time() - _t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
