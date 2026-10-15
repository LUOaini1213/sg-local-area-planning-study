"""Study settings. Every threshold below is a planning convention, cited in README.md section 'Thresholds'."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
WORK = ROOT / "data" / "work"          # rebuilt intermediates (git-ignored)
OUT = ROOT / "outputs"                 # small result tables (committed)
FIG = ROOT / "report" / "figures"      # PNG maps and charts (committed)

CRS = 3414                             # SVY21 / Singapore TM, metres
STUDY_AREA = "JURONG EAST"             # MP2019 planning area name (PLN_AREA_N)
STUDY_BUFFER_M = 2_000                 # amenities this far outside the boundary still serve its residents
WALK_M_PER_MIN = 80                    # 4.8 km/h

# amenity -> walking threshold (network metres)
THRESHOLD_M = {
    "bus_stop": 400,        # 5-minute walk, the usual bus catchment
    "mrt_exit": 800,        # 10-minute walk to a train station (URA MP2025 West region)
    "park": 800,            # 10-minute walk to a park for every household by 2030 (NParks, City in Nature)
    "park_zoned": 800,      # same target, measured to any land zoned PARK in MP2025
    "hawker": 800,          # 10-minute walk (no statutory norm; same as the neighbourhood standard above)
    "clinic": 800,          # CHAS GP clinic, 10-minute walk
    "community_club": 800,  # PA community club, 10-minute walk
    "primary_school": 1_000,  # MOE P1 registration home-school distance band "within 1 km"
}
SENSITIVITY_M = (600, 800, 1_000)     # alternative thresholds reported for the 800 m amenities

GRID_M = 25                            # spacing of resident origin points inside housing parcels
SNAP_WARN_M = 150                      # origins or amenities further than this from the walk network are flagged
PARK_EDGE_M = 20                       # walk-network nodes this close to a park polygon count as park entrances
MIN_PA_RESIDENTS = 10_000              # planning areas below this are left out of the island-wide median

RESIDENTIAL = ("RESIDENTIAL", "RESIDENTIAL WITH COMMERCIAL AT 1ST STOREY", "COMMERCIAL & RESIDENTIAL",
               "RESIDENTIAL / INSTITUTION")

# scenario assumptions (stated in the brief; varied in the sensitivity table)
GFA_PER_DWELLING_M2 = 100              # gross floor area per dwelling unit incl. common areas
GFA_PER_DWELLING_RANGE = (85, 115)
PERSONS_PER_HOUSEHOLD = 3.06           # SingStat GHS 2025, average resident household size
