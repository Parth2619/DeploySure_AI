"""Check writer: asks the AI for HTTP checks that would reveal a regression in a change, then adds deterministic probes.

The AI's checks come first because they target the change. The probes (every plain GET, and each write endpoint with
sample bodies built from its model) always follow, so coverage never depends on the AI alone. Every check is validated
against the endpoints of the OLD version before it is allowed to run.
"""
from pathlib import Path

from deploysure.models import llm
from deploysure.models.llm import ask
from deploysure.tools import git_tool
from deploysure.tools.api_checks import ApiChecks, fallback_checks, validate_checks
from deploysure.tools.app_scan import scan_change
from deploysure.tools.browser_checks import BrowserChecks, smoke_checks, validate_browser_checks

# Groq's free tier allows about 8,000 tokens a minute and the answer schema is added on top, so keep this short.
MAX_PROMPT_CHARS = 6500
BROWSER_PATCH_CHARS = 2000
PATCH_CHARS_PER_FILE = 1200
PATCH_CHARS_TOTAL = 2800
CODE_LAYERS = ("backend", "frontend")


FOCUS_TEXT = {
    "api_contract": "the routes and fields the page and the backend share",
    "page_behavior": "what the page shows after clicks",
    "data_values": "numbers the API calculates: vary the inputs",
    "config_and_dependencies": "behavior that depends on settings or packages",
}


def _guidance(focus: list[str] | tuple, hint: str) -> list[str]:
    """Lines that carry what other agents told the Check writer: the Planner's focus and, in a second round, the Differential run's complaint."""
    lines = []
    if focus:
        lines += ["PRIORITY (from the Planner):", *[f"- {name}: {FOCUS_TEXT.get(name, name)}" for name in focus]]
    if hint:
        lines += ["PROBLEM WITH YOUR PREVIOUS CHECKS (from the Differential run):", hint]
    return lines


def _endpoint_line(e: dict) -> str:
    return f"{e['method']} {e['path']}  takes: {', '.join(e['request_fields']) or '-'}  returns: {', '.join(e['response_fields']) or '-'}"


def build_prompt(repo: Path, scan: dict, focus: list[str] | tuple = (), hint: str = "") -> str:
    changed = [f"- {layer}: {', '.join(paths)}" for layer, paths in scan["layers"].items() if layer in (*CODE_LAYERS, "config", "dependencies")]
    functions = [f"- {path}: {', '.join(names)}" for path, names in scan["changed_functions"].items()]
    issues = [f"- {i['kind']}: " + ", ".join(f"{k}={v}" for k, v in i.items() if k != "kind") for i in scan["contract_issues"]]
    endpoint_changes = [f"- {c['endpoint']} {c['kind']}: {', '.join(c['fields'])}" for c in scan["endpoint_changes"]]
    patches, room = [], PATCH_CHARS_TOTAL
    for layer in CODE_LAYERS:
        for path in scan["layers"].get(layer, []):
            if room <= 0:
                break
            patch = git_tool.diff_patch(repo, scan["old"], scan["new"], path, max_chars=min(PATCH_CHARS_PER_FILE, room))
            patches.append(patch)
            room -= len(patch)
    parts = [
        "You test a web app after a code change. Propose up to 6 HTTP checks against the running app that would reveal a regression.",
        "Use only the endpoints listed. Vary the inputs: quantities of 1 and more than 1, different ids, empty lists, unknown ids.",
        "Paths must be concrete (use 1, not {id}). Do not guess expected numbers: leave expect_json out unless the code makes the value certain.",
        'Reply as JSON: {"checks": [{"name": "...", "method": "GET|POST|PUT|PATCH|DELETE", "path": "/...", "json_body": {...}, "expect_status": 200, "reason": "..."}]}',
        *_guidance(focus, hint),
        "ENDPOINTS", *[_endpoint_line(e) for e in scan["old_map"]["endpoints"]],
        "CHANGE", *changed, *(["changed functions:", *functions] if functions else []),
        *(["endpoint changes:", *endpoint_changes] if endpoint_changes else []),
        *(["problems between page and API:", *issues] if issues else []),
        "DIFF", *patches,
    ]
    return "\n".join(parts)[:MAX_PROMPT_CHARS]


def build_browser_prompt(repo: Path, scan: dict, focus: list[str] | tuple = (), hint: str = "") -> str:
    """What the AI needs to write browser scenarios: the page's selectors, the API calls it makes, and what changed in it."""
    new_map = scan["new_map"]
    calls = sorted({f"{c['method']} {c['path']}" for c in new_map["frontend_calls"]})
    changed = [f"- {layer}: {', '.join(paths)}" for layer, paths in scan["layers"].items() if layer in (*CODE_LAYERS, "config")]
    issues = [f"- {i['kind']}: " + ", ".join(f"{k}={v}" for k, v in i.items() if k != "kind") for i in scan["contract_issues"]]
    patches, room = [], BROWSER_PATCH_CHARS
    for path in scan["layers"].get("frontend", []):
        if room > 0:
            patch = git_tool.diff_patch(repo, scan["old"], scan["new"], path, max_chars=room)
            patches.append(patch)
            room -= len(patch)
    parts = [
        "You test a web page after a code change. Propose up to 3 browser scenarios of at most 10 steps each.",
        "Steps: goto (value is a path such as /), click (selector), fill (selector and value), read (selector: records the texts of the matching elements), wait (value in milliseconds, at most 2000).",
        "Read the elements the change may affect, and wait after a click that calls the API. Use only the selectors listed.",
        'Reply as JSON: {"checks": [{"name": "...", "reason": "...", "steps": [{"action": "goto", "value": "/"}, {"action": "click", "selector": "#id"}]}]}',
        *_guidance(focus, hint),
        "SELECTORS", ", ".join(new_map["selectors"][:60]),
        "PAGE CALLS", *calls,
        "CHANGE", *changed, *(["problems between page and API:", *issues] if issues else []),
        "DIFF", *patches,
    ]
    return "\n".join(parts)[:MAX_PROMPT_CHARS]


def write_browser_checks(repo: Path, scan: dict, focus: list[str] | tuple = (), hint: str = "") -> dict:
    """AI scenarios first, then the generic smoke scenario. Unsafe or broken scenarios are dropped with the reason."""
    answer, fell_back = ask(build_browser_prompt(repo, scan, focus, hint), BrowserChecks, task="browser_checks", default={"checks": []})
    ai_checks, dropped = validate_browser_checks(answer["checks"])
    checks, _ = validate_browser_checks(ai_checks + smoke_checks())
    note = ""
    if fell_back:
        note = llm.fallback_note("running the generic smoke scenario only")
    elif not ai_checks:
        note = "the AI proposed no usable scenario, so only the smoke scenario runs"
    return {"checks": checks, "dropped": dropped, "source": "ai+smoke" if ai_checks else "smoke", "note": note}


def write_checks(repo: Path, old: str, new: str, scan: dict | None = None, focus: list[str] | tuple = (), hint: str = "") -> dict:
    scan = scan or scan_change(repo, old, new)
    endpoints = scan["old_map"]["endpoints"]
    answer, fell_back = ask(build_prompt(repo, scan, focus, hint), ApiChecks, task="api_checks", default={"checks": []})
    ai_checks, dropped = validate_checks(answer["checks"], endpoints)
    checks, _ = validate_checks(ai_checks + fallback_checks(endpoints), endpoints)  # duplicates and extras are removed here
    note = ""
    if fell_back:
        note = llm.fallback_note("probing endpoints with sample bodies")
    elif not ai_checks:
        note = "the AI proposed no usable check, so only the probes run"
    return {"checks": checks, "dropped": dropped, "source": "ai+probes" if ai_checks else "probes", "note": note, "scan": scan}
