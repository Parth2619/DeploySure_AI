"""Checks that the demo can run on this computer:  python scripts/verify_setup.py"""
import importlib.util
import inspect
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ["app/main.py", "app/release_analyzer.py", "app/test_selector.py", "app/test_runner.py", "app/risk_scorer.py",
         "app/deployment_gate.py", "app/critic.py", "demo_app/pricing.py", "baseline/pricing.py",
         "bug_variants/pricing_buggy.py", "tests/test_pricing.py", "tests/test_deployment_gate.py", "pytest.ini"]


def _load(path: Path):
    spec = importlib.util.spec_from_file_location("_check_" + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _signatures(module) -> dict:
    return {n: str(inspect.signature(f)) for n, f in inspect.getmembers(module, inspect.isfunction) if f.__module__ == module.__name__}


def main() -> int:
    problems = []
    if sys.version_info < (3, 9):
        problems.append(f"Python 3.9 or newer is needed, this is {sys.version.split()[0]}")
    if importlib.util.find_spec("pytest") is None:
        problems.append("pytest is not installed: python -m pip install -r requirements.txt")
    problems += [f"missing file: {f}" for f in FILES if not (ROOT / f).is_file()]
    if not problems:
        base, buggy = _signatures(_load(ROOT / "baseline/pricing.py")), _signatures(_load(ROOT / "bug_variants/pricing_buggy.py"))
        if base != buggy:
            problems.append(f"the buggy file is not a drop-in replacement: {base} vs {buggy}")
        found = subprocess.run([sys.executable, "-m", "pytest", "tests/test_pricing.py", "--collect-only", "-q", "-p", "no:cacheprovider"],
                               cwd=ROOT, capture_output=True, text=True, timeout=60)
        if found.returncode != 0:
            problems.append("the pricing tests cannot be collected:\n" + found.stdout[-400:])
    if problems:
        print("Setup NOT ready:")
        print("\n".join("  - " + p for p in problems))
        return 1
    print("Setup OK: Python, pytest, all files and the pricing tests are available.")
    print("The buggy replacement has the same functions and signatures as the original.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
