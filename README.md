# sabre_project

This is a BioSTEAM model for Sargassum biorefinery (SaBRe).

## Setup
```bash
conda create -n sabre python=3.10 -y
conda activate sabre
pip install -e
```

## Model Notes
30/1/26:
<img width="1225" height="292" alt="image" src="https://github.com/user-attachments/assets/51709eab-f5d4-4097-a5ef-066af69f73ad" />

The model currently has preprocessing (press and mill), anaerboic digestor (AD), biogas upgrading (UP), and screw press (SP) units build. I only have economoic information on AD, UP and SP units, and will need to look further at the preprocessing unit CAPEX/OPEX. I need to look further into utilities, temperatures, and pressures of all the units. In the next few days, I will need to start pulling flowsheets for the development of fermentors. The products that were initially discussed were lactic acid and ethanol since there is already substantial work done on BioSTEAM for those processes.

To-do:
1. Compile economic CAPEX/OPEX in a table (include sources)
2. Start working on the fermentor unit (products to first look at: ethanol and lactic acid)
