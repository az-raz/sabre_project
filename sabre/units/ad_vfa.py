"""
Acidogenic (VFA-targeted) digester unit operation

Purpose:
- Arrested/acidogenic digestion: convert a fraction of VS into VFAs (no methanogenesis)
- Size digester using HRT + headspace
- Enforce maximum single-digester volume and model parallel digesters
- CAPEX scaling via ADBC interpolation (same as your AD unit)
- Optional: add Heat-Shock (HS) energy penalty as an average additional heating duty

Outputs (3):
0) offgas      : default CO2 only (optional)
1) digestate   : liquid/solids after VFA removal (if enabled)
2) vfa_product : VFA-rich liquid stream (if separation enabled)
"""

import math
import biosteam as bst

# -----------------------------
# ADBC interpolation
# -----------------------------
GAL_TO_M3 = 0.003785411784  # US gallons -> m3
ADBC_VOL_M3 = [878, 1755, 2633, 3510, 5265, 8775]
ADBC_CAPEX  = [1720964, 1750201, 1779439, 1808676, 1867151, 1984101]

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

# -----------------------------
# Acidogenic digester
# -----------------------------
class AcidogenicDigester(bst.Unit):
    _N_ins = 1
    _N_outs = 3  # offgas, digestate, vfa_product

    # ADBC already installed; keep BM=1
    F_BM = {"Acidogenic digester": 1.0}

    def __init__(
        self, ID="", ins=None, outs=(),
        # performance (acidogenic)
        vs_destruction=0.50,                     # fraction of VS converted
        vfa_kg_per_kg_vs_destroyed=0.80,         # kg VFA produced per kg VS destroyed
        vfa_split=None,                          # dict: {chemical_id: fraction} sums to 1
        vfa_recovery=0.90,                       # fraction of produced VFA sent to vfa_product stream
        produce_offgas_co2=False,                # if True, vent CO2

        # sizing
        hrt_days=15.0,
        slurry_density_kg_per_m3=1000.0,
        headspace_frac=0.2,
        max_single_digester_volume_MG=1.5,

        # utilities
        mixing_W_per_m3=5.0,
        influent_temperature_K=298.15,           # 25C
        target_temperature_K=308.15,             # 35C
        cp_kJ_per_kgK=4.18,                      # slurry ~ water

        # heat shock (HS) option
        enable_heat_shock=False,
        hs_target_temperature_K=338.15,          # 65C
        hs_events_per_day=1.0/7.0,               # weekly as default
        hs_heated_fraction_of_liquid=0.10,       # slipstream fraction heated per event (0-1)
        hs_duration_min=15.0,                    # stored for reporting (not used in duty calc)

        **kwargs
    ):
        super().__init__(ID, ins, outs, **kwargs)

        # performance
        self.vs_destruction = float(vs_destruction)
        self.vfa_kg_per_kg_vs_destroyed = float(vfa_kg_per_kg_vs_destroyed)
        self.vfa_recovery = float(vfa_recovery)
        self.produce_offgas_co2 = bool(produce_offgas_co2)

        # default VFA split
        self.vfa_split = vfa_split

        # sizing
        self.hrt_days = float(hrt_days)
        self.slurry_density_kg_per_m3 = float(slurry_density_kg_per_m3)
        self.headspace_frac = float(headspace_frac)
        self.max_single_digester_volume_m3 = float(max_single_digester_volume_MG) * 1e6 * GAL_TO_M3

        # utilities
        self.mixing_W_per_m3 = float(mixing_W_per_m3)
        self.influent_temperature_K = float(influent_temperature_K)
        self.target_temperature_K = float(target_temperature_K)
        self.cp_kJ_per_kgK = float(cp_kJ_per_kgK)

        # HS
        self.enable_heat_shock = bool(enable_heat_shock)
        self.hs_target_temperature_K = float(hs_target_temperature_K)
        self.hs_events_per_day = float(hs_events_per_day)
        self.hs_heated_fraction_of_liquid = float(hs_heated_fraction_of_liquid)
        self.hs_duration_min = float(hs_duration_min)

        self.F_BM = dict(self.F_BM)

    # -------------
    # helpers
    # -------------
    def _resolve_vfa_split(self):
        """
        Returns (split_dict, mode) where:
        - split_dict: {chem_id: frac} sums to 1
        """
        chems = bst.settings.thermo.chemicals
        ids = set(chems.IDs)

        # If provided a split, validate IDs exist
        if self.vfa_split is not None:
            split = dict(self.vfa_split)
            missing = [k for k in split.keys() if k not in ids]
            if missing:
                raise RuntimeError(
                    f"VFA split includes chemicals not in thermo: {missing}. "
                    f"Either add them to your chemicals list or use a single pseudo component 'VFA'."
                )
            s = sum(split.values())
            if s <= 0:
                raise RuntimeError("vfa_split sums to 0; provide positive fractions.")
            # normalize
            split = {k: v/s for k, v in split.items()}
            return split, "acids"

        common = ["AceticAcid", "PropionicAcid", "ButyricAcid", "ValericAcid", "HexanoicAcid"]
        if all(c in ids for c in common):
            split = {"AceticAcid":0.35, "PropionicAcid":0.10, "ButyricAcid":0.35, "ValericAcid":0.10, "HexanoicAcid":0.10}
            return split, "acids"

        if "VFA" in ids:
            return {"VFA": 1.0}, "pseudo"

        raise RuntimeError(
            "No valid VFA representation found. Either:\n"
            "  (1) Add acids to thermo: AceticAcid, PropionicAcid, ButyricAcid, ValericAcid, CaproicAcid\n"
            "  (2) OR add a single pseudo chemical named 'VFA' and use that."
        )

    # -------------
    # mass balances
    # -------------
    def _run(self):
        feed = self.ins[0]
        offgas, digestate, vfa_product = self.outs

        offgas.empty()
        vfa_product.empty()
        digestate.copy_like(feed)

        offgas.phase = "g"
        digestate.phase = "l"
        vfa_product.phase = "l"

        # --- compute TS/VS robustly ---
        water = digestate.imass["Water"]
        TS = max(digestate.F_mass - water, 0.0)    # total solids (kg/h)
        ash = digestate.imass["Ash"]
        VS = max(TS - ash, 0.0)                    # volatile solids (kg/h)

        VS_destroyed = self.vs_destruction * VS
        if VS_destroyed <= 0:
            return

        # --------------------------------------------
        # Remove destroyed VS proportionally from organics
        # --------------------------------------------
        # Treat Ash and Lignin as inert
        digestible = [
            "Glucan", "Xylan", "Mannan", "Galactan",
            "Alginate", "Fucoidan", "Mannitol",
            "Protein", "OtherSolids",
            "Cellulose",
        ]

        ids = set(bst.settings.thermo.chemicals.IDs)

        # Build available digestible pool (kg/h)
        avail = {}
        for cid in digestible:
            if cid not in ids:
                continue
            m = float(digestate.imass[cid])
            if m > 0:
                avail[cid] = m

        pool = sum(avail.values())
        if pool <= 1e-12:
            return  # nothing digestible found

        # Amount of organics to destroy (kg/h)
        remove = min(VS_destroyed, pool)

        # Proportional removal
        for cid, m in avail.items():
            take = remove * (m / pool)
            digestate.imass[cid] -= take

        # --- produce VFAs from destroyed VS proxy mass ---
        split, mode = self._resolve_vfa_split()
        vfa_total = self.vfa_kg_per_kg_vs_destroyed * remove  # kg/h

        # Put VFAs into vfa_product based on recovery, remainder stays in digestate
        rec = min(max(self.vfa_recovery, 0.0), 1.0)
        vfa_to_prod = rec * vfa_total
        vfa_to_dig = (1.0 - rec) * vfa_total

        for chem_id, frac in split.items():
            m = vfa_total * frac
            vfa_product.imass[chem_id] += vfa_to_prod * frac
            digestate.imass[chem_id] += vfa_to_dig * frac

        # Optional: vent CO2 as a simple placeholder fraction of VS destroyed
        if self.produce_offgas_co2 and ("CarbonDioxide" in bst.settings.thermo.chemicals.IDs):
            # crude: 5% of destroyed mass to CO2 (tunable)
            co2_mass = 0.05 * remove
            digestate.imass["Water"] += 0.0  # no-op placeholder
            offgas.imass["CarbonDioxide"] = co2_mass

    # -------------
    # sizing + utilities
    # -------------
    def _design(self):
        feed = self.ins[0]

        slurry_m3_per_hr = feed.F_mass / self.slurry_density_kg_per_m3
        V_liquid = slurry_m3_per_hr * 24.0 * self.hrt_days

        hf = min(max(self.headspace_frac, 0.0), 0.95)
        V_total = V_liquid / (1.0 - hf)

        V_max = self.max_single_digester_volume_m3
        N = max(1, math.ceil(V_total / V_max))
        V_each = V_total / N

        self.design_results["Slurry flow (m3/hr)"] = slurry_m3_per_hr
        self.design_results["HRT (days)"] = self.hrt_days
        self.design_results["Headspace frac"] = hf
        self.design_results["Total digester volume (m3)"] = V_total
        self.design_results["Number of digesters"] = N
        self.design_results["Digester volume each (m3)"] = V_each

        # ----- Utilities: mixing -----
        mixing_kW = (self.mixing_W_per_m3 * V_liquid) / 1000.0
        self.design_results["Mixing power (kW)"] = mixing_kW
        self.power_utility.consumption = mixing_kW
        self.power_utility.production = 0.0

        # ----- Utilities: base heating (influent -> target) -----
        T_in = self.influent_temperature_K
        T_base = self.target_temperature_K
        dT = max(0.0, T_base - T_in)
        m_dot_kgph = feed.F_mass
        Q_base_kJph = m_dot_kgph * self.cp_kJ_per_kgK * dT

        self.design_results["Influent T (K)"] = T_in
        self.design_results["Base target T (K)"] = T_base
        self.design_results["Base heating duty (kJ/h)"] = Q_base_kJph

        # ----- HS penalty (average) -----
        Q_hs_kJph = 0.0
        if self.enable_heat_shock:
            # heat a fraction of the reactor liquid volume each event from base T to HS T
            frac = min(max(self.hs_heated_fraction_of_liquid, 0.0), 1.0)
            events_per_day = max(0.0, self.hs_events_per_day)
            dT_hs = max(0.0, self.hs_target_temperature_K - T_base)

            # liquid mass in reactor (kg) ≈ V_liquid * density
            m_liq_kg = V_liquid * self.slurry_density_kg_per_m3
            Q_event_kJ = (m_liq_kg * frac) * self.cp_kJ_per_kgK * dT_hs
            Q_day_kJ = Q_event_kJ * events_per_day
            Q_hs_kJph = Q_day_kJ / 24.0

            self.design_results["HS enabled"] = True
            self.design_results["HS target T (K)"] = self.hs_target_temperature_K
            self.design_results["HS events/day"] = events_per_day
            self.design_results["HS heated fraction"] = frac
            self.design_results["HS duration (min)"] = self.hs_duration_min
            self.design_results["HS avg duty (kJ/h)"] = Q_hs_kJph
        else:
            self.design_results["HS enabled"] = False

        Q_total_kJph = Q_base_kJph + Q_hs_kJph
        self.design_results["Total heating duty (kJ/h)"] = Q_total_kJph

        if Q_total_kJph > 0:
            try:
                self.add_heat_utility(Q_total_kJph, T_in, max(T_base, self.hs_target_temperature_K if self.enable_heat_shock else T_base))
            except TypeError:
                self.add_heat_utility(Q_total_kJph, T_in)

    # -------------
    # costing
    # -------------
    def _cost(self):
        V_each = self.design_results["Digester volume each (m3)"]
        N = int(self.design_results["Number of digesters"])
        self.F_BM["Acidogenic digester"] = 1.0

        C_each = interp_capex(V_each)
        C_total = N * C_each

        self.design_results["ADBC_capex_each_$"] = C_each
        self.baseline_purchase_costs["Acidogenic digester"] = C_total