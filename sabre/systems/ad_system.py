"""
AD system builder (one-block flowsheet)

Purpose:
- Build the AD process block as a BioSTEAM System
- Load assumptions, create feed stream, instantiate AD unit, return bst.System

Key entry points:
- create_ad_system(quality=...)

Notes:
- Uses plant-scale throughput from YAML (e.g., 15,000 ton/day wet feed)
- Feed composition (moisture/ash/VS/TS) is quality-bin dependent
- Downstream processing (biogas upgrading, dewatering, separations) should be added here next
"""

import biosteam as bst
from sabre.streams import make_sargassum_feed
from sabre.config import load_assumptions, get_scale_feed_kgph, get_quality_params
from sabre.units.ad import AnaerobicDigester

# Creating AD system
def create_ad_system(quality="pelagic_high_quality", mode="biogas"):
    A = load_assumptions()
    fresh_feed_kgph = get_scale_feed_kgph(A)
    q = get_quality_params(A, quality)
    vs_ts = q["vs_ts"]
    moisture_frac = q["moisture_frac"]

    feed = make_sargassum_feed(
    fresh_feed_kgph=fresh_feed_kgph,
    moisture_frac=moisture_frac,
    quality=quality,
    )

    adp = A["ad_performance"]
    AD = AnaerobicDigester( 
    "AD",
    ins=feed,
    outs=("biogas", "digestate"),
    vs_ts=vs_ts,
    vs_destruction=adp["vs_destruction"],
    ch4_kg_per_kg_vs=adp["ch4_kg_per_kg_vs"],
    ch4_molfrac=adp["ch4_molfrac"],
)

    return bst.System("AD_sys", path=(AD,))