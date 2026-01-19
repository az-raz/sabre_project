import yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # project root if sabre/ is inside it

def load_yaml(relpath: str):
    path = ROOT / relpath
    with open(path, "r") as f:
        return yaml.safe_load(f)