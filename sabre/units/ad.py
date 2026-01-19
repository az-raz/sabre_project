"""
Anaerobic digestion unit operation (AD)

Purpose:
- Custom BioSTEAM unit converting volatile solids (VS) to biogas (CH4 + CO2)
- Produces two outlet streams: biogas (g) and digestate (l)

Performance model:
- VS approximated as a fraction of TS, where TS = Cellulose + Ash
- VS destruction reduces Cellulose only (Ash inert)
- Methane mass is based on `ch4_kg_per_kg_vs * VS_destroyed`
- Biogas composition controlled by `ch4_molfrac` (CH4 vs CO2)

Sizing + costing model (for TEA):
- Digester volume V [m3] = Q [m3/hr] * HRT [hr] * (1 + headspace_frac)
- CAPEX scaled from an anchor point: C = C0*(V/V0)^n

Units:
- Mass flows: kg/hr
- Molar flows: kmol/hr
- Volume: m3
"""

import biosteam as bst


class AnaerobicDigester(bst.Unit):
    _N_ins = 1
    _N_outs = 2  # biogas, digestate

    # Bare-module factors (purchase → installed)
    F_BM = {"Anaerobic digester": 1.5}

    def __init__(
        self, ID="", ins=None, outs=(),
        # performance
        vs_ts=0.65,
        vs_destruction=0.50,
        ch4_kg_per_kg_vs=0.0555,
        ch4_molfrac=0.60,
        # sizing
        hrt_days=20.0,
        slurry_density_kg_per_m3=1000.0,
        headspace_frac=0.15,
        # costing (anchor scaling)
        base_volume_m3=None,
        base_capex_usd=None,
        scaling_exponent=0.60,
        maintenance_usd_per_m3_yr=None,  # optional (see note below)
        **kwargs
    ):
        super().__init__(ID, ins, outs, **kwargs)

        # Performance
        self.vs_ts = vs_ts
        self.vs_destruction = vs_destruction
        self.ch4_kg_per_kg_vs = ch4_kg_per_kg_vs
        self.ch4_molfrac = ch4_molfrac

        # Sizing
        self.hrt_days = hrt_days
        self.slurry_density_kg_per_m3 = slurry_density_kg_per_m3
        self.headspace_frac = headspace_frac

        # Costing
        self.base_volume_m3 = base_volume_m3
        self.base_capex_usd = base_capex_usd
        self.scaling_exponent = scaling_exponent
        self.maintenance_usd_per_m3_yr = maintenance_usd_per_m3_yr

    def _run(self):
        feed = self.ins[0]
        biogas, digestate = self.outs

        biogas.empty()
        digestate.copy_like(feed)

        biogas.phase = "g"
        digestate.phase = "l"

        # Total solids and volatile solids (kg/hr)
        TS = digestate.imass["Cellulose"] + digestate.imass["Ash"]
        VS = self.vs_ts * TS

        # VS destroyed (kg/hr)
        VS_destroyed = self.vs_destruction * VS

        # Methane produced from yield (kg/hr)
        m_ch4 = self.ch4_kg_per_kg_vs * VS_destroyed

        # Convert CH4 mass -> kmol/hr
        chems = bst.settings.thermo.chemicals
        ch4 = chems["Methane"]
        n_ch4 = m_ch4 / ch4.MW

        # Use CH4 mol fraction to set CO2 (assume only CH4+CO2)
        n_total = n_ch4 / self.ch4_molfrac if self.ch4_molfrac > 0 else 0.0
        n_co2 = max(n_total - n_ch4, 0.0)

        biogas.imol["Methane"] = n_ch4
        biogas.imol["CarbonDioxide"] = n_co2

        # Remove destroyed VS from cellulose only (ash inert)
        remove = min(VS_destroyed, digestate.imass["Cellulose"])
        digestate.imass["Cellulose"] -= remove

    def _design(self):
        # Size digester from slurry volumetric flow and HRT
        feed = self.ins[0]
        rho = float(self.slurry_density_kg_per_m3)  # kg/m3

        Q_m3ph = feed.F_mass / rho
        HRT_hr = float(self.hrt_days) * 24.0

        V_m3 = Q_m3ph * HRT_hr * (1.0 + float(self.headspace_frac))

        self.design_results["Slurry flow (m3/hr)"] = Q_m3ph
        self.design_results["HRT (days)"] = float(self.hrt_days)
        self.design_results["Headspace frac"] = float(self.headspace_frac)
        self.design_results["Digester volume (m3)"] = V_m3

    def _cost(self):
        # CAPEX: scale from anchor point if provided
        V = self.design_results["Digester volume (m3)"]
        self.F_BM["Anaerobic digester"] = 1.5

        if self.base_volume_m3 is not None and self.base_capex_usd is not None:
            V0 = float(self.base_volume_m3)
            C0 = float(self.base_capex_usd)
            n = float(self.scaling_exponent)
            C = C0 * (V / V0) ** n
            self.baseline_purchase_costs["Anaerobic digester"] = C
        else:
            self.baseline_purchase_costs["Anaerobic digester"] = 0.0

        # Optional: record annual maintenance for reporting
        if self.maintenance_usd_per_m3_yr is not None:
            self.design_results["Annual maintenance ($/yr)"] = float(self.maintenance_usd_per_m3_yr) * V
