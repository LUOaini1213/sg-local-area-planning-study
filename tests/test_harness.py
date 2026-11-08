"""The mutation check's verdict rule: only a test failure is a kill; collection, import or setup errors are not."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("mutate", Path(__file__).resolve().parent / "mutate.py")
mutate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mutate)

# pytest -q tails, as mutate.pytest_run() captures them
PASS = "........ [100%]\n89 passed in 5.10s\n"
FAIL = "F\n=== short test summary info ===\nFAILED tests/test_core.py::test_x - assert 1 == 2\n" \
       "!!!!!!! stopping after 1 failures !!!!!!!\n1 failed, 12 passed in 2.31s\n"
COLLECT_ERROR = "=== ERRORS ===\n___ ERROR collecting tests/test_core.py ___\nRuntimeError: boom\n" \
                "=== short test summary info ===\nERROR tests/test_core.py - RuntimeError: boom\n" \
                "!!!!!!! Interrupted: 1 error during collection !!!!!!!\n1 error in 1.02s\n"
SETUP_ERROR = "E\n=== ERRORS ===\nERROR at setup of test_y\n1 error, 3 passed in 0.80s\n"
# a failure text that merely mentions 'error' must still count as a failure
FAIL_MENTIONING_ERROR = "F\nE   AssertionError: error rate too high\n1 failed, 4 passed, 2 warnings in 1.10s\n"


@pytest.mark.parametrize("code,out,verdict", [
    (0, PASS, "survived"),
    (1, FAIL, "killed"),
    (1, FAIL_MENTIONING_ERROR, "killed"),
    (2, COLLECT_ERROR, "invalid"),
    (1, COLLECT_ERROR, "invalid"),          # whatever the exit code, an error is not a kill
    (1, SETUP_ERROR, "invalid"),
    (1, "", "invalid"),                     # no summary line at all
    (0, "no tests ran in 0.01s\n", "invalid"),
])
def test_classify(code, out, verdict):
    assert mutate.classify(code, out) == verdict


def test_summary_counts():
    assert mutate.summary_counts(FAIL) == {"failed": 1, "passed": 12}
    assert mutate.summary_counts(COLLECT_ERROR) == {"error": 1}
    assert mutate.summary_counts(FAIL_MENTIONING_ERROR) == {"failed": 1, "passed": 4, "warnings": 2}
