"""End-to-end build. Each step caches its product in data/work so later steps can be re-run alone."""
import json

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer

from . import access, amenities, landuse, network, population, ratios, scenario
from .config import (CRS, FIG, GFA_PER_DWELLING_M2, GFA_PER_DWELLING_RANGE, GRID_M, MIN_PA_RESIDENTS, OUT,
                     PARK_EDGE_M, PERSONS_PER_HOUSEHOLD, RAW, RESIDENTIAL, SENSITIVITY_M, SNAP_WARN_M,
                     STUDY_AREA, STUDY_BUFFER_M, THRESHOLD_M, WORK)

KINDS = list(THRESHOLD_M)


# ---------------------------------------------------------------- inputs
def boundaries():
    sz = gpd.read_file(RAW / "mp2019_subzone.geojson").to_crs(CRS)
    pa = gpd.read_file(RAW / "mp2019_planning_area.geojson").to_crs(CRS)
    return sz, pa


def walk_network():
    if not (WORK / "walk_edges.parquet").exists():
        tf = Transformer.from_crs(4326, CRS, always_xy=True)
        edges, nodes = network.parse_osm(RAW / "Singapore.osm.gz", tf.transform)
        network.save(edges, nodes, WORK)
    return network.load(WORK)


def origins(sz):
    f = WORK / "origins.parquet"
    if f.exists():
        return gpd.read_parquet(f)
    szp, pap = population.load_population(RAW / "singstat_C020123_ghs2025.json")
    s, missing = population.attach(sz, szp)
    lu = gpd.read_file(RAW / "mp2019_land_use.geojson", columns=["LU_DESC", "GPR"]).to_crs(CRS)
    res = lu[lu.LU_DESC.isin(RESIDENTIAL)]
    o = population.allocate(s, res, step=GRID_M)
    o.to_parquet(f)
    return o


def rail_future(pa_geom):
    """MP2025 rail station polygons with no LTA exit within 150 m, i.e. stations not yet open."""
    st = gpd.read_file(RAW / "mp2025_rail_station.geojson").to_crs(CRS)
    ex = gpd.read_file(RAW / "lta_mrt_exit.geojson").to_crs(CRS)
    near = gpd.sjoin_nearest(st, ex[["geometry"]], max_distance=150, how="left", distance_col="d")
    open_idx = near[near.d.notna()].index.unique()
    fut = st.drop(index=open_idx)
    fut["NAME"] = fut.NAME.str.strip()
    return fut


# ---------------------------------------------------------------- steps
def step_landuse(sz):
    szj = sz[sz.PLN_AREA_N == STUDY_AREA]
    tables, cuts = {}, {}
    for yr in ("2019", "2025"):
        lu = landuse.load(RAW / f"mp{yr}_land_use.geojson", CRS)
        lu = lu[lu.intersects(szj.union_all())]
        cut = landuse.overlay_subzones(lu, szj)
        cuts[yr] = cut
        t = landuse.subzone_table(cut)
        t.to_csv(OUT / f"landuse_subzone_mp{yr}.csv", float_format="%.4f")
        tables[yr] = t
    # parcel-level zoning changes MP2019 -> MP2025
    a = cuts["2019"][["LU_DESC", "GPR", "SUBZONE_N", "geometry"]].rename(columns={"LU_DESC": "lu2019", "GPR": "gpr2019"})
    b = cuts["2025"][["LU_DESC", "GPR", "geometry"]].rename(columns={"LU_DESC": "lu2025", "GPR": "gpr2025"})
    x = gpd.overlay(a, b, how="intersection", keep_geom_type=True)
    norm = lambda s: s.fillna("NA").astype(str).str.strip().replace({"": "NA"})
    x["gpr2019"], x["gpr2025"] = norm(x.gpr2019), norm(x.gpr2025)
    x["ha"] = x.area / 1e4
    ch = x[(x.lu2019 != x.lu2025) | (x.gpr2019 != x.gpr2025)]
    chg = (ch.groupby(["SUBZONE_N", "lu2019", "gpr2019", "lu2025", "gpr2025"]).ha.sum().reset_index()
           .query("ha >= 0.25").sort_values("ha", ascending=False))
    chg.to_csv(OUT / "zoning_changes_mp2019_mp2025.csv", index=False, float_format="%.2f")
    ch.to_parquet(WORK / "zoning_changes.parquet")
    return tables, cuts, chg


def step_access(net, o, amen, polys, fut):
    f = WORK / "distances.parquet"
    if f.exists():
        return pd.read_parquet(f)
    xy = np.c_[o.geometry.x, o.geometry.y]
    d = access.distances(net, xy, amen, polys, KINDS, PARK_EDGE_M)
    # rail after the stations now under construction open: existing exits plus edges of future station boxes
    ex = amen[amen.kind == "mrt_exit"]
    ex_n, ex_d = net.snap(np.c_[ex.geometry.x, ex.geometry.y])
    fn, fd = access.polygon_sources(net, fut, edge_m=30)
    nd = net.nearest_distance(np.r_[ex_n, fn], np.r_[ex_d, fd])
    on, od = net.snap(xy)
    d["mrt_future"] = od + nd[on]
    d["origin_snap_m"] = od
    d.to_parquet(f)
    return d


def run():
    for p in (WORK, OUT, FIG):
        p.mkdir(parents=True, exist_ok=True)
    sz, pa = boundaries()
    summary = {}
    tables, cuts, chg = step_landuse(sz)
    net = walk_network()
    summary["network"] = {"nodes_kept": int(net.n), "share_nodes_in_largest_component": round(net.share_kept, 4)}
    o = origins(sz)
    amen, polys = amenities.load_all(RAW, CRS)
    je = pa[pa.PLN_AREA_N == STUDY_AREA].geometry.iloc[0]
    fut = rail_future(je)
    d = step_access(net, o, amen, polys, fut)
    thr = dict(THRESHOLD_M)
    o = o.reset_index(drop=True)

    # coverage by subzone (study area) and planning area (island)
    cov_pa = access.coverage_table(o, d, thr, "planning_area").set_index("planning_area")
    cov_sz = access.coverage_table(o[o.planning_area == STUDY_AREA], d, thr, "subzone").set_index("subzone")
    thr_f = {"mrt_future": THRESHOLD_M["mrt_exit"]}
    cov_pa["within_mrt_future"] = access.coverage_table(o, d, thr_f, "planning_area").set_index(
        "planning_area").within_mrt_future
    cov_sz["within_mrt_future"] = access.coverage_table(o[o.planning_area == STUDY_AREA], d, thr_f,
                                                        "subzone").set_index("subzone").within_mrt_future
    # planned facility test: a community club in the Jurong Gateway Hub (URA MP2025 integrated transport hub point)
    ith = gpd.read_file(RAW / "mp2025_integrated_transport_hub.geojson").to_crs(CRS)
    hub = ith[ith.NAME.str.strip() == STUDY_AREA]
    cc = amen[amen.kind == "community_club"]
    mask0 = (o.planning_area == STUDY_AREA).to_numpy()
    xy0 = np.c_[o.geometry.x[mask0], o.geometry.y[mask0]]
    d_hub = net.distance_to_points(xy0, np.r_[np.c_[cc.geometry.x, cc.geometry.y], np.c_[hub.geometry.x, hub.geometry.y]])
    tmp = pd.DataFrame({"cc_with_hub": d_hub, "subzone": o.subzone[mask0].to_numpy(),
                        "residents": o.residents[mask0].to_numpy()})
    cov_sz["within_cc_with_hub"] = access.coverage_table(tmp, tmp[["cc_with_hub"]], {"cc_with_hub": 800},
                                                         "subzone").set_index("subzone").within_cc_with_hub
    cov_sz.to_csv(OUT / "access_subzone.csv", float_format="%.4f")

    # sensitivity of the 10-minute amenities
    sens = []
    mask = (o.planning_area == STUDY_AREA).to_numpy()
    for k in ("mrt_exit", "park", "hawker", "clinic", "community_club"):
        for t in SENSITIVITY_M:
            sens.append({"kind": k, "threshold_m": t,
                         "study_area": access.share_within(d[k][mask], o.residents[mask], t)})
    pd.DataFrame(sens).to_csv(OUT / "access_sensitivity.csv", index=False, float_format="%.4f")

    # ratios against the island-wide median
    szp, pap = population.load_population(RAW / "singstat_C020123_ghs2025.json")
    pap["PLN_AREA_N"] = pap.name.str.upper()
    pap = pap.set_index("PLN_AREA_N")
    rk = ["hawker", "clinic", "community_club", "primary_school"]
    cnt = ratios.counts(pa, amen, rk)
    pm2 = ratios.park_area(pa, polys["park"])
    rt = ratios.ratio_table(pap[["residents", "age_0_4", "age_5_14", "age_65_plus"]], cnt, pm2)
    rt = rt.join(cov_pa.drop(columns="residents"), how="left")
    cols = [f"per_{k}" for k in rk] + ["park_m2_per_resident"] + [f"within_{k}" for k in thr] + ["within_mrt_future"]
    cmp_ = ratios.compare(rt, STUDY_AREA, cols, MIN_PA_RESIDENTS)
    cmp_.to_csv(OUT / "ratios_vs_island_median.csv", index=False, float_format="%.4f")
    rt[rt.residents >= MIN_PA_RESIDENTS].to_csv(OUT / "planning_area_indicators.csv", float_format="%.4f")

    # gaps in the study area
    oj = o[mask].copy()
    dj = d[mask].reset_index(drop=True)
    oj = oj.reset_index(drop=True)
    flags = access.gap_flags(dj, thr)
    oj["n_gaps_10min"] = flags[["hawker", "clinic", "community_club", "park_zoned", "primary_school"]].sum(
        axis=1).to_numpy()  # five neighbourhood facilities (rail is reported on its own)
    gaps = pd.DataFrame({k: oj.residents[flags[k]].groupby(oj.subzone[flags[k]]).sum() for k in flags}).fillna(0)
    gaps = gaps.reindex(cov_sz.index).fillna(0)
    gaps.insert(0, "residents", cov_sz.residents)
    gaps.to_csv(OUT / "gaps_subzone_residents_beyond_threshold.csv", float_format="%.0f")
    snapped_far = float(oj.residents[dj.origin_snap_m > SNAP_WARN_M].sum())

    # how much longer than the crow flies are walks in the study area's existing estates?
    xy_j = np.c_[oj.geometry.x, oj.geometry.y]
    sl = access.straight_line(xy_j, amen, polys, ["mrt_exit", "hawker", "clinic", "community_club"])
    circ = access.circuity(dj[sl.columns].to_numpy(), sl.to_numpy())
    summary["circuity_study_area"] = circ
    t19 = tables["2019"]
    sz_res = oj.groupby("subzone").residents.sum().reindex(t19.index).fillna(0)
    m2_per_res = scenario.local_density(t19.gfa_residential_zoned_m2, sz_res)
    summary["zoned_res_gfa_m2_per_resident"] = m2_per_res
    sc = step_scenario(net, o, amen, polys, fut, d, cuts, circ, m2_per_res)

    summary.update({
        "study_area": STUDY_AREA,
        "residents_study_area": float(oj.residents.sum()),
        "residents_island": float(o.residents.sum()),
        "origin_points_study_area": int(len(oj)),
        "residents_snapped_beyond_150m": snapped_far,
        "coverage_study_area": {k: access.share_within(dj[k], oj.residents, t) for k, t in thr.items()},
        "coverage_mrt_future": access.share_within(dj["mrt_future"], oj.residents, THRESHOLD_M["mrt_exit"]),
        "residents_two_or_more_neighbourhood_gaps": float(oj.residents[oj.n_gaps_10min >= 2].sum()),
        "coverage_cc_with_jurong_gateway_hub": access.share_within(d_hub, oj.residents, 800),
        "future_stations_used": sorted(fut[fut.distance(je) < STUDY_BUFFER_M].NAME.unique().tolist()),
        "scenario": sc,
    })
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=float), encoding="utf-8")
    oj.assign(d_cc_with_hub=d_hub, **{f"d_{k}": dj[k].to_numpy() for k in list(thr) + ["mrt_future"]}).to_parquet(
        WORK / "origins_study.parquet")
    return summary


def step_scenario(net, o, amen, polys, fut, d, cuts, circ, m2_per_res):
    """Residential land that MP2025 zones in the study area but that held (almost) no residents in 2025.

    Plots: MP2025 residential parcels of at least 2 ha in the study area with fewer than 10 residents per ha after the
    dasymetric step. Central case: the zoned GPR on the whole site where the plan gives a number; where it says SDP,
    the median numeric residential GPR in the study area on 75 % of the site. Residents: central case at the local
    density of the study area's existing estates (zoned residential GFA per resident); upper case at plan capacity
    (100 m2 GFA per dwelling, 3.06 persons per household). Intensified case: the highest residential GPR the plan
    allows anywhere in the study area, at local density. New residents are placed on the 25 m lattice.
    Walking access is reported twice: on today's mapped paths, and 'if connected' = straight line x the circuity
    measured for existing residents of the study area. Facility load: existing residents go to their nearest facility
    on the network; new residents to the nearest by straight line (the connected assumption).
    """
    from scipy.spatial import cKDTree
    c25 = cuts["2025"]
    res = c25[c25.LU_DESC.isin(RESIDENTIAL)].copy().reset_index(drop=True)
    gnum = res.gpr.dropna()
    gnum = gnum[res.loc[gnum.index].area_m2 >= 1e4]
    gpr_central, gpr_high = float(np.median(gnum)), float(gnum.max())
    oj = o[o.planning_area == STUDY_AREA]
    hit = gpd.sjoin(oj[["residents", "geometry"]], res[["geometry"]], predicate="within")
    res["residents_2025"] = hit.groupby("index_right").residents.sum().reindex(res.index).fillna(0)
    res["ha"] = res.area_m2 / 1e4
    plots = res[(res.ha >= 2) & (res.residents_2025 / res.ha < 10)].sort_values("ha", ascending=False)
    plots = plots.reset_index(drop=True)
    xy_all = np.c_[o.geometry.x, o.geometry.y]
    w_all = o.residents.to_numpy()
    fac = {}
    for k in ("hawker", "clinic", "community_club"):
        sub = amen[amen.kind == k].reset_index(drop=True)
        dxy = np.c_[sub.geometry.x, sub.geometry.y]
        fac[k] = (sub, dxy, access.nearest_facility_load(net, xy_all, w_all, dxy)[0])
    ex = amen[amen.kind == "mrt_exit"]
    ex_n, ex_d = net.snap(np.c_[ex.geometry.x, ex.geometry.y])
    fn, fd = access.polygon_sources(net, fut, edge_m=30)
    rail_future_nodes = net.nearest_distance(np.r_[ex_n, fn], np.r_[ex_d, fd])
    gfa_rng = (GFA_PER_DWELLING_RANGE[0], GFA_PER_DWELLING_M2, GFA_PER_DWELLING_RANGE[1])
    plans, all_pxy, all_w, all_w_hi = [], [], [], []
    for i, p in plots.iterrows():
        tag = f"plot{i + 1}"
        area = p.area_m2
        zoned = not np.isnan(p.gpr)
        g0, share0 = (p.gpr, 1.0) if zoned else (gpr_central, 0.75)
        nres = scenario.residents_at_density(area, g0, share0, m2_per_res)
        du_cap, nres_cap = scenario.added_residents(area, g0, share0, GFA_PER_DWELLING_M2, PERSONS_PER_HOUSEHOLD)
        nres_hi = scenario.residents_at_density(area, gpr_high, share0, m2_per_res)
        sens = scenario.sensitivity(area, sorted({g0, gpr_central, gpr_high}),
                                    (1.0,) if zoned else (0.6, 0.75, 1.0), gfa_rng, PERSONS_PER_HOUSEHOLD)
        sens.to_csv(OUT / f"scenario_{tag}_sensitivity.csv", index=False, float_format="%.0f")
        pts = population.points_in(gpd.GeoDataFrame(geometry=[p.geometry], crs=CRS), GRID_M)
        pxy = np.c_[pts.geometry.x, pts.geometry.y]
        dist = access.distances(net, pxy, amen, polys, KINDS, PARK_EDGE_M)
        on, od = net.snap(pxy)
        dist["mrt_future"] = od + rail_future_nodes[on]
        sl = access.straight_line(pxy, amen, polys, KINDS)
        sl["mrt_future"] = np.minimum(sl.mrt_exit, access.straight_line(pxy, amen, {"f": fut}, ["f"]).f.to_numpy())
        conn = sl * circ
        thr = dict(THRESHOLD_M, mrt_future=THRESHOLD_M["mrt_exit"])
        plans.append({
            "plot": tag, "subzone": p.SUBZONE_N, "lu_mp2025": p.LU_DESC, "gpr_mp2025": p.GPR, "area_ha": p.ha,
            "residents_2025": p.residents_2025, "gpr_central": g0, "net_share_central": share0,
            "gfa_m2_central": area * g0 * share0, "residents_central": nres,
            "dwellings_plan_capacity": du_cap, "residents_plan_capacity": nres_cap,
            "gpr_intensified": gpr_high, "residents_intensified": nres_hi,
            "residents_range": [float(min(nres, sens.residents.min())), float(sens.residents.max())],
            "median_walk_today_m": {k: float(np.median(dist[k])) for k in dist},
            "share_within_today": {k: float((dist[k] <= thr[k]).mean()) for k in dist},
            "median_walk_if_connected_m": {k: float(np.median(conn[k])) for k in conn},
            "share_within_if_connected": {k: float((conn[k] <= thr[k]).mean()) for k in conn},
        })
        gpd.GeoDataFrame({"plot": [tag], "subzone": [p.SUBZONE_N], "gpr": [p.GPR]}, geometry=[p.geometry],
                         crs=CRS).to_parquet(WORK / f"scenario_{tag}.parquet")
        all_pxy.append(pxy)
        all_w.append(np.full(len(pxy), nres / len(pxy)))
        all_w_hi.append(np.full(len(pxy), nres_hi / len(pxy)))
    # combined build-out: load on the nearest existing facilities
    pxy, pw, pw_hi = np.vstack(all_pxy), np.concatenate(all_w), np.concatenate(all_w_hi)
    loads = {}
    for k, (sub, dxy, base) in fac.items():
        lab = cKDTree(dxy).query(pxy)[1]
        add = np.bincount(lab, weights=pw, minlength=len(sub))
        add_hi = np.bincount(lab, weights=pw_hi, minlength=len(sub))
        lc = scenario.load_change(base, add)
        lc.insert(0, "name", sub.name)
        lc["after_intensified"] = base + add_hi
        lc["change_pct_intensified"] = scenario.load_change(base, add_hi).change_pct.to_numpy()
        lc = lc[lc.after - lc.before > 1].sort_values("change_pct", ascending=False)
        lc.to_csv(OUT / f"scenario_load_{k}.csv", index=False, float_format="%.1f")
        loads[k] = lc.head(3).to_dict("records")
    pd.DataFrame([{k: v for k, v in r.items() if not isinstance(v, (dict, list))} for r in plans]).to_csv(
        OUT / "scenario_plots.csv", index=False, float_format="%.2f")
    return {"gpr_central_sdp": gpr_central, "gpr_intensified": gpr_high, "circuity": circ,
            "zoned_res_gfa_m2_per_resident": m2_per_res,
            "plots": plans, "combined_residents_central": float(pw.sum()),
            "combined_residents_intensified": float(pw_hi.sum()), "load_change_top": loads}
