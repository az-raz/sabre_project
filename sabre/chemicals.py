# sabre/chemicals.py
import biosteam as bst
import thermosteam as tmo

def _pseudo_solid(ID: str, MW: float = 1.0):
    return bst.Chemical(ID, search_db=False, default=True, phase="s", MW=MW)

def create_chemicals():
    Water = bst.Chemical("Water")

    # Sargassum components
    Ash         = _pseudo_solid("Ash")
    Protein     = _pseudo_solid("Protein")
    Lignin      = _pseudo_solid("Lignin")
    Glucan      = _pseudo_solid("Glucan")
    Xylan       = _pseudo_solid("Xylan")
    Mannan      = _pseudo_solid("Mannan")
    Galactan    = _pseudo_solid("Galactan")
    Arabinan    = _pseudo_solid("Arabinan")
    Alginate    = _pseudo_solid("Alginate")
    Fucoidan    = _pseudo_solid("Fucoidan")
    Mannitol    = _pseudo_solid("Mannitol")
    OtherSolids = _pseudo_solid("OtherSolids")

    # Gases
    CH4 = bst.Chemical("Methane", phase="g")
    CO2 = bst.Chemical("CarbonDioxide", phase="g")

    # VFAs
    AceticAcid    = bst.Chemical("AceticAcid", phase="l")
    PropionicAcid = bst.Chemical("PropionicAcid", phase="l")
    ButyricAcid   = bst.Chemical("ButyricAcid", phase="l")
    ValericAcid   = bst.Chemical("ValericAcid", phase="l")
    HexanoicAcid  = bst.Chemical("HexanoicAcid", phase="l")

    chems = bst.Chemicals([
        Water,
        Ash, Protein, Lignin, Glucan, Xylan, Mannan, Galactan, Arabinan,
        Alginate, Fucoidan, Mannitol, OtherSolids,
        CH4, CO2,
        AceticAcid, PropionicAcid, ButyricAcid, ValericAcid, HexanoicAcid,
    ])
    chems.compile()

    thermo = tmo.Thermo(chems)
    bst.settings.set_thermo(thermo)
    tmo.settings.set_thermo(thermo)
    return chems

def set_thermo():
    return create_chemicals()