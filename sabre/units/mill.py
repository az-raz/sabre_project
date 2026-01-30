"""
    Milling / size reduction

    Applies explicit mass loss during milling/shredding from TEA notes
    Sends lost material to a 'losses' stream (same composition as feed)

"""

import biosteam as bst


class Mill(bst.Unit):

    _N_ins = 1
    _N_outs = 2  # milled_biomass, milling_losses

    def __init__(self, ID="", ins=None, outs=(), loss_frac=0.15, power_kWh_per_ton_wet=None, **kwargs):

        super().__init__(ID, ins, outs, **kwargs)
        self.loss_frac = float(loss_frac)
        self.power_kWh_per_ton_wet = power_kWh_per_ton_wet

    def _run(self):
        feed = self.ins[0]
        milled, losses = self.outs
        milled.empty()
        losses.empty()

        milled.phase = feed.phase
        losses.phase = feed.phase

        lf = min(max(self.loss_frac, 0.0), 1.0)
        for chem_id in feed.chemicals.IDs:
            m = float(feed.imass[chem_id])
            m_loss = lf * m
            losses.imass[chem_id] = m_loss
            milled.imass[chem_id] = m - m_loss

    def _cost(self):

        # placeholder (need to find cost)
        self.baseline_purchase_costs["Mill"] = 0.0
        self.F_BM["Mill"] = 1.0

        if self.power_kWh_per_ton_wet is not None:
            ton_per_hr = self.ins[0].F_mass / 1000.0  # metric ton/hr
            kW = float(self.power_kWh_per_ton_wet) * ton_per_hr
            self.power_utility(kW)
