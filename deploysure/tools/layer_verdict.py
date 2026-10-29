"""Which layer broke: the frontend, the backend, or the connection between them.

Deterministic rules over three kinds of evidence: the static contract scan, the API checks and the browser checks.
  - Static issue: a page call to a route the backend does not serve, or a field the page still reads that the API dropped.
  - API regression: the same request gives a different answer on the new version.
  - Browser regression: the page shows something broken on the new version.
A fault is the connection when both sides must agree (a field was renamed, a route was removed) and the frontend when
only the page changed. API and browser regressions that a static issue already explains are not blamed on another layer.
Confidence is high when two kinds of evidence support a layer, medium for one, low when no check could be trusted.
"""
from deploysure.tools.app_map import paths_match

STRUCTURAL = {"field_removed", "field_added"}


def _describe(diff: dict) -> str:
    kind = diff["kind"]
    if kind == "value_changed":
        return f"{diff['field']} changed from {diff['old']} to {diff['new']}"
    if kind == "field_removed":
        return f"field {diff['field']} was removed"
    if kind == "field_added":
        return f"field {diff['field']} was added"
    if kind == "status_changed":
        return f"status changed from {diff['old']} to {diff['new']}"
    if kind in {"new_failed_request", "request_missing"}:
        return f"request {diff['request']} {'failed' if kind == 'new_failed_request' else 'is no longer made'}"
    if kind == "broken_value":
        return f"{diff['field']} now shows {diff['new']}"
    if kind == "items_lost":
        return f"{diff['field']} lost items"
    return diff.get("detail") or kind


def _first(result: dict) -> str:
    return "; ".join(_describe(d) for d in result["differences"][:2])


def layer_verdict(scan: dict, api: list[dict], browser: list[dict], start_error: str = "", browser_error: str = "") -> dict:
    changed = set(scan["layers"])
    removed = any(c["kind"] == "endpoint_removed" for c in scan["endpoint_changes"])
    support: dict[str, set[str]] = {}
    reasons: list[str] = []
    api_regressions = [r for r in api if r["verdict"] == "regression"]
    ui_regressions = [r for r in browser if r["verdict"] == "regression"]

    def blame(layer: str, kind: str, reason: str | None = None) -> None:
        support.setdefault(layer, set()).add(kind)
        if reason:
            reasons.append(reason)

    if start_error:
        layer = "backend" if "backend" in changed else "environment"
        blame(layer, "start", f"The new version did not start: {start_error[:150]}")

    explained_api: set[int] = set()
    issue_layers = []
    for issue in scan["contract_issues"]:
        if issue["kind"] == "unknown_endpoint":
            if removed or ("frontend" not in changed and "backend" in changed):
                layer, reason = "connection", f"The backend no longer serves {issue['call']}, but {issue['file']} still calls it."
            else:
                layer, reason = "frontend", f"{issue['file']} calls {issue['call']}, which the backend does not serve."
        else:
            layer = "connection"
            reason = f"The backend no longer returns '{issue['field']}' on {issue['endpoint']}, but {', '.join(issue['read_by'])} still reads it."
            method, _, path = issue["endpoint"].partition(" ")
            for i, result in enumerate(api_regressions):  # a renamed field shows up in the API check too: same cause
                if result["method"] == method and paths_match(result["path"], path) and {d["kind"] for d in result["differences"]} <= STRUCTURAL:
                    explained_api.add(i)
                    blame(layer, "api")
        blame(layer, "static", reason)
        issue_layers.append(layer)

    if issue_layers and ui_regressions:  # the broken page is the symptom of the static issue
        for layer in set(issue_layers):
            blame(layer, "browser")
    for i, result in enumerate(api_regressions):
        if i not in explained_api:
            blame("backend", "api", f"API check '{result['name']}' gives a different answer: {_first(result)}.")
    if ui_regressions and not issue_layers:
        for result in ui_regressions:
            if api_regressions and "frontend" not in changed:  # no page file changed, so the broken page is a symptom of the API change
                blame("backend", "browser", f"Browser check '{result['name']}' breaks because of the backend change: {_first(result)}.")
            else:
                blame("frontend", "browser", f"Browser check '{result['name']}' shows a broken page: {_first(result)}.")

    checks = api + browser
    if support:
        confidence = "high" if all(len(kinds) >= 2 for kinds in support.values()) else "medium"
    elif not any(r["verdict"] in {"unchanged", "benign_change", "ui_changed"} for r in checks):
        confidence = "low"
        reasons.append("No check could be trusted or none ran, so the result is uncertain.")
    else:
        confidence = "medium" if browser_error else "high"
        reasons.append("No regression was found.")
    if browser_error:
        reasons.append(f"Some checks did not run: {browser_error[:120]}")
    layers = sorted(support)
    return {"layers": layers, "primary": " and ".join(layers) or "none", "confidence": confidence, "reasons": reasons,
            "evidence": {"static": len(scan["contract_issues"]), "api": len(api_regressions), "browser": len(ui_regressions)}}
