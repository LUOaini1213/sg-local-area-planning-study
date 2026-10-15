"""Land-use mix and gross floor area (GFA) potential by subzone, from the URA Master Plan land-use layers.

GFA potential of a parcel = parcel land area x gross plot ratio (GPR). The Master Plan GPR is the maximum
permissible intensity, so the total is what the plan allows, not what is built. Parcels without a numeric GPR are
kept out of the GFA total and reported by code: LND (landed housing, controlled by storey height, not GPR),
EVA (intensity subject to evaluation) and SDP (subject to a detailed or special plan).

Land-use mix is the Shannon entropy of the area shares of five activity groups (residential, commercial and mixed,
business, institution and community, parks and recreation), divided by ln(5) so that 0 means a single use and 1 an
even spread. Roads, rail, utilities, water, reserve sites and other non-activity land are left out of the mix.
"""
import math

import geopandas as gpd
import numpy as np
import pandas as pd

GROUP = {
    "RESIDENTIAL": "Residential",
    "RESIDENTIAL / INSTITUTION": "Residential",
    "RESIDENTIAL WITH COMMERCIAL AT 1ST STOREY": "Commercial & mixed",
    "COMMERCIAL & RESIDENTIAL": "Commercial & mixed",
    "COMMERCIAL": "Commercial & mixed",
    "COMMERCIAL / INSTITUTION": "Commercial & mixed",
    "HOTEL": "Commercial & mixed",
    "WHITE": "Commercial & mixed",
    "BUSINESS PARK": "Business",
    "BUSINESS PARK - WHITE": "Business",
    "BUSINESS 1": "Business",
    "BUSINESS 1 - WHITE": "Business",
    "BUSINESS 2": "Business",
    "BUSINESS 2 - WHITE": "Business",
    "EDUCATIONAL INSTITUTION": "Institution & community",
    "CIVIC & COMMUNITY INSTITUTION": "Institution & community",
    "HEALTH & MEDICAL CARE": "Institution & community",
    "PLACE OF WORSHIP": "Institution & community",
    "PARK": "Parks & recreation",
    "OPEN SPACE": "Parks & recreation",
    "SPORTS & RECREATION": "Parks & recreation",
    "BEACH AREA": "Parks & recreation",
    "ROAD": "Transport",
    "TRANSPORT FACILITIES": "Transport",
    "MASS RAPID TRANSIT": "Transport",
    "LIGHT RAPID TRANSIT": "Transport",
    "PORT / AIRPORT": "Transport",
    "UTILITY": "Utility & special",
    "SPECIAL USE": "Utility & special",
    "CEMETERY": "Utility & special",
    "AGRICULTURE": "Utility & special",
    "WATERBODY": "Water",
    "RESERVE SITE": "Reserve site",
}
ACTIVITY = ("Residential", "Commercial & mixed", "Business", "Institution & community", "Parks & recreation")


def group_of(lu_desc):
    return GROUP.get(str(lu_desc).strip().upper(), "Other")


def gpr_value(code):
    """Numeric GPR, or NaN for LND / EVA / SDP / blank."""
    try:
        v = float(str(code).strip())
    except ValueError:
        return float("nan")
    return v if v > 0 else float("nan")


def mix_index(areas):
    """Normalised Shannon entropy of activity-group areas (dict or Series group -> m2)."""
    a = np.array([float(areas.get(g, 0.0)) for g in ACTIVITY])
    tot = a.sum()
    if tot <= 0:
        return float("nan")
    p = a[a > 0] / tot
    return max(0.0, float(-(p * np.log(p)).sum() / math.log(len(ACTIVITY))))  # max() turns -0.0 into 0.0


def load(path, crs=3414):
    lu = gpd.read_file(path, columns=["LU_DESC", "GPR"]).to_crs(crs)
    lu["group"] = lu.LU_DESC.map(group_of)
    lu["gpr"] = lu.GPR.map(gpr_value)
    lu["gpr_code"] = np.where(lu.gpr.notna(), "numeric", lu.GPR.fillna("blank").astype(str).str.strip())
    return lu


def overlay_subzones(lu, sz):
    """Cut parcels by subzone boundaries so areas add up per subzone. sz needs SUBZONE_N and PLN_AREA_N."""
    cut = gpd.overlay(lu, sz[["SUBZONE_N", "PLN_AREA_N", "geometry"]], how="intersection", keep_geom_type=True)
    cut["area_m2"] = cut.area
    cut["gfa_m2"] = cut.area_m2 * cut.gpr
    return cut


def subzone_table(cut):
    """One row per subzone: land area by group, mix index, GFA potential, area with non-numeric GPR."""
    area = cut.pivot_table(index="SUBZONE_N", columns="group", values="area_m2", aggfunc="sum", fill_value=0.0)
    out = pd.DataFrame(index=area.index)
    out["land_ha"] = area.sum(axis=1) / 1e4
    for g in ACTIVITY + ("Transport", "Reserve site"):
        out[f"share_{g}"] = area.get(g, 0.0) / area.sum(axis=1)
    out["mix_index"] = [mix_index(area.loc[i]) for i in area.index]
    gfa = cut.groupby("SUBZONE_N").gfa_m2.sum(min_count=1).fillna(0.0)
    out["gfa_potential_m2"] = gfa
    res = cut[cut.group.isin(["Residential"]) | cut.LU_DESC.isin(["COMMERCIAL & RESIDENTIAL",
                                                                   "RESIDENTIAL WITH COMMERCIAL AT 1ST STOREY"])]
    out["gfa_residential_zoned_m2"] = res.groupby("SUBZONE_N").gfa_m2.sum(min_count=1).reindex(out.index).fillna(0)
    for code in ("LND", "EVA", "SDP"):
        out[f"ha_gpr_{code}"] = cut[cut.gpr_code == code].groupby("SUBZONE_N").area_m2.sum().reindex(
            out.index).fillna(0) / 1e4
    out["gfa_per_land_m2"] = out.gfa_potential_m2 / (out.land_ha * 1e4)
    return out
