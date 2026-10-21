"""Software-in-the-loop test of the generated controller C code, before Typhoon.

The exact pr.c / meter.c that go into the Typhoon model are compiled with Typhoon's own VHIL gcc into a
DLL and driven by an averaged three-phase model of the power stage (the PWM replaced by its average over
one carrier period; one sample of computation delay, as designed). Checks signs, PLL, reference
sequence, active damping and tracking on each bench grid before any slow Virtual HIL run.

Run:  python sil_test.py [--grids 0,1,2,3] [--t 3] [--f 50] [--h5 0]
"""
import argparse
import ctypes
import os
import subprocess

import numpy as np
from scipy.linalg import expm

import params as P
import pr_design as D
import controller_c as CC

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(HERE, "sil_build")
GCC = r"C:\Program Files\Typhoon HIL Control Center 2026.3\compilers\windows\vhil\gcc\bin"
KC, KP, SIGMA = 2.0, 1.5, 50.0
GRID = {0: None, 1: 20, 2: 10, 3: 5}


def build_dll():
    d = D.robust(KC, KP, SIGMA)
    pr = CC.pr_block(d, KC)
    me = CC.meter_block()
    CC.to_files("pr", *pr, BUILD)
    CC.to_files("meter", *me, BUILD)
    env = dict(os.environ, PATH=GCC + os.pathsep + os.environ["PATH"])
    dll = os.path.join(BUILD, "bench.dll")
    subprocess.run([os.path.join(GCC, "gcc.exe"), "-std=c99", "-Wall", "-O2", "-shared", "-o", dll, "pr.c", "meter.c"],
                   cwd=BUILD, env=env, check=True)
    return ctypes.CDLL(dll), pr[0], pr[1], me[0], me[1]


def run(lib, pins, pouts, mins, mouts, scr, t_end=3.0, f_grid=50.0, h5=0.0, sub=10, ovr=None):
    lg, rg = D.scr_rl(scr)
    l1, l2, c, rd, r = P.L1, P.L2 + lg, P.C, P.RD, P.R_W
    A = np.array([[-(r + rd) / l1, -1 / l1, rd / l1], [1 / c, 0, -1 / c], [rd / l2, 1 / l2, -(r + rg + rd) / l2]])
    B = np.array([[1 / l1, 0], [0, 0], [0, -1 / l2]])          # inputs: v_inv, v_grid
    h = P.TS / sub
    M = expm(np.block([[A, B], [np.zeros((2, 5))]]) * h)
    Ad, Bd = M[:3, :3], M[:3, 3:]
    x = np.zeros((3, 3))                                       # rows i1, vc, i2; columns phases a b c
    shift = np.array([0, -2 * np.pi / 3, 2 * np.pi / 3])
    m_applied = np.zeros(3); m_next = np.zeros(3)
    u = (ctypes.c_double * len(pins))(); y = (ctypes.c_double * len(pouts))()
    um = (ctypes.c_double * len(mins))(); ym = (ctypes.c_double * len(mouts))()
    vals = {"enable": 1.0, "I1": 1.0, "master": 1.0, "pll_on": 1.0, "f_free": 50.0, "adapt_on": 1.0,
            "kc_on": 1.0, "vdc": P.V_DC}
    vals.update({"e%d" % hh: 1.0 for hh in P.ORDERS})
    vals.update(ovr or {})
    n = int(round(t_end / P.TS))
    log = np.zeros((n, 5))
    vpcc = np.zeros(3)
    mmax = 0.0
    for k in range(n):
        t = k * P.TS
        # ---- sample (start of period) ----
        i1, vc, i2 = x
        vnode = vc + rd * (i1 - i2)
        vg = np.sqrt(2) * P.V_PH * (np.sin(2 * np.pi * f_grid * t + shift)
                                     + h5 / 100 * np.sin(5 * (2 * np.pi * f_grid * t + shift)))
        di2 = (vnode - (r + rg) * i2 - vg) / l2
        vpcc = vnode - P.R_W * i2 - P.L2 * di2
        vals.update(ia=i2[0], ib=i2[1], ic=i2[2], i1_a=i1[0], i1_b=i1[1], i1_c=i1[2],
                    va=vpcc[0], vb=vpcc[1], vc=vpcc[2])
        for j, nm in enumerate(pins):
            u[j] = vals[nm]
        lib.pr_step(u, y)
        out = dict(zip(pouts, list(y)))
        um[0], um[1], um[2] = vpcc[0], i2[0], out["theta"]
        lib.meter_step(um, ym)
        log[k] = [t, i2[0], out["iref_a"], vpcc[0], out["f_pll"]]
        # ---- the value computed now is applied over the NEXT period ----
        m_applied, m_next = m_next, np.array([out["ma"], out["mb"], out["mc"]]) * out["en"]
        vinv = m_applied * vals["vdc"] / 2
        mmax = max(mmax, np.abs(m_next).max()) if k > n // 2 else mmax
        vinv = vinv - vinv.mean()                               # floating star: no zero sequence
        for s in range(sub):
            ts = t + s * h
            vg = np.sqrt(2) * P.V_PH * (np.sin(2 * np.pi * f_grid * ts + shift)
                                         + h5 / 100 * np.sin(5 * (2 * np.pi * f_grid * ts + shift)))
            x = Ad @ x + Bd @ np.vstack([vinv, vg])
        if not np.all(np.isfinite(x)) or np.abs(x[2]).max() > 1e4:
            print("   diverged at t = %.3f s" % t)
            break
    meter = dict(zip(mouts, list(ym)))
    meter["m_max_2nd_half"] = mmax
    return log[:k + 1], meter


def orders_from_log(log, f0):
    seg = log[-int(round(10 / f0 / P.TS)):]
    t = seg[:, 0]
    res = {}
    for hh, req in zip([1] + P.ORDERS, [100.0] + P.PCT):
        ph = 2 * abs(np.mean(seg[:, 1] * np.exp(-2j * np.pi * f0 * hh * t)))
        res[hh] = (ph / P.I_PK * 100, req)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grids", default="0,1,2,3")
    ap.add_argument("--t", type=float, default=3.0)
    ap.add_argument("--f", type=float, default=50.0)
    ap.add_argument("--h5", type=float, default=0.0)
    ap.add_argument("--pll", type=float, default=1.0)
    ap.add_argument("--adapt", type=float, default=1.0)
    ap.add_argument("--vdc", type=float, default=P.V_DC)
    ap.add_argument("--kc", type=float, default=1.0, help="active damping on (1) or off (0)")
    a = ap.parse_args()
    lib, pins, pouts, mins, mouts = build_dll()
    for g in [int(s) for s in a.grids.split(",")]:
        log, meter = run(lib, pins, pouts, mins, mouts, GRID[g], a.t, a.f, a.h5,
                         ovr={"pll_on": a.pll, "adapt_on": a.adapt, "vdc": a.vdc, "kc_on": a.kc})
        res = orders_from_log(log, a.f)
        worst = max(abs(v - r) / r * 100 for hh, (v, r) in res.items() if hh > 1)
        fp = log[-2000:, 4]
        print("grid %-5s f_pll %.3f Hz (ripple %.2f..%.2f)  fundamental %.2f %% of rated  worst order error %.2f %% of request"
              % (GRID[g], fp.mean(), fp.min(), fp.max(), res[1][0], worst))
        print("   orders:", " ".join("%d:%.2f/%.2f" % (hh, v, r) for hh, (v, r) in res.items() if hh > 1))
        print("   peak |m| in the second half: %.3f (1 = the bridge is at its voltage limit)" % meter["m_max_2nd_half"])
        print("   meter : THDv %.2f %%  THDv_total %.2f %%  THDi %.2f %%  V5 %.3f %%  I5 %.3f %%"
              % (meter["THDv"], meter["THDv_total"], meter["THDi"], meter["V5"], meter["I5"]))
        lib = fresh(g)


def fresh(k):
    """The C state is static: a copy of the DLL under a new name starts from a clean state."""
    import shutil
    dst = os.path.join(BUILD, "bench_%d.dll" % k)
    shutil.copy(os.path.join(BUILD, "bench.dll"), dst)
    return ctypes.CDLL(dst)


if __name__ == "__main__":
    main()
