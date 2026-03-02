"""

Ethanol-only fermentation flowsheet with:
- optional upstream + post-pretreatment dewatering (ScrewPress) with feasible-moisture fallback
- optional conversion of alginate/fucoidan/mannitol -> glucose/xylose (mass bookkeeping)
- optional stripping of mostly-water auxiliary inlets in the fermentation template
"""

from __future__ import annotations

import biosteam as bst
import thermosteam as tmo

from biorefineries import cellulosic
from biorefineries.ethanol import create_ethanol_purification_system
from biorefineries.tea import create_cellulosic_ethanol_tea
from biosteam.units.solids_separation import ScrewPress
from thermosteam.exceptions import InfeasibleRegion


# -----------------------------
# Small helpers
# -----------------------------

def ensure_chemical(chems: bst.Chemicals, chem_id: str, *, phase: str, MW: float = 1.0) -> None:
    if chem_id in chems:
        return
    chems.append(bst.Chemical(chem_id, search_db=False, default=True, phase=phase, MW=MW))


def clamp_heat_exchanger_target(pretreatment_sys: bst.System, hx_id: str = "H201") -> None:
    hx = next((u for u in pretreatment_sys.units if u.ID == hx_id), None)
    if hx is None:
        return

    original_run = hx._run

    def _run():
        Tin = hx.ins[0].T
        target = getattr(hx, "T", Tin - 1.0)
        hx.T = min(target, Tin - 1.0)
        original_run()
        if hx.outs[0].T > Tin - 1.0:
            hx.outs[0].T = Tin - 1.0

    hx._run = _run


def water_wt(s: bst.Stream) -> float:
    if not s.F_mass or "Water" not in s.chemicals:
        return float("nan")
    return float(s.imass["Water"] / s.F_mass)


def zero_mostly_water_aux_inlets(sys: bst.System, *, threshold: float = 0.95, debug: bool = False) -> None:
    # Keep sys.ins[0] as main feed, clear other inlets that are basically water
    for i, s in enumerate(sys.ins):
        if i == 0:
            continue
        if s.F_mass <= 0 or "Water" not in s.chemicals:
            continue
        wt = float(s.imass["Water"] / s.F_mass)
        if wt >= threshold:
            if debug:
                print(f"Zeroing aux inlet {i}: {s.ID} (water wt%={wt:.3f})")
            s.empty()


def simulate_screwpress_with_fallback(
    press: ScrewPress,
    target_moisture: float,
    *,
    lo: float = 0.50,
    hi: float = 0.95,
    max_iter: int = 20,
    debug: bool = False,
) -> float:
    """
    Try to hit target moisture_content (water mass fraction in cake).
    If infeasible, back off to the closest feasible value (usually wetter).
    Returns the moisture_content actually used (or NaN if unconstrained fallback).
    """
    target = float(min(max(target_moisture, lo), hi))

    def try_m(x: float) -> bool:
        press.moisture_content = float(x)
        try:
            press.simulate()
            return True
        except InfeasibleRegion:
            return False

    # First attempt: requested target
    if try_m(target):
        return float(press.moisture_content)

    if debug:
        print(f"[{press.ID}] target moisture_content={target:.3f} infeasible; searching fallback")

    # Common failure mode: too dry => try wetter
    if try_m(hi):
        a, b = target, hi
        best = hi
        for _ in range(max_iter):
            m = 0.5 * (a + b)
            if try_m(m):
                best = m
                b = m
            else:
                a = m
        press.moisture_content = best
        press.simulate()
        if debug:
            print(f"[{press.ID}] using moisture_content={best:.4f}")
        return float(best)

    # If even hi fails, try any feasible on [lo, target]
    if try_m(lo):
        a, b = lo, target
        best = lo
        for _ in range(max_iter):
            m = 0.5 * (a + b)
            if try_m(m):
                best = m
                a = m
            else:
                b = m
        press.moisture_content = best
        press.simulate()
        if debug:
            print(f"[{press.ID}] using moisture_content={best:.4f}")
        return float(best)

    # Last resort: no moisture constraint
    press.moisture_content = None
    press.simulate()
    if debug:
        print(f"[{press.ID}] WARNING: no feasible moisture_content; ran unconstrained")
    return float("nan")


# -----------------------------
# Splits
# -----------------------------

def build_feed_dewatering_split(*, keep_solids: float = 0.995, keep_solubles: float = 0.90) -> dict[str, float]:
    # IMPORTANT: do not include "Water" if you are using moisture_content.
    return {
        "Ash": keep_solids,
        "Protein": keep_solids,
        "Lignin": keep_solids,
        "OtherSolids": keep_solids,
        "Glucan": keep_solids,
        "Xylan": keep_solids,
        "Mannan": keep_solids,
        "Galactan": keep_solids,
        "Arabinan": keep_solids,
        "Alginate": keep_solids,
        "Fucoidan": keep_solids,
        "Mannitol": keep_solubles,
        "Glucose": keep_solubles,
        "Xylose": keep_solubles,
        "Arabinose": keep_solubles,
    }


def build_post_pretreatment_dewatering_split(*, keep_solids: float = 0.995, keep_solubles: float = 0.85) -> dict[str, float]:
    # IMPORTANT: do not include "Water" if you are using moisture_content.
    return {
        "Ash": keep_solids,
        "Protein": keep_solids,
        "Lignin": keep_solids,
        "OtherSolids": keep_solids,
        "Glucan": keep_solids,
        "Xylan": keep_solids,
        "Mannan": keep_solids,
        "Galactan": keep_solids,
        "Arabinan": keep_solids,
        "Alginate": keep_solids,
        "Fucoidan": keep_solids,
        "Mannitol": keep_solubles,
        "Glucose": keep_solubles,
        "Xylose": keep_solubles,
        "Arabinose": keep_solubles,
    }


# -----------------------------
# Stream transforms
# -----------------------------

def solubilize_seaweed_pools(
    stream: bst.Stream,
    *,
    solubilization: float,
    alginate_id: str = "Alginate",
    fucoidan_id: str = "Fucoidan",
    pool_id: str = "SeaweedFermentables",
) -> None:
    if solubilization <= 0:
        return

    for src in (alginate_id, fucoidan_id):
        if src not in stream.chemicals:
            continue
        m = float(stream.imass[src]) * float(solubilization)
        if m > 0:
            stream.imass[src] -= m
            stream.imass[pool_id] += m


def convert_seaweed_to_sugars(
    s: bst.Stream,
    *,
    X_alginate: float,
    X_fucoidan: float,
    X_mannitol: float,
    frac_to_xylose: float,
) -> None:
    """
    Mass-bookkeeping conversion (not stoichiometric):
    Alginate/Fucoidan/Mannitol -> Glucose (+ optional Xylose fraction).
    """
    def take(ID: str, X: float) -> float:
        if ID not in s.chemicals:
            return 0.0
        m = float(s.imass[ID])
        dm = m * float(X)
        if dm > 0:
            s.imass[ID] -= dm
        return dm

    dm = take("Alginate", X_alginate) + take("Fucoidan", X_fucoidan) + take("Mannitol", X_mannitol)
    if dm <= 0:
        return

    f = float(frac_to_xylose)
    f = 0.0 if f < 0 else 1.0 if f > 1 else f
    dm_xyl = dm * f
    dm_glc = dm - dm_xyl

    if "Glucose" in s.chemicals:
        s.imass["Glucose"] += dm_glc
    if dm_xyl > 0 and "Xylose" in s.chemicals:
        s.imass["Xylose"] += dm_xyl


def select_wet_ethanol(purif_sys: bst.System) -> bst.Stream:
    wet = None
    best = -1.0
    for s in purif_sys.outs:
        if "Ethanol" not in s.chemicals or s.F_mass <= 0:
            continue
        purity = float(s.imass["Ethanol"] / s.F_mass)
        if purity > best:
            best = purity
            wet = s
    if wet is None:
        raise RuntimeError("Purification produced no stream containing ethanol.")
    wet.ID = "wet_ethanol"
    return wet


def select_stillage(purif_sys: bst.System, *, exclude: bst.Stream) -> bst.Stream | None:
    stillage = None
    best_w = -1.0
    for s in purif_sys.outs:
        if s is exclude:
            continue
        if "Water" in s.chemicals:
            w = float(s.imass["Water"])
            if w > best_w:
                best_w = w
                stillage = s
    if stillage is not None:
        stillage.ID = "stillage"
    return stillage


# -----------------------------
# Main builder
# -----------------------------

def create_ethanol_fermentation_system(
    *,
    debug: bool = False,

    # Feedstock
    feedstock_price: float = 0.0,

    # ScrewPress cake moisture_content (water mass fraction)
    feed_dewatering_moisture: float = 0.60,
    dewatering_moisture: float = 0.60,

    # Keep solubles with cake (since you are not fermenting pressate in this flowsheet)
    keep_feed_solubles: float = 0.85,
    keep_post_solubles: float = 0.85,

    # Optional pool bookkeeping
    seaweed_solubilization: float = 0.0,

    # Seaweed -> sugars conversion knobs (THIS is what you sweep)
    X_alginate_to_sugars: float = 0.90,
    X_fucoidan_to_sugars: float = 0.90,
    X_mannitol_to_sugars: float = 0.95,
    frac_seaweed_sugars_to_xylose: float = 0.0,

    # Dehydration
    dehydr_eth_to_product: float = 0.995,
    dehydr_water_to_product: float = 0.005,

    # Fermentation template dilution control
    strip_ferm_aux_water: bool = True,
    aux_water_threshold: float = 0.95,
):
    # Isolated flowsheet to avoid collisions
    fs = bst.Flowsheet("ethanol_fs")
    bst.main_flowsheet.set_flowsheet(fs)
    fs.clear()

    # Thermo
    cellulosic.load_process_settings()
    base = cellulosic.create_cellulosic_ethanol_chemicals()
    thermo = bst.Chemicals(list(base))

    ensure_chemical(thermo, "Alginate", phase="s", MW=1.0)
    ensure_chemical(thermo, "Fucoidan", phase="s", MW=1.0)
    ensure_chemical(thermo, "Mannitol", phase="l", MW=182.17)
    ensure_chemical(thermo, "SeaweedFermentables", phase="l", MW=1.0)
    ensure_chemical(thermo, "OtherSolids", phase="s", MW=1.0)

    thermo.compile()
    bst.settings.set_thermo(thermo)
    tmo.settings.set_thermo(thermo)

    if debug:
        print("Thermo set? bst:", bst.settings.thermo is not None, "tmo:", tmo.settings.thermo is not None)

    # Feedstock (wet Sargassum proxy)
    feedstock = bst.Stream(
        "feedstock",
        total_flow=104229.16,
        units="kg/hr",
        price=float(feedstock_price),
        Water=0.85,
        Ash=0.0720,
        Protein=0.0090,
        Lignin=0.0003,
        Glucan=0.01146,
        Xylan=0.000705,
        Mannan=0.000705,
        Galactan=0.001665,
        Arabinan=0.0,
        Alginate=0.00987,
        Fucoidan=0.00321,
        Mannitol=0.007785,
        OtherSolids=0.0333,
    )

    # Feed handling
    U101 = cellulosic.units.FeedStockHandling("U101", feedstock)
    U101.cost_items["System"].cost = 0.0
    U101.simulate()

    if debug:
        print("Feedstock F_mass:", feedstock.F_mass, "water wt%:", water_wt(feedstock))
        print("U101 out F_mass:", U101.outs[0].F_mass, "water wt%:", water_wt(U101.outs[0]))

    # Upstream dewatering
    U_DW0 = ScrewPress(
        "U_DW0",
        ins=U101 - 0,
        outs=("feed_dewatered_cake", "feed_pressate"),
        split=build_feed_dewatering_split(keep_solubles=keep_feed_solubles),
        moisture_content=float(feed_dewatering_moisture),
    )
    used_m0 = simulate_screwpress_with_fallback(U_DW0, feed_dewatering_moisture, debug=debug)
    feed_cake, feed_pressate = U_DW0.outs

    if debug:
        print("\n=== Upstream dewatering (U_DW0) ===")
        print("Target moisture:", feed_dewatering_moisture, "used:", used_m0)
        print("Feed cake F_mass:", feed_cake.F_mass, "water wt%:", water_wt(feed_cake))
        print("Feed pressate F_mass:", feed_pressate.F_mass, "water wt%:", water_wt(feed_pressate))

    # Pretreatment (on dewatered cake)
    pretreatment_sys = cellulosic.create_dilute_acid_pretreatment_system(ins=feed_cake, area=200, mockup=False)
    clamp_heat_exchanger_target(pretreatment_sys, "H201")
    pretreatment_sys.simulate()

    pretreated = pretreatment_sys.get_outlet("pretreated_biomass") or pretreatment_sys.outs[0]
    pretreated.ID = "sabre_pretreated_biomass"

    if debug:
        print("\n=== Pretreatment ===")
        print("Pretreated F_mass:", pretreated.F_mass, "water wt%:", water_wt(pretreated))

    # Seaweed -> sugars (simple bookkeeping unit)
    U_SW2S = bst.Unit("U_SW2S", ins=pretreated, outs=("pretreated_with_sugars",))

    def _run_sw2s():
        out = U_SW2S.outs[0]
        out.copy_like(U_SW2S.ins[0])

        convert_seaweed_to_sugars(
            out,
            X_alginate=float(X_alginate_to_sugars),
            X_fucoidan=float(X_fucoidan_to_sugars),
            X_mannitol=float(X_mannitol_to_sugars),
            frac_to_xylose=float(frac_seaweed_sugars_to_xylose),
        )

    U_SW2S._run = _run_sw2s
    U_SW2S._design = lambda: None
    U_SW2S._cost = lambda: None
    U_SW2S.simulate()
    pretreated2 = U_SW2S.outs[0]

    # Post-pretreatment dewatering
    U_DW = ScrewPress(
        "U_DW",
        ins=pretreated2,
        outs=("dewatered_cake", "pressate"),
        split=build_post_pretreatment_dewatering_split(keep_solubles=keep_post_solubles),
        moisture_content=float(dewatering_moisture),
    )
    used_m1 = simulate_screwpress_with_fallback(U_DW, dewatering_moisture, debug=debug)
    cake, pressate = U_DW.outs

    if debug:
        print("\n=== Dewatering (U_DW) ===")
        print("Target moisture:", dewatering_moisture, "used:", used_m1)
        print("Cake F_mass:", cake.F_mass, "water wt%:", water_wt(cake))
        print("Pressate F_mass:", pressate.F_mass, "water wt%:", water_wt(pressate))

    solubilize_seaweed_pools(cake, solubilization=float(seaweed_solubilization))

    # Fermentation template
    fermentation_sys = cellulosic.create_cellulosic_fermentation_system(ins=cake, area=300, mockup=False, kind="SCF")
    if strip_ferm_aux_water:
        zero_mostly_water_aux_inlets(fermentation_sys, threshold=float(aux_water_threshold), debug=debug)
    fermentation_sys.simulate()

    vent = fermentation_sys.get_outlet("vent") or (fermentation_sys - 0)
    beer_raw = fermentation_sys.get_outlet("beer") or (fermentation_sys - 1)
    lignin = fermentation_sys.get_outlet("lignin") or (fermentation_sys - 2)

    if debug:
        gx = 0.0
        if "Glucose" in beer_raw.chemicals:
            gx += float(beer_raw.imass["Glucose"])
        if "Xylose" in beer_raw.chemicals:
            gx += float(beer_raw.imass["Xylose"])
        print("\n=== Beer after fermentation ===")
        print("Beer F_mass:", beer_raw.F_mass, "water wt%:", water_wt(beer_raw))
        print("Ethanol (kg/hr):", float(beer_raw.imass["Ethanol"]) if "Ethanol" in beer_raw.chemicals else 0.0)
        print("Glucose+Xylose (kg/hr):", gx)

    # Purification
    ethanol_placeholder = bst.Stream("ethanol")
    purif_sys = create_ethanol_purification_system(ins=beer_raw, outs=[ethanol_placeholder], area=400, mockup=False)
    purif_sys.simulate()

    wet_ethanol = select_wet_ethanol(purif_sys)

    # Dehydration: default everything to recycle unless specified
    ethanol_prod = bst.Stream("ethanol")
    recycle_process_water = bst.Stream("recycle_process_water_dehyd")

    split = {ID: 0.0 for ID in wet_ethanol.chemicals.IDs}
    if "Ethanol" in split:
        split["Ethanol"] = float(dehydr_eth_to_product)
    if "Water" in split:
        split["Water"] = float(dehydr_water_to_product)

    U_DEHYD = bst.units.Splitter(
        "U_DEHYD",
        ins=wet_ethanol,
        outs=(ethanol_prod, recycle_process_water),
        split=split,
    )
    U_DEHYD.simulate()

    stillage = select_stillage(purif_sys, exclude=wet_ethanol)

    # Facilities
    bst.create_all_facilities(
        feedstock,
        recycle_process_water_streams=[recycle_process_water],
        HXN=False,
        area=600,
    )

    # System
    all_units = (
        U101,
        U_DW0,
        *pretreatment_sys.units,
        U_SW2S,
        U_DW,
        *fermentation_sys.units,
        *purif_sys.units,
        U_DEHYD,
    )

    system = bst.System("Ethanol_Fermentation_sys", path=all_units)
    tea = create_cellulosic_ethanol_tea(system)

    key_streams = {
        "feedstock": feedstock,
        "feed_dewatered_cake": feed_cake,
        "feed_pressate": feed_pressate,
        "pretreated_biomass": pretreated,
        "pretreated_with_sugars": pretreated2,
        "dewatered_cake": cake,
        "pressate": pressate,
        "beer_raw": beer_raw,
        "vent": vent,
        "lignin": lignin,
        "stillage": stillage,
        "wet_ethanol": wet_ethanol,
        "ethanol": ethanol_prod,
        "recycle_process_water": recycle_process_water,
    }

    subsystems = {
        "pretreatment": pretreatment_sys,
        "fermentation": fermentation_sys,
        "purification": purif_sys,
    }

    return system, tea, key_streams, subsystems