"""
Thermodynamic chemicals and composite groups for the SABRE model

Purpose:
- Define all chemicals used by the flowsheet (Water, Cellulose, Ash, Methane, CO2, etc.)
- Set the global BioSTEAM thermo object via `bst.settings.set_thermo(...)`
- Define dry Sargassum groups by quality bin using YAML (e.g., ash fraction on dry basis)

Key entry points:
- create_chemicals()

Notes:
- Sargassum is represented as a composite group of real chemicals (Cellulose + Ash)
"""

import biosteam as bst
from sabre.config import load_assumptions

def create_chemicals():
    Water = bst.Chemical("Water")

    # Biomass components
    Cellulose = bst.Chemical("Cellulose", phase="s")
    Ash = bst.Chemical("Ash", search_db=False, default=True, phase="s", MW=1)

    # AD products
    CH4 = bst.Chemical("Methane", phase="g")
    CO2 = bst.Chemical("CarbonDioxide", phase="g")

    chems = bst.Chemicals([Water, Cellulose, Ash, CH4, CO2])
    chems.compile()
    bst.settings.set_thermo(chems)

    # Loading the ash content for type of Sargassum from YAML
    A = load_assumptions()
    for name, q in A["quality_bins"].items():
        ash = q["ash_wt_frac_dry"]
        chems.define_group(
            f"SargassumDry_{name}",
            ["Cellulose", "Ash"],
            [1 - ash, ash],
            wt=True,
        )