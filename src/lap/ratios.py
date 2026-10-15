"""Population-to-amenity ratios by planning area, and the study area's position against the island-wide median.

Counts are amenities whose point lies inside the MP2019 planning-area polygon; park provision is NParks park area
inside the polygon per resident. Boundary-blind counts understate provision for areas whose residents use
facilities next door, so the brief reads them together with the walking-distance coverage, which is boundary-free.
Planning areas with fewer than MIN_PA_RESIDENTS residents are left out of the median.
"""
import geopandas as gpd
import numpy as np
import pandas as pd

POP_BASE = {"hawker": "residents", "clinic": "residents", "community_club": "residents",
            "primary_school": "age_5_14", "mrt_exit": "residents", "bus_stop": "residents"}


def counts(pa, amen, kinds):
    j = gpd.sjoin(amen[amen.kind.isin(kinds)], pa[["PLN_AREA_N", "geometry"]], predicate="within")
    c = j.groupby(["PLN_AREA_N", "kind"]).size().unstack(fill_value=0)
    return c.reindex(index=pa.PLN_AREA_N, columns=list(kinds), fill_value=0)


def park_area(pa, parks):
    cut = gpd.overlay(parks[["geometry"]], pa[["PLN_AREA_N", "geometry"]], how="intersection", keep_geom_type=True)
    return cut.assign(a=cut.area).groupby("PLN_AREA_N").a.sum().reindex(pa.PLN_AREA_N, fill_value=0.0)


def ratio_table(pa_pop, cnt, park_m2):
    """pa_pop: DataFrame indexed by planning area with residents and age bands."""
    t = pa_pop.copy()
    for k in cnt.columns:
        base = t[POP_BASE[k]]
        t[f"n_{k}"] = cnt[k].reindex(t.index).fillna(0).astype(int)
        t[f"per_{k}"] = np.where(t[f"n_{k}"] > 0, base / t[f"n_{k}"].replace(0, np.nan), np.inf)
    t["park_m2_per_resident"] = park_m2.reindex(t.index).fillna(0) / t.residents.replace(0, np.nan)
    return t


def compare(table, area, columns, min_residents):
    """Study area value, island-wide median and the area's rank (1 = best provided) for each column."""
    pool = table[table.residents >= min_residents]
    rows = []
    for c in columns:
        better_high = c.startswith("within_") or c == "park_m2_per_resident"
        v = table.loc[area, c]
        med = float(np.median(pool[c]))  # an area with none of the amenity counts as inf (worst), not as missing
        ranked = pool[c].rank(ascending=not better_high, method="min")
        rows.append({"metric": c, "study_area": v, "island_median": med,
                     "rank": int(ranked.loc[area]) if area in ranked.index else None, "of": len(pool),
                     "better_is": "higher" if better_high else "lower"})
    return pd.DataFrame(rows)
