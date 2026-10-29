"""Stage 2: pick the tests that matter for the changed component."""
from pathlib import Path

CORE = ("tests/test_pricing.py", "core regression suite, runs for every release")
BY_COMPONENT = {"pricing": ("tests/test_pricing.py", "covers demo_app/pricing.py")}


def select_tests(components: list[str], root: Path) -> list[dict]:
    wanted = [CORE] + [BY_COMPONENT[c] for c in components if c in BY_COMPONENT]
    chosen: dict[str, str] = {}
    for file, reason in wanted:  # the same file asked for twice is listed once, with every reason
        chosen[file] = f"{chosen[file]}; {reason}" if file in chosen else reason
    return [{"file": f, "reason": r, "exists": (Path(root) / f).is_file()} for f, r in chosen.items()]
