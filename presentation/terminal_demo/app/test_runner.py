"""Stage 3: run the selected tests with real pytest and read the report.

A failed assertion is a regression (evidence about the code). An error, a crash or a missing file is an
execution problem (no usable evidence). The two are kept apart because the gate treats them differently.
"""
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

TIMEOUT_SECONDS = 120
CRITICAL_PREFIX = "test_critical_"


def is_critical(name: str) -> bool:
    return name.startswith(CRITICAL_PREFIX)


def _empty(problem: str) -> dict:
    return {"passed": [], "failed": [], "errors": [], "critical_failed": [], "messages": {}, "total": 0, "problem": problem}


def run_tests(root: Path, selected: list[dict]) -> dict:
    root = Path(root)
    missing = [t["file"] for t in selected if not t["exists"]]
    if missing:
        return _empty("selected test file not found: " + ", ".join(missing))
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.xml"
        command = [sys.executable, "-m", "pytest", *[t["file"] for t in selected], "-q", "--tb=line",
                   f"--junitxml={report}", "-p", "no:cacheprovider"]
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}  # a file swapped during the demo must never run from a stale cache
        try:
            done = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            return _empty(f"the test run did not finish within {TIMEOUT_SECONDS} seconds")
        if not report.is_file():
            return _empty(f"pytest produced no report (exit code {done.returncode})")
        return _read_report(report, done.returncode)


def _read_report(report: Path, exit_code: int) -> dict:
    result = _empty("")
    for case in ET.parse(report).getroot().iter("testcase"):
        name = case.get("name", "?")
        failure, error = case.find("failure"), case.find("error")
        if failure is not None:
            result["failed"].append(name)
            result["messages"][name] = (failure.get("message") or "").splitlines()[0][:120] if failure.get("message") else "assertion failed"
        elif error is not None:
            result["errors"].append(name)
            result["messages"][name] = (error.get("message") or "error")[:120]
        elif case.find("skipped") is None:
            result["passed"].append(name)
    result["critical_failed"] = [n for n in result["failed"] if is_critical(n)]
    result["total"] = len(result["passed"]) + len(result["failed"]) + len(result["errors"])
    if result["errors"]:
        result["problem"] = f"{len(result['errors'])} test(s) could not run (error, not a failed assertion): {result['errors'][0]}"
    elif result["total"] == 0:
        result["problem"] = f"no tests were executed (pytest exit code {exit_code})"
    elif exit_code not in (0, 1):
        result["problem"] = f"pytest exited with code {exit_code}"
    return result
