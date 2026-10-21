# Claims

Every number used in the README and the notebooks. Each comes from a notebook run on
the saved data; each notebook writes its own claims to `notebooks/figures/claims_<notebook>.csv`.

| ID | Claim | Number | Source |
|---|---|---|---|
| C0.1 | On the HIL404 at SCR 20, full IEEE 1547 request, every order is within this error of its request | 0.13 % | results/bench_hil404.csv |
| C1.1 | LCL filter resonance on a stiff grid | 1472 Hz | hil_bench/params.py |
| C1.2 | All 16 orders at their IEEE 1547 limit add up to a total distortion (TRD) of | 6.82 % (IEEE 1547 allows 5 %) | IEEE Std 1547-2018 Table 26; computed here |
| C1.3 | Largest uniform master scale that keeps TRD at 5 % | 0.733 | computed here |
| C1.4 | Grid inductance moves the LCL resonance from 1472 Hz (stiff) down to | 1070 Hz (SCR 20) ... 853 Hz (SCR 5), orders 17-21 | computed from hil_bench/params.py |
| C2.1 | HIL404, full request, worst order error on stiff / SCR 20 / SCR 10 / SCR 5 (1000 V) | 0.46 % / 0.13 % / 0.20 % / 0.26 % | results/bench_hil404.csv, scenarios_hil404.csv (F) |
| C2.2 | Scenarios A-G: worst error on the HIL404 except C (fixed resonators off-nominal) | 0.26 % (C: 95 %) | results/scenarios_summary_hil404.csv |
| C2.3 | Largest difference between panel meter and offline THD_V (HIL404, A-G) | 0.06 percentage points | results/scenarios_summary_hil404.csv |
| C2.4 | Over 82 sweep points, largest THD_V difference HIL404 vs Virtual HIL | 0.24 percentage points | results/sweep_vhil_points.csv, sweep_hil404_points.csv |
| C2.5 | Points with worst error below 1 % on both platforms | 63 of 82 | same files; the rest are SCR 5 / low-DC points still recovering after a step (notebook 06) or fixed resonators off 50 Hz (05) |
| C3.1 | Single order at a time (HIL404, SCR 10 and 5): PCC voltage / current equals the grid impedance within | 0.4 % | results/sweep_hil404_orders.csv (sweep 'single') |
| C3.2 | Current at regulated orders that were not requested (single-order sweep, HIL404) | at most 0.0025 % of rated | results/sweep_hil404_points.csv |
| C3.3 | Settled grids (stiff, SCR 20, SCR 10): even orders / triplens / above 5 kHz, at most | 0.10 / 0.13 / 0.07 % of rated | results/bench_hil404_wave_*.csv |
| C3.4 | Worst order error with 0-3 % background 5th/7th (HIL404, SCR 10) | 0.20-0.21 % | results/sweep_hil404_points.csv (sweep 'bg') |
| C4.1 | Controller tuned for a stiff grid without damping is unstable as soon as the grid has impedance | unstable from SCR 60 down | analysis, hil_bench/pr_design.py |
| C4.2 | Used design (one tuning + active damping, Kc = 2 Ω) is stable from stiff to SCR 3; slowest mode at SCR 5 decays at | 2.5 1/s (time constant 0.40 s) | analysis, hil_bench/pr_design.py; ran stably on HIL404 on all grids |
| C4.3 | With active damping, the largest phase change of any order between stiff grid and SCR 4 | 93° (so the middle value is at most 46° off) | analysis, hil_bench/pr_design.py |
| C5.1 | Adaptive resonators, 49-51 Hz (HIL404): worst order error at most | 0.17 % | results/sweep_hil404_points.csv (sweep 'freq') |
| C5.2 | Fixed resonators, any frequency 0.25 Hz or more off 50 Hz (HIL404): worst order error | 89-97 % | same file |
| C5.3 | Fixed resonators: delivered total harmonic current ranges from (49 Hz) to (51 Hz) | 2.9 % to 7.7 % (asked 6.82 %) | same file |
| C6.1 | SCR 5, full request (HIL404): error at the end of the hold at 850 / 750 / 725 V | 0.26 % / 0.23 % / 0.31 % | results/saturation_hold_hil404_SCR5_*.csv |
| C6.2 | SCR 5, full request, 700 V: steady error (does not recover) | 12.5 % | results/saturation_hold_hil404_SCR5_700.csv |
| C6.3 | SCR 5, full request, 650 V: error range and largest THD_V over the hold | 41-214 %, THD_V up to 20.7 % | results/saturation_hold_hil404_SCR5_650.csv |
| C6.4 | SCR 10 at 650 V, full request (HIL404): error at the end of the hold | 0.28 % | results/saturation_hold_hil404_SCR10_650.csv |
| C7.1 | Largest uniform emission (fraction of IEEE 1547 limits) meeting EN 50160 at every order, SCR 10 / SCR 5 | 0.55 / 0.28 (SCR 20: full request is fine) | results/sweep_hil404_points.csv (sweep 'master') |
| C7.2 | SCR 5, one order at a time at its IEEE 1547 limit: orders over EN 50160, and the worst | 7, 11, 13, 17, 19, 23, 25; the 19th at 3.6× | results/sweep_hil404_orders.csv (sweep 'single') |
