"""Builds the Typhoon HIL emission bench: model/emission_bench.tse, then compiles it for the HIL404.

    Vdc -> 3-phase IGBT bridge (10 kHz) -> L1 -> C+Rd star -> L2 -> PCC -> grid section A -> B -> C -> grid source
                                                                       (A, B, C each with a bypass contactor)

Controller (C, 10 kHz): PLL, reference, multi-resonant PR with capacitor-current active damping.
Meter (C, 10 kHz): 10-cycle DFT of PCC voltage and grid current, phase a.

SCADA inputs: enable, I1, master, e5 ... e49, pll_on, f_free, adapt_on, kc_on, scr_step (0 stiff, 1 SCR 20,
2 SCR 10, 3 SCR 5). DC voltage, grid voltage, frequency and background harmonics are set on the sources
from the SCADA panel (hil.set_source_...).

Run:  python build_bench.py          (HIL SCADA must be closed)
"""
import os
import sys

os.environ.setdefault("TYPHOONPATH", r"C:\Program Files\Typhoon HIL Control Center 2026.3")
from typhoon.api.schematic_editor import model as mdl

import params as P
import pr_design as D
import controller_c as CC

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "model")
TSE = os.path.join(OUT, "emission_bench.tse")
KC, KP, SIGMA = 2.0, 1.5, 50.0          # chosen in pr_design.py: stable from stiff grid to SCR 4
TS = P.TS


VERBOSE = "-v" in sys.argv


def comp(t, name, pos, rotation="up", **props):
    if VERBOSE:
        print("  comp", t, name, flush=True)
    h = mdl.create_component(t, name=name, position=pos, rotation=rotation)
    for k, v in props.items():
        mdl.set_property_value(mdl.prop(h, k), v)
    return h


CBLOCKS = set()       # C function blocks: their terminals exist only after the model is saved and reloaded
PENDING = []          # connections to C blocks, made after the reload, by component name


def wire(a, ta, b, tb=None):
    if mdl.get_name(a) in CBLOCKS or mdl.get_name(b) in CBLOCKS:
        PENDING.append((mdl.get_name(a), ta, mdl.get_name(b), tb))
        return
    mdl.create_connection(mdl.term(a, ta) if ta else a, (b if tb is None else mdl.term(b, tb)))


def cfun(name, pos, ins, outs, glob, init, code):
    files = {}
    if glob:                          # the block's own globals cannot hold functions: use a .c/.h pair
        c_path, h_path, code = CC.to_files(name.lower(), ins, outs, glob, init, code, OUT)
        files = dict(add_src_path=c_path, h_file_path=h_path)
        glob = init = ""
    h = comp("core/C function", name, pos, **files,
                input_terminals=" ".join("real %s;" % x for x in ins),
                input_terminals_show_labels=" ".join("True;" for _ in ins),
                output_terminals=" ".join("real %s;" % x for x in outs),
                output_terminals_show_labels=" ".join("True;" for _ in outs),
                global_variables=glob, init_fnc=init, output_fnc=code, execution_rate=TS)
    CBLOCKS.add(name)
    return h


def scada(name, pos, default, lo, hi):
    return comp("core/SCADA Input", name, pos, def_value=default, min=lo, max=hi, execution_rate=TS)


def imeas(name, pos):
    return comp("core/Current Measurement", name, pos, sig_output="True", execution_rate=TS)


def vmeas(name, pos, rotation="right"):
    return comp("core/Voltage Measurement", name, pos, rotation=rotation, sig_output="True", execution_rate=TS)


def build():
    os.makedirs(OUT, exist_ok=True)
    mdl.raise_exceptions(True)
    print("new model", flush=True)
    mdl.create_new_model("emission_bench")
    mdl.set_hw_settings("HIL404", 1, 2)
    print("hw set", flush=True)

    d = D.robust(KC, KP, SIGMA)
    Y = {"a": 8000, "b": 8200, "c": 8400}

    # ---------------- DC side and bridge ----------------
    vdc = comp("core/Voltage Source", "Vdc", (6800, 8200), rotation="right", init_const_value=P.V_DC)
    vdcm = vmeas("Vdc_meas", (6600, 8200))
    inv = comp("core/Three Phase Inverter", "Inv", (7100, 8200), ctrl_src="Internal modulator",
               carrier_freq=P.F_SW, d_time=0.0, load_mode="on min", execution_rate=TS)
    wire(vdc, "p_node", inv, "pos_out"); wire(vdc, "n_node", inv, "neg_out")
    wire(vdcm, "p_node", vdc, "p_node"); wire(vdcm, "n_node", vdc, "n_node")

    gnd = comp("core/Ground", "gnd", (11400, 8900))
    star = mdl.create_junction(name="Jstar", position=(8000, 8800))
    gj = mdl.create_junction(name="Jgnd", position=(11400, 8800))
    wire(gnd, "node", gj)

    grid = comp("core/Three Phase Voltage Source", "Vgrid", (11200, 8200), rotation="left",
                init_rms_value=P.V_PH, init_frequency=P.F0, init_phase=0.0)
    wire(grid, "n_node", gj)

    sec = {}
    for k, s in enumerate("ABC"):
        r, l = P.rl(P.Z_SECTIONS_PU[s])
        sec[s] = (r, l, comp("core/Triple Pole Single Throw Contactor", "K" + s, (9400 + 550 * k, 7700),
                             ctrl_src="Model", initial_state="on", switching="zero current", execution_rate=TS))

    # Core coupling at the filter-capacitor node: bridge, L1 and C on one core; L2, PCC, the grid
    # sections with their contactors and the grid source on another. One core with all of it needed
    # 200 % of its matrix memory (6 bridge switches x 3 contactors).
    cpl = comp("core/Three Phase Core Coupling", "Coupling", (8070, 8200))
    for ph in "abc":
        y = Y[ph]
        r1 = comp("core/Resistor", "R1" + ph, (7350, y), resistance=P.R_W)
        l1 = comp("core/Inductor", "L1" + ph, (7550, y), inductance=P.L1)
        i1 = imeas("I1" + ph, (7750, y))
        jf = mdl.create_junction(name="Jf" + ph, position=(7950, y))
        rd = comp("core/Resistor", "Rd" + ph, (7950 + 50 * "abc".index(ph), y + 120), rotation="right", resistance=P.RD)
        cf = comp("core/Capacitor", "Cf" + ph, (7950 + 50 * "abc".index(ph), y + 220), rotation="right", capacitance=P.C)
        r2 = comp("core/Resistor", "R2" + ph, (8150, y), resistance=P.R_W)
        l2 = comp("core/Inductor", "L2" + ph, (8350, y), inductance=P.L2)
        i2 = imeas("I" + ph, (8550, y))
        jp = mdl.create_junction(name="Jpcc" + ph, position=(8750, y))
        vm = vmeas("V" + ph, (8750, y + 300))
        wire(inv, ph + "_in", r1, "p_node"); wire(r1, "n_node", l1, "p_node"); wire(l1, "n_node", i1, "p_node")
        wire(i1, "n_node", jf); wire(jf, None, cpl, ph + "_in"); wire(cpl, ph + "_out", r2, "p_node")
        wire(jf, None, rd, "p_node")
        wire(rd, "n_node", cf, "p_node"); wire(cf, "n_node", star)
        wire(r2, "n_node", l2, "p_node"); wire(l2, "n_node", i2, "p_node"); wire(i2, "n_node", jp)
        wire(vm, "p_node", jp); wire(vm, "n_node", gj)
        node = jp
        for k, s in enumerate("ABC"):
            r, l, kk = sec[s]
            x = 9000 + 550 * k
            rg = comp("core/Resistor", "Rg%s%s" % (s, ph), (x + 100, y), resistance=r)
            lg = comp("core/Inductor", "Lg%s%s" % (s, ph), (x + 300, y), inductance=l)
            jo = mdl.create_junction(name="J%s%s" % (s, ph), position=(x + 450, y))
            wire(node, None, rg, "p_node"); wire(rg, "n_node", lg, "p_node"); wire(lg, "n_node", jo)
            wire(kk, ph + "_in", node); wire(kk, ph + "_out", jo)
            node = jo
        wire(node, None, grid, ph + "_node")

    # ---------------- SCADA inputs ----------------
    X0, Y0 = 6400, 6000
    sc = {}
    spec = [("enable", 1, 0, 1), ("I1", 1.0, 0, 1), ("master", 1.0, 0, 1)] + \
           [("e%d" % h, 1.0, 0, 1) for h in P.ORDERS] + \
           [("pll_on", 1, 0, 1), ("f_free", 50.0, 45, 55), ("adapt_on", 1, 0, 1), ("kc_on", 1, 0, 1),
            ("scr_step", 1, 0, 3)]
    for k, (n, dv, lo, hi) in enumerate(spec):
        sc[n] = scada(n, (X0, Y0 + 70 * k), dv, lo, hi)

    # ---------------- grid selector ----------------
    gsel = cfun("GridSel", (X0 + 1800, Y0 + 1500), ["scr_step"], ["kA", "kB", "kC"], "", "",
                "int s = (int)(scr_step + 0.5);\n"
                "kA = s >= 1 ? 0.0 : 1.0;   /* contactor on = section bypassed */\n"
                "kB = s >= 2 ? 0.0 : 1.0;\n"
                "kC = s >= 3 ? 0.0 : 1.0;\n")
    wire(sc["scr_step"], "out", gsel, "scr_step")
    for s in "ABC":
        wire(gsel, "k" + s, sec[s][2], "ctrl_in")

    # ---------------- controller ----------------
    ins, outs, glob, init, code = CC.pr_block(d, KC)
    pr = cfun("PR", (X0 + 1200, Y0 + 700), ins, outs, glob, init, code)
    src = {"ia": "Ia", "ib": "Ib", "ic": "Ic", "i1_a": "I1a", "i1_b": "I1b", "i1_c": "I1c",
           "va": "Va", "vb": "Vb", "vc": "Vc", "vdc": "Vdc_meas"}
    for t, n in src.items():
        wire(mdl.get_item(n), "out", pr, t)
    for t in ins:
        if t in sc:
            wire(sc[t], "out", pr, t)
    for k, (t, inp) in enumerate([("ma", "InA"), ("mb", "InB"), ("mc", "InC"), ("en", "En")]):
        wire(pr, t, inv, inp)
    for k, t in enumerate(["theta", "f_pll", "iref_a", "err_a"]):
        wire(pr, t, comp("core/Probe", t, (X0 + 1700, Y0 + 900 + 80 * k)), "in")

    # ---------------- meter ----------------
    ins, outs, glob, init, code = CC.meter_block()
    met = cfun("Meter", (X0 + 2400, Y0 + 700), ins, outs, glob, init, code)
    wire(mdl.get_item("Va"), "out", met, "va"); wire(mdl.get_item("Ia"), "out", met, "ia")
    wire(pr, "theta", met, "theta")
    for k, t in enumerate(outs):
        wire(met, t, comp("core/Probe", "m_" + t, (X0 + 2800 + 250 * (k // 20), Y0 + 60 * (k % 20))), "in")

    mdl.save_as(TSE)
    mdl.close_model()
    mdl.load(TSE)
    for a, ta, b, tb in PENDING:
        mdl.create_connection(mdl.term(mdl.get_item(a), ta), mdl.term(mdl.get_item(b), tb))
    mdl.save()
    print("%d connections to C blocks made after reload" % len(PENDING), flush=True)
    return d


if __name__ == "__main__":
    d = build()
    print("saved", TSE, " Kp %.3f  Kc %.1f  sigma %.0f" % (d["Kp"], KC, SIGMA), flush=True)
    if "--no-compile" not in sys.argv:
        ok = mdl.compile()
        print("compile:", ok, "->", mdl.get_compiled_model_file(TSE), flush=True)
    mdl.close_model()
