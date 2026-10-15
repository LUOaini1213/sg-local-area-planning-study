"""Pedestrian network from the BBBike OpenStreetMap extract, and shortest walking distances on it.

Way filter. It starts from the osmnx 'walk' definition (any highway except motorways, cycleways, bus guideways, platforms, raceways and roads that are abandoned, planned, proposed or under
construction; drop foot=no, access=private, service=private, area=yes). One change: Singapore's park connectors are
often mapped as highway=cycleway with foot=yes or foot=designated, and osmnx drops them; they are kept here.

Distances. Edges are straight segments between OSM nodes measured in SVY21 metres. Only the largest connected
component is kept. An origin or destination point joins the network at its nearest component node, and the
straight-line join distance is added to the network distance. Many-to-nearest distances use one Dijkstra run from a
virtual source linked to every destination node by its join distance, so a far-snapped destination is not treated
as if it sat on the network.
"""
import gzip
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components, dijkstra
from scipy.spatial import cKDTree

EXCLUDED_HIGHWAY = {"abandoned", "bus_guideway", "construction", "motorway", "motorway_link", "no", "planned",
                    "platform", "proposed", "raceway", "razed"}
EPS = 1e-6  # scipy treats an explicit 0 weight as a missing edge


def walkable(tags):
    h = tags.get("highway")
    if not h or h in EXCLUDED_HIGHWAY:
        return False
    if tags.get("area") == "yes" or tags.get("access") == "private" or tags.get("service") == "private":
        return False
    if tags.get("foot") == "no":
        return False
    if h == "cycleway":
        return tags.get("foot") in ("yes", "designated", "permissive")
    return True


def parse_osm(path, transform):
    """Two streaming passes over an .osm.gz file. Returns (edges DataFrame u, v, length_m; nodes DataFrame)."""
    from lxml import etree

    def iterate(tag):
        with gzip.open(path, "rb") as f:
            for _, el in etree.iterparse(f, events=("end",), tag=tag):
                yield el
                el.clear()
                while el.getprevious() is not None:
                    del el.getparent()[0]

    pairs = []
    for el in iterate("way"):
        tags = {t.get("k"): t.get("v") for t in el.iterfind("tag")}
        if walkable(tags):
            refs = [int(n.get("ref")) for n in el.iterfind("nd")]
            pairs.extend(zip(refs[:-1], refs[1:]))
    e = np.array(pairs, dtype=np.int64)
    needed = set(np.unique(e).tolist())
    ids, lat, lon = [], [], []
    for el in iterate("node"):
        i = int(el.get("id"))
        if i in needed:
            ids.append(i)
            lat.append(float(el.get("lat")))
            lon.append(float(el.get("lon")))
    x, y = transform(np.array(lon), np.array(lat))
    nodes = pd.DataFrame({"osm_id": ids, "x": x, "y": y})
    return edges_from_pairs(e, nodes), nodes


def edges_from_pairs(pairs, nodes):
    pos = nodes.set_index("osm_id")[["x", "y"]]
    ed = pd.DataFrame(pairs, columns=["u", "v"])
    ed = ed[ed.u.isin(pos.index) & ed.v.isin(pos.index) & (ed.u != ed.v)]
    pu, pv = pos.loc[ed.u].to_numpy(), pos.loc[ed.v].to_numpy()
    ed["length_m"] = np.hypot(pu[:, 0] - pv[:, 0], pu[:, 1] - pv[:, 1])
    return ed.reset_index(drop=True)


class WalkNetwork:
    """Undirected walking graph restricted to its largest connected component."""

    def __init__(self, edges, nodes):
        idx = {o: i for i, o in enumerate(nodes.osm_id.to_numpy())}
        u = edges.u.map(idx).to_numpy()
        v = edges.v.map(idx).to_numpy()
        w = np.maximum(edges.length_m.to_numpy(dtype=float), EPS)
        n = len(nodes)
        g = coo_matrix((np.r_[w, w], (np.r_[u, v], np.r_[v, u])), shape=(n, n)).tocsr()
        g.sum_duplicates()
        _, lab = connected_components(g, directed=False)
        big = np.bincount(lab).argmax()
        keep = np.flatnonzero(lab == big)
        self.share_kept = len(keep) / n
        self.graph = g[keep][:, keep].tocsr()
        self.xy = nodes[["x", "y"]].to_numpy()[keep]
        self.osm_id = nodes.osm_id.to_numpy()[keep]
        self.tree = cKDTree(self.xy)

    @property
    def n(self):
        return self.graph.shape[0]

    def snap(self, xy):
        d, i = self.tree.query(np.asarray(xy, dtype=float).reshape(-1, 2))
        return i, d

    def nearest_distance(self, source_nodes, source_offsets, limit=np.inf):
        """Network metres from every node to the nearest source; offsets are the sources' join distances."""
        n = self.n
        src = np.asarray(source_nodes, dtype=np.int64)
        off = np.maximum(np.asarray(source_offsets, dtype=float), EPS)
        # keep only the smallest offset per node
        order = np.lexsort((off, src))
        src, off = src[order], off[order]
        first = np.r_[True, src[1:] != src[:-1]]
        src, off = src[first], off[first]
        rows = np.full(len(src), n)
        g = self.graph.tocoo()
        big = coo_matrix((np.r_[g.data, off], (np.r_[g.row, rows], np.r_[g.col, src])), shape=(n + 1, n + 1)).tocsr()
        dist = dijkstra(big, directed=True, indices=n, limit=limit)
        return dist[:n]

    def distance_to_points(self, origin_xy, dest_xy, limit=np.inf):
        """Origin -> nearest destination walking metres (join + network + join). inf when beyond limit."""
        dn, dd = self.snap(dest_xy)
        node_dist = self.nearest_distance(dn, dd, limit=limit)
        on, od = self.snap(origin_xy)
        return od + node_dist[on]

    def distance_to_node_sets(self, origin_xy, node_ids, limit=np.inf):
        """Same as distance_to_points, but the destination is a set of network nodes reached at zero cost."""
        node_dist = self.nearest_distance(node_ids, np.zeros(len(node_ids)), limit=limit)
        on, od = self.snap(origin_xy)
        return od + node_dist[on]


def save(edges, nodes, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    edges.to_parquet(folder / "walk_edges.parquet", index=False)
    nodes.to_parquet(folder / "walk_nodes.parquet", index=False)


def load(folder):
    folder = Path(folder)
    return WalkNetwork(pd.read_parquet(folder / "walk_edges.parquet"), pd.read_parquet(folder / "walk_nodes.parquet"))
