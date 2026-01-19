import biosteam as bst
from sabre.chemicals import create_chemicals
from sabre.systems.ad_biogas_system import create_ad_biogas_system

bst.main_flowsheet.clear()
create_chemicals()

sys = create_ad_biogas_system(quality="pelagic_high_quality")
sys.simulate(design_and_cost=True)
sys.show()

sys.diagram(kind="cluster", file="AD_Biogas_sys.png")
print("Saved diagram: AD_Biogas_sys.png")
