"""STRELKA — builds the four R6 avatars + the animation library and exports them.

    python3 build_characters.py

Outputs (../assets):
  strelka_characters.blend        4 rigged avatars, 24 actions (SK_*), textures packed
  fbx/<NAME>.fbx                  one file per avatar, all actions baked as takes
  textures/<NAME>_atlas.png       256x256 colour atlas (+ _emit.png)
  preview/cast.png, clips.png     lineup render and a pose sheet

Clips are authored in beats. AUTHOR_BPM = 150 at 30 fps -> 12 frames per beat.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy
from mathutils import Vector

import da_characters as CH
import da_clips as K
import da_common as C

FPS, AUTHOR_BPM = 30, 150
FPB = FPS * 60 / AUTHOR_BPM          # 12 frames per beat


def lights_and_camera(sc, cam_loc, cam_tgt, lens=55):
    cam = bpy.data.objects.new("PreviewCam", bpy.data.cameras.new("PreviewCam"))
    sc.collection.objects.link(cam)
    cam.location = cam_loc
    cam.rotation_euler = (Vector(cam_tgt) - Vector(cam_loc)).to_track_quat("-Z", "Y").to_euler()
    cam.data.lens = lens
    sc.camera = cam

    def area(loc, tgt, e, col, size):
        ld = bpy.data.lights.new("PreviewLight", "AREA")
        ld.energy, ld.size, ld.color = e, size, col
        ob = bpy.data.objects.new("PreviewLight", ld)
        ob.location = loc
        ob.rotation_euler = (Vector(tgt) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        sc.collection.objects.link(ob)

    area((2.5, -4, 3.5), (0, 0, 1), 520, (1, 0.94, 0.9), 2.5)
    area((-4, 2.5, 2.5), (0, 0, 1), 800, (1, 0.5, 0.2), 1.5)
    area((4, 3, 2.5), (0, 0, 1), 620, (1.0, 0.37, 0.82), 1.5)
    w = bpy.data.worlds.new("PreviewWorld")
    sc.world = w
    w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (0.012, 0.011, 0.018, 1)
    mb = C.MeshBuilder()
    mb.quad([(-12, -12, 0), (12, -12, 0), (12, 12, 0), (-12, 12, 0)], C.flat_mat("PreviewFloor", "#17151c", fog=0))
    mb.build("PreviewFloor")
    sc.render.engine = "CYCLES"
    sc.cycles.samples = 48
    sc.cycles.use_denoising = True
    sc.view_settings.view_transform = "AgX"
    return cam


def main():
    C.reset_scene()
    sc = bpy.context.scene
    sc.render.fps = FPS
    names = list(CH.CAST)
    arms = {}
    for i, n in enumerate(names):
        arm, objs = CH.build_character(n)
        arm.location = ((i - 1.5) * 1.25, 0, 0)
        arms[n] = (arm, objs)
    first = arms[names[0]][0]
    actions = [K.bake_action(first, clip, FPB) for clip in K.CLIPS]
    idle = bpy.data.actions["SK_Idle"]
    for n, (arm, _) in arms.items():
        arm.animation_data_create()
        arm.animation_data.action = idle
    sc.frame_start, sc.frame_end = 1, int(1 + 4 * FPB)
    os.makedirs(os.path.join(C.OUT, "fbx"), exist_ok=True)
    os.makedirs(os.path.join(C.OUT, "preview"), exist_ok=True)

    # ---- FBX per avatar (rig + meshes + every action as a take)
    for n, (arm, objs) in arms.items():
        keep = arm.location.copy()
        arm.location = (0, 0, 0)
        bpy.ops.object.select_all(action="DESELECT")
        arm.select_set(True)
        for o in objs:
            o.select_set(True)
        bpy.context.view_layer.objects.active = arm
        bpy.ops.export_scene.fbx(
            filepath=os.path.join(C.OUT, "fbx", f"{n}.fbx"), use_selection=True,
            object_types={"ARMATURE", "MESH"}, add_leaf_bones=False, bake_anim=True,
            bake_anim_use_all_actions=True, bake_anim_use_nla_strips=False, bake_anim_use_all_bones=True,
            bake_anim_simplify_factor=0.0, bake_anim_force_startend_keying=True,
            path_mode="COPY", embed_textures=True, mesh_smooth_type="FACE",
            axis_forward="-Z", axis_up="Y", apply_scale_options="FBX_SCALE_ALL")
        arm.location = keep

    # ---- previews
    lights_and_camera(sc, (0, -6.6, 1.0), (0, 0, 0.86), 58)
    sc.render.resolution_x, sc.render.resolution_y = 1600, 800
    for i, (n, (arm, _)) in enumerate(arms.items()):
        arm.rotation_euler = (0, 0, math.radians((18, 8, -8, -18)[i]))
    sc.frame_set(1)
    sc.render.filepath = os.path.join(C.OUT, "preview", "cast.png")
    bpy.ops.render.render(write_still=True)
    for n, (arm, _) in arms.items():
        arm.rotation_euler = (0, 0, 0)

    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(C.OUT, "strelka_characters.blend"), compress=True)
    print("actions:", len(actions), "| fbx:", sorted(os.listdir(os.path.join(C.OUT, "fbx"))))


if __name__ == "__main__":
    main()
