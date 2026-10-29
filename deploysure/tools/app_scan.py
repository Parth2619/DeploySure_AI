"""Scans what changed between two commits of a whole app: files by layer, config and dependency changes,
endpoint changes, and contract problems between the frontend and the backend.

Env files are reported by KEY only. Values are never read into the report.
"""
import json
import re
from pathlib import Path

from deploysure.tools import git_tool
from deploysure.tools.app_map import build_map
from deploysure.tools.diff_tool import changed_functions
from deploysure.tools.git_tool import GitError, classify_layer


# ---------- config and dependency files ----------

def env_pairs(text: str) -> dict[str, str]:
    pairs = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            pairs[key.strip()] = value.strip()
    return pairs


def diff_env_keys(old: str, new: str) -> dict:
    a, b = env_pairs(old), env_pairs(new)
    return {"added": sorted(b.keys() - a.keys()), "removed": sorted(a.keys() - b.keys()),
            "changed": sorted(k for k in a.keys() & b.keys() if a[k] != b[k])}


def _requirements(text: str) -> dict[str, str]:
    packages = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        match = re.match(r"([A-Za-z0-9_.\[\]-]+)\s*(.*)$", line)
        if match and not line.startswith("-"):
            packages[match.group(1)] = match.group(2).strip()
    return packages


def _package_diff(old: dict[str, str], new: dict[str, str]) -> dict:
    return {"added": [{"name": n, "version": new[n]} for n in sorted(new.keys() - old.keys())],
            "removed": [{"name": n, "version": old[n]} for n in sorted(old.keys() - new.keys())],
            "changed": [{"name": n, "old": old[n], "new": new[n]} for n in sorted(old.keys() & new.keys()) if old[n] != new[n]]}


def diff_requirements(old: str, new: str) -> dict:
    return _package_diff(_requirements(old), _requirements(new))


def _package_json(text: str) -> dict[str, str]:
    try:
        data = json.loads(text) if text.strip() else {}
        return {**data.get("devDependencies", {}), **data.get("dependencies", {})}
    except (ValueError, AttributeError):
        return {}  # a broken package.json must not stop the scan


def diff_package_json(old: str, new: str) -> dict:
    return _package_diff(_package_json(old), _package_json(new))


# ---------- the map, compared ----------

def diff_endpoints(old_map: dict, new_map: dict) -> list[dict]:
    key = lambda e: f"{e['method']} {e['path']}"
    old, new = {key(e): e for e in old_map["endpoints"]}, {key(e): e for e in new_map["endpoints"]}
    changes = [{"endpoint": k, "kind": "endpoint_added", "fields": []} for k in sorted(new.keys() - old.keys())]
    changes += [{"endpoint": k, "kind": "endpoint_removed", "fields": []} for k in sorted(old.keys() - new.keys())]
    for k in sorted(old.keys() & new.keys()):
        for label, field in (("fields", "response_fields"), ("request_fields", "request_fields")):
            added, removed = sorted(set(new[k][field]) - set(old[k][field])), sorted(set(old[k][field]) - set(new[k][field]))
            if added:
                changes.append({"endpoint": k, "kind": f"{label}_added", "fields": added})
            if removed:
                changes.append({"endpoint": k, "kind": f"{label}_removed", "fields": removed})
    return changes


def find_contract_issues(old_map: dict, new_map: dict) -> list[dict]:
    """Problems between frontend and backend that the new commit introduced."""
    issues = []
    already = {(c["method"], c["path"]) for c in old_map["unmatched_calls"]}
    for call in new_map["unmatched_calls"]:
        if (call["method"], call["path"]) not in already:
            issues.append({"kind": "unknown_endpoint", "call": f"{call['method']} {call['path']}", "file": call["file"]})
    new_endpoints = {f"{e['method']} {e['path']}": e for e in new_map["endpoints"]}
    for entry in old_map["contract"]:
        endpoint = new_endpoints.get(entry["endpoint"])
        if endpoint is None:
            continue  # a removed endpoint that the page still calls is reported as unknown_endpoint above
        for field in entry["frontend_reads"]:
            readers = [f for f in entry["frontend_files"] if field in new_map["frontend_names"].get(f, [])]
            if field not in endpoint["response_fields"] and readers:
                issues.append({"kind": "missing_field", "endpoint": entry["endpoint"], "field": field, "read_by": readers})
    return issues


# ---------- the scan ----------

def _read(repo: Path, ref: str, path: str) -> str:
    try:
        return git_tool.read_file(repo, ref, path)
    except GitError:
        return ""  # the file does not exist at that commit (added or deleted)


def scan_change(repo: Path, old: str, new: str) -> dict:
    old_sha, new_sha = git_tool.resolve(repo, old), git_tool.resolve(repo, new)
    files = [{**f, "layer": classify_layer(f["path"])} for f in git_tool.changed_files(repo, old_sha, new_sha)]
    layers: dict[str, list[str]] = {}
    for f in files:
        layers.setdefault(f["layer"], []).append(f["path"])
    config_changes, dependency_changes, functions = [], [], {}
    for f in files:
        path, name = f["path"], Path(f["path"]).name.lower()
        before, after = _read(repo, old_sha, path), _read(repo, new_sha, path)
        if f["layer"] == "config":
            keys = diff_env_keys(before, after) if name.startswith(".env") else None
            if keys is None:
                config_changes.append({"file": path, "status": f["status"]})
            elif any(keys.values()):
                config_changes.append({"file": path, **keys})
        elif f["layer"] == "dependencies":
            diff = (diff_package_json(before, after) if name == "package.json"
                    else diff_requirements(before, after) if name.startswith("requirements") else None)
            dependency_changes.append({"file": path, **(diff or {"status": f["status"]})})
        elif f["layer"] == "backend" and path.endswith(".py") and f["status"] == "M":
            try:
                functions[path] = changed_functions(before, after, path)
            except SyntaxError:
                functions[path] = ["<syntax error>"]
    old_map, new_map = build_map(repo, old_sha), build_map(repo, new_sha)
    readable = not new_map["errors"]  # code that cannot be parsed has no readable endpoints: do not report them as removed
    return {"old": old_sha, "new": new_sha, "files": files, "layers": layers, "config_changes": config_changes,
            "dependency_changes": dependency_changes, "changed_functions": functions,
            "endpoint_changes": diff_endpoints(old_map, new_map) if readable else [],
            "contract_issues": find_contract_issues(old_map, new_map) if readable else [],
            "stack": new_map["stack"], "map_errors": new_map["errors"], "old_map": old_map, "new_map": new_map}


if __name__ == "__main__":
    import sys
    print(json.dumps(scan_change(Path(sys.argv[1]), sys.argv[2], sys.argv[3]), indent=2))
