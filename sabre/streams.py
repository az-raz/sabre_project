"""
Stream functions (feed/product streams)

Purpose:
- Create BioSTEAM Stream objects with correct mass flowrates and composition
- Convert high-level scenario inputs (fresh feed kg/hr, moisture, quality bin) into component flows

Key entry points:
- make_sargassum_feed(fresh_feed_kgph, moisture_frac, quality)

Notes:
- Streams are typically specified in kg/hr; BioSTEAM may display kmol/hr
- Dry Sargassum is injected via a group name (e.g., SargassumDry_<quality>)
"""

import biosteam as bst

def make_sargassum_feed(fresh_feed_kgph: float, moisture_frac: float, quality: str):
    water_kgph = fresh_feed_kgph * moisture_frac
    dry_kgph   = fresh_feed_kgph * (1 - moisture_frac)

    group = f"SargassumDry_{quality}"

    return bst.Stream(
        "sargassum_feed",
        Water=water_kgph,
        **{group: dry_kgph},
        units="kg/hr",
        phase="l",
    )
