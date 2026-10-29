"""App-mode nodes that gather the evidence: plan, scan the commits, write the checks, run old and new side by side."""
from contextlib import ExitStack
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from deploysure.agents.check_writer import write_browser_checks, write_checks
from deploysure.models import llm
from deploysure.models.llm import ask
from deploysure.orchestration.app_state import AppState
from deploysure.tools import api_checks, app_runner, browser_checks
from deploysure.tools.app_runner import AppStartError
from deploysure.tools.app_scan import scan_change

MAX_CHECK_ROUNDS = 2  # the Check writer runs once, and once more if the Differential run says some checks were unreliable
Focus = Literal["api_contract", "page_behavior", "data_values", "config_and_dependencies"]


class AppPlan(BaseModel):
    focus: list[Focus] = Field(min_length=1, max_length=4)
    reason: str


def say(sender: str, to: str, kind: str, text: str, **extra) -> dict:
    """One message from an agent to another. They are kept in the shared state and shown in the UI."""
    return {"from": sender, "to": to, "kind": kind, "text": text, **extra}


def default_focus(scan: dict) -> list[str]:
    """What to test first, by fixed rules from what changed. Used when the AI is not available."""
    layers = set(scan["layers"])
    focus = []
    if scan["contract_issues"] or scan["endpoint_changes"]:
        focus.append("api_contract")
    if "frontend" in layers:
        focus.append("page_behavior")
    if "backend" in layers:
        focus += ["api_contract", "data_values"]
    if layers & {"config", "dependencies"}:
        focus.append("config_and_dependencies")
    return list(dict.fromkeys(focus or ["api_contract", "page_behavior"]))


def change_scan(state: AppState) -> dict:
    scan = scan_change(Path(state["repo"]), state["old"], state["new"])
    layers = ", ".join(f"{layer} ({len(paths)})" for layer, paths in scan["layers"].items()) or "nothing"
    issues = f", {len(scan['contract_issues'])} contract issue(s)" if scan["contract_issues"] else ""
    told = (f"{len(scan['files'])} file(s) changed in: {layers}. {len(scan['contract_issues'])} contract issue(s), "
            f"{len(scan['endpoint_changes'])} endpoint change(s), {len(scan['config_changes'])} config change(s), {len(scan['dependency_changes'])} dependency change(s).")
    return {"scan": scan, "old_sha": scan["old"], "new_sha": scan["new"], "messages": [say("change_scan", "planner", "info", told)],
            "trace": [f"change_scan: {len(scan['files'])} file(s) changed: {layers}{issues}"]}


def app_planner(state: AppState) -> dict:
    """Reads the scan and decides what the Check writer should test first. The Check writer receives this as its priority."""
    scan = state["scan"]
    facts = [f"changed layers: {', '.join(f'{layer} ({len(paths)})' for layer, paths in scan['layers'].items()) or 'none'}",
             f"contract issues between page and API: {len(scan['contract_issues'])}",
             f"endpoint changes: {', '.join(c['endpoint'] + ' ' + c['kind'] for c in scan['endpoint_changes'][:5]) or 'none'}",
             f"changed functions: {', '.join(n for names in scan['changed_functions'].values() for n in names[:4]) or 'none'}",
             f"config or dependency changes: {len(scan['config_changes']) + len(scan['dependency_changes'])}"]
    prompt = (f"You plan the safety check of a change to a web app, from {state['old']} to {state['new']}. Choose 1 to 4 focus areas to test first.\n"
              "api_contract: the routes and fields the page and backend share. page_behavior: what the page shows after clicks. "
              "data_values: numbers the API calculates. config_and_dependencies: settings and packages.\n"
              + "\n".join(facts) + '\nReply as JSON: {"focus": ["api_contract"], "reason": "one sentence"}')
    answer, fallback = ask(prompt, AppPlan, task="planner",
                           default={"focus": default_focus(scan), "reason": "Chosen by fixed rules from what changed."})
    focus = list(dict.fromkeys(answer["focus"]))
    note = llm.fallback_note("used fixed rules") if fallback else ""
    return {"focus": focus, "focus_reason": answer["reason"],
            "messages": [say("planner", "check_writing", "focus", f"Test these first: {', '.join(focus)}. {answer['reason']}")],
            "trace": [f"planner: focus {', '.join(focus)}{note}"]}


def check_writing(state: AppState) -> dict:
    repo = Path(state["repo"])
    round_no = state.get("check_round", 0) + 1
    hint = next((m["text"] for m in reversed(state.get("messages", [])) if m["to"] == "check_writing" and m["kind"] == "repair"), "") if round_no > 1 else ""
    focus = state.get("focus", [])
    api = write_checks(repo, state["old"], state["new"], scan=state["scan"], focus=focus, hint=hint)
    ui = write_browser_checks(repo, state["scan"], focus=focus, hint=hint)
    line = (f"check_writing: {len(api['checks'])} API check(s) from {api['source']}{api['note']}, "
            f"{len(ui['checks'])} browser scenario(s) from {ui['source']}{ui['note']}" + (" (second round, after the Differential run's complaint)" if hint else ""))
    told = f"{len(api['checks'])} API check(s) from {api['source']} and {len(ui['checks'])} scenario(s) from {ui['source']}" + (", rewritten after round 1." if hint else ".")
    return {"api_checks": api["checks"], "browser_checks": ui["checks"], "check_sources": {"api": api["source"], "browser": ui["source"]},
            "check_round": round_no, "messages": [say("check_writing", "differential_run", "info", told)], "trace": [line]}


def _trim_api(results: list[dict]) -> list[dict]:
    return [{"name": r["name"], "method": r["method"], "path": r["path"], "reason": r["reason"], "verdict": r["verdict"],
             "differences": r["differences"], "assertion": r["assertion"], "old_status": r["old"]["status"], "new_status": r["new"]["status"]}
            for r in results]


def _trim_browser(results: list[dict]) -> list[dict]:
    return [{"name": r["name"], "reason": r["reason"], "verdict": r["verdict"], "differences": r["differences"],
             "old": {"requests": r["old"]["requests"], "step_error": r["old"]["step_error"]},
             "new": {"requests": r["new"]["requests"], "step_error": r["new"]["step_error"]}} for r in results]


def differential_run(state: AppState) -> dict:
    """Starts the old version, then the new one, and runs every check against both. Failures become evidence, not crashes."""
    repo = Path(state["repo"])
    start_error = browser_error = ""
    api_results, browser_results = [], []
    with ExitStack() as stack:
        try:
            old = stack.enter_context(app_runner.running_app(repo, state["old"]))
        except AppStartError as err:  # no baseline, so nothing can be compared
            browser_error = f"the old version did not start, so nothing could be compared: {str(err)[:150]}"
        else:
            try:
                new = stack.enter_context(app_runner.running_app(repo, state["new"]))
            except AppStartError as err:
                start_error = str(err)[:300]
            else:
                api_results = api_checks.run_checks(old.base_url, new.base_url, state["api_checks"])
                try:
                    browser_results = browser_checks.run_browser_checks(old.base_url, new.base_url, state["browser_checks"])
                except browser_checks.BrowserUnavailable as err:
                    browser_error = str(err)
    api_summary, ui_summary = api_checks.summarise(api_results), browser_checks.summarise(browser_results)
    line = (f"differential_run: API {api_summary['regression']} regression(s) of {len(api_results)}, "
            f"browser {ui_summary['regression']} regression(s) of {len(browser_results)}")
    if start_error:
        line = f"differential_run: the new version did not start: {start_error[:100]}"
    elif browser_error:
        line += f" ({browser_error[:100]})"
    unreliable = [r["name"] for r in api_results + browser_results if r["verdict"] == "unreliable"]
    told = (f"New version did not start: {start_error[:120]}" if start_error else
            f"{api_summary['regression']} API regression(s), {ui_summary['regression']} page regression(s), {len(unreliable)} unreliable check(s)"
            + (f". Some checks did not run: {browser_error[:100]}" if browser_error else "."))
    messages = [say("differential_run", "layer_attribution", "info", told)]
    round_no = state.get("check_round", 1)
    ai_wrote_checks = any("ai" in source for source in state.get("check_sources", {}).values())
    if unreliable and ai_wrote_checks and round_no < MAX_CHECK_ROUNDS and not (start_error or browser_error):
        messages.append(say("differential_run", "check_writing", "repair",
                            "These checks were unreliable, the old version already failed them: " + "; ".join(unreliable[:6])
                            + ". Propose different inputs that the old version accepts.", round=round_no))
        line += f", asking the Check writer to repair {len(unreliable)} unreliable check(s)"
    return {"api_report": {"results": _trim_api(api_results), "summary": api_summary},
            "browser_report": {"results": _trim_browser(browser_results), "summary": ui_summary},
            "start_error": start_error, "browser_error": browser_error, "messages": messages, "trace": [line]}


def repair_requested(state: AppState) -> bool:
    """True when the Differential run just asked the Check writer to redo its checks. Used by the graph to loop back, at most once."""
    round_no = state.get("check_round", 0)
    return round_no < MAX_CHECK_ROUNDS and any(m["kind"] == "repair" and m.get("round") == round_no for m in state.get("messages", []))
