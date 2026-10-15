"""Residents by subzone (SingStat GHS 2025, table C020123) placed on housing land as weighted origin points.

Dasymetric step. Within each MP2019 subzone, residents are shared among Master Plan residential parcels in
proportion to parcel area x GPR (a proxy for floor area). Landed parcels (GPR code LND) take GPR 1.0; parcels with
EVA or SDP take the median numeric GPR of the same land-use class. Each parcel's residents are then spread evenly
over the points of a fixed 25 m lattice that fall inside it (the representative point when none do). Subzones with residents but no residential parcel fall back to a grid over the whole subzone.
The MP2019 land-use layer is used because SingStat tabulates residents on MP2019 boundaries.
"""
import json
import re

import geopandas as gpd
import numpy as np
import pandas as pd

AGE_BANDS = {"age_0_4": ["0 - 4"], "age_5_14": ["5 - 9", "10-14"],
             "age_65_plus": ["65 - 69", "70 - 74", "75 - 79", "80 - 84", "85 - 89", "90 & Over"]}


def key(name):
    return re.sub(r"[^A-Z0-9]", "", str(name).upper())


def _num(v):
    v = str(v).strip()
    return 0 if v in ("-", "", "na") else int(float(v))


def parse_singstat(payload):
    """Rows '2.1' style are subzones, '2' planning-area totals, '1' Singapore. Returns (subzones, planning areas)."""
    rows = payload["Data"]["row"]
    sz, pa = [], []
    for r in rows:
        tot = next(c for c in r["columns"] if c["key"] == "Total")["columns"]
        vals = {c["key"]: _num(c["value"]) for c in tot}
        rec = {"name": r["rowText"].replace(" - Total", "").strip(), "residents": vals["Total"]}
        for band, keys in AGE_BANDS.items():
            rec[band] = sum(vals[k] for k in keys)
        depth = r["rowNo"].count(".")
        if depth == 1:
            sz.append(rec)
        elif depth == 0 and r["rowText"] != "Total":
            pa.append(rec)
    return pd.DataFrame(sz), pd.DataFrame(pa)


def load_population(path):
    return parse_singstat(json.loads(open(path, encoding="utf-8").read()))


def parcel_weights(lu):
    """Area x GPR weight for residential parcels; lu needs LU_DESC, GPR, geometry in metres."""
    g = pd.to_numeric(lu.GPR, errors="coerce")
    g = g.where(g > 0)
    g = g.where(lu.GPR.astype(str).str.strip() != "LND", 1.0)
    g = g.fillna(g.groupby(lu.LU_DESC).transform("median"))
    g = g.fillna(1.0)
    return lu.geometry.area * g


def _grid(bounds, step):
    minx, miny, maxx, maxy = bounds
    xs = np.arange(np.floor(minx / step) * step + step / 2, maxx, step)
    ys = np.arange(np.floor(miny / step) * step + step / 2, maxy, step)
    gx, gy = np.meshgrid(xs, ys)
    return gpd.GeoDataFrame(geometry=gpd.points_from_xy(gx.ravel(), gy.ravel()))


def points_in(polys, step):
    """Grid points (on a fixed step-aligned lattice) inside each polygon; polygons that catch no lattice point get
    their representative point. Returns GeoDataFrame with column 'poly' = index label of the polygon."""
    grid = _grid(polys.total_bounds, step).set_crs(polys.crs)
    hit = gpd.sjoin(grid, polys[["geometry"]], predicate="within", how="inner")
    hit = hit.rename(columns={"index_right": "poly"})[["poly", "geometry"]]
    hit = hit[~hit.index.duplicated()]  # a lattice point on a shared edge goes to one polygon only
    empty = polys.index.difference(hit.poly.unique())
    rep = gpd.GeoDataFrame({"poly": empty}, geometry=polys.loc[empty].representative_point().values, crs=polys.crs)
    return pd.concat([hit, rep], ignore_index=True)


def allocate(subzones, parcels, step=25):
    """subzones: GeoDataFrame with SUBZONE_N, PLN_AREA_N, residents (+ age bands), geometry.
    parcels: residential GeoDataFrame with LU_DESC, GPR, geometry, same CRS.
    Returns a point GeoDataFrame: subzone, planning_area, method, residents (float) and age bands per point.
    Point weights sum exactly to each subzone's SingStat count."""
    parcels = parcels.copy()
    parcels["w"] = parcel_weights(parcels)
    parcels["a0"] = parcels.geometry.area
    sz = subzones[subzones.residents > 0].reset_index(drop=True)
    cut = gpd.overlay(parcels[["w", "a0", "LU_DESC", "geometry"]], sz[["SUBZONE_N", "geometry"]],
                      how="intersection", keep_geom_type=True)
    cut["w"] = cut.w * cut.area / cut.a0  # a parcel split by a subzone line keeps its weight per m2
    cut = cut[(cut.area > 1.0) & (cut.w > 0)].reset_index(drop=True)
    pts = points_in(cut, step)
    pts["SUBZONE_N"] = cut.SUBZONE_N.to_numpy()[pts.poly.to_numpy()]
    n_in = pts.groupby("poly").size()
    w_sz = cut.groupby("SUBZONE_N").w.sum()
    pts["share"] = (cut.w.to_numpy()[pts.poly.to_numpy()] / n_in.loc[pts.poly].to_numpy()
                    / w_sz.loc[pts.SUBZONE_N].to_numpy())
    pts["method"] = "dasymetric"
    bare = sz[~sz.SUBZONE_N.isin(w_sz.index)].reset_index(drop=True)
    if len(bare):
        bp = points_in(bare, step)
        bp["SUBZONE_N"] = bare.SUBZONE_N.to_numpy()[bp.poly.to_numpy()]
        bp["share"] = 1.0 / bp.groupby("poly").poly.transform("size").to_numpy()
        bp["method"] = "subzone grid"
        pts = pd.concat([pts, bp], ignore_index=True)
    s = sz.set_index("SUBZONE_N")
    pts["planning_area"] = s.PLN_AREA_N.loc[pts.SUBZONE_N].to_numpy()
    for c in ["residents"] + [b for b in AGE_BANDS if b in s.columns]:
        pts[c] = pts.share.to_numpy() * s[c].loc[pts.SUBZONE_N].to_numpy()
    pts = pts.rename(columns={"SUBZONE_N": "subzone"}).drop(columns=["poly"])
    return gpd.GeoDataFrame(pts, geometry="geometry", crs=subzones.crs)


def attach(subzones_gdf, sz_pop):
    """Join SingStat subzone rows onto MP2019 subzone polygons by normalised name."""
    s = subzones_gdf.copy()
    s["k"] = s.SUBZONE_N.map(key)
    p = sz_pop.assign(k=sz_pop.name.map(key)).drop(columns="name")
    s = s.merge(p, on="k", how="left")
    missing = s.residents.isna()
    for c in ["residents"] + list(AGE_BANDS):
        s[c] = s[c].fillna(0)
    return s.drop(columns="k"), int(missing.sum())
