"""
AD + biogas upgrading system builder

Purpose:
- Build a flowsheet block for the current system
- Return a BioSTEAM System for simulation and diagramming

Key entry points:
- create_ad_biogas_system(...)

Notes:
- feed --> press --> mill --> AD --> biogas upgrading --> digestate separation
- Uses plant-scale throughput from YAML (e.g., 15,000 ton/day wet feed)
- Feed composition (moisture/ash/VS/TS) is quality-bin dependent
- Adds BiogasUpgrading unit downstream of AD biogas output

"""

import biosteam as bst

from sabre.config import load_assumptions, get_quality_params, get_scale_feed_kgph
from sabre.streams import make_sargassum_feed
from sabre.units.ad import AnaerobicDigester
from sabre.units.biogas_upgrading import BiogasUpgrading
from sabre.units.centrifuge import DigestateDecanterCentrifuge
from sabre.units.press import Press
from sabre.units.mill import Mill


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

        # ---- preprocessing (press + mill) ----
    pp = A.get("preprocessing", {})
    prA = pp.get("press", {})
    mlA = pp.get("mill", {})

    PR = Press(
        "PR",
        ins=feed,
        outs=("pressed_cake", "pressate"),
        solids_IDs=tuple(prA.get("solids_IDs", ["Cellulose", "Ash"])),
        solids_capture_frac=prA.get("solids_capture_frac", 0.98),
        cake_solids_wt_frac=prA.get("cake_solids_wt_frac", 0.35),
        solubles_to_pressate_frac=prA.get("solubles_to_pressate_frac", 1.0),
        power_kWh_per_ton_wet=prA.get("power_kWh_per_ton_wet", None),
    )

    ML = Mill(
        "ML",
        ins=PR-0,
        outs=("milled_biomass", "milling_losses"),
        loss_frac=mlA.get("loss_frac", 0.15),
        power_kWh_per_ton_wet=mlA.get("power_kWh_per_ton_wet", None),
    )

    # ---- pull parameters from YAML ----
    adS = A["ad"]              # sizing
    adp = A["ad_performance"]  # performance
    adC = A["ad_costing"]      # costing anchor

    AD = AnaerobicDigester(
        "AD",
        ins=ML-0,
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
        max_single_digester_volume_MG=adS.get("max_single_digester_volume_MG", 1.5),

        # costing
        base_volume_m3=adC["base_volume_m3"],
        base_capex_usd=adC["base_capex_usd"],
        maintenance_usd_per_m3_yr=adC.get("maintenance_usd_per_m3_yr", None),
    )

    upA = A["biogas_upgrading"]
    UP = BiogasUpgrading(
        "UP",
        ins=AD-0,
        outs=("biomethane", "offgas"),
        ch4_recovery=upA["ch4_recovery"],
        co2_removal=upA["co2_removal"],
        electricity_kwh_per_Nm3_raw=upA["electricity_kWh_per_Nm3_raw"],
        capex_usd_per_Nm3ph_raw=upA["capex_usd_per_Nm3ph_raw"],
    )

    dc = A["digestate_decanter_centrifuge"]

    DC = DigestateDecanterCentrifuge(
        ID="DC",
        ins=AD-1,
        outs=("soil_amendment", "liquid_digestate"),
        solids_IDs=tuple(dc["solids_IDs"]),
        ts_capture_frac=dc["ts_capture_frac"],
        cake_moisture_frac=dc["cake_moisture_frac"],
        capacity_tph_each=dc["capacity_tph_each"],
        centrifuge_purchase_cost_usd_each=dc["centrifuge_purchase_cost_usd_each"],
        F_BM=dc.get("F_BM", 1.0),
    )
    
    return bst.System("AD_Biogas_sys", path=(PR, ML, AD, UP,DC))