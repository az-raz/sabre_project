import biosteam as bst
from sabre.systems.ethanol_fermentation_system import create_ethanol_fermentation_system

ETHANOL_DENSITY_KG_L = 0.789
L_PER_GAL = 3.785
HOURS_PER_YEAR = 24 * 365  # BioSTEAM TEA convention


def _ethanol_metrics(stream: bst.Stream):
    if stream is None or stream.F_mass <= 0 or "Ethanol" not in stream.chemicals:
        return 0.0, 0.0, 0.0
    etoh = stream.imass["Ethanol"]
    purity = etoh / stream.F_mass if stream.F_mass else 0.0
    gal_per_hr = (etoh / ETHANOL_DENSITY_KG_L) / L_PER_GAL if etoh > 0 else 0.0
    return etoh, purity, gal_per_hr


def main():
    # Keep debug=False so the builder doesn't spam.
    system, tea, streams, subsystems = create_ethanol_fermentation_system(
        debug=False,
        dewatering_moisture=0.70,
        seaweed_solubilization=0.60,
        seaweed_to_ethanol_yield=0.25,
        mannitol_to_ethanol_yield=0.45,
    )

    system.simulate()

    feedstock = streams["feedstock"]
    beer = streams["beer_to_purification"]
    ethanol = streams["ethanol"]
    stillage = streams.get("stillage")

    beer_etoh, beer_purity, _ = _ethanol_metrics(beer)
    prod_etoh, prod_purity, gal_per_hr = _ethanol_metrics(ethanol)

    # MESP ($/kg of *product stream*), then convert to $/kg EtOH and $/gal EtOH
    mesp_per_kg_stream = tea.solve_price(ethanol)
    if prod_purity > 0:
        mesp_per_kg_etoh = mesp_per_kg_stream / prod_purity
        mesp_per_gal_etoh = mesp_per_kg_etoh * ETHANOL_DENSITY_KG_L * L_PER_GAL
    else:
        mesp_per_kg_etoh = 0.0
        mesp_per_gal_etoh = 0.0

    # Stillage EtOH loss (kg/hr)
    stillage_loss = 0.0
    if stillage is not None and stillage.F_mass > 0 and "Ethanol" in stillage.chemicals:
        stillage_loss = stillage.imass["Ethanol"]

    # Feedstock contribution ($/gal)
    feed_cost_hr = feedstock.F_mass * (feedstock.price or 0.0)
    feed_cost_per_gal = (feed_cost_hr / gal_per_hr) if gal_per_hr > 0 else 0.0

    # Operating + capital summaries if present on this TEA object
    FCI = getattr(tea, "FCI", None)
    AOC = getattr(tea, "AOC", None)
    annual_gal = gal_per_hr * HOURS_PER_YEAR if gal_per_hr > 0 else 0.0
    aoc_per_gal = (AOC / annual_gal) if (AOC is not None and annual_gal > 0) else None

    print("\n=== Key results ===")
    print(f"Beer -> purification: EtOH wt% = {beer_purity:.4f}  (EtOH {beer_etoh:,.2f} kg/hr)")
    print(f"Product ethanol:      EtOH wt% = {prod_purity:.4f}  (EtOH {prod_etoh:,.2f} kg/hr, {gal_per_hr:,.2f} gal/hr)")
    if stillage is not None:
        loss_frac = (stillage_loss / prod_etoh) if prod_etoh > 0 else 0.0
        print(f"EtOH loss to stillage: {stillage_loss:,.4f} kg/hr  (frac of product EtOH = {loss_frac:.6f})")

    print("\n=== Economics ===")
    print(f"MESP: {mesp_per_gal_etoh:,.2f} $/gal EtOH  ({mesp_per_kg_etoh:,.3f} $/kg EtOH)")
    print(f"Feedstock: {feed_cost_per_gal:,.2f} $/gal EtOH  (price {feedstock.price or 0.0:.5f} $/kg)")

    if FCI is not None:
        print(f"FCI: {FCI:,.0f} $")
    if AOC is not None:
        print(f"AOC: {AOC:,.0f} $/yr")
    if aoc_per_gal is not None:
        print(f"AOC-only: {aoc_per_gal:,.2f} $/gal (using {HOURS_PER_YEAR} hr/yr)")

    # Optional: show the purification outlet purities if you're debugging separation
    # Toggle this to True when needed.
    SHOW_PURIF_OUTS = False
    if SHOW_PURIF_OUTS:
        purif = subsystems.get("purification")
        if purif is not None:
            print("\n=== Purification outlets ===")
            for s in purif.outs:
                _, p, _ = _ethanol_metrics(s)
                if s.F_mass > 0:
                    print(f"{s.ID:24s}  F_mass={s.F_mass:12.2f}  EtOH_wt={p:.4f}")


if __name__ == "__main__":
    main()