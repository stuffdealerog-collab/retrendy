"""Master body surface of the M5 G90 as an implicit function F(x, y, z) <= 0.

The body is described the way a clay model is: by a handful of height fields

    side   |y| <= Yl(x, z)        (flanks, wheel-arch flares, sill)
    top    z   <= Zl(x, |y|)      (bonnet, shoulders, boot lid)
    front  x   <= Xf(|y|, z)      (nose / front bumper)
    rear   x   >= Xr(|y|, z)      (tail / rear bumper)
    under  z   >= Zb(x, |y|)

intersected with conic-like (C2) blends, plus a greenhouse (windscreen, roof,
backlight, side glass) united on top of it.  Every height field is tabulated on
a fine grid and evaluated with cubic B-spline interpolation, so F is cheap and
smooth and can be meshed at any resolution (see mesher.py).
"""
import numpy as np
from scipy import ndimage
from scipy.interpolate import CubicSpline, PchipInterpolator

from . import params as P


# ---------------------------------------------------------------------------
# small maths helpers
# ---------------------------------------------------------------------------
def curve(pts, kind="cubic"):
    """Spline through (t, v) control points, any order of t; linear extrapolation."""
    pts = sorted(pts)
    t = np.array([p[0] for p in pts], float)
    v = np.array([p[1] for p in pts], float)
    f = CubicSpline(t, v, bc_type="natural") if kind == "cubic" else PchipInterpolator(t, v)
    d0, d1 = float(f(t[0], 1)), float(f(t[-1], 1))

    def ev(x):
        x = np.asarray(x, float)
        y = f(np.clip(x, t[0], t[-1]))
        y = np.where(x < t[0], v[0] + d0 * (x - t[0]), y)
        y = np.where(x > t[-1], v[-1] + d1 * (x - t[-1]), y)
        return y

    return ev


def sstep(e0, e1, x):
    """C2 smootherstep from 0 at e0 to 1 at e1 (works for e0 > e1 too)."""
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * t * (t * (t * 6 - 15) + 10)


def smax(a, b, k):
    """C2 smooth maximum with finite support |a-b| < k (k may be an array)."""
    h = np.maximum(k - np.abs(a - b), 0.0) / k
    return np.maximum(a, b) + h * h * h * k * (1.0 / 6.0)


def smin(a, b, k):
    return -smax(-a, -b, k)


def bump(x, c, w):
    """Smooth compact bump: 1 at c, 0 beyond c +- w (C2)."""
    t = np.clip(np.abs(x - c) / w, 0.0, 1.0)
    return 1 - t * t * t * (t * (t * 6 - 15) + 10)


def ppow(x, p):
    return np.power(np.maximum(x, 0.0), p)


class Table:
    """2D height field on a regular grid with cubic interpolation."""

    def __init__(self, u, v, values, smooth=0.0):
        self.u0, self.du = float(u[0]), float(u[1] - u[0])
        self.v0, self.dv = float(v[0]), float(v[1] - v[0])
        vals = np.asarray(values, np.float64)
        if smooth:
            vals = ndimage.gaussian_filter(vals, smooth, mode="nearest")
        self.values = vals
        self.coef = ndimage.spline_filter(vals, order=3, mode="nearest")

    def __call__(self, u, v):
        u = np.asarray(u, np.float64)
        v = np.asarray(v, np.float64)
        shp = np.broadcast(u, v).shape
        cu = (np.broadcast_to(u, shp).ravel() - self.u0) / self.du
        cv = (np.broadcast_to(v, shp).ravel() - self.v0) / self.dv
        out = ndimage.map_coordinates(self.coef, [cu, cv], order=3, mode="nearest", prefilter=False)
        return out.reshape(shp)


# ---------------------------------------------------------------------------
# design curves (all metres, car coordinates)
# ---------------------------------------------------------------------------
XF, XR = P.X_FRONT, P.X_REAR
AXF, AXR = P.AXLE_F_X, P.AXLE_R_X
ZWF, ZWR = P.WHEEL_F_Z, P.WHEEL_R_Z
ARCH_R_F = 0.392      # wheel-arch opening radius
ARCH_R_R = 0.398

# waist half-width (widest line of the flank, flares excluded)
waist_y = curve([(2.45, 0.815), (2.30, 0.850), (2.15, 0.888), (1.95, 0.925), (1.50, 0.943),
                 (1.00, 0.947), (0.00, 0.950), (-1.00, 0.948), (-1.50, 0.948), (-2.00, 0.956),
                 (-2.40, 0.962), (-2.75, 0.955)], "pchip")
# shoulder / belt height
shoulder_z = curve([(2.45, 0.735), (2.20, 0.795), (2.00, 0.842), (1.75, 0.888), (1.50, 0.920),
                    (1.20, 0.955), (0.90, 0.980), (0.72, 0.992), (0.00, 1.008), (-0.50, 1.030),
                    (-1.00, 1.055), (-1.40, 1.075), (-1.80, 1.062), (-2.10, 1.035),
                    (-2.40, 1.000), (-2.75, 0.960)])
# how far the flank leans in between waist and shoulder
lean_up = curve([(2.45, 0.170), (2.00, 0.165), (1.50, 0.145), (0.95, 0.105), (0.60, 0.068),
                 (0.00, 0.064), (-1.00, 0.066), (-1.40, 0.078), (-1.80, 0.094), (-2.30, 0.096),
                 (-2.75, 0.100)], "pchip")
# lower edge of the flank
sill_z = curve([(2.45, 0.200), (1.95, 0.200), (1.10, 0.185), (-1.10, 0.185), (-1.95, 0.235),
                (-2.40, 0.320), (-2.75, 0.390)], "pchip")
# tuck-under below the waist
tuck_lo = curve([(2.45, 0.020), (1.10, 0.012), (-1.10, 0.012), (-1.95, 0.016), (-2.75, 0.025)],
                "pchip")

# centreline of the lower body top: bonnet ... (hidden under the cabin) ... boot lid
low_top_z = curve([(2.47, 0.715), (2.35, 0.795), (2.20, 0.856), (2.10, 0.886), (1.90, 0.935),
                   (1.70, 0.967), (1.50, 0.990), (1.30, 1.010), (1.10, 1.030), (0.95, 1.044),
                   (0.70, 1.010), (0.00, 1.022), (-0.50, 1.044), (-1.00, 1.069), (-1.40, 1.092),
                   (-1.80, 1.112), (-2.12, 1.110), (-2.23, 1.086), (-2.33, 1.068),
                   (-2.44, 1.056), (-2.55, 1.046), (-2.75, 1.030)], "pchip")

# greenhouse centreline: windscreen - roof - backlight
roof_z = curve([(1.30, 0.860), (0.97, 1.030), (0.75, 1.150), (0.50, 1.288), (0.30, 1.385),
                (0.15, 1.440), (0.00, 1.474), (-0.21, 1.495), (-0.42, 1.505), (-0.64, 1.506),
                (-0.85, 1.497), (-1.06, 1.478), (-1.27, 1.445), (-1.48, 1.388), (-1.59, 1.350),
                (-1.80, 1.252), (-2.01, 1.152), (-2.12, 1.102), (-2.40, 0.975)])
# glass plane half-width at the belt line (plan view of the greenhouse)
glass_y = curve([(1.20, 0.640), (0.95, 0.730), (0.72, 0.800), (0.40, 0.835), (0.00, 0.850),
                 (-0.50, 0.852), (-1.00, 0.842), (-1.40, 0.810), (-1.80, 0.745), (-2.10, 0.665),
                 (-2.45, 0.540)])

# nose and tail profiles on the centreline: x as a function of z
nose_x = curve([(0.10, 2.350), (0.17, 2.382), (0.24, 2.400), (0.35, 2.406), (0.50, 2.408),
                (0.62, 2.406), (0.70, 2.394), (0.78, 2.356), (0.84, 2.290), (0.95, 2.050)],
               "pchip")
tail_x = curve([(0.15, -2.380), (0.25, -2.520), (0.33, -2.600), (0.42, -2.635), (0.52, -2.645),
                (0.62, -2.640), (0.75, -2.615), (0.85, -2.585), (0.93, -2.560), (1.00, -2.535),
                (1.08, -2.500), (1.20, -2.420)], "pchip")
# underside
under_z = curve([(2.45, 0.165), (1.90, 0.150), (-1.90, 0.150), (-2.30, 0.220), (-2.75, 0.330)],
                "pchip")


def chin(z):
    """Front bumper below the ridge at kidney-bottom height: scoops back, then the lip steps out."""
    zr = 0.497
    t = np.clip((zr - z) / 0.15, 0.0, 1.0)
    return 0.075 * t ** 1.25 - 0.070 * sstep(0.275, 0.228, z)


def k_shoulder(x):
    """Blend size between flank and top: soft over the wings, crisp at the door belt."""
    k = 0.11 + 0.03 * sstep(1.2, 2.2, x)                     # front wings
    k = np.where(x < 0.95, 0.11 - 0.085 * sstep(0.95, 0.55, x), k)   # into the doors
    k = np.where(x < -0.9, 0.025 + 0.095 * sstep(-0.9, -1.7, x), k)  # rear haunch
    return k


def top_power(x):
    p = 2.5 + 1.5 * sstep(1.0, 0.6, x)           # bonnet -> flat belt ledge
    p = np.where(x < -1.2, 4.0 - 1.2 * sstep(-1.2, -2.1, x), p)
    return p


# ---------------------------------------------------------------------------
class Body:
    """Tabulated height fields + the combined implicit function."""

    def __init__(self, step=0.005):
        self.step = step
        self._build_tables()

    # -- individual analytic fields (evaluated once on grids) -----------------
    @staticmethod
    def flare(x, z):
        """Outward wheel-arch flare added to the flank."""
        out = 0.0
        for xw, zw, ra, amp, wf, wr in ((AXF, ZWF, ARCH_R_F, 0.990, 0.30, 0.34),
                                         (AXR, ZWR, ARCH_R_R, 0.984, 0.36, 0.46)):
            dx, dz = x - xw, z - zw
            r = np.hypot(dx, dz)
            a = amp - waist_y(xw)                       # needed extra width at the lip
            w = np.where(dx > 0, wf, wr)                # falls off slower towards the rear
            s = np.clip((r - ra) / w, 0.0, 1.0)
            radial = (1 - s * s) ** 3                   # 1 at the lip, 0 at lip + w
            below = sstep(-0.42, 0.02, dz)              # fades out towards the sill
            out = out + a * radial * below
        return out

    @staticmethod
    def side_y(x, z):
        zs, z4 = sill_z(x), shoulder_z(x)
        u = (z - zs) / (z4 - zs)
        u0 = 0.42
        pu = 2.3 - 0.55 * sstep(0.75, 1.35, x)        # wings start rolling in earlier
        y = waist_y(x) - tuck_lo(x) * ppow((u0 - u) / u0, 2.2) \
            - lean_up(x) * ppow((u - u0) / (1 - u0), pu)
        # shoulder line: a crisp fold ~6 cm under the belt, running from lamp to lamp
        d = z - (z4 - 0.062)
        on = sstep(2.05, 1.75, x) * sstep(-2.45, -2.20, x)
        y = y - on * 0.30 * 0.5 * (d + np.sqrt(d * d + 0.007 ** 2))
        # sill: the lower door scallops in below a rising crease, then the skirt steps out
        mid = sstep(1.13, 0.98, x) * sstep(-1.16, -0.98, x)
        zc = 0.445 + 0.022 * (0.8 - x)
        zt = 0.338
        t = np.clip((zc - z) / (zc - zt), 0.0, 1.0)
        scallop = 0.040 * t ** 1.45
        skirt = 0.047 * sstep(zt + 0.020, zt - 0.020, z)
        y = y + Body.flare(x, z) + mid * (skirt - scallop)
        # front corner follows the bumper's chin
        y = y - sstep(1.94, 2.06, x) * chin(z)
        # rear: the wide wheel-arch box ends in a vertical edge, the tail behind it is narrower
        xe = -2.285 - 0.20 * (0.72 - z)
        notch = sstep(xe + 0.008, xe - 0.016, x) * sstep(0.36, 0.41, z) * sstep(0.80, 0.73, z)
        return y - 0.072 * notch

    @staticmethod
    def top_z(x, ay):
        zc, z4 = low_top_z(x), shoulder_z(x)
        ye = waist_y(x) - lean_up(x) - 0.019 * sstep(2.05, 1.75, x) * sstep(-2.45, -2.20, x)
        drop = np.maximum(zc - z4, 0.004)
        z = zc - drop * ppow(ay / ye, top_power(x))
        # bonnet: two creases fanning out from the roundel to the A-pillars, shallow valley between
        on = sstep(0.95, 1.25, x) * sstep(2.40, 2.22, x)
        yc = 0.085 + 0.50 * ppow((2.36 - x) / 1.42, 1.15)
        valley = 0.016 * on * ppow(1 - (ay / yc) ** 2, 1.0)
        # boot lid: slight raised centre with the spoiler kick at the trailing edge
        return z - valley

    @staticmethod
    def front_x(ay, z):
        hi = sstep(0.52, 0.80, z)                       # more plan sweep higher up
        sweep = (0.15 + 0.20 * hi) * ay ** 2.2 + (0.10 + 0.10 * hi) * ppow((ay - 0.74) / 0.20, 3.0)
        return nose_x(z) - sweep - sstep(0.44, 0.57, ay) * chin(z)

    @staticmethod
    def rear_x(ay, z):
        hi = sstep(0.60, 0.95, z)
        sweep = (0.185 + 0.06 * hi) * ay ** 1.9 + 0.10 * hi * ppow((ay - 0.80) / 0.16, 3.0)
        # number-plate cove in the boot lid
        cove = 0.022 * sstep(0.60, 0.44, ay) * sstep(0.665, 0.715, z) * sstep(0.905, 0.865, z)
        return tail_x(z) + sweep + cove

    @staticmethod
    def green_top(x, ay):
        wf = sstep(-0.25, 0.45, x)
        wr = sstep(-0.95, -1.65, x)
        xe = x + 0.27 * (ay / 0.75) ** 2 * wf - 0.21 * (ay / 0.70) ** 2 * wr
        return roof_z(xe) - 0.050 * ppow(ay / 0.60, 2.3)

    @staticmethod
    def green_side(x, z):
        dz = np.maximum(z - shoulder_z(x), -0.03)
        return glass_y(x) - 0.33 * dz - 0.32 * dz * np.abs(dz)

    # -- tables -------------------------------------------------------------
    def _build_tables(self):
        s = self.step
        xs = np.arange(-2.90, 2.60 + s, s)
        zs = np.arange(-0.05, 1.70 + s, s)
        ys = np.arange(0.0, 1.20 + s, s)
        X, Z = np.meshgrid(xs, zs, indexing="ij")
        self.t_side = Table(xs, zs, self.side_y(X, Z))
        self.t_gside = Table(xs, zs, self.green_side(X, Z))
        X, Y = np.meshgrid(xs, ys, indexing="ij")
        self.t_top = Table(xs, ys, self.top_z(X, Y))
        self.t_gtop = Table(xs, ys, self.green_top(X, Y))
        Y, Z = np.meshgrid(ys, zs, indexing="ij")
        self.t_front = Table(ys, zs, self.front_x(Y, Z))
        self.t_rear = Table(ys, zs, self.rear_x(Y, Z))

    # -- implicit functions ---------------------------------------------------
    def lower(self, x, y, z):
        ay = np.abs(y)
        side = ay - self.t_side(x, z)
        top = z - self.t_top(x, ay)
        f = smax(side, top, k_shoulder(x))
        f = smax(f, x - self.t_front(ay, z), 0.060)
        f = smax(f, self.t_rear(ay, z) - x, 0.050)
        f = smax(f, under_z(x) - z, 0.045)
        return f

    def greenhouse(self, x, y, z):
        ay = np.abs(y)
        g = smax(z - self.t_gtop(x, ay), ay - self.t_gside(x, z), 0.085)
        # keep the greenhouse solid bounded (its lower part is buried in the body)
        return np.maximum(np.maximum(g, 0.70 - z), np.maximum(x - 1.30, -2.50 - x))

    def F(self, x, y, z):
        return smin(self.lower(x, y, z), self.greenhouse(x, y, z), 0.014)

    def grad(self, x, y, z, h=5e-4):
        gx = self.F(x + h, y, z) - self.F(x - h, y, z)
        gy = self.F(x, y + h, z) - self.F(x, y - h, z)
        gz = self.F(x, y, z + h) - self.F(x, y, z - h)
        g = np.stack([gx, gy, gz], -1)
        n = np.linalg.norm(g, axis=-1, keepdims=True)
        return g / np.maximum(n, 1e-12)
