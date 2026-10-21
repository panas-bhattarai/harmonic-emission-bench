"""Is the +-3 % at orders 35-49 off-nominal real, or a measurement artefact? 49.5 Hz, SCR 20, adaptive on.
Compares: 10-cycle DFT, 50-cycle DFT, least-squares fit of all orders at once, and the model's own meter."""
import os, time
os.environ.setdefault("TYPHOONPATH", r"C:\Program Files\Typhoon HIL Control Center 2026.3")
import numpy as np, typhoon.api.hil as hil
import params as P
from run_bench import CPD, wait_sim
from test_scenarios import Panel, CUS, capture
F = 49.5
pan = Panel(CUS)
assert hil.load_model(file=CPD, vhil_device=True)
hil.start_simulation()
try:
    pan.use("Grid strength", "SCR 20"); pan.use("Grid frequency Hz", F)
    wait_sim(4.0)
    meter = {h: hil.read_analog_signal(name="m_I%d" % h) for h in P.ORDERS}
    df = capture(F, n_cycles=50, rate=25e3)
finally:
    hil.stop_simulation()
t = df.t.values; x = df.Ia.values
def dft(tt, xx, h): return 2 * abs(np.mean(xx * np.exp(-2j * np.pi * F * h * tt))) / P.I_PK * 100
n10 = int(len(t) / 5)
hs = [1] + P.ORDERS
M = np.column_stack([f(2 * np.pi * F * h * t) for h in hs for f in (np.cos, np.sin)] + [np.ones_like(t)])
coef = np.linalg.lstsq(M, x, rcond=None)[0]
ls = {h: np.hypot(coef[2 * k], coef[2 * k + 1]) / P.I_PK * 100 for k, h in enumerate(hs)}
print("order  request  10-cycle  50-cycle  LSQ-fit  meter(in model)   [% of rated]")
for h, p in zip(P.ORDERS, P.PCT):
    print("%5d  %6.2f   %7.3f   %7.3f  %7.3f  %7.3f" % (h, p, dft(t[:n10], x[:n10], h), dft(t, x, h), ls[h], meter[h]))
