"""Is the SCR 5 saturation error history-dependent or just slow? Hold one operating point and capture repeatedly.

Steps the grid from SCR 20 to SCR 5 (master 1, given DC voltage), then captures 10 cycles every `--every`
seconds for `--hold` seconds and prints the worst order error each time.
Writes results/saturation_hold<suffix>_<vdc>.csv.

Run:  python saturation_hold.py [--device] [--vdc 750] [--hold 90] [--every 5]
"""
import argparse
import os

os.environ.setdefault("TYPHOONPATH", r"C:\Program Files\Typhoon HIL Control Center 2026.3")
import pandas as pd
import typhoon.api.hil as hil

import analog_out as AO
from run_bench import CPD, RES, wait_sim, analyse
from test_scenarios import CUS, Panel, capture
from sweep import Bench, evaluate


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", action="store_true")
    ap.add_argument("--vdc", type=float, default=750.0)
    ap.add_argument("--grid", default="SCR 5")
    ap.add_argument("--hold", type=float, default=90.0)
    ap.add_argument("--every", type=float, default=5.0)
    a = ap.parse_args()
    if a.device:
        assert AO.connect_device(), "HIL404 not connected"
    assert hil.load_model(file=CPD, vhil_device=not a.device), "load failed"
    bench = Bench(Panel(CUS))
    hil.start_simulation()
    rows = []
    try:
        bench.apply({"grid": "SCR 20", "vdc": a.vdc})
        wait_sim(3.0)
        s, _ = bench.apply({"grid": a.grid, "vdc": a.vdc})
        t0 = hil.get_sim_time()
        while hil.get_sim_time() < t0 + a.hold:
            wait_sim(a.every)
            tab, thd_v, thd_i = analyse(capture(s["f"]))
            ev = evaluate(tab, s)
            r = {"t_after_step_s": hil.get_sim_time() - t0, "THD_V_pct": thd_v, "THD_I_pct": thd_i, **ev}
            rows.append(r)
            print("t %5.1f s  worst err %6.2f %% (h%d)  THD_I %.2f  THD_V %.2f"
                  % (r["t_after_step_s"], ev["worst_order_error_pct"], ev["worst_order"], thd_i, thd_v), flush=True)
    finally:
        hil.stop_simulation()
    pd.DataFrame(rows).to_csv(os.path.join(RES, "saturation_hold%s_%s_%d.csv"
                                           % ("_hil404" if a.device else "_vhil", a.grid.replace(" ", ""), a.vdc)), index=False)


if __name__ == "__main__":
    main()
