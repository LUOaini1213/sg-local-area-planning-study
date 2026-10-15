"""Walking accessibility of resident origin points to amenities, coverage shares, gaps and catchment loads."""
import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.sparse.csgraph import dijkstra
from scipy.sparse import coo_matrix

from .network import EPS


def polygon_entry_nodes(net, polys, edge_m=20):
    """Network nodes inside a polygon (park, station box) or within edge_m of its edge."""
    nodes = gpd.GeoDataFrame(geometry=gpd.points_from_xy(net.xy[:, 0], net.xy[:, 1]), crs=polys.crs)
    hit = gpd.sjoin(nodes, gpd.GeoDataFrame(geometry=polys.buffer(edge_m), crs=polys.crs), predicate="within")
    return np.unique(hit.index.to_numpy())


def polygon_sources(net, polys, edge_m=20, step_m=25):
    """Entry points of polygons as (nodes, join offsets). Nodes inside or within edge_m of a polygon join at zero
    cost; in addition every step_m along each polygon edge is joined to its nearest network node at the straight-line
    distance. The second part matters where a polygon has no path inside or next to it yet (a station box on land
    still being developed): it is then reached from the nearest existing path instead of not at all."""
    inner = polygon_entry_nodes(net, polys, edge_m)
    pts = []
    for geom in polys.geometry:
        for ring in getattr(geom, "geoms", [geom]):
            b = ring.exterior
            k = max(int(b.length // step_m), 1)
            pts.extend(b.interpolate(t, normalized=True).coords[0] for t in np.linspace(0, 1, k, endpoint=False))
    bn, bd = net.snap(np.array(pts))
    return np.r_[inner, bn], np.r_[np.zeros(len(inner)), bd]


def distances(net, origins_xy, amen, polygons, kinds, park_edge_m=20):
    """DataFrame (one row per origin, one column per kind) of walking metres to the nearest amenity of that kind.
    Point kinds come from `amen`; polygon kinds (parks) from the dict `polygons` and are entered at their edge."""
    out = {}
    for k in kinds:
        if k in polygons:
            nodes, offs = polygon_sources(net, polygons[k], park_edge_m)
            node_dist = net.nearest_distance(nodes, offs)
            on, od = net.snap(origins_xy)
            out[k] = od + node_dist[on]
        else:
            sub = amen[amen.kind == k]
            out[k] = net.distance_to_points(origins_xy, np.c_[sub.geometry.x, sub.geometry.y])
    return pd.DataFrame(out)


def straight_line(origins_xy, amen, polygons, kinds):
    """Straight-line metres to the nearest amenity of each kind (polygon kinds: to the nearest polygon edge)."""
    from scipy.spatial import cKDTree
    xy = np.asarray(origins_xy, dtype=float).reshape(-1, 2)
    out = {}
    for k in kinds:
        if k in polygons:
            pts = gpd.GeoSeries(gpd.points_from_xy(xy[:, 0], xy[:, 1]), crs=polygons[k].crs)
            j = gpd.sjoin_nearest(gpd.GeoDataFrame(geometry=pts), polygons[k][["geometry"]], distance_col="d")
            out[k] = j.groupby(level=0).d.min().reindex(range(len(xy))).to_numpy()
        else:
            sub = amen[amen.kind == k]
            out[k] = cKDTree(np.c_[sub.geometry.x, sub.geometry.y]).query(xy)[0]
    return pd.DataFrame(out)


def circuity(network_m, straight_m, min_straight=200.0):
    """Median ratio of walking to straight-line distance, over origins at least min_straight away."""
    n = np.asarray(network_m, dtype=float).ravel()
    s = np.asarray(straight_m, dtype=float).ravel()
    ok = np.isfinite(n) & (s >= min_straight)
    return float(np.median(n[ok] / s[ok]))


def share_within(dist, weight, threshold):
    """Weighted share of origins whose distance is at most threshold (inclusive)."""
    dist = np.asarray(dist, dtype=float)
    weight = np.asarray(weight, dtype=float)
    tot = weight.sum()
    return float(weight[dist <= threshold].sum() / tot) if tot > 0 else float("nan")


def coverage_table(origins, dist, thresholds, by):
    """Share of residents within each kind's threshold, grouped by column `by` of origins."""
    rows = []
    for g, idx in origins.groupby(by).groups.items():
        w = origins.loc[idx, "residents"].to_numpy()
        rec = {by: g, "residents": w.sum()}
        for k, t in thresholds.items():
            if k in dist:
                rec[f"within_{k}"] = share_within(dist.loc[idx, k].to_numpy(), w, t)
        rows.append(rec)
    return pd.DataFrame(rows)


def gap_flags(dist, thresholds):
    """Boolean frame: True where the origin is beyond the threshold for that kind."""
    return pd.DataFrame({k: dist[k].to_numpy() > t for k, t in thresholds.items() if k in dist}, index=dist.index)


def nearest_assignment(net, dest_nodes, dest_offsets):
    """For every node: network distance to the nearest destination and that destination's position in dest_nodes.
    Uses a virtual source and pointer jumping along the shortest-path tree. Unreached nodes get -1."""
    n = net.n
    dest_nodes = np.asarray(dest_nodes, dtype=np.int64)
    off = np.maximum(np.asarray(dest_offsets, dtype=float), EPS)
    g = net.graph.tocoo()
    m = len(dest_nodes)
    # one virtual node per destination (n+1 .. n+m) hangs off the master source n, so ties at one node stay separable
    rows = np.r_[g.row, np.full(m, n), np.arange(n + 1, n + 1 + m)]
    cols = np.r_[g.col, np.arange(n + 1, n + 1 + m), dest_nodes]
    data = np.r_[g.data, off, np.full(m, EPS)]
    big = coo_matrix((data, (rows, cols)), shape=(n + 1 + m, n + 1 + m)).tocsr()
    dist, pred = dijkstra(big, directed=True, indices=n, return_predecessors=True)
    return dist[:n], label_by_root(pred, n)


def label_by_root(pred, n):
    """pred: predecessor array of a shortest-path tree grown from master source n, where nodes n+1.. are virtual
    destination nodes. Returns, for each real node < n, the index (0-based) of the virtual node it hangs from."""
    par = pred[:n].astype(np.int64)
    lab = np.full(n, -1, dtype=np.int64)
    virt = par >= n + 1
    lab[virt] = par[virt] - (n + 1)
    up = np.where((par >= 0) & (par < n), par, -1)  # real parent, or -1
    todo = (lab < 0) & (up >= 0)
    while todo.any():
        t = np.flatnonzero(todo)
        anc = up[t]
        got = lab[anc] >= 0
        lab[t[got]] = lab[anc[got]]
        rest = t[~got]
        up[rest] = up[up[rest]]  # pointer jumping halves the remaining path each round
        todo = (lab < 0) & (up >= 0)
    return lab


def nearest_facility_load(net, origins_xy, weights, dest_xy):
    """Residents assigned to their nearest facility by walking distance. Returns (load per facility, origin labels,
    origin distances)."""
    dn, dd = net.snap(dest_xy)
    node_dist, lab = nearest_assignment(net, dn, dd)
    on, od = net.snap(origins_xy)
    olab = lab[on]
    load = np.bincount(olab[olab >= 0], weights=np.asarray(weights)[olab >= 0], minlength=len(dn))
    return load, olab, od + node_dist[on]


def catchment_residents(net, origins_xy, weights, dest_xy, limit):
    """Gross catchment: residents within `limit` walking metres of each facility (an origin can count twice)."""
    dn, dd = net.snap(dest_xy)
    on, od = net.snap(origins_xy)
    w = np.asarray(weights, dtype=float)
    out = np.zeros(len(dn))
    for i, (node, off) in enumerate(zip(dn, dd)):
        d = dijkstra(net.graph, directed=False, indices=int(node), limit=limit)
        tot = od + d[on] + off
        out[i] = w[tot <= limit].sum()
    return out
