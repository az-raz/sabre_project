"""
Integrated Sargassum Biorefinery System Builder
================================================
Shared preprocessing (Press → PC → Mill) then splits milled biomass:
  alpha     → Methanogenic AD pathway → biomethane
  (1-alpha) → VFA fermentation pathway → microbial oil

Edge cases handled cleanly:
  alpha=0.0 → pure VFA-to-oil  (methanogenic pathway not built)
  alpha=1.0 → pure biomethane  (VFA/fermentation pathway not built)

Returns (sys, streams, units, alpha).
"""

from __future__ import annotations

import biosteam as bst

from sabre.config import load_assumptions, get_quality_params, get_scale_feed_kgph
from sabre.streams import make_sargassum_feed
from sabre.units.press import Press
from sabre.units.mill import Mill
from sabre.units.pressate_concentrator import PressateConcentrator
from sabre.units.ad import AnaerobicDigester
from sabre.units.biogas_upgrading import BiogasUpgrading
from sabre.units.h2s_removal import H2SRemoval
from sabre.units.screwpress import DigestateScrewPress
from sabre.units.enzymatic_pretreatment import EnzymaticPretreatment
from sabre.units.heating_pretreatment import HeatingPretreatment
from sabre.units.peroxide_pretreatment import PeroxidePretreatment
from sabre.systems.vfa_system import create_vfa_ad_system
from sabre.systems.vfa_fermentation_system import create_vfa_fermentation_system


SOLIDS_IDS = [
    "Ash", "Protein", "Lignin", "Glucan", "Xylan", "Mannan", "Galactan", "Arabinan",
    "Alginate", "Fucoidan", "Mannitol", "OtherSolids",
]


def _get_stream(stream_id: str):
    """Safe stream lookup — returns None if not in registry."""
    try:
        return bst.main_flowsheet.stream[stream_id]
    except Exception:
        return None


def _get_unit(unit_id: str):
    """Safe unit lookup — returns None if not in registry."""
    try:
        return bst.main_flowsheet.unit[unit_id]
    except Exception:
        return None


class MassSplitter(bst.Unit):
    """
    Splits all components by the same mass fraction.
    outs[0] gets fraction alpha (→ methanogenic AD).
    outs[1] gets fraction (1-alpha) (→ VFA fermentation).
    """
    _N_ins = 1
    _N_outs = 2

    def __init__(self, ID="", ins=None, outs=(), alpha=0.5, **kwargs):
        super().__init__(ID, ins, outs, **kwargs)
        self.alpha = float(alpha)

    def _run(self):
        feed = self.ins[0]
        to_methane, to_vfa = self.outs
        to_methane.empty()
        to_vfa.empty()
        to_methane.phase = feed.phase
        to_vfa.phase = feed.phase
        alpha = min(max(self.alpha, 0.0), 1.0)
        for cid in feed.chemicals.IDs:
            m = float(feed.imass[cid])
            to_methane.imass[cid] = alpha * m
            to_vfa.imass[cid] = (1.0 - alpha) * m

    def _design(self):
        self.design_results["Alpha (to methane AD)"] = self.alpha
        self.design_results["Alpha (to VFA oil)"] = 1.0 - self.alpha

    def _cost(self):
        pass


def _build_methane_pathway(A, ad_feed_in, pretreatment_case):
    """Build AD → H2SR → UP → SP_AD. Returns (units_list, streams_dict)."""
    adS   = A["ad"]
    adp   = A["ad_performance"]
    adC   = A["ad_costing"]
    pretreatments = A.get("ad_pretreatment_cases", {})

    vs_destruction       = float(adp.get("vs_destruction", 0.20))
    ch4_kg_per_kg_vs_fed = float(adp.get("ch4_kg_per_kg_vs_fed", 0.10))
    raw_biogas_molfrac   = dict(adp.get("raw_biogas_molfrac", {
        "Methane": 0.55, "CarbonDioxide": 0.43, "HydrogenSulfide": 0.02,
    }))
    biodegradability = dict(adp.get("biodegradability", {}))

    pt_case    = pretreatments.get(pretreatment_case, {})
    ad_effects = pt_case.get("ad_effects", {})
    vs_destruction       = float(ad_effects.get("vs_destruction",       vs_destruction))
    ch4_kg_per_kg_vs_fed = float(ad_effects.get("ch4_kg_per_kg_vs_fed", ch4_kg_per_kg_vs_fed))
    # Per-case biogas composition overrides global default (Chikani-Cabrera et al. 2022)
    _global_molfrac = adp.get("raw_biogas_molfrac", {
        "Methane": 0.55, "CarbonDioxide": 0.43, "HydrogenSulfide": 0.02,
    })
    raw_biogas_molfrac = dict(ad_effects.get("raw_biogas_molfrac", _global_molfrac))

    pt_kind = pt_case.get("kind", "none")

    path_units = []
    ad_feed = ad_feed_in  # will be updated as pretreatment units are chained

    # -------------------------
    # Pretreatment units (mirrors ad_biogas_system.py exactly)
    # -------------------------
    if pt_kind == "none":
        pass

    elif pt_kind == "heating":
        hA = pt_case.get("heating", {})
        HT = HeatingPretreatment(
            "HT", ins=ad_feed, outs=("heated_biomass",),
            target_temperature_K=hA.get("target_temperature_K", 338.15),
            residence_time_hr=hA.get("residence_time_hr", 0.25),
            slurry_density_kg_per_m3=A["ad"].get("slurry_density_kg_per_m3", 1000.0),
            cp_kJ_per_kgK=A["ad"].get("cp_kJ_per_kgK", 4.18),
            capex_usd=hA.get("capex_usd", 0.0),
            maintenance_frac_of_capex_per_yr=hA.get("maintenance_frac_of_capex_per_yr", 0.035),
        )
        ad_feed = HT - 0
        path_units.append(HT)

    elif pt_kind == "enzymatic":
        eA = pt_case.get("enzymatic", {})
        EZ = EnzymaticPretreatment(
            "EZ", ins=ad_feed, outs=("enzyme_treated_biomass",),
            temperature_K=eA.get("temperature_K", 308.15),
            residence_time_hr=eA.get("residence_time_hr", 24.0),
            enzyme_dose_kg_per_kg_dry_feed=eA.get("enzyme_dose_kg_per_kg_dry_feed", 0.02),
            treated_fraction=eA.get("treated_fraction", 1.0),
            enzyme_recycle_factor=eA.get("enzyme_recycle_factor", 1.0),
            slurry_density_kg_per_m3=A["ad"].get("slurry_density_kg_per_m3", 1000.0),
            capex_usd=eA.get("capex_usd", 0.0),
            enzyme_price_usd_per_kg=eA.get("enzyme_price_usd_per_kg", 7.0),
            maintenance_frac_of_capex_per_yr=eA.get("maintenance_frac_of_capex_per_yr", 0.035),
        )
        ad_feed = EZ - 0
        path_units.append(EZ)

    elif pt_kind == "peroxide":
        pA = pt_case.get("peroxide", {})
        PX = PeroxidePretreatment(
            "PX", ins=ad_feed, outs=("peroxide_treated_biomass",),
            h2o2_wt_frac_on_dry_feed=pA.get("h2o2_wt_frac_on_dry_feed", 0.025),
            temperature_K=pA.get("temperature_K", 298.15),
            residence_time_hr=pA.get("residence_time_hr", 2.0),
            slurry_density_kg_per_m3=A["ad"].get("slurry_density_kg_per_m3", 1000.0),
            capex_usd=pA.get("capex_usd", 0.0),
            h2o2_price_usd_per_kg=pA.get("h2o2_price_usd_per_kg", 0.37),
            maintenance_frac_of_capex_per_yr=pA.get("maintenance_frac_of_capex_per_yr", 0.035),
        )
        ad_feed = PX - 0
        path_units.append(PX)

    elif pt_kind == "combined_PE":
        pA = pretreatments.get("peroxide", {}).get("peroxide", {})
        eA = pretreatments.get("enzymatic", {}).get("enzymatic", {})
        PX = PeroxidePretreatment(
            "PX", ins=ad_feed, outs=("peroxide_treated_biomass",),
            h2o2_wt_frac_on_dry_feed=pA.get("h2o2_wt_frac_on_dry_feed", 0.025),
            temperature_K=pA.get("temperature_K", 298.15),
            residence_time_hr=pA.get("residence_time_hr", 2.0),
            slurry_density_kg_per_m3=A["ad"].get("slurry_density_kg_per_m3", 1000.0),
            capex_usd=pA.get("capex_usd", 0.0),
            h2o2_price_usd_per_kg=pA.get("h2o2_price_usd_per_kg", 0.37),
            maintenance_frac_of_capex_per_yr=pA.get("maintenance_frac_of_capex_per_yr", 0.035),
        )
        EZ = EnzymaticPretreatment(
            "EZ", ins=PX - 0, outs=("combined_PE_treated_biomass",),
            temperature_K=eA.get("temperature_K", 308.15),
            residence_time_hr=eA.get("residence_time_hr", 24.0),
            enzyme_dose_kg_per_kg_dry_feed=eA.get("enzyme_dose_kg_per_kg_dry_feed", 0.02),
            treated_fraction=eA.get("treated_fraction", 1.0),
            enzyme_recycle_factor=eA.get("enzyme_recycle_factor", 1.0),
            slurry_density_kg_per_m3=A["ad"].get("slurry_density_kg_per_m3", 1000.0),
            capex_usd=eA.get("capex_usd", 0.0),
            enzyme_price_usd_per_kg=eA.get("enzyme_price_usd_per_kg", 7.0),
            maintenance_frac_of_capex_per_yr=eA.get("maintenance_frac_of_capex_per_yr", 0.035),
        )
        ad_feed = EZ - 0
        path_units.extend([PX, EZ])

    elif pt_kind == "combined_PTE":
        pA = pretreatments.get("peroxide", {}).get("peroxide", {})
        hA = pt_case.get("heating", {})
        eA = pretreatments.get("enzymatic", {}).get("enzymatic", {})
        PX = PeroxidePretreatment(
            "PX", ins=ad_feed, outs=("peroxide_treated_biomass",),
            h2o2_wt_frac_on_dry_feed=pA.get("h2o2_wt_frac_on_dry_feed", 0.025),
            temperature_K=pA.get("temperature_K", 298.15),
            residence_time_hr=pA.get("residence_time_hr", 2.0),
            slurry_density_kg_per_m3=A["ad"].get("slurry_density_kg_per_m3", 1000.0),
            capex_usd=pA.get("capex_usd", 0.0),
            h2o2_price_usd_per_kg=pA.get("h2o2_price_usd_per_kg", 0.37),
            maintenance_frac_of_capex_per_yr=pA.get("maintenance_frac_of_capex_per_yr", 0.035),
        )
        HT = HeatingPretreatment(
            "HT", ins=PX - 0, outs=("heated_biomass",),
            target_temperature_K=hA.get("target_temperature_K", 393.15),
            residence_time_hr=hA.get("residence_time_hr", 0.25),
            slurry_density_kg_per_m3=A["ad"].get("slurry_density_kg_per_m3", 1000.0),
            cp_kJ_per_kgK=A["ad"].get("cp_kJ_per_kgK", 4.18),
            capex_usd=hA.get("capex_usd", 0.0),
            maintenance_frac_of_capex_per_yr=hA.get("maintenance_frac_of_capex_per_yr", 0.035),
        )
        EZ = EnzymaticPretreatment(
            "EZ", ins=HT - 0, outs=("combined_PTE_treated_biomass",),
            temperature_K=eA.get("temperature_K", 308.15),
            residence_time_hr=eA.get("residence_time_hr", 24.0),
            enzyme_dose_kg_per_kg_dry_feed=eA.get("enzyme_dose_kg_per_kg_dry_feed", 0.02),
            treated_fraction=eA.get("treated_fraction", 1.0),
            enzyme_recycle_factor=eA.get("enzyme_recycle_factor", 1.0),
            slurry_density_kg_per_m3=A["ad"].get("slurry_density_kg_per_m3", 1000.0),
            capex_usd=eA.get("capex_usd", 0.0),
            enzyme_price_usd_per_kg=eA.get("enzyme_price_usd_per_kg", 7.0),
            maintenance_frac_of_capex_per_yr=eA.get("maintenance_frac_of_capex_per_yr", 0.035),
        )
        ad_feed = EZ - 0
        path_units.extend([PX, HT, EZ])
    enable_feed_dilution      = bool(adS.get("enable_feed_dilution", False))
    target_feed_moisture_frac = float(adS.get("target_feed_moisture_frac", 0.90))

    if enable_feed_dilution:
        dilution_water = bst.Stream("dilution_water")
        MX = bst.Mixer("MX", ins=(ad_feed, dilution_water), outs=("diluted_ad_feed",))

        @MX.add_specification(run=False)
        def _set_dilution():
            f = MX.ins[0]
            total = float(f.F_mass)
            water = float(f.imass["Water"]) if "Water" in f.chemicals else 0.0
            dry   = max(total - water, 0.0)
            water_to_add = (
                max(dry * target_feed_moisture_frac / (1.0 - target_feed_moisture_frac) - water, 0.0)
                if dry > 0.0 else 0.0
            )
            dilution_water.empty()
            dilution_water.imass["Water"] = water_to_add

        ad_feed = MX - 0
        path_units.append(MX)

    AD = AnaerobicDigester(
        "AD",
        ins=ad_feed,
        outs=("biogas_raw", "digestate"),
        vs_destruction=vs_destruction,
        ch4_kg_per_kg_vs_fed=ch4_kg_per_kg_vs_fed,
        raw_biogas_molfrac=raw_biogas_molfrac,
        digestible_IDs=tuple(adp.get("digestible_IDs", [])),
        biodegradability=biodegradability,
        hrt_days=adS["hrt_days"],
        slurry_density_kg_per_m3=adS["slurry_density_kg_per_m3"],
        headspace_frac=adS["gas_storage_frac_of_total_volume"],
        max_single_digester_volume_MG=adS.get("max_single_digester_volume_MG", 1.5),
        base_volume_m3=adC.get("base_volume_m3"),
        base_capex_usd=adC.get("base_capex_usd"),
        maintenance_usd_per_m3_yr=adC.get("maintenance_usd_per_m3_yr"),
        mixing_W_per_m3=adS.get("mixing_W_per_m3", 5.0),
        influent_temperature_K=adS.get("influent_temperature_K", 298.15),
        target_temperature_K=adS.get("temperature_K", 308.15),
        cp_kJ_per_kgK=adS.get("cp_kJ_per_kgK", 4.18),
    )

    h2sA = A.get("h2s_removal", {})
    H2SR = H2SRemoval(
        "H2SR",
        ins=AD - 0,
        outs=("treated_biogas", "spent_h2s_media"),
        h2s_removal_efficiency=h2sA.get("h2s_removal_efficiency", 0.99),
        ref_flow_Nm3ph=h2sA.get("ref_flow_Nm3ph", 1000.0),
        ref_installed_cost_usd=h2sA.get("ref_installed_cost_usd", 400_000.0),
        scale_exponent=h2sA.get("scale_exponent", 0.6),
        reagent_cost_usd_per_Nm3_raw=h2sA.get("reagent_cost_usd_per_Nm3_raw", 0.002),
    )

    upA = A["biogas_upgrading"]
    UP = BiogasUpgrading(
        "UP",
        ins=H2SR - 0,
        outs=("biomethane", "offgas_co2"),
        ch4_recovery=upA["ch4_recovery"],
        co2_removal=upA["co2_removal"],
        electricity_kwh_per_Nm3_raw=upA["electricity_kWh_per_Nm3_raw"],
        capex_usd_per_Nm3ph_raw=upA["capex_usd_per_Nm3ph_raw"],
        maintenance_frac_of_capex_per_yr=upA.get("maintenance_frac_of_capex_per_yr", 0.035),
    )

    sp = A.get("digestate_screw_press", {})
    SP_AD = DigestateScrewPress(
        ID="SP_AD",
        ins=AD - 1,
        outs=("soil_amendment", "liquid_digestate"),
        solids_IDs=SOLIDS_IDS,
        ts_capture_frac=sp.get("ts_capture_frac", 0.40),
        cake_moisture_frac=sp.get("cake_moisture_frac", 0.50),
        capacity_tph_each=sp.get("capacity_tph_each", 6.0),
        kWh_per_m3=sp.get("kWh_per_m3", 0.67),
        eur_to_usd=sp.get("eur_to_usd", 1.19),
        capex_eur_table=sp.get("capex_eur_table"),
        include_polymer_dosing=sp.get("include_polymer_dosing", False),
        polymer_dosing_cost_eur_each=sp.get("polymer_dosing_cost_eur_each", 0.0),
        F_BM=sp.get("F_BM", 1.0),
    )

    path_units.extend([AD, H2SR, UP, SP_AD])

    streams = {
        "biomethane":      _get_stream("biomethane"),
        "offgas_co2":      _get_stream("offgas_co2"),
        "soil_amendment":  _get_stream("soil_amendment"),
        "liquid_digestate":_get_stream("liquid_digestate"),
    }
    units = {"AD": AD, "H2SR": H2SR, "UP": UP, "SP_AD": SP_AD}

    return path_units, streams, units


def _build_vfa_pathway(vfa_stream, ferm_kwargs):
    """Build VFA_AD → SP_VFA → fermentation chain. Returns (units_list, streams_dict, units_dict)."""
    vfa_subsys = create_vfa_ad_system(milled_biomass_stream=vfa_stream)

    vfa_broth = _get_stream("vfa_broth")
    if vfa_broth is None:
        raise RuntimeError(
            "Could not find 'vfa_broth' stream. Check SP_VFA output IDs in vfa_system.py."
        )

    fer_sys, fer_streams, fer_units = create_vfa_fermentation_system(
        vfa_broth=vfa_broth, **ferm_kwargs
    )

    path_units = list(vfa_subsys.units) + list(fer_sys.units)

    streams = {
        "vfa_broth":               vfa_broth,
        "backend_oil":             fer_streams.get("backend_oil"),
        "fermentation_wastewater": fer_streams.get("fermentation_wastewater"),
        "vfa_retentate":           fer_streams.get("vfa_retentate"),
        "acidogenic_residual_solids": _get_stream("acidogenic_residual_solids"),
    }
    units = {
        "VFA_AD": _get_unit("VFA_AD"),
        "SP_VFA": _get_unit("SP_VFA"),
        **fer_units,
    }

    return path_units, streams, units


def create_integrated_biorefinery(
    alpha: float = 0.5,
    quality: str = "pelagic_high_quality",
    pretreatment_case: str = "press_mill_only",
    vfa_conversion: float = 0.85,
    vfa_product_yield: float = 0.45,
    vfa_biomass_yield: float = 0.10,
    vfa_co2_yield: float = 0.20,
    vfa_o2_demand: float = 0.80,
    ferm_residence_time_h: float = 48.0,
    ferm_target_pH: float = 8.0,
    ferm_mgso4_dose: float = 0.49,
    target_oil_and_solids_content: float = 70.0,
):
    """
    Build the full integrated Sargassum biorefinery.

    Parameters
    ----------
    alpha : float in [0, 1]
        Fraction of milled biomass routed to methanogenic AD.
        alpha=0 → pure VFA-to-oil (methane path not built).
        alpha=1 → pure biomethane (VFA path not built).

    Returns
    -------
    sys : bst.System
    streams : dict of key streams (None for streams not built at edge cases)
    units : dict of key units
    alpha : float
    """
    alpha = float(alpha)
    if not (0.0 <= alpha <= 1.0):
        raise ValueError(f"alpha must be in [0, 1], got {alpha}")

    build_methane = alpha > 0.0
    build_vfa     = alpha < 1.0

    A = load_assumptions()
    q = get_quality_params(A, quality)
    fresh_feed_kgph = get_scale_feed_kgph(A)

    # =========================================================
    # SHARED PREPROCESSING: Press → PC → Mill
    # =========================================================
    feed = make_sargassum_feed(
        fresh_feed_kgph=fresh_feed_kgph,
        moisture_frac=q["moisture_frac"],
        quality=quality,
    )

    pp  = A.get("preprocessing", {})
    prA = pp.get("press", {})
    mlA = pp.get("mill", {})

    PR = Press(
        "PR",
        ins=feed,
        outs=("pressed_cake", "pressate"),
        solids_IDs=SOLIDS_IDS,
        solids_capture_frac=prA.get("solids_capture_frac", 0.98),
        cake_solids_wt_frac=prA.get("cake_solids_wt_frac", 0.35),
        solubles_to_pressate_frac=prA.get("solubles_to_pressate_frac", 1.0),
        power_kWh_per_dry_ton_TS=prA.get("power_kWh_per_dry_ton_TS"),
        capex_model=prA.get("capex_model"),
        ref_capacity_tph_wet=(prA.get("ref_capacity_tph_wet") or 50.0),
        capex_installed_ref_usd=(prA.get("capex_installed_ref_usd") or 5e6),
        scale_exponent=(prA.get("scale_exponent") or 0.6),
        F_BM=(prA.get("F_BM") or 1.0),
    )

    pb  = A.get("pressate_biostimulant", {})
    pcA = pb.get("concentrator", {})
    PC  = None
    if pb.get("enabled", False) and pb.get("concentrate_pressate", False):
        PC = PressateConcentrator(
            "PC",
            ins=PR - 1,
            outs=("biostimulant_membrane_concentrate", "pressate_permeate"),
            retained_solute_IDs=tuple(pcA.get(
                "retained_solute_IDs",
                ["Alginate", "Fucoidan", "Mannitol", "Protein", "OtherSolids"],
            )),
            water_recovery_to_permeate=pcA.get("water_recovery_to_permeate", 0.70),
            retained_solute_recovery_to_concentrate=pcA.get(
                "retained_solute_recovery_to_concentrate", 0.95
            ),
            design_flux_L_m2_h=pcA.get("design_flux_L_m2_h", 35.0),
            operating_pressure_bar=pcA.get("operating_pressure_bar", 5.0),
            electricity_kWh_per_m3_feed=pcA.get("electricity_kWh_per_m3_feed", 0.8),
            capex_usd_per_m2=pcA.get("capex_usd_per_m2", 120.0),
            maintenance_frac_of_capex_per_yr=pcA.get(
                "maintenance_frac_of_capex_per_yr", 0.035
            ),
        )

    ML = Mill(
        "ML",
        ins=PR - 0,
        outs=("milled_biomass", "milling_losses"),
        loss_frac=mlA.get("loss_frac", 0.15),
        power_kWh_per_dry_ton_dry=mlA.get("power_kWh_per_dry_ton_dry"),
        capex_model=mlA.get("capex_model"),
        ref_capacity_dry_ton_per_hr=mlA.get("ref_capacity_dry_ton_per_hr", 10.0),
        purchase_cost_ref_usd=mlA.get("purchase_cost_ref_usd", 206400.0),
        install_factor=mlA.get("install_factor", 1.8),
        scale_exponent=mlA.get("scale_exponent", 0.6),
        F_BM=mlA.get("F_BM", 1.0),
    )

    # =========================================================
    # SPLITTER
    # =========================================================
    to_methane_ad = bst.Stream("to_methane_ad")
    to_vfa_ad     = bst.Stream("to_vfa_ad")

    SPL = MassSplitter(
        "SPL",
        ins=ML - 0,
        outs=(to_methane_ad, to_vfa_ad),
        alpha=alpha,
    )

    # =========================================================
    # BUILD PATHWAYS CONDITIONALLY
    # =========================================================
    # ── Read fermentation parameters from YAML ────────────────────────────
    # Caller-supplied arguments take precedence over YAML when they differ
    # from their defaults (same pattern as ad_biogas_system.py).
    vfaF  = A.get("vfa_fermentation", {})
    fc    = vfaF.get("cases", {}).get(vfaF.get("case", "yarrowia_vfa_base"), {})
    mf    = vfaF.get("vfa_microfilter", {})
    fmed  = vfaF.get("fermentation_medium_tank", {})

    _conversion       = vfa_conversion        if vfa_conversion        != 0.85 else fc.get("conversion",                          0.85)
    _product_yield    = vfa_product_yield      if vfa_product_yield      != 0.45 else fc.get("product_yield_kg_per_kg_vfa_consumed", 0.45)
    _biomass_yield    = vfa_biomass_yield      if vfa_biomass_yield      != 0.10 else fc.get("biomass_yield_kg_per_kg_vfa_consumed", 0.10)
    _co2_yield        = vfa_co2_yield          if vfa_co2_yield          != 0.20 else fc.get("co2_yield_kg_per_kg_vfa_consumed",     0.20)
    _o2_demand        = vfa_o2_demand          if vfa_o2_demand          != 0.80 else fc.get("oxygen_kg_per_kg_vfa_consumed",        0.80)
    _res_time         = ferm_residence_time_h  if ferm_residence_time_h  != 48.0 else fc.get("residence_time_h",                    48.0)
    _target_pH        = ferm_target_pH         if ferm_target_pH         != 8.0  else fc.get("target_pH",                           8.0)
    _vfa_perm_frac    = mf.get("vfa_to_permeate_frac",    0.98)
    _water_perm_frac  = mf.get("water_to_permeate_frac",  0.97)
    _solids_perm_frac = mf.get("solids_to_permeate_frac", 0.05)
    _ammonia_dose     = fmed.get("ammonia_dose_kg_per_m3",   0.0)
    _phosphate_dose   = fmed.get("phosphate_dose_kg_per_m3", 0.0)
    _base_dose        = fmed.get("base_dose_kg_per_m3",      0.0)
    # ─────────────────────────────────────────────────────────────────────

    ferm_kwargs = dict(
        product_ID="MicrobialOil",
        conversion=_conversion,
        product_yield_kg_per_kg_vfa_consumed=_product_yield,
        biomass_yield_kg_per_kg_vfa_consumed=_biomass_yield,
        co2_yield_kg_per_kg_vfa_consumed=_co2_yield,
        oxygen_kg_per_kg_vfa_consumed=_o2_demand,
        residence_time_h=_res_time,
        broth_density_kg_per_m3=1000.0,
        target_pH=_target_pH,
        ammonia_dose_kg_per_m3=_ammonia_dose,
        phosphate_dose_kg_per_m3=_phosphate_dose,
        base_dose_kg_per_m3=_base_dose,
        magnesium_sulfate_dose_kg_per_m3=ferm_mgso4_dose,
        seed_water_kgph=0.0,
        seed_cellmass_kgph=0.0,
        vfa_to_permeate_frac=_vfa_perm_frac,
        water_to_permeate_frac=_water_perm_frac,
        solids_to_permeate_frac=_solids_perm_frac,
        dissolved_other_to_permeate_frac=0.90,
        target_oil_and_solids_content=target_oil_and_solids_content,
    )

    methane_units   = []
    methane_streams = {}
    methane_units_d = {}
    if build_methane:
        methane_units, methane_streams, methane_units_d = _build_methane_pathway(
            A, SPL - 0, pretreatment_case
        )

    vfa_units   = []
    vfa_streams = {}
    vfa_units_d = {}
    if build_vfa:
        vfa_units, vfa_streams, vfa_units_d = _build_vfa_pathway(SPL - 1, ferm_kwargs)

    # =========================================================
    # ASSEMBLE FULL SYSTEM
    # =========================================================
    preprocessing = [PR] + ([PC] if PC else []) + [ML]
    all_units = preprocessing + [SPL] + methane_units + vfa_units

    sys = bst.System.from_units("integrated_biorefinery", units=all_units)

    # =========================================================
    # STREAMS DICT
    # =========================================================
    streams = {
        "feed":           feed,
        "milled_biomass": ML.outs[0],
        "to_methane_ad":  to_methane_ad,
        "to_vfa_ad":      to_vfa_ad,
        "biostimulant_membrane_concentrate": (
            _get_stream("biostimulant_membrane_concentrate") if PC else None
        ),
        # Methane pathway (None if alpha=0)
        **{k: methane_streams.get(k) for k in [
            "biomethane", "offgas_co2", "soil_amendment", "liquid_digestate"
        ]},
        # VFA pathway (None if alpha=1)
        **{k: vfa_streams.get(k) for k in [
            "vfa_broth", "backend_oil", "fermentation_wastewater",
            "vfa_retentate", "acidogenic_residual_solids",
        ]},
    }

    units = {
        "PR": PR, "PC": PC, "ML": ML, "SPL": SPL,
        **methane_units_d,
        **vfa_units_d,
    }

    return sys, streams, units, alpha