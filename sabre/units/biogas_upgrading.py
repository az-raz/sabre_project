"""
Biogas upgrading via membrane separation (TEA-ready, simplified)

Purpose:
- Split raw biogas into biomethane product + offgas
- Include literature-based electricity and CAPEX scaling for TEA

Modeling choices:
- Only tracks CH4 and CO2 explicitly; everything else goes to offgas
- Electricity scales with raw biogas flow (kWh/Nm3 raw)
- CAPEX scales with raw biogas capacity (USD per Nm3/h raw)

Literature basis (typical ranges):
- Electricity: ~0.20–0.30 kWh/Nm3 raw biogas
- CH4 losses: ~0.5–2% (=> CH4 recovery ~0.98 is reasonable)
- CAPEX: ~1950–2600 USD per (Nm3/h) raw capacity
"""

import biosteam as bst


class BiogasUpgrading(bst.Unit):
    _N_ins = 1
    _N_outs = 2  # biomethane, offgas

    # Bare-module factors (purchase -> installed)
    F_BM = {"Membrane upgrading skid": 1.5}

    def __init__(
        self, ID="", ins=None, outs=(),
        ch4_recovery=0.98,
        co2_removal=0.95,
        electricity_kwh_per_Nm3_raw=0.25,
        capex_usd_per_Nm3ph_raw=2250.0,
        **kwargs
    ):
        super().__init__(ID, ins, outs, **kwargs)
        self.ch4_recovery = ch4_recovery
        self.co2_removal = co2_removal
        self.electricity_kwh_per_Nm3_raw = electricity_kwh_per_Nm3_raw
        self.capex_usd_per_Nm3ph_raw = capex_usd_per_Nm3ph_raw

    def _run(self):
        biogas_in = self.ins[0]
        biomethane, offgas = self.outs

        biomethane.empty()
        offgas.empty()
        biomethane.phase = "g"
        offgas.phase = "g"

        IDs = biogas_in.chemicals.IDs
        n_ch4_in = biogas_in.imol["Methane"] if "Methane" in IDs else 0.0
        n_co2_in = biogas_in.imol["CarbonDioxide"] if "CarbonDioxide" in IDs else 0.0

        # CH4 split
        n_ch4_to_biomethane = self.ch4_recovery * n_ch4_in
        n_ch4_to_offgas = n_ch4_in - n_ch4_to_biomethane

        # CO2 split
        n_co2_to_offgas = self.co2_removal * n_co2_in
        n_co2_to_biomethane = n_co2_in - n_co2_to_offgas

        biomethane.imol["Methane"] = n_ch4_to_biomethane
        biomethane.imol["CarbonDioxide"] = n_co2_to_biomethane
        offgas.imol["Methane"] = n_ch4_to_offgas
        offgas.imol["CarbonDioxide"] = n_co2_to_offgas

        # Pass through anything else to offgas
        for chem_id in biogas_in.chemicals.IDs:
            if chem_id in ("Methane", "CarbonDioxide"):
                continue
            n = biogas_in.imol[chem_id]
            if n:
                offgas.imol[chem_id] += n

    def _design(self):
        biogas_in = self.ins[0]

        # Normal m3/h at 0C, 1 atm: 1 kmol = 22.414 Nm3
        Q_Nm3ph = float(biogas_in.F_mol) * 22.414

        self.design_results["Raw biogas flow (Nm3/h)"] = Q_Nm3ph
        self.design_results["Electricity (kWh/Nm3 raw)"] = float(self.electricity_kwh_per_Nm3_raw)
        self.design_results["CAPEX basis ($/(Nm3/h) raw)"] = float(self.capex_usd_per_Nm3ph_raw)

        # Electricity: kWh/h == kW
        kW = Q_Nm3ph * float(self.electricity_kwh_per_Nm3_raw)
        self.add_power_utility(kW)

    def _cost(self):
        self.F_BM["Membrane upgrading skid"] = 1.5
        Q_Nm3ph = self.design_results["Raw biogas flow (Nm3/h)"]
        C = float(self.capex_usd_per_Nm3ph_raw) * float(Q_Nm3ph)
        self.baseline_purchase_costs["Membrane upgrading skid"] = C
