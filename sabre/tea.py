import biosteam as bst

class ADBaselineTEA(bst.TEA):
    """
    Minimal TEA implementation for AD + upgrading baseline.

    - FOC (fixed operating cost): placeholder as fraction of FCI.
      This is where maintenance/labor/overhead live in a simplified TEA.

    - VOC (variable operating cost): use system-level material + utility costs,
      which come from stream prices and utility usage.
    """
    
    def _FOC(self, FCI):
        # Baseline placeholder: 4% of FCI per year.
        return 0.04 * FCI

    def _VOC(self, FCI):
        # Variable costs already computed by BioSTEAM from stream prices + utilities.
        return self.system.material_cost + self.system.utility_cost


def make_ad_baseline_tea(sys):
    tea = ADBaselineTEA(
        system=sys,

        # targets
        IRR=0.10,
        duration=(2026, 2046),
        depreciation="MACRS7",
        income_tax=0.21,
        operating_days=330,

        # capital deployment
        construction_schedule=(0.4, 0.6),
        WC_over_FCI=0.05,

        # financing
        finance_interest=0.08,
        finance_years=10,
        finance_fraction=0.6,

        # Operating costs
        lang_factor=None,
        startup_months=3,
        startup_FOCfrac=1.0,
        startup_VOCfrac=0.5,
        startup_salesfrac=0.5,
    )
    return tea