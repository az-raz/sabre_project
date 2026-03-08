from __future__ import annotations

import pandas as pd
import biosteam as bst

from sabre.chemicals import create_chemicals
from sabre.systems.ad_biogas_system import create_ad_biogas_system


MW_CH4 = 16.042
MW_CO2 = 44.01
CH4_LHV_MJ_PER_KG = 50.0
NM3_PER_KMOL = 22.414


def safe_imass(stream, ID):
    try:
        return float(stream.imass[ID])
    except Exception:
        return 0.0


def get_ts_vs(stream):
    if getattr(stream, "phase", None) == "g":
        return 0.0, 0.0

    water = safe_imass(stream, "Water")
    ash = safe_imass(stream, "Ash")
    ts = max(float(stream.F_mass) - water, 0.0)
    vs = max(ts - ash, 0.0)
    return ts, vs


def gas_fractions(stream):
    ch4_kgph = safe_imass(stream, "CH4")
    co2_kgph = safe_imass(stream, "CO2")

    total_mass = ch4_kgph + co2_kgph
    ch4_massfrac = ch4_kgph / total_mass if total_mass > 0 else 0.0

    n_ch4_kmolph = ch4_kgph / MW_CH4 if ch4_kgph > 0 else 0.0
    n_co2_kmolph = co2_kgph / MW_CO2 if co2_kgph > 0 else 0.0
    total_mol = n_ch4_kmolph + n_co2_kmolph
    ch4_molfrac = n_ch4_kmolph / total_mol if total_mol > 0 else 0.0

    return {
        "CH4_kgph": ch4_kgph,
        "CO2_kgph": co2_kgph,
        "CH4_massfrac": ch4_massfrac,
        "CH4_molfrac": ch4_molfrac,
        "CH4_kmolph": n_ch4_kmolph,
    }


def stream_summary(stream):
    ts, vs = get_ts_vs(stream)
    return {
        "ID": stream.ID,
        "Phase": getattr(stream, "phase", ""),
        "F_mass_kgph": float(stream.F_mass),
        "Water_kgph": safe_imass(stream, "Water"),
        "Ash_kgph": safe_imass(stream, "Ash"),
        "TS_kgph": ts,
        "VS_kgph": vs,
        "CH4_kgph": safe_imass(stream, "CH4"),
        "CO2_kgph": safe_imass(stream, "CO2"),
    }


def print_stream(stream, name=None):
    s = stream_summary(stream)
    label = name or s["ID"]
    print(f"\n--- {label} ---")
    for k, v in s.items():
        if k == "ID":
            continue
        if isinstance(v, float):
            print(f"{k}: {v:,.3f}")
        else:
            print(f"{k}: {v}")


def system_results_table(sys):
    rows = []
    for u in sys.units:
        row = {
            "Unit": u.ID,
            "Installed_cost_USD": float(getattr(u, "installed_cost", 0.0) or 0.0),
            "Purchase_cost_USD": float(getattr(u, "purchase_cost", 0.0) or 0.0),
            "Power_kW": float(
                getattr(u, "power_utility", 0.0).rate if hasattr(u, "power_utility") else 0.0
            ),
        }
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    chems = create_chemicals()
    bst.settings.set_thermo(chems)

    sys = create_ad_biogas_system()
    sys.simulate()

    PR = sys.flowsheet.unit.PR
    ML = sys.flowsheet.unit.ML
    AD = sys.flowsheet.unit.AD
    UP = sys.flowsheet.unit.UP
    SP = sys.flowsheet.unit.SP

    feed = PR.ins[0]
    pressed_cake = PR.outs[0]
    pressate = PR.outs[1]
    milled = ML.outs[0]
    milling_losses = ML.outs[1]
    biogas = AD.outs[0]
    digestate = AD.outs[1]
    biomethane = UP.outs[0]
    offgas = UP.outs[1]
    soil_amendment = SP.outs[0]
    liquid_digestate = SP.outs[1]

    print("\n==============================")
    print("AD BIOGAS SYSTEM: SANITY CHECK")
    print("==============================")

    print_stream(feed, "feed")
    print_stream(pressed_cake, "pressed_cake")
    print_stream(pressate, "pressate")
    print_stream(milled, "milled_biomass")
    print_stream(milling_losses, "milling_losses")
    print_stream(biogas, "raw_biogas")
    print_stream(digestate, "digestate")
    print_stream(biomethane, "biomethane")
    print_stream(offgas, "offgas")
    print_stream(soil_amendment, "soil_amendment")
    print_stream(liquid_digestate, "liquid_digestate")

    ad_in_ts, ad_in_vs = get_ts_vs(milled)
    dig_ts, dig_vs = get_ts_vs(digestate)

    raw_gas = gas_fractions(biogas)
    upgraded_gas = gas_fractions(biomethane)

    biomethane_nm3ph = upgraded_gas["CH4_kmolph"] * NM3_PER_KMOL
    biomethane_mjph = upgraded_gas["CH4_kgph"] * CH4_LHV_MJ_PER_KG

    print("\n------------------------------")
    print("Quick metrics")
    print("------------------------------")
    print(f"AD inlet TS (kg/h): {ad_in_ts:,.3f}")
    print(f"AD inlet VS (kg/h): {ad_in_vs:,.3f}")
    print(f"Digestate TS (kg/h): {dig_ts:,.3f}")
    print(f"Digestate VS (kg/h): {dig_vs:,.3f}")
    print(f"VS removed (kg/h): {ad_in_vs - dig_vs:,.3f}")
    print(f"Raw biogas CH4 (kg/h): {raw_gas['CH4_kgph']:,.3f}")
    print(f"Raw biogas CO2 (kg/h): {raw_gas['CO2_kgph']:,.3f}")
    print(f"Raw biogas CH4 mole fraction: {raw_gas['CH4_molfrac']:,.3f}")
    print(f"Raw biogas CH4 mass fraction: {raw_gas['CH4_massfrac']:,.3f}")
    print(f"Biomethane CH4 mole fraction: {upgraded_gas['CH4_molfrac']:,.3f}")
    print(f"Biomethane CH4 mass fraction: {upgraded_gas['CH4_massfrac']:,.3f}")
    print(f"Biomethane CH4 (Nm3/h): {biomethane_nm3ph:,.3f}")
    print(f"Biomethane energy (MJ/h): {biomethane_mjph:,.3f}")

    print("\n------------------------------")
    print("Unit summary")
    print("------------------------------")
    print(system_results_table(sys).to_string(index=False))

    print("\nDone.")


if __name__ == "__main__":
    main()