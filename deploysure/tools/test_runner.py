"""Runs a release's own pytest suite in a subprocess and parses the junit XML."""
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET  # XML comes from our own pytest run, not untrusted input
from pathlib import Path

from .code_reader import release_path

DEFAULT_TIMEOUT = 120


def _pytest(release_dir: Path, args: list[str], timeout: int) -> subprocess.CompletedProcess:
    # shortcut: timeout only kills pytest itself, upgrade to taskkill /T if tests ever spawn children.
    return subprocess.run([sys.executable, "-m", "pytest", *args], cwd=release_dir, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=timeout)


def parse_collect(output: str) -> list[str]:
    """Pulls test ids out of 'pytest --collect-only -q' output."""
    return [line.strip() for line in output.splitlines() if "::" in line]


def collect_tests(release_dir: Path, timeout: int = 60) -> list[dict]:
    """Lists every test id and whether it is marked critical."""
    all_ids = parse_collect(_pytest(release_dir, ["--collect-only", "-q"], timeout).stdout)
    critical = set(parse_collect(_pytest(release_dir, ["--collect-only", "-q", "-m", "critical"], timeout).stdout))
    return [{"id": i, "critical": i in critical} for i in all_ids]


def parse_junit(xml_path: Path) -> list[dict]:
    results = []
    for case in ET.parse(xml_path).getroot().iter("testcase"):
        file = case.get("classname", "").split(".")[0] + ".py"
        props = {p.get("name"): p.get("value") for p in case.iter("property")}
        if case.find("failure") is not None or case.find("error") is not None:
            status = "failed"
        elif case.find("skipped") is not None:
            status = "skipped"
        else:
            status = "passed"
        results.append({"id": f"{file}::{case.get('name')}", "status": status, "critical": props.get("critical") == "True"})
    return results


def run_tests(release_dir: Path, test_ids: list[str] | None = None, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Runs the given tests (all if None). 'error' is set when pytest could not run them."""
    xml_path = Path(tempfile.mkdtemp()) / "result.xml"
    args = ["-q", "--tb=no", f"--junitxml={xml_path}", *(test_ids or [])]
    empty = {"total": 0, "passed": 0, "failed": 0, "results": [], "failed_tests": [], "failed_critical": [], "error": None}
    try:
        proc = _pytest(release_dir, args, timeout)
    except subprocess.TimeoutExpired:
        return {**empty, "error": f"timeout after {timeout}s"}
    # Exit 0 = all passed, 1 = some failed. Anything else means pytest itself could not run the tests.
    if proc.returncode not in (0, 1) or not xml_path.exists():
        return {**empty, "error": f"pytest exit code {proc.returncode}: {proc.stdout.strip()[-300:]}"}
    results = parse_junit(xml_path)
    failed = [r for r in results if r["status"] == "failed"]
    return {
        **empty,
        "total": len(results),
        "passed": sum(r["status"] == "passed" for r in results),
        "failed": len(failed),
        "results": results,
        "failed_tests": [r["id"] for r in failed],
        "failed_critical": [r["id"] for r in failed if r["critical"]],
    }


if __name__ == "__main__":
    out = run_tests(release_path(sys.argv[1]))
    print(f"{sys.argv[1]}: total={out['total']} passed={out['passed']} failed={out['failed']} error={out['error']}")
    print("failed:", out["failed_tests"], "critical:", out["failed_critical"])
