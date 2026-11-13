"""Key dimensions of the BMW M5 saloon (G90), in metres.

Axes: +X forward, +Y car-left, +Z up. Origin on the ground, mid-wheelbase.
"""

# ---- overall -------------------------------------------------------------
LENGTH = 5.096
WIDTH = 1.970          # across the wheel-arch flares, mirrors excluded
HEIGHT = 1.510
WHEELBASE = 3.006
OVERHANG_F = 0.905
OVERHANG_R = LENGTH - WHEELBASE - OVERHANG_F   # 1.185

AXLE_F_X = WHEELBASE / 2      # +1.503
AXLE_R_X = -WHEELBASE / 2     # -1.503
X_FRONT = AXLE_F_X + OVERHANG_F   # +2.408
X_REAR = AXLE_R_X - OVERHANG_R    # -2.688

TRACK_F = 1.684
TRACK_R = 1.660

# ---- wheels / tyres ------------------------------------------------------
# front 285/40 ZR20 on 10.5Jx20, rear 295/35 ZR21 on 11Jx21
TYRE_F = dict(width=0.285, aspect=0.40, rim_in=20, rim_width_in=10.5)
TYRE_R = dict(width=0.295, aspect=0.35, rim_in=21, rim_width_in=11.0)


def tyre_radius(t):
    return t["rim_in"] * 0.0254 / 2 + t["width"] * t["aspect"]


TYRE_F_RADIUS = tyre_radius(TYRE_F)   # 0.368
TYRE_R_RADIUS = tyre_radius(TYRE_R)   # 0.370
WHEEL_F_Z = TYRE_F_RADIUS - 0.006     # axle height (slightly loaded tyre)
WHEEL_R_Z = TYRE_R_RADIUS - 0.006
# Y of the wheel *centre plane* (left side; mirror for right)
WHEEL_F_Y = TRACK_F / 2
WHEEL_R_Y = TRACK_R / 2

# ---- cabin envelope (for the interior) ------------------------------------
CABIN = dict(
    floor_z=0.30,            # top of carpet
    half_width_shoulder=0.75,  # inner half width at z~0.9
    half_width_belt=0.72,      # inner half width at the belt line z~1.0
    belt_z=1.00,
    roof_z=1.42,             # headliner at the centreline
    cowl_x=0.95,             # base of the windscreen / front of dash
    dash_rear_x=0.55,        # rear edge of the dash top (displays)
    dash_top_z=0.99,
    steering=dict(x=0.40, y=0.37, z=0.95, diameter=0.375, rake_deg=22),
    front_seat=dict(hx=0.00, hz=0.55, y=0.37, width=0.52, top_z=1.25),
    rear_seat=dict(hx=-0.85, hz=0.58, back_x=-1.25, top_z=1.12),
    parcel_shelf=dict(x0=-1.25, x1=-1.80, z=1.02),
    console=dict(width=0.22, top_z=0.66, x0=0.60, x1=-0.45),
)
