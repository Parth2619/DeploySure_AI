"""Run a version from the terminal: python -m deploysure.cli v2.2 [project_id] [--json]"""
import json
import sys

from deploysure.api import stream_release_validation
from deploysure.tools.code_reader import DEFAULT_PROJECT


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    if len(args) not in (1, 2):
        print("usage: python -m deploysure.cli <version> [project_id] [--json]")
        return 2
    as_json = "--json" in argv
    project = args[1] if len(args) == 2 else DEFAULT_PROJECT
    try:
        for event in stream_release_validation(args[0], project):
            if event["node"] == "final":
                report = event["final_report"]
                print(json.dumps(report, indent=2) if as_json else _summary(report))
            elif not as_json:
                line = event["state_update"].get("trace", [""])[0]
                print(f"[{event['node']:<15}] done  {line}", flush=True)
    except (ValueError, FileNotFoundError) as err:
        print(f"error: {err}")
        return 1
    return 0


def _summary(r: dict) -> str:
    tests = r["test_results"]
    return (f"\nRelease {r['release_id']}: {r['decision']}\n"
            f"  reason:  {r['decision_reason']}\n"
            f"  risk:    {r['risk_score']} ({r['risk_level']})\n"
            f"  tests:   {tests['passed']} passed, {tests['failed']} failed of {tests['total']}\n"
            f"  critic:  {r['critic_result']} after {r['retry_count']} retry(ies). {r['critic_reason']}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
