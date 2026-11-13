"""Turn an implicit solid F(x, y, z) <= 0 into a clean, dense quad mesh.

A box-shaped lattice is wrapped around the solid; every lattice vertex is shot
along a ray from an inner "spine" segment and snapped onto F = 0 by bisection.
The result is an all-quad, watertight grid (only 8 irregular vertices) that
lies exactly on the analytic surface, with analytic normals available from the
gradient of F.
"""
import numpy as np


def box_lattice(xs, ys, zs, open_ymin=False):
    """Surface of the lattice xs*ys*zs. Returns (points[N,3], quads[M,4]).

    With open_ymin the face at ys[0] is left out (symmetry plane).
    Quads are wound so that normals point out of the box.
    """
    nx, ny, nz = len(xs), len(ys), len(zs)
    idx = -np.ones((nx, ny, nz), np.int64)
    on = np.zeros((nx, ny, nz), bool)
    on[0], on[-1] = True, True
    on[:, -1] = True
    if not open_ymin:
        on[:, 0] = True
    on[:, :, 0], on[:, :, -1] = True, True
    idx[on] = np.arange(on.sum())
    I, J, K = np.nonzero(on)
    pts = np.stack([xs[I], ys[J], zs[K]], -1)

    def face(a, b, c, d, flip):
        q = np.stack([a.ravel(), b.ravel(), c.ravel(), d.ravel()], -1)
        return q[:, ::-1] if flip else q

    quads = []
    # x faces (normal -x at i=0, +x at i=nx-1)
    for i, flip in ((0, True), (nx - 1, False)):
        g = idx[i]
        quads.append(face(g[:-1, :-1], g[1:, :-1], g[1:, 1:], g[:-1, 1:], flip))
    # y faces
    for j, flip in ((0, False), (ny - 1, True)):
        if j == 0 and open_ymin:
            continue
        g = idx[:, j]
        quads.append(face(g[:-1, :-1], g[1:, :-1], g[1:, 1:], g[:-1, 1:], flip))
    # z faces
    for k, flip in ((0, True), (nz - 1, False)):
        g = idx[:, :, k]
        quads.append(face(g[:-1, :-1], g[1:, :-1], g[1:, 1:], g[:-1, 1:], flip))
    return pts, np.concatenate(quads)


def project(F, pts, spine_x, spine_z, tmax=4.0, n_coarse=96, n_bisect=26, chunk=400_000):
    """Snap lattice points onto F=0 along rays from the spine segment (y = 0)."""
    out = np.empty_like(pts)
    for s in range(0, len(pts), chunk):
        p = pts[s:s + chunk]
        o = np.stack([np.clip(p[:, 0], spine_x[0], spine_x[1]),
                      np.zeros(len(p)), np.full(len(p), spine_z)], -1)
        d = p - o
        d /= np.linalg.norm(d, axis=1, keepdims=True)
        ts = np.linspace(0.0, tmax, n_coarse)
        last_in = np.zeros(len(p), np.int64)
        for i, t in enumerate(ts):
            q = o + d * t
            inside = F(q[:, 0], q[:, 1], q[:, 2]) < 0
            last_in[inside] = i
        lo = ts[last_in]
        hi = ts[np.minimum(last_in + 1, n_coarse - 1)]
        for _ in range(n_bisect):
            mid = 0.5 * (lo + hi)
            q = o + d * mid[:, None]
            inside = F(q[:, 0], q[:, 1], q[:, 2]) < 0
            lo = np.where(inside, mid, lo)
            hi = np.where(inside, hi, mid)
        out[s:s + chunk] = o + d * (0.5 * (lo + hi))[:, None]
    return out


def spaced(a, b, h):
    n = max(2, int(round((b - a) / h)) + 1)
    return np.linspace(a, b, n)


def mesh_half(F, bounds, h, spine_x, spine_z, h_bottom=None):
    """Half solid (y >= 0), open at the symmetry plane. Returns verts, quads."""
    (x0, x1), (y1,), (z0, z1) = bounds
    xs, ys, zs = spaced(x0, x1, h), spaced(0.0, y1, h), spaced(z0, z1, h)
    pts, quads = box_lattice(xs, ys, zs, open_ymin=True)
    verts = project(F, pts, spine_x, spine_z)
    verts[np.abs(pts[:, 1]) < 1e-9, 1] = 0.0
    return verts, quads


def mirror_full(verts, quads, tol=1e-7):
    """Mirror a y>=0 half mesh into a closed full mesh (welding the seam)."""
    on_seam = np.abs(verts[:, 1]) < tol
    n = len(verts)
    remap = np.where(on_seam, np.arange(n), np.arange(n) + n)
    # compact the mirrored index range
    mirrored_ids = np.nonzero(~on_seam)[0]
    new_index = np.arange(n)
    new_index[mirrored_ids] = n + np.arange(len(mirrored_ids))
    mv = verts[mirrored_ids] * np.array([1, -1, 1.0])
    all_verts = np.concatenate([verts, mv])
    mq = new_index[quads][:, ::-1]
    return all_verts, np.concatenate([quads, mq])


def relax(F, V, Q, iters=12, lam=0.6, newton=2, h=4e-4, chunk=600_000, log=None):
    """Even out the vertex distribution: tangential Laplacian smoothing with
    re-projection onto F = 0 (Newton steps along the gradient).

    Removes the stretched / mis-snapped quads the ray projection leaves on
    undercuts and ledges, while every vertex stays exactly on the surface.
    """
    from scipy import sparse
    n = len(V)
    e = np.concatenate([Q[:, [0, 1]], Q[:, [1, 2]], Q[:, [2, 3]], Q[:, [3, 0]]])
    e = np.concatenate([e, e[:, ::-1]])
    A = sparse.csr_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(n, n))
    A.data[:] = 1.0
    deg = np.asarray(A.sum(1)).ravel()
    A = sparse.diags(1.0 / np.maximum(deg, 1)) @ A
    V = V.copy()

    def project(P):
        for _ in range(newton):
            for s in range(0, len(P), chunk):
                p = P[s:s + chunk]
                x, y, z = p[:, 0], p[:, 1], p[:, 2]
                f = F(x, y, z)
                g = np.stack([F(x + h, y, z) - F(x - h, y, z), F(x, y + h, z) - F(x, y - h, z),
                              F(x, y, z + h) - F(x, y, z - h)], -1) / (2 * h)
                g2 = np.maximum((g * g).sum(1), 1e-9)
                step = (f / g2)[:, None] * g
                # trust region: never jump more than 3 cm in one go
                ln = np.linalg.norm(step, axis=1, keepdims=True)
                step *= np.minimum(1.0, 0.03 / np.maximum(ln, 1e-12))
                P[s:s + chunk] = p - step
        return P

    for it in range(iters):
        V = V + lam * (A @ V - V)
        V = project(V)
    # final exact snap
    V = project(project(V))
    return V
