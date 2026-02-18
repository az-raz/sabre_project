import numpy as np
import biosteam as bst
from sabre.systems.ethanol_fermentation_system import create_ethanol_fermentation_system


system, tea, streams, subsystems = create_ethanol_fermentation_system(debug=True)

beer = streams["beer"]

print("\n=== Beer summary ===")
print("Beer F_mass:", beer.F_mass)
print("Beer Ethanol (kg/hr):", beer.imass["Ethanol"])
print("Beer Water (kg/hr):", beer.imass["Water"])

print("\n=== Top 15 Beer Components ===")
IDs = bst.settings.thermo.chemicals.IDs
arr = beer.imass.data
idx = np.argsort(arr)[::-1][:15]

for i in idx:
    if arr[i] > 0:
        print(IDs[i], arr[i])

print("\n=== Running full system simulation ===")
system.simulate()

print("\n=== Final Ethanol Product ===")
ethanol = streams["ethanol"]
print("Ethanol F_mass:", ethanol.F_mass)
print("Ethanol purity:", ethanol.imass["Ethanol"] / ethanol.F_mass if ethanol.F_mass > 0 else 0)

print("\n=== MESP ===")
print("USD/gal:", tea.solve_price(ethanol) * 2.98668849)
