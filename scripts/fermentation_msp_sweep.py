from __future__ import annotations

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from sabre.systems.ethanol_fermentation_system import create_ethanol_fermentation_system


DENSITY_ETHANOL = 0.789   # kg/L
L_PER_GAL = 3.785


def mesp_per_gal(tea, ethanol_stream):
    """
    Returns MESP in $/gal ethanol
    """
    p_stream = tea.solve_price(ethanol_stream)  # $/kg stream

    if ethanol_stream.F_mass <= 0:
        raise RuntimeError("Zero ethanol stream flow.")

    e = ethanol_stream.imass["Ethanol"]
    if e <= 0:
        raise RuntimeError("Zero ethanol production.")

    wt = e / ethanol_stream.F_mass
    p_ethanol = p_stream / wt  # $/kg ethanol

    return p_ethanol * DENSITY_ETHANOL * L_PER_GAL


def run_case(**kwargs):
    system, tea, streams, _ = create_ethanol_fermentation_system(**kwargs)
    system.simulate()
    return mesp_per_gal(tea, streams["ethanol"])


def sweep(param, values, base_kwargs):
    rows = []

    for v in values:
        kwargs = dict(base_kwargs)
        kwargs[param] = float(v)

        try:
            mesp = run_case(**kwargs)
            print(f"[OK] {param}={v:.3f}  MESP={mesp:.3f}")
        except Exception as e:
            print(f"[FAIL] {param}={v:.3f}  {e}")
            mesp = float("nan")

        rows.append({param: v, "MESP_$/gal": mesp})

    return pd.DataFrame(rows)


def plot_mesp(df, x, filename, title):
    d = df.dropna()

    plt.figure()
    plt.plot(d[x], d["MESP_$/gal"], marker="o")
    plt.xlabel(x)
    plt.ylabel("MESP ($/gal)")
    plt.title(title)
    plt.grid(True)
    plt.tight_layout()
    plt.savefig(filename, dpi=220)
    plt.close()


def main():

    base = dict(
        debug=False,
        feedstock_price=0.0,
        feed_dewatering_moisture=0.65,
        dewatering_moisture=0.65,
        keep_feed_solubles=0.90,
        keep_post_solubles=0.90,
        X_alginate_to_sugars=0.90,
        X_fucoidan_to_sugars=0.90,
        X_mannitol_to_sugars=0.95,
        frac_seaweed_sugars_to_xylose=0.0,
        strip_ferm_aux_water=True,
    )

    # Yield Sweep
    yield_vals = np.linspace(0.10, 0.95, 10)

    df_y = sweep("X_alginate_to_sugars", yield_vals, base)
    df_y.to_csv("mesp_vs_alginate_yield.csv", index=False)

    plot_mesp(
        df_y,
        "X_alginate_to_sugars",
        "mesp_vs_alginate_yield.png",
        "MESP vs Alginate → Sugars Yield",
    )

    # Feedstock price sweep
    price_vals = np.linspace(0.0, 0.10, 11)

    df_p = sweep("feedstock_price", price_vals, base)
    df_p.to_csv("mesp_vs_feedstock_price.csv", index=False)

    plot_mesp(
        df_p,
        "feedstock_price",
        "mesp_vs_feedstock_price.png",
        "MESP vs Feedstock Price",
    )

    # Dewatering moisture sweep
    moisture_vals = np.linspace(0.55, 0.85, 10)

    df_m = sweep("dewatering_moisture", moisture_vals, base)
    df_m.to_csv("mesp_vs_dewatering_moisture.csv", index=False)

    plot_mesp(
        df_m,
        "dewatering_moisture",
        "mesp_vs_dewatering_moisture.png",
        "MESP vs Post-Pretreatment Moisture",
    )

    print("\nDone. CSV + PNG files written.")


if __name__ == "__main__":
    main()