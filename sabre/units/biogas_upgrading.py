"""
Biogas upgrading unit (UP)

Purpose
- Takes raw biogas from anaerobic digestion and splits it into:
  (1) biomethane product (CH4-rich gas) and (2) offgas (CO2-rich stream + impurities)
- Applies simple performance parameters (CH4 recovery, CO2 removal)
- Estimates utilities and CAPEX using a capacity-based membrane upgrading skid

Key assumptions / conventions
- Raw biogas volumetric flow is computed at STP (0°C, 1 atm) using 22.414 Nm3 per kmol ideal gas
- Electricity demand is modeled as kWh per Nm3 raw biogas (converted to kW in _design())
- CAPEX is modeled as USD per (Nm3/h) of raw biogas capacity and annual maintenance is a fixed fraction of CAPEX
- Non-CH4/CO2 species (trace gases) are sent to offgas by default

Outputs
- biomethane: Methane + any unrecovered CO2
- offgas: removed CO2 + unrecovered CH4 + all other species

"""

import biosteam as bst

# creating the biogas upgrading unit 
class BiogasUpgrading(bst.Unit):
    _N_ins = 1
    _N_outs = 2  # biomethane, offgas

    def __init__(
        self, ID="", ins=None, outs=(),
        ch4_recovery=0.98,
        co2_removal=0.95,
        electricity_kwh_per_Nm3_raw=0.25,
        capex_usd_per_Nm3ph_raw=2200.0,
        maintenance_frac_of_capex_per_yr=0.035,
        **kwargs
    ):
        super().__init__(ID, ins, outs, **kwargs)
        self.ch4_recovery = float(ch4_recovery)
        self.co2_removal = float(co2_removal)
        self.electricity_kwh_per_Nm3_raw = float(electricity_kwh_per_Nm3_raw)
        self.capex_usd_per_Nm3ph_raw = float(capex_usd_per_Nm3ph_raw)
        self.maintenance_frac_of_capex_per_yr = float(maintenance_frac_of_capex_per_yr)

    def _run(self):
        raw = self.ins[0]
        biomethane, offgas = self.outs
        biomethane.empty()
        offgas.empty()

        biomethane.phase = "g"
        offgas.phase = "g"

        ch4_in = float(raw.imol["Methane"])
        co2_in = float(raw.imol["CarbonDioxide"])

        ch4_to_bm = self.ch4_recovery * ch4_in
        biomethane.imol["Methane"] = ch4_to_bm
        offgas.imol["Methane"] = ch4_in - ch4_to_bm

        co2_to_off = self.co2_removal * co2_in
        offgas.imol["CarbonDioxide"] = co2_to_off
        biomethane.imol["CarbonDioxide"] = co2_in - co2_to_off

        for cid in raw.chemicals.IDs:
            if cid in ("Methane", "CarbonDioxide"):
                continue
            n = float(raw.imol[cid])
            if n:
                offgas.imol[cid] = n

    def _design(self):
        # compute raw biogas flow in Nm3/h at STP
        raw = self.ins[0]

        # total kmol/h
        n_kmolph = float(raw.F_mol)  # kmol/hr

        # 1 kmol ideal gas = 22.414 Nm3 (STP)
        Q_Nm3ph = 22.414 * n_kmolph

        self.design_results["Raw biogas flow (Nm3/h)"] = Q_Nm3ph

        # electricity: kWh per Nm3 raw -> kW (since per hour)
        kW = self.electricity_kwh_per_Nm3_raw * Q_Nm3ph
        if kW:
            self.power_utility(kW)

    def _cost(self):
        Q_Nm3ph = self.design_results.get("Raw biogas flow (Nm3/h)")
        if Q_Nm3ph is None:
            n_kmolph = float(self.ins[0].F_mol)
            Q_Nm3ph = 22.414 * n_kmolph
            self.design_results["Raw biogas flow (Nm3/h)"] = Q_Nm3ph

        capex = self.capex_usd_per_Nm3ph_raw * float(Q_Nm3ph)
        self.baseline_purchase_costs["Membrane upgrading skid"] = capex

        self.design_results["Annual maintenance ($/yr)"] = (
            self.maintenance_frac_of_capex_per_yr * capex
        )