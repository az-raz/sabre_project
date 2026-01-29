class BiogasUpgrading(bst.Unit):
    _N_ins = 1
    _N_outs = 2
    F_BM = {"Membrane upgrading skid": 1.5}

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
        self.ch4_recovery = ch4_recovery
        self.co2_removal = co2_removal
        self.electricity_kwh_per_Nm3_raw = electricity_kwh_per_Nm3_raw
        self.capex_usd_per_Nm3ph_raw = capex_usd_per_Nm3ph_raw
        self.maintenance_frac_of_capex_per_yr = maintenance_frac_of_capex_per_yr

    def _cost(self):
        Q_Nm3ph = float(self.design_results["Raw biogas flow (Nm3/h)"])
        capex = float(self.capex_usd_per_Nm3ph_raw) * Q_Nm3ph
        self.baseline_purchase_costs["Membrane upgrading skid"] = capex

        self.design_results["Annual maintenance ($/yr)"] = (
            float(self.maintenance_frac_of_capex_per_yr) * capex
        )
