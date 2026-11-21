"""
Biogas yield and digester sizing calculator for swine waste.
Method: PAES 413:2001 (AMTEC, 2001) with stage-specific excretion from
PAES 414-1:2002 Annex B (AMTEC, 2002a).

One function per equation (Eq. 1-12 of the mid-term report).
This module holds only the calculation logic. The Streamlit interface is
in app.py (run with: streamlit run app.py). It can also be used from a
terminal: python calculator.py
"""
__version__ = "0.2.0"

import datetime
import json

# ----------------------------------------------------------------------
# Constants (single source; can be overridden from the Excel Constants sheet)
# ----------------------------------------------------------------------
STAGES = ["Nursery", "Growing", "Finishing", "Gestating sow", "Sow with litter", "Boar"]

CONSTANTS = {
    "manure": {"Nursery": 1.03, "Growing": 1.88, "Finishing": 4.38,
               "Gestating sow": 3.97, "Sow with litter": 14.73, "Boar": 4.91},
    "ts":     {"Nursery": 0.09, "Growing": 0.17, "Finishing": 0.40,
               "Gestating sow": 0.37, "Sow with litter": 1.34, "Boar": 0.45},
    "vs":     {"Nursery": 0.08, "Growing": 0.14, "Finishing": 0.32,
               "Gestating sow": 0.29, "Sow with litter": 1.07, "Boar": 0.38},
    "r_w": 1.0,        # kg water per kg manure (AMTEC 2001, 6.1.2)
    "rho_s": 1000.0,   # kg/m3 (AMTEC 2001, Annex F)
    "f_s": 0.80,       # slurry fraction, fixed/balloon (6.3.3)
    "f_g": 0.20,       # gas fraction, fixed/balloon (6.4.3)
    "k_f": 1.3,        # floating-type fluctuation factor (6.4.2)
    "LHV": 21.4,       # MJ/m3  [VERIFY: replace with a citable source]
    "MJ_PER_KWH": 3.6,
    # AMTEC 2001, Table B.4 (pig manure): HRT (d) -> m3 biogas / kg manure
    "yield_table": {25: 0.058, 30: 0.063, 35: 0.068, 50: 0.077},
    "hrt_sizing_range": (15, 25),   # Table 2, liquid pig manure
    "temp_range": (20, 40),         # mesophilic, deg C
}

DIGESTER_TYPES = ("floating", "fixed", "balloon")


def load_constants_from_excel(path):
    """Read constants from the 'Constants' sheet of the workbook so that
    Python and Excel share one sourced table."""
    from openpyxl import load_workbook
    ws = load_workbook(path, data_only=True)["Constants"]
    c = json.loads(json.dumps(CONSTANTS))  # deep copy
    c["yield_table"] = {int(k): v for k, v in c["yield_table"].items()}
    for i, st in enumerate(STAGES):
        r = 4 + i
        c["manure"][st], c["ts"][st], c["vs"][st] = (ws.cell(r, 2).value,
                                                      ws.cell(r, 3).value,
                                                      ws.cell(r, 4).value)
    c["r_w"], c["rho_s"], c["f_s"], c["f_g"], c["k_f"], c["LHV"], c["MJ_PER_KWH"] = \
        [ws.cell(13 + i, 2).value for i in range(7)]
    c["yield_table"] = {int(ws.cell(22 + i, 1).value): ws.cell(22 + i, 2).value
                        for i in range(4)}
    return c


# ----------------------------------------------------------------------
# Equations
# ----------------------------------------------------------------------
def eq1_3_loadings(herd, c=CONSTANTS):
    """Eq. 1-3: daily manure M, total solids TS, volatile solids VS (kg/day)."""
    M = sum(n * c["manure"][s] for s, n in herd.items())
    TS = sum(n * c["ts"][s] for s, n in herd.items())
    VS = sum(n * c["vs"][s] for s, n in herd.items())
    return M, TS, VS


def eq4_dilution_water(M, c=CONSTANTS):
    """Eq. 4: dilution water (kg/day; 1 L = 1 kg)."""
    return c["r_w"] * M


def eq5_slurry_volume(M, Mw, c=CONSTANTS):
    """Eq. 5: daily slurry volume Q (m3/day)."""
    return (M + Mw) / c["rho_s"]


def eq6_working_volume(Q, hrt):
    """Eq. 6: slurry (working) volume V_d (m3)."""
    return Q * hrt


def eq7_total_volume(Vd, c=CONSTANTS):
    """Eq. 7: total volume incl. gas chamber for fixed/balloon types (m3)."""
    return Vd / c["f_s"]


def yield_rate(hrt, c=CONSTANTS):
    """Gas production rate y (m3/kg manure), linear interpolation of Table B.4.
    Refuses HRT outside the tabulated range (no extrapolation, assumption A4)."""
    t = sorted(c["yield_table"].items())
    lo, hi = t[0][0], t[-1][0]
    if hrt < lo or hrt > hi:
        raise ValueError(f"HRT {hrt} d is outside the Table B.4 range {lo}-{hi} d; "
                         "yield is not extrapolated.")
    for (x0, y0), (x1, y1) in zip(t, t[1:]):
        if x0 <= hrt <= x1:
            return y0 + (y1 - y0) * (hrt - x0) / (x1 - x0)


def eq8_biogas(y, M):
    """Eq. 8: daily biogas yield G (m3/day)."""
    return y * M


def eq9_energy(G, c=CONSTANTS):
    """Eq. 9: energy equivalent E (kWh/day)."""
    return G * c["LHV"] / c["MJ_PER_KWH"]


def eq10_olr(VS, Vd):
    """Eq. 10: organic loading rate (kg VS / m3.day)."""
    return VS / Vd


def eq11_ts_slurry(TS, M, Mw):
    """Eq. 11: solids content of slurry (%)."""
    return TS / (M + Mw) * 100


def eq12_gas_chamber(G, Cg, c=CONSTANTS):
    """Eq. 12: effective gas chamber volume, floating type (m3)."""
    return c["k_f"] * (G - Cg)


# ----------------------------------------------------------------------
# Input validation
# ----------------------------------------------------------------------
def validate_inputs(herd, hrt, digester_type, temp_c, c=CONSTANTS, need_yield=True):
    """Stops with a clear message on invalid input. No silent defaults."""
    warnings = []
    if not isinstance(herd, dict) or not herd:
        raise ValueError("herd must be a dict {stage: heads}.")
    for s, n in herd.items():
        if s not in c["manure"]:
            raise ValueError(f"Unknown stage '{s}'. Valid: {STAGES}")
        if isinstance(n, bool) or not isinstance(n, int) or n < 0:
            raise ValueError(f"Heads for '{s}' must be a non-negative integer, got {n!r}.")
    if sum(herd.values()) == 0:
        raise ValueError("At least one stage must have heads > 0.")
    if digester_type not in DIGESTER_TYPES:
        raise ValueError(f"digester_type must be one of {DIGESTER_TYPES}.")
    if not isinstance(hrt, (int, float)) or hrt <= 0:
        raise ValueError("HRT must be a positive number of days.")
    ymin = min(c["yield_table"]); ymax = max(c["yield_table"])
    smin, smax = c["hrt_sizing_range"]
    if need_yield and not (ymin <= hrt <= ymax):
        raise ValueError(f"HRT {hrt} d: yield needs {ymin}-{ymax} d (Table B.4). "
                         "Use need_yield=False for sizing only (15-25 d, Table 2).")
    if not need_yield and not (smin <= hrt <= ymax):
        raise ValueError(f"HRT {hrt} d is outside the allowed {smin}-{ymax} d.")
    if not isinstance(temp_c, (int, float)) or not (-10 <= temp_c <= 60):
        raise ValueError("Temperature must be a plausible number (-10 to 60 deg C).")
    tmin, tmax = c["temp_range"]
    if not (tmin <= temp_c <= tmax):
        warnings.append(f"Temperature {temp_c} C is outside the mesophilic range "
                        f"{tmin}-{tmax} C. Yield is NOT corrected for temperature.")
    return warnings


# ----------------------------------------------------------------------
# Full design run
# ----------------------------------------------------------------------
def design_from_loads(M, TS, VS, hrt, digester_type="floating", temp_c=30,
                      gas_demand=0.0, need_yield=True, c=CONSTANTS, warnings=None):
    Mw = eq4_dilution_water(M, c)
    Q = eq5_slurry_volume(M, Mw, c)
    Vd = eq6_working_volume(Q, hrt)
    out = {"M": M, "TS": TS, "VS": VS, "Mw": Mw, "Q": Q, "Vd": Vd,
           "HRT": hrt, "digester_type": digester_type, "temp_c": temp_c}
    out["Vtot"] = eq7_total_volume(Vd, c) if digester_type in ("fixed", "balloon") else Vd
    if need_yield:
        y = yield_rate(hrt, c)
        out["y"] = y
        out["G"] = eq8_biogas(y, M)
        out["E_kWh"] = eq9_energy(out["G"], c)
        out["G_per_Vd"] = out["G"] / Vd
        out["G_per_VS"] = out["G"] / VS if VS else None
        if digester_type == "floating":
            out["Vg"] = eq12_gas_chamber(out["G"], gas_demand, c)
            if out["Vg"] < 0:
                warnings = (warnings or []) + [
                    f"Appliance gas demand ({gas_demand} m3/day) is larger than the "
                    f"daily biogas yield ({out['G']:.2f} m3/day); the gas chamber "
                    "volume from Eq. 12 is negative and is not physically meaningful."]
    else:
        out.update({"y": None, "G": None, "E_kWh": None})
    out["OLR"] = eq10_olr(VS, Vd)
    out["TS_slurry_pct"] = eq11_ts_slurry(TS, M, Mw)
    smin, smax = c["hrt_sizing_range"]
    out["HRT_in_table2_range"] = smin <= hrt <= smax
    out["warnings"] = warnings or []
    return out


def design(herd, hrt, digester_type="floating", temp_c=30, gas_demand=0.0,
           need_yield=True, c=CONSTANTS):
    """Main entry point. herd = {stage: heads}."""
    warnings = validate_inputs(herd, hrt, digester_type, temp_c, c, need_yield)
    if not isinstance(gas_demand, (int, float)) or gas_demand < 0:
        raise ValueError("Appliance gas demand must be a number >= 0 (m3/day).")
    M, TS, VS = eq1_3_loadings(herd, c)
    res = design_from_loads(M, TS, VS, hrt, digester_type, temp_c, gas_demand,
                            need_yield, c, warnings)
    res["herd"] = dict(herd)
    return res


def save_results(res, path="results.json"):
    """Save results with inputs, date and tool version (workflow step 11)."""
    with open(path, "w") as f:
        f.write(results_to_json(res))
    return path


def print_report(res):
    for w in res["warnings"]:
        print("WARNING:", w)
    rows = [("Manure M (kg/day)", "M"), ("TS (kg/day)", "TS"), ("VS (kg/day)", "VS"),
            ("Dilution water (kg/day)", "Mw"), ("Slurry Q (m3/day)", "Q"),
            ("Working volume Vd (m3)", "Vd"), ("Total volume (m3)", "Vtot"),
            ("Biogas G (m3/day)", "G"), ("Energy (kWh/day)", "E_kWh"),
            ("OLR (kg VS/m3.day)", "OLR"), ("Slurry TS (%)", "TS_slurry_pct"),
            ("G / Vd (m3/m3.day)", "G_per_Vd"), ("G / VS (m3/kg VS)", "G_per_VS")]
    for label, k in rows:
        v = res.get(k)
        print(f"{label:28s} {'n/a' if v is None else round(v, 3)}")


# ----------------------------------------------------------------------
# Sensitivity (herd size, VS content, HRT at +-10 % and +-20 %)
# ----------------------------------------------------------------------
def sensitivity(herd, hrt, digester_type="fixed", temp_c=30, c=CONSTANTS):
    """Returns list of rows. Herd size is scaled on loadings (continuous),
    VS scales VS only, HRT scales HRT. G is None when HRT is outside 25-50 d."""
    M0, TS0, VS0 = eq1_3_loadings(herd, c)
    rows = []
    for factor_name in ("Herd size", "VS content", "HRT"):
        for pct in (-20, -10, 0, 10, 20):
            f = 1 + pct / 100
            M, TS, VS, h = M0, TS0, VS0, hrt
            if factor_name == "Herd size":
                M, TS, VS = M0 * f, TS0 * f, VS0 * f
            elif factor_name == "VS content":
                VS = VS0 * f
            else:
                h = hrt * f
            try:
                r = design_from_loads(M, TS, VS, h, digester_type, temp_c, c=c)
                note = ""
            except ValueError:
                r = design_from_loads(M, TS, VS, h, digester_type, temp_c,
                                      need_yield=False, c=c)
                note = "HRT outside 25-50 d: yield not defined by Table B.4"
            rows.append({"factor": factor_name, "change_pct": pct, "Vd": r["Vd"],
                         "Vtot": r["Vtot"], "G": r["G"], "OLR": r["OLR"], "note": note})
    return rows


def sensitivity_figure(rows):
    """Matplotlib Figure of the sensitivity results (used by app.py)."""
    from matplotlib.figure import Figure
    fig = Figure(figsize=(11, 4))
    axes = fig.subplots(1, 2)
    for ax, key, title in ((axes[0], "Vd", "Working volume Vd (m3)"),
                           (axes[1], "G", "Biogas G (m3/day)")):
        for fac in ("Herd size", "VS content", "HRT"):
            pts = [(r["change_pct"], r[key]) for r in rows
                   if r["factor"] == fac and r[key] is not None]
            if pts:
                ax.plot(*zip(*pts), marker="o", label=fac)
        ax.set_xlabel("Change in parameter (%)")
        ax.set_title(title)
        ax.grid(alpha=.3)
        ax.legend()
    fig.tight_layout()
    return fig


def plot_sensitivity(rows, path="sensitivity.png"):
    sensitivity_figure(rows).savefig(path, dpi=150)
    return path


def results_to_json(res):
    """Results + date + tool version as a JSON string (for download)."""
    rec = dict(res)
    rec["date"] = datetime.datetime.now().isoformat(timespec="seconds")
    rec["tool_version"] = __version__
    return json.dumps(rec, indent=2)


# ----------------------------------------------------------------------
# Example: the mixed herd from Section 10 of the report
# ----------------------------------------------------------------------
EXAMPLE_HERD = {"Nursery": 40, "Growing": 60, "Finishing": 100,
                "Gestating sow": 15, "Sow with litter": 5, "Boar": 1}

# ----------------------------------------------------------------------
# USER INPUT
# ----------------------------------------------------------------------
def _ask(prompt, cast, check=None, default=None):
    """Console prompt that re-asks until the value is valid."""
    while True:
        raw = input(f"{prompt}" + (f" [{default}]" if default is not None else "") + ": ").strip()
        if raw == "" and default is not None:
            return default
        try:
            val = cast(raw)
            if check and not check(val):
                raise ValueError
            return val
        except ValueError:
            print("  Invalid entry, please try again.")


def run_console():
    """Asks for the inputs one by one (works in Colab, Jupyter or a terminal)."""
    print("=== Swine biogas digester calculator ===")
    print("Number of heads per production stage (whole numbers, 0 if none):")
    herd = {s: _ask(f"  {s}", int, lambda v: v >= 0, default=0) for s in STAGES}
    dtype = _ask("Digester type (floating / fixed / balloon)", str,
                 lambda v: v in DIGESTER_TYPES, default="fixed")
    need_yield = _ask("Estimate biogas yield? (y/n)", str,
                      lambda v: v in ("y", "n"), default="y") == "y"
    lo, hi = (25, 50) if need_yield else (15, 50)
    hrt = _ask(f"Retention time HRT in days ({lo}-{hi})", float,
               lambda v: lo <= v <= hi, default=25.0)
    temp = _ask("Ambient/digester temperature (deg C)", float,
                lambda v: -10 <= v <= 60, default=28.0)
    demand = 0.0
    if dtype == "floating" and need_yield:
        demand = _ask("Daily gas consumption of appliances (m3/day)", float,
                      lambda v: v >= 0, default=0.0)
    try:
        res = design(herd, hrt, dtype, temp, demand, need_yield)
    except ValueError as e:
        print("INPUT ERROR:", e)
        return None
    print_report(res)
    print("Saved:", save_results(res))
    return res


if __name__ == "__main__":
    run_console()