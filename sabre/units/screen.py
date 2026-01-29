"""
Digestate screening (solid-liquid separation)

Purpose:
- Split AD digestate into:
  (1) soil_amendment: captured solids (Cellulose + Ash)
  (2) liquid_digestate: remaining liquid + uncaptured solids

Assumptions:
- Total solids (TS) = Cellulose + Ash
- Water is the only liquid tracked explicitly here
- ts_capture_frac controls fraction of TS sent to cake
- cake_moisture_frac sets water fraction in soil_amendment by mass
"""

import biosteam as bst

class Screen(bst.Unit):
    _N_ins = 1
    _N_outs = 2  # cake, liquid

    def __init__(self, ID="", ins=None, outs=(),
                 solids_IDs=("Cellulose", "Ash"),
                 solids_capture=0.95,
                 cake_moisture=0.70,
                 **kwargs):
        super().__init__(ID, ins, outs, **kwargs)
        self.solids_IDs = tuple(solids_IDs)
        self.solids_capture = float(solids_capture)
        self.cake_moisture = float(cake_moisture)

    def _run(self):
        feed = self.ins[0]
        cake, liq = self.outs
        cake.empty()
        liq.empty()

        cake.phase = "l"
        liq.phase = "l"

        # Split solids by capture fraction
        for sid in self.solids_IDs:
            m = float(feed.imass[sid])
            m_cake = self.solids_capture * m
            cake.imass[sid] = m_cake
            liq.imass[sid] = m - m_cake

        # Non-solids initially goes to liquid
        for chem_id in feed.chemicals.IDs:
            if chem_id in self.solids_IDs:
                continue
            liq.imass[chem_id] = float(feed.imass[chem_id])

        # Pull water from liquid to meet cake moisture target
        TS_cake = sum(float(cake.imass[sid]) for sid in self.solids_IDs)
        if TS_cake > 0:
            # moisture = water / (water + TS)
            water_needed = self.cake_moisture / (1 - self.cake_moisture) * TS_cake
            water_available = float(liq.imass["Water"])
            water_to_cake = min(water_needed, water_available)
            cake.imass["Water"] += water_to_cake
            liq.imass["Water"] -= water_to_cake
