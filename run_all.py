"""One command: python run_all.py  (add --fetch to download the inputs first).

Steps: fetch inputs -> walk network -> resident origins -> walking distances -> land use, coverage, ratios, gaps
-> intensification scenario -> figures -> planning brief (markdown tables refreshed, PDF rebuilt).
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from lap import fetch, figures, pipeline, report  # noqa: E402

if __name__ == "__main__":
    t0 = time.time()
    if "--fetch" in sys.argv:
        fetch.main()
    summary = pipeline.run()
    figures.make_all()
    report.build()
    print(f"done in {time.time() - t0:.0f} s; study area residents {summary['residents_study_area']:,.0f}")
