"""Every headline number in the brief and README must match the committed outputs (rounded as printed)."""
import json
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
BRIEF = (ROOT / "report" / "brief.md").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")


def pct(x, nd=0):
    return f"{x * 100:.{nd}f} %"


def thousands(x, step=100):
    return f"{round(x / step) * step:,.0f}"


def expected():
    s = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))
    cmp_ = pd.read_csv(OUT / "ratios_vs_island_median.csv").set_index("metric")
    sz = pd.read_csv(OUT / "access_subzone.csv", index_col=0)
    pa = pd.read_csv(OUT / "planning_area_indicators.csv", index_col=0)
    sc = s["scenario"]
    plots = {p["plot"]: p for p in sc["plots"]}
    load = {k: pd.read_csv(OUT / f"scenario_load_{k}.csv").iloc[0] for k in ("hawker", "community_club", "clinic")}
    cov = s["coverage_study_area"]
    return {
        "residents": f"{pa.loc['JURONG EAST', 'residents']:,.0f}",
        "mrt today": pct(cov["mrt_exit"]),
        "mrt median": pct(cmp_.loc["within_mrt_exit", "island_median"]),
        "mrt rank": f"{cmp_.loc['within_mrt_exit', 'rank']}th of {cmp_.loc['within_mrt_exit', 'of']}",
        "mrt future": pct(s["coverage_mrt_future"]),
        "hawker": pct(cov["hawker"]),
        "hawker median": pct(cmp_.loc["within_hawker", "island_median"]),
        "nparks park": pct(cov["park"]),
        "zoned park": pct(cov["park_zoned"], 1),
        "zoned park median": pct(cmp_.loc["within_park_zoned", "island_median"], 1),
        "clinic": pct(cov["clinic"]),
        "cc": pct(cov["community_club"]),
        "toh guan cc": pct(sz.loc["TOH GUAN", "within_community_club"]),
        "toh guan cc with hub": pct(sz.loc["TOH GUAN", "within_cc_with_hub"]),
        "teban future rail": pct(sz.loc["TEBAN GARDENS", "within_mrt_future"]),
        "toh guan future rail": pct(sz.loc["TOH GUAN", "within_mrt_future"]),
        "two or more gaps": thousands(s["residents_two_or_more_neighbourhood_gaps"]),
        "two or more share": pct(s["residents_two_or_more_neighbourhood_gaps"] / s["residents_study_area"]),
        "local density": f"{s['zoned_res_gfa_m2_per_resident']:.1f} m²",
        "circuity": f"× {s['circuity_study_area']:.2f}",
        "combined central": thousands(sc["combined_residents_central"]),
        "combined capacity": thousands(sum(p["residents_plan_capacity"] for p in sc["plots"])),
        "combined intensified": thousands(sc["combined_residents_intensified"]),
        "P1 central": thousands(plots["plot1"]["residents_central"]),
        "P1 capacity": thousands(plots["plot1"]["residents_plan_capacity"]),
        "P2 central": thousands(plots["plot2"]["residents_central"]),
        "P1 rail if connected": pct(plots["plot1"]["share_within_if_connected"]["mrt_future"]),
        "hawker load": f"+{load['hawker'].change_pct:.0f} %",
        "hawker load intensified": f"+{load['hawker'].change_pct_intensified:.0f} %",
        "cc load": f"+{load['community_club'].change_pct:.0f} %",
        "clinic load": f"+{load['clinic'].change_pct:.0f} %",
        "sdp gpr": f"({sc['gpr_central_sdp']:.1f})",
        "intensified gpr": f"({sc['gpr_intensified']:.1f})",
    }


@pytest.mark.parametrize("name,text", list(expected().items()))
def test_brief_numbers(name, text):
    assert text in BRIEF, f"{name}: expected '{text}' in report/brief.md"


README_KEYS = ["residents", "mrt today", "mrt future", "hawker", "nparks park", "zoned park", "toh guan cc",
               "two or more gaps", "combined central", "combined capacity", "hawker load"]


@pytest.mark.parametrize("name", README_KEYS)
def test_readme_numbers(name):
    text = expected()[name]
    assert text in README, f"{name}: expected '{text}' in README.md"
