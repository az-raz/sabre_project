"""
AD system builder

Purpose:
- Build a flowsheet block for the current system
- Return a BioSTEAM System for simulation and diagramming

Key entry points:
- create_ad_biogas_system(...)

Notes:
- feed --> press --> mill --> AD --> biogas upgrading --> digestate separation
- Uses plant-scale throughput from YAML (e.g., 15,000 ton/day wet feed)
- Feed composition (moisture/ash/VS/TS) is quality-bin dependent (only have pelagic for now

"""

import biosteam as bst

from sabre.config import load_assumptions, get_quality_params, get_scale_feed_kgph
from sabre.streams import make_sargassum_feed
from sabre.units.ad import AnaerobicDigester
from sabre.units.biogas_upgrading import BiogasUpgrading
from sabre.units.screwpress import DigestateScrewPress
from sabre.units.press import Press
from sabre.units.mill import Mill

# function to create the AD system
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

    # ---- preprocessing units (Press and Mill) ----
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

    # ---- AD unit ----
    adS = A["ad"]              # sizing
    adp = A["ad_performance"]  # performance
    adC = A["ad_costing"]      # costing

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

    # ---- biogas upgrading unit ---- 
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

     # ---- screw press unit (post-AD digestate separation) ----
    sp = A.get("digestate_screw_press", {})  # new YAML section name

    SP = DigestateScrewPress(
        ID="SP",
        ins=AD-1,
        outs=("soil_amendment", "liquid_digestate"),

        solids_IDs=tuple(sp.get("solids_IDs", ["Cellulose", "Ash"])),

        # performance (screw press defaults should be lower than centrifuge)
        ts_capture_frac=sp.get("ts_capture_frac", 0.33),
        cake_moisture_frac=sp.get("cake_moisture_frac", 0.77),

        # sizing
        capacity_tph_each=sp.get("capacity_tph_each", 6.0),

        # energy
        kWh_per_m3=sp.get("kWh_per_m3", 0.67),

        # costing (Table-based CAPEX; you choose currency handling)
        eur_to_usd=sp.get("eur_to_usd", 1.0),
        capex_eur_table=sp.get("capex_eur_table", None),

        include_polymer_dosing=sp.get("include_polymer_dosing", False),
        polymer_dosing_cost_eur_each=sp.get("polymer_dosing_cost_eur_each", 0.0),

        F_BM=sp.get("F_BM", 1.0),
    )
    
    return bst.System("AD_Biogas_sys", path=(PR, ML, AD, UP, SP))