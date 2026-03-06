# scripts/vfa_test.py

from sabre.chemicals import set_thermo
set_thermo()

import biosteam as bst

# Import your VFA system builder (adjust module path if your file is named differently)
from sabre.systems.vfa_system import create_vfa_ad_system


def main():
    # Build and simulate
    sys = create_vfa_ad_system(
        quality="pelagic_high_quality",
        enable_heat_shock=False,   # flip True later for HS scenario
    )
    sys.simulate()

    # Grab units/streams (IDs must match what you used in the builder)
    fs = sys.flowsheet
    VFA_AD = fs.unit.VFA_AD

    offgas, digestate, vfa_product = VFA_AD.outs

    # ---- Debug prints: feed into VFA digester ----
    feed = VFA_AD.ins[0]
    print("\n=== VFA_AD feed (kg/hr) ===")
    print("F_mass:", feed.F_mass)
    print(stream_imass_nonzero(feed))

    print("\n=== VFA_AD digestate (kg/hr) ===")
    print("F_mass:", digestate.F_mass)
    print(stream_imass_nonzero(digestate))

    print("\n=== VFA product stream (kg/hr) ===")
    print("F_mass:", vfa_product.F_mass)
    print(stream_imass_nonzero(vfa_product))

    acids = ["AceticAcid", "PropionicAcid", "ButyricAcid", "ValericAcid", "HexanoicAcid"]
    print("\n=== VFAs in product (kg/hr) ===")
    print({a: float(vfa_product.imass[a]) for a in acids if a in vfa_product.chemicals.IDs and vfa_product.imass[a] > 1e-12})

    print("\n=== VFAs in digestate (kg/hr) ===")
    print({a: float(digestate.imass[a]) for a in acids if a in digestate.chemicals.IDs and digestate.imass[a] > 1e-12})

    # ---- Design/cost sanity ----
    print("\n=== VFA_AD design results ===")
    for k, v in VFA_AD.design_results.items():
        print(f"{k}: {v}")

def stream_imass_nonzero(stream, tol=1e-9):
    out = {}
    for chem in stream.chemicals:
        m = float(stream.imass[chem.ID])
        if m > tol:
            out[chem.ID] = m
    return out

if __name__ == "__main__":
    main()