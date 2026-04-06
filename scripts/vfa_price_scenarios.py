"""
plot_vfa_results_figures.py
---------------------------
Generate Section 4.2 economics figures for the acidogenic AD + fermentation pathway.

Figures:
1) fig_vfa_feed_price.png / pdf
   - crude microbial oil MSP vs feed price

2) fig_vfa_biostimulant_price.png / pdf
   - crude microbial oil MSP vs assumed biostimulant price

3) fig_vfa_product_scenarios.png / pdf
   - MSP by product scenario, with market-price markers

Run from sabre_project root:
    python scripts/plot_vfa_results_figures.py
"""

from __future__ import annotations

from pathlib import Path
import sys

import biosteam as bst
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.append(str(SCRIPT_DIR))

from vfa_fermentation_tea import (
    FEED_PRICE_CASES,
    PRODUCT_SCENARIOS,
    OIL_EXTRACTION_REAGENT_USD_PER_KG_OIL,
    SOLIDS_DISPOSAL_USD_PER_KG,
    build_and_simulate,
    build_and_simulate_scenario,
    run_case,
    _patch_ev607,
    _apply_disposal_costs,
)
from sabre.tea import make_baseline_tea, solve_product_msp


OUT = Path("results/figures")
OUT.mkdir(parents=True, exist_ok=True)

# Base assumptions for 4.2 figures
BIOSTIMULANT_PRICE_CASES = [0.00, 0.50, 1.00, 2.00]
FEED_PRICE_BASE = 0.00

# Change this if you want a different benchmark line on the feed/biostim plots
CRUDE_OIL_MARKET_REF_USD_PER_KG = 5.00

plt.rcParams.update({
    "font.family":      "DejaVu Sans",
    "font.size":        10,
    "axes.titlesize":   10,
    "axes.labelsize":   10,
    "xtick.labelsize":  9,
    "ytick.labelsize":  9,
    "figure.dpi":       150,
    "axes.linewidth":   0.8,
    "axes.edgecolor":   "black",
    "xtick.direction":  "in",
    "ytick.direction":  "in",
    "xtick.top":        True,
    "ytick.right":      True,
})


def _solve_msp_from_system(
    full_sys,
    streams,
    extraction_usd_per_kg_oil: float = OIL_EXTRACTION_REAGENT_USD_PER_KG_OIL,
    solids_disposal_usd_per_kg: float = SOLIDS_DISPOSAL_USD_PER_KG,
) -> float:
    """
    Solve crude microbial oil MSP on the same basis as run_case().
    """
    _patch_ev607(full_sys, silent=True)
    _apply_disposal_costs(streams, solids_disposal_usd_per_kg=solids_disposal_usd_per_kg)

    oil_stream = streams["backend_oil"]
    oil_kg_hr = float(oil_stream.imass["MicrobialOil"])

    extraction_usd_per_hr = oil_kg_hr * extraction_usd_per_kg_oil
    try:
        oe_unit = bst.main_flowsheet.unit["OE"]
        oe_unit.add_OPEX = {"Oil extraction reagent": extraction_usd_per_hr}
    except Exception:
        pass

    tea = make_baseline_tea(full_sys)
    msp = solve_product_msp(
        tea=tea,
        product_stream=oil_stream,
        product_ID="MicrobialOil",
    )
    return float(msp["usd_per_kg_product"])


def _apply_biostimulant_price(streams, price_per_kg: float) -> bool:
    """
    Try to assign a biostimulant coproduct price if that stream exists.
    Returns True if a matching stream was found, else False.
    """
    candidate_ids = [
        "biostimulant_membrane_concentrate",
        "biostimulant_concentrate",
        "pressate_concentrate",
    ]

    # try dictionary-style access first
    for sid in candidate_ids:
        try:
            s = bst.main_flowsheet.stream[sid]
            s.price = price_per_kg
            return True
        except Exception:
            pass

    # try passed streams dict second
    if isinstance(streams, dict):
        for sid in candidate_ids:
            try:
                s = streams[sid]
                s.price = price_per_kg
                return True
            except Exception:
                pass

    return False


# ============================================================
# Figure 1 — Feed Price
# ============================================================
def make_feed_price_figure():
    feed_prices = [price for _, price in FEED_PRICE_CASES]
    msp_vals = []

    for label, price in FEED_PRICE_CASES:
        tea, msp, streams, units, full_sys = run_case(
            feed_price_per_kg_wet=price,
            case_label=label,
            run_diagnostics=False,
            silent=True,
        )
        msp_vals.append(float(msp["usd_per_kg_product"]))

    fig, ax = plt.subplots(figsize=(6.8, 4.5))
    ax.plot(
        feed_prices,
        msp_vals,
        marker="o",
        linewidth=1.8,
        markersize=6,
        markeredgecolor="black",
        zorder=3,
    )

    for x, y in zip(feed_prices, msp_vals):
        ax.text(
            x,
            y + max(msp_vals) * 0.015,
            f"{y:.2f}",
            ha="center",
            va="bottom",
            fontsize=8,
        )

    # Base case star: near-zero feed price
    base_feed_price = 0.00
    base_idx = feed_prices.index(base_feed_price)
    base_msp = msp_vals[base_idx]

    ax.scatter(
        [base_feed_price],
        [base_msp],
        marker="*",
        s=220,
        color="gold",
        edgecolors="black",
        linewidths=0.8,
        zorder=5,
        label="Base case",
    )

    ax.axhline(
        CRUDE_OIL_MARKET_REF_USD_PER_KG,
        color="black",
        linewidth=1.0,
        linestyle="--",
        zorder=1,
        label=f"${CRUDE_OIL_MARKET_REF_USD_PER_KG:.0f}/kg reference",
    )

    ax.set_xlabel("Feed price ($/kg wet Sargassum)")
    ax.set_ylabel("Crude microbial oil MSP ($/kg)")
    ax.set_title("Effect of feed price on crude microbial oil MSP")
    ax.xaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f"))
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("$%.0f"))
    ax.grid(axis="both", linewidth=0.4, color="#D3D1C7", zorder=0)
    ax.legend(frameon=False, fontsize=8, loc="upper left")

    ax.set_ylim(0, max(msp_vals) * 1.15)

    fig.tight_layout()
    fig.savefig(OUT / "fig_vfa_feed_price.png", bbox_inches="tight")
    fig.savefig(OUT / "fig_vfa_feed_price.pdf", bbox_inches="tight")


# ============================================================
# Figure 2 — Biostimulant Price
# ============================================================
def make_biostimulant_price_figure():
    msp_vals = []
    found_biostim_stream = False

    for bs_price in BIOSTIMULANT_PRICE_CASES:
        vfa_sys, fer_sys, streams, units, full_sys = build_and_simulate(FEED_PRICE_BASE)

        found_here = _apply_biostimulant_price(streams, bs_price)
        found_biostim_stream = found_biostim_stream or found_here

        msp_val = _solve_msp_from_system(full_sys, streams)
        msp_vals.append(msp_val)

    fig, ax = plt.subplots(figsize=(6.8, 4.5))
    ax.plot(
        BIOSTIMULANT_PRICE_CASES,
        msp_vals,
        marker="o",
        linewidth=1.8,
        markersize=6,
        markeredgecolor="black",
        zorder=3,
    )

    for x, y in zip(BIOSTIMULANT_PRICE_CASES, msp_vals):
        ax.text(
            x,
            y + max(msp_vals) * 0.015,
            f"{y:.2f}",
            ha="center",
            va="bottom",
            fontsize=8,
        )

    # Base case star: zero biostimulant price
    base_biostim_price = 0.00
    base_idx = BIOSTIMULANT_PRICE_CASES.index(base_biostim_price)
    base_msp = msp_vals[base_idx]

    ax.scatter(
        [base_biostim_price],
        [base_msp],
        marker="*",
        s=220,
        color="gold",
        edgecolors="black",
        linewidths=0.8,
        zorder=5,
        label="Base case",
    )

    ax.axhline(
        CRUDE_OIL_MARKET_REF_USD_PER_KG,
        color="black",
        linewidth=1.0,
        linestyle="--",
        zorder=1,
        label=f"${CRUDE_OIL_MARKET_REF_USD_PER_KG:.0f}/kg reference",
    )

    ax.set_xlabel("Biostimulant price ($/kg)")
    ax.set_ylabel("Crude microbial oil MSP ($/kg)")
    ax.set_title("Effect of biostimulant price on crude microbial oil MSP")
    ax.xaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f"))
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("$%.0f"))
    ax.grid(axis="both", linewidth=0.4, color="#D3D1C7", zorder=0)
    ax.legend(frameon=False, fontsize=8, loc="upper right")
    ax.set_ylim(-1.2, max(msp_vals) * 1.15)

    fig.tight_layout()
    fig.savefig(OUT / "fig_vfa_biostimulant_price.png", bbox_inches="tight")
    fig.savefig(OUT / "fig_vfa_biostimulant_price.pdf", bbox_inches="tight")


# ============================================================
# Figure 3 — Product Scenarios
# ============================================================
def make_product_scenarios_figure():
    labels = []
    msp_vals = []
    market_vals = []

    for sc in PRODUCT_SCENARIOS:
        vfa_sys, fer_sys, streams, units, full_sys = build_and_simulate_scenario(
            feed_price_per_kg_wet=FEED_PRICE_BASE,
            product_yield=sc["yield"],
            residence_time_h=sc["residence_h"],
        )

        _patch_ev607(full_sys, silent=True)
        _apply_disposal_costs(streams)

        oil_stream = streams["backend_oil"]
        product_kg_hr = float(oil_stream.imass["MicrobialOil"])
        extraction_usd_per_hr = product_kg_hr * sc["extraction_usd_per_kg"]

        try:
            oe_unit = bst.main_flowsheet.unit["OE"]
            oe_unit.add_OPEX = {
                "Product extraction/purification": extraction_usd_per_hr
            }
        except Exception:
            pass

        tea = make_baseline_tea(full_sys)
        msp_dict = solve_product_msp(
            tea=tea,
            product_stream=oil_stream,
            product_ID="MicrobialOil",
        )

        labels.append(sc["label"])
        msp_vals.append(float(msp_dict["usd_per_kg_product"]))
        market_vals.append(float(sc["market_price"]))

    x = np.arange(len(labels))

    fig, ax = plt.subplots(figsize=(7.0, 4.8))
    bars = ax.bar(
        x,
        msp_vals,
        edgecolor="black",
        linewidth=0.8,
        width=0.55,
        zorder=3,
        label="MSP",
    )

    # market-price markers
    ax.scatter(
        x,
        market_vals,
        marker="D",
        s=65,
        color="gold",
        edgecolors="black",
        linewidths=0.8,
        zorder=5,
        label="Market reference",
    )

    for bar, val in zip(bars, msp_vals):
        ax.text(
            bar.get_x() + bar.get_width()/2,
            val * 1.08,
            f"{val:,.1f}",
            ha="center",
            va="bottom",
            fontsize=8,
        )

    for xi, mv in zip(x, market_vals):
        ax.text(
            xi,
            mv * 1.08,
            f"{mv:,.0f}",
            ha="center",
            va="bottom",
            fontsize=8,
        )

    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Price ($/kg product)")
    ax.set_title("Product scenario comparison at near-zero feed price")

    # log scale is cleaner because astaxanthin is orders of magnitude higher
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax.grid(axis="y", linewidth=0.4, color="#D3D1C7", zorder=0, which="both")
    ax.legend(frameon=False, fontsize=8, loc="upper left")

    fig.tight_layout()
    fig.savefig(OUT / "fig_vfa_product_scenarios.png", bbox_inches="tight")
    fig.savefig(OUT / "fig_vfa_product_scenarios.pdf", bbox_inches="tight")

    print("\nProduct scenario results:")
    for lab, msp, mkt in zip(labels, msp_vals, market_vals):
        print(f"  {lab:<18} MSP={msp:,.2f} $/kg | market ref={mkt:,.2f} $/kg")


if __name__ == "__main__":
    make_feed_price_figure()
    make_biostimulant_price_figure()
    make_product_scenarios_figure()

    print("\nSaved:")
    print(OUT / "fig_vfa_feed_price.png")
    print(OUT / "fig_vfa_biostimulant_price.png")
    print(OUT / "fig_vfa_product_scenarios.png")