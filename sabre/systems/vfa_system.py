import biosteam as bst

from sabre.config import load_assumptions, get_quality_params, get_scale_feed_kgph
from sabre.streams import make_sargassum_feed
from sabre.units.ad_vfa import AcidogenicDigester
from sabre.units.screwpress import DigestateScrewPress
from sabre.units.press import Press
from sabre.units.mill import Mill


def create_vfa_ad_system(
    quality="pelagic_high_quality",
    enable_heat_shock=False,
    hs_target_temperature_K=338.15,      # 65C HS --> heat shock
    hs_events_per_day=1.0/7.0,           # weekly default
    hs_heated_fraction_of_liquid=0.10,   # slipstream fraction
    hs_duration_min=15.0,
):
    """
    Acidogenic / VFA-targeted digestion system builder

    """

    A = load_assumptions()
    q = get_quality_params(A, quality)

    fresh_feed_kgph = get_scale_feed_kgph(A)
    moisture_frac = q["moisture_frac"]

    feed = make_sargassum_feed(
        fresh_feed_kgph=fresh_feed_kgph,
        moisture_frac=moisture_frac,
        quality=quality,
    )

    # preprocessing units (Press and Mill)
    pp = A.get("preprocessing", {})
    prA = pp.get("press", {})
    mlA = pp.get("mill", {})

    PR = Press(
        "PR",
        ins=feed,
        outs=("pressed_cake", "pressate"),
        solids_IDs=["Ash","Protein","Lignin","Glucan","Xylan","Mannan","Galactan","Arabinan",
                    "Alginate","Fucoidan","Mannitol","OtherSolids"],
        solids_capture_frac=prA.get("solids_capture_frac", 0.98),
        cake_solids_wt_frac=prA.get("cake_solids_wt_frac", 0.35),
        solubles_to_pressate_frac=prA.get("solubles_to_pressate_frac", 1.0),
        power_kWh_per_dry_ton_TS=prA.get("power_kWh_per_dry_ton_TS", None),
        capex_model=prA.get("capex_model", None),
        ref_capacity_tph_wet=(prA.get("ref_capacity_tph_wet") or 50.0),
        capex_installed_ref_usd=(prA.get("capex_installed_ref_usd") or 5e6),
        scale_exponent=(prA.get("scale_exponent") or 0.6),
        F_BM=(prA.get("F_BM") or 1.0),
    )

    ML = Mill(
        "ML",
        ins=PR-0,
        outs=("milled_biomass", "milling_losses"),
        loss_frac=mlA.get("loss_frac", 0.15),
        power_kWh_per_dry_ton_dry=mlA.get("power_kWh_per_dry_ton_dry", None),
        capex_model=mlA.get("capex_model", None),
        ref_capacity_dry_ton_per_hr=mlA.get("ref_capacity_dry_ton_per_hr", 10.0),
        purchase_cost_ref_usd=mlA.get("purchase_cost_ref_usd", 206400.0),
        install_factor=mlA.get("install_factor", 1.8),
        scale_exponent=mlA.get("scale_exponent", 0.6),
        F_BM=mlA.get("F_BM", 1.0),
    )

    # --- Acidogenic digester assumptions ---
    vfaS = A["vfa_ad"]
    vfaP = A["vfa_ad_performance"]
    hrt_days = vfaS["hrt_days"]

    AD = AcidogenicDigester(
        "VFA_AD",
        ins=ML-0,
        outs=("offgas", "digestate", "vfa_product"),

        # performance
        vs_destruction=float(vfaP.get("vs_destruction", 0.50)),
        vfa_kg_per_kg_vs_destroyed=float(vfaP.get("vfa_kg_per_kg_vs_destroyed", 0.80)),
        vfa_split=vfaP.get("vfa_split", None),
        vfa_recovery=float(vfaP.get("vfa_recovery", 0.90)),
        produce_offgas_co2=bool(vfaP.get("produce_offgas_co2", False)),

        # sizing
        hrt_days=hrt_days,
        slurry_density_kg_per_m3=float(vfaS.get("slurry_density_kg_per_m3", 1000.0)),
        headspace_frac=float(vfaS.get("gas_storage_frac_of_total_volume", 0.2)),
        max_single_digester_volume_MG=float(vfaS.get("max_single_digester_volume_MG", 1.5)),

        # utilities
        mixing_W_per_m3=float(vfaS.get("mixing_W_per_m3", 5.0)),
        influent_temperature_K=float(vfaS.get("influent_temperature_K", 298.15)),
        target_temperature_K=float(vfaS.get("target_temperature_K", 308.15)),
        cp_kJ_per_kgK=float(vfaS.get("cp_kJ_per_kgK", 4.18)),

        # heat shock scenario
        enable_heat_shock=enable_heat_shock,
        hs_target_temperature_K=hs_target_temperature_K,
        hs_events_per_day=hs_events_per_day,
        hs_heated_fraction_of_liquid=hs_heated_fraction_of_liquid,
        hs_duration_min=hs_duration_min,
    )

    # Post-digestion solid/liquid separation
    sp = A.get("digestate_screw_press", {})
    SP = DigestateScrewPress(
        ID="SP",
        ins=AD-1,  # digestate
        outs=("soil_amendment", "liquid_digestate"),
        solids_IDs=["Ash","Protein","Lignin","Glucan","Xylan","Mannan","Galactan","Arabinan",
                     "Alginate","Fucoidan","Mannitol","OtherSolids"],
        ts_capture_frac=sp.get("ts_capture_frac", 0.33),
        cake_moisture_frac=sp.get("cake_moisture_frac", 0.77),
        capacity_tph_each=sp.get("capacity_tph_each", 6.0),
        kWh_per_m3=sp.get("kWh_per_m3", 0.67),
        eur_to_usd=sp.get("eur_to_usd", 1.0),
        capex_eur_table=sp.get("capex_eur_table", None),
        include_polymer_dosing=sp.get("include_polymer_dosing", False),
        polymer_dosing_cost_eur_each=sp.get("polymer_dosing_cost_eur_each", 0.0),
        F_BM=sp.get("F_BM", 1.0),
    )

    # Return system
    return bst.System("VFA_AD_sys", path=(PR, ML, AD, SP))