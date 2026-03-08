from __future__ import annotations

from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
import biosteam as bst

from sabre.chemicals import create_chemicals
from sabre.systems.ad_biogas_system import create_ad_biogas_system

MW_CH4 = 16.042
MW_CO2 = 44.01
NM3_PER_KMOL = 22.414
CH4_LHV_MJ_PER_KG = 50.0
MJ_PER_MMBTU = 1055.056

# screening TEA assumptions
OPERATING_DAYS = 330.0
OPERATING_HOURS_PER_YEAR = 24.0 * OPERATING_DAYS
DISCOUNT_RATE = 0.10
PROJECT_LIFE_YEARS = 30
FIXED_OPEX_FRAC_OF_CAPEX = 0.03
ELECTRICITY_PRICE_PER_KWH = 0.08
HEAT_PRICE_PER_MJ = 0.006


def safe_float(x, default=float("nan")):
    try:
        if x is None:
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


def annualize_hourly(x, operating_days: float = OPERATING_DAYS) -> float:
    return safe_float(x, 0.0) * safe_float(operating_days, 0.0) * 24.0


def crf(i: float, n: float) -> float:
    return i * (1 + i) ** n / ((1 + i) ** n - 1)


def safe_imass(stream, ID):
    try:
        return float(stream.imass[ID])
    except Exception:
        return 0.0


def water_wt(stream) -> float:
    if stream is None or stream.F_mass <= 0 or "Water" not in stream.chemicals:
        return float("nan")
    return safe_float(stream.imass["Water"], 0.0) / safe_float(stream.F_mass, 1.0)


def get_ts_vs(stream):
    if getattr(stream, "phase", None) == "g":
        return 0.0, 0.0
    water = safe_imass(stream, "Water")
    ash = safe_imass(stream, "Ash")
    ts = max(safe_float(stream.F_mass, 0.0) - water, 0.0)
    vs = max(ts - ash, 0.0)
    return ts, vs


def ch4_kg_hr(stream) -> float:
    if stream is None or stream.F_mass <= 0 or "CH4" not in stream.chemicals:
        return 0.0
    return safe_float(stream.imass["CH4"], 0.0)


def ch4_kmol_hr(stream) -> float:
    return ch4_kg_hr(stream) / MW_CH4


def ch4_nm3_hr(stream) -> float:
    return ch4_kmol_hr(stream) * NM3_PER_KMOL


def ch4_mmbtu_hr(stream) -> float:
    mj_hr = ch4_kg_hr(stream) * CH4_LHV_MJ_PER_KG
    return mj_hr / MJ_PER_MMBTU


def gas_ch4_molfrac(stream) -> float:
    ch4 = safe_imass(stream, "CH4")
    co2 = safe_imass(stream, "CO2")
    n_ch4 = ch4 / MW_CH4 if ch4 > 0 else 0.0
    n_co2 = co2 / MW_CO2 if co2 > 0 else 0.0
    n_tot = n_ch4 + n_co2
    return n_ch4 / n_tot if n_tot > 0 else float("nan")


def total_unit_utility_cost_per_hr(system) -> float:
    total = 0.0
    for u in system.units:
        total += safe_float(getattr(u, "utility_cost", 0.0), 0.0)
    return total


def unit_purchase_cost(unit) -> float:
    if hasattr(unit, "purchase_costs") and getattr(unit, "purchase_costs"):
        try:
            return sum(safe_float(v, 0.0) for v in unit.purchase_costs.values())
        except Exception:
            pass
    return safe_float(getattr(unit, "purchase_cost", 0.0), 0.0)


def unit_installed_cost(unit) -> float:
    if hasattr(unit, "installed_costs") and getattr(unit, "installed_costs"):
        try:
            return sum(safe_float(v, 0.0) for v in unit.installed_costs.values())
        except Exception:
            pass
    return safe_float(getattr(unit, "installed_cost", 0.0), 0.0)


def total_installed_cost(system) -> float:
    return sum(unit_installed_cost(u) for u in system.units)


def total_purchase_cost(system) -> float:
    return sum(unit_purchase_cost(u) for u in system.units)


def total_heating_duty_MJ_hr(system) -> float:
    total_kJ_hr = 0.0
    for u in system.units:
        if hasattr(u, "heat_utilities"):
            for hu in u.heat_utilities:
                duty = safe_float(getattr(hu, "duty", 0.0), 0.0)
                if duty > 0:
                    total_kJ_hr += duty
    return total_kJ_hr / 1000.0


def save_barh(df: pd.DataFrame, label_col: str, value_col: str, title: str, outpath: Path, top_n: int = 10):
    d = df.copy()
    d = d.dropna(subset=[label_col, value_col])
    d = d.sort_values(value_col, ascending=False).head(top_n)

    plt.figure(figsize=(9, 6))
    plt.barh(d[label_col], d[value_col])
    plt.gca().invert_yaxis()
    plt.title(title)
    plt.xlabel(value_col)
    plt.tight_layout()
    plt.savefig(outpath, dpi=220)
    plt.close()


def save_case_bar(df: pd.DataFrame, x: str, y: str, title: str, ylabel: str, outpath: Path):
    d = df.copy().dropna(subset=[x, y])

    plt.figure(figsize=(8, 5))
    plt.bar(d[x], d[y])
    plt.title(title)
    plt.ylabel(ylabel)
    plt.xticks(rotation=20, ha="right")
    plt.tight_layout()
    plt.savefig(outpath, dpi=220)
    plt.close()


def run_case(
    case_name: str,
    vs_destruction: float | None = None,
    ch4_kg_per_kg_vs: float | None = None,
    ch4_molfrac: float | None = None,
) -> tuple[dict, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    chems = create_chemicals()
    bst.settings.set_thermo(chems)

    system = create_ad_biogas_system()
    fs = system.flowsheet

    AD = fs.unit.AD
    if vs_destruction is not None:
        AD.vs_destruction = vs_destruction
    if ch4_kg_per_kg_vs is not None:
        AD.ch4_kg_per_kg_vs = ch4_kg_per_kg_vs
    if ch4_molfrac is not None:
        AD.ch4_molfrac = ch4_molfrac

    system.simulate()

    PR = fs.unit.PR
    ML = fs.unit.ML
    UP = fs.unit.UP
    SP = fs.unit.SP

    streams = {
        "feed": PR.ins[0],
        "pressed_cake": PR.outs[0],
        "pressate": PR.outs[1],
        "milled_biomass": ML.outs[0],
        "milling_losses": ML.outs[1],
        "raw_biogas": AD.outs[0],
        "digestate": AD.outs[1],
        "biomethane": UP.outs[0],
        "offgas": UP.outs[1],
        "soil_amendment": SP.outs[0],
        "liquid_digestate": SP.outs[1],
    }

    subsystems = {
        "preprocessing": bst.System("preprocessing_tmp", path=(PR, ML)),
        "anaerobic_digestion": bst.System("ad_tmp", path=(AD,)),
        "upgrading": bst.System("upgrading_tmp", path=(UP,)),
        "digestate_handling": bst.System("digestate_tmp", path=(SP,)),
    }

    biomethane = streams["biomethane"]
    raw_biogas = streams["raw_biogas"]
    digestate = streams["digestate"]
    ad_feed = streams["milled_biomass"]

    ad_feed_ts, ad_feed_vs = get_ts_vs(ad_feed)
    digestate_ts, digestate_vs = get_ts_vs(digestate)

    installed_cost = total_installed_cost(system)
    purchase_cost = total_purchase_cost(system)
    annual_utility_cost = annualize_hourly(total_unit_utility_cost_per_hr(system), OPERATING_DAYS)
    annual_heat_cost = annualize_hourly(total_heating_duty_MJ_hr(system) * HEAT_PRICE_PER_MJ, OPERATING_DAYS)

    annualized_capex = installed_cost * crf(DISCOUNT_RATE, PROJECT_LIFE_YEARS)
    fixed_opex = FIXED_OPEX_FRAC_OF_CAPEX * installed_cost
    total_annual_cost = annualized_capex + annual_utility_cost + annual_heat_cost + fixed_opex

    biomethane_kg_hr = ch4_kg_hr(biomethane)
    biomethane_nm3_hr = ch4_nm3_hr(biomethane)
    biomethane_mmbtu_hr = ch4_mmbtu_hr(biomethane)

    biomethane_kg_yr = annualize_hourly(biomethane_kg_hr, OPERATING_DAYS)
    biomethane_nm3_yr = annualize_hourly(biomethane_nm3_hr, OPERATING_DAYS)
    biomethane_mmbtu_yr = annualize_hourly(biomethane_mmbtu_hr, OPERATING_DAYS)

    breakeven_per_kg = total_annual_cost / biomethane_kg_yr if biomethane_kg_yr > 0 else float("nan")
    breakeven_per_nm3 = total_annual_cost / biomethane_nm3_yr if biomethane_nm3_yr > 0 else float("nan")
    breakeven_per_mmbtu = total_annual_cost / biomethane_mmbtu_yr if biomethane_mmbtu_yr > 0 else float("nan")

    row = {
        "case": case_name,
        "vs_destruction": safe_float(AD.vs_destruction),
        "ch4_kg_per_kg_vs": safe_float(AD.ch4_kg_per_kg_vs),
        "raw_biogas_ch4_molfrac": gas_ch4_molfrac(raw_biogas),
        "biomethane_kg_hr": biomethane_kg_hr,
        "biomethane_nm3_hr": biomethane_nm3_hr,
        "biomethane_mmbtu_hr": biomethane_mmbtu_hr,
        "biomethane_kg_yr": biomethane_kg_yr,
        "biomethane_nm3_yr": biomethane_nm3_yr,
        "biomethane_mmbtu_yr": biomethane_mmbtu_yr,
        "AD_feed_F_mass_kg_hr": safe_float(ad_feed.F_mass),
        "AD_feed_TS_kg_hr": ad_feed_ts,
        "AD_feed_VS_kg_hr": ad_feed_vs,
        "digestate_F_mass_kg_hr": safe_float(digestate.F_mass),
        "digestate_TS_kg_hr": digestate_ts,
        "digestate_VS_kg_hr": digestate_vs,
        "VS_removed_kg_hr": ad_feed_vs - digestate_vs,
        "annual_utility_cost_$": annual_utility_cost,
        "annual_heat_cost_$": annual_heat_cost,
        "FOC_proxy_$": fixed_opex,
        "TCI_proxy_$": installed_cost,
        "purchase_cost_proxy_$": purchase_cost,
        "annualized_capex_$": annualized_capex,
        "total_annual_cost_$": total_annual_cost,
        "breakeven_$_per_kg_CH4": breakeven_per_kg,
        "breakeven_$_per_Nm3": breakeven_per_nm3,
        "breakeven_$_per_MMBtu": breakeven_per_mmbtu,
        "operating_days_per_year": OPERATING_DAYS,
        "project_years": PROJECT_LIFE_YEARS,
        "discount_rate": DISCOUNT_RATE,
    }

    unit_rows = []
    for u in system.units:
        unit_rows.append(
            {
                "case": case_name,
                "unit": u.ID,
                "line": type(u).__name__,
                "purchase_cost_$": unit_purchase_cost(u),
                "installed_cost_$": unit_installed_cost(u),
                "utility_cost_$_per_hr": safe_float(getattr(u, "utility_cost", 0.0), 0.0),
                "annual_utility_cost_$": annualize_hourly(
                    safe_float(getattr(u, "utility_cost", 0.0), 0.0),
                    OPERATING_DAYS,
                ),
            }
        )
    unit_df = pd.DataFrame(unit_rows)

    area_rows = []
    for area_name, subsystem in subsystems.items():
        units = list(subsystem.units)
        area_rows.append(
            {
                "case": case_name,
                "area": area_name,
                "purchase_cost_$": sum(unit_purchase_cost(u) for u in units),
                "installed_cost_$": sum(unit_installed_cost(u) for u in units),
                "annual_utility_cost_$": annualize_hourly(
                    sum(safe_float(getattr(u, "utility_cost", 0.0), 0.0) for u in units),
                    OPERATING_DAYS,
                ),
            }
        )
    area_df = pd.DataFrame(area_rows)

    tracked_chems = [
        "Water", "CH4", "CO2", "Glucan", "Xylan", "Alginate",
        "Fucoidan", "Mannitol", "Protein", "OtherSolids", "Ash"
    ]
    stream_rows = []
    for name, s in streams.items():
        if s is None:
            continue
        ts, vs = get_ts_vs(s)
        rec = {
            "case": case_name,
            "stream": name,
            "ID": s.ID,
            "phase": getattr(s, "phase", ""),
            "F_mass_kg_hr": safe_float(s.F_mass, 0.0),
            "water_wt_frac": water_wt(s),
            "TS_kg_hr": ts,
            "VS_kg_hr": vs,
        }
        for chem in tracked_chems:
            rec[f"{chem}_kg_hr"] = safe_float(s.imass[chem], 0.0) if chem in s.chemicals else 0.0
        stream_rows.append(rec)
    stream_df = pd.DataFrame(stream_rows)

    return row, unit_df, area_df, stream_df


def main():
    outdir = Path("results/ad/tea")
    figs = outdir / "figures"
    tables = outdir / "tables"
    figs.mkdir(parents=True, exist_ok=True)
    tables.mkdir(parents=True, exist_ok=True)

    cases = [
        ("basecase", dict(vs_destruction=0.50, ch4_kg_per_kg_vs=0.0555, ch4_molfrac=0.50)),
        ("low_performance", dict(vs_destruction=0.35, ch4_kg_per_kg_vs=0.0450, ch4_molfrac=0.50)),
        ("high_performance", dict(vs_destruction=0.60, ch4_kg_per_kg_vs=0.0700, ch4_molfrac=0.50)),
    ]

    summary_rows = []
    unit_dfs = []
    area_dfs = []
    stream_dfs = []

    for case_name, case_kwargs in cases:
        print(f"Running {case_name} ...")
        row, unit_df, area_df, stream_df = run_case(case_name=case_name, **case_kwargs)
        summary_rows.append(row)
        unit_dfs.append(unit_df)
        area_dfs.append(area_df)
        stream_dfs.append(stream_df)

        print(
            f"  Break-even = {row['breakeven_$_per_MMBtu']:.3f} $/MMBtu | "
            f"Biomethane = {row['biomethane_nm3_yr']:.0f} Nm3/yr | "
            f"TCI proxy = {row['TCI_proxy_$']:.0f} $"
        )

    summary_df = pd.DataFrame(summary_rows)
    units_df = pd.concat(unit_dfs, ignore_index=True)
    areas_df = pd.concat(area_dfs, ignore_index=True)
    streams_df = pd.concat(stream_dfs, ignore_index=True)

    summary_df.to_csv(tables / "tea_case_summary.csv", index=False)
    units_df.to_csv(tables / "unit_cost_breakdown.csv", index=False)
    areas_df.to_csv(tables / "area_cost_breakdown.csv", index=False)
    streams_df.to_csv(tables / "stream_summary.csv", index=False)

    save_case_bar(
        summary_df,
        x="case",
        y="breakeven_$_per_MMBtu",
        title="Break-even Biomethane Price by Case",
        ylabel="Break-even price ($/MMBtu)",
        outpath=figs / "breakeven_by_case.png",
    )

    save_case_bar(
        summary_df,
        x="case",
        y="annual_utility_cost_$",
        title="Annual Utility Cost by Case",
        ylabel="Annual utility cost ($/yr)",
        outpath=figs / "utility_by_case.png",
    )

    save_case_bar(
        summary_df,
        x="case",
        y="TCI_proxy_$",
        title="Installed Capital by Case",
        ylabel="Installed capital ($)",
        outpath=figs / "tci_by_case.png",
    )

    save_case_bar(
        summary_df,
        x="case",
        y="biomethane_nm3_yr",
        title="Annual Biomethane Production by Case",
        ylabel="Biomethane (Nm3/yr)",
        outpath=figs / "biomethane_by_case.png",
    )

    base_units = units_df[units_df["case"] == "basecase"].copy()
    base_areas = areas_df[areas_df["case"] == "basecase"].copy()

    costed_units = base_units[(base_units["installed_cost_$"] > 0) | (base_units["purchase_cost_$"] > 0)].copy()
    costed_units.to_csv(tables / "basecase_costed_units_only.csv", index=False)
    placeholders = base_units[(base_units["installed_cost_$"] == 0) & (base_units["purchase_cost_$"] == 0)].copy()
    placeholders.to_csv(tables / "basecase_placeholder_units.csv", index=False)

    save_barh(
        costed_units,
        label_col="unit",
        value_col="installed_cost_$",
        title="Top Installed-Cost Units (Base Case)",
        outpath=figs / "basecase_top_installed_cost_units.png",
        top_n=10,
    )

    save_barh(
        base_units[base_units["annual_utility_cost_$"] > 0],
        label_col="unit",
        value_col="annual_utility_cost_$",
        title="Top Utility-Cost Units (Base Case)",
        outpath=figs / "basecase_top_utility_cost_units.png",
        top_n=10,
    )

    save_barh(
        base_areas,
        label_col="area",
        value_col="installed_cost_$",
        title="Installed Cost by Area (Base Case)",
        outpath=figs / "basecase_installed_cost_by_area.png",
        top_n=10,
    )

    base = summary_df[summary_df["case"] == "basecase"].iloc[0]
    lines = [
        f"Break-even ($/MMBtu): {base['breakeven_$_per_MMBtu']:,.3f}",
        f"Break-even ($/Nm3): {base['breakeven_$_per_Nm3']:,.3f}",
        f"Biomethane (Nm3/yr): {base['biomethane_nm3_yr']:,.0f}",
        f"Biomethane (kg/yr): {base['biomethane_kg_yr']:,.0f}",
        f"Installed capital proxy ($): {base['TCI_proxy_$']:,.0f}",
        f"Annual utility cost ($/yr): {base['annual_utility_cost_$']:,.0f}",
        f"Annual heat cost ($/yr): {base['annual_heat_cost_$']:,.0f}",
        f"FOC proxy ($/yr): {base['FOC_proxy_$']:,.0f}",
        f"AD feed VS (kg/h): {base['AD_feed_VS_kg_hr']:,.0f}",
        f"VS removed (kg/h): {base['VS_removed_kg_hr']:,.0f}",
        f"Raw biogas CH4 mol frac: {base['raw_biogas_ch4_molfrac']:.3f}",
        f"Project years: {base['project_years']}",
        f"Operating days/year: {base['operating_days_per_year']}",
    ]

    plt.figure(figsize=(9, 5))
    plt.axis("off")
    plt.text(0.01, 0.98, "Base Case AD TEA Summary", fontsize=16, va="top")
    plt.text(0.01, 0.82, "\n".join(lines), fontsize=12, va="top", family="monospace")
    plt.tight_layout()
    plt.savefig(figs / "basecase_tea_summary.png", dpi=220, bbox_inches="tight")
    plt.close()

    print(f"\nSaved tables to: {tables.resolve()}")
    print(f"Saved figures to: {figs.resolve()}")


if __name__ == "__main__":
    main()