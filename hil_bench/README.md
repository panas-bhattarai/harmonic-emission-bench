# hil_bench: the emitter model and its scripts

One PV inverter (100 kVA, 400 V, 750 V DC, 10 kHz, LCL filter) with a multi-resonant PR controller that
injects each harmonic order at a chosen fraction of its IEEE 1547 limit, on a grid whose strength is
switched in steps (stiff, SCR 20, SCR 10, SCR 5). **The results and what they mean are in `../notebooks`.**
This folder is the model and the scripts that produced the data in `results/`.

## Files

| File | What it does |
|---|---|
| `params.py` | Ratings, LCL filter, IEEE 1547 limits, grid sections (X/R = 3 assumed) |
| `pr_design.py` | Controller design: PR terms, capacitor-current active damping, one robust tuning for stiff grid to SCR 4 |
| `lin_check.py` | Linear check of the design on each grid |
| `controller_c.py` | Generates the C code: PLL, reference, PR, active damping, SVPWM, and the 10-cycle meter |
| `sil_test.py` | The generated C code in closed loop with an averaged power stage (quick check before Typhoon) |
| `build_bench.py` | Builds and compiles `model/emission_bench.tse` |
| `build_panel.py` | Builds the SCADA panel `model/emission_bench.cus` |
| `analog_out.py` | Analog outputs for an oscilloscope; connects a HIL device on the network |
| `run_bench.py` | Steps through the four grids, captures 10 cycles each, compares every order with its request |
| `test_scenarios.py` | Scenarios A-G (frequency, background distortion, SCR 5 at 1000 V, sliders) through the panel's own macros |
| `sweep.py` | 82-point sweeps: emission level × grid, DC voltage, grid frequency, one order at a time, background |
| `saturation_hold.py` | Steps to a weak grid and keeps measuring for minutes (saturation vs slow recovery) |
| `diag_freq.py` | Checks the per-order least-squares fit against the in-model meter off 50 Hz |
| `analysis.py` | Shared loading, calculations and plot style for the notebooks (no Typhoon needed) |
| `model/` | Typhoon model, SCADA panel, C sources of the controller and meter |

## Results files

`results/` holds what the scripts wrote: `*_vhil*` from Virtual HIL (4 Oct 2026), `*_hil404*` from the
HIL404 at Pulchowk Campus, Institute of Engineering, Tribhuvan University (5 Oct 2026), as CSV plus the run logs. `scenarios_freq.csv` is the Virtual HIL
re-run of scenarios A-D with the least-squares analysis.

## Run

Needs Typhoon HIL Control Center 2026.3 (Virtual HIL is enough). Close HIL SCADA before running a script.

```
python build_bench.py        # build and compile the model (about 10 min); writes the C file paths for your machine
python build_panel.py        # the SCADA panel
python run_bench.py          # Virtual HIL: every grid step -> results/bench_vhil*.csv
python test_scenarios.py     # scenarios A-G through the panel's macros
python sweep.py [--quick]    # the 82-point sweeps (--quick: first and last point of each)
python saturation_hold.py --grid "SCR 5" --vdc 700   # hold one point, capture every 5 s
python sil_test.py           # quick check of the C code without Typhoon

# on a real device: add --device to run_bench.py / test_scenarios.py / sweep.py / saturation_hold.py
# (set HIL_SERIAL to choose the device if more than one is on the network)
```
