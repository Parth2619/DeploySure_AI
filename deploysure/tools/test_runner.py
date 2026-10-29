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


def is_critical_file(file: str, critical_modules) -> bool:
    """test_payment.py counts as critical when 'payment' is a critical module."""
    return Path(file).stem.removeprefix("test_") in critical_modules and Path(file).stem.startswith("test_")


class CollectionError(Exception):
    """pytest could not even list the tests, for example a test file fails to import."""


def collect_tests(release_dir: Path, timeout: int = 60, critical_modules=frozenset()) -> list[dict]:
    """Lists every test id and whether it is critical (marker or critical module)."""
    listing = _pytest(release_dir, ["--collect-only", "-q"], timeout)
    # Exit 0 = collected, 5 = no tests at all. Anything else (2 = a test file failed to import) must not be ignored,
    # or the broken file's tests silently vanish and the release looks safe.
    if listing.returncode not in (0, 5):
        raise CollectionError(f"pytest could not collect the tests (exit {listing.returncode}): "
                              f"{(listing.stdout + listing.stderr).strip()[-300:]}")
    all_ids = parse_collect(listing.stdout)
    marked = set(parse_collect(_pytest(release_dir, ["--collect-only", "-q", "-m", "critical"], timeout).stdout))
    return [{"id": i, "critical": i in marked or is_critical_file(i.split("::")[0], critical_modules)} for i in all_ids]


def parse_junit(xml_path: Path, critical_modules=frozenset(), critical_ids=frozenset()) -> list[dict]:
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
        test_id = f"{file}::{case.get('name')}"
        critical = props.get("critical") == "True" or test_id in critical_ids or is_critical_file(file, critical_modules)
        results.append({"id": test_id, "status": status, "critical": critical})
    return results


def run_tests(release_dir: Path, test_ids: list[str] | None = None, timeout: int = DEFAULT_TIMEOUT,
              critical_modules=frozenset(), critical_ids=frozenset()) -> dict:
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
    results = parse_junit(xml_path, critical_modules, critical_ids)
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
