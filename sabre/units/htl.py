from __future__ import annotations

import biosteam as bst


class HTLFeedConditioner(bst.Unit):
    """
    Adjust slurry water content to hit a target solids mass fraction.

    ins:
        0 - wet biomass feed
        1 - makeup water
    outs:
        0 - conditioned slurry
        1 - removed water
    """
    _N_ins = 2
    _N_outs = 2
    _units = {
        "Feed mass flow": "kg/hr",
        "Dry mass flow": "kg/hr",
        "Target solids fraction": "-",
    }

    def __init__(
        self,
        ID="",
        ins=None,
        outs=(),
        target_solids_wt_frac=0.10,
    ):
        super().__init__(ID, ins, outs)
        self.target_solids_wt_frac = target_solids_wt_frac

    def _run(self):
        if not (0 < self.target_solids_wt_frac < 1):
            raise ValueError(
                f"{self.ID}: target_solids_wt_frac must be between 0 and 1."
            )

        feed, makeup_water = self.ins
        conditioned, removed_water = self.outs

        conditioned.copy_like(feed)
        removed_water.empty()

        water_mass = conditioned.imass["Water"]
        dry_mass = conditioned.F_mass - water_mass

        if dry_mass <= 0:
            return

        target_water_mass = (
            dry_mass * (1 - self.target_solids_wt_frac) / self.target_solids_wt_frac
        )

        if water_mass < target_water_mass:
            water_needed = target_water_mass - water_mass
            water_available = makeup_water.imass["Water"]
            water_added = min(water_needed, water_available)

            conditioned.imass["Water"] += water_added
            makeup_water.imass["Water"] -= water_added

        elif water_mass > target_water_mass:
            water_removed = water_mass - target_water_mass
            conditioned.imass["Water"] -= water_removed
            removed_water.imass["Water"] += water_removed

    def _design(self):
        conditioned = self.outs[0]
        dry_mass = conditioned.F_mass - conditioned.imass["Water"]

        self.design_results["Feed mass flow"] = self.ins[0].F_mass
        self.design_results["Dry mass flow"] = dry_mass
        self.design_results["Target solids fraction"] = self.target_solids_wt_frac


class HTLReactor(bst.Unit):
    """
    Lumped HTL reactor.

    Converts dry feed into:
        - HTLBiocrude
        - HTLAqueousOrg
        - HTLGas
        - HTLChar

    Water is carried through as reaction medium.

    ins:
        0 - conditioned slurry
    outs:
        0 - mixed HTL effluent
    """
    _N_ins = 1
    _N_outs = 1
    _units = {
        "Feed mass flow": "kg/hr",
        "Dry feed mass flow": "kg/hr",
        "Slurry volumetric flow": "m3/hr",
        "Residence time": "min",
        "Reactor volume": "m3",
        "Temperature": "C",
        "Pressure": "bar",
    }

    def __init__(
        self,
        ID="",
        ins=None,
        outs=(),
        temperature_C=280.0,
        pressure_bar=100.0,
        residence_time_min=15.0,
        biocrude_yield_wt_frac_dry=0.12,
        aqueous_yield_wt_frac_dry=0.46,
        gas_yield_wt_frac_dry=0.10,
        char_yield_wt_frac_dry=0.32,
        slurry_density_kg_per_m3=1000.0,
    ):
        super().__init__(ID, ins, outs)

        self.temperature_C = temperature_C
        self.pressure_bar = pressure_bar
        self.residence_time_min = residence_time_min

        self.biocrude_yield_wt_frac_dry = biocrude_yield_wt_frac_dry
        self.aqueous_yield_wt_frac_dry = aqueous_yield_wt_frac_dry
        self.gas_yield_wt_frac_dry = gas_yield_wt_frac_dry
        self.char_yield_wt_frac_dry = char_yield_wt_frac_dry

        self.slurry_density_kg_per_m3 = slurry_density_kg_per_m3

    def _run(self):
        feed = self.ins[0]
        effluent = self.outs[0]
        effluent.empty()

        water_mass = feed.imass["Water"]
        dry_mass = feed.F_mass - water_mass
        if dry_mass < 0:
            dry_mass = 0.0

        total_yield = (
            self.biocrude_yield_wt_frac_dry
            + self.aqueous_yield_wt_frac_dry
            + self.gas_yield_wt_frac_dry
            + self.char_yield_wt_frac_dry
        )

        if total_yield > 1.000001:
            raise ValueError(
                f"{self.ID}: HTL yields sum to {total_yield:.4f}, which is > 1.0."
            )

        if self.residence_time_min <= 0:
            raise ValueError(f"{self.ID}: residence_time_min must be > 0.")

        if self.slurry_density_kg_per_m3 <= 0:
            raise ValueError(f"{self.ID}: slurry_density_kg_per_m3 must be > 0.")

        biocrude_mass = dry_mass * self.biocrude_yield_wt_frac_dry
        aqueous_mass = dry_mass * self.aqueous_yield_wt_frac_dry
        gas_mass = dry_mass * self.gas_yield_wt_frac_dry
        char_mass = dry_mass * self.char_yield_wt_frac_dry

        remainder = dry_mass - (
            biocrude_mass + aqueous_mass + gas_mass + char_mass
        )
        if remainder < 0:
            remainder = 0.0

        effluent.imass["Water"] = water_mass
        effluent.imass["HTLBiocrude"] = biocrude_mass
        effluent.imass["HTLAqueousOrg"] = aqueous_mass
        effluent.imass["HTLGas"] = gas_mass
        effluent.imass["HTLChar"] = char_mass + remainder

        effluent.T = self.temperature_C + 273.15
        effluent.P = self.pressure_bar * 1e5

    def _design(self):
        feed = self.ins[0]
        dry_mass = feed.F_mass - feed.imass["Water"]
        slurry_vol_flow = feed.F_mass / self.slurry_density_kg_per_m3
        reactor_volume = slurry_vol_flow * (self.residence_time_min / 60.0)

        self.design_results["Feed mass flow"] = feed.F_mass
        self.design_results["Dry feed mass flow"] = dry_mass
        self.design_results["Slurry volumetric flow"] = slurry_vol_flow
        self.design_results["Residence time"] = self.residence_time_min
        self.design_results["Reactor volume"] = reactor_volume
        self.design_results["Temperature"] = self.temperature_C
        self.design_results["Pressure"] = self.pressure_bar

    def _cost(self):
        # placeholder: leave blank for now unless you already have a YAML cost block
        pass


class HTLPhaseSeparator(bst.Unit):
    """
    Rule-based HTL phase separator.

    Splits HTL effluent into:
        0 - gas
        1 - biocrude
        2 - aqueous
        3 - solids

    Assumes:
        - HTLGas goes to gas
        - HTLBiocrude mostly goes to oil
        - HTLAqueousOrg mostly goes to aqueous
        - HTLChar goes to solids
        - most water goes to aqueous
    """
    _N_ins = 1
    _N_outs = 4
    _units = {
        "Feed mass flow": "kg/hr",
        "Oil recovery": "-",
        "Aqueous recovery": "-",
        "Water to oil fraction": "-",
    }

    def __init__(
        self,
        ID="",
        ins=None,
        outs=(),
        biocrude_recovery_to_oil=0.98,
        aqueous_org_recovery_to_aqueous=0.99,
        char_recovery_to_solids=1.00,
        gas_recovery_to_gas=1.00,
        oil_water_to_oil_frac=0.02,
    ):
        super().__init__(ID, ins, outs)

        self.biocrude_recovery_to_oil = biocrude_recovery_to_oil
        self.aqueous_org_recovery_to_aqueous = aqueous_org_recovery_to_aqueous
        self.char_recovery_to_solids = char_recovery_to_solids
        self.gas_recovery_to_gas = gas_recovery_to_gas
        self.oil_water_to_oil_frac = oil_water_to_oil_frac

    def _run(self):
        feed = self.ins[0]
        gas, oil, aqueous, solids = self.outs

        gas.empty()
        oil.empty()
        aqueous.empty()
        solids.empty()

        # Gas
        gas_mass = feed.imass["HTLGas"]
        gas.imass["HTLGas"] = gas_mass * self.gas_recovery_to_gas
        aqueous.imass["HTLGas"] = gas_mass * (1 - self.gas_recovery_to_gas)

        # Biocrude
        biocrude_mass = feed.imass["HTLBiocrude"]
        oil.imass["HTLBiocrude"] = biocrude_mass * self.biocrude_recovery_to_oil
        aqueous.imass["HTLBiocrude"] = biocrude_mass * (1 - self.biocrude_recovery_to_oil)

        # Aqueous organics
        aq_org_mass = feed.imass["HTLAqueousOrg"]
        aqueous.imass["HTLAqueousOrg"] = aq_org_mass * self.aqueous_org_recovery_to_aqueous
        oil.imass["HTLAqueousOrg"] = aq_org_mass * (1 - self.aqueous_org_recovery_to_aqueous)

        # Char
        char_mass = feed.imass["HTLChar"]
        solids.imass["HTLChar"] = char_mass * self.char_recovery_to_solids
        aqueous.imass["HTLChar"] = char_mass * (1 - self.char_recovery_to_solids)

        # Water
        water_mass = feed.imass["Water"]
        oil.imass["Water"] = water_mass * self.oil_water_to_oil_frac
        aqueous.imass["Water"] = water_mass * (1 - self.oil_water_to_oil_frac)

        for s in self.outs:
            s.T = feed.T
            s.P = feed.P

    def _design(self):
        self.design_results["Feed mass flow"] = self.ins[0].F_mass
        self.design_results["Oil recovery"] = self.biocrude_recovery_to_oil
        self.design_results["Aqueous recovery"] = self.aqueous_org_recovery_to_aqueous
        self.design_results["Water to oil fraction"] = self.oil_water_to_oil_frac

    def _cost(self):
        # placeholder for later
        pass