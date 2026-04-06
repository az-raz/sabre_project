"""
Integrated Biorefinery TEA — SABRE Project
===========================================
Sweeps the split fraction alpha (0 → 1) between the two pathways:
  alpha=0   → 100% VFA-to-oil
  alpha=0.5 → 50/50 split
  alpha=1   → 100% biomethane

For each alpha, reports:
  - Biomethane MSP ($/MMBtu)
  - Microbial oil MSP ($/kg)
  - Combined NPV at assumed market prices
  - TCI and VOC breakdown

Products:
  - Biomethane at assumed $5/MMBtu (Henry Hub midpoint)
  - Microbial oil at assumed $2.47/kg (near_zero standalone result)
  - Biostimulant at $0.50/kg (conservative)

The sweep shows the optimal alpha that maximizes combined NPV.
"""

import biosteam as bst
import math

from sabre.chemicals import set_thermo
from sabre.systems.integrated_system import create_integrated_biorefinery
from sabre.tea import make_baseline_tea, solve_product_msp, solve_biomethane_msp

# -------------------------
# Market price assumptions
# Used for NPV calculation at each alpha
# -------------------------
BIOMETHANE_MARKET_MMBTU    = 3.00    # $/MMBtu — Henry Hub midpoint
OIL_MARKET_USD_PER_KG      = 5.00  # $/kg — near_zero standalone VFA MSP
BIOSTIMULANT_USD_PER_KG    = 0.00   # $/kg — conservative wholesale

# -------------------------
# Reagent cost (oil extraction)
# Wired into OE.add_OPEX same as standalone VFA TEA
# -------------------------
OIL_EXTRACTION_REAGENT_USD_PER_KG_OIL = 0.50

# -------------------------
# Disposal costs
# -------------------------
RETENTATE_DISPOSAL_USD_PER_KG      = -0.005
FERM_WASTEWATER_DISPOSAL_USD_PER_KG = -0.005
SOLIDS_DISPOSAL_USD_PER_KG          = -0.04   # acidogenic solids
LIQUID_DIGESTATE_DISPOSAL_USD_PER_KG = -0.002
SOLID_DIGESTATE_DISPOSAL_USD_PER_KG  = -0.02

# -------------------------
# Feed price scenarios
# -------------------------
FEED_PRICE_CASES = [
    ("tipping_fee",  -0.02),
    ("near_zero",     0.00),
]

# -------------------------
# Alpha sweep points
# -------------------------
ALPHA_SWEEP = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]

CH4_MMBTU_PER_KG = 0.0526


def _get_integrated_stream(stream_id: str):
    """Safe stream lookup — returns None if not in registry."""
    try:
        return bst.main_flowsheet.stream[stream_id]
    except Exception:
        return None


def _apply_stream_prices(streams, biostimulant_price=BIOSTIMULANT_USD_PER_KG):
    """Set prices on all outlet streams that carry economic value or cost."""
    # Biostimulant revenue
    if streams.get("biostimulant_membrane_concentrate") is not None:
        streams["biostimulant_membrane_concentrate"].price = biostimulant_price

    # Pressate permeate — zero-cost discharge (floating biorefinery assumption)
    # The PC permeate is mostly water; modeled as near-shore discharge with no cost.
    # A disposal cost of $0.001–0.003/kg could be applied for land-based sensitivity.
    permeate = _get_integrated_stream("pressate_permeate")
    if permeate is not None:
        permeate.price = 0.0

    # VFA pathway disposal costs
    for sid, price in [
        ("vfa_retentate",              RETENTATE_DISPOSAL_USD_PER_KG),
        ("fermentation_wastewater",    FERM_WASTEWATER_DISPOSAL_USD_PER_KG),
        ("acidogenic_residual_solids", SOLIDS_DISPOSAL_USD_PER_KG),
    ]:
        s = streams.get(sid)
        if s is not None:
            s.price = price

    # AD pathway disposal costs
    for sid, price in [
        ("soil_amendment",    SOLID_DIGESTATE_DISPOSAL_USD_PER_KG),
        ("liquid_digestate",  LIQUID_DIGESTATE_DISPOSAL_USD_PER_KG),
    ]:
        s = streams.get(sid)
        if s is not None:
            s.price = price


def _wire_oil_reagent(streams, units):
    """Wire oil extraction reagent cost into OE.add_OPEX."""
    oil_stream = streams.get("backend_oil")
    oe = units.get("OE")
    if oil_stream is not None and oe is not None:
        oil_kg_hr = float(oil_stream.imass["MicrobialOil"])
        reagent_usd_per_hr = oil_kg_hr * OIL_EXTRACTION_REAGENT_USD_PER_KG_OIL
        oe.add_OPEX = {"Oil extraction reagent": reagent_usd_per_hr}


def _patch_ev607():
    """Low-duty evaporator placeholder (same as standalone VFA TEA)."""
    try:
        ev607 = bst.main_flowsheet.unit["Ev607"]
        v = getattr(ev607, "V", None)
        if v is not None and v < 0.02:
            feed = ev607.ins[0]
            feed_m3h = max(feed.F_mass / 1000.0, 1.0)
            placeholder_usd = 50000.0 * (feed_m3h ** 0.6)
            for k in list(ev607.baseline_purchase_costs.keys()):
                ev607.baseline_purchase_costs[k] = 0.0
            ev607.baseline_purchase_costs["Evaporator (low-duty placeholder)"] = placeholder_usd
            ev607.power_utility.consumption = 0.0
            ev607.heat_utilities.clear()
    except Exception:
        pass


def _compute_npv_at_market(tea, streams, market_mmbtu, market_oil_usd_per_kg):
    """
    Compute NPV at assumed market prices for both products.
    Sets prices temporarily, reads NPV, restores prices.
    """
    biomethane = streams.get("biomethane")
    oil_stream = streams.get("backend_oil")

    old_bm_price = biomethane.price if biomethane is not None else None
    old_oil_price = oil_stream.price if oil_stream is not None else None

    try:
        if biomethane is not None and float(biomethane.F_mass) > 0:
            ch4_mass = float(biomethane.imass["Methane"])
            total_mass = float(biomethane.F_mass)
            ch4_frac = ch4_mass / total_mass if total_mass > 0 else 0.0
            biomethane.price = market_mmbtu * CH4_MMBTU_PER_KG * ch4_frac

        if oil_stream is not None and float(oil_stream.F_mass) > 0:
            oil_mass_frac = float(oil_stream.imass["MicrobialOil"]) / float(oil_stream.F_mass)
            oil_stream.price = market_oil_usd_per_kg * oil_mass_frac

        npv = tea.NPV

    finally:
        if biomethane is not None and old_bm_price is not None:
            biomethane.price = old_bm_price
        if oil_stream is not None and old_oil_price is not None:
            oil_stream.price = old_oil_price

    return npv


def run_alpha_sweep(
    feed_price: float = 0.00,
    case_label: str = "near_zero",
    pretreatment_case: str = "press_mill_only",
    biostimulant_price: float = BIOSTIMULANT_USD_PER_KG,
    market_mmbtu: float = BIOMETHANE_MARKET_MMBTU,
    market_oil: float = OIL_MARKET_USD_PER_KG,
    print_summary: bool = True,
):
    """
    Sweep alpha from 0 to 1 and report both product MSPs and combined NPV.

    Returns a list of result dicts, one per alpha point.
    """
    results = []

    for alpha in ALPHA_SWEEP:
        bst.main_flowsheet.clear()
        set_thermo()

        try:
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

            # --- Biomethane MSP (if any methane is produced) ---
            biomethane = streams.get("biomethane")
            msp_mmbtu = float("nan")
            msp_ch4 = float("nan")
            # --- Independent MSPs ---
            # Each MSP is solved with the OTHER product's stream price held at
            # zero. This gives the true standalone breakeven for each product
            # within the integrated system — i.e., the price each product needs
            # to reach if the other contributes nothing. The two MSPs are NOT
            # additive; they are independent sensitivity answers. The NPV column
            # (below) is the correct multi-product economic result.

            oil_stream = streams.get("backend_oil")
            msp_oil    = float("nan")   # reset each iteration — prevents value leaking from previous alpha
            oil_kg_yr  = 0.0

            # Biomethane MSP: solve with oil price = 0
            if biomethane is not None and alpha > 0 and float(biomethane.F_mass) > 0:
                old_oil_price = oil_stream.price if oil_stream is not None else None
                try:
                    if oil_stream is not None:
                        oil_stream.price = 0.0
                    bm_msp   = solve_biomethane_msp(tea, biomethane)
                    msp_mmbtu = bm_msp.get("usd_per_mmbtu", float("nan"))
                    msp_ch4   = bm_msp.get("usd_per_kg_ch4", float("nan"))
                finally:
                    if oil_stream is not None and old_oil_price is not None:
                        oil_stream.price = old_oil_price

            # Oil MSP: solve with biomethane price = 0
            if oil_stream is not None and alpha < 1.0 and float(oil_stream.F_mass) > 0:
                old_bm_price = biomethane.price if biomethane is not None else None
                try:
                    if biomethane is not None:
                        biomethane.price = 0.0
                    oil_msp  = solve_product_msp(tea, oil_stream, product_ID="MicrobialOil")
                    msp_oil  = oil_msp.get("usd_per_kg_product", float("nan"))
                    oil_kg_yr = oil_msp.get("annual_product_kg", 0.0)
                finally:
                    if biomethane is not None and old_bm_price is not None:
                        biomethane.price = old_bm_price

            # --- Combined NPV at market prices ---
            npv = _compute_npv_at_market(tea, streams, market_mmbtu, market_oil)

            row = {
                "alpha": alpha,
                "msp_biomethane_mmbtu": msp_mmbtu,
                "msp_biomethane_ch4": msp_ch4,
                "msp_oil_usd_per_kg": msp_oil,
                "combined_npv_M": npv / 1e6,
                "tci_M": tea.TCI / 1e6,
                "voc_M": tea.VOC / 1e6,
                "foc_M": tea.FOC / 1e6,
                "oil_kg_yr": oil_kg_yr,
                "ok": True,
            }

        except Exception as e:
            row = {
                "alpha": alpha,
                "msp_biomethane_mmbtu": float("nan"),
                "msp_biomethane_ch4": float("nan"),
                "msp_oil_usd_per_kg": float("nan"),
                "combined_npv_M": float("nan"),
                "tci_M": float("nan"),
                "voc_M": float("nan"),
                "foc_M": float("nan"),
                "oil_kg_yr": 0.0,
                "ok": False,
                "error": str(e),
            }
            print(f"  [alpha={alpha:.1f}] ERROR: {e}")

        results.append(row)

    if print_summary:
        _print_sweep_table(results, case_label, pretreatment_case,
                           feed_price, biostimulant_price, market_mmbtu, market_oil)

    return results


def _print_sweep_table(results, case_label, pretreatment_case,
                       feed_price, biostimulant_price, market_mmbtu, market_oil):
    print("\n" + "=" * 95)
    print(
        f"INTEGRATED BIOREFINERY — ALPHA SWEEP\n"
        f"  Feed: ${feed_price:.3f}/kg [{case_label}]  |  "
        f"Pretreatment: {pretreatment_case}  |  "
        f"Biostimulant: ${biostimulant_price:.2f}/kg\n"
        f"  Market assumptions for NPV: biomethane ${market_mmbtu:.1f}/MMBtu  |  "
        f"microbial oil ${market_oil:.2f}/kg\n"
        f"  MSPs are INDEPENDENT: each solved with the other product price = $0\n"
        f"  (i.e. breakeven price if that product carries all remaining costs)"
    )
    print("=" * 95)
    print(
        f"  {'Alpha':>6}  {'→CH4':>6}  {'→Oil':>6}  "
        f"{'MSP CH4 ($/MMBtu)':>20}  {'MSP Oil ($/kg)':>16}  "
        f"{'NPV @ mkt ($M)':>15}  {'TCI ($M)':>10}"
    )
    print("  " + "-" * 93)

    best_npv = max((r["combined_npv_M"] for r in results if r["ok"]), default=float("nan"))

    for r in results:
        if not r["ok"]:
            print(f"  {r['alpha']:>6.1f}  ERROR")
            continue

        alpha = r["alpha"]
        pct_ch4 = f"{alpha*100:.0f}%"
        pct_oil = f"{(1-alpha)*100:.0f}%"

        msp_ch4_str = f"${r['msp_biomethane_mmbtu']:.2f}" if not math.isnan(r["msp_biomethane_mmbtu"]) else "  n/a  "
        msp_oil_str = f"${r['msp_oil_usd_per_kg']:.3f}" if not math.isnan(r["msp_oil_usd_per_kg"]) else "  n/a  "
        npv_str = f"${r['combined_npv_M']:.1f}M"
        tci_str = f"${r['tci_M']:.1f}M"

        star = " ◄ best NPV" if abs(r["combined_npv_M"] - best_npv) < 0.01 and r["ok"] else ""

        print(
            f"  {alpha:>6.1f}  {pct_ch4:>6}  {pct_oil:>6}  "
            f"{msp_ch4_str:>20}  {msp_oil_str:>16}  "
            f"{npv_str:>15}  {tci_str:>10}{star}"
        )

    # Find best alpha
    valid = [r for r in results if r["ok"] and not math.isnan(r["combined_npv_M"])]
    if valid:
        best = max(valid, key=lambda r: r["combined_npv_M"])
        print(f"\n  Optimal alpha = {best['alpha']:.1f} "
              f"(NPV = ${best['combined_npv_M']:.1f}M)")


# =============================================================
# Main
# =============================================================

if __name__ == "__main__":

    # -------------------------
    # 1. near_zero feed, press_mill_only, base biostimulant price
    # -------------------------
    print("\n>>> SWEEP 1: near_zero feed | press_mill_only | biostimulant=$0.50/kg")
    run_alpha_sweep(
        feed_price=0.00,
        case_label="near_zero",
        pretreatment_case="press_mill_only",
        biostimulant_price=0.50,
        market_mmbtu=3.50,
        market_oil=2.47,
    )

    # -------------------------
    # 2. tipping_fee feed, press_mill_only
    # -------------------------
    print("\n>>> SWEEP 2: tipping_fee feed | press_mill_only | biostimulant=$0.50/kg")
    run_alpha_sweep(
        feed_price=-0.02,
        case_label="tipping_fee",
        pretreatment_case="press_mill_only",
        biostimulant_price=0.50,
        market_mmbtu=3.50,
        market_oil=2.47,
    )

    # -------------------------
    # 3. near_zero feed, combined_PE (best methanogenic pretreatment)
    # -------------------------
    print("\n>>> SWEEP 3: near_zero feed | combined_PE | biostimulant=$0.50/kg")
    run_alpha_sweep(
        feed_price=0.00,
        case_label="near_zero",
        pretreatment_case="combined_PE",
        biostimulant_price=0.50,
        market_mmbtu=3.50,
        market_oil=2.47,
    )

    # -------------------------
    # 4. near_zero feed, optimistic biostimulant
    # -------------------------
    print("\n>>> SWEEP 4: near_zero feed | press_mill_only | biostimulant=$1.00/kg")
    run_alpha_sweep(
        feed_price=0.00,
        case_label="near_zero",
        pretreatment_case="press_mill_only",
        biostimulant_price=1.00,
        market_mmbtu=3.50,
        market_oil=2.47,
    )