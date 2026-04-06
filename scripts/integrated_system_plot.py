import os
from pathlib import Path

import biosteam as bst

os.environ["PATH"] = "/opt/homebrew/bin:" + os.environ["PATH"]

from sabre.chemicals import set_thermo
from sabre.systems.integrated_system import create_integrated_biorefinery

OUTDIR = Path("results") / "flowsheets"
OUTDIR.mkdir(parents=True, exist_ok=True)

set_thermo()

# Build at alpha=0.5 so both pathways are populated
sys, streams, units, _ = create_integrated_biorefinery(
    alpha=0.5,
    pretreatment_case="combined_PE",
)
sys.simulate()

# Full integrated system diagram
sys.diagram(file=str(OUTDIR / "integrated_biorefinery_full"))
print(f"Saved: {OUTDIR / 'integrated_biorefinery_full'}")

# Preprocessing only (PR → PC → ML)
pre_units = [u for u in sys.units if u.ID in ("PR", "PC", "ML")]
pre_sys = bst.System("preprocessing", path=pre_units)
pre_sys.diagram(file=str(OUTDIR / "preprocessing"))
print(f"Saved: {OUTDIR / 'preprocessing'}")

# Methanogenic pathway only (PX, EZ, AD → H2SR → UP → SP_AD)
meth_ids = ("PX", "EZ", "AD", "H2SR", "UP", "SP_AD")
meth_units = [u for u in sys.units if u.ID in meth_ids]
if meth_units:
    meth_sys = bst.System("methanogenic_path", path=meth_units)
    meth_sys.diagram(file=str(OUTDIR / "methanogenic_pathway"))
    print(f"Saved: {OUTDIR / 'methanogenic_pathway'}")

# VFA fermentation pathway only
vfa_ids = ("VFA_AD", "SP_VFA", "MF", "T601", "R601", "V605", "OE", "C603_2")
vfa_units = [u for u in sys.units if u.ID in vfa_ids]
if vfa_units:
    vfa_sys = bst.System("vfa_ferm_path", path=vfa_units)
    vfa_sys.diagram(file=str(OUTDIR / "vfa_fermentation_pathway"))
    print(f"Saved: {OUTDIR / 'vfa_fermentation_pathway'}")

print(f"\nAll flowsheets saved to: {OUTDIR.resolve()}")