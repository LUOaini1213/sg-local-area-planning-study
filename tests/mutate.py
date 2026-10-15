"""Mutation check: every deliberate bug below must make the test suite fail.

Procedure:
  1. run the untouched suite; it must pass and collect at least one test (a collection error is not a 'kill');
  2. for each mutant, assert the original snippet occurs exactly once, apply it, check the module still compiles,
     run pytest, restore the file;
  3. exit 1 if any mutant survives (tests still pass) or any snippet is missing.
Run: python tests/mutate.py            (add -v to see pytest output for survivors, --only 3,7 to run a subset)
"""
import py_compile
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "lap"

MUTANTS = [
    ("network.py", 'return tags.get("foot") in ("yes", "designated", "permissive")', "return True"),
    ("network.py", 'if tags.get("foot") == "no":', 'if tags.get("foot") == "never":'),
    ("network.py", "keep = np.flatnonzero(lab == big)", "keep = np.arange(n)"),
    ("network.py", "off = np.maximum(np.asarray(source_offsets, dtype=float), EPS)",
     "off = np.full(len(source_nodes), EPS)"),
    ("network.py", "node_dist = self.nearest_distance(dn, dd, limit=limit)\n        on, od = self.snap(origin_xy)\n"
                   "        return od + node_dist[on]",
     "node_dist = self.nearest_distance(dn, dd, limit=limit)\n        on, od = self.snap(origin_xy)\n"
     "        return node_dist[on]"),
    ("network.py", 'ed["length_m"] = np.hypot(pu[:, 0] - pv[:, 0], pu[:, 1] - pv[:, 1])',
     'ed["length_m"] = np.abs(pu[:, 0] - pv[:, 0])'),
    ("access.py", "return float(weight[dist <= threshold].sum() / tot)", "return float(weight[dist < threshold].sum() / tot)"),
    ("access.py", "dist[k].to_numpy() > t for k, t", "dist[k].to_numpy() >= t for k, t"),
    ("access.py", "lab[virt] = par[virt] - (n + 1)", "lab[virt] = par[virt] - n"),
    ("access.py", "return np.r_[inner, bn], np.r_[np.zeros(len(inner)), bd]",
     "return np.r_[inner, bn], np.r_[np.zeros(len(inner)), np.zeros(len(bd))]"),
    ("access.py", "geometry=polys.buffer(edge_m)", "geometry=polys.buffer(0)"),
    ("access.py", 'w = origins.loc[idx, "residents"].to_numpy()', "w = np.ones(len(idx))"),
    ("access.py", "weights=np.asarray(weights)[olab >= 0]", "weights=None"),
    ("access.py", "out[i] = w[tot <= limit].sum()", "out[i] = w[tot < limit].sum()"),
    ("access.py", "return float(np.median(n[ok] / s[ok]))", "return float(np.mean(n[ok] / s[ok]))"),
    ("landuse.py", 'return v if v > 0 else float("nan")', "return v"),
    ("landuse.py", "/ math.log(len(ACTIVITY))))", "/ math.log(len(ACTIVITY) + 1)))"),
    ("landuse.py", 'cut["gfa_m2"] = cut.area_m2 * cut.gpr', 'cut["gfa_m2"] = cut.area_m2 * cut.gpr.fillna(1.0)'),
    ("population.py", "rec[band] = sum(vals[k] for k in keys)", "rec[band] = vals[keys[0]]"),
    ("population.py", 'g = g.where(lu.GPR.astype(str).str.strip() != "LND", 1.0)', "g = g"),
    ("population.py", 'cut["w"] = cut.w * cut.area / cut.a0', 'cut["w"] = cut.w'),
    ("population.py", "/ n_in.loc[pts.poly].to_numpy()", ""),
    ("ratios.py", '"primary_school": "age_5_14"', '"primary_school": "residents"'),
    ("ratios.py", "ranked = pool[c].rank(ascending=not better_high", "ranked = pool[c].rank(ascending=better_high"),
    ("ratios.py", "pool = table[table.residents >= min_residents]", "pool = table"),
    ("scenario.py", "return dwellings, dwellings * persons_per_hh", "return dwellings, dwellings"),
    ("scenario.py", "ok = (r >= min_residents) & (g > 0)", "ok = g > 0"),
    ("scenario.py", "(after - base) / np.where(base > 0, base, 1) * 100", "(after - base) / np.where(base > 0, base, 1)"),
]


def pytest_run():
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", str(ROOT / "tests")],
                       cwd=ROOT, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def main(verbose=False):
    code, out = pytest_run()
    m = re.search(r"(\d+) passed", out)
    if code != 0 or not m:
        print("unmutated suite does not pass cleanly; mutation check aborted\n", out[-2000:])
        return 1
    print(f"baseline: {m.group(1)} tests pass")
    survivors, missing = [], []
    only = None
    if "--only" in sys.argv:
        only = {int(x) for x in sys.argv[sys.argv.index("--only") + 1].split(",")}
    for i, (fname, old, new) in enumerate(MUTANTS, 1):
        if only and i not in only:
            continue
        path = SRC / fname
        text = path.read_text(encoding="utf-8")
        if text.count(old) != 1:
            missing.append((i, fname, old))
            print(f"[{i:02d}] {fname}: snippet found {text.count(old)} times - SKIPPED (counts as failure)")
            continue
        try:
            path.write_text(text.replace(old, new), encoding="utf-8")
            py_compile.compile(str(path), doraise=True)
            code, out = pytest_run()
        finally:
            path.write_text(text, encoding="utf-8")
        killed = code != 0 and ("failed" in out or "error" in out.lower())
        print(f"[{i:02d}] {fname}: {'killed' if killed else 'SURVIVED'}  ({old[:60]!r})")
        if not killed:
            survivors.append((i, fname, old))
            if verbose:
                print(out[-1500:])
    total = len(only) if only else len(MUTANTS)
    print(f"\n{total - len(survivors) - len(missing)}/{total} mutants killed")
    return 1 if (survivors or missing) else 0


if __name__ == "__main__":
    sys.exit(main("-v" in sys.argv))
