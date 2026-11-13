"""2D outline helpers: splined paths, shapely polygons, triangulation."""
import numpy as np
from scipy.interpolate import CubicSpline
from shapely.geometry import Polygon, LineString, box
from shapely import contains_xy
from mathutils.geometry import delaunay_2d_cdt


def spline_open(pts, step=0.004):
    """Smooth open curve through points (chord-length cubic spline)."""
    pts = np.asarray(pts, float)
    if len(pts) == 2:
        n = max(2, int(np.linalg.norm(pts[1] - pts[0]) / step) + 1)
        return np.linspace(pts[0], pts[1], n)
    d = np.r_[0, np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))]
    cs = CubicSpline(d, pts, bc_type="natural")
    n = max(2, int(d[-1] / step) + 1)
    return cs(np.linspace(0, d[-1], n))


def spline_closed(pts, step=0.004):
    pts = np.asarray(pts, float)
    pts = np.vstack([pts, pts[:1]])
    d = np.r_[0, np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))]
    cs = CubicSpline(d, pts, bc_type="periodic")
    n = max(8, int(d[-1] / step))
    return cs(np.linspace(0, d[-1], n, endpoint=False))


def path(segments, step=0.004):
    """Concatenate segments (each a list of points; >2 points = spline, 2 = straight).

    Consecutive segments share their end point, giving a sharp corner there.
    """
    out = []
    for seg in segments:
        c = spline_open(seg, step)
        out.append(c[:-1] if len(out) or True else c)
    out.append(np.asarray(segments[-1][-1], float)[None])
    return np.vstack(out)


def polygon(segments, step=0.004, round_r=0.0):
    """Closed polygon from path segments; optionally round all corners by round_r."""
    p = path(segments, step)
    if np.allclose(p[0], p[-1]):
        p = p[:-1]
    poly = Polygon(p)
    if not poly.is_valid:
        poly = poly.buffer(0)
    if round_r:
        poly = rounded(poly, round_r)
    return poly


def rounded(poly, r):
    return poly.buffer(-r, join_style=1, resolution=12).buffer(2 * r, join_style=1, resolution=12) \
        .buffer(-r, join_style=1, resolution=12)


def offset(poly, d):
    return poly.buffer(d, join_style=1, resolution=12)


def stroke(pts, width, closed=False, step=0.004, cap="flat"):
    """Band of given width along a polyline/spline (for grooves)."""
    pts = np.asarray(pts, float)
    ls = LineString(np.vstack([pts, pts[:1]]) if closed else pts)
    return ls.buffer(width / 2, cap_style=2 if cap == "flat" else 1, join_style=1, resolution=8)


def resample(coords, step):
    """Resample a closed ring so that no edge is longer than step."""
    c = np.asarray(coords, float)
    if np.allclose(c[0], c[-1]):
        c = c[:-1]
    out = []
    n = len(c)
    for i in range(n):
        a, b = c[i], c[(i + 1) % n]
        k = max(1, int(np.ceil(np.linalg.norm(b - a) / step)))
        out.append(a + (b - a) * np.linspace(0, 1, k, endpoint=False)[:, None])
    return np.vstack(out)


def simple_parts(poly):
    """Split a polygon (possibly with holes / multi) into simple hole-free polygons."""
    geoms = list(poly.geoms) if hasattr(poly, "geoms") else [poly]
    out = []
    for g in geoms:
        if g.is_empty:
            continue
        if not g.interiors:
            out.append(g)
            continue
        # cut through every hole with a vertical line -> pieces without holes
        xs = sorted(h.centroid.x for h in g.interiors)
        x0, y0, x1, y1 = g.bounds
        cuts = [x0 - 1] + xs + [x1 + 1]
        for a, b in zip(cuts[:-1], cuts[1:]):
            piece = g.intersection(box(a - 2e-4, y0 - 1, b + 2e-4, y1 + 1))
            out.extend(simple_parts(piece))
    return [g for g in out if g.area > 1e-10]


def triangulate(poly, edge=0.01, inner=None):
    """CDT of a simple polygon with a regular interior point grid.

    Returns (points[N,2], tris[M,3], n_boundary) - the first n_boundary points are
    the boundary ring in order.
    """
    ring = resample(poly.exterior.coords, edge)
    nb = len(ring)
    pts = [ring]
    g = inner or edge
    x0, y0, x1, y1 = poly.bounds
    gx = np.arange(x0 + g / 2, x1, g)
    gy = np.arange(y0 + g / 2, y1, g)
    if len(gx) and len(gy):
        GX, GY = np.meshgrid(gx, gy)
        cand = np.stack([GX.ravel(), GY.ravel()], -1)
        shr = poly.buffer(-0.45 * g)
        if not shr.is_empty:
            keep = contains_xy(shr, cand[:, 0], cand[:, 1])
            pts.append(cand[keep])
    allp = np.vstack(pts)
    edges = [(i, (i + 1) % nb) for i in range(nb)]
    v, e, f, ov, oe, of = delaunay_2d_cdt([tuple(p) for p in allp], edges,
                                          [list(range(nb))], 1, 1e-7, True)
    v = np.array([tuple(p) for p in v])
    tris = np.array([t for t in f if len(t) == 3], np.int64)
    return v, tris, ring
