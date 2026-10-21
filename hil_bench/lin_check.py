"""Linear, sampled check of the robust design: track rated current + IEEE 1547 limits from zero,
on each bench grid, and report the per-order error after 1, 2 and 3 s (no switching, no PWM)."""
import numpy as np, params as P, pr_design as D
KC, KP, SIGMA = 2.0, 1.5, 50.0
d = D.robust(KC, KP, SIGMA)
for delay in (1, 2):
    print("delay %d samples, radius per grid:" % delay,
          {str(s): round(D.radius(d, *D.scr_rl(s), delay=delay), 5) for s in (None, 20, 10, 5)})
n = int(3.0 / P.TS); t = np.arange(n) * P.TS
amp = np.r_[1.0, np.array(P.PCT) / 100] * P.I_PK
ref = sum(a * np.sin(2 * np.pi * 50 * h * t) for a, h in zip(amp, [1] + P.ORDERS))
Ac, Bc, Cc, Dc = D.controller_ss(d["Kp"], d["terms"])
for s in (None, 20, 10, 5):
    Ap, Bp, Cp = D.plant(*D.scr_rl(s), 1, KC)
    xp = np.zeros((Ap.shape[0], 1)); xc = np.zeros((Ac.shape[0], 1)); y = np.zeros(n)
    for k in range(n):
        y[k] = (Cp @ xp)[0, 0]
        e = ref[k] - y[k]
        u = (Cc @ xc)[0, 0] + Dc * e
        xc = Ac @ xc + Bc * e; xp = Ap @ xp + Bp * u
    row = []
    for t_end in (1.0, 2.0, 3.0):
        k1 = int(t_end / P.TS); seg = slice(k1 - 2000, k1)
        tt = t[seg]
        worst = 0
        for a, h in zip(amp, [1] + P.ORDERS):
            ph = 2 * np.mean(y[seg] * np.exp(-2j * np.pi * 50 * h * tt))
            worst = max(worst, abs(abs(ph) - a) / a * 100)
        row.append(worst)
    print("grid %-5s worst per-order magnitude error  1 s %.2f %%   2 s %.2f %%   3 s %.2f %%" % (s, *row))
