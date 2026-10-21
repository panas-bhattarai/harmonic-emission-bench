"""Builds the HIL SCADA panel of the emission bench: model/emission_bench.cus

Left column  : operating point (fundamental, master emission, DC voltage, grid voltage, frequency,
               background 5th/7th, grid strength, switches).
Middle column: one slider per order, 0..1 x its IEEE 1547 limit (referred to rated current).
Right column : PCC voltage per order and grid current per order (bar graphs), THD readouts, waveforms.
"""
import os
import re

os.environ.setdefault("TYPHOONPATH", r"C:\Program Files\Typhoon HIL Control Center 2026.3")
from typhoon.api.scada import panel
import typhoon.api.scada.const as c

import params as P
import analog_out as AO
from build_bench import OUT

CUS = os.path.join(OUT, "emission_bench.cus")

INIT = """
# grid source state, shared by the grid sliders
GRID = {'v': 1.0, 'f': %.1f, 'h5': 0.0, 'h7': 0.0}
V_PH = %.6f
def apply_grid():
    hil.set_source_sine_waveform('Vgrid', rms=GRID['v'] * V_PH, frequency=GRID['f'],
                                 harmonics_pu=[(5, GRID['h5'] / 100.0, 0.0), (7, GRID['h7'] / 100.0, 0.0)])
""" % (P.F0, P.V_PH) + AO.init_code()

NOTE = (
    "PV INVERTER EMISSION BENCH  (100 kVA, 400 V, 750 V DC, 10 kHz, LCL; PR current control)\n"
    "Each order slider = fraction of its IEEE 1547 limit, referred to RATED current (not to the "
    "fundamental).\n"
    "Bars: PCC voltage per order in %% of nominal, and grid current per order in %% of rated.\n"
    "Meter = 10-cycle DFT of phase a, updated every 0.2 s. After a change, allow ~2 s to settle "
    "(slowest mode about 0.5 s on SCR 5)."
)


def widget(wtype, name, pos, size=None, **props):
    """Widget names allow only letters, digits, spaces and underscores; the full text goes in the label."""
    safe = re.sub(r"[^A-Za-z0-9 _]", "", name.replace("%", "pct").replace(".", "p")).strip()
    w = panel.create_widget(wtype, name=safe, position=list(pos))
    if safe != name:
        try:                                         # not every widget type has a label
            panel.set_property_value(w, c.PROP_USE_LABEL, True)
            panel.set_property_value(w, c.PROP_LABEL, name)
        except Exception:
            pass
    if size:
        panel.set_property_value(w, c.PROP_SIZE, list(size))
    for k, v in props.items():
        panel.set_property_value(w, k, v)
    return w


def slider(name, pos, lo, hi, step, value, on_use, width=330):
    return widget(c.WT_SLIDER_MACRO, name, pos, (width, 60), **{
        c.PROP_RANGE: [lo, hi], c.PROP_STEP: step, c.PROP_WIDGET_VALUE: value,
        c.PROP_ON_USE: on_use, c.PROP_ON_START_ENABLED: True,
        c.PROP_ON_START: "widgetValue = %r\n" % value,
    })


def checkbox(name, pos, scada_input, value=True):
    return widget(c.WT_CHECKBOX_MACRO, name, pos, (330, 32), **{
        c.PROP_WIDGET_VALUE: value,
        c.PROP_ON_USE: "hil.set_scada_input_value('%s', 1.0 if inputValue else 0.0)\n" % scada_input,
    })


def display(name, pos, signal, unit, decimals=2, width=160):
    return widget(c.WT_DIGITAL, name, pos, (width, 60), **{
        c.PROP_DATA_TYPE: "Analog signal", c.PROP_SIGNALS: signal, c.PROP_UNIT: unit,
        c.PROP_DECIMALS: decimals,
    })


LOW, HIGH = slice(0, 8), slice(8, 16)        # HIL SCADA allows at most 10 bars per graph: 2 x 8 orders


def bars(sig, limits, vmax, part=slice(None)):
    """Expression for a bar graph: one bar per order; divided by the order's limit (x100) if given."""
    orders = P.ORDERS[part]
    lims = list(limits)[part] if limits else [0] * len(orders)
    code = [
        "displayValue = []",
        "for h, lim in zip(%r, %r):" % (orders, lims),
        "    v = hil.read_analog_signal(name='%s' %% h)" % sig,
        "    if lim: v = 100.0 * v / lim",
        "    displayValue.append({'bar_name': str(h), 'value': v, 'unit': '%%', 'minimum_value': 0.0,",
        "                         'maximum_value': %r, 'use_warning_critical': %r," % (vmax, bool(limits)),
        "                         'warning_value': 100.0, 'critical_value': 105.0})",
    ]
    return "\n".join(code).replace("'%%'", "'%'") + "\n"


def build():
    panel.create_new_panel()
    widget(c.WT_TEXT_NOTE, "About", (16, 16), (1400, 90), **{c.PROP_TEXT: NOTE})

    # ---------------- left column: operating point ----------------
    x, y = 16, 120
    slider("Fundamental x rated", (x, y), 0, 1, 0.05, 1.0, "hil.set_scada_input_value('I1', inputValue)\n"); y += 68
    slider("Master emission", (x, y), 0, 1, 0.05, 1.0, "hil.set_scada_input_value('master', inputValue)\n"); y += 68
    slider("DC voltage V", (x, y), 650, 1000, 5, P.V_DC,
           "hil.set_source_constant_value('Vdc', value=inputValue)\n"); y += 68
    slider("Grid voltage pu", (x, y), 0.9, 1.1, 0.01, 1.0, "GRID['v'] = inputValue\napply_grid()\n"); y += 68
    slider("Grid frequency Hz", (x, y), 49.0, 51.0, 0.1, P.F0, "GRID['f'] = inputValue\napply_grid()\n"); y += 68
    slider("Background 5th % of V", (x, y), 0, 4, 0.1, 0.0, "GRID['h5'] = inputValue\napply_grid()\n"); y += 68
    slider("Background 7th % of V", (x, y), 0, 4, 0.1, 0.0, "GRID['h7'] = inputValue\napply_grid()\n"); y += 68
    widget(c.WT_COMBO_MACRO, "Grid strength", (x, y), (330, 60), **{
        c.PROP_COMBO_VALUES: ["stiff", "SCR 20", "SCR 10", "SCR 5"], c.PROP_WIDGET_VALUE: "SCR 20",
        c.PROP_ON_USE: "hil.set_scada_input_value('scr_step', "
                       "{'stiff': 0, 'SCR 20': 1, 'SCR 10': 2, 'SCR 5': 3}[inputValue])\n",
    }); y += 68
    checkbox("Inverter enabled", (x, y), "enable"); y += 36
    checkbox("PLL (off = free 50 Hz clock)", (x, y), "pll_on"); y += 36
    checkbox("Frequency-adaptive resonators", (x, y), "adapt_on"); y += 36
    checkbox("Active damping (capacitor current)", (x, y), "kc_on"); y += 36

    # ---------------- middle column: one slider per order ----------------
    x, y = 362, 120
    for h, p in zip(P.ORDERS, P.PCT):
        slider("h%d  (limit %g %%)" % (h, p), (x, y), 0, 1, 0.05, 1.0,
               "hil.set_scada_input_value('e%d', inputValue)\n" % h, width=300)
        y += 68                                  # same step as the left column
    y_mid_end = y

    # ---------------- right column: results ----------------
    x, y = 680, 120
    display("THD V (16 orders)", (x, y), "m_THDv", "%")
    display("THD V (total)", (x + 170, y), "m_THDv_total", "%")
    display("THD I (16 orders)", (x + 340, y), "m_THDi", "%")
    display("PLL frequency", (x + 510, y), "f_pll", "Hz", 3)
    y += 72
    for title, sig, lim, vmax in (("PCC voltage, % of nominal", "m_V%d", None, 8.0),
                                  ("Grid current, % of its IEEE 1547 limit", "m_I%d", P.PCT, 120.0)):
        group = ("PCC HARMONIC VOLTAGE per order, % of nominal phase voltage" if lim is None else
                 "GRID HARMONIC CURRENT per order, % of its IEEE 1547 limit (100 = at the limit)")
        widget(c.WT_TEXT_NOTE, group, (x, y), (720, 34), **{c.PROP_TEXT: group})
        y += 42
        for part, rng in ((LOW, "orders 5-25"), (HIGH, "orders 29-49")):
            widget(c.WT_BAR_GRAPH, "%s, %s" % (title, rng), (x, y), (720, 150), **{
                c.PROP_DATA_TYPE: "Expression", c.PROP_EXPRESSION: bars(sig, lim, vmax, part)})
            y += 158
    widget(c.WT_TRACE, "THD V at PCC, %", (x, y), (720, 200), **{
        c.PROP_SIGNALS: [["m_THDv", "m_THDv_total"], []], c.PROP_TIME_WINDOW: 30})
    y += 210
    y_scope = max(y, y_mid_end) + 10             # below both the trace and the order sliders
    scope = [{"Name": n, "Type": c.CS_SIG_T_A, "Viewports": [vp]} for n, vp in
             (("Va", 1), ("Vb", 1), ("Vc", 1), ("Ia", 2), ("iref_a", 2))]
    widget(c.WT_CAPTURE_SCOPE, "Waveforms", (16, y_scope), (1384, 460), **{
        c.PROP_CS_STATE: "Scope", c.PROP_CS_SCOPE_LAYOUT: "Vertical",
        c.PROP_CS_SCOPE_SIGNALS: scope, c.PROP_CS_SCOPE_TIME_BASE: 0.005})

    panel.save_panel_as(CUS)
    # The panel initialization code (shared by all macros) is not settable through the API: write it
    # into the saved file.
    txt = open(CUS, encoding="utf-8").read()
    assert txt.count("]]></initialization_code>") == 1
    txt = txt.replace("]]></initialization_code>", INIT + "]]></initialization_code>")
    open(CUS, "w", encoding="utf-8").write(txt)
    return CUS


if __name__ == "__main__":
    print("saved:", build())
