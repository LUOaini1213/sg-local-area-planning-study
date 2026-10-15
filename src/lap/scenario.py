"""Intensification scenario: residents added by developing one plot, and what that does to walking access and to
the load on nearby facilities.

Two ways to turn floor area into residents:
  plan capacity   residents = area x GPR x net share / GFA per dwelling unit x persons per household
  local density   residents = area x GPR x net share / (zoned residential GFA per resident in the study area's
                  existing estates), which builds in how far today's estates fall short of their zoned intensity.
Every factor except the plot area is an assumption and is varied in the sensitivity table.
"""
import itertools

import numpy as np
import pandas as pd


def added_residents(area_m2, gpr, net_share, gfa_per_du, persons_per_hh):
    dwellings = area_m2 * gpr * net_share / gfa_per_du
    return dwellings, dwellings * persons_per_hh


def local_density(gfa_by_area, residents_by_area, min_residents=1000):
    """Zoned residential GFA per resident, pooled over areas with at least min_residents residents."""
    g = np.asarray(gfa_by_area, dtype=float)
    r = np.asarray(residents_by_area, dtype=float)
    ok = (r >= min_residents) & (g > 0)
    return float(g[ok].sum() / r[ok].sum())


def residents_at_density(area_m2, gpr, net_share, gfa_per_resident):
    return area_m2 * gpr * net_share / gfa_per_resident


def sensitivity(area_m2, gprs, net_shares, gfa_per_dus, persons_per_hh):
    rows = []
    for g, s, f in itertools.product(gprs, net_shares, gfa_per_dus):
        du, res = added_residents(area_m2, g, s, f, persons_per_hh)
        rows.append({"gpr": g, "net_share": s, "gfa_per_du_m2": f, "dwellings": du, "residents": res})
    return pd.DataFrame(rows)


def load_change(base_load, add_load):
    """Per-facility nearest-facility load before and after, with percentage change."""
    base = np.asarray(base_load, dtype=float)
    after = base + np.asarray(add_load, dtype=float)
    pct = np.where(base > 0, (after - base) / np.where(base > 0, base, 1) * 100, np.nan)
    return pd.DataFrame({"before": base, "after": after, "change_pct": pct})
