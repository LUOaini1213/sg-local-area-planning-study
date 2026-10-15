"""Load the amenity layers into one schema: GeoDataFrame(kind, name, geometry) in SVY21.

kind values: bus_stop, mrt_exit, hawker, clinic, community_club, primary_school (points) and park (polygons).
Choices, all stated in the README:
  * hawker: NEA centres with status Existing, Existing (new), Existing (replacement) or Interim Centre; centres
    under construction are listed separately for the scenario, not counted as serving residents today.
  * clinic: MOH CHAS GP clinics (the layer was last refreshed in June 2024); clinics inside worker dormitories are
    left out because they do not serve residents.
  * community_club: PA community clubs (layer refreshed 2026); PAssion WaVe outlets and clubs marked (U/C) or
    Pending are left out.
  * primary_school: MOE schools whose main level is PRIMARY or MIXED LEVEL (P1-S4), geocoded by postal code.
  * park: NParks parks polygons, nature reserves (N_RESERVE = 1) left out.
  * park_zoned: land zoned PARK in Master Plan 2025, a wider definition that includes estate parks.
"""
import re

import geopandas as gpd
import pandas as pd

OPERATING_HAWKER = {"Existing", "Existing (new)", "Existing (replacement)", "Interim Centre"}


def kml_table(desc):
    """data.gov.sg KML-derived layers hide attributes in an HTML table in 'Description'."""
    return dict(re.findall(r"<th>([^<]+)</th>\s*<td>([^<]*)</td>", str(desc)))


def _pts(gdf, kind, names, crs):
    g = gdf.to_crs(crs)
    return gpd.GeoDataFrame({"kind": kind, "name": list(names)}, geometry=g.geometry.values, crs=crs)


def bus_stops(path, crs=3414):
    g = gpd.read_file(path)
    return _pts(g, "bus_stop", g.BUS_STOP_NUM.astype(str), crs)


def mrt_exits(path, crs=3414):
    g = gpd.read_file(path)
    return _pts(g, "mrt_exit", (g.STATION_NA.str.title() + " " + g.EXIT_CODE.astype(str)), crs)


def hawkers(path, crs=3414, include_planned=False):
    g = gpd.read_file(path)
    ok = g.STATUS.isin(OPERATING_HAWKER)
    g = g[~ok] if include_planned else g[ok]
    out = _pts(g, "hawker", g.NAME, crs)
    out["status"] = g.STATUS.values
    return out


def clinics(path, crs=3414):
    g = gpd.read_file(path)
    t = pd.DataFrame([kml_table(d) for d in g.Description])
    keep = (~t.HCI_NAME.str.contains("dorm", case=False)).to_numpy()  # clinics inside worker dormitories
    return _pts(g[keep], "clinic", t.HCI_NAME[keep].str.strip(), crs)


def community_clubs(path, crs=3414):
    g = gpd.read_file(path)
    t = pd.DataFrame([kml_table(d) for d in g.Description]) if "Description" in g else g
    name = t.NAME.astype(str).str.strip()
    keep = ((t.DESCRIPTION.astype(str).str.strip() == "CC") & ~name.str.contains(r"\(U/C\)|Pending", regex=True)).to_numpy()
    return _pts(g[keep], "community_club", name[keep], crs)


def primary_schools(path, crs=3414):
    s = pd.read_csv(path, dtype={"postal_code": str})
    s = s[s.mainlevel_code.isin(["PRIMARY", "MIXED LEVEL (P1-S4)"]) & s.lat.notna()]
    g = gpd.GeoDataFrame(s, geometry=gpd.points_from_xy(s.lon.astype(float), s.lat.astype(float)), crs=4326)
    return _pts(g, "primary_school", s.school_name.str.title(), crs)


def parks(path, crs=3414):
    g = gpd.read_file(path)
    g = g[g.N_RESERVE != 1].to_crs(crs)
    return gpd.GeoDataFrame({"kind": "park", "name": g.NAME.str.title().values}, geometry=g.geometry.values, crs=crs)


def zoned_parks(path, crs=3414):
    """Land zoned PARK in the Master Plan 2025 (includes neighbourhood parks that NParks does not manage)."""
    g = gpd.read_file(path, columns=["LU_DESC"])
    g = g[g.LU_DESC == "PARK"].to_crs(crs)
    return gpd.GeoDataFrame({"kind": ["park_zoned"] * len(g), "name": ["MP2025 park"] * len(g)},
                            geometry=g.geometry.values, crs=crs)


def load_all(raw, crs=3414):
    pts = pd.concat([
        bus_stops(raw / "lta_bus_stop.geojson", crs),
        mrt_exits(raw / "lta_mrt_exit.geojson", crs),
        hawkers(raw / "nea_hawker_centres.geojson", crs),
        clinics(raw / "moh_chas_clinics.geojson", crs),
        community_clubs(raw / "pa_community_clubs.geojson", crs),
        primary_schools(raw / "moe_schools_geocoded.csv", crs),
    ], ignore_index=True)
    polys = {"park": parks(raw / "nparks_parks_nature_reserves.geojson", crs),
             "park_zoned": zoned_parks(raw / "mp2025_land_use.geojson", crs)}
    return gpd.GeoDataFrame(pts, geometry="geometry", crs=crs), polys
