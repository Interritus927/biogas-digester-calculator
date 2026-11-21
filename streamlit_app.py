"""Streamlit interface for the swine biogas digester calculator.
Run with:  streamlit run app.py
All calculations are done by calculator.py; this file only handles input and display.
"""
import pandas as pd
import streamlit as st
import calculator as calc
import digester_plot

st.set_page_config(page_title="Swine Biogas Digester Calculator", page_icon="🐖", layout="wide")

st.title("Swine Biogas Digester Calculator")
st.caption("Digester sizing and biogas yield for swine waste. "
           "Method: PAES 413:2001 with stage-specific excretion from PAES 414-1:2002, Annex B.")

# ----------------------------------------------------------------------
# Inputs (sidebar)
# ----------------------------------------------------------------------
with st.sidebar:
    st.header("Inputs")

    for s in calc.STAGES:
        st.session_state.setdefault(f"heads_{s}", 0)

    def load_example():
        for s, n in calc.EXAMPLE_HERD.items():
            st.session_state[f"heads_{s}"] = n

    st.button("Load example herd", on_click=load_example)

    st.subheader("Heads per production stage")
    herd = {}
    for s in calc.STAGES:
        herd[s] = int(st.number_input(s, min_value=0, max_value=1_000_000, step=1,
                                      key=f"heads_{s}"))

    st.subheader("Design settings")
    dtype = st.selectbox("Digester type", calc.DIGESTER_TYPES, index=1,
                         format_func=str.capitalize)
    mode = st.radio("Calculation", ["Sizing and biogas yield", "Sizing only"],
                    help="Biogas yield needs an HRT of 25-50 days (AMTEC 2001, Table B.4). "
                         "Sizing alone accepts 15-50 days.")
    need_yield = mode == "Sizing and biogas yield"
    lo, hi = (25.0, 50.0) if need_yield else (15.0, 50.0)
    hrt = st.number_input(f"Retention time, HRT (days, {lo:.0f}-{hi:.0f})",
                          min_value=lo, max_value=hi, value=max(25.0, lo), step=1.0)
    temp = st.number_input("Temperature (°C)", min_value=-10.0, max_value=60.0,
                           value=28.0, step=1.0,
                           help="Mesophilic range is 20-40 °C. Yield is not corrected for temperature.")
    demand = 0.0
    if dtype == "floating" and need_yield:
        demand = st.number_input("Daily gas use of appliances (m³/day)",
                                 min_value=0.0, value=0.0, step=1.0)

# ----------------------------------------------------------------------
# Calculation
# ----------------------------------------------------------------------
if sum(herd.values()) == 0:
    st.info("Enter the number of heads for at least one stage in the sidebar, "
            "or click **Load example herd**.")
    st.stop()

try:
    res = calc.design(herd, hrt, dtype, temp, demand, need_yield)
except ValueError as e:
    st.error(f"Input error: {e}")
    st.stop()

for w in res["warnings"]:
    st.warning(w)

# ----------------------------------------------------------------------
# Results
# ----------------------------------------------------------------------
st.subheader("Digester design")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Working volume, Vd", f"{res['Vd']:.1f} m³")
if dtype in ("fixed", "balloon"):
    c2.metric("Total volume (with gas chamber)", f"{res['Vtot']:.1f} m³")
else:
    c2.metric("Digester volume", f"{res['Vtot']:.1f} m³")
if need_yield:
    c3.metric("Biogas yield, G", f"{res['G']:.1f} m³/day")
    c4.metric("Energy equivalent", f"{res['E_kWh']:.0f} kWh/day")
else:
    c3.metric("Biogas yield, G", "n/a")
    c4.metric("Energy equivalent", "n/a")
if need_yield and dtype == "floating":
    st.metric("Effective gas chamber volume, Vg", f"{res['Vg']:.1f} m³")

st.subheader("Loadings")
stage_rows = []
for s in calc.STAGES:
    n = herd[s]
    stage_rows.append({"Stage": s, "Heads": n,
                       "Manure (kg/day)": n * calc.CONSTANTS["manure"][s],
                       "TS (kg/day)": n * calc.CONSTANTS["ts"][s],
                       "VS (kg/day)": n * calc.CONSTANTS["vs"][s]})
stage_rows.append({"Stage": "Total", "Heads": sum(herd.values()),
                   "Manure (kg/day)": res["M"], "TS (kg/day)": res["TS"],
                   "VS (kg/day)": res["VS"]})
st.dataframe(pd.DataFrame(stage_rows).style.format(
    {"Manure (kg/day)": "{:.1f}", "TS (kg/day)": "{:.1f}", "VS (kg/day)": "{:.1f}"}),
    hide_index=True, width="stretch")

left, right = st.columns(2)
with left:
    st.subheader("Slurry")
    st.table(pd.DataFrame({
        "Value": [f"{res['Mw']:.1f}", f"{res['Q']:.3f}", f"{res['TS_slurry_pct']:.2f}"]},
        index=["Dilution water (kg/day)", "Slurry volume Q (m³/day)", "Slurry TS (%)"]))
with right:
    st.subheader("Checks")
    smin, smax = calc.CONSTANTS["hrt_sizing_range"]
    st.write(f"**OLR:** {res['OLR']:.2f} kg VS/m³·day")
    st.caption("For context, Tápparo et al. (2021) measured about 0.35 (covered lagoon) and about "
               "1.7 (CSTR). No pass/fail limit is applied.")
    if res["HRT_in_table2_range"]:
        st.write(f"**HRT:** within the {smin}-{smax} day range of AMTEC (2001), Table 2.")
    else:
        st.write(f"**HRT:** outside the {smin}-{smax} day range of AMTEC (2001), Table 2.")
    if need_yield:
        st.write(f"**Biogas per m³ digester:** {res['G_per_Vd']:.2f} m³/m³·day")
        st.write(f"**Biogas per kg VS:** {res['G_per_VS']:.2f} m³/kg VS")

# ----------------------------------------------------------------------
# Sensitivity
# ----------------------------------------------------------------------
st.subheader("Sensitivity analysis")
st.caption("Herd size, VS content, and HRT varied by ±10% and ±20%. "
           "Yield is not defined where HRT falls outside 25-50 days.")
rows = calc.sensitivity(herd, hrt, dtype, temp)
st.pyplot(calc.sensitivity_figure(rows))
with st.expander("Show sensitivity table"):
    st.dataframe(pd.DataFrame(rows).rename(columns={
        "factor": "Factor", "change_pct": "Change (%)", "Vd": "Vd (m³)",
        "Vtot": "Total volume (m³)", "G": "G (m³/day)", "OLR": "OLR", "note": "Note"}),
        hide_index=True, width="stretch")

# ----------------------------------------------------------------------
# Digester schematic
# ----------------------------------------------------------------------
st.subheader("Digester schematic")
if dtype == "balloon":
    ratio = st.slider("Assumed length-to-diameter ratio, L/D", 2.0, 8.0, 4.0, 0.5)
else:
    ratio = st.slider("Assumed height-to-diameter ratio, H/D", 0.5, 3.0, 1.0, 0.1)
st.pyplot(digester_plot.digester_figure(res, ratio))
st.caption("Schematic drawn to scale from the calculated volumes. The standard gives volumes, "
           "not dimensions, so the shape follows the ratio chosen above. It is not a "
           "structural design.")

# ----------------------------------------------------------------------
# Download
# ----------------------------------------------------------------------
st.subheader("Save results")
st.download_button("Download results (JSON)", calc.results_to_json(res),
                   file_name="results.json", mime="application/json")