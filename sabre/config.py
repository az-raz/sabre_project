from pathlib import Path
import yaml

def load_assumptions():
    path = Path(__file__).resolve().parents[1] / "data" / "assumptions.yaml"
    with open(path, "r") as f:
        return yaml.safe_load(f)

def wet_tpd_to_kgph(wet_tpd: float, ton_definition: str) -> float:
    if ton_definition == "metric":
        kg_per_ton = 1000.0
    elif ton_definition == "short":
        kg_per_ton = 907.185
    else:
        raise ValueError("ton_definition must be 'metric' or 'short'")
    return wet_tpd * kg_per_ton / 24.0

def get_scale_feed_kgph(A: dict) -> float:
    wet_tpd = A["scale"]["wet_feed_ton_per_day"]
    ton_def = A["scale"]["ton_definition"]
    return wet_tpd_to_kgph(wet_tpd, ton_def)

def get_quality_params(A: dict, quality: str) -> dict:
    qb = A["quality_bins"]
    if quality not in qb:
        raise KeyError(f"Unknown quality '{quality}'. Options: {list(qb.keys())}")
    return qb[quality]
