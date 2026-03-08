from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import biosteam as bst

from biosteam.exceptions import CostWarning
from sabre.chemicals import create_chemicals
from sabre.systems.ad_biogas_system import create_ad_biogas_system


# Silence BioSTEAM warnings during sweeps/plots
warnings.filterwarnings("ignore", category=CostWarning)

MW_CH4 = 16.042
MW_CO2 = 44.01
NM3_PER_KMOL = 22.414
CH4_LHV_MJ_PER_KG = 50.0
MJ_PER_MMBTU = 1055.056

# -----------------------------
# Screening TEA assumptions
# -----------------------------
OPERATING_DAYS = 330.0
OPERATING_HOURS_PER_YEAR = 24.0 * OPERATING_DAYS
DISCOUNT_RATE = 0.10
PROJECT_LIFE_YEARS = 30
FIXED_OPEX_FRAC_OF_CAPEX = 0.03
HEAT_PRICE_PER_MJ = 0.006


# -----------------------------
# Paths
# -----------------------------
RESULTS_DIR = Path("results/ad/sweeps")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


# -----------------------------
# Helpers
# -----------------------------
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


def total_installed_cost(system) -> float:
    total = 0.0
    for u in system.units:
        total += safe_float(getattr(u, "installed_cost", 0.0), 0.0)
    return total


def total_heating_duty_MJ_hr(system) -> float:
    total_kJ_hr = 0.0
    for u in system.units:
        if hasattr(u, "heat_utilities"):
            for hu in u.heat_utilities:
                duty = safe_float(getattr(hu, "duty", 0.0), 0.0)
                if duty > 0:
                    total_kJ_hr += duty
    return total_kJ_hr / 1000.0


# -----------------------------
# Screening TEA metric
# -----------------------------
def breakeven_price_per_mmbtu(system, biomethane_stream) -> float:
    installed_cost = total_installed_cost(system)
    annual_utility_cost = annualize_hourly(total_unit_utility_cost_per_hr(system), OPERATING_DAYS)
    annual_heat_cost = annualize_hourly(total_heating_duty_MJ_hr(system) * HEAT_PRICE_PER_MJ, OPERATING_DAYS)
    annualized_capex = installed_cost * crf(DISCOUNT_RATE, PROJECT_LIFE_YEARS)
    fixed_opex = FIXED_OPEX_FRAC_OF_CAPEX * installed_cost
    total_annual_cost = annualized_capex + annual_utility_cost + annual_heat_cost + fixed_opex

    biomethane_mmbtu_yr = annualize_hourly(ch4_mmbtu_hr(biomethane_stream), OPERATING_DAYS)
    if biomethane_mmbtu_yr <= 0:
        return float("nan")

    return total_annual_cost / biomethane_mmbtu_yr


# -----------------------------
# Case runner
# -----------------------------
@dataclass(frozen=True)
class CaseResult:
    breakeven_mmbtu: float
    biomethane_nm3_hr: float
    biomethane_kg_hr: float
    ad_feed_vs_kg_hr: float
    digestate_vs_kg_hr: float
    raw_biogas_ch4_molfrac: float


def run_case(**kwargs) -> CaseResult:
    chems = create_chemicals()
    bst.settings.set_thermo(chems)

    system = create_ad_biogas_system()
    fs = system.flowsheet

    AD = fs.unit.AD

    if "vs_destruction" in kwargs:
        AD.vs_destruction = float(kwargs["vs_destruction"])
    if "ch4_kg_per_kg_vs" in kwargs:
        AD.ch4_kg_per_kg_vs = float(kwargs["ch4_kg_per_kg_vs"])
    if "ch4_molfrac" in kwargs:
        AD.ch4_molfrac = float(kwargs["ch4_molfrac"])

    system.simulate()

    ad_feed = fs.unit.ML.outs[0]
    digestate = fs.unit.AD.outs[1]
    raw_biogas = fs.unit.AD.outs[0]
    biomethane = fs.unit.UP.outs[0]

    _, ad_feed_vs = get_ts_vs(ad_feed)
    _, digestate_vs = get_ts_vs(digestate)

    return CaseResult(
        breakeven_mmbtu=breakeven_price_per_mmbtu(system, biomethane),
        biomethane_nm3_hr=ch4_nm3_hr(biomethane),
        biomethane_kg_hr=ch4_kg_hr(biomethane),
        ad_feed_vs_kg_hr=ad_feed_vs,
        digestate_vs_kg_hr=digestate_vs,
        raw_biogas_ch4_molfrac=gas_ch4_molfrac(raw_biogas),
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
                f"[OK] {param}={v:.4f}  "
                f"BE={r.breakeven_mmbtu:.3f} $/MMBtu  "
                f"biomethane={r.biomethane_nm3_hr:.1f} Nm3/h  "
                f"raw_CH4_molfrac={r.raw_biogas_ch4_molfrac:.3f}"
            )
            rows.append(
                {
                    param: float(v),
                    "breakeven_$_per_MMBtu": r.breakeven_mmbtu,
                    "biomethane_Nm3_hr": r.biomethane_nm3_hr,
                    "biomethane_kg_hr": r.biomethane_kg_hr,
                    "ad_feed_vs_kg_hr": r.ad_feed_vs_kg_hr,
                    "digestate_vs_kg_hr": r.digestate_vs_kg_hr,
                    "raw_biogas_ch4_molfrac": r.raw_biogas_ch4_molfrac,
                }
            )
        except Exception as e:
            print(f"[FAIL] {param}={v:.4f}  {e}")
            rows.append(
                {
                    param: float(v),
                    "breakeven_$_per_MMBtu": float("nan"),
                    "biomethane_Nm3_hr": float("nan"),
                    "biomethane_kg_hr": float("nan"),
                    "ad_feed_vs_kg_hr": float("nan"),
                    "digestate_vs_kg_hr": float("nan"),
                    "raw_biogas_ch4_molfrac": float("nan"),
                }
            )

    return pd.DataFrame(rows)


def sweep_yield_across_vs_destruction(
    *,
    yield_param: str,
    yield_vals: Iterable[float],
    vs_destruction_vals: Iterable[float],
    base_kwargs: Dict[str, Any],
) -> pd.DataFrame:
    rows = []
    for vsd in vs_destruction_vals:
        base2 = dict(base_kwargs)
        base2["vs_destruction"] = float(vsd)

        for y in yield_vals:
            kwargs = dict(base2)
            kwargs[yield_param] = float(y)

            try:
                r = run_case(**kwargs)
                print(
                    f"[OK] vs_destruction={vsd:.3f}  {yield_param}={y:.4f}  "
                    f"BE={r.breakeven_mmbtu:.3f}"
                )
                rows.append(
                    {
                        "vs_destruction": float(vsd),
                        yield_param: float(y),
                        "breakeven_$_per_MMBtu": r.breakeven_mmbtu,
                        "biomethane_Nm3_hr": r.biomethane_nm3_hr,
                        "biomethane_kg_hr": r.biomethane_kg_hr,
                        "ad_feed_vs_kg_hr": r.ad_feed_vs_kg_hr,
                        "digestate_vs_kg_hr": r.digestate_vs_kg_hr,
                        "raw_biogas_ch4_molfrac": r.raw_biogas_ch4_molfrac,
                    }
                )
            except Exception as e:
                print(f"[FAIL] vs_destruction={vsd:.3f}  {yield_param}={y:.4f}  {e}")
                rows.append(
                    {
                        "vs_destruction": float(vsd),
                        yield_param: float(y),
                        "breakeven_$_per_MMBtu": float("nan"),
                        "biomethane_Nm3_hr": float("nan"),
                        "biomethane_kg_hr": float("nan"),
                        "ad_feed_vs_kg_hr": float("nan"),
                        "digestate_vs_kg_hr": float("nan"),
                        "raw_biogas_ch4_molfrac": float("nan"),
                    }
                )

    return pd.DataFrame(rows)


# -----------------------------
# Plotting
# -----------------------------
def plot_1d(df: pd.DataFrame, x: str, filename: str, title: str, xlabel: str | None = None) -> None:
    d = df.dropna(subset=[x, "breakeven_$_per_MMBtu"]).copy()
    plt.figure(figsize=(8, 5))
    plt.plot(d[x], d["breakeven_$_per_MMBtu"], marker="o")
    plt.xlabel(xlabel or x)
    plt.ylabel("Break-even price ($/MMBtu)")
    plt.title(title)
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(RESULTS_DIR / filename, dpi=220)
    plt.close()


def plot_yield_be_multi_vsd(
    df: pd.DataFrame,
    *,
    x: str,
    filename: str,
    title: str = "Break-even Price vs Methane Yield at Different VS Destruction Values",
) -> None:
    d0 = df.dropna(subset=["vs_destruction", x, "breakeven_$_per_MMBtu"]).copy()

    plt.figure(figsize=(8, 5))
    for vsd, g in d0.groupby("vs_destruction"):
        g = g.sort_values(x)
        plt.plot(g[x], g["breakeven_$_per_MMBtu"], marker="o", label=f"{vsd:.2f}")

    plt.xlabel(x)
    plt.ylabel("Break-even price ($/MMBtu)")
    plt.title(title)
    plt.grid(True)
    plt.legend(title="VS destruction")
    plt.tight_layout()
    plt.savefig(RESULTS_DIR / filename, dpi=220)
    plt.close()


def plot_yield_prod_multi_vsd(
    df: pd.DataFrame,
    *,
    x: str,
    filename: str,
    title: str = "Biomethane Production vs Methane Yield at Different VS Destruction Values",
) -> None:
    d0 = df.dropna(subset=["vs_destruction", x, "biomethane_Nm3_hr"]).copy()

    plt.figure(figsize=(8, 5))
    for vsd, g in d0.groupby("vs_destruction"):
        g = g.sort_values(x)
        plt.plot(g[x], g["biomethane_Nm3_hr"], marker="o", label=f"{vsd:.2f}")

    plt.xlabel(x)
    plt.ylabel("Biomethane (Nm3/h)")
    plt.title(title)
    plt.grid(True)
    plt.legend(title="VS destruction")
    plt.tight_layout()
    plt.savefig(RESULTS_DIR / filename, dpi=220)
    plt.close()


# -----------------------------
# Main
# -----------------------------
def main() -> None:
    base = dict(
        vs_destruction=0.50,
        ch4_kg_per_kg_vs=0.0555,
        ch4_molfrac=0.50,
    )

    # -------------------------
    # 1) Single-factor sweeps
    # -------------------------
    vs_vals = np.linspace(0.30, 0.60, 7)
    df_vs = sweep_1d("vs_destruction", vs_vals, base)
    df_vs.to_csv(RESULTS_DIR / "breakeven_vs_vs_destruction.csv", index=False)
    plot_1d(
        df_vs,
        "vs_destruction",
        "breakeven_vs_vs_destruction.png",
        "Break-even Price vs VS Destruction",
        xlabel="VS destruction",
    )

    ch4_yield_vals = np.array([0.040, 0.045, 0.050, 0.0555, 0.0625, 0.070])
    df_y = sweep_1d("ch4_kg_per_kg_vs", ch4_yield_vals, base)
    df_y.to_csv(RESULTS_DIR / "breakeven_vs_ch4_yield.csv", index=False)
    plot_1d(
        df_y,
        "ch4_kg_per_kg_vs",
        "breakeven_vs_ch4_yield.png",
        "Break-even Price vs Methane Yield",
        xlabel="Methane yield (kg CH4 / kg VS removed)",
    )

    molfrac_vals = np.linspace(0.45, 0.65, 6)
    df_m = sweep_1d("ch4_molfrac", molfrac_vals, base)
    df_m.to_csv(RESULTS_DIR / "breakeven_vs_ch4_molfrac.csv", index=False)
    plot_1d(
        df_m,
        "ch4_molfrac",
        "breakeven_vs_ch4_molfrac.png",
        "Break-even Price vs Raw Biogas CH4 Mole Fraction",
        xlabel="Raw biogas CH4 mole fraction",
    )

    # ---------------------------------------------------
    # 2) Methane yield curves with multiple VS destruction values
    # ---------------------------------------------------
    vs_curve_vals = np.array([0.30, 0.36, 0.42, 0.48, 0.54, 0.60], dtype=float)

    df_multi = sweep_yield_across_vs_destruction(
        yield_param="ch4_kg_per_kg_vs",
        yield_vals=ch4_yield_vals,
        vs_destruction_vals=vs_curve_vals,
        base_kwargs=base,
    )
    df_multi.to_csv(RESULTS_DIR / "breakeven_vs_yield_multi_vsd.csv", index=False)

    plot_yield_be_multi_vsd(
        df_multi,
        x="ch4_kg_per_kg_vs",
        filename="breakeven_vs_yield_multi_vsd.png",
        title="Break-even Price vs Methane Yield (multiple VS destruction values)",
    )

    plot_yield_prod_multi_vsd(
        df_multi,
        x="ch4_kg_per_kg_vs",
        filename="biomethane_vs_yield_multi_vsd.png",
        title="Biomethane Production vs Methane Yield (multiple VS destruction values)",
    )

    print(f"\nDone. CSV + PNG files written to: {RESULTS_DIR.resolve()}")


if __name__ == "__main__":
    main()