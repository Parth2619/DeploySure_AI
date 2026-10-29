"""Check a whole app from the terminal: python -m deploysure.app_cli <repo folder> <old ref> <new ref> [--json]"""
import json
import sys

from deploysure.app_api import AppRequestError, stream_app_validation


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 3:
        print("usage: python -m deploysure.app_cli <repo folder> <old ref> <new ref> [--json]")
        return 2
    try:
        for event in stream_app_validation(args[0], args[1], args[2]):
            if event["node"] == "final":
                print(json.dumps(event["final_report"], indent=2) if "--json" in argv else _summary(event["final_report"]))
            elif "--json" not in argv:
                print(f"[{event['node']:<17}] done  {(event['state_update'].get('trace') or [''])[0][:150]}", flush=True)
    except AppRequestError as err:
        print(f"error: {err}")
        return 1
    return 0


def _summary(r: dict) -> str:
    v = r["layer_verdict"]
    return (f"\n{r['old']} -> {r['new']}: {r['decision']}\n"
            f"  reason:        {r['decision_reason']}\n"
            f"  faulty layer:  {v['primary']} ({v['confidence']} confidence)\n"
            + "".join(f"                 - {reason}\n" for reason in v["reasons"])
            + f"  risk:          {r['risk_score']} ({r['risk_level']})\n"
            f"  API checks:    {r['api_summary']['regression']} regression(s)    browser: {r['browser_summary']['regression']} regression(s)\n"
            f"  critic:        {r['critic_result']} after {r['retry_count']} retry(ies)")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
