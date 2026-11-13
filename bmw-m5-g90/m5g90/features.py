"""Openings, panel gaps, glazing and trim regions of the M5 G90 body.

Outlines are given the way they were measured: in "photo" coordinates of the
three orthogonal press shots (profile, front, rear).  Each photo point is cast
through its camera onto the analytic body surface, so the features land where
they are on the real car regardless of later tweaks to the surface.
"""
import numpy as np
from shapely.geometry import Polygon, Point
from shapely.ops import unary_union
from shapely import affinity

from . import cut, surf, util, geom2d as G, materials as M, params as P

# The measurements were taken in the 1888x1260 reference tiles; "photo coordinates" are
# metres at a reference depth of each shot and map linearly to tile pixels (to_px).  The
# rays are cast through the matched cameras of scene.VIEWS (4 = profile, 2 = front, 8 = rear).
CAM_SIDE = dict(view="side", n=4, to_px=lambda p: (942.0 - p[:, 0] / 0.00385,
                                                   805.5 - p[:, 1] / 0.00385))
CAM_FRONT = dict(view="front", n=2, to_px=lambda p: (944.0 + p[:, 0] * 704.2,
                                                     630.0 - (p[:, 1] - 0.615) * 704.2))
CAM_REAR = dict(view="rear", n=8, to_px=lambda p: (944.0 - p[:, 0] * 556.5,
                                                   630.0 - (p[:, 1] - 0.794) * 556.5))
TILE_W, TILE_H = 1888, 1260


def _rays(cam, pts):
    from mathutils import Euler
    from .scene import VIEWS
    v = VIEWS[cam["n"]]
    px, py = cam["to_px"](np.asarray(pts, float))
    s = v["lens"] / 36.0 * TILE_W
    d_cam = np.stack([(px - TILE_W / 2) / s, (TILE_H / 2 - py) / s, -np.ones(len(px))], -1)
    R = np.array(Euler([np.radians(a) for a in v["rot"]], "XYZ").to_matrix())
    d = d_cam @ R.T
    return np.array(v["loc"], float), d


def unproject(body, cam, pts, F=None, _depth=0):
    """Photo coordinates -> 3D points on the body (first hit of the camera ray)."""
    F = F or body.F
    pts = np.asarray(pts, float)
    c, d = _rays(cam, pts)
    dist = np.linalg.norm(c)
    ts = np.arange(max(dist - 4.5, 0.5), dist + 4.5, 0.008)
    idx = np.full(len(pts), -1)
    for i, t in enumerate(ts):
        p = c + d * t
        inside = F(p[:, 0], p[:, 1], p[:, 2]) < 0
        idx = np.where((idx < 0) & inside, i, idx)
    if (idx <= 0).any():
        # points just off the silhouette: pull them towards the outline's centroid
        bad = idx <= 0
        cen = pts[~bad].mean(0) if (~bad).any() else pts.mean(0)
        if _depth > 40:
            raise ValueError(f"photo points miss the body: {pts[bad][:5]}")
        fixed = pts.copy()
        fixed[bad] = cen + (pts[bad] - cen) * 0.985
        return unproject(body, cam, fixed, F, _depth + 1)
    lo, hi = ts[idx - 1], ts[idx]
    for _ in range(24):
        mid = 0.5 * (lo + hi)
        p = c + d * mid[:, None]
        inside = F(p[:, 0], p[:, 1], p[:, 2]) < 0
        hi = np.where(inside, mid, hi)
        lo = np.where(inside, lo, mid)
    return c + d * (0.5 * (lo + hi))[:, None]


def photo(body, cam, pts):
    """Photo coordinates -> coordinates in the cutter view plane of that camera."""
    p = unproject(body, cam, pts)
    if cam["view"] == "side":
        return p[:, [0, 2]]
    return p[:, [1, 2]]


def mirror_v(poly):
    """Mirror a top-view polygon (x, y) across the centreline."""
    return affinity.scale(poly, xfact=1, yfact=-1, origin=(0, 0))


def mirror_u(poly):
    """Mirror a front/rear-view polygon (y, z) across the centreline."""
    return affinity.scale(poly, xfact=-1, yfact=1, origin=(0, 0))


def sym_top(half_pts, step=0.004):
    """Closed top-view polygon from a half outline running from centre to centre (y >= 0)."""
    c = G.spline_open(half_pts, step) if not isinstance(half_pts[0][0], (list, tuple)) \
        else G.path(half_pts, step)
    full = np.vstack([c, c[::-1][1:-1] * [1, -1]])
    return Polygon(full).buffer(0)


def sym_front(half_segments, step=0.004):
    """Closed front/rear-view polygon from a half outline (y >= 0) centre -> centre."""
    c = G.path(half_segments, step)
    full = np.vstack([c, c[::-1][1:-1] * [-1, 1]])
    return Polygon(full).buffer(0)


# ---------------------------------------------------------------------------
# measured outlines (photo coordinates)
# ---------------------------------------------------------------------------
# profile shot: (x, z) at the near flank
BELT = [(0.700, 1.004), (0.40, 1.005), (0.00, 1.013), (-0.50, 1.033), (-1.00, 1.058),
        (-1.440, 1.082)]
DLO_REAR = [(-1.440, 1.082), (-1.458, 1.150), (-1.468, 1.210), (-1.452, 1.256)]
DLO_TOP = [(-1.452, 1.256), (-1.30, 1.312), (-1.10, 1.360), (-0.90, 1.390), (-0.60, 1.406),
           (-0.30, 1.405), (0.00, 1.388), (0.070, 1.368)]
DLO_A = [(0.070, 1.368), (0.700, 1.004)]
B_FRONT = [(-0.246, 1.035), (-0.376, 1.380)]      # B-pillar cover edges
B_REAR = [(-0.499, 1.035), (-0.458, 1.380)]
Q_FRONT = [(-1.092, 1.070), (-1.092, 1.330)]      # quarter-light divider
Q_REAR = [(-1.118, 1.070), (-1.118, 1.330)]
C_TRIM = [(-1.462, 1.248), (-1.520, 1.212), (-1.618, 1.168), (-1.520, 1.122), (-1.448, 1.092),
          (-1.470, 1.170)]

DOOR_GAP = [[(0.700, 1.000), (0.770, 0.955), (0.805, 0.900), (0.816, 0.800), (0.816, 0.500),
             (0.806, 0.345)],
            [(0.806, 0.345), (-0.925, 0.335)],
            [(-0.925, 0.335), (-1.000, 0.420), (-1.080, 0.520), (-1.200, 0.720), (-1.300, 0.862),
             (-1.380, 0.985), (-1.440, 1.080)]]
B_GAP = [(-0.305, 0.337), (-0.312, 0.600), (-0.326, 0.900), (-0.345, 1.030)]
SILL_F = [(1.135, 0.340), (0.806, 0.345)]
CHARGE_FLAP = [(0.885, 0.822), (1.095, 0.830), (1.120, 0.800), (1.122, 0.700), (1.050, 0.655),
               (0.905, 0.650), (0.872, 0.685), (0.868, 0.790)]
FUEL_FLAP = [(-1.790, 0.962), (-1.985, 0.966), (-2.020, 0.935), (-2.020, 0.880), (-1.975, 0.852),
             (-1.800, 0.848), (-1.772, 0.880), (-1.770, 0.935)]
HANDLE_F = (-0.085, 0.897, 0.245, 0.050)      # centre x, z, length, height (photo coords)
HANDLE_R = (-1.065, 0.930, 0.245, 0.050)
BUMPER_R_JOINT = [(-1.752, 0.688), (-1.900, 0.742), (-2.000, 0.800), (-2.085, 0.872)]
BUMPER_F_JOINT = [(1.955, 0.722), (1.870, 0.706), (1.782, 0.696)]
HEAD_SIDE_TIP = (1.770, 0.862)
TAIL_SIDE = [[(-2.385, 0.872), (-2.250, 0.868), (-2.085, 0.872)],
             [(-2.085, 0.872), (-2.150, 0.935), (-2.215, 0.982)],
             [(-2.215, 0.982), (-2.300, 0.985), (-2.385, 0.968)]]

HEAD_SIDE = [(2.075, 0.700), (1.970, 0.716), (1.880, 0.790), (1.770, 0.862), (1.900, 0.851),
             (2.075, 0.815)]
TAIL_SIDE_POLY = [(-2.335, 0.872), (-2.250, 0.868), (-2.085, 0.872), (-2.150, 0.935),
                  (-2.215, 0.982), (-2.335, 0.976)]

# front shot: (y, z) at the grille plane
KIDNEY = [[(0.000, 0.530), (0.012, 0.500), (0.060, 0.492), (0.200, 0.492), (0.318, 0.500)],
          [(0.318, 0.500), (0.395, 0.542), (0.452, 0.622)],
          [(0.452, 0.622), (0.458, 0.668), (0.440, 0.712), (0.395, 0.742), (0.340, 0.752)],
          [(0.340, 0.752), (0.200, 0.756), (0.110, 0.750), (0.035, 0.728), (0.000, 0.700)]]
HEADLIGHT = [[(0.478, 0.708), (0.540, 0.722), (0.620, 0.746), (0.700, 0.778)],
             [(0.700, 0.778), (0.732, 0.735), (0.748, 0.672)],
             [(0.748, 0.672), (0.700, 0.652), (0.620, 0.642), (0.555, 0.636), (0.505, 0.655)],
             [(0.505, 0.655), (0.478, 0.708)]]
DRL_IN = [(0.578, 0.728), (0.596, 0.733), (0.612, 0.668), (0.660, 0.668), (0.660, 0.655),
          (0.590, 0.655)]
DRL_OUT = [(0.692, 0.770), (0.712, 0.770), (0.726, 0.672), (0.706, 0.660), (0.640, 0.650),
           (0.640, 0.662), (0.702, 0.676)]
INTAKE = [[(0.000, 0.448), (0.250, 0.448), (0.432, 0.446)],
          [(0.432, 0.446), (0.520, 0.365), (0.612, 0.276)],
          [(0.612, 0.276), (0.560, 0.238), (0.505, 0.205)],
          [(0.505, 0.205), (0.250, 0.200), (0.000, 0.200)]]
SIDE_INTAKE = [(0.764, 0.428), (0.708, 0.292), (0.802, 0.276)]
HOOD_FRONT = [(0.000, 0.776), (0.110, 0.776), (0.300, 0.772), (0.420, 0.752), (0.478, 0.712)]

# rear shot: (y, z) at the tail plane (y positive towards the car's left)
TAIL = [[(0.272, 0.905), (0.330, 0.936), (0.450, 0.956), (0.600, 0.966), (0.772, 0.976)],
        [(0.772, 0.976), (0.812, 0.925), (0.846, 0.866)],
        [(0.846, 0.866), (0.700, 0.862), (0.500, 0.864), (0.330, 0.880), (0.272, 0.905)]]
TRUNK = [(0.676, 1.060), (0.668, 0.960), (0.660, 0.862), (0.630, 0.762), (0.570, 0.692),
         (0.470, 0.656), (0.300, 0.648), (0.000, 0.648)]
REFLECTOR = [(0.868, 0.655), (0.892, 0.648), (0.898, 0.445), (0.872, 0.438)]
DIFFUSER = [[(0.130, 0.496), (0.400, 0.498), (0.700, 0.496)],
            [(0.700, 0.496), (0.790, 0.430), (0.862, 0.372)],
            [(0.862, 0.372), (0.800, 0.300), (0.770, 0.240)],
            [(0.770, 0.240), (0.400, 0.225), (0.045, 0.225)],
            [(0.045, 0.225), (0.130, 0.496)]]
EXHAUST = [(0.530, 0.305, 0.052), (0.645, 0.308, 0.052)]
PLATE_R = (0.0, 0.778)


# ---------------------------------------------------------------------------
class Features:
    def __init__(self, body, shell, collection=None, edge=0.008, log=print):
        self.body, self.shell, self.coll, self.edge, self.log = body, shell, collection, edge, log
        self.parts = []
        self.black = M.gloss_black()
        self.gap = M.matte_black()

    # -- helpers ------------------------------------------------------------
    def side_poly(self, segs, round_r=0.0):
        segs = [segs] if not isinstance(segs[0], list) else segs
        return G.polygon([photo(self.body, CAM_SIDE, s) for s in segs], round_r=round_r)

    def cut_follow(self, poly, view, sign, depth, mat=None, inner=None, proud=0.05, edge=None,
                   const_floor=None):
        cs = cut.follow("Cut", self.body, poly, view, sign, depth, proud=proud,
                        edge=edge or self.edge, inner=inner, mat=mat, const_floor=const_floor)
        cut.boolean(self.shell, cs)

    def groove(self, pts, view, sign, width=0.0042, depth=0.014, closed=False):
        band = G.stroke(pts, width, closed=closed)
        self.cut_follow(band, view, sign, depth, mat=self.gap, proud=0.02, edge=0.006)

    def add(self, obj, name=None):
        if obj is None:
            return None
        if name:
            obj.name = name
            obj.data.name = name
        if self.coll is not None:
            for c in obj.users_collection:
                c.objects.unlink(obj)
            self.coll.objects.link(obj)
        self.parts.append(obj)
        return obj

    def skin(self, name, poly, view, sign, mat, offset=0.0, thickness=0.0, inner=None, edge=None):
        return self.add(cut.skin(name, self.body, poly, view, sign, offset=offset,
                                 edge=edge or self.edge, inner=inner, mat=mat,
                                 thickness=thickness), name)

    # -- cabin ----------------------------------------------------------------
    def cavity(self, h=0.03):
        b = self.body

        def Fc(x, y, z):
            ay = np.abs(y)
            f = np.maximum(b.F(x, y, z) + 0.050, 0.27 - z)
            f = np.maximum(f, np.maximum(x - 1.04, -1.93 - x))
            r = np.hypot(x - surf.AXR, z - surf.ZWR)
            well = np.minimum(0.45 - r, ay - 0.48)
            return np.maximum(f, well)

        c = cut.build_master(b, h, name="Cavity", F=Fc, bounds=((-2.0, 1.1), (0.95,), (0.2, 1.48)),
                             spine_x=(-1.3, 0.45), spine_z=0.75)
        c.data.materials.append(M.interior_plastic())
        cut.boolean(self.shell, c)
        self.log("cabin cavity")

    # -- glazing ----------------------------------------------------------------
    def side_glass(self):
        b = self.body
        dlo = self.side_poly([BELT, DLO_REAR, DLO_TOP, DLO_A])
        def ext(pts):                      # line through two glass points, extended
            a, c = photo(b, CAM_SIDE, pts)
            return a - (c - a) * 0.25, c + (c - a) * 0.25
        bf, br, qf, qr = ext(B_FRONT), ext(B_REAR), ext(Q_FRONT), ext(Q_REAR)
        bpil = Polygon([bf[0], bf[1], br[1], br[0]])
        qpil = Polygon([qf[0], qf[1], qr[1], qr[0]])
        panes = dlo.difference(bpil).difference(qpil)
        panes = [G.rounded(p, 0.012) for p in sorted(panes.geoms, key=lambda g: -g.centroid.x)]
        ctrim = G.rounded(self.side_poly(C_TRIM), 0.008)
        frame = G.offset(dlo, 0.016).union(ctrim)
        for s in (1, -1):
            # gloss-black window surround (shadow line) as a 1.2 mm recess
            self.cut_follow(frame, "side", s, 0.0012, mat=self.black, inner=0.012)
            for i, p in enumerate(panes):
                self.cut_follow(G.offset(p, -0.004), "side", s, 0.085, mat=self.black, inner=0.03)
            sfx = "L" if s > 0 else "R"
            self.skin(f"Glass_Door_F_{sfx}", G.offset(panes[0], 0.004), "side", s,
                      M.window_glass("front"), offset=-0.0022, thickness=0.004, inner=0.012)
            self.skin(f"Glass_Door_R_{sfx}", unary_union([G.offset(p, 0.004) for p in panes[1:]]),
                      "side", s, M.window_glass("rear"), offset=-0.0022, thickness=0.004,
                      inner=0.012)
            self.skin(f"Trim_CPillar_{sfx}", G.offset(ctrim, -0.003), "side", s, M.aluminium(),
                      offset=-0.0004, thickness=0.0015)
        self.log("side glazing")

    def top_glass(self):
        ws = sym_top([[(0.972, 0.0), (0.935, 0.30), (0.842, 0.57), (0.738, 0.742)],
                      [(0.738, 0.742), (0.420, 0.682), (0.108, 0.612)],
                      [(0.108, 0.612), (0.150, 0.30), (0.160, 0.0)]])
        ws = G.rounded(ws, 0.02)
        bl = sym_top([[(-2.088, 0.0), (-2.062, 0.30), (-2.004, 0.56), (-1.972, 0.655)],
                      [(-1.972, 0.655), (-1.650, 0.622), (-1.360, 0.582)],
                      [(-1.360, 0.582), (-1.405, 0.30), (-1.418, 0.0)]])
        bl = G.rounded(bl, 0.02)
        roof = sym_top([[(0.060, 0.0), (0.050, 0.30), (0.030, 0.515)],
                        [(0.030, 0.515), (-0.60, 0.535), (-1.285, 0.500)],
                        [(-1.285, 0.500), (-1.310, 0.30), (-1.318, 0.0)]])
        roof = G.rounded(roof, 0.035)
        for name, poly, frit, depth, kind in (("Windscreen", ws, 0.030, 0.085, "screen"),
                                              ("Backlight", bl, 0.034, 0.085, "rear"),
                                              ("Roof", roof, 0.060, 0.085, "roof")):
            glass = M.window_glass(kind)
            self.cut_follow(poly, "top", 1, 0.0045, mat=self.black, inner=0.02)
            self.cut_follow(G.offset(poly, -frit), "top", 1, depth, mat=self.black, inner=0.04)
            self.skin(f"Glass_{name}", G.offset(poly, -0.002), "top", 1, glass, offset=-0.0005,
                      thickness=0.004, inner=0.015)
        self.log("windscreen, backlight, glass roof")

    # -- shut lines -------------------------------------------------------------
    def gaps(self):
        b = self.body
        for s in (1, -1):
            door = G.path([photo(b, CAM_SIDE, seg) for seg in DOOR_GAP])
            self.groove(door, "side", s)
            self.groove(G.spline_open(photo(b, CAM_SIDE, B_GAP)), "side", s)
            self.groove(photo(b, CAM_SIDE, SILL_F), "side", s)
            self.groove(G.spline_open(photo(b, CAM_SIDE, BUMPER_R_JOINT)), "side", s)
            self.groove(G.spline_open(photo(b, CAM_SIDE, BUMPER_F_JOINT)), "side", s)
        flap = G.spline_closed(photo(b, CAM_SIDE, CHARGE_FLAP))
        self.groove(flap, "side", 1, width=0.003, depth=0.008, closed=True)
        flap = G.spline_closed(photo(b, CAM_SIDE, FUEL_FLAP))
        self.groove(flap, "side", -1, width=0.003, depth=0.008, closed=True)
        # flush door handles: outline groove + grip pocket under the paddle
        for (cx, cz, L, Hh) in (HANDLE_F, HANDLE_R):
            rect = [(cx - L / 2, cz - Hh / 2), (cx + L / 2, cz - Hh / 2 + 0.006),
                    (cx + L / 2, cz + Hh / 2 + 0.006), (cx - L / 2, cz + Hh / 2)]
            hp = G.rounded(Polygon(photo(b, CAM_SIDE, rect)), 0.016)
            x0, z0, x1, z1 = hp.bounds
            from shapely.geometry import box as sbox
            grip = G.rounded(hp.intersection(sbox(x0, z0, x1, z0 + 0.42 * (z1 - z0))), 0.006)
            for s in (1, -1):
                self.cut_follow(grip, "side", s, 0.022, mat=self.gap, inner=0.01, proud=0.02,
                                edge=0.005)
                self.groove(np.array(hp.exterior.coords)[:-1], "side", s, width=0.0028,
                            depth=0.006, closed=True)
        self.log("door / flap / bumper shut lines")
        # bonnet: front edge from the front shot, flanks in plan
        hf = unproject(b, CAM_FRONT, HOOD_FRONT)
        tip = unproject(b, CAM_SIDE, [HEAD_SIDE_TIP])[0]
        front_edge = hf[:, [0, 1]]
        plan = np.vstack([front_edge, [(tip[0] + 0.10, tip[1] - 0.012), (tip[0], tip[1])],
                          [(1.50, 0.812), (1.10, 0.806), (0.86, 0.792)],
                          ])
        c = G.spline_open(plan)
        for sgn in (1, -1):
            self.groove(c * [1, sgn], "top", 1)
        # boot lid: rear face from the rear shot, flanks of the deck in plan
        tr = unproject(b, CAM_REAR, TRUNK)
        for sgn in (1, -1):
            self.groove(G.spline_open(tr[:, [1, 2]]) * [sgn, 1], "rear", -1)
            self.groove(np.array([(tr[0, 0] + 0.03, tr[0, 1]), (-2.20, 0.682), (-2.02, 0.668)])
                        * [1, sgn], "top", 1)
        self.log("bonnet and boot shut lines")

    # -- front end --------------------------------------------------------------
    def front(self):
        b = self.body
        kid = sym_front([photo(b, CAM_FRONT, s) for s in KIDNEY])
        kid = G.rounded(kid, 0.012)
        self.kidney = kid
        self.cut_follow(kid, "front", 1, 0.060, mat=self.black, inner=0.02)
        head = G.rounded(G.polygon([photo(b, CAM_FRONT, s) for s in HEADLIGHT]), 0.006)
        intake = G.rounded(sym_front([photo(b, CAM_FRONT, s) for s in INTAKE]), 0.008)
        sidei = G.rounded(Polygon(photo(b, CAM_FRONT, SIDE_INTAKE)), 0.006)
        self.intake = intake
        housing = M.principled("Lamp_Housing_Black", color=(0.008, 0.008, 0.009), roughness=0.38)
        self.cut_follow(intake, "front", 1, 0.0025, mat=self.black, inner=0.02)
        self.cut_follow(G.offset(intake, -0.035), "front", 1, 0.14, mat=M.matte_black(), inner=0.03)
        lens = M.clear_glass()
        hside = G.rounded(Polygon(photo(b, CAM_SIDE, HEAD_SIDE)), 0.004)
        for sgn in (1, -1):
            sfx = "L" if sgn > 0 else "R"
            hp = head if sgn > 0 else mirror_u(head)
            self.cut_follow(hp, "front", 1, 0.085, mat=housing, inner=0.02)
            self.cut_follow(hside, "side", sgn, 0.045, mat=housing, inner=0.02)
            self.skin(f"Lens_Head_{sfx}", G.offset(hp, 0.0015), "front", 1, lens, offset=-0.0008,
                      thickness=0.003, inner=0.012)
            self.skin(f"Lens_HeadSide_{sfx}", G.offset(hside, 0.0015), "side", sgn, lens,
                      offset=-0.0008, thickness=0.003, inner=0.012)
            for nm, pts in (("In", DRL_IN), ("Out", DRL_OUT)):
                dp = Polygon(photo(b, CAM_FRONT, pts)).buffer(0).buffer(-0.0025)
                dp = dp if sgn > 0 else mirror_u(dp)
                self.skin(f"DRL_{nm}_{sfx}", dp, "front", 1, M.emit_white(), offset=-0.030,
                          thickness=0.010, inner=0.006, edge=0.004)
            sp = sidei if sgn > 0 else mirror_u(sidei)
            c = np.array(sp.exterior.coords)
            xs = cut.first_hit(b.F, "front", c, *cut.RANGES[("front", 1)])
            self.cut_follow(sp, "front", 1, 0.09, mat=self.gap, inner=0.02,
                            const_floor=float(np.nanmin(xs)) - 0.06)
        self.log("kidney, headlights, intakes")

    # -- rear end ---------------------------------------------------------------
    def rear(self):
        b = self.body
        tail = G.rounded(G.polygon([photo(b, CAM_REAR, s) for s in TAIL]), 0.005)
        refl = G.rounded(Polygon(photo(b, CAM_REAR, REFLECTOR)), 0.004)
        diff = G.rounded(G.polygon([photo(b, CAM_REAR, s) for s in DIFFUSER]), 0.008)
        self.diffuser = diff
        red = M.red_lens()
        dark = M.principled("Lamp_Housing_Dark", color=(0.022, 0.002, 0.002), roughness=0.4)
        tside = G.rounded(Polygon(photo(b, CAM_SIDE, TAIL_SIDE_POLY)), 0.004)
        for sgn in (1, -1):
            sfx = "L" if sgn > 0 else "R"
            tp = tail if sgn > 0 else mirror_u(tail)
            self.cut_follow(tp, "rear", -1, 0.030, mat=dark, inner=0.015)
            self.cut_follow(tside, "side", sgn, 0.022, mat=dark, inner=0.015)
            self.skin(f"Lens_Tail_{sfx}", G.offset(tp, 0.001), "rear", -1, red, offset=-0.0006,
                      thickness=0.003, inner=0.012)
            self.skin(f"Lens_TailSide_{sfx}", G.offset(tside, 0.001), "side", sgn, red,
                      offset=-0.0006, thickness=0.003, inner=0.012)
            rp = refl if sgn > 0 else mirror_u(refl)
            self.skin(f"Reflector_{sfx}", rp, "rear", -1, M.principled(
                "Reflector_Red", color=(0.35, 0.005, 0.005), roughness=0.15, coat=1.0),
                offset=0.0012, thickness=0.003, inner=0.008, edge=0.005)
            dp = diff if sgn > 0 else mirror_u(diff)
            self.cut_follow(dp, "rear", -1, 0.010, mat=M.satin_black(), inner=0.02)
            ex = G.rounded(Polygon(photo(b, CAM_REAR, [(0.455, 0.372), (0.722, 0.376),
                                                        (0.722, 0.246), (0.455, 0.242)])), 0.02)
            ex = ex if sgn > 0 else mirror_u(ex)
            self.cut_follow(ex, "rear", -1, 0.16, mat=self.gap, inner=0.03)
        self.log("tail lights, reflectors, diffuser")

    # -- black lower trim -------------------------------------------------------
    def trim(self):
        from shapely.geometry import box as sbox
        sb = M.satin_black()
        self.cut_follow(sbox(-0.99, 0.10, 0.99, 0.214), "front", 1, 0.002, mat=sb, inner=0.03)
        valance = Polygon([(-1.86, 0.10), (-1.86, 0.250), (-2.10, 0.300), (-2.40, 0.392),
                           (-2.80, 0.520), (-2.80, 0.10)])
        for s in (1, -1):
            self.cut_follow(sbox(-1.14, 0.10, 1.14, 0.222), "side", s, 0.002, mat=sb, inner=0.03)
            self.cut_follow(valance, "side", s, 0.002, mat=sb, inner=0.03)
        self.log("lower trim")

    def run(self, stages):
        for st in stages:
            getattr(self, st)()
        return self.parts
