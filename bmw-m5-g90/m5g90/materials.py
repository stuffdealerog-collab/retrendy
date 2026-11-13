"""Shared material library. Every getter is idempotent (returns the existing datablock)."""
import bpy


def _bsdf(mat):
    return mat.node_tree.nodes["Principled BSDF"]


def principled(name, color=(0.8, 0.8, 0.8), metallic=0.0, roughness=0.5, coat=0.0,
               coat_roughness=0.03, transmission=0.0, ior=1.5, emission=None,
               emission_strength=0.0, alpha=1.0, specular=0.5, sheen=0.0):
    """Get-or-create a simple Principled material."""
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    b = _bsdf(mat)
    b.inputs["Base Color"].default_value = (*color[:3], 1.0)
    b.inputs["Metallic"].default_value = metallic
    b.inputs["Roughness"].default_value = roughness
    b.inputs["IOR"].default_value = ior
    b.inputs["Coat Weight"].default_value = coat
    b.inputs["Coat Roughness"].default_value = coat_roughness
    b.inputs["Transmission Weight"].default_value = transmission
    b.inputs["Specular IOR Level"].default_value = specular
    b.inputs["Sheen Weight"].default_value = sheen
    b.inputs["Alpha"].default_value = alpha
    if emission is not None:
        b.inputs["Emission Color"].default_value = (*emission[:3], 1.0)
        b.inputs["Emission Strength"].default_value = emission_strength
    mat.diffuse_color = (*color[:3], 1.0)
    mat.metallic = metallic
    mat.roughness = roughness
    return mat


# ---- exterior ---------------------------------------------------------------
def car_paint():
    """Isle of Man Green metallic: flake layer under a clear coat."""
    name = "Paint_IsleOfManGreen"
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = principled(name, color=(0.004, 0.115, 0.062), metallic=0.85, roughness=0.45,
                     coat=1.0, coat_roughness=0.025)
    nt = mat.node_tree
    b = _bsdf(mat)
    # view-angle colour travel: brighter emerald face-on, deep blue-green at grazing angles
    lw = nt.nodes.new("ShaderNodeLayerWeight")
    lw.inputs["Blend"].default_value = 0.35
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = (0.008, 0.25, 0.12, 1)
    ramp.color_ramp.elements[1].position = 1.0
    ramp.color_ramp.elements[1].color = (0.002, 0.05, 0.04, 1)
    nt.links.new(lw.outputs["Facing"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    # metallic flakes: tiny normal perturbation of the base layer only
    tex = nt.nodes.new("ShaderNodeTexVoronoi")
    tex.inputs["Scale"].default_value = 9000.0
    tc = nt.nodes.new("ShaderNodeTexCoord")
    nt.links.new(tc.outputs["Object"], tex.inputs["Vector"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.06
    bump.inputs["Distance"].default_value = 0.0002
    nt.links.new(tex.outputs["Color"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    return mat


def gloss_black():
    return principled("Gloss_Black", color=(0.004, 0.004, 0.005), roughness=0.08, coat=1.0)


def satin_black():
    return principled("Satin_Black_Plastic", color=(0.012, 0.012, 0.013), roughness=0.45)


def matte_black():
    return principled("Matte_Black", color=(0.006, 0.006, 0.006), roughness=0.85)


def rubber():
    return principled("Rubber_Tyre", color=(0.012, 0.012, 0.012), roughness=0.78, specular=0.3)


def chrome():
    return principled("Chrome", color=(0.9, 0.9, 0.9), metallic=1.0, roughness=0.06)


def dark_chrome():
    return principled("Dark_Chrome", color=(0.08, 0.08, 0.085), metallic=1.0, roughness=0.12)


def aluminium():
    return principled("Aluminium_Machined", color=(0.78, 0.78, 0.80), metallic=1.0, roughness=0.22)


GLASS_TINT = {"screen": 0.60, "front": 0.30, "rear": 0.20, "roof": 0.50}


def window_glass(kind="rear"):
    """Tinted glazing; the tint is applied at both faces of the pane."""
    t = GLASS_TINT[kind]
    return principled(f"Glass_{kind.capitalize()}", color=(t * 0.93, t, t * 0.97), roughness=0.0,
                      transmission=1.0, ior=1.52)


def clear_glass():
    return principled("Glass_Clear", color=(1, 1, 1), roughness=0.0, transmission=1.0, ior=1.5)


def red_lens():
    return principled("Lens_Red", color=(0.62, 0.035, 0.03), roughness=0.02, transmission=1.0,
                      ior=1.49)


def emit_white(strength=7.0):
    return principled("Emit_DRL_White", color=(1, 1, 1), emission=(0.92, 0.96, 1.0),
                      emission_strength=strength)


def emit_red(strength=10.0):
    return principled("Emit_Tail_Red", color=(1, 0.02, 0.01), emission=(1.0, 0.03, 0.012),
                      emission_strength=strength)


def caliper_gold():
    return principled("Caliper_Gold", color=(0.52, 0.38, 0.13), metallic=0.7, roughness=0.35,
                      coat=0.6)


def brake_disc():
    return principled("Brake_Disc_Ceramic", color=(0.17, 0.17, 0.17), metallic=0.6, roughness=0.5)


def carbon():
    """Gloss carbon fibre (procedural 2x2 twill look)."""
    name = "Carbon_Fibre"
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = principled(name, color=(0.012, 0.012, 0.013), roughness=0.3, coat=1.0, metallic=0.3)
    nt = mat.node_tree
    b = _bsdf(mat)
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (260.0, 260.0, 260.0)
    mp.inputs["Rotation"].default_value = (0.0, 0.0, 0.785)
    wave = nt.nodes.new("ShaderNodeTexWave")
    wave.wave_type = "BANDS"
    wave.bands_direction = "DIAGONAL"
    wave.inputs["Scale"].default_value = 1.0
    wave.inputs["Distortion"].default_value = 0.0
    chk = nt.nodes.new("ShaderNodeTexChecker")
    chk.inputs["Scale"].default_value = 1.0
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = "MULTIPLY"
    mix.inputs["Factor"].default_value = 0.6
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.004, 0.004, 0.004, 1)
    ramp.color_ramp.elements[1].color = (0.05, 0.05, 0.055, 1)
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    nt.links.new(mp.outputs["Vector"], wave.inputs["Vector"])
    nt.links.new(mp.outputs["Vector"], chk.inputs["Vector"])
    nt.links.new(wave.outputs["Color"], mix.inputs["A"])
    nt.links.new(chk.outputs["Color"], mix.inputs["B"])
    nt.links.new(mix.outputs["Result"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    return mat


# ---- interior ---------------------------------------------------------------
def leather_orange():
    return principled("Leather_KyalamiOrange", color=(0.50, 0.14, 0.03), roughness=0.55, sheen=0.2)


def leather_black():
    return principled("Leather_Black", color=(0.012, 0.012, 0.013), roughness=0.55, sheen=0.2)


def interior_plastic():
    return principled("Interior_Plastic", color=(0.015, 0.015, 0.016), roughness=0.6)


def carpet():
    return principled("Interior_Carpet", color=(0.01, 0.01, 0.01), roughness=0.95, sheen=0.5)


def screen():
    return principled("Display_Screen", color=(0.0, 0.0, 0.0), roughness=0.05, coat=1.0,
                      emission=(0.08, 0.16, 0.35), emission_strength=0.6)
