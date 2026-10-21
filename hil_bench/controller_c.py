"""C source of the two signal-processing blocks, generated from the design in pr_design.py.

PR   : PLL, reference (rated current x I1 plus each order at master x e_h x its IEEE 1547 limit),
       multi-resonant PR on alpha and beta with frequency-adaptive coefficients, capacitor-current
       active damping, fundamental voltage feed-forward, modulation indices.
METER: 10-cycle DFT (IEC 61000-4-7 window length) of PCC voltage and grid current, phase a,
       synchronised to the PLL angle; per-order values and THD.
"""
import numpy as np

import params as P

HS = [1] + P.ORDERS
NH = len(HS)


def carr(name, vals, ctype="double"):
    return "%s %s[%d] = {%s};\n" % (ctype, name, len(vals), ", ".join("%.12g" % v for v in vals))


def pr_block(d, kc):
    K = [t[0] for t in d["terms"]]
    PHI = [t[1] for t in d["terms"]]
    amp_pu = [1.0] + [p / 100 for p in P.PCT]
    seq = [-1.0 if (h % 6 == 1) else 1.0 for h in HS]           # beta = seq * A cos(h theta); -1 = positive sequence
    glob = (
        "#include <math.h>\n"
        "#define NH %d\n" % NH
        + carr("HH", HS)
        + carr("KH", K)
        + carr("PHI", PHI)
        + carr("APU", amp_pu)
        + carr("SEQ", seq)
        + "double TS = %.12g, IPK = %.12g, KP = %.12g, KC = %.12g, W0 = %.12g, VPK = %.12g;\n"
        % (P.TS, P.I_PK, d["Kp"], kc, P.W0, P.V_PK)
        + "double b0[NH], b1[NH], b2[NH], a1[NH];\n"
          "double sa1[NH], sa2[NH], sb1[NH], sb2[NH];\n"
          "double th, wpll, wint, wf, vamp, ramp;\n"
          "int jupd;\n"
          "double maf[33], mafsum; int imaf;\n"
          "static void coef(int j, double w) {\n"
          "    double wh = HH[j] * w, k = wh / tan(wh * TS / 2), den = k * k + wh * wh;\n"
          "    double c = cos(PHI[j]), s = sin(PHI[j]);\n"
          "    b0[j] = KH[j] * (k * c - wh * s) / den;\n"
          "    b1[j] = -2.0 * KH[j] * wh * s / den;\n"
          "    b2[j] = KH[j] * (-k * c - wh * s) / den;\n"
          "    a1[j] = 2.0 * cos(wh * TS);\n"
          "}\n"
    )
    init = (
        "int j;\n"
        "for (j = 0; j < NH; j++) { sa1[j] = sa2[j] = sb1[j] = sb2[j] = 0.0; coef(j, W0); }\n"
        "th = 0.0; wpll = W0; wint = 0.0; wf = W0; vamp = VPK; ramp = 0.0; jupd = 0;\n"
        "for (j = 0; j < 33; j++) { maf[j] = 0.0; }\n"
        "mafsum = 0.0; imaf = 0;\n"
    )
    out = r"""
int j;
double va_ = (2.0/3.0)*(va - 0.5*vb - 0.5*vc), vb_ = (vb - vc)*0.57735026919;
double ia_ = (2.0/3.0)*(ia - 0.5*ib - 0.5*ic), ib_ = (ib - ic)*0.57735026919;
double i1a = (2.0/3.0)*(i1_a - 0.5*i1_b - 0.5*i1_c), i1b = (i1_b - i1_c)*0.57735026919;
double c1, s1, ch, sh, tmp, ea, eb, ua, ub, ya, yb, ra = 0.0, rb = 0.0, m, eps, vdc2;

/* ---- PLL: va = V sin(th). eps = sin(th_grid - th), through a moving average over T/6
   (33 samples), which removes the 6k-order ripple that the PCC harmonics put on eps; PI 5 Hz ---- */
tmp = sqrt(va_*va_ + vb_*vb_);
vamp += (tmp - vamp) * (TS / 0.5);                        /* amplitude, 0.5 s filter (feed-forward) */
c1 = cos(th); s1 = sin(th);
eps = (va_*c1 + vb_*s1) / (vamp > 50.0 ? vamp : 50.0);
mafsum += eps - maf[imaf]; maf[imaf] = eps; imaf = (imaf + 1) % 33;
eps = mafsum / 33.0;
if (pll_on > 0.5) { wint += 987.0 * eps * TS; wpll = W0 + 44.0 * eps + wint; }
else              { wint = 0.0; wpll = 2.0 * 3.14159265358979 * f_free; }
wf += (wpll - wf) * (TS / 0.05);                           /* coefficient frequency, 50 ms filter */
th += wpll * TS; if (th > 6.28318530717959) th -= 6.28318530717959;
c1 = cos(th); s1 = sin(th);

/* ---- adaptive coefficients: one branch per sample ---- */
if (adapt_on > 0.5) coef(jupd, wf); else coef(jupd, W0);
jupd = (jupd + 1) % NH;

/* ---- reference in alpha-beta, soft start 0.2 s after enable ---- */
if (enable > 0.5) { ramp += TS / 0.2; if (ramp > 1.0) ramp = 1.0; } else ramp = 0.0;
ch = c1; sh = s1;
{
    int h = 1, k = 0;
    double e[16] = {e5, e7, e11, e13, e17, e19, e23, e25, e29, e31, e35, e37, e41, e43, e47, e49};
    for (h = 1; h <= 49; h++) {
        if (h == HH[k]) {
            double a = IPK * APU[k] * (k == 0 ? I1 : master * e[k-1]) * ramp;
            ra += a * sh; rb += SEQ[k] * a * ch;
            k++;
            if (k == NH) break;
        }
        tmp = ch*c1 - sh*s1; sh = sh*c1 + ch*s1; ch = tmp;    /* (ch, sh) -> angle (h+1) th */
    }
}

/* ---- multi-resonant PR, DF2T per branch ---- */
ea = ra - ia_; eb = rb - ib_;
ua = KP * ea; ub = KP * eb;
for (j = 0; j < NH; j++) {
    ya = b0[j]*ea + sa1[j]; sa1[j] = b1[j]*ea + a1[j]*ya + sa2[j]; sa2[j] = b2[j]*ea - ya;
    yb = b0[j]*eb + sb1[j]; sb1[j] = b1[j]*eb + a1[j]*yb + sb2[j]; sb2[j] = b2[j]*eb - yb;
    ua += ya; ub += yb;
}
if (enable < 0.5) { for (j = 0; j < NH; j++) { sa1[j] = sa2[j] = sb1[j] = sb2[j] = 0.0; } ua = ub = 0.0; }

/* ---- active damping and fundamental feed-forward (PLL voltage, no harmonic path) ---- */
ua += -KC * kc_on * (i1a - ia_) + vamp * s1;
ub += -KC * kc_on * (i1b - ib_) - vamp * c1;

/* ---- back to abc, min-max zero-sequence injection (= space-vector PWM: 15 % more linear range;
   the capacitor star and the bridge float, so the common mode drives no current),
   modulation index (-1..1 = -Vdc/2..Vdc/2) ---- */
vdc2 = 0.5 * (vdc > 100.0 ? vdc : 100.0);
{
    double xa = ua, xb = -0.5*ua + 0.86602540378*ub, xc = -0.5*ua - 0.86602540378*ub;
    double mx = xa > xb ? (xa > xc ? xa : xc) : (xb > xc ? xb : xc);
    double mn = xa < xb ? (xa < xc ? xa : xc) : (xb < xc ? xb : xc);
    double v0 = -0.5 * (mx + mn);
    m = (xa + v0) / vdc2;  ma = m > 1.0 ? 1.0 : (m < -1.0 ? -1.0 : m);
    m = (xb + v0) / vdc2;  mb = m > 1.0 ? 1.0 : (m < -1.0 ? -1.0 : m);
    m = (xc + v0) / vdc2;  mc = m > 1.0 ? 1.0 : (m < -1.0 ? -1.0 : m);
}
en = enable > 0.5 ? 1.0 : 0.0;
theta = th; f_pll = wpll / 6.28318530717959; iref_a = ra; err_a = ea;
"""
    ins = ["ia", "ib", "ic", "i1_a", "i1_b", "i1_c", "va", "vb", "vc", "vdc",
           "enable", "I1", "master"] + ["e%d" % h for h in P.ORDERS] + ["pll_on", "f_free", "adapt_on", "kc_on"]
    outs = ["ma", "mb", "mc", "en", "theta", "f_pll", "iref_a", "err_a"]
    return ins, outs, glob, init, out


def meter_block():
    """Outputs V<h> in % of nominal phase voltage, I<h> in % of rated current, THD_V (16 orders and
    total), THD_I. Updated every 10 cycles of the PLL angle."""
    glob = (
        "#include <math.h>\n"
        "#define NH %d\n" % NH
        + carr("HH", HS)
        + "double VPK = %.12g, IPK = %.12g;\n" % (P.V_PK, P.I_PK)
        + "double svc[NH], svs[NH], sic[NH], sis[NH], sv2, si2, thp; int ns, ncyc;\n"
          "double Vo[NH], Io[NH], thdv, thdvt, thdi;\n"
    )
    init = ("int j; for (j = 0; j < NH; j++) { svc[j] = svs[j] = sic[j] = sis[j] = 0.0; Vo[j] = Io[j] = 0.0; }\n"
            "sv2 = si2 = 0.0; thp = 0.0; ns = 0; ncyc = 0; thdv = thdvt = thdi = 0.0;\n")
    out = r"""
int j, h, k;
double c1 = cos(theta), s1 = sin(theta), ch = c1, sh = s1, tmp;
if (theta < thp - 3.0) ncyc++;                         /* the PLL angle wrapped: one more cycle */
thp = theta;
if (ncyc == 10) {                                      /* window closed: 10 cycles */
    double v1, i1, sv = 0.0, si = 0.0;
    for (j = 0; j < NH; j++) {
        Vo[j] = 2.0 * sqrt(svc[j]*svc[j] + svs[j]*svs[j]) / ns;
        Io[j] = 2.0 * sqrt(sic[j]*sic[j] + sis[j]*sis[j]) / ns;
        if (j > 0) { sv += Vo[j]*Vo[j]; si += Io[j]*Io[j]; }
        svc[j] = svs[j] = sic[j] = sis[j] = 0.0;
    }
    v1 = Vo[0] > 1.0 ? Vo[0] : 1.0; i1 = Io[0] > 1.0 ? Io[0] : 1.0;
    thdv = 100.0 * sqrt(sv) / v1; thdi = 100.0 * sqrt(si) / i1;
    tmp = 2.0 * sv2 / ns - v1 * v1;                     /* (peak-equivalent) total minus fundamental */
    thdvt = 100.0 * sqrt(tmp > 0.0 ? tmp : 0.0) / v1;
    sv2 = si2 = 0.0; ns = 0; ncyc = 0;
}
k = 0;
for (h = 1; h <= 49; h++) {
    if (h == HH[k]) { svc[k] += va * ch; svs[k] += va * sh; sic[k] += ia * ch; sis[k] += ia * sh; k++; if (k == NH) break; }
    tmp = ch*c1 - sh*s1; sh = sh*c1 + ch*s1; ch = tmp;
}
sv2 += va * va; si2 += ia * ia; ns++;
"""
    outs = []
    lines = []
    for j, h in enumerate(HS):
        outs += ["V%d" % h, "I%d" % h]
        lines.append("V%d = 100.0 * Vo[%d] / VPK; I%d = 100.0 * Io[%d] / IPK;" % (h, j, h, j))
    outs += ["THDv", "THDv_total", "THDi"]
    lines.append("THDv = thdv; THDv_total = thdvt; THDi = thdi;")
    out += "\n".join(lines) + "\n"
    return ["va", "ia", "theta"], outs, glob, init, out


def to_files(prefix, ins, outs, glob, init, body, folder):
    """Write <prefix>.c / <prefix>.h holding all state, and return the thin output_fnc of the block.

    The block passes its inputs in u[] and takes its outputs from y[]; inside the .c file the inputs
    and outputs keep their names (as macros), so the bodies above are used unchanged."""
    import os
    os.makedirs(folder, exist_ok=True)
    h = os.path.join(folder, prefix + ".h")
    c = os.path.join(folder, prefix + ".c")
    guard = prefix.upper() + "_H"
    open(h, "w").write("#ifndef %s\n#define %s\nvoid %s_step(const double *u, double *y);\n#endif\n"
                       % (guard, guard, prefix))
    # file-scope globals are static, so two blocks never clash at link time
    glob = "\n".join(("static " + l) if l.startswith(("double ", "int ")) else l for l in glob.split("\n"))
    src = ["/* generated by controller_c.py - do not edit */", glob, "static int started = 0;",
           "void %s_step(const double *u, double *y) {" % prefix]
    src += ["#define %s (u[%d])" % (n, k) for k, n in enumerate(ins)]
    src += ["#define %s (y[%d])" % (n, k) for k, n in enumerate(outs)]
    src += ["if (!started) { started = 1; {", init, "} }", "{", body, "}"]
    src += ["#undef %s" % n for n in ins + outs]
    src += ["}"]
    open(c, "w").write("\n".join(src) + "\n")
    fnc = "double u[%d]; double y[%d];\n" % (len(ins), len(outs))
    fnc += "".join("u[%d] = %s;\n" % (k, n) for k, n in enumerate(ins))
    fnc += "%s_step(u, y);\n" % prefix
    fnc += "".join("%s = y[%d];\n" % (n, k) for k, n in enumerate(outs))
    return c, h, fnc


