"""PNG maps and charts for the brief (report/figures). Static, light background, print-friendly.

Colour roles: land-use groups use fixed categorical slots; distance maps use a diverging blue/red pair around the
walking threshold (blue = within, red = beyond) with a light grey for 'no residents'."""
import json

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from . import amenities, landuse  # noqa: E402
from .config import CRS, FIG, OUT, RAW, STUDY_AREA, THRESHOLD_M, WORK  # noqa: E402

INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#8a8984", "#e4e3df"
SURFACE = "#fcfcfb"
LU_COLOR = {  # categorical slots in fixed order; non-activity land in greys
    "Residential": "#eda100", "Commercial & mixed": "#e34948", "Business": "#4a3aa7",
    "Institution & community": "#2a78d6", "Parks & recreation": "#1baf7a",
    "Transport": "#e4e3df", "Water": "#cde2fb", "Reserve site": "#c9c7c0", "Utility & special": "#b5b3ab",
    "Other": "#d8d6d0",
}
BANDS = [(0, 400, "#1c5cab", "0-400 m"), (400, 800, "#86b6ef", "400-800 m"),
         (800, 1200, "#f0a3a2", "800-1,200 m"), (1200, np.inf, "#c9302f", "over 1,200 m")]

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8, "axes.edgecolor": MUTED,
                     "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                     "figure.facecolor": "white", "savefig.facecolor": "white"})


def _ctx():
    sz = gpd.read_file(RAW / "mp2019_subzone.geojson").to_crs(CRS)
    pa = gpd.read_file(RAW / "mp2019_planning_area.geojson").to_crs(CRS)
    szj = sz[sz.PLN_AREA_N == STUDY_AREA]
    je = pa[pa.PLN_AREA_N == STUDY_AREA]
    return sz, szj, je


def _frame(ax, je, pad=300):
    x0, y0, x1, y1 = je.total_bounds
    ax.set_xlim(x0 - pad, x1 + pad)
    ax.set_ylim(y0 - pad, y1 + pad)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)


def _scalebar(ax, je, length=1000):
    x0, y0, _, _ = je.total_bounds
    ax.plot([x0, x0 + length], [y0 - 150, y0 - 150], color=INK, lw=2, solid_capstyle="butt")
    ax.text(x0 + length / 2, y0 - 120, "1 km", ha="center", va="bottom", fontsize=7, color=INK)


def _base(ax, lu, szj, je, alpha=0.55):
    lu.plot(ax=ax, color=lu.group.map(LU_COLOR).fillna("#d8d6d0"), alpha=alpha, linewidth=0)
    szj.boundary.plot(ax=ax, color="white", lw=1.6)
    szj.boundary.plot(ax=ax, color=INK2, lw=0.5)
    je.boundary.plot(ax=ax, color=INK, lw=1.2)


def _labels(ax, szj, min_km2=0.4):
    for _, r in szj.iterrows():
        if r.geometry.area / 1e6 < min_km2 and r.SUBZONE_N not in ("TOH GUAN", "JURONG GATEWAY"):
            continue
        c = r.geometry.representative_point()
        ax.text(c.x, c.y, r.SUBZONE_N.title().replace("(", "\n("), fontsize=6.2, color=INK, ha="center",
                va="center", bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.7))


def _landuse_clip(je, year="2025"):
    f = WORK / f"lu{year}_clip.parquet"
    if f.exists():
        return gpd.read_parquet(f)
    lu = landuse.load(RAW / f"mp{year}_land_use.geojson", CRS)
    box = je.buffer(1500).union_all()
    lu = lu[lu.intersects(box)].copy()
    lu.to_parquet(f)
    return lu


def fig_context(sz, szj, je, amen, fut):
    lu = _landuse_clip(je)
    fig, ax = plt.subplots(figsize=(7.2, 6.2))
    _base(ax, lu, szj, je, alpha=0.75)
    ex = amen[(amen.kind == "mrt_exit") & (amen.distance(je.union_all()) < 1500)]
    f = fut[fut.distance(je.union_all()) < 1500]
    f.plot(ax=ax, facecolor="white", edgecolor=INK, lw=1.0, hatch="////")
    ex.plot(ax=ax, color=INK, markersize=9, marker="s")
    for _, r in f.drop_duplicates("NAME").iterrows():
        c = r.geometry.centroid
        ax.annotate(r.NAME.title(), (c.x, c.y), xytext=(4, 4), textcoords="offset points", fontsize=6, color=INK,
                    bbox=dict(boxstyle="round,pad=0.1", fc="white", ec="none", alpha=0.8))
    plots = [gpd.read_parquet(p) for p in sorted(WORK.glob("scenario_plot*.parquet"))]
    for p in plots:
        p.boundary.plot(ax=ax, color=INK, lw=1.4, linestyle="--")
        c = p.geometry.iloc[0].representative_point()
        ax.text(c.x, c.y, p["plot"].iloc[0].replace("plot", "P"), fontsize=7, fontweight="bold", color=INK,
                ha="center", va="center", zorder=5,
                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec=INK, lw=0.6))
    _labels(ax, szj)
    _frame(ax, je)
    _scalebar(ax, je)
    handles = [Patch(color=LU_COLOR[g], label=g, alpha=0.75) for g in landuse.ACTIVITY] + [
        Patch(color=LU_COLOR["Transport"], label="Roads and rail"), Patch(color=LU_COLOR["Water"], label="Water"),
        Line2D([], [], marker="s", color=INK, lw=0, markersize=4, label="MRT exit (LTA, open)"),
        Patch(facecolor="white", edgecolor=INK, hatch="////", label="Station not yet open (MP2025)"),
        Line2D([], [], color=INK, lw=1.4, ls="--", label="Scenario plot (P1-P4)")]
    ax.legend(handles=handles, loc="lower right", fontsize=6.2, frameon=True, framealpha=0.9, edgecolor=GRID)
    ax.set_title("Jurong East: Master Plan 2025 land use, rail and scenario plots", fontsize=9, color=INK,
                 loc="left")
    fig.savefig(FIG / "fig1_context.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


def fig_landuse():
    t19 = pd.read_csv(OUT / "landuse_subzone_mp2019.csv", index_col=0)
    t25 = pd.read_csv(OUT / "landuse_subzone_mp2025.csv", index_col=0)
    order = t25.sort_values("land_ha").index
    fig, (a, b) = plt.subplots(1, 2, figsize=(7.4, 3.6), sharey=True, gridspec_kw={"width_ratios": [1.25, 1]})
    left = np.zeros(len(order))
    groups = list(landuse.ACTIVITY) + ["Transport", "Reserve site"]
    for g in groups:
        v = t25.loc[order, f"share_{g}"].to_numpy()
        a.barh(range(len(order)), v, left=left, color=LU_COLOR[g], height=0.7, edgecolor="white", lw=0.8, label=g)
        left += v
    a.barh(range(len(order)), 1 - left, left=left, color="#f0efec", height=0.7, edgecolor="white", lw=0.8,
           label="Water, utility, other")
    a.set_yticks(range(len(order)))
    a.set_yticklabels([f"{s.title()}  (mix {t25.loc[s, 'mix_index']:.2f})" for s in order], fontsize=6.5)
    a.set_xlim(0, 1)
    a.set_xlabel("share of subzone land, MP2025")
    a.legend(fontsize=5.8, ncol=2, loc="upper center", bbox_to_anchor=(0.5, -0.17), frameon=False)
    y = np.arange(len(order))
    b.barh(y + 0.18, t19.loc[order, "gfa_potential_m2"] / 1e4, height=0.34, color="#9ec5f4", label="MP2019")
    b.barh(y - 0.18, t25.loc[order, "gfa_potential_m2"] / 1e4, height=0.34, color="#1c5cab", label="MP2025")
    b.set_xlabel("permissible GFA (ha)")
    b.legend(fontsize=6.5, frameon=False, loc="lower right")
    b.grid(axis="x", color=GRID, lw=0.6)
    b.set_axisbelow(True)
    for ax in (a, b):
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
    fig.suptitle("Land-use mix and gross floor area potential by subzone", fontsize=9, color=INK, x=0.02,
                 ha="left")
    fig.savefig(FIG / "fig2_landuse_gfa.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


def _dist_panel(ax, oj, col, thr, szj, je, title, lu):
    _base(ax, lu, szj, je, alpha=0.18)
    d = oj[col].to_numpy()
    for lo, hi, c, _ in BANDS:
        lo2, hi2 = (lo, hi) if thr == 800 else (lo * thr / 800, hi * thr / 800)
        m = (d > lo2) & (d <= hi2) if lo2 > 0 else (d <= hi2)
        pts = oj[m]
        ax.scatter(pts.geometry.x, pts.geometry.y, s=1.1, c=c, lw=0, rasterized=True)
    within = (oj.residents[d <= thr].sum() / oj.residents.sum())
    ax.set_title(f"{title}\n{within:.0%} of residents within {thr:,} m", fontsize=7.5, color=INK, loc="left")
    _frame(ax, je, pad=100)


def fig_access(szj, je):
    oj = gpd.read_parquet(WORK / "origins_study.parquet")
    oj = oj[oj.residents > 0.5]  # leave out the near-empty industrial subzones (10 residents each)
    lu = _landuse_clip(je)
    panels = [("d_mrt_exit", "MRT exit today"), ("d_mrt_future", "Rail incl. JRL / CRL stations (MP2025)"),
              ("d_hawker", "Hawker centre"), ("d_community_club", "Community club"),
              ("d_park", "NParks-managed park"), ("d_park_zoned", "Any land zoned Park (MP2025)")]
    fig, axes = plt.subplots(2, 3, figsize=(7.6, 5.6))
    for ax, (col, title) in zip(axes.ravel(), panels):
        _dist_panel(ax, oj, col, THRESHOLD_M.get(col[2:], 800), szj, je, title, lu)
    handles = [Patch(color=c, label=l) for *_, c, l in BANDS]
    fig.legend(handles=handles, loc="lower center", ncol=4, fontsize=7, frameon=False,
               title="walking distance on the OSM path network (threshold 800 m)", title_fontsize=7)
    fig.suptitle("Walking distance from homes to the nearest facility, Jurong East residents (GHS 2025)",
                 fontsize=9, color=INK, x=0.02, ha="left")
    fig.subplots_adjust(wspace=0.03, hspace=0.18, bottom=0.08)
    fig.savefig(FIG / "fig3_access.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


def fig_gaps(szj, je):
    oj = gpd.read_parquet(WORK / "origins_study.parquet")
    oj = oj[oj.residents > 0.5]
    lu = _landuse_clip(je)
    kinds = ["hawker", "clinic", "community_club", "park_zoned", "primary_school"]
    n = sum((oj[f"d_{k}"] > THRESHOLD_M[k]).astype(int) for k in kinds)
    ramp = ["#cde2fb", "#9ec5f4", "#5598e7", "#256abf", "#104281", "#0d366b"]
    fig, (a, b) = plt.subplots(1, 2, figsize=(7.4, 3.5), gridspec_kw={"width_ratios": [1.3, 1]})
    _base(a, lu, szj, je, alpha=0.15)
    for i in range(6):
        p = oj[n == i]
        a.scatter(p.geometry.x, p.geometry.y, s=1.2, c=ramp[i], lw=0, rasterized=True)
    _labels(a, szj, min_km2=0.6)
    _frame(a, je, pad=100)
    a.legend(handles=[Patch(color=ramp[i], label=str(i)) for i in range(6)], title="facilities out of reach",
             fontsize=6.5, title_fontsize=6.5, loc="lower left", frameon=True, framealpha=0.9, edgecolor=GRID,
             ncol=3)
    a.set_title("How many of 5 neighbourhood facilities are beyond the threshold", fontsize=7.5, color=INK,
                loc="left")
    g = pd.read_csv(OUT / "gaps_subzone_residents_beyond_threshold.csv", index_col=0)
    g = g[g.residents >= 1000].sort_values("residents")
    labels = {"hawker": "Hawker", "community_club": "Comm. club", "primary_school": "Primary sch. (1 km)",
              "mrt_exit": "MRT exit"}
    cols = list(labels)
    y = np.arange(len(g))
    h = 0.8 / len(cols)
    colors = ["#2a78d6", "#eb6834", "#1baf7a", "#4a3aa7"]
    for i, k in enumerate(cols):
        b.barh(y + (i - 1.5) * h, g[k] / 1e3, height=h * 0.92, color=colors[i], label=labels[k])
    b.barh(y, g.residents / 1e3, height=0.86, facecolor="none", edgecolor=MUTED, lw=0.7, label="All residents")
    b.set_yticks(y)
    b.set_yticklabels([s.title() for s in g.index], fontsize=7)
    b.set_xlabel("residents beyond the threshold, thousands")
    b.legend(fontsize=6, frameon=False, loc="upper center", bbox_to_anchor=(0.45, -0.17), ncol=3)
    b.grid(axis="x", color=GRID, lw=0.6)
    b.set_axisbelow(True)
    for s in ("top", "right"):
        b.spines[s].set_visible(False)
    fig.savefig(FIG / "fig4_gaps.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


def fig_ratios():
    t = pd.read_csv(OUT / "planning_area_indicators.csv", index_col=0)
    rows = [("within_bus_stop", "Bus stop, 400 m"), ("within_mrt_exit", "MRT exit, 800 m"),
            ("within_mrt_future", "Rail incl. stations not yet open"), ("within_park", "NParks park, 800 m"),
            ("within_park_zoned", "Zoned park, 800 m"), ("within_hawker", "Hawker centre, 800 m"),
            ("within_clinic", "CHAS clinic, 800 m"), ("within_community_club", "Community club, 800 m"),
            ("within_primary_school", "Primary school, 1 km")]
    fig, ax = plt.subplots(figsize=(7.0, 3.6))
    for i, (c, lab) in enumerate(rows[::-1]):
        v = t[c].to_numpy()
        ax.scatter(v, np.full(len(v), i) + np.random.default_rng(i).uniform(-0.12, 0.12, len(v)), s=10,
                   color="#b7d3f6", lw=0)
        med = np.median(v)
        ax.plot([med, med], [i - 0.3, i + 0.3], color=INK2, lw=1.5)
        je = t.loc[STUDY_AREA, c]
        ax.scatter([je], [i], s=46, color="#eb6834", edgecolor="white", lw=1.2, zorder=3)
        ax.text(1.02, i, f"{je:.0%}  (median {med:.0%})", va="center", fontsize=6.8, color=INK,
                transform=ax.get_yaxis_transform())
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([l for _, l in rows[::-1]], fontsize=7)
    ax.set_xlim(0, 1)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.set_xlabel("share of residents within walking threshold")
    ax.grid(axis="x", color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.legend(handles=[Line2D([], [], marker="o", color="#eb6834", lw=0, label="Jurong East"),
                       Line2D([], [], marker="o", color="#b7d3f6", lw=0, label=f"Other planning areas (n={len(t) - 1})"),
                       Line2D([], [], color=INK2, lw=1.5, label="Median")],
              fontsize=6.5, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=3)
    ax.set_title("Jurong East against planning areas with at least 10,000 residents", fontsize=9, color=INK,
                 loc="left")
    fig.savefig(FIG / "fig5_benchmark.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


def fig_scenario(szj, je, amen):
    s = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))["scenario"]
    lu = _landuse_clip(je)
    fig, (a, b) = plt.subplots(1, 2, figsize=(7.6, 3.9), gridspec_kw={"width_ratios": [1, 1.0], "wspace": 0.55})
    _base(a, lu, szj, je, alpha=0.35)
    for p in sorted(WORK.glob("scenario_plot*.parquet")):
        g = gpd.read_parquet(p)
        g.plot(ax=a, facecolor="#eb6834", edgecolor=INK, alpha=0.85, lw=0.8)
        c = g.geometry.iloc[0].representative_point()
        a.text(c.x, c.y, g["plot"].iloc[0].replace("plot", "P"), fontsize=7, fontweight="bold", color="white",
               ha="center", va="center")
    near = amen[amen.kind.isin(["hawker", "community_club"]) & (amen.distance(je.union_all()) < 1200)]
    for k, m in (("hawker", "^"), ("community_club", "D")):
        q = near[near.kind == k]
        a.scatter(q.geometry.x, q.geometry.y, marker=m, s=22, color=INK, edgecolor="white", lw=0.6, zorder=3)
    a.legend(handles=[Line2D([], [], marker="^", color=INK, lw=0, label="Hawker centre"),
                      Line2D([], [], marker="D", color=INK, lw=0, markersize=4, label="Community club"),
                      Patch(color="#eb6834", label="Residential land, no residents in 2025")],
             fontsize=6, loc="lower left", frameon=True, framealpha=0.9, edgecolor=GRID)
    _frame(a, je, pad=100)
    a.set_title("Zoned residential land not yet occupied", fontsize=7.5, color=INK, loc="left")
    rows = []
    for k, lab in (("hawker", "hawker"), ("clinic", "clinic"), ("community_club", "CC")):
        lc = pd.read_csv(OUT / f"scenario_load_{k}.csv").head(2)
        for _, r in lc.iterrows():
            short = r["name"].split("(")[-1].rstrip(")") if "(" in r["name"] else r["name"]
            rows.append((f"{short.title()[:30]} ({lab})", r.before, r.after, r.after_intensified))
    y = np.arange(len(rows))[::-1]
    b.barh(y, [r[3] / 1e3 for r in rows], height=0.62, color="#f6c6a9", label="+ new residents, intensified")
    b.barh(y, [r[2] / 1e3 for r in rows], height=0.62, color="#eb6834", label="+ new residents, central")
    b.barh(y, [r[1] / 1e3 for r in rows], height=0.62, color="#52514e", label="Existing residents")
    b.set_yticks(y)
    b.set_yticklabels([r[0] for r in rows], fontsize=6)
    b.set_xlabel("residents nearest to it (thousands)")
    b.legend(fontsize=6, frameon=False, loc="upper center", bbox_to_anchor=(0.4, -0.17), ncol=2)
    b.grid(axis="x", color=GRID, lw=0.6)
    b.set_axisbelow(True)
    for sp in ("top", "right"):
        b.spines[sp].set_visible(False)
    b.set_title("Nearest-facility load if all four plots are built\n"
                f"({s['combined_residents_central']:,.0f}"
                f" to {s['combined_residents_intensified']:,.0f} new residents)", fontsize=7.5, color=INK, loc="left")
    fig.savefig(FIG / "fig6_scenario.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


def make_all():
    FIG.mkdir(parents=True, exist_ok=True)
    from .pipeline import rail_future
    sz, szj, je = _ctx()
    amen, _ = amenities.load_all(RAW, CRS)
    fut = rail_future(je.geometry.iloc[0])
    fig_context(sz, szj, je, amen, fut)
    fig_landuse()
    fig_access(szj, je)
    fig_gaps(szj, je)
    fig_ratios()
    fig_scenario(szj, je, amen)
