"""Step 2 of PLAN_TYPHOON_BENCH.md: run the bench on Virtual HIL and check it against the request.

For each grid step (stiff, SCR 20, 10, 5): settle, capture 10 cycles of the PCC voltage and grid
current (all three phases), and take the IEC 61000-4-7 style DFT offline. Per order: the grid
current as % of rated against its request, and the PCC voltage as % of nominal.

Writes results/bench_<tag>.csv and the figures results/bench_<tag>_*.png.

Run:  python run_bench.py [--device] [--steps 0,1,2,3] [--settle 3] [--tag vhil]
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

HERE = os.path.dirname(os.path.abspath(__file__))
CPD = os.path.join(HERE, "model", "emission_bench Target files", "emission_bench.cpd")
RES = os.path.join(HERE, "results")
STEP_NAME = {0: "stiff", 1: "SCR 20", 2: "SCR 10", 3: "SCR 5"}
CH = ["Ia", "Ib", "Ic", "Va", "Vb", "Vc", "iref_a"]
HS = [1] + P.ORDERS


def wait_sim(dt):
    t0 = hil.get_sim_time()
    while hil.get_sim_time() < t0 + dt:
        time.sleep(0.2)


def capture(n_cycles=10, rate=50e3):
    """n_cycles of all channels at about `rate` samples/s. Returns DataFrame with column t."""
    step = hil.get_sim_step()
    dec = max(1, int(round(1 / (rate * step))))
    n = int(round(n_cycles / P.F0 / (dec * step)))
    buf = []
    hil.start_capture(cpSettings=[dec, len(CH), n], trSettings=["Forced"], chSettings=[CH, []], dataBuffer=buf)
    while hil.capture_in_progress():
        time.sleep(0.2)
    names, data, t = buf[0]
    df = pd.DataFrame(np.asarray(data).T, columns=list(names))
    df.insert(0, "t", np.asarray(t) - np.asarray(t)[0])
    return df


def dft(x, t, f0):
    """Peak amplitude per order: least-squares fit of all orders at once (plus DC) at frequency f0.

    Equal to the plain DFT when the window is exactly an integer number of cycles. Off nominal
    frequency the plain DFT leaked between neighbouring orders (+-3 % at orders 35-49 at 49.5 Hz,
    while the fit and the model's own PLL-synchronised meter both showed every order on its request:
    diag_freq.py), so the fit is used everywhere."""
    M = np.column_stack([f(2 * np.pi * f0 * h * t) for h in HS for f in (np.cos, np.sin)] + [np.ones_like(t)])
    c = np.linalg.lstsq(M, x, rcond=None)[0]
    return {h: np.hypot(c[2 * k], c[2 * k + 1]) for k, h in enumerate(HS)}


def analyse(df, f0=P.F0):
    t = df["t"].values
    rows = []
    for k, h in enumerate(HS):
        req = 100.0 if h == 1 else P.PCT[k - 1]
        i_pct = np.mean([dft(df["I" + p].values, t, f0)[h] for p in "abc"]) / P.I_PK * 100
        v_pct = np.mean([dft(df["V" + p].values, t, f0)[h] for p in "abc"]) / P.V_PK * 100
        rows.append({"order": h, "f_Hz": h * f0, "I_request_pct": req, "I_pct": i_pct,
                     "I_error_pct_of_request": (i_pct - req) / req * 100, "V_pct": v_pct})
    out = pd.DataFrame(rows)
    v_h = out.loc[out.order > 1, "V_pct"].values
    i_h = out.loc[out.order > 1, "I_pct"].values
    thd_v = np.sqrt(np.sum(v_h ** 2)) / out.V_pct.iloc[0] * 100
    thd_i = np.sqrt(np.sum(i_h ** 2)) / out.I_pct.iloc[0] * 100
    return out, thd_v, thd_i


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", action="store_true", help="run on the HIL404 instead of Virtual HIL")
    ap.add_argument("--steps", default="0,1,2,3")
    ap.add_argument("--settle", type=float, default=3.0, help="simulated seconds before the first capture")
    ap.add_argument("--settle-step", type=float, default=2.5, help="simulated seconds after a grid change")
    ap.add_argument("--tag", default=None)
    a = ap.parse_args()
    tag = a.tag or ("hil404" if a.device else "vhil")
    os.makedirs(RES, exist_ok=True)

    if a.device:
        assert AO.connect_device(), "HIL404 not connected (Ethernet via the lab router? Control Center closed?)"
    assert hil.load_model(file=CPD, vhil_device=not a.device), "load failed"
    bad = AO.set_all(hil)
    print("analog outputs set%s" % (" - FAILED on channels %s" % bad if bad else ""), flush=True)
    steps = [int(s) for s in a.steps.split(",")]
    hil.set_scada_input_value("scr_step", float(steps[0]))
    hil.start_simulation()
    tables, waves, summary = [], {}, []
    t_wall = time.time()
    try:
        wait_sim(a.settle)
        for k, s in enumerate(steps):
            if k > 0:
                hil.set_scada_input_value("scr_step", float(s))
                wait_sim(a.settle_step)
            df = capture()
            tab, thd_v, thd_i = analyse(df)
            tab.insert(0, "grid", STEP_NAME[s])
            tables.append(tab)
            waves[STEP_NAME[s]] = df
            worst = tab.loc[tab.order > 1, "I_error_pct_of_request"].abs().max()
            summary.append({"grid": STEP_NAME[s], "THD_V_pct": thd_v, "THD_I_pct": thd_i,
                            "worst_order_error_pct": worst, "f_pll": hil.read_analog_signal(name="f_pll"),
                            "sim_time": hil.get_sim_time()})
            print("%-7s THD_V %.2f %%  THD_I %.2f %%  worst order error %.2f %% of request  (sim %.1f s, wall %.0f s)"
                  % (STEP_NAME[s], thd_v, thd_i, worst, hil.get_sim_time(), time.time() - t_wall), flush=True)
    finally:
        hil.stop_simulation()

    full = pd.concat(tables, ignore_index=True)
    full.to_csv(os.path.join(RES, "bench_%s.csv" % tag), index=False)
    pd.DataFrame(summary).to_csv(os.path.join(RES, "bench_%s_summary.csv" % tag), index=False)
    for g, df in waves.items():
        df.to_csv(os.path.join(RES, "bench_%s_wave_%s.csv" % (tag, g.replace(" ", ""))), index=False)
    plot(full, waves, tag)
    print(pd.DataFrame(summary).to_string(index=False))


def plot(full, waves, tag):
    grids = list(waves)
    hs = np.array(P.ORDERS)
    # 1: current per order against request, one panel per grid
    fig, axs = plt.subplots(len(grids), 1, figsize=(11, 3.2 * len(grids)), squeeze=False)
    for ax, g in zip(axs[:, 0], grids):
        t = full[(full.grid == g) & (full.order > 1)]
        ax.bar(hs - 0.4, t.I_request_pct, 0.8, color="0.8", label="request (IEEE 1547 limit)")
        ax.bar(hs + 0.4, t.I_pct, 0.8, color="C0", label="measured grid current")
        ax.set_title("%s: grid current per order, %% of rated" % g)
        ax.set_xticks(hs); ax.set_ylabel("% of rated"); ax.legend(loc="upper right")
    ax.set_xlabel("harmonic order")
    fig.tight_layout(); fig.savefig(os.path.join(RES, "bench_%s_current.png" % tag), dpi=130); plt.close(fig)
    # 2: PCC voltage per order, all grids on one axis (grouped)
    fig, ax = plt.subplots(figsize=(11, 4))
    w = 0.8 / len(grids)
    for k, g in enumerate(grids):
        t = full[(full.grid == g) & (full.order > 1)]
        ax.bar(hs - 0.4 + w * (k + 0.5), t.V_pct, w, label=g)
    ax.set_xticks(hs); ax.set_xlabel("harmonic order"); ax.set_ylabel("% of nominal phase voltage")
    ax.set_title("PCC harmonic voltage per order, same emission on every grid"); ax.legend()
    fig.tight_layout(); fig.savefig(os.path.join(RES, "bench_%s_pcc_voltage.png" % tag), dpi=130); plt.close(fig)
    # 3: waveforms, one panel per grid
    fig, axs = plt.subplots(len(grids), 1, figsize=(11, 3.0 * len(grids)), squeeze=False)
    for ax, g in zip(axs[:, 0], grids):
        df = waves[g]; m = df.t < 0.04
        ax.plot(df.t[m] * 1e3, df.Ia[m], label="i_a measured")
        ax.plot(df.t[m] * 1e3, df.iref_a[m], "--", label="i_a reference")
        ax2 = ax.twinx(); ax2.plot(df.t[m] * 1e3, df.Va[m], color="C3", lw=0.8, label="v_a PCC"); ax2.set_ylabel("V")
        ax.set_title("%s: phase a, two cycles" % g); ax.set_ylabel("A"); ax.legend(loc="upper left")
    ax.set_xlabel("ms")
    fig.tight_layout(); fig.savefig(os.path.join(RES, "bench_%s_waves.png" % tag), dpi=130); plt.close(fig)


if __name__ == "__main__":
    main()
