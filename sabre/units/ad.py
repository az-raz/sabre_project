"""
Anaerobic digestion unit operation (AD)

Purpose:
- Convert Sargassum volatile solids into biogas (CH4 + CO2) and digestate
- Size the digester using HRT and headspace
- Enforce a maximum single-digester size and model parallel digesters
- Estimate CAPEX by scaling from an anchor point (ADBC spreadsheet)

Key points:
- Total required digester volume is computed from slurry volumetric flow and HRT
- Total volume includes headspace: V_total = V_liquid / (1 - headspace_frac)
- If V_total exceeds max_single_digester_volume, we create N parallel digesters:
    N = ceil(V_total / V_max)
    V_each = V_total / N
- Cost scales on a per-digester basis and is multiplied by N

Units:
- Flow: kg/hr internally
- Volume: m3
- HRT: days
"""

import math
import biosteam as bst

# Constants
GAL_TO_M3 = 0.003785411784  # US gallons -> m3 conversion
ADBC_VOL_M3 = [878, 1755, 2633, 3510, 5265, 8775]
ADBC_CAPEX  = [1720964, 1750201, 1779439, 1808676, 1867151, 1984101]

# Volume and Cost Interpolation from ADBC excel
def interp_capex(volume_m3: float) -> float:
    x = ADBC_VOL_M3
    y = ADBC_CAPEX
    if volume_m3 <= x[0]:
        m = (y[1]-y[0])/(x[1]-x[0])
        return y[0] + m*(volume_m3 - x[0])
    if volume_m3 >= x[-1]:
        m = (y[-1]-y[-2])/(x[-1]-x[-2])
        return y[-1] + m*(volume_m3 - x[-1])
    for i in range(len(x)-1):
        if x[i] <= volume_m3 <= x[i+1]:
            m = (y[i+1]-y[i])/(x[i+1]-x[i])
            return y[i] + m*(volume_m3 - x[i])
    raise RuntimeError("Interpolation failed")


class AnaerobicDigester(bst.Unit):
    _N_ins = 1
    _N_outs = 2  # biogas, digestate

    # Bare-module factor (purchase -> installed)
    F_BM = {"Anaerobic digester": 1.0}

    def __init__(
        self, ID="", ins=None, outs=(),
        # performance
        vs_ts=0.65,
        vs_destruction=0.50,
        ch4_kg_per_kg_vs=0.0555,
        ch4_molfrac=0.60,
        # sizing
        hrt_days=25.0,
        slurry_density_kg_per_m3=1000.0,
        headspace_frac=0.2,
        max_single_digester_volume_MG=1.5,
        # costing anchor
        base_volume_m3=None,
        base_capex_usd=None,
        maintenance_usd_per_m3_yr=None,
        **kwargs
    ):
        super().__init__(ID, ins, outs, **kwargs)

        # performance
        self.vs_ts = float(vs_ts)
        self.vs_destruction = float(vs_destruction)
        self.ch4_kg_per_kg_vs = float(ch4_kg_per_kg_vs)
        self.ch4_molfrac = float(ch4_molfrac)

        # sizing
        self.hrt_days = float(hrt_days)
        self.slurry_density_kg_per_m3 = float(slurry_density_kg_per_m3)
        self.headspace_frac = float(headspace_frac)

        # 1.5 MG default convert to m3
        self.max_single_digester_volume_m3 = float(max_single_digester_volume_MG) * 1e6 * GAL_TO_M3

        # costing anchor
        self.base_volume_m3 = base_volume_m3
        self.base_capex_usd = base_capex_usd
        self.maintenance_usd_per_m3_yr = maintenance_usd_per_m3_yr
        self.F_BM = dict(self.F_BM)

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
        ch4 = bst.settings.thermo.chemicals["Methane"]
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
        feed = self.ins[0]

        slurry_m3_per_hr = feed.F_mass / self.slurry_density_kg_per_m3
        V_liquid = slurry_m3_per_hr * 24.0 * self.hrt_days

        # Total volume includes headspace fraction of total
        hf = min(max(self.headspace_frac, 0.0), 0.95)
        V_total = V_liquid / (1.0 - hf)

        # Design in parallel
        V_max = self.max_single_digester_volume_m3
        N = max(1, math.ceil(V_total / V_max))
        V_each = V_total / N

        self.design_results["Slurry flow (m3/hr)"] = slurry_m3_per_hr
        self.design_results["HRT (days)"] = self.hrt_days
        self.design_results["Headspace frac"] = self.headspace_frac

        self.design_results["Total digester volume (m3)"] = V_total
        self.design_results["Max single digester (m3)"] = V_max
        self.design_results["Number of digesters"] = N
        self.design_results["Digester volume each (m3)"] = V_each

    def _cost(self):
        # Cost on a per-digester basis, multiplied by number of digesters.
        V_each = self.design_results["Digester volume each (m3)"]
        N = int(self.design_results["Number of digesters"])
        self.F_BM["Anaerobic digester"] = 1.0

        C_each = interp_capex(V_each)
        C_total = N * C_each
        self.design_results["ADBC_capex_each_$"] = C_each
        self.baseline_purchase_costs["Anaerobic digester"] = C_total