"""Headline numbers in the brief and README must match the committed outputs (rounded as printed).

README: every number in the opening lines and in 'Headline findings' is pinned by a pattern anchored to its sentence or
table row, and test_readme_has_no_unpinned_numbers fails on any number there that no pattern covers.
Brief: a fixed list of headline numbers is checked by substring (not every number in the brief).
"""
import json
import re
import string
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
BRIEF = (ROOT / "report" / "brief.md").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")

sys.path.insert(0, str(ROOT / "src"))

from lap import config, landuse  # noqa: E402


def pct(x, nd=0):
    return f"{x * 100:.{nd}f} %"


def thousands(x, step=100):
    return f"{round(x / step) * step:,.0f}"


def ordinal(n):
    n = int(n)
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def gfa_split_from_outputs():
    """GFA change split from the committed parcel table, cross-checked with summary.json when the pipeline wrote it."""
    chg = pd.read_csv(OUT / "zoning_changes_mp2019_mp2025.csv", dtype={"gpr2019": str, "gpr2025": str},
                      keep_default_na=False)
    split = landuse.gfa_change_split(chg)
    s = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))
    if "gfa_change_split_ha" in s:          # written by pipeline.run() from the unrounded table
        # the CSV rounds ha to 0.01, so each row can move its part by up to 0.005 ha x its GPR
        g = lambda c: pd.to_numeric(chg[c], errors="coerce").fillna(0)
        tol = float((0.005 * (g("gpr2019") + g("gpr2025"))).sum()) + 1e-6
        for k, v in s["gfa_change_split_ha"].items():
            assert split[k] == pytest.approx(v, abs=tol), k
    return chg, split


def expected():
    s = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))
    cmp_ = pd.read_csv(OUT / "ratios_vs_island_median.csv").set_index("metric")
    sz = pd.read_csv(OUT / "access_subzone.csv", index_col=0)
    pa = pd.read_csv(OUT / "planning_area_indicators.csv", index_col=0)
    lu19 = pd.read_csv(OUT / "landuse_subzone_mp2019.csv", index_col=0)
    lu25 = pd.read_csv(OUT / "landuse_subzone_mp2025.csv", index_col=0)
    chg, split = gfa_split_from_outputs()
    sc = s["scenario"]
    plots = {p["plot"]: p for p in sc["plots"]}
    load = {k: pd.read_csv(OUT / f"scenario_load_{k}.csv").iloc[0] for k in ("hawker", "community_club", "clinic")}
    cov = s["coverage_study_area"]
    gfa19, gfa25 = lu19.gfa_potential_m2.sum() / 1e4, lu25.gfa_potential_m2.sum() / 1e4

    def change_ha(subzone, lu19_, lu25_):
        row = chg[(chg.SUBZONE_N == subzone) & (chg.lu2019 == lu19_) & (chg.lu2025 == lu25_)]
        assert len(row) == 1, (subzone, lu19_, lu25_)
        return f"{row.ha.iloc[0]:.1f}"

    def rank_label(metric):
        r, n = cmp_.loc[metric, "rank"], cmp_.loc[metric, "of"]
        return f"lowest of {n}" if r == n else f"{ordinal(r)} of {n}"

    min_ha = re.search(r'query\("ha >= ([\d.]+)"\)', (ROOT / "src" / "lap" / "pipeline.py").read_text(
        encoding="utf-8")).group(1)
    assert chg.ha.min() >= float(min_ha)
    jem = pa.loc["JURONG EAST"]
    return {
        "residents": f"{jem.residents:,.0f}",
        "residents subzone sum": f"{s['residents_study_area']:,.0f}",
        "aged 65+": pct(jem.age_65_plus / jem.residents),
        "areas compared": f"{cmp_.loc['within_mrt_exit', 'of']}",
        "min residents": f"{config.MIN_PA_RESIDENTS:,}",
        "walk 800": f"{config.THRESHOLD_M['mrt_exit']} m",
        "school walk": f"{config.THRESHOLD_M['primary_school'] / 1000:.0f} km",
        "mrt today": pct(cov["mrt_exit"]),
        "mrt median": pct(cmp_.loc["within_mrt_exit", "island_median"]),
        "mrt rank": f"{ordinal(cmp_.loc['within_mrt_exit', 'rank'])} of {cmp_.loc['within_mrt_exit', 'of']}",
        "mrt future": pct(s["coverage_mrt_future"]),
        "mrt future median": pct(cmp_.loc["within_mrt_future", "island_median"]),
        "hawker": pct(cov["hawker"]),
        "hawker median": pct(cmp_.loc["within_hawker", "island_median"]),
        "nparks park": pct(cov["park"]),
        "nparks park median": pct(cmp_.loc["within_park", "island_median"]),
        "nparks park rank": rank_label("within_park"),
        "nparks park rank words": rank_label("within_park").replace(" of ", " of the "),
        "zoned park": pct(cov["park_zoned"], 1),
        "zoned park median": pct(cmp_.loc["within_park_zoned", "island_median"], 1),
        "clinic": pct(cov["clinic"]),
        "cc": pct(cov["community_club"]),
        "toh guan residents": f"{sz.loc['TOH GUAN', 'residents']:,.0f}",
        "toh guan hawker": "none" if sz.loc["TOH GUAN", "within_hawker"] == 0 else pct(sz.loc["TOH GUAN", "within_hawker"]),
        "toh guan cc": pct(sz.loc["TOH GUAN", "within_community_club"]),
        "toh guan cc with hub": pct(sz.loc["TOH GUAN", "within_cc_with_hub"]),
        "toh guan beyond cc with hub": pct(1 - sz.loc["TOH GUAN", "within_cc_with_hub"]),
        "teban rail": pct(sz.loc["TEBAN GARDENS", "within_mrt_exit"]),
        "toh guan rail": pct(sz.loc["TOH GUAN", "within_mrt_exit"]),
        "teban future rail": pct(sz.loc["TEBAN GARDENS", "within_mrt_future"]),
        "toh guan future rail": pct(sz.loc["TOH GUAN", "within_mrt_future"]),
        "two or more gaps": thousands(s["residents_two_or_more_neighbourhood_gaps"]),
        "two or more share": pct(s["residents_two_or_more_neighbourhood_gaps"] / s["residents_study_area"]),
        "gfa 2019": f"{gfa19:,.0f}",
        "gfa 2025": f"{gfa25:,.0f}",
        "gfa change pct": f"+{(gfa25 / gfa19 - 1) * 100:.1f} %",
        "gfa change ha": f"+{gfa25 - gfa19:.0f}",
        "gfa gained gpr": f"{split['gained_gpr']:.1f}",
        "gfa lost gpr": f"{-split['lost_gpr']:.1f}",
        "gfa both numeric": f"{split['both_numeric']:.1f}",
        "gfa parts sum": f"+{sum(split.values()):.1f}",
        "change table min ha": min_ha,
        "jalan papan to residential": change_ha("JURONG RIVER", "RESERVE SITE", "RESIDENTIAL"),
        "toh guan to residential": change_ha("TOH GUAN", "RESERVE SITE", "RESIDENTIAL"),
        "sdp ha": f"{lu25.ha_gpr_SDP.sum():.0f}",
        "lakeside sdp ha": f"{lu25.loc['LAKESIDE (BUSINESS)', 'ha_gpr_SDP']:.0f}",
        "unoccupied ha": f"{sum(p['area_ha'] for p in sc['plots']):.0f}",
        "local density": f"{s['zoned_res_gfa_m2_per_resident']:.1f} m²",
        "capacity density": f"{config.GFA_PER_DWELLING_M2 / config.PERSONS_PER_HOUSEHOLD:.1f} m²",
        "gfa per dwelling": f"{config.GFA_PER_DWELLING_M2}",
        "persons per household": f"{config.PERSONS_PER_HOUSEHOLD}",
        "circuity": f"× {s['circuity_study_area']:.2f}",
        "combined central": thousands(sc["combined_residents_central"]),
        "combined capacity": thousands(sum(p["residents_plan_capacity"] for p in sc["plots"])),
        "combined intensified": thousands(sc["combined_residents_intensified"]),
        "P1 central": thousands(plots["plot1"]["residents_central"]),
        "P1 capacity": thousands(plots["plot1"]["residents_plan_capacity"]),
        "P2 central": thousands(plots["plot2"]["residents_central"]),
        "P1 rail if connected": pct(plots["plot1"]["share_within_if_connected"]["mrt_future"]),
        "hawker load before": thousands(load["hawker"].before),
        "hawker load after": thousands(load["hawker"].after),
        "hawker load": f"+{load['hawker'].change_pct:.0f} %",
        "hawker load intensified": f"+{load['hawker'].change_pct_intensified:.0f} %",
        "cc load": f"+{load['community_club'].change_pct:.0f} %",
        "clinic load": f"+{load['clinic'].change_pct:.0f} %",
        "sdp gpr": f"({sc['gpr_central_sdp']:.1f})",
        "intensified gpr": f"({sc['gpr_intensified']:.1f})",
        "pdf pages": str(len(re.findall(rb"/Type\s*/Page[^s]", (ROOT / "report" / "brief.pdf").read_bytes()))),
    }


E = expected()

BRIEF_KEYS = [
    "residents", "mrt today", "mrt median", "mrt rank", "mrt future", "hawker", "hawker median", "nparks park",
    "zoned park", "zoned park median", "clinic", "cc", "toh guan cc", "toh guan cc with hub",
    "toh guan beyond cc with hub", "teban future rail", "toh guan future rail", "two or more gaps",
    "two or more share", "gfa 2019", "gfa 2025", "gfa change pct", "gfa gained gpr", "gfa lost gpr",
    "gfa both numeric", "gfa parts sum", "local density", "capacity density", "circuity", "combined central",
    "combined capacity", "combined intensified", "P1 central", "P1 capacity", "P2 central", "P1 rail if connected",
    "hawker load", "hawker load intensified", "cc load", "clinic load", "sdp gpr", "intensified gpr",
]


@pytest.mark.parametrize("name", BRIEF_KEYS)
def test_brief_numbers(name):
    text = E[name]
    assert text in BRIEF, f"{name}: expected '{text}' in report/brief.md"


def anchored(template):
    """Regex for a README sentence: {key} fields become the expected values, any run of spaces may wrap."""
    out = []
    for literal, field, _, _ in string.Formatter().parse(template):
        out.append(re.escape(literal))
        if field is not None:
            out.append(re.escape(E[field]))
    return re.sub(r"(\\ )+", r"\\s+", "".join(out))


# (section, sentence or table row with {expected value} fields)
README_PINS = [
    ("intro", "The output is an {pdf pages}-page planning brief"),
    ("intro", "{mrt today} of residents live within {walk 800} of an MRT exit (median {mrt median}), and "
              "{mrt future} will once the JRL and CRL stations open"),
    ("intro", "{two or more share} are beyond the threshold for two or more of five neighbourhood facilities"),
    ("intro", "building the four unoccupied residential plots adds about {combined central} residents"),
    ("why", "About {unoccupied ha} ha of land zoned residential had essentially no residents"),
    ("headline", "Jurong East had {residents} residents in 2025, {aged 65+} of them aged 65 or over"),
    ("headline", "they sum to {residents subzone sum}, the base used for shares below"),
    ("headline", '"Median" means the median of the {areas compared} planning areas with at least {min residents} '
                 "residents"),
    ("headline", "| Residents within {walk 800} of an MRT exit ({mrt rank}) | {mrt today} | {mrt median} |"),
    ("headline", "| Same, counting JRL and CRL stations not yet open | {mrt future} | {mrt future median} |"),
    ("headline", "| Within {walk 800} of a hawker centre | {hawker} | {hawker median} |"),
    ("headline", "| Within {walk 800} of land zoned Park | {zoned park} | {zoned park median} |"),
    ("headline", "| Within {walk 800} of an NParks-managed park ({nparks park rank}) | {nparks park} | "
                 "{nparks park median} |"),
    ("headline", "Teban Gardens is at {teban rail} within {walk 800} of an MRT exit and Toh Guan at {toh guan rail}; "
                 "the new stations would raise them to {teban future rail} and {toh guan future rail}."),
    ("headline", "Toh Guan ({toh guan residents} residents) has {toh guan hawker} within {walk 800}."),
    ("headline", "Only {toh guan cc} of Toh Guan residents are within {walk 800} of one. A club at the planned "
                 "Jurong Gateway Hub would lift that to {toh guan cc with hub}: {toh guan beyond cc with hub} of "
                 "Toh Guan residents would still be more than {walk 800} from any club."),
    ("headline", "the NParks-managed measure is the {nparks park rank words}."),
    ("headline", "{two or more gaps} residents ({two or more share}) are beyond the threshold for at least two of "
                 "five neighbourhood facilities: hawker centre, clinic, community club, zoned park and primary school "
                 "({school walk})."),
    ("headline", "rose from {gfa 2019} ha in MP2019 to {gfa 2025} ha in MP2025 ({gfa change pct}, {gfa change ha} "
                 "ha). Most of that is land gaining a published GPR, not upzoning."),
    ("headline", "land that went from SDP, EVA or no GPR to a number adds {gfa gained gpr} ha of GFA, land that lost "
                 "its number removes {gfa lost gpr} ha, and land with a number in both plans adds only "
                 "{gfa both numeric} ha. (Changes under {change table min ha} ha are left out of the parcel table, "
                 "so these parts sum to {gfa parts sum} ha.)"),
    ("headline", "MP2025 also turned {jalan papan to residential} ha of reserve land at Jalan Papan and "
                 "{toh guan to residential} ha in Toh Guan into residential land. {sdp ha} ha, including "
                 "{lakeside sdp ha} ha of the Lakeside (Business) core, has no published GPR (SDP)."),
    ("headline", "adds about {combined central} residents; at plan capacity ({gfa per dwelling} m² per dwelling, "
                 "{persons per household} persons per household) the same floor area holds {combined capacity}."),
    ("headline", "Teban Gardens Market would become the nearest hawker centre for {hawker load after} residents, up "
                 "from {hawker load before} ({hawker load})."),
]

# numbers in pinned sections that are names, not results (plan years)
README_NAMES = [r"MP20(?:19|25)", r"Master\s+Plan\s+2019\s+and\s+2025", r"residents\s+in\s+2025"]


def readme_section(name):
    bounds = {"intro": (r"\A", r"^## Why Jurong East"), "why": (r"^## Why Jurong East", r"^## Headline findings"),
              "headline": (r"^## Headline findings", r"^!\[Walking distance maps\]")}
    a, b = bounds[name]
    start = re.search(a, README, re.M).end()
    end = re.search(b, README[start:], re.M).start() + start
    return README[start:end]


@pytest.mark.parametrize("section,template", README_PINS, ids=[t[:50] for _, t in README_PINS])
def test_readme_numbers(section, template):
    assert re.search(anchored(template), readme_section(section)), \
        f"README.md ({section}) no longer contains, with today's outputs:\n  {template.format_map(E)}"


@pytest.mark.parametrize("section", ["intro", "headline"])
def test_readme_has_no_unpinned_numbers(section):
    text = readme_section(section)
    covered = []
    for sec, template in README_PINS:
        if sec == section:
            covered += [m.span() for m in re.finditer(anchored(template), text)]
    for pat in README_NAMES:
        covered += [m.span() for m in re.finditer(pat, text)]
    loose = [m.group() for m in re.finditer(r"\d(?:[\d,]*\d)?(?:\.\d+)?", text)
             if not any(a <= m.start() and m.end() <= b for a, b in covered)]
    assert not loose, f"numbers in README.md ({section}) that no check pins to the outputs: {loose}"


def test_readme_mutant_count_matches_mutate_py():
    import importlib.util
    spec = importlib.util.spec_from_file_location("mutate", ROOT / "tests" / "mutate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert f"plants {len(mod.MUTANTS)} specific bugs" in README


def test_scenario_case_ordering_as_described():
    """README and brief say plan capacity is not a ceiling (the sensitivity range goes higher) and that the
    intensified case, at local density, can come out below plan capacity."""
    sc = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))["scenario"]
    for p in sc["plots"]:
        assert p["residents_range"][1] > p["residents_plan_capacity"], p["plot"]
    assert sc["combined_residents_intensified"] < sum(p["residents_plan_capacity"] for p in sc["plots"])
    assert "not a ceiling" in README and "not a ceiling" in BRIEF
