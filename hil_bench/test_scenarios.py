"""Items 1-3 of the open list, in one Virtual HIL session, driven through the SCADA panel's OWN macro code.

The macros (slider/combo/checkbox 'on use' code, the panel initialization code and the bar-graph
expressions) are read from model/emission_bench.cus and executed here with `inputValue` set, in one
shared namespace, exactly as HIL SCADA would run them. This tests the panel logic without the GUI.

Scenarios (each: change -> settle -> capture 10 cycles -> per-order analysis at the actual frequency):
  A  SCR 20, 50 Hz                           baseline
  B  frequency 49.5 Hz, adaptive resonators on
  C  frequency 49.5 Hz, adaptive resonators off
  D  frequency 50.5 Hz, adaptive on
  E  50 Hz, background 5th and 7th at 2 % each
  F  SCR 5, DC 1000 V (background off)
  G  SCR 5, DC 1000 V, master emission 0.5 and h13 slider 0

Writes results/scenarios.csv, results/scenarios_summary.csv, results/scenarios_*.png.
Run:  python test_scenarios.py      (HIL SCADA must be closed)
"""
import os
import time
import xml.etree.ElementTree as ET

os.environ.setdefault("TYPHOONPATH", r"C:\Program Files\Typhoon HIL Control Center 2026.3")
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import typhoon.api.hil as hil

import argparse

import params as P
import analog_out as AO
from run_bench import CPD, CH, RES, wait_sim, analyse

CUS = os.path.join(os.path.dirname(CPD), "..", "emission_bench.cus")
HS = P.ORDERS
SUFFIX = ("_freq" if os.environ.get("ONLY_FREQ") else "") + ("_hil404" if "--device" in __import__("sys").argv else "")


def load_panel(path):
    root = ET.parse(path).getroot()
    init = root.findtext("initialization_code") or ""
    widgets = {}
    for cd in root.iter("component_data"):
        name, wtype = cd.findtext("name"), cd.findtext("type")
        widgets[name] = {"type": wtype, "on_use": cd.findtext("on_use_code"), "code": cd.findtext("code"),
                         "signals": [s.text for s in cd.iter() if s.tag in ("signal", "signal_name", "name")
                                     and s.text and s.text.startswith(("m_", "f_pll", "V", "I", "iref"))]}
    return init, widgets


class Panel:
    """Runs the panel macros in one namespace, like HIL SCADA."""

    def __init__(self, path):
        self.init, self.w = load_panel(path)
        self.ns = {"hil": hil, "np": np, "printf": print, "panel": None, "api_const": None,
                   "get_settings_dir_path": lambda: os.path.dirname(path),
                   "add_to_python_path": lambda p: None}
        exec(self.init, self.ns)

    def use(self, name, value):
        assert name in self.w, "no widget %r" % name
        self.ns["inputValue"] = value
        exec(self.w[name]["on_use"], self.ns)

    def expression(self, name):
        exec(self.w[name]["code"], self.ns)
        return self.ns["displayValue"]


def capture(f, n_cycles=10, rate=50e3):
    step = hil.get_sim_step()
    dec = max(1, int(round(1 / (rate * step))))
    n = int(round(n_cycles / f / (dec * step)))
    n += n % 2                                  # the capture accepts only an even number of samples
    buf = []
    hil.start_capture(cpSettings=[dec, len(CH), n], trSettings=["Forced"], chSettings=[CH, []], dataBuffer=buf)
    while hil.capture_in_progress():
        time.sleep(0.2)
    names, data, t = buf[0]
    df = pd.DataFrame(np.asarray(data).T, columns=list(names))
    df.insert(0, "t", np.asarray(t) - np.asarray(t)[0])
    span = df.t.iloc[-1] * f
    assert abs(span - n_cycles) < 0.05, "capture holds %.2f cycles, not %d" % (span, n_cycles)
    return df


def main():
    os.makedirs(RES, exist_ok=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", action="store_true", help="run on the HIL404 instead of Virtual HIL")
    a = ap.parse_args()
    if a.device:
        assert AO.connect_device(), "HIL404 not connected"
    assert hil.load_model(file=CPD, vhil_device=not a.device), "load failed"
    bad = AO.set_all(hil)
    print("analog outputs set%s" % (" - FAILED on channels %s" % bad if bad else ""), flush=True)
    pan = Panel(CUS)                          # after the load: its init code sets the analog outputs too
    print("panel: %d widgets, init code %d lines" % (len(pan.w), pan.init.count("\n")), flush=True)
    def flat(x):
        return [z for y in x for z in flat(y)] if isinstance(x, (list, tuple)) else [x]
    sigs = set(flat(hil.get_analog_signals()))
    needed = ["m_V%d" % h for h in HS] + ["m_I%d" % h for h in HS] + \
             ["m_THDv", "m_THDv_total", "m_THDi", "f_pll", "Va", "Vb", "Vc", "Ia", "iref_a"]
    missing = [s for s in needed if s not in sigs]
    print("signals the panel reads: %d, missing in the model: %s" % (len(needed), missing or "none"), flush=True)

    hil.start_simulation()
    rows, summary = [], []
    expected_req = {h: p for h, p in zip(HS, P.PCT)}

    def step(tag, desc, f, settle, req_scale=None):
        wait_sim(settle)
        df = capture(f)
        tab, thd_v, thd_i = analyse(df, f0=f)
        req = dict(expected_req)
        if req_scale:
            req = {h: req[h] * req_scale.get(h, 1.0) for h in HS}
        tab["I_request_pct"] = [100.0] + [req[h] for h in HS]
        err = []
        for _, r in tab[tab.order > 1].iterrows():
            e = abs(r.I_pct - r.I_request_pct)
            err.append(e / r.I_request_pct * 100 if r.I_request_pct > 0 else e / 0.3 * 100)  # zero request: % of the smallest limit
        tab.insert(0, "scenario", tag)
        rows.append(tab)
        bars_v = pan.expression("PCC voltage pct of nominal orders 525")
        bars_i = pan.expression("Grid current pct of its IEEE 1547 limit orders 525")
        s = {"scenario": tag, "what": desc, "f_grid": f, "f_pll": hil.read_analog_signal(name="f_pll"),
             "worst_order_error_pct": max(err), "THD_V_pct": thd_v, "THD_I_pct": thd_i,
             "meter_THDv": hil.read_analog_signal(name="m_THDv"),
             "meter_V5": hil.read_analog_signal(name="m_V5"), "offline_V5": float(tab.V_pct[tab.order == 5].iloc[0]),
             "bar_I5_pct_of_limit": bars_i[0]["value"], "bar_V5": bars_v[0]["value"], "n_bars": len(bars_v),
             "sim_time": hil.get_sim_time()}
        summary.append(s)
        print("%s %-44s f_pll %.3f  worst order error %6.2f %%  THD_V %.2f %%  (meter %.2f)  bar I5 %.1f %% of limit"
              % (tag, desc, s["f_pll"], s["worst_order_error_pct"], thd_v, s["meter_THDv"],
                 s["bar_I5_pct_of_limit"]), flush=True)
        return tab

    t0 = time.time()
    try:
        pan.use("Grid strength", "SCR 20")
        step("A", "SCR 20, 50 Hz", 50.0, 3.0)
        pan.use("Grid frequency Hz", 49.5)
        step("B", "49.5 Hz, adaptive resonators on", 49.5, 3.0)
        pan.use("Frequencyadaptive resonators", False)
        step("C", "49.5 Hz, adaptive resonators OFF", 49.5, 3.0)
        pan.use("Frequencyadaptive resonators", True)
        pan.use("Grid frequency Hz", 50.5)
        step("D", "50.5 Hz, adaptive on", 50.5, 3.0)
        pan.use("Grid frequency Hz", 50.0)
        if os.environ.get("ONLY_FREQ"):          # rerun of A-D only
            return_early = True
            raise KeyboardInterrupt
        pan.use("Background 5th pct of V", 2.0)
        pan.use("Background 7th pct of V", 2.0)
        step("E", "50 Hz, background 5th + 7th at 2 %", 50.0, 3.0)
        pan.use("Background 5th pct of V", 0.0)
        pan.use("Background 7th pct of V", 0.0)
        pan.use("Grid strength", "SCR 5")
        pan.use("DC voltage V", 1000.0)
        step("F", "SCR 5, DC 1000 V", 50.0, 4.0)
        pan.use("Master emission", 0.5)
        pan.use("h13  limit 2 pct", 0.0)
        step("G", "SCR 5, DC 1000 V, master 0.5, h13 off", 50.0, 3.0,
             req_scale={h: (0.0 if h == 13 else 0.5) for h in HS})
    except KeyboardInterrupt:
        if not os.environ.get("ONLY_FREQ"):
            raise
    finally:
        hil.stop_simulation()
    print("wall %.0f s" % (time.time() - t0))

    full = pd.concat(rows, ignore_index=True)
    full.to_csv(os.path.join(RES, "scenarios%s.csv" % SUFFIX), index=False)
    sm = pd.DataFrame(summary)
    sm.to_csv(os.path.join(RES, "scenarios_summary%s.csv" % SUFFIX), index=False)
    print(sm.to_string(index=False))
    plot(full, sm)


def plot(full, sm):
    hs = np.array(HS)
    tags = list(sm.scenario)
    fig, axs = plt.subplots(len(tags), 1, figsize=(11, 2.8 * len(tags)), squeeze=False)
    for ax, tg in zip(axs[:, 0], tags):
        t = full[(full.scenario == tg) & (full.order > 1)]
        ax.bar(hs - 0.4, t.I_request_pct, 0.8, color="0.8", label="request")
        ax.bar(hs + 0.4, t.I_pct, 0.8, color="C0", label="measured")
        what = sm[sm.scenario == tg].what.iloc[0]
        ax.set_title("%s: %s - grid current per order, %% of rated" % (tg, what))
        ax.set_xticks(hs); ax.set_ylabel("% of rated"); ax.legend(loc="upper right")
    ax.set_xlabel("harmonic order")
    fig.tight_layout(); fig.savefig(os.path.join(RES, "scenarios_current%s.png" % SUFFIX), dpi=120); plt.close(fig)

    fig, axs = plt.subplots(len(tags), 1, figsize=(11, 2.8 * len(tags)), squeeze=False)
    for ax, tg in zip(axs[:, 0], tags):
        t = full[(full.scenario == tg) & (full.order > 1)]
        rel = np.where(t.I_request_pct > 0, (t.I_pct - t.I_request_pct) / t.I_request_pct.replace(0, np.nan) * 100,
                       t.I_pct / 0.3 * 100)
        ax.bar(hs, rel, 1.2, color=["C3" if abs(x) > 2 else "C2" for x in rel])
        ax.axhline(0, color="k", lw=0.8)
        ax.set_title("%s: error per order, %% of its request (red = more than 2 %%)" % tg)
        ax.set_xticks(hs); ax.set_ylabel("%")
    ax.set_xlabel("harmonic order")
    fig.tight_layout(); fig.savefig(os.path.join(RES, "scenarios_error%s.png" % SUFFIX), dpi=120); plt.close(fig)


if __name__ == "__main__":
    main()
