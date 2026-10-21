"""Multi-resonant PR design, the Python port of simulink/design_pr.m, plus a stability check
against grids other than the one it was designed for.

Plant per phase: inverter voltage -> L1 -> node (C + Rd to star) -> L2 + Lg -> grid (shorted).
ZOH at TS, then `delay` samples of computation delay. Controller per axis:
    C(z) = Kp + sum_h H_h(z),  H_h = Tustin(prewarped at w_h) of K_h (s cos phi_h - w_h sin phi_h)/(s^2 + w_h^2)
Kp = kp_frac x largest stable gain; phi_h = -angle(T_h); K_h = 2 sigma / |T_h|, T_h = G/(1 + Kp G) at w_h.
"""
import numpy as np
from scipy.signal import cont2discrete

import params as P


def plant(lg=0.0, rg=0.0, delay=1, kc=0.0):
    """Discrete state space (A, B, C) of i2 / v_pr, with `delay` samples of delay.

    kc > 0 closes the active-damping loop first: v_inverter[n] = v_pr[n] - kc i_c[n], i_c = i1 - i2
    (capacitor current, sampled with the rest), applied after the same delay."""
    l1, l2, c, rd, r = P.L1, P.L2 + lg, P.C, P.RD, P.R_W
    r2 = r + rg
    # states: i1, vc, i2 (vc is the capacitor voltage; node voltage = vc + rd (i1 - i2))
    A = np.array([[-(r + rd) / l1, -1 / l1, rd / l1],
                  [1 / c, 0, -1 / c],
                  [rd / l2, 1 / l2, -(r2 + rd) / l2]])
    B = np.array([[1 / l1], [0], [0]])
    Cm = np.array([[0, 0, 1.0]])
    Ad, Bd, Cd, _, _ = cont2discrete((A, B, Cm, np.zeros((1, 1))), P.TS, method="zoh")
    Cic = np.array([[1.0, 0, -1.0]])
    for _ in range(delay):                      # u[n] reaches the plant at n+1: one extra state
        n = Ad.shape[0]
        Ad = np.block([[Ad, Bd], [np.zeros((1, n)), np.zeros((1, 1))]])
        Bd = np.vstack([np.zeros((n, 1)), [[1.0]]])
        Cd = np.hstack([Cd, [[0.0]]])
        Cic = np.hstack([Cic, [[0.0]]])
    Ad = Ad - Bd @ (kc * Cic)
    return Ad, Bd, Cd


def freq(plant_ss, w):
    A, B, C = plant_ss
    z = np.exp(1j * w * P.TS)
    return (C @ np.linalg.solve(z * np.eye(A.shape[0]) - A, B))[0, 0]


def coeffs(K, phi, wh, ts=P.TS):
    """b0, b1, b2, a1 of one resonant branch (CONTROLLER_MATH.md section 8)."""
    k = wh / np.tan(wh * ts / 2)
    den = k * k + wh * wh
    b0 = K * (k * np.cos(phi) - wh * np.sin(phi)) / den
    b1 = -2 * K * wh * np.sin(phi) / den
    b2 = K * (-k * np.cos(phi) - wh * np.sin(phi)) / den
    return b0, b1, b2, 2 * np.cos(wh * ts)


def controller_ss(Kp, terms):
    """terms = [(K, phi, wh), ...] -> discrete state space of C(z) (two states per branch)."""
    n = 2 * len(terms)
    A = np.zeros((n, n)); B = np.zeros((n, 1)); C = np.zeros((1, n)); D = Kp
    for i, (K, phi, wh) in enumerate(terms):
        b0, b1, b2, a1 = coeffs(K, phi, wh)
        # DF2T: y = b0 e + s1; s1' = b1 e + a1 y + s2; s2' = b2 e - y
        j = 2 * i
        A[j, j] = a1; A[j, j + 1] = 1; A[j + 1, j] = -1
        B[j, 0] = b1 + a1 * b0; B[j + 1, 0] = b2 - b0
        C[0, j] = 1
        D += b0
    return A, B, C, D


def closed_loop_radius(ctrl, pl):
    Ac, Bc, Cc, Dc = ctrl
    Ap, Bp, Cp = pl
    Acl = np.block([[Ap - Bp * Dc @ Cp, Bp @ Cc], [-Bc @ Cp, Ac]])
    return np.max(np.abs(np.linalg.eigvals(Acl)))


def kmax(pl):
    lo, hi = 0.0, 50.0
    for _ in range(50):
        mid = (lo + hi) / 2
        if closed_loop_radius((np.zeros((0, 0)), np.zeros((0, 1)), np.zeros((1, 0)), mid), pl) < 1:
            lo = mid
        else:
            hi = mid
    return lo


def design(lg=0.0, rg=0.0, delay=1, kp_frac=0.5, sigma=50.0, orders=P.ORDERS, f0=P.F0, kc=0.0,
           grids=None, kp=None):
    """Nominal design on one grid (grids=None, as design_pr.m), or a robust design over a list of
    grids [(lg, rg), ...]: phi_h at the middle of the range of angle(T_h) over the grids, K_h from the
    largest |T_h| (so no term decays faster than sigma on any grid)."""
    pls = [plant(lg, rg, delay, kc)] if grids is None else [plant(l, r, delay, kc) for l, r in grids]
    Kmax = min(kmax(pl) for pl in pls)
    Kp = kp_frac * Kmax if kp is None else kp
    hs = [1] + list(orders)
    terms, spread = [], []
    for h in hs:
        wh = 2 * np.pi * f0 * h
        T = np.array([freq(pl, wh) / (1 + Kp * freq(pl, wh)) for pl in pls])
        a = np.unwrap(np.angle(T))
        mid = (a.max() + a.min()) / 2
        terms.append((2 * sigma / np.abs(T).max(), -mid, wh))
        spread.append(np.degrees(a.max() - a.min()))
    return {"Kp": Kp, "Kmax": Kmax, "hs": hs, "terms": terms, "lg": lg, "rg": rg, "delay": delay,
            "kc": kc, "sigma": sigma, "spread_deg": spread}


def radius(d, lg=None, rg=None, delay=None, n_terms=None):
    """Closed-loop spectral radius of design d on a (possibly different) grid."""
    pl = plant(d["lg"] if lg is None else lg, d["rg"] if rg is None else rg,
               d["delay"] if delay is None else delay, d["kc"])
    terms = d["terms"] if n_terms is None else d["terms"][:n_terms]
    return closed_loop_radius(controller_ss(d["Kp"], terms), pl)


def scr_rl(scr):
    """(lg, rg) of a grid with short-circuit ratio scr (None = stiff), X/R from params."""
    if scr is None:
        return 0.0, 0.0
    z = P.Z_B / scr
    r = z / np.sqrt(1 + P.X_OVER_R ** 2)
    return P.X_OVER_R * r / P.W0, r


SWEEP = [None, 60, 40, 30, 20, 15, 12, 10, 8, 6, 5, 4]


def robust(kc, kp, sigma=20.0, delay=1):
    return design(kc=kc, kp=kp, sigma=sigma, delay=delay, grids=[scr_rl(s) for s in SWEEP])


if __name__ == "__main__":
    d = design()
    print("stiff-grid design, no active damping: Kmax %.3f  Kp %.3f ohm   (MATLAB: Kp 1.06)" % (d["Kmax"], d["Kp"]))
    print("  radius on stiff grid %.4f, on SCR 20 %.4f, SCR 5 %.4f" % (
        radius(d), radius(d, *scr_rl(20)), radius(d, *scr_rl(5))))
    print("\nrobust designs, active damping; worst closed-loop radius over SCR inf..4 (slowest time constant)")
    best = None
    for kc in [1.5, 2.0, 2.5, 3.0, 3.5]:
        for kp in [0.5, 1.0, 1.5]:
            for sigma in [20.0, 50.0]:
                d = robust(kc, kp, sigma)
                w = max(radius(d, *scr_rl(s)) for s in SWEEP + [50, 25, 7, 4.5])
                tau = P.TS / (1 - w) if w < 1 else float("inf")
                print("  Kc %.1f  Kp %.1f  sigma %3.0f  max spread %5.1f deg  worst r %.5f  tau %.3f s"
                      % (kc, kp, sigma, max(d["spread_deg"]), w, tau))
                if w < 1 and (best is None or w < best[0]):
                    best = (w, kc, kp, sigma)
    print("best:", best)
