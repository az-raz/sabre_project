"""
AD + biogas upgrading system builder

Purpose:
- Build a flowsheet block: feed -> AD -> Upgrading.
- Return a BioSTEAM System for simulation and diagramming

Key entry points:
- create_ad_biogas_system(...)

Notes:
- Uses the existing AD system builder logic: assumptions -> feed -> AD
- Adds BiogasUpgrading unit downstream of AD biogas output
"""

import biosteam as bst

from sabre.config import load_assumptions, get_quality_params, get_scale_feed_kgph
from sabre.streams import make_sargassum_feed
from sabre.units.ad import AnaerobicDigester
from sabre.units.biogas_upgrading import BiogasUpgrading


def create_ad_biogas_system(quality="pelagic_high_quality"):
    A = load_assumptions()
    q = get_quality_params(A, quality)

    fresh_feed_kgph = get_scale_feed_kgph(A)
    moisture_frac = q["moisture_frac"]
    vs_ts = q["vs_ts"]

    feed = make_sargassum_feed(
        fresh_feed_kgph=fresh_feed_kgph,
        moisture_frac=moisture_frac,
        quality=quality,
    )

    # ---- pull parameters from YAML ----
    adS = A["ad"]              # sizing
    adp = A["ad_performance"]  # performance
    adC = A["ad_costing"]      # costing anchor

    AD = AnaerobicDigester(
        "AD",
        ins=feed,
        outs=("biogas", "digestate"),

        # performance
        vs_ts=vs_ts,
        vs_destruction=adp["vs_destruction"],
        ch4_kg_per_kg_vs=adp["ch4_kg_per_kg_vs"],
        ch4_molfrac=adp["ch4_molfrac"],

        # sizing
        hrt_days=adS["hrt_days"],
        slurry_density_kg_per_m3=adS["slurry_density_kg_per_m3"],
        headspace_frac=adS["gas_storage_frac_of_total_volume"],

        # costing
        base_volume_m3=adC["base_volume_m3"],
        base_capex_usd=adC["base_capex_usd"],
        scaling_exponent=adC["scaling_exponent"],
        maintenance_usd_per_m3_yr=adC.get("maintenance_usd_per_m3_yr", None),
    )

    upA = A["biogas_upgrading"]
    UP = BiogasUpgrading(
        "UP",
        ins=AD - 0,
        outs=("biomethane", "offgas"),
        ch4_recovery=upA["ch4_recovery"],
        co2_removal=upA["co2_removal"],
        electricity_kwh_per_Nm3_raw=upA["electricity_kWh_per_Nm3_raw"],
        capex_usd_per_Nm3ph_raw=upA["capex_usd_per_Nm3ph_raw"],
    )
    
    return bst.System("AD_Biogas_sys", path=(AD, UP))