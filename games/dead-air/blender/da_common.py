"""STRELKA — shared helpers for the Blender (bpy) pipeline.

Everything is procedural: no external assets. Run with the `bpy` Python module
(pip install bpy) or inside Blender: `blender -b -P build_characters.py`.
"""
import math
import os

import bpy
import numpy as np
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "assets"))
TEX = os.path.join(OUT, "textures")


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def srgb_to_lin(c):
    return tuple(((x / 12.92) if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4) for x in c)


def lin(h):
    """hex sRGB -> linear RGBA tuple for shader inputs."""
    return (*srgb_to_lin(hex_rgb(h)), 1.0)


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for blk in (bpy.data.meshes, bpy.data.materials, bpy.data.images, bpy.data.actions):
        for item in list(blk):
            blk.remove(item)


def save_png(arr, path):
    """arr: HxWx3 or HxWx4 uint8, row 0 = top."""
    from PIL import Image
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.fromarray(arr).save(path)
    return path


def load_image(path, colorspace="sRGB"):
    img = bpy.data.images.load(path, check_existing=True)
    img.colorspace_settings.name = colorspace
    return img


# --------------------------------------------------------------------------
# Fog: one shared node group so the whole world (and the sky) fades to the
# same animated colour. PS1-style distance fog, done in the shader.
# --------------------------------------------------------------------------
FOG_GROUP = "DA_Fog"
FOGCOL_GROUP = "DA_FogColor"
PULSE_GROUP = "DA_Pulse"


def _value_group(name, kind="VALUE", default=0.0):
    """A node group that only outputs one animatable value / colour."""
    if name in bpy.data.node_groups:
        return bpy.data.node_groups[name]
    g = bpy.data.node_groups.new(name, "ShaderNodeTree")
    out = g.nodes.new("NodeGroupOutput")
    if kind == "VALUE":
        g.interface.new_socket("Value", in_out="OUTPUT", socket_type="NodeSocketFloat")
        n = g.nodes.new("ShaderNodeValue")
        n.name = "src"
        n.outputs[0].default_value = default
    else:
        g.interface.new_socket("Color", in_out="OUTPUT", socket_type="NodeSocketColor")
        n = g.nodes.new("ShaderNodeRGB")
        n.name = "src"
        n.outputs[0].default_value = default
    g.links.new(n.outputs[0], out.inputs[0])
    return g


def fog_color_group():
    return _value_group(FOGCOL_GROUP, "RGB", lin("#241c33"))


def pulse_group():
    """0..1 value keyed on every beat: the city breathes with the track."""
    return _value_group(PULSE_GROUP, "VALUE", 0.0)


def density_group():
    return _value_group("DA_FogDensity", "VALUE", 0.022)


def fog_group():
    if FOG_GROUP in bpy.data.node_groups:
        return bpy.data.node_groups[FOG_GROUP]
    g = bpy.data.node_groups.new(FOG_GROUP, "ShaderNodeTree")
    g.interface.new_socket("Shader", in_out="INPUT", socket_type="NodeSocketShader")
    g.interface.new_socket("Amount", in_out="INPUT", socket_type="NodeSocketFloat").default_value = 1.0
    g.interface.new_socket("Shader", in_out="OUTPUT", socket_type="NodeSocketShader")
    N, L = g.nodes, g.links
    gi, go = N.new("NodeGroupInput"), N.new("NodeGroupOutput")
    cam = N.new("ShaderNodeCameraData")
    geo = N.new("ShaderNodeNewGeometry")
    sep = N.new("ShaderNodeSeparateXYZ")
    L.new(geo.outputs["Position"], sep.inputs[0])
    dens = N.new("ShaderNodeGroup"); dens.node_tree = density_group()
    # height falloff: thick at street level, thin above the roofs
    hmap = N.new("ShaderNodeMapRange")
    hmap.inputs["From Min"].default_value = 0.0
    hmap.inputs["From Max"].default_value = 40.0
    hmap.inputs["To Min"].default_value = 1.0
    hmap.inputs["To Max"].default_value = 0.45
    L.new(sep.outputs["Z"], hmap.inputs["Value"])
    m1 = N.new("ShaderNodeMath"); m1.operation = "MULTIPLY"
    L.new(cam.outputs["View Distance"], m1.inputs[0]); L.new(dens.outputs[0], m1.inputs[1])
    m2 = N.new("ShaderNodeMath"); m2.operation = "MULTIPLY"
    L.new(m1.outputs[0], m2.inputs[0]); L.new(hmap.outputs[0], m2.inputs[1])
    p = N.new("ShaderNodeMath"); p.operation = "POWER"; p.inputs[1].default_value = 1.35
    L.new(m2.outputs[0], p.inputs[0])
    neg = N.new("ShaderNodeMath"); neg.operation = "MULTIPLY"; neg.inputs[1].default_value = -1.0
    L.new(p.outputs[0], neg.inputs[0])
    ex = N.new("ShaderNodeMath"); ex.operation = "EXPONENT"
    L.new(neg.outputs[0], ex.inputs[0])
    inv = N.new("ShaderNodeMath"); inv.operation = "SUBTRACT"; inv.inputs[0].default_value = 1.0
    L.new(ex.outputs[0], inv.inputs[1])
    amt = N.new("ShaderNodeMath"); amt.operation = "MULTIPLY"; amt.use_clamp = True
    L.new(inv.outputs[0], amt.inputs[0]); L.new(gi.outputs["Amount"], amt.inputs[1])
    col = N.new("ShaderNodeGroup"); col.node_tree = fog_color_group()
    em = N.new("ShaderNodeEmission")
    L.new(col.outputs[0], em.inputs["Color"])
    mix = N.new("ShaderNodeMixShader")
    L.new(amt.outputs[0], mix.inputs[0])
    L.new(gi.outputs["Shader"], mix.inputs[1])
    L.new(em.outputs[0], mix.inputs[2])
    L.new(mix.outputs[0], go.inputs[0])
    return g


def _finish(mat, shader_socket, fog=1.0):
    N, L = mat.node_tree.nodes, mat.node_tree.links
    out = N.get("Material Output") or N.new("ShaderNodeOutputMaterial")
    if fog > 0:
        f = N.new("ShaderNodeGroup"); f.node_tree = fog_group()
        f.inputs["Amount"].default_value = fog
        L.new(shader_socket, f.inputs["Shader"])
        L.new(f.outputs[0], out.inputs["Surface"])
    else:
        L.new(shader_socket, out.inputs["Surface"])
    if hasattr(mat, "cycles"):
        mat.cycles.emission_sampling = "NONE"
    return mat


def new_mat(name):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.node_tree.nodes.clear()
    return mat


def flat_mat(name, color, rough=0.9, emit=None, emit_strength=0.0, fog=1.0, pulse=0.0, spec=0.0):
    """Diffuse (+optional glossy / emission) material with shader fog."""
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    mat = new_mat(name)
    N, L = mat.node_tree.nodes, mat.node_tree.links
    bsdf = N.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = lin(color) if isinstance(color, str) else color
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Specular IOR Level"].default_value = spec
    if emit:
        bsdf.inputs["Emission Color"].default_value = lin(emit) if isinstance(emit, str) else emit
        if pulse:
            pg = N.new("ShaderNodeGroup"); pg.node_tree = pulse_group()
            m = N.new("ShaderNodeMath"); m.operation = "MULTIPLY_ADD"
            m.inputs[1].default_value = emit_strength * pulse
            m.inputs[2].default_value = emit_strength
            L.new(pg.outputs[0], m.inputs[0])
            L.new(m.outputs[0], bsdf.inputs["Emission Strength"])
        else:
            bsdf.inputs["Emission Strength"].default_value = emit_strength
    mat.diffuse_color = lin(color) if isinstance(color, str) else color
    return _finish(mat, bsdf.outputs[0], fog)


def tex_mat(name, base_img, emit_img=None, emit_strength=1.0, rough=0.9, fog=1.0, pulse=0.0,
            alpha=False, uv_scale=None):
    """Pixel-art textured material (Closest filtering), optional emission map."""
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    mat = new_mat(name)
    N, L = mat.node_tree.nodes, mat.node_tree.links
    bsdf = N.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Specular IOR Level"].default_value = 0.0
    t = N.new("ShaderNodeTexImage"); t.image = base_img; t.interpolation = "Closest"
    t.name = "BaseTex"
    L.new(t.outputs["Color"], bsdf.inputs["Base Color"])
    if alpha:
        L.new(t.outputs["Alpha"], bsdf.inputs["Alpha"])
    if emit_img is not None:
        e = N.new("ShaderNodeTexImage"); e.image = emit_img; e.interpolation = "Closest"
        e.name = "EmitTex"
        L.new(e.outputs["Color"], bsdf.inputs["Emission Color"])
        if pulse:
            pg = N.new("ShaderNodeGroup"); pg.node_tree = pulse_group()
            m = N.new("ShaderNodeMath"); m.operation = "MULTIPLY_ADD"
            m.inputs[1].default_value = emit_strength * pulse
            m.inputs[2].default_value = emit_strength
            L.new(pg.outputs[0], m.inputs[0])
            L.new(m.outputs[0], bsdf.inputs["Emission Strength"])
        else:
            bsdf.inputs["Emission Strength"].default_value = emit_strength
    return _finish(mat, bsdf.outputs[0], fog)


def glow_mat(name, color, strength=1.0, alpha=1.0, pulse=0.0, obj_alpha=False, fresnel=False,
             gradient_z=None):
    """Unlit emissive material. alpha<1 -> additive-ish transparency (light cones, ghosts)."""
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    mat = new_mat(name)
    N, L = mat.node_tree.nodes, mat.node_tree.links
    em = N.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = lin(color) if isinstance(color, str) else color
    strength_sock = None
    if pulse:
        pg = N.new("ShaderNodeGroup"); pg.node_tree = pulse_group()
        m = N.new("ShaderNodeMath"); m.operation = "MULTIPLY_ADD"
        m.inputs[1].default_value = strength * pulse
        m.inputs[2].default_value = strength
        L.new(pg.outputs[0], m.inputs[0])
        strength_sock = m.outputs[0]
    fac = None
    if obj_alpha:
        oi = N.new("ShaderNodeObjectInfo")
        fac = oi.outputs["Alpha"]
    if fresnel:
        lw = N.new("ShaderNodeLayerWeight"); lw.inputs["Blend"].default_value = 0.35
        inv = N.new("ShaderNodeMath"); inv.operation = "SUBTRACT"; inv.inputs[0].default_value = 1.0
        L.new(lw.outputs["Facing"], inv.inputs[1])
        pw = N.new("ShaderNodeMath"); pw.operation = "POWER"; pw.inputs[1].default_value = 1.6
        L.new(inv.outputs[0], pw.inputs[0])
        fac = _mul(N, L, fac, pw.outputs[0])
    if gradient_z is not None:
        # fade along object-space Z between (z0 -> 0, z1 -> 1)
        tc = N.new("ShaderNodeTexCoord")
        sep = N.new("ShaderNodeSeparateXYZ")
        L.new(tc.outputs["Object"], sep.inputs[0])
        mr = N.new("ShaderNodeMapRange")
        mr.inputs["From Min"].default_value = gradient_z[0]
        mr.inputs["From Max"].default_value = gradient_z[1]
        L.new(sep.outputs["Z"], mr.inputs["Value"])
        fac = _mul(N, L, fac, mr.outputs[0])
    if strength_sock is not None:
        L.new(strength_sock, em.inputs["Strength"])
    else:
        em.inputs["Strength"].default_value = strength
    out = N.new("ShaderNodeOutputMaterial")
    if alpha < 1.0 or fac is not None:
        tr = N.new("ShaderNodeBsdfTransparent")
        mix = N.new("ShaderNodeMixShader")
        if fac is not None:
            a = N.new("ShaderNodeMath"); a.operation = "MULTIPLY"; a.inputs[1].default_value = alpha
            a.use_clamp = True
            L.new(fac, a.inputs[0])
            L.new(a.outputs[0], mix.inputs[0])
        else:
            mix.inputs[0].default_value = alpha
        L.new(tr.outputs[0], mix.inputs[1])
        L.new(em.outputs[0], mix.inputs[2])
        L.new(mix.outputs[0], out.inputs["Surface"])
    else:
        L.new(em.outputs[0], out.inputs["Surface"])
    if hasattr(mat, "cycles"):
        mat.cycles.emission_sampling = "NONE"
    return mat


def _mul(N, L, a, b):
    if a is None:
        return b
    m = N.new("ShaderNodeMath"); m.operation = "MULTIPLY"
    L.new(a, m.inputs[0]); L.new(b, m.inputs[1])
    return m.outputs[0]


# --------------------------------------------------------------------------
# Low-poly mesh builder
# --------------------------------------------------------------------------
class MeshBuilder:
    """Collects quads with per-face material slots and UVs; emits one mesh."""

    def __init__(self):
        self.verts, self.faces, self.uvs, self.mats = [], [], [], []
        self.mat_names = []

    def _slot(self, mat):
        if mat.name not in self.mat_names:
            self.mat_names.append(mat.name)
        return self.mat_names.index(mat.name)

    def quad(self, pts, mat, uv=None):
        i = len(self.verts)
        self.verts.extend([tuple(p) for p in pts])
        self.faces.append(tuple(range(i, i + len(pts))))
        self.uvs.append(uv or [(0, 0), (1, 0), (1, 1), (0, 1)][:len(pts)])
        self.mats.append(self._slot(mat))

    def box(self, lo, hi, mat, top_scale=(1, 1), mats=None, uv_fn=None, skip=()):
        """Axis-aligned box lo..hi. top_scale tapers the +Z face. mats: optional per-side
        override {'x-','x+','y-','y+','z-','z+'}. uv_fn(side, pts)->uvs."""
        x0, y0, z0 = lo; x1, y1, z1 = hi
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        sx, sy = top_scale
        tx0, tx1 = cx + (x0 - cx) * sx, cx + (x1 - cx) * sx
        ty0, ty1 = cy + (y0 - cy) * sy, cy + (y1 - cy) * sy
        b = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0)]
        t = [(tx0, ty0, z1), (tx1, ty0, z1), (tx1, ty1, z1), (tx0, ty1, z1)]
        sides = {
            "y-": [b[0], b[1], t[1], t[0]],
            "x+": [b[1], b[2], t[2], t[1]],
            "y+": [b[2], b[3], t[3], t[2]],
            "x-": [b[3], b[0], t[0], t[3]],
            "z+": [t[0], t[1], t[2], t[3]],
            "z-": [b[3], b[2], b[1], b[0]],
        }
        for side, pts in sides.items():
            if side in skip:
                continue
            m = (mats or {}).get(side, mat)
            self.quad(pts, m, uv_fn(side, pts) if uv_fn else None)

    def build(self, name, collection=None, smooth=False):
        me = bpy.data.meshes.new(name)
        me.from_pydata(self.verts, [], self.faces)
        for mn in self.mat_names:
            me.materials.append(bpy.data.materials[mn])
        uvl = me.uv_layers.new(name="UVMap")
        k = 0
        for poly, fuv, mi in zip(me.polygons, self.uvs, self.mats):
            poly.material_index = mi
            poly.use_smooth = smooth
            for j in range(poly.loop_total):
                uvl.data[k].uv = fuv[j]
                k += 1
        me.update()
        ob = bpy.data.objects.new(name, me)
        (collection or bpy.context.scene.collection).objects.link(ob)
        return ob


def world_uv(scale_u, scale_v, off_u=0.0, off_v=0.0):
    """UVs from world coordinates: u along the horizontal run of the face, v along Z."""
    def fn(side, pts):
        out = []
        for (x, y, z) in pts:
            if side == "y-":
                u = x
            elif side == "y+":
                u = -x
            elif side == "x+":
                u = y
            elif side == "x-":
                u = -y
            else:
                u, z = x, y
            out.append((u / scale_u + off_u, z / scale_v + off_v))
        return out
    return fn


def rot_z(deg):
    return Matrix.Rotation(math.radians(deg), 4, "Z")


def set_interp(obj, interp="LINEAR", path_contains=None):
    """Set interpolation on every keyframe of an object's action (5.x slotted actions)."""
    ad = obj.animation_data
    if not ad or not ad.action:
        return
    for fc in iter_fcurves(ad.action):
        if path_contains and path_contains not in fc.data_path:
            continue
        for kp in fc.keyframe_points:
            kp.interpolation = interp


def iter_fcurves(action):
    if hasattr(action, "layers") and len(action.layers):
        for layer in action.layers:
            for strip in layer.strips:
                for cb in strip.channelbags:
                    for fc in cb.fcurves:
                        yield fc
    elif hasattr(action, "fcurves"):
        for fc in action.fcurves:
            yield fc
