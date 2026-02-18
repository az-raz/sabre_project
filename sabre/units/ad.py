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

    def _run(self):
        feed = self.ins[0]
        biogas, digestate = self.outs

        biogas.empty()
        digestate.copy_like(feed)

        biogas.phase = "g"
        digestate.phase = "l"

        # calculate TS and VS
        TS = digestate.imass["Cellulose"] + digestate.imass["Ash"]
        VS = self.vs_ts * TS
        VS_destroyed = self.vs_destruction * VS

        # remove destroyed VS from cellulose only (ash inert)
        cellulose_available = digestate.imass["Cellulose"]
        remove = min(VS_destroyed, cellulose_available)
        if remove <= 0:
            return

        # stoichiometric conversion for cellulose monomer C6H10O5 
        chems = bst.settings.thermo.chemicals
        cell = chems["Cellulose"]
        h2o  = chems["Water"]
        ch4  = chems["Methane"]
        co2  = chems["CarbonDioxide"]

        # moles of cellulose monomer destroyed
        n_cell = remove / cell.MW  # kmol/hr

        # reaction: Cellulose + Water -> 3 CH4 + 3 CO2
        n_h2o = 1.0 * n_cell
        n_ch4 = 3.0 * n_cell
        n_co2 = 3.0 * n_cell

        # consume cellulose
        digestate.imass["Cellulose"] -= remove

        # consume water
        water_available = digestate.imass["Water"]
        water_needed = n_h2o * h2o.MW
        if water_available < water_needed - 1e-9:
            raise RuntimeError(
                f"Not enough water in digestate for AD stoichiometry: "
                f"need {water_needed:.2f} kg/hr, have {water_available:.2f} kg/hr. "
                f"Check feed water content or Water chemical ID."
            )
        digestate.imass["Water"] -= water_needed # mass balances

        # produce biogas
        biogas.imol["Methane"] = n_ch4
        biogas.imol["CarbonDioxide"] = n_co2

        # adjust biogas composition if target specified
        if 0 < self.ch4_molfrac < 1:
            n_total = n_ch4 + n_co2
            n_ch4_target = self.ch4_molfrac * n_total
            n_co2_target = (1 - self.ch4_molfrac) * n_total
            biogas.imol["Methane"] = n_ch4_target
            biogas.imol["CarbonDioxide"] = n_co2_target

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
                hu = self.add_heat_utility(Q_kJph, T_in, T_out)
            except TypeError:
                hu = self.add_heat_utility(Q_kJph, T_in)


    def _cost(self):
        # cost on a per-digester basis, multiplied by number of digesters
        V_each = self.design_results["Digester volume each (m3)"]
        N = int(self.design_results["Number of digesters"])
        self.F_BM["Anaerobic digester"] = 1.0

        C_each = interp_capex(V_each)
        C_total = N * C_each
        self.design_results["ADBC_capex_each_$"] = C_each
        self.baseline_purchase_costs["Anaerobic digester"] = C_total