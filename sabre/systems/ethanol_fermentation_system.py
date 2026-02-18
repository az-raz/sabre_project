import biosteam as bst
from biorefineries import cellulosic
from biorefineries.ethanol import create_ethanol_purification_system
from biorefineries.tea import create_cellulosic_ethanol_tea


def create_ethanol_fermentation_system(debug=False):

    # --- Isolated flowsheet to avoid registry collisions ---
    fs = bst.Flowsheet('ethanol_fs')
    bst.main_flowsheet.set_flowsheet(fs)
    fs.clear()

    # --- Thermo ---
    cellulosic.load_process_settings()
    thermo = cellulosic.create_cellulosic_ethanol_chemicals()
    bst.settings.set_thermo(thermo)

    # --- Feedstock (wet Sargassum proxy; ~85% water, low lignin, high ash) ---
    feedstock = bst.Stream(
    ID='feedstock',
    total_flow=104229.16,   # kg/hr WET feed (keep wet basis)
    units='kg/hr',
    price=0.0516,

    # wet seaweed moisture
    Water=0.85,

    # high minerals + moderate protein (wet-basis fractions)
    Ash=0.032,
    Protein=0.014,
    Lignin=0.001,

    # remap extract -> fermentable polysaccharide proxy
    Extract=0.021,   # keep 30% of prior 0.070
    Glucan=0.069,    # prior 0.020 + (0.070*0.70) = 0.020 + 0.049 = 0.069

    # keep these small for now
    Xylan=0.006,
    Arabinan=0.002,
    Mannan=0.002,
    Galactan=0.001,
    )

    # --- Feed handling ---
    U101 = cellulosic.units.FeedStockHandling('U101', feedstock)
    U101.cost_items['System'].cost = 0.
    U101.simulate()


    if debug:
        print("Feedstock F_mass:", feedstock.F_mass)
        print("U101 out F_mass:", U101.outs[0].F_mass)

    # --- Pretreatment ---
    pretreatment_sys = cellulosic.create_dilute_acid_pretreatment_system(
        ins=U101-0,
        area=200,
        mockup=False,
    )

    if debug:
        print("Pretreatment inlet F_mass:", pretreatment_sys.ins[0].F_mass)

    pretreatment_sys.simulate()

    pretreated = pretreatment_sys.get_outlet('pretreated_biomass') or (pretreatment_sys - 0)
    pretreated.ID = "sabre_pretreated_biomass"

    if debug:
        print("Pretreatment outs:",
              [(s.ID, s.F_mass) for s in pretreatment_sys.outs])

    # --- Fermentation ---
    fermentation_sys = cellulosic.create_cellulosic_fermentation_system(
        ins=pretreated,
        area=300,
        mockup=False,
        kind='SCF',
    )

    if debug:
        print("Fermentation inlet F_mass:", fermentation_sys.ins[0].F_mass)

    fermentation_sys.simulate()

    vent = fermentation_sys.get_outlet('vent') or (fermentation_sys - 0)
    beer = fermentation_sys.get_outlet('beer') or (fermentation_sys - 1)
    lignin = fermentation_sys.get_outlet('lignin') or (fermentation_sys - 2)

    if debug:
        print("Beer after fermentation:")
        print("  F_mass:", beer.F_mass)
        print("  Ethanol:", beer.imass["Ethanol"])
        print("  Water:", beer.imass["Water"])

    pretreated = pretreatment_sys.get_outlet('pretreated_biomass')
    print("Pretreated Glucose+Xylose (kg/hr):",
        pretreated.imass['Glucose'] + pretreated.imass['Xylose'])

    beer = fermentation_sys.get_outlet('beer')
    print("Beer Glucose+Xylose (kg/hr):",
        beer.imass['Glucose'] + beer.imass['Xylose'])

    # --- Purification ---
    ethanol_stream = bst.Stream('ethanol')
    ethanol_purification_sys = create_ethanol_purification_system(
        ins=beer,
        outs=[ethanol_stream],
        area=400,
        mockup=False,
    )

    ethanol_purification_sys.simulate()

    stillage = ethanol_purification_sys.outs[1]

    # --- Facilities ---
    bst.create_all_facilities(
        feedstock,
        recycle_process_water_streams=[stillage],
        HXN=False,
        area=600,
    )

    # --- Combine units into one system ---
    all_units = (
        U101,
        *pretreatment_sys.units,
        *fermentation_sys.units,
        *ethanol_purification_sys.units,
    )

    system = bst.System("Ethanol_Fermentation_sys", path=all_units)

    tea = create_cellulosic_ethanol_tea(system)

    key_streams = {
        "feedstock": feedstock,
        "pretreated_biomass": pretreated,
        "beer": beer,
        "vent": vent,
        "lignin": lignin,
        "ethanol": ethanol_stream,
        "stillage": stillage,
    }

    subsystems = {
        "pretreatment": pretreatment_sys,
        "fermentation": fermentation_sys,
        "purification": ethanol_purification_sys,
    }

    return system, tea, key_streams, subsystems
