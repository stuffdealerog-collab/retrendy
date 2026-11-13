"""Body shell of the M5 G90: master surface -> openings, panel gaps, glazing."""
import time

import numpy as np
import bpy
from shapely.geometry import Point

from . import util, cut, surf, materials as M, params as P, geom2d as G

H = {"draft": 0.020, "preview": 0.011, "final": 0.0065}


def log(msg, t0=[time.time()]):
    print(f"[body {time.time() - t0[0]:6.1f}s] {msg}", flush=True)


def wheel_wells(body):
    """Cylindrical wheel-well cutters (both sides)."""
    liner = M.matte_black()
    out = []
    for xw, zw, ra in ((surf.AXF, surf.ZWF, surf.ARCH_R_F), (surf.AXR, surf.ZWR, surf.ARCH_R_R)):
        circle = Point(xw, zw).buffer(ra, resolution=48)
        for s in (1, -1):
            out.append(cut.prism("WellCut", circle, "side", s * 0.52, s * 1.30, mat=liner))
    return out


ALL_STAGES = ("wells", "cavity", "side_glass", "top_glass", "gaps", "front", "rear", "trim")


def build_body(quality="draft", collection=None, stages=ALL_STAGES):
    from . import features
    body = surf.Body()
    h = H[quality]
    log(f"tables ready, meshing master at {h * 1000:.1f} mm")
    shell = cut.build_master(body, h, name="Body", relax=14)
    shell.data.materials.append(M.car_paint())
    log(f"master: {len(shell.data.polygons)} quads")
    if "wells" in stages:
        cut.boolean(shell, wheel_wells(body))
        log(f"wheel wells cut: {len(shell.data.polygons)} faces")
    edge = {"draft": 0.012, "preview": 0.008, "final": 0.005}[quality]
    feat = features.Features(body, shell, collection, edge=edge, log=log)
    feat.run([s for s in stages if s != "wells"])
    cut.restore_normals(shell, body)
    log(f"normals restored, {len(shell.data.polygons)} faces")
    if collection is not None:
        for c in shell.users_collection:
            c.objects.unlink(shell)
        collection.objects.link(shell)
    return body, shell, feat
