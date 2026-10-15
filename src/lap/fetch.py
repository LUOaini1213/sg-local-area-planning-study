"""Download every public input into data/raw and record its source, retrieval time and SHA-256 in data/sources.csv.

All inputs are keyless public downloads:
  * data.gov.sg (URA, LTA, NEA, NParks, MOH, PA and MOE datasets) via the v1 poll-download API;
  * SingStat Table Builder table C020123 (General Household Survey 2025, residents by planning area / subzone);
  * OneMap search API, used only to geocode MOE school postal codes;
  * the BBBike OpenStreetMap extract of Singapore (walking network).

Run:  python -m lap.fetch            (skips files that already exist)
      python -m lap.fetch --force    (re-downloads everything)
"""
import csv
import datetime as dt
import hashlib
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
MANIFEST = ROOT / "data" / "sources.csv"
HDR = {"User-Agent": "sg-local-area-planning-study/0.1 (research; github.com/LUOaini1213)"}

# file name -> (data.gov.sg dataset id, title as published, agency)
DATAGOV = {
    "mp2019_land_use.geojson": ("d_90d86daa5bfaa371668b84fa5f01424f", "Master Plan 2019 Land Use layer", "URA"),
    "mp2025_land_use.geojson": ("d_a8c3546b26712e35021f3a681d0353ae", "Master Plan 2025 Land Use Layer", "URA"),
    "mp2019_subzone.geojson": ("d_8594ae9ff96d0c708bc2af633048edfb", "Master Plan 2019 Subzone Boundary (No Sea)", "URA"),
    "mp2019_planning_area.geojson": ("d_4765db0e87b9c86336792efe8a1f7a66",
                                     "Master Plan 2019 Planning Area Boundary (No Sea)", "URA"),
    "mp2025_rail_station.geojson": ("d_2c06c9fe8ae724b5d33efa1f203e2c38", "Master Plan 2025 Rail Station Layer", "URA"),
    "mp2025_integrated_transport_hub.geojson": ("d_a5047ce23e02c5ca3aa56199d7d3eb59",
                                                "Master Plan 2025 SDCP Integrated Transport Hub layer", "URA"),
    "lta_bus_stop.geojson": ("d_3f172c6feb3f4f92a2f47d93eed2908a", "LTA Bus Stop", "LTA"),
    "lta_mrt_exit.geojson": ("d_b39d3a0871985372d7e1637193335da5", "LTA MRT Station Exit (GEOJSON)", "LTA"),
    "nea_hawker_centres.geojson": ("d_4a086da0a5553be1d89383cd90d07ecd", "Hawker Centres (GEOJSON)", "NEA"),
    "nparks_parks_nature_reserves.geojson": ("d_77d7ec97be83d44f61b85454f844382f",
                                             "NParks Parks and Nature Reserves", "NParks"),
    "moh_chas_clinics.geojson": ("d_548c33ea2d99e29ec63a7cc9edcccedc", "CHAS Clinics", "MOH"),
    "pa_community_clubs.geojson": ("d_9de02d3fb33d96da1855f4fbef549a0f", "Community Club / PAssion WaVe Outlet", "PA"),
    "moe_schools.csv": ("d_688b934f82c1059ed0a6993d2a829089", "General information of schools", "MOE"),
}
SINGSTAT = ("singstat_C020123_ghs2025.json", "https://tablebuilder.singstat.gov.sg/api/table/tabledata/C020123",
            "SingStat Table C020123, Resident Population by Planning Area/Subzone of Residence, Age Group and Sex "
            "(General Household Survey 2025)")
OSM = ("Singapore.osm.gz", "https://download.bbbike.org/osm/bbbike/Singapore/Singapore.osm.gz",
       "OpenStreetMap contributors, BBBike extract of Singapore (ODbL)")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _get(url, **kw):
    for attempt in range(4):
        try:
            r = requests.get(url, headers=HDR, timeout=300, **kw)
            if r.status_code == 429:
                time.sleep(10 * (attempt + 1))
                continue
            r.raise_for_status()
            return r
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(url)


def datagov(ds):
    meta = _get(f"https://api-open.data.gov.sg/v1/public/api/datasets/{ds}/poll-download").json()
    return _get(meta["data"]["url"]).content


def geocode_schools(csv_path, out_path):
    """Geocode MOE school postal codes with the OneMap search API (keyless). Unmatched codes are kept with no x/y."""
    rows = list(csv.DictReader(open(csv_path, encoding="utf-8-sig")))
    out = []
    for r in rows:
        pc = str(r["postal_code"]).zfill(6)
        res = _get("https://www.onemap.gov.sg/api/common/elastic/search",
                   params={"searchVal": pc, "returnGeom": "Y", "getAddrDetails": "Y", "pageNum": 1}).json()
        hit = next((x for x in res.get("results", []) if x.get("POSTAL") == pc), None)
        out.append({"school_name": r["school_name"], "mainlevel_code": r["mainlevel_code"], "postal_code": pc,
                    "lat": hit["LATITUDE"] if hit else "", "lon": hit["LONGITUDE"] if hit else ""})
        time.sleep(0.3)  # OneMap allows 250 calls a minute
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    return sum(1 for o in out if o["lat"]), len(out)


def main(force=False):
    RAW.mkdir(parents=True, exist_ok=True)
    log = {}
    if MANIFEST.exists():
        log = {r["file"]: r for r in csv.DictReader(open(MANIFEST, encoding="utf-8"))}
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M SGT")

    def record(name, source, title):
        p = RAW / name
        log[name] = {"file": name, "title": title, "source": source, "retrieved": now,
                     "bytes": p.stat().st_size, "sha256": sha256(p)}

    for name, (ds, title, agency) in DATAGOV.items():
        if force or not (RAW / name).exists():
            (RAW / name).write_bytes(datagov(ds))
            record(name, f"https://data.gov.sg/datasets/{ds}/view", f"{agency}: {title}")
            print("ok", name)
    name, url, title = SINGSTAT
    if force or not (RAW / name).exists():
        (RAW / name).write_bytes(_get(url, params={"limit": 5000}).content)
        record(name, url, title)
    name, url, title = OSM
    if force or not (RAW / name).exists():
        with _get(url, stream=True) as r, open(RAW / name, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
        record(name, url, title)
    if force or not (RAW / "moe_schools_geocoded.csv").exists():
        hit, n = geocode_schools(RAW / "moe_schools.csv", RAW / "moe_schools_geocoded.csv")
        record("moe_schools_geocoded.csv", "https://www.onemap.gov.sg/api/common/elastic/search",
               f"SLA OneMap search API: postal-code geocode of MOE schools ({hit}/{n} matched)")
        print(f"schools geocoded {hit}/{n}")

    used = set(DATAGOV) | {SINGSTAT[0], OSM[0], "moe_schools_geocoded.csv"}
    log = {k: v for k, v in log.items() if k in used}
    with open(MANIFEST, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["file", "title", "source", "retrieved", "bytes", "sha256"])
        w.writeheader()
        for k in sorted(log):
            w.writerow(log[k])


if __name__ == "__main__":
    main(force="--force" in sys.argv)
