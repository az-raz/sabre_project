from __future__ import annotations

from pathlib import Path
import math
import pandas as pd
import matplotlib.pyplot as plt

from sabre.systems.ethanol_fermentation_system import create_ethanol_fermentation_system

DENSITY_ETHANOL_KG_L = 0.789
L_PER_GAL = 3.785


def safe_float(x, default=float("nan")):
    try:
        if x is None:
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


def ethanol_kg_hr(stream) -> float:
    if stream is None or stream.F_mass <= 0 or "Ethanol" not in stream.chemicals:
        return 0.0
    return safe_float(stream.imass["Ethanol"], 0.0)


def ethanol_gal_hr(stream) -> float:
    return ethanol_kg_hr(stream) / DENSITY_ETHANOL_KG_L / L_PER_GAL


def annualize_hourly(x, operating_days: float) -> float:
    return safe_float(x, 0.0) * safe_float(operating_days, 0.0) * 24.0


def water_wt(stream) -> float:
    if stream is None or stream.F_mass <= 0 or "Water" not in stream.chemicals:
        return float("nan")
    return safe_float(stream.imass["Water"], 0.0) / safe_float(stream.F_mass, 1.0)


def mesp_per_gal(tea, ethanol_stream) -> float:
    price_per_kg_product = safe_float(tea.solve_price(ethanol_stream), float("nan"))

    if ethanol_stream is None or ethanol_stream.F_mass <= 0:
        return float("nan")

    ethanol_mass = ethanol_kg_hr(ethanol_stream)
    if ethanol_mass <= 0:
        return float("nan")

    wt_ethanol = ethanol_mass / safe_float(ethanol_stream.F_mass)
    if wt_ethanol <= 0:
        return float("nan")

    price_per_kg_ethanol = price_per_kg_product / wt_ethanol
    return price_per_kg_ethanol * DENSITY_ETHANOL_KG_L * L_PER_GAL


def ethanol_stream_price_per_kg_from_gal(price_per_gal: float) -> float:
    """
    Convert $/gal pure ethanol -> $/kg pure ethanol.
    Since product stream is nearly pure ethanol in this placeholder dehydration,
    this is also a decent proxy for stream price.
    """
    return safe_float(price_per_gal, 0.0) / (DENSITY_ETHANOL_KG_L * L_PER_GAL)


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


def get_tea_metric(tea, name: str):
    return safe_float(getattr(tea, name, float("nan")), float("nan"))


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


def run_case(case_name: str, target_ethanol_price_per_gal: float | None = None, **kwargs) -> dict:
    system, tea, streams, subsystems = create_ethanol_fermentation_system(**kwargs)
    system.simulate()

    ethanol = streams["ethanol"]
    beer = streams["beer_raw"]

    operating_days = safe_float(getattr(tea, "operating_days", 330.0), 330.0)
    duration = getattr(tea, "duration", None)

    project_years = float("nan")
    if duration is not None and len(duration) == 2:
        project_years = duration[1] - duration[0]

    mesp = mesp_per_gal(tea, ethanol)
    implied_stream_price = safe_float(tea.solve_price(ethanol), float("nan"))

    target_stream_price = float("nan")
    npv_at_target_price = float("nan")
    if target_ethanol_price_per_gal is not None:
        target_stream_price = ethanol_stream_price_per_kg_from_gal(target_ethanol_price_per_gal)
        old_price = safe_float(getattr(ethanol, "price", 0.0), 0.0)
        ethanol.price = target_stream_price
        try:
            npv_at_target_price = get_tea_metric(tea, "NPV")
        finally:
            ethanol.price = old_price

    row = {
        "case": case_name,
        "include_feed_dewatering": kwargs.get("include_feed_dewatering", True),
        "MESP_$/gal": mesp,
        "target_ethanol_price_$/gal": target_ethanol_price_per_gal if target_ethanol_price_per_gal is not None else float("nan"),
        "target_ethanol_stream_price_$/kg": target_stream_price,
        "NPV_at_target_price_$": npv_at_target_price,
        "ethanol_kg_hr": ethanol_kg_hr(ethanol),
        "ethanol_gal_hr": ethanol_gal_hr(ethanol),
        "ethanol_gal_yr": annualize_hourly(ethanol_gal_hr(ethanol), operating_days),
        "beer_F_mass_kg_hr": safe_float(beer.F_mass, float("nan")),
        "beer_water_wt_frac": water_wt(beer),
        "ferm_feed_F_mass_kg_hr": safe_float(streams["dewatered_cake"].F_mass, float("nan")),
        "ferm_feed_water_wt_frac": water_wt(streams["dewatered_cake"]),
        "annual_utility_cost_$": annualize_hourly(total_unit_utility_cost_per_hr(system), operating_days),
        "VOC_$": get_tea_metric(tea, "VOC"),
        "FOC_$": get_tea_metric(tea, "FOC"),
        "TCI_$": get_tea_metric(tea, "TCI"),
        "FCI_$": get_tea_metric(tea, "FCI"),
        "WC_$": get_tea_metric(tea, "WC"),
        "IRR": get_tea_metric(tea, "IRR"),
        "NPV_break_even_$": get_tea_metric(tea, "NPV"),
        "product_price_break_even_$_per_kg_stream": implied_stream_price,
        "tea_duration": str(duration),
        "project_years": project_years,
        "operating_days_per_year": operating_days,
    }

    # unit-level capital and utility
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
                "annual_utility_cost_$": annualize_hourly(safe_float(getattr(u, "utility_cost", 0.0), 0.0), operating_days),
            }
        )
    unit_df = pd.DataFrame(unit_rows)

    # area-level breakdown
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
                    operating_days,
                ),
            }
        )

    subsystem_unit_ids = {u.ID for s in subsystems.values() for u in s.units}
    other_units = [u for u in system.units if u.ID not in subsystem_unit_ids]
    area_rows.append(
        {
            "case": case_name,
            "area": "other_system_units",
            "purchase_cost_$": sum(unit_purchase_cost(u) for u in other_units),
            "installed_cost_$": sum(unit_installed_cost(u) for u in other_units),
            "annual_utility_cost_$": annualize_hourly(
                sum(safe_float(getattr(u, "utility_cost", 0.0), 0.0) for u in other_units),
                operating_days,
            ),
        }
    )
    area_df = pd.DataFrame(area_rows)

    # stream summary
    tracked_chems = ["Water", "Ethanol", "Glucose", "Xylose", "Alginate", "Fucoidan", "Mannitol", "Ash"]
    stream_rows = []
    for name, s in streams.items():
        if s is None:
            continue
        rec = {
            "case": case_name,
            "stream": name,
            "ID": s.ID,
            "F_mass_kg_hr": safe_float(s.F_mass, 0.0),
            "water_wt_frac": water_wt(s),
        }
        for chem in tracked_chems:
            rec[f"{chem}_kg_hr"] = safe_float(s.imass[chem], 0.0) if chem in s.chemicals else 0.0
        stream_rows.append(rec)
    stream_df = pd.DataFrame(stream_rows)

    return row, unit_df, area_df, stream_df


def main():
    target_ethanol_price_per_gal = 3.50

    outdir = Path("results/tea")
    figs = outdir / "figures"
    tables = outdir / "tables"
    figs.mkdir(parents=True, exist_ok=True)
    tables.mkdir(parents=True, exist_ok=True)

    base_kwargs = dict(
        debug=False,
        feedstock_price=0.0,
        feed_total_flow_kg_hr=625000,
        feed_dewatering_moisture=0.60,
        keep_feed_solubles=0.90,
        X_alginate_to_sugars=0.90,
        X_fucoidan_to_sugars=0.90,
        X_mannitol_to_sugars=0.95,
        frac_seaweed_sugars_to_xylose=0.0,
        strip_ferm_aux_water=True,
    )

    cases = [
        ("one_dewatering_basecase", dict(include_feed_dewatering=True)),
        ("no_dewatering", dict(include_feed_dewatering=False)),
    ]

    summary_rows = []
    unit_dfs = []
    area_dfs = []
    stream_dfs = []

    for case_name, case_kwargs in cases:
        kwargs = dict(base_kwargs)
        kwargs.update(case_kwargs)

        print(f"Running {case_name} ...")
        row, unit_df, area_df, stream_df = run_case(
            case_name=case_name,
            target_ethanol_price_per_gal=target_ethanol_price_per_gal,
            **kwargs,
        )
        summary_rows.append(row)
        unit_dfs.append(unit_df)
        area_dfs.append(area_df)
        stream_dfs.append(stream_df)

        print(
            f"  MESP = {row['MESP_$/gal']:.3f} $/gal | "
            f"NPV @ {target_ethanol_price_per_gal:.2f} $/gal = {row['NPV_at_target_price_$']:.2f} | "
            f"Ethanol = {row['ethanol_gal_yr']:.2f} gal/yr"
        )

    summary_df = pd.DataFrame(summary_rows)
    units_df = pd.concat(unit_dfs, ignore_index=True)
    areas_df = pd.concat(area_dfs, ignore_index=True)
    streams_df = pd.concat(stream_dfs, ignore_index=True)

    summary_df.to_csv(tables / "tea_case_summary.csv", index=False)
    units_df.to_csv(tables / "unit_cost_breakdown.csv", index=False)
    areas_df.to_csv(tables / "area_cost_breakdown.csv", index=False)
    streams_df.to_csv(tables / "stream_summary.csv", index=False)

    # case comparison figures
    save_case_bar(
        summary_df,
        x="case",
        y="MESP_$/gal",
        title="MESP by Case",
        ylabel="MESP ($/gal)",
        outpath=figs / "mesp_by_case.png",
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
        y="TCI_$",
        title="Total Capital Investment by Case",
        ylabel="TCI ($)",
        outpath=figs / "tci_by_case.png",
    )

    save_case_bar(
        summary_df,
        x="case",
        y="NPV_at_target_price_$",
        title=f"NPV by Case at ${target_ethanol_price_per_gal:.2f}/gal Ethanol",
        ylabel="NPV ($)",
        outpath=figs / "npv_by_case_target_price.png",
    )

    # one-dewatering basecase detailed plots
    base_units = units_df[units_df["case"] == "one_dewatering_basecase"].copy()
    base_areas = areas_df[areas_df["case"] == "one_dewatering_basecase"].copy()

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

    # small presentation-friendly summary table as image
    base = summary_df[summary_df["case"] == "one_dewatering_basecase"].iloc[0]
    lines = [
        f"MESP ($/gal): {base['MESP_$/gal']:,.3f}",
        f"Ethanol production (gal/yr): {base['ethanol_gal_yr']:,.0f}",
        f"TCI ($): {base['TCI_$']:,.0f}",
        f"Annual utilities ($/yr): {base['annual_utility_cost_$']:,.0f}",
        f"VOC ($/yr): {base['VOC_$']:,.0f}",
        f"FOC ($/yr): {base['FOC_$']:,.0f}",
        f"Beer water wt frac: {base['beer_water_wt_frac']:.4f}",
        f"NPV at ${target_ethanol_price_per_gal:.2f}/gal ($): {base['NPV_at_target_price_$']:,.0f}",
        f"TEA duration: {base['tea_duration']}",
        f"Project years: {base['project_years']}",
        f"Operating days/year: {base['operating_days_per_year']}",
    ]

    plt.figure(figsize=(9, 5))
    plt.axis("off")
    plt.text(0.01, 0.98, "Base Case TEA Summary", fontsize=16, va="top")
    plt.text(0.01, 0.82, "\n".join(lines), fontsize=12, va="top", family="monospace")
    plt.tight_layout()
    plt.savefig(figs / "basecase_tea_summary.png", dpi=220, bbox_inches="tight")
    plt.close()

    print(f"\nSaved tables to: {tables.resolve()}")
    print(f"Saved figures to: {figs.resolve()}")


if __name__ == "__main__":
    main()