from __future__ import annotations

"""
Integrated-system TEA figures

1) Runs the alpha sweep for several integrated-system scenarios
2) Saves one CSV per scenario plus a summary CSV of the best point in each case
3) Plots 4 figures:
   - Figure 1: Alpha sweep across four scenario cases (2x2 panels, NPV vs alpha)
   - Figure 2: Best-case scenario comparison
   - Figure 3: Cost metrics at selected alpha values (base scenario)
   - Figure 4: Annual product outputs vs alpha (base scenario)
"""

import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import biosteam as bst
import matplotlib.pyplot as plt
import pandas as pd

# -----------------------------------------------------------------------------
# Import integrated TEA utilities
# -----------------------------------------------------------------------------
THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from integrated_tea import (
    BIOMETHANE_MARKET_MMBTU,
    OIL_MARKET_USD_PER_KG,
    _apply_stream_prices,
    _patch_ev607,
    _wire_oil_reagent,
    run_alpha_sweep,
)
from sabre.chemicals import set_thermo
from sabre.systems.integrated_system import create_integrated_biorefinery
from sabre.tea import make_baseline_tea


# -----------------------------------------------------------------------------
# Scenario definitions --> trying to find worst/best cases
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class Scenario:
    name: str
    label: str
    group_label: str
    pretreatment_label: str
    feed_price: float
    pretreatment_case: str
    biostimulant_price: float
    market_mmbtu: float = BIOMETHANE_MARKET_MMBTU
    market_oil: float = OIL_MARKET_USD_PER_KG


SCENARIOS: tuple[Scenario, ...] = (
    # 1) zero feed cost, zero biostimulant
    Scenario(
        name="pm_feed0_bio0",
        label="Press and mill | feed $0/kg | biostim $0/kg",
        group_label="Feed $0/kg\nBiostim $0/kg",
        pretreatment_label="Press and mill",
        feed_price=0.00,
        pretreatment_case="press_mill_only",
        biostimulant_price=0.00,
    ),
    Scenario(
        name="pe_feed0_bio0",
        label="PE | feed $0/kg | biostim $0/kg",
        group_label="Feed $0/kg\nBiostim $0/kg",
        pretreatment_label="PE",
        feed_price=0.00,
        pretreatment_case="combined_PE",
        biostimulant_price=0.00,
    ),

    # 2) tipping fees, zero biostimulant
    Scenario(
        name="pm_tip_bio0",
        label="Press and mill | tipping fee | biostim $0/kg",
        group_label="Tipping fee\nBiostim $0/kg",
        pretreatment_label="Press and mill",
        feed_price=-0.02,
        pretreatment_case="press_mill_only",
        biostimulant_price=0.00,
    ),
    Scenario(
        name="pe_tip_bio0",
        label="PE | tipping fee | biostim $0/kg",
        group_label="Tipping fee\nBiostim $0/kg",
        pretreatment_label="PE",
        feed_price=-0.02,
        pretreatment_case="combined_PE",
        biostimulant_price=0.00,
    ),

    # 3) zero feed cost, $1 biostimulant
    Scenario(
        name="pm_feed0_bio1",
        label="Press and mill | feed $0/kg | biostim $1/kg",
        group_label="Feed $0/kg\nBiostim $1/kg",
        pretreatment_label="Press and mill",
        feed_price=0.00,
        pretreatment_case="press_mill_only",
        biostimulant_price=1.00,
    ),
    Scenario(
        name="pe_feed0_bio1",
        label="PE | feed $0/kg | biostim $1/kg",
        group_label="Feed $0/kg\nBiostim $1/kg",
        pretreatment_label="PE",
        feed_price=0.00,
        pretreatment_case="combined_PE",
        biostimulant_price=1.00,
    ),

    # 4) tipping fees, $1 biostimulant
    Scenario(
        name="pm_tip_bio1",
        label="Press and mill | tipping fee | biostim $1/kg",
        group_label="Tipping fee\nBiostim $1/kg",
        pretreatment_label="Press and mill",
        feed_price=-0.02,
        pretreatment_case="press_mill_only",
        biostimulant_price=1.00,
    ),
    Scenario(
        name="pe_tip_bio1",
        label="PE | tipping fee | biostim $1/kg",
        group_label="Tipping fee\nBiostim $1/kg",
        pretreatment_label="PE",
        feed_price=-0.02,
        pretreatment_case="combined_PE",
        biostimulant_price=1.00,
    ),
)

BASE_SCENARIO_NAME = "pm_feed0_bio0"
OUTPUT_DIR = Path("results") / "integrated_figures"
CSV_DIR = OUTPUT_DIR / "csv"
FIG_DIR = OUTPUT_DIR / "figures"


# -----------------------------------------------------------------------------
# Helper functions
# -----------------------------------------------------------------------------
def _safe_operating_hours(tea) -> float:
    if hasattr(tea, "operating_hours"):
        return float(tea.operating_hours)
    if hasattr(tea, "operating_days"):
        return float(tea.operating_days) * 24.0
    return 330.0 * 24.0


def _crf(rate: float, years: int) -> float:
    if rate == 0:
        return 1.0 / years
    return rate * (1.0 + rate) ** years / ((1.0 + rate) ** years - 1.0)


def _build_case_metrics(
    alpha: float,
    *,
    feed_price: float,
    pretreatment_case: str,
    biostimulant_price: float,
) -> dict[str, float]:
    """Rebuild one alpha case and return detailed metrics for plotting."""
    bst.main_flowsheet.clear()
    set_thermo()

    sys, streams, units, _ = create_integrated_biorefinery(
        alpha=alpha,
        pretreatment_case=pretreatment_case,
    )
    streams["feed"].price = feed_price
    sys.simulate()

    _patch_ev607()
    _apply_stream_prices(streams, biostimulant_price)
    _wire_oil_reagent(streams, units)

    tea = make_baseline_tea(sys)
    op_hours = _safe_operating_hours(tea)

    duration = getattr(tea, "duration", (0, 30))
    if isinstance(duration, tuple) and len(duration) == 2:
        years = int(duration[1] - duration[0])
    else:
        years = 30
    rate = float(getattr(tea, "IRR", 0.10) or 0.10)
    annualized_capital = float(tea.TCI) * _crf(rate, max(years, 1))

    biomethane = streams.get("biomethane")
    backend_oil = streams.get("backend_oil")
    biostimulant = streams.get("biostimulant_membrane_concentrate")

    methane_kgph = 0.0
    methane_mmbtu_per_yr = 0.0
    if biomethane is not None and float(biomethane.F_mass) > 0:
        methane_kgph = float(biomethane.imass["Methane"])
        methane_mmbtu_per_yr = methane_kgph * 0.0526 * op_hours

    oil_t_per_yr = 0.0
    if backend_oil is not None and float(backend_oil.F_mass) > 0:
        oil_kgph = float(backend_oil.imass["MicrobialOil"])
        oil_t_per_yr = oil_kgph * op_hours / 1000.0

    biostim_t_per_yr = 0.0
    if biostimulant is not None and float(biostimulant.F_mass) > 0:
        biostim_kgph = float(biostimulant.F_mass)
        biostim_t_per_yr = biostim_kgph * op_hours / 1000.0

    return {
        "alpha": alpha,
        "TCI_M": float(tea.TCI) / 1e6,
        "VOC_M_per_yr": float(tea.VOC) / 1e6,
        "FOC_M_per_yr": float(tea.FOC) / 1e6,
        "annualized_capital_M_per_yr": annualized_capital / 1e6,
        "methane_kgph": methane_kgph,
        "methane_MMBtu_per_yr": methane_mmbtu_per_yr,
        "microbial_oil_t_per_yr": oil_t_per_yr,
        "biostimulant_t_per_yr": biostim_t_per_yr,
    }


def _best_row(df: pd.DataFrame) -> pd.Series:
    valid = df[df["ok"]].copy()
    valid = valid[pd.notna(valid["combined_npv_M"])]
    if valid.empty:
        raise RuntimeError("No valid rows found when selecting best alpha.")
    idx = valid["combined_npv_M"].idxmax()
    return valid.loc[idx]


def _save_dataframe(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    print(f"Saved CSV: {path}")


# -----------------------------------------------------------------------------
# Plotting
# -----------------------------------------------------------------------------
def plot_alpha_sweep_four_cases(all_results: dict[str, pd.DataFrame], outpath: Path) -> None:
    """
    Single-panel alpha sweep — one line per scenario (4 series).
    Press-mill only; pretreatment comparison dropped.
    Legend outside right; optimal-alpha dotted vline per series.
    """
    import matplotlib.ticker as mticker

    TEXT   = "#2C2C2A"
    C_GRID = "#E8E6DE"

    # 4 series: feed cost × biostimulant price (press-mill only)
    SERIES = [
        {
            "group":  "Feed $0/kg\nBiostim $0/kg",
            "label":  "Near-zero feed · Biostim $0/kg",
            "color":  "#1f77b4",
            "ls":     "-",
            "marker": "o",
        },
        {
            "group":  "Tipping fee\nBiostim $0/kg",
            "label":  "Tipping fee · Biostim $0/kg",
            "color":  "#ff7f0e",
            "ls":     "--",
            "marker": "^",
        },
        {
            "group":  "Feed $0/kg\nBiostim $1/kg",
            "label":  "Near-zero feed · Biostim $1/kg",
            "color":  "#2ca02c",
            "ls":     "-",
            "marker": "s",
        },
        {
            "group":  "Tipping fee\nBiostim $1/kg",
            "label":  "Tipping fee · Biostim $1/kg",
            "color":  "#d62728",
            "ls":     "--",
            "marker": "D",
        },
    ]

    fig, ax = plt.subplots(figsize=(9, 5.5))
    fig.subplots_adjust(left=0.10, right=0.72, top=0.88, bottom=0.12)

    for sc in SERIES:
        # find the press-mill dataframe for this group
        df = None
        for candidate in all_results.values():
            if (candidate["group_label"].iloc[0] == sc["group"] and
                    candidate["pretreatment_label"].iloc[0] == "Press and mill"):
                df = candidate
                break
        if df is None:
            continue

        valid = df[df["ok"] & df["combined_npv_M"].notna()]
        ax.plot(valid["alpha"], valid["combined_npv_M"],
                color=sc["color"], ls=sc["ls"], lw=1.6,
                marker=sc["marker"], markersize=5,
                markerfacecolor="white", markeredgewidth=1.4,
                markeredgecolor=sc["color"],
                label=sc["label"], zorder=3)

        try:
            best = _best_row(df)
            ax.axvline(best["alpha"], color=sc["color"], ls=":",
                       lw=0.9, zorder=2, alpha=0.6)
        except Exception:
            pass

    # NPV = 0 reference
    ax.axhline(0, color="#555555", lw=0.8, ls="-", zorder=1)
    ax.text(1.01, 0, "NPV = 0", transform=ax.get_yaxis_transform(),
            va="center", fontsize=7.5, color="#555555")

    ax.set_xlabel("\u03b1  (fraction of milled biomass to biomethane pathway)",
                  fontsize=10, color=TEXT)
    ax.set_ylabel("Combined NPV  ($M)", fontsize=10, color=TEXT)
    ax.set_title(
        "Integrated biorefinery NPV vs. pathway split (\u03b1)\n"
        "Oil $5.00/kg  \u00b7  Biomethane $3.00/MMBtu  \u00b7  Press-mill pretreatment",
        fontsize=10.5, color=TEXT, pad=8,
    )

    ax.set_xlim(-0.03, 1.03)
    ax.xaxis.set_major_locator(mticker.MultipleLocator(0.2))
    ax.xaxis.set_minor_locator(mticker.MultipleLocator(0.1))
    ax.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda v, _: f"${v:,.0f}M"))
    ax.tick_params(labelsize=9)
    ax.grid(False)
    ax.set_facecolor("white")
    for spine in ax.spines.values():
        spine.set_linewidth(1.0)
        spine.set_color("#1a1a1a")

    leg = ax.legend(title="Scenario", title_fontsize=8.5,
                    fontsize=8.5, loc="upper left",
                    bbox_to_anchor=(1.02, 1.0),
                    frameon=True, framealpha=0.95,
                    edgecolor="#D3D1C7", ncol=1,
                    handlelength=2.4, borderaxespad=0)
    leg.get_title().set_fontweight("bold")

    outpath.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(outpath, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Saved figure: {outpath}")

def plot_scenario_comparison(summary_df: pd.DataFrame, outpath: Path) -> None:
    """
    Best-NPV bar chart only — one bar per scenario, press-mill pretreatment.
    Optimal alpha annotated inside each bar.
    """
    import numpy as np
    import matplotlib.ticker as mticker

    TEXT   = "#2C2C2A"
    C_GRID = "#E8E6DE"

    groups = [
        "Feed $0/kg\nBiostim $0/kg",
        "Tipping fee\nBiostim $0/kg",
        "Feed $0/kg\nBiostim $1/kg",
        "Tipping fee\nBiostim $1/kg",
    ]
    xlabels = [
        "Near-zero feed\nBiostim $0/kg",
        "Tipping fee\nBiostim $0/kg",
        "Near-zero feed\nBiostim $1/kg",
        "Tipping fee\nBiostim $1/kg",
    ]
    COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"]

    pm = (summary_df[summary_df["pretreatment_label"] == "Press and mill"]
          .set_index("group_label").loc[groups])

    x = np.arange(len(groups))

    fig, ax = plt.subplots(figsize=(8, 5))

    bars = ax.bar(x, pm["best_npv_M"], width=0.5,
                  color=COLORS, alpha=0.88,
                  zorder=3, linewidth=0.5, edgecolor="white")

    ax.axhline(0, color="#555555", lw=0.9, zorder=2)

    # Annotate optimal alpha inside bars
    for bar, (_, row) in zip(bars, pm.iterrows()):
        a   = row["optimal_alpha"]
        h   = bar.get_height()
        yc  = bar.get_y() + h / 2
        ax.text(bar.get_x() + bar.get_width() / 2, yc,
                f"\u03b1 = {a:.1f}",
                ha="center", va="center",
                fontsize=9, color="white", fontweight="bold")

    ax.set_ylabel("Best combined NPV  ($M)", fontsize=10, color=TEXT)
    ax.set_title(
        "Best integrated-system NPV at optimal \u03b1\n"
        "Oil $5.00/kg  \u00b7  Biomethane $3.00/MMBtu  \u00b7  Press-mill pretreatment",
        fontsize=10.5, color=TEXT, pad=8,
    )
    ax.set_xticks(x)
    ax.set_xticklabels(xlabels, fontsize=9)
    ax.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda v, _: f"${v:,.0f}M"))
    ax.tick_params(labelsize=9)
    ax.set_facecolor("white")
    ax.grid(False)
    ax.set_axisbelow(False)
    for spine in ax.spines.values():
        spine.set_linewidth(1.0)
        spine.set_color("#1a1a1a")

    fig.tight_layout(pad=1.2)
    outpath.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(outpath, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Saved figure: {outpath}")

def plot_cost_metrics(selected_df: pd.DataFrame, outpath: Path) -> None:
    """Cost breakdown at selected alpha values (thesis quality)."""
    import matplotlib.ticker as mticker

    C_VOC  = "#185FA5"
    C_FOC  = "#9FE1CB"
    C_TCI  = "#BA7517"
    C_GRID = "#E8E6DE"
    TEXT   = "#2C2C2A"

    labels = [f"α = {a:.1f}" for a in selected_df["alpha"]]
    x = range(len(labels))

    fig, axes = plt.subplots(2, 1, figsize=(7, 6.5), constrained_layout=True)

    def _style(ax):
        ax.set_facecolor("white")
        ax.grid(False)
        ax.set_axisbelow(False)
        for spine in ax.spines.values():
            spine.set_linewidth(1.0); spine.set_color("#1a1a1a")
        ax.tick_params(labelsize=9)

    # Stacked VOC + FOC
    axes[0].bar(labels, selected_df["VOC_M_per_yr"], color=C_VOC,
                alpha=0.85, label="VOC", zorder=3, edgecolor="white", lw=0.5)
    axes[0].bar(labels, selected_df["FOC_M_per_yr"],
                bottom=selected_df["VOC_M_per_yr"],
                color=C_FOC, alpha=0.85, label="FOC",
                zorder=3, edgecolor="white", lw=0.5)
    axes[0].set_ylabel("Annual operating cost  ($M/yr)", fontsize=9.5, color=TEXT)
    axes[0].yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda v, _: f"${v:,.0f}M"))
    leg = axes[0].legend(fontsize=8.5, frameon=True, framealpha=0.95,
                          edgecolor="#D3D1C7")
    axes[0].set_title("Cost metrics at selected α values (base scenario)",
                       fontsize=10, color=TEXT, pad=6)
    _style(axes[0])

    # TCI
    axes[1].bar(labels, selected_df["TCI_M"], color=C_TCI,
                alpha=0.85, zorder=3, edgecolor="white", lw=0.5)
    axes[1].set_ylabel("Total capital investment  ($M)", fontsize=9.5, color=TEXT)
    axes[1].set_xlabel("Pathway split  (α)", fontsize=9.5, color=TEXT)
    axes[1].yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda v, _: f"${v:,.0f}M"))
    _style(axes[1])

    outpath.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(outpath, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Saved figure: {outpath}")


def plot_product_outputs(full_metrics_df: pd.DataFrame, outpath: Path) -> None:
    """Annual product rates vs alpha"""
    import matplotlib.ticker as mticker

    C_CH4  = "#185FA5"
    C_OIL  = "#0F6E56"
    C_BIO  = "#BA7517"
    C_GRID = "#E8E6DE"
    TEXT   = "#2C2C2A"

    x = full_metrics_df["alpha"]

    fig, axes = plt.subplots(3, 1, figsize=(7.5, 8.5),
                              sharex=True, constrained_layout=True)

    def _style(ax):
        ax.set_facecolor("white")
        ax.grid(False)
        ax.set_axisbelow(False)
        for spine in ax.spines.values():
            spine.set_linewidth(1.0); spine.set_color("#1a1a1a")
        ax.tick_params(labelsize=9)

    kw = dict(lw=1.6, markersize=5, markerfacecolor="white",
              markeredgewidth=1.3, zorder=3)

    axes[0].plot(x, full_metrics_df["methane_MMBtu_per_yr"] / 1e6,
                 color=C_CH4, marker="o", markeredgecolor=C_CH4, **kw)
    axes[0].set_ylabel("Biomethane\n(MMBtu/yr × 10⁶)", fontsize=9, color=TEXT)
    axes[0].set_title("Annual product rates vs. pathway split (α)\n"
                       "(base scenario: press-mill, near-zero feed, biostimulant $0/kg)",
                       fontsize=10, color=TEXT, pad=6)
    _style(axes[0])

    axes[1].plot(x, full_metrics_df["microbial_oil_t_per_yr"] / 1e3,
                 color=C_OIL, marker="s", markeredgecolor=C_OIL, **kw)
    axes[1].set_ylabel("Microbial oil\n(kt/yr)", fontsize=9, color=TEXT)
    _style(axes[1])

    axes[2].plot(x, full_metrics_df["biostimulant_t_per_yr"] / 1e3,
                 color=C_BIO, marker="^", markeredgecolor=C_BIO, **kw)
    axes[2].set_ylabel("Biostimulant\n(kt/yr)", fontsize=9, color=TEXT)
    axes[2].set_xlabel("α  (fraction of milled biomass to biomethane pathway)",
                        fontsize=9.5, color=TEXT)
    axes[2].set_xlim(-0.03, 1.03)
    _style(axes[2])

    outpath.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(outpath, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Saved figure: {outpath}")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main(scenarios: Iterable[Scenario] = SCENARIOS) -> None:
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    all_results: dict[str, pd.DataFrame] = {}
    summary_rows: list[dict[str, float | str]] = []

    # 1) Run alpha sweeps and save CSVs
    for scenario in scenarios:
        print("\n" + "=" * 90)
        print(f"Running scenario: {scenario.label}")
        print("=" * 90)

        results = run_alpha_sweep(
            feed_price=scenario.feed_price,
            case_label=scenario.name,
            pretreatment_case=scenario.pretreatment_case,
            biostimulant_price=scenario.biostimulant_price,
            market_mmbtu=scenario.market_mmbtu,
            market_oil=scenario.market_oil,
            print_summary=True,
        )

        df = pd.DataFrame(results)
        df["scenario_name"] = scenario.name
        df["scenario_label"] = scenario.label
        df["group_label"] = scenario.group_label
        df["pretreatment_label"] = scenario.pretreatment_label

        all_results[scenario.name] = df
        _save_dataframe(df, CSV_DIR / f"alpha_sweep_{scenario.name}.csv")

        best = _best_row(df)
        summary_rows.append(
            {
                "scenario_name": scenario.name,
                "scenario_label": scenario.label,
                "group_label": scenario.group_label,
                "pretreatment_label": scenario.pretreatment_label,
                "optimal_alpha": float(best["alpha"]),
                "best_npv_M": float(best["combined_npv_M"]),
                "best_tci_M": float(best["tci_M"]),
                "best_voc_M": float(best["voc_M"]),
                "best_foc_M": float(best["foc_M"]),
                "best_biomethane_msp_mmbtu": float(best["msp_biomethane_mmbtu"])
                if pd.notna(best["msp_biomethane_mmbtu"]) else math.nan,
                "best_oil_msp_usd_per_kg": float(best["msp_oil_usd_per_kg"])
                if pd.notna(best["msp_oil_usd_per_kg"]) else math.nan,
            }
        )

    summary_df = pd.DataFrame(summary_rows)
    _save_dataframe(summary_df, CSV_DIR / "scenario_summary.csv")

    # 2) Figure 1: alpha sweep across four paired cases
    plot_alpha_sweep_four_cases(
        all_results,
        FIG_DIR / "figure1_alpha_sweep_four_cases.png",
    )

    # 3) Figure 2: scenario comparison
    plot_scenario_comparison(summary_df, FIG_DIR / "figure2_scenario_comparison.png")

    # 4) Rebuild selected alpha values for cost metrics and product outputs
    base_scenario = next(s for s in scenarios if s.name == BASE_SCENARIO_NAME)
    base_df = all_results[BASE_SCENARIO_NAME]

    base_best_alpha = float(_best_row(base_df)["alpha"])
    selected_alphas = sorted({0.0, 0.5, 1.0, base_best_alpha})

    selected_metrics = []
    full_metrics = []
    for alpha in base_df["alpha"]:
        metrics = _build_case_metrics(
            float(alpha),
            feed_price=base_scenario.feed_price,
            pretreatment_case=base_scenario.pretreatment_case,
            biostimulant_price=base_scenario.biostimulant_price,
        )
        full_metrics.append(metrics)
        if any(abs(float(alpha) - a) < 1e-9 for a in selected_alphas):
            selected_metrics.append(metrics)

    full_metrics_df = pd.DataFrame(full_metrics)
    selected_metrics_df = pd.DataFrame(selected_metrics).sort_values("alpha")

    _save_dataframe(full_metrics_df, CSV_DIR / "base_scenario_full_metrics.csv")
    _save_dataframe(selected_metrics_df, CSV_DIR / "base_scenario_selected_alphas.csv")

    # 5) Figure 3 and Figure 4
    plot_cost_metrics(selected_metrics_df, FIG_DIR / "figure3_cost_metrics_selected_alphas.png")
    plot_product_outputs(full_metrics_df, FIG_DIR / "figure4_product_outputs_base.png")

    print("\nDone.")
    print(f"CSV output: {CSV_DIR.resolve()}")
    print(f"Figure output: {FIG_DIR.resolve()}")


if __name__ == "__main__":
    main()