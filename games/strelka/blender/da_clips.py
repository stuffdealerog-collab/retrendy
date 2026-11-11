"""STRELKA — R6 animation clips, authored in BEATS (not seconds).

R6 has six joints and no elbows or knees, so all the acting is in the torso:
lean, twist, drop the hips, throw the limbs. Every hit lands on a beat; every
wind-up is one beat long. In Roblox the clips are played with
AnimationTrack:AdjustSpeed(bpm / AUTHOR_BPM) so they stay on the grid.

Pose keys (semantic, same sign for both sides, so mirroring is trivial):
  hip = (left, forward, up) metres        t  = torso (lean fwd, lean left, turn left)
  h   = head  (nod down, tilt left, turn left) — nod is given in WORLD terms
  la / ra = arm (swing fwd, raise out, twist in)
  ll / rl = leg (swing fwd, out, turn out)    — swing is given in WORLD terms
"""
import math

import bpy
from mathutils import Matrix, Vector

BONES = {"t": "Torso", "h": "Head", "la": "Left Arm", "ra": "Right Arm", "ll": "Left Leg", "rl": "Right Leg"}
LEG = 0.6


def _t(v):
    return tuple(v) + (0,) * (3 - len(v)) if isinstance(v, (tuple, list)) else (v, 0, 0)


def Q(hip=(0, 0, 0), t=(0, 0, 0), h=(0, 0, 0), la=(4, 6), ra=(4, 6), ll=(0, 2), rl=(0, 2), ground=True):
    """Build a pose. With ground=True the hips are dropped automatically so the
    supporting foot stays on the floor."""
    t, h, la, ra, ll, rl = map(_t, (t, h, la, ra, ll, rl))
    hx, hy, hz = hip
    if ground:
        def ang(leg):
            return math.acos(max(-1, min(1, math.cos(math.radians(leg[0])) * math.cos(math.radians(leg[1])))))
        a = min(ang(ll), ang(rl))
        hz = hz - LEG * (1 - math.cos(a)) - 0.3 * (1 - math.cos(math.radians(t[0]))) * 0.0
    return {"hip": (hx, hy, hz), "t": t, "h": h, "la": la, "ra": ra, "ll": ll, "rl": rl}


def mirror(p):
    c = lambda v: (v[0], -v[1], -v[2])
    return {"hip": (-p["hip"][0], p["hip"][1], p["hip"][2]), "t": c(p["t"]), "h": c(p["h"]),
            "la": p["ra"], "ra": p["la"], "ll": p["rl"], "rl": p["ll"]}


def mix(p, q, k):
    return {key: tuple(a + (b - a) * k for a, b in zip(p[key], q[key])) for key in p}


def _rot(rx, ry, rz):
    return (Matrix.Rotation(math.radians(rz), 3, "Z") @ Matrix.Rotation(math.radians(rx), 3, "X")
            @ Matrix.Rotation(math.radians(ry), 3, "Y"))


def _raw(key, v, lean):
    a, b, c = v
    if key == "t":
        return (a, b, c)
    if key == "h":
        return (a - lean, b, c)
    s = 1 if key[0] == "l" else -1
    if key in ("la", "ra"):
        return (-a, -s * b, -s * c)
    return (-(a + lean), -s * b, s * c)        # legs: world swing -> relative to the leaning torso


def apply_pose(arm, pose, frame, prev=None):
    M = arm.data.bones["Torso"].matrix_local.to_3x3()
    Mi = M.inverted()
    prev = prev if prev is not None else {}
    lean = pose["t"][0]
    for key, bname in BONES.items():
        pb = arm.pose.bones[bname]
        q = (Mi @ _rot(*_raw(key, pose[key], lean)) @ M).to_quaternion()
        if bname in prev and prev[bname].dot(q) < 0:
            q.negate()
        prev[bname] = q.copy()
        pb.rotation_quaternion = q
        pb.keyframe_insert("rotation_quaternion", frame=frame)
    hx, hy, hz = pose["hip"]
    pb = arm.pose.bones["Torso"]
    pb.location = Mi @ Vector((hx, -hy, hz))
    pb.keyframe_insert("location", frame=frame)
    return prev


# ---------------------------------------------------------------------------
# Poses
# ---------------------------------------------------------------------------
STAND = Q()
GUARD = Q(hip=(0, 0, -0.02), t=(8, 0, -26), h=(4, 0, 24), la=(74, 2, 20), ra=(58, 8, 30),
          ll=(22, 5, 0), rl=(-22, 8, 26))


def guard_keys():
    lo = Q(hip=(0, 0, -0.05), t=(10, 0, -26), h=(6, 0, 24), la=(70, 2, 20), ra=(55, 8, 30),
           ll=(25, 5, 0), rl=(-25, 8, 26))
    return [(0.0, lo), (0.5, GUARD), (1.0, lo), (1.5, GUARD), (2.0, lo)]


def idle_keys():
    out = []
    for i in range(9):
        b = i * 0.5
        on = i % 2 == 0
        ph = 2 * math.pi * b / 4
        out.append((b, Q(hip=(0.02 * math.sin(ph), 0, -0.012 if on else 0.0),
                         t=(2 + (1.5 if on else 0), 2 * math.sin(ph), 3 * math.sin(ph)),
                         h=(10 + (6 if on else 0), 0, -4 * math.sin(ph)),
                         la=(10, 3, 30), ra=(10, 3, 30), ll=(3, 4), rl=(-3, 6, 10))))
    return out


def walk_keys():
    """Slow swagger — one step per beat."""
    a = Q(t=(-3, 4, 9), h=(12, -2, -6), la=(-14, 6, 20), ra=(16, 6, 20), ll=(24, 3), rl=(-22, 3))
    p = Q(hip=(0, 0, 0.0), t=(-2, 0, 0), h=(12, 0, 0), la=(2, 6, 20), ra=(2, 6, 20), ll=(2, 3), rl=(4, 3))
    return [(0.0, a), (0.5, p), (1.0, mirror(a)), (1.5, mirror(p)), (2.0, a)]


def _run(lean, leg, arm_, bob=0.035, ra=None):
    a = Q(t=(lean, 0, 10), h=(4, 0, -6), la=(-arm_, 8), ra=(arm_, 8), ll=(leg, 0), rl=(-leg * 0.9, 0))
    p = Q(hip=(0, 0, bob), t=(lean - 3, 0, 0), h=(4, 0, 0), la=(0, 10), ra=(0, 10), ll=(-8, 0), rl=(30, 0),
          ground=False)
    keys = [(0.0, a), (0.5, p), (1.0, mirror(a)), (1.5, mirror(p)), (2.0, a)]
    if ra is not None:
        keys = [(b, dict(k, ra=_t(ra))) for b, k in keys]
    return keys


def run_keys():
    return _run(16, 46, 52)


def sprint_keys():
    return _run(27, 58, 72, bob=0.05)


def carry_keys():
    """Running with the speaker on the right shoulder."""
    return _run(18, 48, 50, ra=(168, 14, 0))


def dvoika_keys():
    """ДВОЙКА — jab on the off-beat (0.5), cross lands ON the beat (1.0)."""
    jab = Q(hip=(0, 0.10, -0.03), t=(12, 0, -46), h=(6, 0, 42), la=(93, -2, 10), ra=(50, 12, 30),
            ll=(28, 5), rl=(-24, 8, 26))
    load = Q(hip=(0, 0.04, -0.04), t=(8, 0, -44), h=(6, 0, 40), la=(60, 4, 20), ra=(28, 26, 30),
             ll=(24, 5), rl=(-24, 8, 26))
    cross = Q(hip=(0, 0.26, -0.03), t=(18, 0, 52), h=(8, 0, -50), la=(34, 18, 30), ra=(94, -6, 0),
              ll=(32, 5), rl=(-34, 8, 30))
    return [(0.0, GUARD), (0.38, mix(GUARD, jab, 0.25)), (0.5, jab), (0.7, load), (0.86, load),
            (1.0, cross), (1.2, dict(cross, hip=(0, 0.29, cross["hip"][2]))), (1.7, GUARD), (2.0, GUARD)]


def haymaker_keys():
    """РАЗМАХ — the heavy swing. One full beat of wind-up; lands at 1.0."""
    wind = Q(hip=(0, -0.12, -0.04), t=(2, -8, -74), h=(2, 6, 66), la=(64, 8, 20), ra=(-28, 78, 0),
             ll=(18, 6), rl=(-20, 10, 30))
    hit = Q(hip=(0, 0.26, -0.04), t=(20, 10, 78), h=(10, -8, -70), la=(10, 30, 20), ra=(86, 14, 0),
            ll=(34, 5), rl=(-36, 8, 30))
    thru = Q(hip=(0, 0.30, -0.06), t=(24, 14, 124), h=(12, -8, -100), la=(-10, 40, 20), ra=(64, -46, 0),
             ll=(34, 5), rl=(-30, 8, 30))
    return [(0.0, GUARD), (0.5, wind), (0.84, dict(wind, t=(2, -8, -80))), (1.0, hit), (1.25, thru),
            (1.9, GUARD), (2.5, GUARD)]


def pushkick_keys():
    """С НОГИ — front push kick; lands at 1.0, sends them flying."""
    chamber = Q(hip=(0, 0.02, 0), t=(-4, 0, -10), h=(6, 0, 10), la=(60, 10, 20), ra=(50, 16, 30),
                ll=(0, 3), rl=(48, 4))
    hit = Q(hip=(0, 0.20, 0), t=(-24, 0, 0), h=(-6, 0, 0), la=(-34, 34), ra=(-44, 30), ll=(-6, 3), rl=(90, 0))
    return [(0.0, GUARD), (0.5, chamber), (0.84, chamber), (1.0, hit), (1.25, dict(hit, hip=(0, 0.24, 0))),
            (1.8, GUARD), (2.5, GUARD)]


def slip_keys():
    """УКЛОН — slip outside the punch; the lean peaks ON the beat (0.5)."""
    s = Q(hip=(-0.16, -0.02, -0.07), t=(16, -32, -18), h=(4, 22, 22), la=(60, 14, 20), ra=(46, 20, 30),
          ll=(26, 16), rl=(-22, 4, 26))
    return [(0.0, GUARD), (0.36, mix(GUARD, s, 0.3)), (0.5, s), (0.8, s), (1.2, GUARD), (1.5, GUARD)]


def block_keys():
    """БЛОК — forearms up ON the beat (0.5)."""
    b = Q(hip=(0, -0.08, -0.04), t=(-4, 0, -8), h=(12, 0, 8), la=(98, -26, 40), ra=(98, -26, 40),
          ll=(24, 5), rl=(-24, 8, 26))
    return [(0.0, GUARD), (0.38, mix(GUARD, b, 0.3)), (0.5, b), (0.62, dict(b, hip=(0, -0.16, b["hip"][2]))),
            (1.0, b), (1.5, GUARD)]


def hit_keys():
    """Light hit reaction: the head snaps, the body follows."""
    a = Q(hip=(0, -0.08, -0.02), t=(-12, 6, 24), h=(-22, 8, 44), la=(50, 20, 20), ra=(40, 26, 30),
          ll=(20, 5), rl=(-24, 8, 26))
    return [(0.0, a), (0.3, dict(a, t=(-6, 4, 14), h=(-8, 4, 22))), (1.0, GUARD)]


def stagger_keys():
    """Heavy hit: thrown back, folded over, shaking it off."""
    a = Q(hip=(0, -0.20, 0), t=(-28, 8, 36), h=(-30, 10, 30), la=(40, 72), ra=(20, 82), ll=(34, 6), rl=(-10, 8))
    b = Q(hip=(0, -0.34, -0.04), t=(-10, 0, 10), h=(-6, 0, 8), la=(20, 40), ra=(10, 46), ll=(-16, 6), rl=(24, 8))
    c = Q(hip=(0, -0.40, -0.05), t=(34, 0, 6), h=(40, 0, 0), la=(30, 8), ra=(34, 6), ll=(26, 8), rl=(-24, 8))
    return [(0.0, a), (0.4, b), (0.9, c), (1.6, dict(c, t=(30, 3, 6))), (2.5, GUARD)]


LYING = Q(hip=(0, -1.25, -0.74), t=(-90, 0, 0), h=(-80, 0, 12), la=(20, 78), ra=(-10, 70), ll=(92, 8), rl=(86, 12),
          ground=False)


def knockdown_keys():
    """НОКДАУН — off the feet, flat on the back. (Лежачего не бьют.)"""
    air = Q(hip=(0, -0.45, 0.16), t=(-52, 0, 8), h=(-30, 0, 0), la=(70, 44), ra=(60, 50), ll=(74, 6), rl=(52, 10),
            ground=False)
    hitg = Q(hip=(0, -1.05, -0.70), t=(-84, 0, 4), h=(-60, 0, 0), la=(40, 70), ra=(30, 74), ll=(112, 8),
             rl=(100, 12), ground=False)
    return [(0.0, Q(hip=(0, -0.10, 0), t=(-24, 0, 0), h=(-20, 0, 0), la=(50, 30), ra=(40, 36), ll=(30, 4),
                    rl=(10, 6))),
            (0.45, air), (1.0, hitg), (1.25, dict(LYING, hip=(0, -1.20, -0.70), ll=(98, 8, 0))), (1.6, LYING),
            (3.0, LYING)]


def getup_keys():
    sit = Q(hip=(0, -1.05, -0.60), t=(-34, 0, 0), h=(0, 0, 0), la=(-46, 20), ra=(-46, 20), ll=(88, 8), rl=(80, 14),
            ground=False)
    crouch = Q(hip=(0, -0.70, -0.10), t=(36, 0, -10), h=(10, 0, 10), la=(30, 10), ra=(50, 10), ll=(50, 6),
               rl=(-50, 8))
    return [(0.0, LYING), (0.7, sit), (1.3, crouch), (2.0, dict(GUARD, hip=(0, -0.55, GUARD["hip"][2])))]


def flykick_keys():
    """Running flying kick. Take-off at 0, the heel lands at 1.0."""
    crouch = Q(t=(30, 0, 0), h=(4, 0, 0), la=(-50, 14), ra=(-50, 14), ll=(48, 0), rl=(-46, 0))
    air = Q(hip=(0, 0.25, 0.62), t=(-8, 0, -24), h=(0, 0, 20), la=(60, 40), ra=(-30, 50), ll=(-34, 4), rl=(70, 0),
            ground=False)
    hit = Q(hip=(0, 0.55, 0.66), t=(-36, 0, -36), h=(-12, 0, 30), la=(-20, 66), ra=(34, 46), ll=(-30, 8),
            rl=(96, 0), ground=False)
    land = Q(hip=(0, 0.95, 0), t=(26, 0, 14), h=(4, 0, -10), la=(-30, 30), ra=(20, 30), ll=(52, 4), rl=(-52, 6))
    return [(0.0, crouch), (0.45, air), (0.86, mix(air, hit, 0.6)), (1.0, hit), (1.2, hit), (1.8, land),
            (2.5, dict(GUARD, hip=(0, 0.95, GUARD["hip"][2])))]


SLIDE = Q(hip=(0, 0, -0.56), t=(-52, 0, 8), h=(-4, 0, -6), la=(-62, 28), ra=(34, 40), ll=(64, 4), rl=(84, 2),
          ground=False)


def slide_keys():
    r = sprint_keys()
    return [(0.0, r[0][1]), (0.5, SLIDE), (1.3, dict(SLIDE, hip=(0, 0, -0.575))), (2.2, SLIDE),
            (2.7, Q(t=(34, 0, 0), h=(6, 0, 0), la=(-20, 20), ra=(30, 20), ll=(54, 4), rl=(-50, 6))),
            (3.0, r[2][1])]


def pickup_keys():
    bend = Q(hip=(0, 0.05, 0), t=(72, 0, 8), h=(40, 0, 0), la=(-30, 16), ra=(6, 4), ll=(34, 6), rl=(-34, 8))
    up = Q(t=(0, -4, 0), h=(0, 0, 0), la=(4, 8), ra=(168, 14), ll=(4, 4), rl=(-4, 8, 10))
    return [(0.0, STAND), (0.6, bend), (1.0, bend), (1.6, up), (2.0, up)]


SHOULDER = Q(hip=(0.03, 0, 0), t=(0, -5, 8), h=(6, 6, -14), la=(8, 8, 30), ra=(168, 14), ll=(2, 3), rl=(-4, 12, 14))
SIT = Q(hip=(0, 0, -0.16), t=(-6, 0, 0), h=(30, 0, 0), la=(46, -8, 30), ra=(46, -8, 30), ll=(86, 6), rl=(86, 6),
        ground=False)
LEAN = Q(hip=(0, -0.05, 0), t=(-9, 0, 0), h=(22, 0, 14), la=(34, -26, 60), ra=(34, -26, 60), ll=(20, 3), rl=(4, 4))
SQUAT = Q(hip=(0, 0, -0.30), t=(10, 0, 0), h=(4, 0, 0), la=(60, 14, 20), ra=(60, 14, 20), ll=(84, 20), rl=(84, 20),
          ground=False)


def victory_keys():
    return [(0.0, STAND), (0.5, Q(hip=(0, 0, -0.03), t=(10, 0, 0), h=(14, 0, 0), ll=(14, 4), rl=(-14, 6))),
            (1.0, dict(SHOULDER, hip=(0.03, 0, 0.03))), (1.3, SHOULDER), (4.0, SHOULDER)]


def emote_keys():
    a = Q(hip=(0.07, 0, -0.01), t=(4, 7, 10), h=(4, 4, -6), la=(104, 30), ra=(-12, 20), ll=(4, 4), rl=(-6, 18, 10))
    d = Q(hip=(0.02, 0, -0.01), t=(10, 2, 0), h=(14, 0, 0), la=(50, 24), ra=(34, 24), ll=(20, 8), rl=(-20, 8))
    return [(0.0, a), (0.5, d), (1.0, a), (1.5, d), (2.0, mirror(a)), (2.5, mirror(d)), (3.0, mirror(a)),
            (3.5, mirror(d)), (4.0, a)]


def hold(p, beats=4.0):
    return [(0.0, p), (beats, p)]


CLIPS = {  # name: (keys fn, loop?)
    "Idle": (idle_keys, True), "Walk": (walk_keys, True), "Run": (run_keys, True),
    "Sprint": (sprint_keys, True), "CarryRun": (carry_keys, True), "Guard": (guard_keys, True),
    "Dvoika": (dvoika_keys, False), "Haymaker": (haymaker_keys, False), "PushKick": (pushkick_keys, False),
    "Slip": (slip_keys, False), "Block": (block_keys, False), "Hit": (hit_keys, False),
    "Stagger": (stagger_keys, False), "Knockdown": (knockdown_keys, False), "GetUp": (getup_keys, False),
    "FlyKick": (flykick_keys, False), "Slide": (slide_keys, False), "PickUp": (pickup_keys, False),
    "Victory": (victory_keys, False), "EmoteTwoStep": (emote_keys, True),
    "PoseShoulder": (lambda: hold(SHOULDER), True), "PoseSit": (lambda: hold(SIT), True),
    "PoseLean": (lambda: hold(LEAN), True), "PoseSquat": (lambda: hold(SQUAT), True),
}


def clip_keys(name, mirrored=False):
    keys = CLIPS[name][0]()
    return [(b, mirror(p)) for b, p in keys] if mirrored else keys


def clip_len(name):
    return CLIPS[name][0]()[-1][0]


def sample(name, beat, mirrored=False):
    keys = clip_keys(name, mirrored)
    a = max((k for k in keys if k[0] <= beat + 1e-6), key=lambda k: k[0])
    b = min((k for k in keys if k[0] >= beat - 1e-6), key=lambda k: k[0])
    return a[1] if a[0] == b[0] else mix(a[1], b[1], (beat - a[0]) / (b[0] - a[0]))


def bake_action(arm, name, fpb, start_frame=1):
    """One Blender action per clip (the Roblox export library)."""
    arm.animation_data_create()
    act = bpy.data.actions.new("SK_" + name)
    act.use_fake_user = True
    arm.animation_data.action = act
    prev = {}
    for b, pose in clip_keys(name):
        prev = apply_pose(arm, pose, start_frame + b * fpb, prev)
    act["loop"] = CLIPS[name][1]
    act["beats"] = clip_len(name)
    return act


class Performer:
    """Lays clips end to end on one long action (used by the trailer)."""

    def __init__(self, arm, fpb, frame0=1):
        self.arm, self.fpb, self.f0 = arm, fpb, frame0
        arm.animation_data_create()
        self.prev = {}

    def frame(self, beat):
        return self.f0 + beat * self.fpb

    def pose(self, beat, pose):
        self.prev = apply_pose(self.arm, pose, self.frame(beat), self.prev)

    def play(self, name, at, mirrored=False, loops=None, t0=0.0, t1=None, scale=1.0):
        """Key a clip starting at beat `at`. loops=N repeats a looping clip N times (float ok)."""
        keys = clip_keys(name, mirrored)
        L = keys[-1][0]
        if loops is not None:
            out, n = [], int(math.ceil(loops))
            for i in range(n):
                for b, p in keys[:-1]:
                    if i * L + b <= loops * L + 1e-6:
                        out.append((i * L + b, p))
            if abs(loops - round(loops)) < 1e-6:
                out.append((loops * L, keys[0][1]))
            keys = out
        else:
            t1 = L if t1 is None else t1
            keys = [(b - t0, p) for b, p in keys if t0 - 1e-6 <= b <= t1 + 1e-6]
        for b, p in keys:
            self.pose(at + b * scale, p)
        return at + (keys[-1][0] * scale if keys else 0)
