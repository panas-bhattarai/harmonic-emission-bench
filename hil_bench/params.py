"""Ratings, filter, grid steps and IEEE 1547 limits for the Typhoon bench (SI units).

Same unit as simulink/PV_Inverter_PR.slx, 10 kHz design: 400 V, 100 kVA, 750 V DC.
"""
import math

S = 100e3                      # VA
V_LL = 400.0                   # V rms line-line
F0 = 50.0
W0 = 2 * math.pi * F0
V_PH = V_LL / math.sqrt(3)     # 230.9 V rms
V_PK = math.sqrt(2) * V_PH     # 326.6 V
I_PK = math.sqrt(2) * S / (math.sqrt(3) * V_LL)   # 204.1 A, rated peak phase current
Z_B = V_LL ** 2 / S            # 1.6 ohm
L_B = Z_B / W0                 # 5.093 mH
C_B = 1 / (W0 * Z_B)           # 1.989 mF

V_DC = 750.0
F_SW = 10e3
TS = 1 / F_SW                  # controller step = one carrier period

L1 = 0.10 * L_B                # 0.509 mH
L2 = 0.03 * L_B                # 0.153 mH
C = 0.05 * C_B                 # 99.5 uF, star
R_W = 0.005 * Z_B              # winding resistance of each inductor
W_RES = math.sqrt((L1 + L2) / (L1 * L2 * C))
F_RES = W_RES / (2 * math.pi)  # 1472 Hz
RD = 1 / (3 * W_RES * C)       # 0.362 ohm, in series with C

ORDERS = [5, 7, 11, 13, 17, 19, 23, 25, 29, 31, 35, 37, 41, 43, 47, 49]
PCT = [4, 4, 2, 2, 1.5, 1.5, 0.6, 0.6, 0.6, 0.6, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3]   # IEEE 1547-2018 Table 26, % of rated

# Grid: a chain of three R-L sections behind the PCC. Section A is always in; B and C have bypass
# contactors. SCR = S_sc / S of the inverter, so |Z_grid| = Z_B / SCR.
#   SCR 20: A only          |Z| = 0.05 pu
#   SCR 10: A + B           |Z| = 0.10 pu
#   SCR  5: A + B + C       |Z| = 0.20 pu
# X/R = 3 is an ASSUMPTION (transformer-dominated LV supply); change it here.
X_OVER_R = 3.0
def rl(z_pu):
    z = z_pu * Z_B
    r = z / math.sqrt(1 + X_OVER_R ** 2)
    return r, X_OVER_R * r / W0
Z_SECTIONS_PU = {"A": 0.05, "B": 0.05, "C": 0.10}
SCR_STEPS = {20: ("A",), 10: ("A", "B"), 5: ("A", "B", "C")}

def grid_rl(scr):
    """Total R, L of the grid for an SCR step (None = stiff grid)."""
    if scr is None:
        return 0.0, 0.0
    r = sum(rl(Z_SECTIONS_PU[k])[0] for k in SCR_STEPS[scr])
    l = sum(rl(Z_SECTIONS_PU[k])[1] for k in SCR_STEPS[scr])
    return r, l
