"""Browser checks: short click-through scenarios the AI proposes, run in a real browser on the OLD and the NEW version.

A scenario is a list of steps: goto a path, click, fill, read the text of some elements, or wait. The AI never writes
code. Each run records what the page showed (reads), which API requests it made and how they ended, and any page errors.
Differences between the two runs are the signal:
  a request that now fails, an API call the page stopped making, a page error, a list that lost its items,
  or a value that turned into NaN or undefined, are regressions. Any other text change is only a ui_changed note,
  because a reworded button is not a bug.
Needs Playwright and Chromium: pip install playwright, then python -m playwright install chromium.
"""
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from deploysure.tools import app_runner

MAX_BROWSER_CHECKS = 6
MAX_STEPS = 12
MAX_SELECTOR = 120
MAX_VALUE = 100
MAX_WAIT_MS = 2000
STEP_TIMEOUT_MS = 3000
ACTIONS = {"goto", "click", "fill", "read", "wait"}
BROKEN_VALUE = re.compile(r"\bNaN\b|\bundefined\b|\bnull\b|\[object")
REGRESSIONS = {"step_failed", "new_failed_request", "request_missing", "new_page_error", "broken_value", "items_lost"}


class BrowserUnavailable(RuntimeError):
    """Playwright or Chromium is missing, so browser checks cannot run."""


class BrowserStep(BaseModel):
    action: Literal["goto", "click", "fill", "read", "wait"]
    selector: str | None = None
    value: str | None = None


class BrowserCheck(BaseModel):
    name: str
    steps: list[BrowserStep] = Field(min_length=1)
    reason: str = ""


class BrowserChecks(BaseModel):
    checks: list[BrowserCheck] = Field(min_length=1)


# ---------- choosing and cleaning scenarios ----------

def _bad_step(step: dict) -> str | None:
    action, selector, value = step.get("action"), step.get("selector"), step.get("value")
    if action not in ACTIONS:
        return "unsupported action"
    if action == "goto":
        if not isinstance(value, str) or not value.startswith("/") or value.startswith("//") or "://" in value or len(value) > 200:
            return "goto needs a path that starts with / and has no host"
    elif action in {"click", "read", "fill"}:
        if not isinstance(selector, str) or not 0 < len(selector) <= MAX_SELECTOR:
            return f"{action} needs a selector of 1 to {MAX_SELECTOR} characters"
        if action == "fill" and (not isinstance(value, str) or len(value) > MAX_VALUE):
            return f"fill needs a value of at most {MAX_VALUE} characters"
    elif action == "wait":
        if not (isinstance(value, str) and value.isdigit() and int(value) <= MAX_WAIT_MS):
            return f"wait needs milliseconds up to {MAX_WAIT_MS}"
    return None


def validate_browser_checks(checks: list[dict]) -> tuple[list[dict], list[dict]]:
    """Keeps scenarios made only of allowed, bounded steps. Returns (kept, dropped with the reason)."""
    kept, dropped = [], []
    for raw in checks:
        name = str(raw.get("name", "")).strip()[:80] or "unnamed"
        steps = [dict(s) for s in raw.get("steps", [])]
        why = next((f"step {i}: {bad}" for i, s in enumerate(steps, 1) if (bad := _bad_step(s))), None)
        if not steps:
            why = "no steps"
        elif len(steps) > MAX_STEPS:
            why = f"more than {MAX_STEPS} steps"
        elif len(kept) >= MAX_BROWSER_CHECKS and not why:
            why = f"more than {MAX_BROWSER_CHECKS} scenarios"
        if why:
            dropped.append({"name": name, "why": why})
            continue
        if steps[0].get("action") != "goto":
            steps.insert(0, {"action": "goto", "value": "/"})
        kept.append({**raw, "name": name, "steps": steps})
    return kept, dropped


def smoke_checks() -> list[dict]:
    """One scenario that needs no knowledge of the app: open the page, read it, press the first button, read it again."""
    return [{"name": "Open the page and press the first button", "reason": "a generic smoke check", "steps": [
        {"action": "goto", "value": "/"}, {"action": "wait", "value": "800"}, {"action": "read", "selector": "body"},
        {"action": "click", "selector": "button"}, {"action": "wait", "value": "300"}, {"action": "read", "selector": "body"}]}]


# ---------- judging two runs ----------

def _failing(request: str) -> bool:
    status = request.rsplit(" ", 1)[-1]
    return status == "failed" or (status.isdigit() and int(status) >= 400)


def compare_observations(old: dict, new: dict) -> list[dict]:
    diffs = []
    if new["step_error"] and not old["step_error"]:
        diffs.append({"kind": "step_failed", "detail": new["step_error"]})
    for request in dict.fromkeys(new["requests"]):
        if _failing(request) and request not in old["requests"]:
            diffs.append({"kind": "new_failed_request", "request": request})
    for request in dict.fromkeys(old["requests"]):
        if not _failing(request) and request not in new["requests"]:
            diffs.append({"kind": "request_missing", "request": request})
    diffs += [{"kind": "new_page_error", "detail": e} for e in new["page_errors"] if e not in old["page_errors"]]
    for key in sorted(old["reads"].keys() & new["reads"].keys()):
        before, after = old["reads"][key], new["reads"][key]
        if before == after:
            continue
        if any(BROKEN_VALUE.search(t) for t in after) and not any(BROKEN_VALUE.search(t) for t in before):
            kind = "broken_value"
        elif len(after) < len(before):
            kind = "items_lost"
        else:
            kind = "text_changed"
        diffs.append({"kind": kind, "field": key, "old": before, "new": after})
    return diffs


def verdict(old: dict, diffs: list[dict]) -> str:
    if old["step_error"] or old["page_errors"] or any(_failing(r) for r in old["requests"]):
        return "unreliable"  # the old version already failed this scenario, so it cannot be a baseline
    if any(d["kind"] in REGRESSIONS for d in diffs):
        return "regression"
    return "ui_changed" if diffs else "unchanged"


# ---------- running ----------

def _observe(browser, base_url: str, check: dict) -> dict:
    result = {"reads": {}, "requests": [], "page_errors": [], "step_error": None}
    context = browser.new_context()
    try:
        page = context.new_page()
        page.set_default_timeout(STEP_TIMEOUT_MS)
        page.on("response", lambda r: result["requests"].append(f"{r.request.method} {urlparse(r.url).path} {r.status}")
                if r.request.resource_type in {"fetch", "xhr"} else None)
        page.on("requestfailed", lambda r: result["requests"].append(f"{r.method} {urlparse(r.url).path} failed")
                if r.resource_type in {"fetch", "xhr"} else None)
        page.on("pageerror", lambda e: result["page_errors"].append(str(e)[:200]))
        for number, step in enumerate(check["steps"], 1):
            try:
                if step["action"] == "goto":
                    page.goto(base_url + step["value"])
                elif step["action"] == "click":
                    page.locator(step["selector"]).first.click()
                elif step["action"] == "fill":
                    page.locator(step["selector"]).first.fill(step["value"])
                elif step["action"] == "read":
                    result["reads"][f"{number}:{step['selector']}"] = [re.sub(r"\s+", " ", t).strip() for t in page.locator(step["selector"]).all_inner_texts()]
                else:
                    page.wait_for_timeout(int(step["value"]))
            except Exception as err:  # a missing element, a timeout or a navigation error ends the scenario
                result["step_error"] = f"step {number} ({step['action']} {step.get('selector') or step.get('value')}): {type(err).__name__}"
                break
        page.wait_for_timeout(300)  # let requests that are still in flight finish
    finally:
        context.close()
    return result


def run_browser_checks(old_url: str, new_url: str, checks: list[dict]) -> list[dict]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise BrowserUnavailable("Playwright is not installed. Run: pip install playwright, then python -m playwright install chromium")
    results = []
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as err:
            raise BrowserUnavailable(f"Chromium could not start ({type(err).__name__}). Run: python -m playwright install chromium")
        try:
            for check in checks:
                old, new = _observe(browser, old_url, check), _observe(browser, new_url, check)
                diffs = compare_observations(old, new)
                results.append({"name": check["name"], "reason": check.get("reason", ""), "old": old, "new": new,
                                "differences": diffs, "verdict": verdict(old, diffs)})
        finally:
            browser.close()
    return results


def summarise(results: list[dict]) -> dict:
    counts = {v: sum(r["verdict"] == v for r in results) for v in ("unchanged", "ui_changed", "regression", "unreliable")}
    return {**counts, "regressions": [r["name"] for r in results if r["verdict"] == "regression"]}


def run_browser_differential(repo: Path, old_ref: str, new_ref: str, checks: list[dict], **runner_options) -> dict:
    with app_runner.running_apps(repo, [old_ref, new_ref], **runner_options) as (old, new):
        results = run_browser_checks(old.base_url, new.base_url, checks)
    return {"old": old.sha, "new": new.sha, "results": results, "summary": summarise(results)}
