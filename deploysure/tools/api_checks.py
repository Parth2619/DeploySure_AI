"""API checks: small declarative HTTP tests that the AI proposes and that run on the OLD and the NEW version of an app.

The AI picks interesting requests. It never has to work out the right answer: the same request goes to both versions,
and a changed answer is the signal. An optional expectation (status, or some JSON fields) is only trusted when it holds on
the old version. This keeps the AI's weaknesses (wrong arithmetic, invented endpoints) out of the verdict.
"""
import json
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, Field

from deploysure.tools import app_map, app_runner

MAX_CHECKS = 12
MAX_BODY_CHARS = 2000
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


class ApiCheck(BaseModel):
    name: str
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str
    json_body: dict | list | None = None
    expect_status: int | None = None
    expect_json: dict | None = None
    reason: str = ""


class ApiChecks(BaseModel):
    checks: list[ApiCheck] = Field(min_length=1)


# ---------- choosing and cleaning checks ----------

def validate_checks(checks: list[dict], endpoints: list[dict]) -> tuple[list[dict], list[dict]]:
    """Keeps checks that can really run against the app. Returns (kept, dropped with the reason)."""
    known = [(e["method"], e["path"]) for e in endpoints]
    kept, dropped, seen = [], [], set()
    for raw in checks:
        name = str(raw.get("name", "")).strip()[:80] or "unnamed"
        method, path = str(raw.get("method", "")).upper(), str(raw.get("path", ""))
        body = json.dumps(raw.get("json_body"), sort_keys=True)
        why = None
        if method not in METHODS:
            why = "unsupported method"
        elif not path.startswith("/") or path.startswith("//") or "://" in path:
            why = "the path must start with / and have no host"
        elif "?" in path or "#" in path or len(path) > 200:
            why = "query strings, fragments and long paths are not supported"
        elif not any(m == method and app_map.paths_match(path, p) for m, p in known):
            why = "no such endpoint in the old version"
        elif len(body) > MAX_BODY_CHARS:
            why = "the request body is too large"
        elif (method, path, body) in seen:
            why = "duplicate"
        elif len(kept) >= MAX_CHECKS:
            why = f"more than {MAX_CHECKS} checks"
        if why:
            dropped.append({"name": name, "why": why})
            continue
        seen.add((method, path, body))
        kept.append({**raw, "name": name, "method": method})
    return kept, dropped


def fallback_checks(endpoints: list[dict]) -> list[dict]:
    """Checks that need no AI: every plain GET, and each write endpoint with two sample bodies built from its model."""
    checks = []
    for e in endpoints:
        if e["method"] == "GET" and "{" not in e["path"] and "<" not in e["path"]:
            checks.append({"name": f"GET {e['path']}", "method": "GET", "path": e["path"]})
        elif e["method"] in {"POST", "PUT", "PATCH"}:
            for number, body in enumerate(e.get("sample_bodies", []), 1):
                checks.append({"name": f"{e['method']} {e['path']} (sample {number})", "method": e["method"],
                               "path": e["path"], "json_body": body})
    return checks


# ---------- comparing answers ----------

def _leaves(value, prefix: str = "") -> dict:
    if isinstance(value, dict) and value:
        return {k: v for key, item in value.items() for k, v in _leaves(item, f"{prefix}.{key}" if prefix else str(key)).items()}
    if isinstance(value, list) and value:
        return {k: v for i, item in enumerate(value) for k, v in _leaves(item, f"{prefix}[{i}]").items()}
    return {prefix: value}


def compare_responses(old: dict, new: dict) -> list[dict]:
    """What differs between two answers to the same request: status, changed values, removed and added fields."""
    if old.get("error") or new.get("error"):
        return [{"kind": "app_error", "detail": new.get("error") or old.get("error")}]
    diffs = []
    if old["status"] != new["status"]:
        diffs.append({"kind": "status_changed", "old": old["status"], "new": new["status"]})
    if old["json"] is None and new["json"] is None:
        if old["text"] != new["text"]:
            diffs.append({"kind": "value_changed", "field": "body", "old": old["text"], "new": new["text"]})
        return diffs
    a, b = _leaves(old["json"]), _leaves(new["json"])
    for path in sorted(a.keys() | b.keys()):
        if path not in b:
            diffs.append({"kind": "field_removed", "field": path})
        elif path not in a:
            diffs.append({"kind": "field_added", "field": path})
        elif a[path] != b[path]:
            diffs.append({"kind": "value_changed", "field": path, "old": a[path], "new": b[path]})
    return diffs


def evaluate(check: dict, response: dict) -> bool | None:
    """Does the answer meet the check's expectation? None when the check has no expectation."""
    if check.get("expect_status") is None and not check.get("expect_json"):
        return None
    if response.get("error"):
        return False
    ok = check.get("expect_status") is None or response["status"] == check["expect_status"]
    if check.get("expect_json"):
        body = response["json"]
        target = body[0] if isinstance(body, list) and body else body  # a list is checked on its first item
        ok = ok and isinstance(target, dict) and all(target.get(k) == v for k, v in check["expect_json"].items())
    return ok


# ---------- running ----------

def _request(base_url: str, check: dict) -> dict:
    try:
        reply = httpx.request(check["method"], base_url + check["path"], json=check.get("json_body"), timeout=10)
    except httpx.HTTPError as err:
        return {"status": 0, "json": None, "text": "", "error": f"{type(err).__name__}: {err}"}
    try:
        body = reply.json()
    except ValueError:
        body = None
    return {"status": reply.status_code, "json": body, "text": reply.text[:300], "error": None}


def _verdict(old: dict, diffs: list[dict], asserted: tuple) -> str:
    if old["error"] or old["status"] >= 500 or old["status"] == 422:  # the old version could not answer it: the check is not trustworthy
        return "unreliable"
    if any(d["kind"] != "field_added" for d in diffs) or asserted == (True, False):
        return "regression"
    return "benign_change" if diffs else "unchanged"


def run_checks(old_url: str, new_url: str, checks: list[dict]) -> list[dict]:
    """Sends each check to both versions, in the same order, and judges the difference."""
    results = []
    for check in checks:
        old, new = _request(old_url, check), _request(new_url, check)
        diffs = compare_responses(old, new)
        asserted = (evaluate(check, old), evaluate(check, new))
        results.append({"name": check["name"], "method": check["method"], "path": check["path"], "reason": check.get("reason", ""),
                        "old": old, "new": new, "differences": diffs, "assertion": {"old": asserted[0], "new": asserted[1]},
                        "verdict": _verdict(old, diffs, asserted)})
    return results


def summarise(results: list[dict]) -> dict:
    counts = {v: sum(r["verdict"] == v for r in results) for v in ("unchanged", "benign_change", "regression", "unreliable")}
    return {**counts, "regressions": [r["name"] for r in results if r["verdict"] == "regression"]}


def run_differential(repo: Path, old_ref: str, new_ref: str, checks: list[dict], **runner_options) -> dict:
    """Starts both versions side by side and runs the checks against each."""
    with app_runner.running_apps(repo, [old_ref, new_ref], **runner_options) as (old, new):
        results = run_checks(old.base_url, new.base_url, checks)
    return {"old": old.sha, "new": new.sha, "results": results, "summary": summarise(results)}
