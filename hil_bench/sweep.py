"""Parameter sweeps on the emission bench, driven through the SCADA panel's own macros (as test_scenarios.py).

Sweeps (each point: change -> settle -> capture 10 cycles -> least-squares per-order analysis):
  master  master emission 0.25 / 0.5 / 0.733 / 1.0 on every grid (750 V DC). 0.733 is the largest
          uniform scale at which the request meets IEEE 1547 TRD 5 % (all orders at limit = 6.82 %).
  vdc     DC voltage 650 / 750 / 850 / 1000 V on SCR 10 and SCR 5: where the bridge saturates.
  freq    grid frequency 49.0..51.0 Hz in 0.25 Hz steps, adaptive resonators on and off, SCR 20.
  single  one order at a time at its limit (others 0) on SCR 10 and SCR 5: PCC voltage per unit of
          current at each order, and the current induced at orders that were not requested.
  bg      background 5th and 7th together at 0 / 1 / 2 / 3 % on SCR 10 and SCR 5.

Writes results/sweep<suffix>_orders.csv (one row per point and order), results/sweep<suffix>_points.csv
(one row per point, written after every point so a crash keeps what was done) and
results/sweep<suffix>_<sweep>.png.

Run:  python sweep.py [--device] [--only master,vdc] [--quick]
      --quick runs the first and last point of each sweep only (a smoke test).
      (HIL SCADA must be closed)
"""
import argparse
import os
import time

os.environ.setdefault("TYPHOONPATH", r"C:\Program Files\Typhoon HIL Control Center 2026.3")
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import typhoon.api.hil as hil

import params as P
import analog_out as AO
from run_bench import CPD, RES, wait_sim, analyse
from test_scenarios import CUS, Panel, capture

HS = P.ORDERS
LIM = dict(zip(HS, P.PCT))
GRIDS = ["stiff", "SCR 20", "SCR 10", "SCR 5"]
# EN 50160 (LV, Table 1) individual harmonic voltage, % of U1, orders up to 25; THD 8 %
EN50160 = {5: 6.0, 7: 5.0, 11: 3.5, 13: 3.0, 17: 2.0, 19: 1.5, 23: 1.5, 25: 1.5}
# IEEE 519-2022 Table 1, bus <= 1 kV: 5 % per order, THD 8 %
IEEE519 = 5.0
THD_LIM = 8.0
DEFAULT = {"grid": "SCR 20", "master": 1.0, "vdc": P.V_DC, "f": P.F0, "bg": 0.0, "adapt": True,
           "only": None}


def points():
    """List of (sweep, settings) in run order; settings are changes from DEFAULT."""
    out = []
    for g in GRIDS:
        for m in (0.25, 0.5, 0.733, 1.0):
            out.append(("master", {"grid": g, "master": m}))
    for g in ("SCR 10", "SCR 5"):
        for v in (650.0, 750.0, 850.0, 1000.0):
            out.append(("vdc", {"grid": g, "vdc": v}))
    for a in (True, False):
        for f in np.arange(49.0, 51.001, 0.25):
            out.append(("freq", {"grid": "SCR 20", "f": round(float(f), 2), "adapt": a}))
    for g in ("SCR 10", "SCR 5"):
        for h in HS:
            out.append(("single", {"grid": g, "only": h}))
    for g in ("SCR 10", "SCR 5"):
        for b in (0.0, 1.0, 2.0, 3.0):
            out.append(("bg", {"grid": g, "bg": b}))
    return out


class Bench:
    """Applies a settings dict through the panel widgets, touching only what changed."""

    def __init__(self, pan):
        self.pan = pan
        self.hname = {h: next(k for k in pan.w if k.startswith("h%d " % h)) for h in HS}
        self.cur = {}

    def apply(self, s):
        s = dict(DEFAULT, **s)
        c, u = self.cur, self.pan.use
        changed = [k for k in s if c.get(k, object()) != s[k]]
        if "grid" in changed:
            u("Grid strength", s["grid"])
        if "master" in changed:
            u("Master emission", s["master"])
        if "vdc" in changed:
            u("DC voltage V", s["vdc"])
        if "adapt" in changed:
            u("Frequencyadaptive resonators", s["adapt"])
        if "f" in changed:
            u("Grid frequency Hz", s["f"])
        if "bg" in changed:
            u("Background 5th pct of V", s["bg"])
            u("Background 7th pct of V", s["bg"])
        if "only" in changed:
            for h in HS:
                u(self.hname[h], 1.0 if s["only"] in (None, h) else 0.0)
        self.cur = s
        # grid, DC or frequency steps excite the slowest mode (~0.5 s on SCR 5): give them longer
        return s, (3.0 if {"grid", "vdc", "f", "adapt"} & set(changed) else 2.0)


def evaluate(tab, s):
    """Request per order, tracking error over requested orders, voltage compliance."""
    req = {h: (LIM[h] * s["master"] if s["only"] in (None, h) else 0.0) for h in HS}
    tab["I_request_pct"] = [100.0] + [req[h] for h in HS]
    rq = tab["I_request_pct"]
    tab["I_error_pct_of_request"] = ((tab.I_pct - rq) / rq.where(rq > 0) * 100)   # vs the scaled request
    t = tab[tab.order > 1]
    on = t[t.I_request_pct > 0]
    err = ((on.I_pct - on.I_request_pct).abs() / on.I_request_pct * 100)
    off = t[t.I_request_pct == 0]
    v = dict(zip(t.order, t.V_pct))
    en = {h: v[h] / EN50160[h] for h in EN50160}
    return {
        "worst_order_error_pct": float(err.max()),
        "worst_order": int(on.order.iloc[int(np.argmax(err.values))]),
        "max_unrequested_I_pct_rated": float(off.I_pct.max()) if len(off) else 0.0,
        "EN50160_worst_ratio": max(en.values()),
        "EN50160_worst_order": max(en, key=en.get),
        "EN50160_orders_over": sum(r > 1 for r in en.values()),
        "IEEE519_orders_over": int((t.V_pct > IEEE519).sum()),
        "V_max_pct": float(t.V_pct.max()),
        "V_max_order": int(t.order.iloc[int(np.argmax(t.V_pct.values))]),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", action="store_true", help="run on the HIL404 instead of Virtual HIL")
    ap.add_argument("--only", default="", help="comma list of sweeps: master,vdc,freq,single,bg")
    ap.add_argument("--quick", action="store_true", help="first and last point of each sweep only")
    a = ap.parse_args()
    suffix = ("_hil404" if a.device else "_vhil") + ("_quick" if a.quick else "")
    pts = points()
    if a.only:
        pts = [p for p in pts if p[0] in a.only.split(",")]
    if a.quick:
        keep = []
        for name in dict.fromkeys(p[0] for p in pts):
            sub = [p for p in pts if p[0] == name]
            keep += [sub[0], sub[-1]]
        pts = keep
    os.makedirs(RES, exist_ok=True)
    f_orders = os.path.join(RES, "sweep%s_orders.csv" % suffix)
    f_points = os.path.join(RES, "sweep%s_points.csv" % suffix)

    if a.device:
        assert AO.connect_device(), "HIL404 not connected"
    assert hil.load_model(file=CPD, vhil_device=not a.device), "load failed"
    AO.set_all(hil)
    bench = Bench(Panel(CUS))
    print("%d points%s" % (len(pts), " on the HIL404" if a.device else " on Virtual HIL"), flush=True)

    hil.start_simulation()
    bench.apply({})
    wait_sim(2.0)                                  # soft start
    rows, summ, t0 = [], [], time.time()
    try:
        for k, (name, chg) in enumerate(pts):
            s, settle = bench.apply(chg)
            wait_sim(settle)
            df = capture(s["f"])
            tab, thd_v, thd_i = analyse(df, f0=s["f"])
            ev = evaluate(tab, s)
            info = {"point": k, "sweep": name, **{kk: s[kk] for kk in DEFAULT}}
            info["only"] = 0 if s["only"] is None else s["only"]
            tab = tab.assign(**info)
            rows.append(tab)
            row = {**info, "THD_V_pct": thd_v, "THD_I_pct": thd_i, **ev,
                   "f_pll": hil.read_analog_signal(name="f_pll"), "sim_time": hil.get_sim_time(),
                   "wall_s": time.time() - t0}
            summ.append(row)
            pd.DataFrame(summ).to_csv(f_points, index=False)
            pd.concat(rows, ignore_index=True).to_csv(f_orders, index=False)
            print("%3d/%d %-6s %-28s THD_V %6.2f  THD_I %5.2f  worst err %6.2f %% (h%d)  EN50160 x%.2f (h%d)  wall %4.0f s"
                  % (k + 1, len(pts), name, ", ".join("%s=%s" % (kk, v) for kk, v in chg.items()), thd_v, thd_i,
                     ev["worst_order_error_pct"], ev["worst_order"], ev["EN50160_worst_ratio"],
                     ev["EN50160_worst_order"], row["wall_s"]), flush=True)
    finally:
        hil.stop_simulation()
    plot(pd.DataFrame(summ), pd.concat(rows, ignore_index=True), suffix)


def save(fig, suffix, name):
    fig.tight_layout()
    fig.savefig(os.path.join(RES, "sweep%s_%s.png" % (suffix, name)), dpi=120)
    plt.close(fig)


def plot(sm, od, suffix):
    """One figure per sweep, panels stacked (one per row)."""
    if (sm.sweep == "master").any():
        d = sm[sm.sweep == "master"]
        fig, ax = plt.subplots(3, 1, figsize=(10, 11))
        for g in GRIDS:
            x = d[d.grid == g]
            ax[0].plot(x.master, x.THD_V_pct, "o-", label=g)
            ax[1].plot(x.master, x.EN50160_worst_ratio, "o-", label=g)
            ax[2].plot(x.master, x.worst_order_error_pct, "o-", label=g)
        ax[0].axhline(THD_LIM, color="k", ls="--", lw=0.8, label="EN 50160 / IEEE 519 THD 8 %")
        ax[0].set_ylabel("PCC THD V, %"); ax[0].set_title("PCC voltage THD vs emission (master x IEEE 1547 limits)")
        ax[1].axhline(1, color="k", ls="--", lw=0.8)
        ax[1].set_ylabel("worst order V / EN 50160 limit")
        ax[1].set_title("Worst order against EN 50160 (above 1 = limit exceeded)")
        ax[2].set_ylabel("%"); ax[2].set_title("Worst current tracking error, % of request (saturation shows here)")
        for x in ax:
            x.axvline(0.733, color="0.6", lw=0.8); x.legend(); x.set_xlabel("master emission (0.733 = TRD 5 %)")
        save(fig, suffix, "master")
    if (sm.sweep == "vdc").any():
        d = sm[sm.sweep == "vdc"]
        fig, ax = plt.subplots(2, 1, figsize=(10, 7.5))
        for g in ("SCR 10", "SCR 5"):
            x = d[d.grid == g]
            ax[0].plot(x.vdc, x.worst_order_error_pct, "o-", label=g)
            ax[1].plot(x.vdc, x.THD_I_pct, "o-", label=g)
        ax[0].set_title("Worst current tracking error vs DC voltage"); ax[0].set_ylabel("% of request")
        ax[1].axhline(6.82, color="k", ls="--", lw=0.8, label="request 6.82 %")
        ax[1].set_title("Delivered current THD vs DC voltage"); ax[1].set_ylabel("THD I, %")
        for x in ax:
            x.legend(); x.set_xlabel("DC voltage, V")
        save(fig, suffix, "vdc")
    if (sm.sweep == "freq").any():
        d = sm[sm.sweep == "freq"]
        fig, ax = plt.subplots(2, 1, figsize=(10, 7.5))
        for a_, lab in ((True, "adaptive resonators"), (False, "fixed resonators")):
            x = d[d.adapt == a_]
            ax[0].plot(x.f, x.worst_order_error_pct, "o-", label=lab)
            ax[1].plot(x.f, x.THD_I_pct, "o-", label=lab)
        ax[0].set_yscale("symlog", linthresh=1); ax[0].set_ylabel("% of request")
        ax[0].set_title("Worst current tracking error vs grid frequency (SCR 20)")
        ax[1].axhline(6.82, color="k", ls="--", lw=0.8, label="request 6.82 %")
        ax[1].set_title("Delivered current THD vs grid frequency"); ax[1].set_ylabel("THD I, %")
        for x in ax:
            x.legend(); x.set_xlabel("grid frequency, Hz")
        save(fig, suffix, "freq")
    if (sm.sweep == "single").any():
        o = od[(od.sweep == "single") & (od.order == od.only)]
        fig, ax = plt.subplots(2, 1, figsize=(10, 7.5))
        for g in ("SCR 10", "SCR 5"):
            x = o[o.grid == g]
            # PCC voltage per unit current at the same order: |Z| seen at the PCC, % V per % I
            ax[0].plot(x.order, x.V_pct / x.I_pct, "o-", label=g)
            ax[1].plot(x.order, x.V_pct, "o-", label=g)
        ax[0].set_title("PCC voltage per unit of injected current, one order at a time (|Z| at the PCC, pu)")
        ax[0].set_ylabel("V% / I%")
        ax[1].plot(list(EN50160), list(EN50160.values()), "k_", ms=14, mew=2, label="EN 50160")
        ax[1].set_title("PCC voltage with that order alone at its IEEE 1547 limit"); ax[1].set_ylabel("% of nominal")
        for x in ax:
            x.set_xticks(HS); x.legend(); x.set_xlabel("harmonic order")
        save(fig, suffix, "single")
    if (sm.sweep == "bg").any():
        d = sm[sm.sweep == "bg"]
        fig, ax = plt.subplots(2, 1, figsize=(10, 7.5))
        for g in ("SCR 10", "SCR 5"):
            x = d[d.grid == g]
            ax[0].plot(x.bg, x.worst_order_error_pct, "o-", label=g)
            ax[1].plot(x.bg, x.THD_V_pct, "o-", label=g)
        ax[0].set_title("Worst current tracking error vs background 5th + 7th"); ax[0].set_ylabel("% of request")
        ax[1].set_title("PCC THD V (16 orders) vs background"); ax[1].set_ylabel("%")
        for x in ax:
            x.legend(); x.set_xlabel("background 5th and 7th, % of V each")
        save(fig, suffix, "bg")


if __name__ == "__main__":
    main()
