#!/usr/bin/env python3
"""Build the BMW M5 (G90) model.

    python3 build.py [--quality draft|preview|final] [--out bmw_m5_g90.blend]
                     [--render OUTDIR] [--views 1,4,8] [--no-interior] [--no-wheels]

Requires Blender as a Python module (pip install bpy numpy scipy shapely pillow) or run
inside Blender:  blender -b -P build.py -- --quality final
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402

from m5g90 import util  # noqa: E402


def build_car(quality="draft", interior=True, wheels=True, stages=None):
    from m5g90 import body as B
    t0 = time.time()
    util.reset_scene()
    car = util.get_collection("M5_G90")
    c_body = util.get_collection("Body", car)
    c_glass = util.get_collection("Glass_Lights", car)
    c_detail = util.get_collection("Details", car)
    body, shell, feat = B.build_body(quality, collection=c_glass,
                                     stages=stages or B.ALL_STAGES)
    for c in shell.users_collection:
        c.objects.unlink(shell)
    c_body.objects.link(shell)
    if stages is None:
        from m5g90 import details
        details.build_details(body, shell, feat, c_detail, quality)
    if wheels:
        from m5g90 import wheels as W
        W.build_wheels(util.get_collection("Wheels", car))
    if interior:
        from m5g90 import interior as I
        I.build_interior(util.get_collection("Interior", car))
    print(f"[build] car ready in {time.time() - t0:.0f} s")
    return body, shell, feat


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--quality", default="draft", choices=["draft", "preview", "final"])
    ap.add_argument("--out", default=None, help="save a .blend here")
    ap.add_argument("--render", default=None, help="render the nine views into this folder")
    ap.add_argument("--render-quality", default=None)
    ap.add_argument("--views", default="1,2,3,4,5,6,7,8,9")
    ap.add_argument("--no-interior", action="store_true")
    ap.add_argument("--no-wheels", action="store_true")
    ap.add_argument("--stages", default=None)
    ap.add_argument("--glb", default=None, help="also export the car as glTF binary")
    ap.add_argument("--sheet", default=None, help="compose the rendered views into a contact sheet")
    if argv is None:
        argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    a = ap.parse_args(argv)
    build_car(a.quality, not a.no_interior, not a.no_wheels,
              a.stages.split(",") if a.stages else None)
    from m5g90 import scene as S
    S.build_studio()
    S.build_cameras()
    if a.out:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(a.out), compress=True)
        print("[build] saved", a.out)
    if a.render:
        os.makedirs(a.render, exist_ok=True)
        paths = S.render_all(a.render, quality=a.render_quality or a.quality,
                             views=[int(v) for v in a.views.split(",")])
        print("[build] rendered", paths)
        if a.sheet:
            S.contact_sheet(paths, a.sheet)
    if a.glb:
        for o in bpy.data.objects:
            o.select_set(any(c.name == "M5_G90" or c.name in
                             [k.name for k in bpy.data.collections["M5_G90"].children_recursive]
                             for c in o.users_collection))
        bpy.ops.export_scene.gltf(filepath=os.path.abspath(a.glb), use_selection=True,
                                  export_apply=True, export_format="GLB")
        print("[build] exported", a.glb)


if __name__ == "__main__":
    main()
