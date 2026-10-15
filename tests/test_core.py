"""Unit tests on small hand-built inputs; no downloaded data needed. Expected values are worked out by hand in the
comments, and inputs are deliberately asymmetric so that swapped or dropped terms change the answer."""
import math
import sys
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Polygon, box

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lap import access, amenities, landuse, network, population, ratios, scenario  # noqa: E402


# ----------------------------------------------------------------------------- network
def line_net():
    """Path 0-1-2-3 with lengths 100, 50, 200 m along the x axis, plus an isolated pair 10-11 far away."""
    nodes = pd.DataFrame({"osm_id": [0, 1, 2, 3, 10, 11],
                          "x": [0.0, 100.0, 150.0, 350.0, 5000.0, 5010.0], "y": [0.0] * 6})
    edges = pd.DataFrame({"u": [0, 1, 2, 10], "v": [1, 2, 3, 11]})
    edges = network.edges_from_pairs(edges.to_numpy(), nodes)
    return network.WalkNetwork(edges, nodes)


def test_edge_lengths_are_euclidean():
    nodes = pd.DataFrame({"osm_id": [1, 2], "x": [0.0, 30.0], "y": [0.0, 40.0]})
    e = network.edges_from_pairs(np.array([[1, 2], [2, 2]]), nodes)
    assert len(e) == 1                      # self-loop dropped
    assert e.length_m.iloc[0] == pytest.approx(50.0)


def test_largest_component_only():
    net = line_net()
    assert net.n == 4
    assert net.share_kept == pytest.approx(4 / 6)


def test_nearest_distance_uses_offsets():
    net = line_net()
    # sources: node 0 joined 30 m away, node 3 joined 5 m away
    d = net.nearest_distance([0, 3], [30.0, 5.0])
    # node 1: via 0 = 30+100 = 130, via 3 = 5+250 = 255 -> 130 ; node 2: via 0 = 180, via 3 = 205 -> 180
    assert d == pytest.approx([30.0, 130.0, 180.0, 5.0], abs=1e-4)


def test_nearest_distance_matches_networkx():
    rng = np.random.default_rng(3)
    xy = rng.uniform(0, 1000, size=(60, 2))
    nodes = pd.DataFrame({"osm_id": np.arange(60), "x": xy[:, 0], "y": xy[:, 1]})
    pairs = [(i, j) for i in range(60) for j in range(i + 1, 60) if np.hypot(*(xy[i] - xy[j])) < 220]
    edges = network.edges_from_pairs(np.array(pairs), nodes)
    net = network.WalkNetwork(edges, nodes)
    g = nx.Graph()
    for r in edges.itertuples():
        g.add_edge(r.u, r.v, weight=r.length_m)
    big = max(nx.connected_components(g), key=len)
    srcs = sorted(big)[:3]
    offs = [12.0, 0.0, 47.0]
    g.add_node("S")
    for s, o in zip(srcs, offs):
        g.add_edge("S", s, weight=o)
    ref = nx.single_source_dijkstra_path_length(g, "S")
    pos = {o: i for i, o in enumerate(net.osm_id)}
    got = net.nearest_distance([pos[s] for s in srcs], offs)
    for o in big:
        assert got[pos[o]] == pytest.approx(ref[o], abs=1e-3)


def test_distance_to_points_adds_both_joins():
    net = line_net()
    # origin 20 m above node 1, destination 10 m above node 3: 20 + 250 + 10
    d = net.distance_to_points([[100.0, 20.0]], [[350.0, 10.0]])
    assert d[0] == pytest.approx(280.0, abs=1e-3)


def test_limit_marks_far_nodes_infinite():
    net = line_net()
    d = net.nearest_distance([0], [0.0], limit=120)
    assert np.isinf(d[2]) and np.isinf(d[3]) and d[1] == pytest.approx(100.0, abs=1e-4)


@pytest.mark.parametrize("tags,ok", [
    ({"highway": "footway"}, True),
    ({"highway": "residential"}, True),
    ({"highway": "motorway"}, False),
    ({"highway": "motorway_link"}, False),
    ({"highway": "cycleway"}, False),
    ({"highway": "cycleway", "foot": "designated"}, True),
    ({"highway": "service", "service": "private"}, False),
    ({"highway": "footway", "access": "private"}, False),
    ({"highway": "primary", "foot": "no"}, False),
    ({"highway": "pedestrian", "area": "yes"}, False),
    ({"highway": "construction"}, False),
    ({"building": "yes"}, False),
])
def test_walkable_filter(tags, ok):
    assert network.walkable(tags) is ok


def test_nearest_assignment_labels():
    net = line_net()
    # destinations at node 0 (offset 0) and node 3 (offset 0); node 1 (100 vs 250) -> 0, node 2 (150 vs 200) -> 0
    dist, lab = access.nearest_assignment(net, [0, 3], [0.0, 0.0])
    assert list(lab) == [0, 0, 0, 1]
    # with a 60 m join at node 0, node 2 is 210 via 0 vs 200 via 3 -> 1 ; node 1: 160 vs 250 -> 0
    dist, lab = access.nearest_assignment(net, [0, 3], [60.0, 0.0])
    assert list(lab) == [0, 0, 1, 1]
    assert dist[2] == pytest.approx(200.0, abs=1e-3)


def test_label_by_root_long_chain():
    # chain of 9 real nodes hanging from virtual node 10 (n=9 -> master 9, virtual 10)
    n = 9
    pred = np.array([10, 0, 1, 2, 3, 4, 5, 6, 7, -9999, 9], dtype=np.int64)
    assert list(access.label_by_root(pred, n)) == [0] * 9
    pred2 = np.array([10, 0, 1, 11, 3, 4, -9999, 6, 7, -9999, 9, 9], dtype=np.int64)
    assert list(access.label_by_root(pred2, n)) == [0, 0, 0, 1, 1, 1, -1, -1, -1]


def test_nearest_facility_load():
    net = line_net()
    # origins on nodes 1 and 2 with weights 7 and 3; facilities at nodes 0 and 3
    load, lab, d = access.nearest_facility_load(net, [[100, 0], [150, 0]], [7, 3], [[0, 0], [350, 0]])
    assert list(load) == [10.0, 0.0]
    load, lab, d = access.nearest_facility_load(net, [[100, 0], [150, 0]], [7, 3], [[-90, 0], [330, 0]])
    # joins 90 m and 20 m: node 1 -> 190 vs 270 (first) ; node 2 -> 240 vs 220 (second)
    assert list(load) == [7.0, 3.0]
    assert list(lab) == [0, 1] and d == pytest.approx([190.0, 220.0], abs=1e-3)
    load, lab, d = access.nearest_facility_load(net, [[100, 0], [150, 0]], [7, 3], [[-200, 0], [350, 0]])
    # first facility now 200 m off node 0: node 1 -> 300 vs 250 -> second; node 2 -> 350 vs 200 -> second
    assert list(load) == [0.0, 10.0]


def test_catchment_residents_counts_overlap():
    net = line_net()
    c = access.catchment_residents(net, [[100, 0], [150, 0]], [7, 3], [[0, 0], [350, 0]], limit=200)
    # facility at 0: node1 100 ok, node2 150 ok -> 10 ; facility at 3: node2 200 ok, node1 250 no -> 3
    assert list(c) == [10.0, 3.0]


# ----------------------------------------------------------------------------- coverage
def test_share_within_inclusive_and_weighted():
    assert access.share_within([100, 400, 401], [1, 2, 7], 400) == pytest.approx(0.3)
    assert access.share_within([500], [1], 400) == 0.0


def test_coverage_table_groups():
    o = pd.DataFrame({"sz": ["A", "A", "B"], "residents": [3.0, 1.0, 5.0]})
    d = pd.DataFrame({"hawker": [100.0, 900.0, 900.0]})
    t = access.coverage_table(o, d, {"hawker": 800}, "sz").set_index("sz")
    assert t.loc["A", "within_hawker"] == pytest.approx(0.75)
    assert t.loc["B", "within_hawker"] == 0.0
    assert t.loc["A", "residents"] == 4.0


def test_gap_flags_strict():
    d = pd.DataFrame({"park": [800.0, 800.5], "bus_stop": [10.0, 401.0]})
    f = access.gap_flags(d, {"park": 800, "bus_stop": 400})
    assert f.park.tolist() == [False, True]
    assert f.bus_stop.tolist() == [False, True]


def test_park_entry_nodes_edge_buffer():
    net = line_net()
    park = gpd.GeoDataFrame(geometry=[box(140, -30, 200, 30), box(330, 15, 400, 60)], crs=3414)
    # node 2 (x=150) inside the first box; node 3 (350,0) is 15 m below the second box: in with 20 m, out with 10 m
    assert list(access.polygon_entry_nodes(net, park, 20)) == [2, 3]
    assert list(access.polygon_entry_nodes(net, park, 10)) == [2]


def test_polygon_sources_reach_unconnected_polygon():
    net = line_net()
    # a box 40 m above node 2 with no node inside: reached via its edge, 40 m join at x=150
    poly = gpd.GeoDataFrame(geometry=[box(140, 40, 160, 60)], crs=3414)
    nodes, offs = access.polygon_sources(net, poly, edge_m=20, step_m=5)
    d = net.nearest_distance(nodes, offs)
    assert d[2] == pytest.approx(40.0, abs=1e-3)       # straight down from (150, 40)
    assert d[0] == pytest.approx(40.0 + 150.0, abs=1e-3)
    # distances() on a polygon kind adds the origin join too
    out = access.distances(net, [[0.0, -30.0]], gpd.GeoDataFrame({"kind": []}, geometry=[], crs=3414),
                           {"park": poly}, ["park"])
    assert out.park.iloc[0] == pytest.approx(30.0 + 150.0 + 40.0, abs=2.0)  # 25 m edge sampling


def test_straight_line_points_and_polygons():
    am = gpd.GeoDataFrame({"kind": ["hawker", "hawker", "clinic"]},
                          geometry=gpd.points_from_xy([30, 500, 0], [40, 0, 9]), crs=3414)
    poly = gpd.GeoDataFrame(geometry=[box(100, -10, 120, 10)], crs=3414)
    sl = access.straight_line([[0, 0], [490, 0]], am, {"park": poly}, ["hawker", "clinic", "park"])
    assert sl.hawker.tolist() == pytest.approx([50.0, 10.0])
    assert sl.clinic.tolist() == pytest.approx([9.0, math.hypot(490, 9)])
    assert sl.park.tolist() == pytest.approx([100.0, 370.0])


def test_circuity_median_and_floor():
    # pairs below 200 m straight line are ignored; ratios 1.2, 1.5, 3.0 -> median 1.5
    assert access.circuity([120, 240, 450, 900, 10], [100, 200, 300, 300, 5]) == pytest.approx(1.5)
    assert access.circuity([[300, 600]], [[250, 200]]) == pytest.approx(2.1)


# ----------------------------------------------------------------------------- land use
def test_gpr_parse():
    assert landuse.gpr_value("4.2") == 4.2
    for code in ("LND", "EVA", "SDP", "", None, "0"):
        assert math.isnan(landuse.gpr_value(code))


def test_groups():
    assert landuse.group_of("BUSINESS PARK - WHITE") == "Business"
    assert landuse.group_of("residential with commercial at 1st storey") == "Commercial & mixed"
    assert landuse.group_of("RESERVE SITE") == "Reserve site"
    assert landuse.group_of("SOMETHING NEW") == "Other"


def test_mix_index_values():
    assert landuse.mix_index({"Residential": 10.0}) == 0.0
    assert landuse.mix_index({"Residential": 5.0, "Business": 5.0}) == pytest.approx(math.log(2) / math.log(5))
    even = {g: 1.0 for g in landuse.ACTIVITY}
    assert landuse.mix_index(even) == pytest.approx(1.0)
    # roads do not count towards the mix
    assert landuse.mix_index({"Residential": 3.0, "Transport": 100.0}) == 0.0
    p = np.array([3, 1]) / 4
    assert landuse.mix_index({"Residential": 3.0, "Parks & recreation": 1.0}) == pytest.approx(
        -(p * np.log(p)).sum() / math.log(5))


def subzone_fixture():
    sz = gpd.GeoDataFrame({"SUBZONE_N": ["A", "B"], "PLN_AREA_N": ["P", "P"]},
                          geometry=[box(0, 0, 100, 100), box(100, 0, 300, 100)], crs=3414)
    lu = gpd.GeoDataFrame({"LU_DESC": ["RESIDENTIAL", "COMMERCIAL", "ROAD", "RESIDENTIAL"],
                           "GPR": ["2.8", "4.2", None, "LND"]},
                          geometry=[box(0, 0, 50, 100), box(50, 0, 150, 100), box(150, 0, 200, 100),
                                    box(200, 0, 300, 100)], crs=3414)
    lu["group"] = lu.LU_DESC.map(landuse.group_of)
    lu["gpr"] = lu.GPR.map(landuse.gpr_value)
    lu["gpr_code"] = np.where(lu.gpr.notna(), "numeric", lu.GPR.fillna("blank"))
    return sz, lu


def test_subzone_gfa_and_split_parcel():
    sz, lu = subzone_fixture()
    t = landuse.subzone_table(landuse.overlay_subzones(lu, sz))
    # A: res 5000 m2 x 2.8 = 14000 + commercial half 5000 x 4.2 = 21000 -> 35000
    assert t.loc["A", "gfa_potential_m2"] == pytest.approx(35000)
    # B: commercial half 21000; landed parcel has no numeric GPR -> 21000, with 1.0 ha of LND land
    assert t.loc["B", "gfa_potential_m2"] == pytest.approx(21000)
    assert t.loc["B", "ha_gpr_LND"] == pytest.approx(1.0)
    assert t.loc["A", "gfa_residential_zoned_m2"] == pytest.approx(14000)
    assert t.loc["A", "share_Residential"] == pytest.approx(0.5)
    assert t.loc["B", "share_Transport"] == pytest.approx(0.25)
    assert t.loc["B", "land_ha"] == pytest.approx(2.0)


# ----------------------------------------------------------------------------- population
def singstat_fixture():
    def row(no, text, total, ages):
        cols = [{"key": "Total", "value": str(total)}] + [{"key": k, "value": str(v)} for k, v in ages.items()]
        return {"rowNo": no, "rowText": text, "columns": [{"key": "Total", "columns": cols}]}
    ages = lambda a, b, c, d: {"0 - 4": a, "5 - 9": b, "10-14": c, "65 - 69": d, "70 - 74": 0, "75 - 79": 0,
                               "80 - 84": 0, "85 - 89": 0, "90 & Over": 0}
    return {"Data": {"row": [
        row("1", "Total", 130, ages(10, 20, 30, 40)),
        row("2", "Pee - Total", 130, ages(10, 20, 30, 40)),
        row("2.1", "A", 100, ages(10, 15, 25, 40)),
        row("2.2", "B", "-", ages("-", "-", "-", "-")),
        row("2.3", "C's Hill", 30, ages(0, 5, 5, 0)),
    ]}}


def test_parse_singstat():
    sz, pa = population.parse_singstat(singstat_fixture())
    assert sz.name.tolist() == ["A", "B", "C's Hill"]
    assert sz.residents.tolist() == [100, 0, 30]
    assert sz.age_5_14.tolist() == [40, 0, 10]
    assert sz.age_65_plus.tolist() == [40, 0, 0]
    assert pa.name.tolist() == ["Pee"] and pa.residents.tolist() == [130]


def test_attach_matches_normalised_names():
    sz, _ = population.parse_singstat(singstat_fixture())
    poly = gpd.GeoDataFrame({"SUBZONE_N": ["A", "C'S HILL", "D"], "PLN_AREA_N": ["P"] * 3},
                            geometry=[box(0, 0, 1, 1)] * 3, crs=3414)
    s, missing = population.attach(poly, sz)
    assert s.residents.tolist() == [100, 30, 0] and missing == 1


def test_parcel_weights():
    lu = gpd.GeoDataFrame({"LU_DESC": ["RESIDENTIAL"] * 4, "GPR": ["3.0", "LND", "EVA", "1.0"]},
                          geometry=[box(0, 0, 10, 10)] * 4, crs=3414)
    w = population.parcel_weights(lu).tolist()
    # EVA takes the class median of the numeric values (3.0, 1.0 from LND, 1.0) = 1.0
    assert w == [300.0, 100.0, 100.0, 100.0]
    lu2 = lu.assign(GPR=["3.0", "LND", "EVA", "5.0"])
    assert population.parcel_weights(lu2).tolist()[2] == 300.0  # median of 3, 1, 5


def test_allocate_preserves_totals_and_weights():
    sz = gpd.GeoDataFrame({"SUBZONE_N": ["A", "B", "C"], "PLN_AREA_N": ["P", "P", "Q"],
                           "residents": [900.0, 50.0, 0.0], "age_5_14": [90.0, 5.0, 0.0]},
                          geometry=[box(0, 0, 200, 100), box(200, 0, 300, 100), box(300, 0, 400, 100)], crs=3414)
    # two parcels in A: 100x100 at GPR 2.0 and 100x100 at GPR 1.0 -> 600 / 300 residents ; B has no parcel
    lu = gpd.GeoDataFrame({"LU_DESC": ["RESIDENTIAL", "RESIDENTIAL"], "GPR": ["2.0", "1.0"]},
                          geometry=[box(0, 0, 100, 100), box(100, 0, 200, 100)], crs=3414)
    o = population.allocate(sz, lu, step=25)
    tot = o.groupby("subzone").residents.sum()
    assert tot["A"] == pytest.approx(900.0) and tot["B"] == pytest.approx(50.0) and "C" not in tot
    left = o[(o.subzone == "A") & (o.geometry.x < 100)].residents.sum()
    assert left == pytest.approx(600.0)
    assert len(o[o.subzone == "A"]) == 32           # 16 lattice points per 100 m square at 25 m
    assert set(o[o.subzone == "B"].method) == {"subzone grid"}
    assert o.groupby("subzone").age_5_14.sum()["A"] == pytest.approx(90.0)
    assert o.planning_area[o.subzone == "B"].iloc[0] == "P"


def test_allocate_split_parcel_keeps_density():
    sz = gpd.GeoDataFrame({"SUBZONE_N": ["A", "B"], "PLN_AREA_N": ["P", "P"], "residents": [100.0, 100.0]},
                          geometry=[box(0, 0, 100, 100), box(100, 0, 200, 100)], crs=3414)
    # one parcel straddles both subzones (75 % in A) and A also has a small 25x100 parcel at GPR 3
    lu = gpd.GeoDataFrame({"LU_DESC": ["RESIDENTIAL", "RESIDENTIAL"], "GPR": ["1.0", "3.0"]},
                          geometry=[box(25, 0, 125, 100), box(0, 0, 25, 100)], crs=3414)
    o = population.allocate(sz, lu, step=25)
    a = o[o.subzone == "A"]
    # A weights: straddler 75x100x1 = 7500, small 25x100x3 = 7500 -> 50 / 50
    assert a[a.geometry.x < 25].residents.sum() == pytest.approx(50.0)


def test_points_in_small_polygon_gets_one_point():
    polys = gpd.GeoDataFrame(geometry=[box(1, 1, 6, 6), box(0, 0, 50, 50)], crs=3414)
    p = population.points_in(polys, 25)
    assert (p.poly == 0).sum() == 1 and (p.poly == 1).sum() == 4


# ----------------------------------------------------------------------------- ratios
def test_ratio_and_compare():
    pa = pd.DataFrame({"residents": [40000, 20000, 30000, 5000], "age_0_4": 0, "age_5_14": [4000, 3000, 6000, 1],
                       "age_65_plus": 0}, index=["W", "X", "Y", "Z"])
    cnt = pd.DataFrame({"hawker": [2, 0, 3, 1], "primary_school": [2, 1, 2, 0]}, index=pa.index)
    park = pd.Series([80000.0, 10000.0, 90000.0, 0.0], index=pa.index)
    t = ratios.ratio_table(pa, cnt, park)
    assert t.loc["W", "per_hawker"] == 20000 and np.isinf(t.loc["X", "per_hawker"])
    assert t.loc["Y", "per_primary_school"] == 3000          # children 5-14, not all residents
    assert t.loc["Y", "park_m2_per_resident"] == pytest.approx(3.0)
    c = ratios.compare(t, "W", ["per_hawker", "park_m2_per_resident"], 10000).set_index("metric")
    # pool W, X, Y (Z below 10k): per_hawker 20000, inf, 10000 -> median 20000 ; W rank 2 of 3 (lower is better)
    assert c.loc["per_hawker", "island_median"] == 20000 and c.loc["per_hawker", "rank"] == 2
    assert c.loc["per_hawker", "of"] == 3
    # park m2 per resident 2.0, 0.5, 3.0 -> median 2.0 ; W rank 2 (higher is better)
    assert c.loc["park_m2_per_resident", "island_median"] == pytest.approx(2.0)
    assert c.loc["park_m2_per_resident", "rank"] == 2
    # W sits in the middle either way; Y is best on both, so a reversed ranking would put it last
    cy = ratios.compare(t, "Y", ["per_hawker", "park_m2_per_resident"], 10000).set_index("metric")
    assert cy.loc["per_hawker", "rank"] == 1 and cy.loc["park_m2_per_resident", "rank"] == 1


def test_counts_within_polygon():
    pa = gpd.GeoDataFrame({"PLN_AREA_N": ["P", "Q"]}, geometry=[box(0, 0, 10, 10), box(10, 0, 20, 10)], crs=3414)
    am = gpd.GeoDataFrame({"kind": ["hawker", "hawker", "clinic", "hawker"]},
                          geometry=gpd.points_from_xy([1, 2, 15, 50], [1, 1, 5, 5]), crs=3414)
    c = ratios.counts(pa, am, ["hawker", "clinic"])
    assert c.loc["P", "hawker"] == 2 and c.loc["Q", "hawker"] == 0 and c.loc["Q", "clinic"] == 1


# ----------------------------------------------------------------------------- amenities / scenario
def test_kml_table():
    d = "<tr><th>NAME</th> <td>Yuhua CC</td></tr><tr><th>DESCRIPTION</th> <td>CC</td></tr><th>X</th><td></td>"
    assert amenities.kml_table(d) == {"NAME": "Yuhua CC", "DESCRIPTION": "CC", "X": ""}


def test_added_residents():
    du, res = scenario.added_residents(20000, 4.2, 0.75, 100, 3.06)
    assert du == pytest.approx(630.0) and res == pytest.approx(1927.8)
    s = scenario.sensitivity(10000, (3.0, 5.6), (0.5,), (80, 120), 3.0)
    assert len(s) == 4
    assert s.residents.max() == pytest.approx(10000 * 5.6 * 0.5 / 80 * 3.0)
    assert s.residents.min() == pytest.approx(10000 * 3.0 * 0.5 / 120 * 3.0)


def test_local_density_and_residents():
    # areas with 2000 and 500 residents: the second is left out -> 120000 / 2000
    assert scenario.local_density([120000, 999999], [2000, 500]) == pytest.approx(60.0)
    assert scenario.local_density([100, 300], [1000, 3000]) == pytest.approx(0.1)
    assert scenario.residents_at_density(10000, 3.5, 0.8, 70) == pytest.approx(400.0)


def test_load_change():
    t = scenario.load_change([200, 0, 50], [50, 10, 0])
    assert t.after.tolist() == [250, 10, 50]
    assert t.change_pct[0] == pytest.approx(25.0) and np.isnan(t.change_pct[1]) and t.change_pct[2] == 0.0
