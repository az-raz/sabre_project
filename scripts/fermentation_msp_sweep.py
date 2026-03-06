from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from biosteam.exceptions import CostWarning
from sabre.systems.ethanol_fermentation_system import create_ethanol_fermentation_system

# Silence BioSTEAM "correlation out of bounds" warnings during sweeps/plots
warnings.filterwarnings("ignore", category=CostWarning)

DENSITY_ETHANOL_KG_L = 0.789
L_PER_GAL = 3.785


# -----------------------------
# Paths
# -----------------------------
RESULTS_DIR = Path("results/sweeps")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


# -----------------------------
# Stream metrics
# -----------------------------
def water_wt(stream) -> float:
    """Water mass fraction in a stream (NaN if undefined)."""
    if stream is None or stream.F_mass <= 0 or "Water" not in stream.chemicals:
        return float("nan")
    return float(stream.imass["Water"] / stream.F_mass)


def kg_hr_from_tonne_hr(tonne_hr: float) -> float:
    """Metric tonne/hr -> kg/hr."""
    return float(tonne_hr) * 1000.0


# -----------------------------
# MESP
# -----------------------------
def mesp_per_gal(tea, ethanol_stream) -> float:
    """Return MESP in $/gal ethanol."""
    p_stream = tea.solve_price(ethanol_stream)  # $/kg of product stream

    if ethanol_stream.F_mass <= 0:
        raise RuntimeError("Zero ethanol stream flow.")
    e = float(ethanol_stream.imass["Ethanol"])
    if e <= 0:
        raise RuntimeError("Zero ethanol production.")

    wt_ethanol = e / ethanol_stream.F_mass
    p_ethanol = p_stream / wt_ethanol  # $/kg ethanol

    return float(p_ethanol * DENSITY_ETHANOL_KG_L * L_PER_GAL)


# -----------------------------
# Case runner
# -----------------------------
@dataclass(frozen=True)
class CaseResult:
    mesp: float
    feed_cake_water_wt: float
    ferm_feed_water_wt: float
    ethanol_kg_hr: float
    beer_water_wt: float


def run_case(**kwargs) -> CaseResult:
    system, tea, streams, _ = create_ethanol_fermentation_system(**kwargs)
    system.simulate()

    mesp = mesp_per_gal(tea, streams["ethanol"])
    m_feed = water_wt(streams.get("feed_dewatered_cake"))   # after U_DW0
    m_ferm = water_wt(streams.get("dewatered_cake"))        # actual fermentation feed
    ethanol_kg = float(streams["ethanol"].imass["Ethanol"]) if "Ethanol" in streams["ethanol"].chemicals else float("nan")
    beer_water = water_wt(streams.get("beer_raw"))

    return CaseResult(
        mesp=mesp,
        feed_cake_water_wt=m_feed,
        ferm_feed_water_wt=m_ferm,
        ethanol_kg_hr=ethanol_kg,
        beer_water_wt=beer_water,
    )


# -----------------------------
# Sweeps
# -----------------------------
def sweep_1d(param: str, values: Iterable[float], base_kwargs: Dict[str, Any]) -> pd.DataFrame:
    rows = []
    for v in values:
        kwargs = dict(base_kwargs)
        kwargs[param] = float(v)

        try:
            r = run_case(**kwargs)
            print(
                f"[OK] {param}={v:.3f}  "
                f"MESP={r.mesp:.3f}  "
                f"feed_cake_water={r.feed_cake_water_wt:.3f}  "
                f"ferm_feed_water={r.ferm_feed_water_wt:.3f}"
            )
            rows.append(
                {
                    param: float(v),
                    "MESP_$/gal": r.mesp,
                    "feed_cake_water_wt": r.feed_cake_water_wt,
                    "ferm_feed_water_wt": r.ferm_feed_water_wt,
                    "ethanol_kg_hr": r.ethanol_kg_hr,
                    "beer_water_wt": r.beer_water_wt,
                }
            )
        except Exception as e:
            print(f"[FAIL] {param}={v:.3f}  {e}")
            rows.append(
                {
                    param: float(v),
                    "MESP_$/gal": float("nan"),
                    "feed_cake_water_wt": float("nan"),
                    "ferm_feed_water_wt": float("nan"),
                    "ethanol_kg_hr": float("nan"),
                    "beer_water_wt": float("nan"),
                }
            )

    return pd.DataFrame(rows)


def sweep_bool(param: str, base_kwargs: Dict[str, Any]) -> pd.DataFrame:
    rows = []
    for v in [False, True]:
        kwargs = dict(base_kwargs)
        kwargs[param] = v

        try:
            r = run_case(**kwargs)
            print(
                f"[OK] {param}={v}  "
                f"MESP={r.mesp:.3f}  "
                f"feed_cake_water={r.feed_cake_water_wt:.3f}  "
                f"ferm_feed_water={r.ferm_feed_water_wt:.3f}"
            )
            rows.append(
                {
                    param: v,
                    "MESP_$/gal": r.mesp,
                    "feed_cake_water_wt": r.feed_cake_water_wt,
                    "ferm_feed_water_wt": r.ferm_feed_water_wt,
                    "ethanol_kg_hr": r.ethanol_kg_hr,
                    "beer_water_wt": r.beer_water_wt,
                }
            )
        except Exception as e:
            print(f"[FAIL] {param}={v}  {e}")
            rows.append(
                {
                    param: v,
                    "MESP_$/gal": float("nan"),
                    "feed_cake_water_wt": float("nan"),
                    "ferm_feed_water_wt": float("nan"),
                    "ethanol_kg_hr": float("nan"),
                    "beer_water_wt": float("nan"),
                }
            )

    return pd.DataFrame(rows)


def sweep_yield_across_feed_rates(
    *,
    yield_param: str,
    yield_vals: Iterable[float],
    feed_tonne_hr_vals: Iterable[float],
    base_kwargs: Dict[str, Any],
) -> pd.DataFrame:
    """
    Run a yield sweep for each feed rate.
    Output has columns: feed_tonne_hr, feed_kg_hr, yield_param, MESP_$/gal, moisture metrics.
    """
    rows = []
    for feed_tph in feed_tonne_hr_vals:
        base2 = dict(base_kwargs)
        base2["feed_total_flow_kg_hr"] = kg_hr_from_tonne_hr(feed_tph)

        for y in yield_vals:
            kwargs = dict(base2)
            kwargs[yield_param] = float(y)

            try:
                r = run_case(**kwargs)
                print(f"[OK] feed={feed_tph:.0f} t/hr  {yield_param}={y:.3f}  MESP={r.mesp:.3f}")
                rows.append(
                    {
                        "feed_tonne_hr": float(feed_tph),
                        "feed_kg_hr": kg_hr_from_tonne_hr(feed_tph),
                        yield_param: float(y),
                        "MESP_$/gal": r.mesp,
                        "feed_cake_water_wt": r.feed_cake_water_wt,
                        "ferm_feed_water_wt": r.ferm_feed_water_wt,
                        "ethanol_kg_hr": r.ethanol_kg_hr,
                        "beer_water_wt": r.beer_water_wt,
                    }
                )
            except Exception as e:
                print(f"[FAIL] feed={feed_tph:.0f} t/hr  {yield_param}={y:.3f}  {e}")
                rows.append(
                    {
                        "feed_tonne_hr": float(feed_tph),
                        "feed_kg_hr": kg_hr_from_tonne_hr(feed_tph),
                        yield_param: float(y),
                        "MESP_$/gal": float("nan"),
                        "feed_cake_water_wt": float("nan"),
                        "ferm_feed_water_wt": float("nan"),
                        "ethanol_kg_hr": float("nan"),
                        "beer_water_wt": float("nan"),
                    }
                )

    return pd.DataFrame(rows)


# -----------------------------
# Plotting
# -----------------------------
def plot_1d(df: pd.DataFrame, x: str, filename: str, title: str, xlabel: str | None = None) -> None:
    d = df.dropna(subset=[x, "MESP_$/gal"]).copy()
    plt.figure(figsize=(8, 5))
    plt.plot(d[x], d["MESP_$/gal"], marker="o")
    plt.xlabel(xlabel or x)
    plt.ylabel("MESP ($/gal)")
    plt.title(title)
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(RESULTS_DIR / filename, dpi=220)
    plt.close()


def plot_bool_bar(df: pd.DataFrame, x: str, filename: str, title: str) -> None:
    d = df.dropna(subset=[x, "MESP_$/gal"]).copy()
    d[x] = d[x].astype(str)

    plt.figure(figsize=(7, 5))
    plt.bar(d[x], d["MESP_$/gal"])
    plt.xlabel(x)
    plt.ylabel("MESP ($/gal)")
    plt.title(title)
    plt.tight_layout()
    plt.savefig(RESULTS_DIR / filename, dpi=220)
    plt.close()


def plot_yield_mesp_multi_flow(
    df: pd.DataFrame,
    *,
    x: str,
    filename: str,
    title: str = "MESP vs Yield at Different Feed Rates",
) -> None:
    d0 = df.dropna(subset=["feed_tonne_hr", x, "MESP_$/gal"]).copy()

    plt.figure(figsize=(8, 5))
    for feed_tph, g in d0.groupby("feed_tonne_hr"):
        g = g.sort_values(x)
        plt.plot(g[x], g["MESP_$/gal"], marker="o", label=f"{feed_tph:.0f} t/hr")

    plt.xlabel(x)
    plt.ylabel("MESP ($/gal)")
    plt.title(title)
    plt.grid(True)
    plt.legend(title="Feed rate")
    plt.tight_layout()
    plt.savefig(RESULTS_DIR / filename, dpi=220)
    plt.close()


# -----------------------------
# Main
# -----------------------------
def main() -> None:
    base = dict(
        debug=False,
        feedstock_price=0.0,
        feed_total_flow_kg_hr=625000,   # ~625 tonne/hr baseline
        include_feed_dewatering=True,
        feed_dewatering_moisture=0.60,
        keep_feed_solubles=0.90,
        X_alginate_to_sugars=0.90,
        X_fucoidan_to_sugars=0.90,
        X_mannitol_to_sugars=0.95,
        frac_seaweed_sugars_to_xylose=0.0,
        strip_ferm_aux_water=True,
        aux_water_threshold=0.95,
    )

    # -------------------------
    # 1) Single-factor sweeps
    # -------------------------
    yield_vals = np.linspace(0.10, 0.95, 10)
    df_y = sweep_1d("X_alginate_to_sugars", yield_vals, base)
    df_y.to_csv(RESULTS_DIR / "mesp_vs_alginate_yield.csv", index=False)
    plot_1d(
        df_y,
        "X_alginate_to_sugars",
        "mesp_vs_alginate_yield.png",
        "MESP vs Alginate to Sugars Yield",
        xlabel="Alginate to sugars conversion",
    )

    price_vals = np.linspace(0.0, 0.10, 11)
    df_p = sweep_1d("feedstock_price", price_vals, base)
    df_p.to_csv(RESULTS_DIR / "mesp_vs_feedstock_price.csv", index=False)
    plot_1d(
        df_p,
        "feedstock_price",
        "mesp_vs_feedstock_price.png",
        "MESP vs Feedstock Price",
        xlabel="Feedstock price ($/kg)",
    )

    moisture_vals = np.linspace(0.55, 0.85, 10)
    df_m = sweep_1d("feed_dewatering_moisture", moisture_vals, base)
    df_m.to_csv(RESULTS_DIR / "mesp_vs_feed_dewatering_moisture.csv", index=False)
    plot_1d(
        df_m,
        "feed_dewatering_moisture",
        "mesp_vs_feed_dewatering_moisture.png",
        "MESP vs Feed Dewatering Moisture",
        xlabel="Feed dewatering cake moisture fraction",
    )

    # Optional but useful: on/off dewatering comparison in the same sweep file
    df_dw = sweep_bool("include_feed_dewatering", base)
    df_dw.to_csv(RESULTS_DIR / "mesp_vs_include_feed_dewatering.csv", index=False)
    plot_bool_bar(
        df_dw,
        "include_feed_dewatering",
        "mesp_vs_include_feed_dewatering.png",
        "MESP with vs without Feed Dewatering",
    )

    # ---------------------------------------------------
    # 2) Yield–MESP curves with multiple feed flow rates
    # ---------------------------------------------------
    feed_rates_tph = np.array([100, 200, 400, 625, 800, 1000, 1200], dtype=float)

    df_multi = sweep_yield_across_feed_rates(
        yield_param="X_alginate_to_sugars",
        yield_vals=yield_vals,
        feed_tonne_hr_vals=feed_rates_tph,
        base_kwargs=base,
    )
    df_multi.to_csv(RESULTS_DIR / "mesp_vs_yield_multi_feed.csv", index=False)

    plot_yield_mesp_multi_flow(
        df_multi,
        x="X_alginate_to_sugars",
        filename="mesp_vs_yield_multi_feed.png",
        title="MESP vs Alginate to Sugars Yield (multiple feed rates)",
    )

    print(f"\nDone. CSV + PNG files written to: {RESULTS_DIR.resolve()}")


if __name__ == "__main__":
    main()