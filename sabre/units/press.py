"""
    Mechanical dewatering (press)

    Splits wet biomass into:
      - pressed_cake: retains most solids + enough water to hit target solids wt%
      - pressate: remaining water + uncaptured solids + (optional) solubles

    Notes:
    - "solids_IDs" defines which chemicals count as total solids for targeting cake solids wt%
    
"""

import biosteam as bst


class Press(bst.Unit):

    _N_ins = 1
    _N_outs = 2  # pressed_cake, pressate

    def __init__(
        self, ID="", ins=None, outs=(),
        solids_IDs=("Cellulose", "Ash"),
        solids_capture_frac=0.98, # assumption
        cake_solids_wt_frac=0.35, # assumption
        solubles_to_pressate_frac=1.0,
        power_kWh_per_ton_wet=None,
        **kwargs
    ):
        super().__init__(ID, ins, outs, **kwargs)
        self.solids_IDs = tuple(solids_IDs)
        self.solids_capture_frac = float(solids_capture_frac)
        self.cake_solids_wt_frac = float(cake_solids_wt_frac)
        self.solubles_to_pressate_frac = float(solubles_to_pressate_frac)
        self.power_kWh_per_ton_wet = power_kWh_per_ton_wet

    def _run(self):
        feed = self.ins[0]
        cake, pressate = self.outs
        cake.empty()
        pressate.empty()

        cake.phase = "l"
        pressate.phase = "l"

        # Split defined solids by capture
        cap = min(max(self.solids_capture_frac, 0.0), 1.0)
        for sid in self.solids_IDs:
            m = float(feed.imass[sid])
            m_cake = cap * m
            cake.imass[sid] = m_cake
            pressate.imass[sid] = m - m_cake

        # Partition everything else except water
        sol_to_p = min(max(self.solubles_to_pressate_frac, 0.0), 1.0)
        for chem_id in feed.chemicals.IDs:
            if chem_id in self.solids_IDs or chem_id == "Water":
                continue
            m = float(feed.imass[chem_id])
            m_p = sol_to_p * m
            pressate.imass[chem_id] += m_p
            cake.imass[chem_id] += (m - m_p)

        # Allocate water to hit cake solids wt% target
        TS_cake = sum(float(cake.imass[sid]) for sid in self.solids_IDs)
        other_nonwater_cake = sum(
            float(cake.imass[i]) for i in feed.chemicals.IDs
            if i not in self.solids_IDs and i != "Water"
        )

        f = self.cake_solids_wt_frac
        if TS_cake > 0 and 0 < f < 1:
            # f = TS / (TS + water + other)
            water_needed = TS_cake * (1 - f) / f - other_nonwater_cake
            water_needed = max(water_needed, 0.0)
        else:
            water_needed = 0.0

        water_avail = float(feed.imass["Water"])
        water_to_cake = min(water_needed, water_avail)

        cake.imass["Water"] += water_to_cake
        pressate.imass["Water"] += (water_avail - water_to_cake)

    def _design(self):
        # placeholder (need to add size metrics)
        pass

    def _cost(self):
        # placeholder (need to find cost)
        self.baseline_purchase_costs["Press"] = 0.0
        self.F_BM["Press"] = 1.0

        # placeholder need to edit power calculation
        if self.power_kWh_per_ton_wet is not None:
            ton_per_hr = self.ins[0].F_mass / 1000.0  # metric ton/hr
            kW = float(self.power_kWh_per_ton_wet) * ton_per_hr
            self.power_utility(kW)
