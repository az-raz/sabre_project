from __future__ import annotations

import biosteam as bst
import thermosteam as tmo

from sabre.units.htl import HTLFeedConditioner, HTLReactor, HTLPhaseSeparator


def _get_htl_case_config(assumptions: dict, case_name: str) -> dict:
    case = assumptions["htl_performance"]["cases"][case_name]

    return {
        "target_solids_wt_frac": case["target_solids_wt_frac"],
        "temperature_C": case["temperature_C"],
        "pressure_bar": case["pressure_bar"],
        "residence_time_min": case["residence_time_min"],
        "biocrude_yield_wt_frac_dry": case["biocrude_yield_wt_frac_dry"],
        "aqueous_yield_wt_frac_dry": case["aqueous_yield_wt_frac_dry"],
        "gas_yield_wt_frac_dry": case["gas_yield_wt_frac_dry"],
        "char_yield_wt_frac_dry": case["char_yield_wt_frac_dry"],
        "slurry_density_kg_per_m3": case["slurry_density_kg_per_m3"],
    }


def _get_htl_separation_config(assumptions: dict) -> dict:
    sep = assumptions["htl_separation"]

    return {
        "biocrude_recovery_to_oil": sep["biocrude_recovery_to_oil"],
        "aqueous_org_recovery_to_aqueous": sep["aqueous_org_recovery_to_aqueous"],
        "char_recovery_to_solids": sep["char_recovery_to_solids"],
        "gas_recovery_to_gas": sep["gas_recovery_to_gas"],
        "oil_water_to_oil_frac": sep["oil_water_to_oil_frac"],
    }


def create_htl_system(
    assumptions: dict,
    case_name: str = "continuous_mexican_sargassum",
    ID: str = "htl_sys",
    feed: tmo.Stream | None = None,
    makeup_water: tmo.Stream | None = None,
):
    """
    Minimal HTL pathway:
        feed -> conditioner -> reactor -> separator

    Returns
    -------
    sys : bst.System
    streams : dict[str, tmo.Stream]
    """
    case_cfg = _get_htl_case_config(assumptions, case_name)
    sep_cfg = _get_htl_separation_config(assumptions)

    if feed is None:
        feed = tmo.Stream(
            "htl_feed",
            Water=8673.0,
            Ash=460.0,
            Glucan=120.0,
            Xylan=40.0,
            Mannan=25.0,
            Galactan=20.0,
            Arabinan=10.0,
            Alginate=310.0,
            Fucoidan=85.0,
            Mannitol=110.0,
            Protein=90.0,
            OtherSolids=57.0,
            units="kg/hr",
        )

    if makeup_water is None:
        makeup_water = tmo.Stream(
            "htl_makeup_water",
            Water=1e6,
            units="kg/hr",
        )

    conditioned_slurry = tmo.Stream("htl_conditioned_slurry")
    removed_water = tmo.Stream("htl_removed_water")
    htl_effluent = tmo.Stream("htl_effluent")

    gas = tmo.Stream("htl_gas")
    biocrude = tmo.Stream("htl_biocrude")
    aqueous = tmo.Stream("htl_aqueous")
    solids = tmo.Stream("htl_solids")

    U100 = HTLFeedConditioner(
        "U100",
        ins=(feed, makeup_water),
        outs=(conditioned_slurry, removed_water),
        target_solids_wt_frac=case_cfg["target_solids_wt_frac"],
    )

    R200 = HTLReactor(
        "R200",
        ins=U100 - 0,
        outs=(htl_effluent,),
        temperature_C=case_cfg["temperature_C"],
        pressure_bar=case_cfg["pressure_bar"],
        residence_time_min=case_cfg["residence_time_min"],
        biocrude_yield_wt_frac_dry=case_cfg["biocrude_yield_wt_frac_dry"],
        aqueous_yield_wt_frac_dry=case_cfg["aqueous_yield_wt_frac_dry"],
        gas_yield_wt_frac_dry=case_cfg["gas_yield_wt_frac_dry"],
        char_yield_wt_frac_dry=case_cfg["char_yield_wt_frac_dry"],
        slurry_density_kg_per_m3=case_cfg["slurry_density_kg_per_m3"],
    )

    S300 = HTLPhaseSeparator(
        "S300",
        ins=R200 - 0,
        outs=(gas, biocrude, aqueous, solids),
        biocrude_recovery_to_oil=sep_cfg["biocrude_recovery_to_oil"],
        aqueous_org_recovery_to_aqueous=sep_cfg["aqueous_org_recovery_to_aqueous"],
        char_recovery_to_solids=sep_cfg["char_recovery_to_solids"],
        gas_recovery_to_gas=sep_cfg["gas_recovery_to_gas"],
        oil_water_to_oil_frac=sep_cfg["oil_water_to_oil_frac"],
    )

    sys = bst.System(ID, path=(U100, R200, S300))

    streams = {
        "feed": feed,
        "makeup_water": makeup_water,
        "conditioned_slurry": conditioned_slurry,
        "removed_water": removed_water,
        "htl_effluent": htl_effluent,
        "gas": gas,
        "biocrude": biocrude,
        "aqueous": aqueous,
        "solids": solids,
    }

    return sys, streams
