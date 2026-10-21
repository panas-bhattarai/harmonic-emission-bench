"""Shared helpers for the notebooks: load saved results, small calculations, plot style.

Needs only numpy, pandas, scipy and matplotlib (no Typhoon software). Every figure is saved as
notebooks/figures/<name>.png together with the numbers behind it in <name>.csv.
"""
import os

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import params as P
import pr_design as D

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
ROOT = os.path.dirname(HERE)
FIG = os.path.join(ROOT, "notebooks", "figures")

GRIDS = ["stiff", "SCR 20", "SCR 10", "SCR 5"]
SCR = {"stiff": None, "SCR 20": 20, "SCR 10": 10, "SCR 5": 5}
REQUEST = dict(zip(P.ORDERS, P.PCT))           # IEEE 1547-2018 Table 26, % of rated current
EN50160 = {5: 6.0, 7: 5.0, 11: 3.5, 13: 3.0, 17: 2.0, 19: 1.5, 23: 1.5, 25: 1.5}   # % of nominal voltage
IEEE519 = 5.0                                   # % per order, bus <= 1 kV

# colours: one blue per grid, darker = weaker grid; blue/orange for "used" vs "alternative"
GRID_COLOR = {"stiff": "#86b6ef", "SCR 20": "#3987e5", "SCR 10": "#1c5cab", "SCR 5": "#0d366b"}
USED, OTHER = "#2a78d6", "#eb6834"
LIMIT, BAD, INK2, MUTED = "#52514e", "#d03b3b", "#52514e", "#898781"
DEVICE = {"vhil": dict(marker="o", mfc="white", label="Virtual HIL"),
          "hil404": dict(marker="o", label="HIL404 (real device)")}

plt.rcParams.update({
    "font.family": "sans-serif", "font.sans-serif": ["Segoe UI", "DejaVu Sans"], "font.size": 11,
    "axes.titlesize": 12.5, "axes.titleweight": "bold", "axes.titlelocation": "left", "axes.titlepad": 10,
    "axes.labelsize": 11, "axes.labelcolor": INK2, "axes.edgecolor": "#c3c2b7", "axes.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": "#e1e0d9",
    "grid.linewidth": 0.8, "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelcolor": INK2,
    "ytick.labelcolor": INK2, "legend.frameon": False, "legend.fontsize": 10, "lines.linewidth": 2,
    "lines.markersize": 7, "figure.dpi": 110, "savefig.dpi": 150, "figure.facecolor": "white",
})


def load(name):
    return pd.read_csv(os.path.join(RES, name))


def panels(n, h=3.4, w=9.5):
    """n panels stacked one per row, each the full width."""
    fig, ax = plt.subplots(n, 1, figsize=(w, h * n), squeeze=False)
    return fig, ax[:, 0]


def save(fig, name, data=None):
    os.makedirs(FIG, exist_ok=True)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, name + ".png"), bbox_inches="tight")
    if data is not None:
        data.to_csv(os.path.join(FIG, name + ".csv"), index=False)


def orders_axis(ax, orders=P.ORDERS):
    ax.set_xticks(orders)
    ax.set_xlabel("harmonic order")


def grid_z_pu(grid, h):
    """|Z_grid| at order h, per unit of the inverter base (R-L grid, X/R = P.X_OVER_R)."""
    scr = SCR[grid]
    if scr is None:
        return np.zeros_like(np.asarray(h, float))
    lg, rg = D.scr_rl(scr)
    return np.abs(rg + 1j * P.W0 * np.asarray(h) * lg) / P.Z_B


def lcl_response(f, grid):
    """|grid current / inverter voltage| of the LCL filter on a grid, in A/V (no control)."""
    lg, rg = D.scr_rl(SCR[grid])
    s = 1j * 2 * np.pi * np.asarray(f)
    z1 = P.R_W + s * P.L1
    zc = P.RD + 1 / (s * P.C)
    z2 = P.R_W + rg + s * (P.L2 + lg)
    return np.abs(zc / (z1 * zc + z1 * z2 + zc * z2))


def lcl_resonance_hz(grid):
    lg, _ = D.scr_rl(SCR[grid])
    l2 = P.L2 + lg
    return np.sqrt((P.L1 + l2) / (P.L1 * l2 * P.C)) / (2 * np.pi)


def spectrum(wave, col="Ia"):
    """Amplitude spectrum of a 10-cycle capture, in % of rated peak current (or of nominal peak voltage)."""
    t = wave.t.values
    n = len(t) - 1 if len(t) % 2 else len(t)        # whole number of cycles
    dt = t[1] - t[0]
    x = wave[col].values[:n]
    amp = np.abs(np.fft.rfft(x)) / n * 2
    f = np.fft.rfftfreq(n, dt)
    base = P.I_PK if col.startswith("I") else P.V_PK
    return f, 100 * amp / base


def outside_regulated(f, amp):
    """Root-sum-square of what is NOT at a regulated order: even orders, triplens, switching band."""
    def at(h):
        return amp[np.argmin(np.abs(f - P.F0 * h))]
    even = np.sqrt(sum(at(h) ** 2 for h in range(2, 51, 2)))
    trip = np.sqrt(sum(at(h) ** 2 for h in range(3, 50, 6)))
    sw = np.sqrt(np.sum(amp[f > 5000] ** 2))
    return {"even orders 2-50": even, "triplen orders 3-45": trip, "above 5 kHz": sw}


def md_table(df, floatfmt=".3g"):
    """DataFrame -> Markdown table string (for display(Markdown(...)))."""
    cols = list(df.columns)
    def fmt(v):
        if isinstance(v, (float, np.floating)):
            return format(v, floatfmt)
        return str(v)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(fmt(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join(lines)
