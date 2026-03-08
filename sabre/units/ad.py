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
- ADBC Excel sheet data is used for cost interpolation

Units:
- Flow: kg/hr internally
- Volume: m3
- HRT: days
"""

import math
import biosteam as bst

# conversion factors and ADBC data
GAL_TO_M3 = 0.003785411784  # US gallons -> m3 conversion
ADBC_VOL_M3 = [878, 1755, 2633, 3510, 5265, 8775]
ADBC_CAPEX  = [1720964, 1750201, 1779439, 1808676, 1867151, 1984101]

# volume and cost interpolation from ADBC excel
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
    raise RuntimeError("Interpolation failed") # avoid errors if logic fails

# creating the AD unit
class AnaerobicDigester(bst.Unit):
    _N_ins = 1
    _N_outs = 2  # biogas, digestate

    # bare-module factor (purchase -> installed)
    F_BM = {"Anaerobic digester": 1.0} # ADBC file already has installed costs

    def __init__(
        self, ID="", ins=None, outs=(),
        # performance
        vs_ts=0.65,
        vs_destruction=0.50,
        ch4_kg_per_kg_vs=0.0555,
        ch4_molfrac=0.50,
        digestible_IDs=None,
        # sizing
        hrt_days=25.0,
        slurry_density_kg_per_m3=1000.0,
        headspace_frac=0.2,
        max_single_digester_volume_MG=1.5,
        # costing anchor
        base_volume_m3=None,
        base_capex_usd=None,
        maintenance_usd_per_m3_yr=None,
        # utilities
        mixing_W_per_m3=5.0,            # 2–10 typical sensitivity band
        influent_temperature_K=298.15,  # assume 25°C unless you track it
        target_temperature_K=308.15,    # 35°C
        cp_kJ_per_kgK=4.18,             # slurry ~ water

        **kwargs
    ):
        super().__init__(ID, ins, outs, **kwargs)

        # performance
        self.vs_ts = float(vs_ts)
        self.vs_destruction = float(vs_destruction)
        self.ch4_kg_per_kg_vs = float(ch4_kg_per_kg_vs)
        self.ch4_molfrac = float(ch4_molfrac)
        self.digestible_IDs = tuple(digestible_IDs) if digestible_IDs is not None else (
            "Glucan", "Xylan", "Mannan", "Galactan",
            "Alginate", "Fucoidan", "Mannitol",
            "Protein", "OtherSolids", "Cellulose",
        )

        # utilities
        self.mixing_W_per_m3 = float(mixing_W_per_m3)
        self.influent_temperature_K = float(influent_temperature_K)
        self.target_temperature_K = float(target_temperature_K)
        self.cp_kJ_per_kgK = float(cp_kJ_per_kgK)

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

    def _available_digestible_pool(self, stream):
        ids = set(bst.settings.thermo.chemicals.IDs)
        avail = {}
        for cid in self.digestible_IDs:
            if cid not in ids:
                continue
            m = float(stream.imass[cid])
            if m > 0:
                avail[cid] = m
        return avail

    def _run(self):
        feed = self.ins[0]
        biogas, digestate = self.outs

        biogas.empty()
        digestate.copy_like(feed)

        biogas.phase = "g"
        digestate.phase = "l"

        chems = bst.settings.thermo.chemicals
        ids = set(chems.IDs)

        water = float(digestate.imass["Water"]) if "Water" in ids else 0.0
        ash = float(digestate.imass["Ash"]) if "Ash" in ids else 0.0
        TS = max(digestate.F_mass - water, 0.0)
        VS = max(TS - ash, 0.0)
        VS_destroyed = self.vs_destruction * VS

        if VS_destroyed <= 0:
            return

        avail = self._available_digestible_pool(digestate)
        pool = sum(avail.values())
        if pool <= 1e-12:
            return

        remove = min(VS_destroyed, pool)
        for cid, m in avail.items():
            take = remove * (m / pool)
            digestate.imass[cid] -= take

        if "Methane" not in ids or "CarbonDioxide" not in ids:
            raise RuntimeError(
                "AD unit requires Methane and CarbonDioxide in thermo."
            )

        ch4 = chems["Methane"]
        ch4_mass = self.ch4_kg_per_kg_vs * remove
        n_ch4 = ch4_mass / ch4.MW

        if n_ch4 <= 0:
            return

        if 0 < self.ch4_molfrac < 1:
            n_total = n_ch4 / self.ch4_molfrac
            n_co2 = max(n_total - n_ch4, 0.0)
        else:
            n_co2 = n_ch4

        biogas.imol["Methane"] = n_ch4
        biogas.imol["CarbonDioxide"] = n_co2

    def _design(self):
        feed = self.ins[0]

        slurry_m3_per_hr = feed.F_mass / self.slurry_density_kg_per_m3
        V_liquid = slurry_m3_per_hr * 24.0 * self.hrt_days

        # total volume includes headspace fraction of total
        hf = min(max(self.headspace_frac, 0.0), 0.95)
        V_total = V_liquid / (1.0 - hf)

        # design in parallel
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

        # ------------------------
        # Utilities: mixing + heating
        # ------------------------

        # Mixing electricity (kW) = (W/m3)*V_liquid / 1000
        # Use liquid volume (excluding headspace) for mixing basis
        mixing_kW = (self.mixing_W_per_m3 * V_liquid) / 1000.0

        # Heating duty (kJ/h) to bring influent slurry to target temperature
        # Use assumed influent temperature (or feed.T if you prefer)
        T_in = self.influent_temperature_K
        T_target = self.target_temperature_K
        dT = max(0.0, T_target - T_in)

        m_dot_kgph = feed.F_mass
        Q_kJph = m_dot_kgph * self.cp_kJ_per_kgK * dT  # kJ/h

        # Record utilities in design_results
        self.design_results["Mixing power (kW)"] = mixing_kW
        self.design_results["Influent T (K)"] = T_in
        self.design_results["Target T (K)"] = T_target
        self.design_results["Heating duty (kJ/h)"] = Q_kJph

        # Apply electricity utility
        self.power_utility.consumption = mixing_kW
        self.power_utility.production = 0.0

        if Q_kJph > 0:
            T_in = self.influent_temperature_K
            T_out = self.target_temperature_K

            # BioSTEAM version differences: some expect (duty, T_in, T_out), others (duty, T_in)
            try:
                self.add_heat_utility(Q_kJph, T_in, T_out)
            except TypeError:
                self.add_heat_utility(Q_kJph, T_in)

    def _cost(self):
        # cost on a per-digester basis, multiplied by number of digesters
        V_each = self.design_results["Digester volume each (m3)"]
        N = int(self.design_results["Number of digesters"])
        self.F_BM["Anaerobic digester"] = 1.0

        C_each = interp_capex(V_each)
        C_total = N * C_each
        self.design_results["ADBC_capex_each_$"] = C_each
        self.baseline_purchase_costs["Anaerobic digester"] = C_total
