"""Maps an app: its backend endpoints, the API calls the frontend makes, and the contract between them.

These are heuristics from reading the code, not proof. They cover FastAPI and Flask routes, and fetch, axios and jQuery
calls. The contract is the set of fields the frontend reads AND the backend returned at the time. If a later backend stops
returning one of them while the frontend still reads it, the connection is broken.
"""
import ast
import json
import re
from pathlib import Path

from deploysure.tools import git_tool
from deploysure.tools.git_tool import classify_layer

HTTP_METHODS = {"get", "post", "put", "delete", "patch"}
FRONTEND_CODE = {".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".html"}
MAX_FILES = 400

CALL_RE = re.compile(r"""(?:\bfetch|\baxios(?:\.(?P<ax>get|post|put|delete|patch))?|\$\.(?P<jq>get|post)"""
                     r"""|\bhttp\.(?P<ng>get|post|put|delete|patch))\(\s*(?P<q>["'`])(?P<url>[^"'`]+)(?P=q)""")
METHOD_RE = re.compile(r"""method\s*:\s*["'`](\w+)["'`]""")
FIELD_RE = re.compile(r"\b[A-Za-z_]\w*\.([A-Za-z_]\w*)")


# ---------- backend ----------

def _module_constants(tree: ast.Module) -> dict[str, ast.AST]:
    return {t.id: node.value for node in tree.body if isinstance(node, ast.Assign) for t in node.targets if isinstance(t, ast.Name)}


def _dict_keys(node: ast.AST) -> set[str]:
    return {k.value for d in ast.walk(node) if isinstance(d, ast.Dict) for k in d.keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)}


def _model_fields(name: str, classes: dict[str, ast.ClassDef], seen: set[str]) -> set[str]:
    """Field names of a pydantic-style class, including the classes its fields refer to."""
    if name in seen or name not in classes:
        return set()
    seen.add(name)
    fields = set()
    for stmt in classes[name].body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            fields.add(stmt.target.id)
            for ref in ast.walk(stmt.annotation):
                if isinstance(ref, ast.Name):
                    fields |= _model_fields(ref.id, classes, seen)
    return fields


def _sample_value(annotation: ast.AST, classes: dict[str, ast.ClassDef], n: int, depth: int = 0):
    """An example value for a type annotation. n varies the numbers so two samples can tell quantity 1 from quantity 2."""
    simple = {"int": n, "float": float(n), "str": "test", "bool": True}
    if isinstance(annotation, ast.Name):
        if annotation.id in simple:
            return simple[annotation.id]
        if annotation.id in classes and depth < 4:
            return {s.target.id: _sample_value(s.annotation, classes, n, depth + 1) for s in classes[annotation.id].body
                    if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)}
    if isinstance(annotation, ast.Subscript) and isinstance(annotation.value, ast.Name) and annotation.value.id in {"list", "List"}:
        return [_sample_value(annotation.slice, classes, n, depth + 1)]
    return None


def endpoints_from_python(path: str, source: str) -> list[dict]:
    """FastAPI (@app.get) and Flask (@app.route) endpoints with the field names they take and return."""
    tree = ast.parse(source, filename=path)
    constants = _module_constants(tree)
    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
    found = []
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in func.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.args
                    and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str)):
                continue
            if dec.func.attr in HTTP_METHODS:
                methods = [dec.func.attr.upper()]
            elif dec.func.attr == "route":
                given = [kw.value for kw in dec.keywords if kw.arg == "methods"]
                methods = [e.value.upper() for e in given[0].elts if isinstance(e, ast.Constant)] if given and isinstance(given[0], ast.List) else ["GET"]
            else:
                continue
            response = _dict_keys(func)
            for node in ast.walk(func):  # "return NAME" where NAME is a module constant holding dicts
                if isinstance(node, ast.Return) and isinstance(node.value, ast.Name) and node.value.id in constants:
                    response |= _dict_keys(constants[node.value.id])
            request, samples = set(), []
            for arg in func.args.args:
                if isinstance(arg.annotation, ast.Name):
                    request |= _model_fields(arg.annotation.id, classes, set())
                    if arg.annotation.id in classes and not samples:  # the body model: two examples with different numbers
                        samples = [_sample_value(arg.annotation, classes, n) for n in (1, 2)]
            for method in methods:
                found.append({"method": method, "path": dec.args[0].value, "file": path, "function": func.name,
                              "response_fields": sorted(response), "request_fields": sorted(request),
                              "sample_bodies": samples if method in {"POST", "PUT", "PATCH"} else []})
    return found


# ---------- frontend ----------

def _call_arguments(text: str, open_paren: int) -> str:
    """The text inside the parentheses that start at open_paren, so the method is read from this call only."""
    depth, quote = 0, None
    for i in range(open_paren, len(text)):
        ch = text[i]
        if quote:
            quote = None if ch == quote else quote
        elif ch in "\"'`":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[open_paren + 1:i]
    return text[open_paren + 1:]


def calls_from_frontend(path: str, text: str) -> list[dict]:
    """API calls with a string or template literal URL. Calls through a variable cannot be read and are skipped."""
    calls = []
    for m in CALL_RE.finditer(text):
        url = re.sub(r"^https?://[^/]+", "", m.group("url"))
        url = re.sub(r"[?#].*$", "", re.sub(r"\$\{[^}]*\}", "{}", url))
        if not url.startswith("/"):
            continue
        method = (m.group("ax") or m.group("jq") or m.group("ng") or "").upper()
        if not method:
            given = METHOD_RE.search(_call_arguments(text, text.index("(", m.start())))
            method = given.group(1).upper() if given else "GET"
        calls.append({"method": method, "path": url, "file": path, "line": text.count("\n", 0, m.start()) + 1})
    return calls


def frontend_names(text: str) -> set[str]:
    """Every name read with a dot, such as p.price. Names are matched against backend fields later."""
    return set(FIELD_RE.findall(text))


def selectors_from_frontend(text: str) -> set[str]:
    """CSS selectors the page defines or uses, so browser checks know what to click and read."""
    found = {f"#{i}" for i in re.findall(r"""\bid\s*=\s*["']([\w-]+)["']""", text)}
    found |= {f"#{i}" for i in re.findall(r"""getElementById\(\s*["']([\w-]+)["']\s*\)""", text)}
    for group in re.findall(r"""\bclass\s*=\s*["']([^"']+)["']""", text) + re.findall(r"""\.className\s*=\s*["']([^"']+)["']""", text):
        found |= {f".{c}" for c in group.split()}
    found |= {f".{c}" for c in re.findall(r"""classList\.add\(\s*["']([\w-]+)["']""", text)}
    found |= set(re.findall(r"""querySelector(?:All)?\(\s*["']([^"']+)["']""", text))
    return found


def _segments(path: str) -> list[str]:
    return ["*" if re.fullmatch(r"\{.*\}|<.*>", s) else s for s in path.strip("/").split("/")]


def paths_match(call_path: str, endpoint_path: str) -> bool:
    a, b = _segments(call_path), _segments(endpoint_path)
    return len(a) == len(b) and all(x == y or "*" in (x, y) for x, y in zip(a, b))


# ---------- the whole map ----------

def detect_stack(files: dict[str, str]) -> dict:
    deps = " ".join(t.lower() for p, t in files.items() if classify_layer(p) == "dependencies")
    backend = next((name for name in ("fastapi", "flask", "django") if name in deps), None)
    frontend = None
    for path, text in files.items():
        if path.endswith("package.json"):
            try:
                packages = {**json.loads(text).get("dependencies", {}), **json.loads(text).get("devDependencies", {})}
            except ValueError:
                continue
            frontend = next((name for name in ("react", "vue", "svelte", "next") if name in packages), frontend or "node")
    if frontend is None and any(classify_layer(p) == "frontend" and Path(p).suffix in FRONTEND_CODE for p in files):
        frontend = "plain html and js"
    return {"backend": backend, "frontend": frontend}


def build_map_from_files(files: dict[str, str]) -> dict:
    endpoints, calls, names, errors, selectors = [], [], {}, [], set()
    for path, text in sorted(files.items()):
        layer = classify_layer(path)
        if layer == "backend" and path.endswith(".py"):
            try:
                endpoints += endpoints_from_python(path, text)
            except SyntaxError as err:  # a broken commit must still be scannable
                errors.append(f"{path} has a syntax error on line {err.lineno}: {err.msg}")
        elif layer == "frontend" and Path(path).suffix in FRONTEND_CODE:
            calls += calls_from_frontend(path, text)
            names[path] = sorted(frontend_names(text))
            selectors |= selectors_from_frontend(text)
    matched = {}
    unmatched = []
    for call in calls:
        owners = [e for e in endpoints if e["method"] == call["method"] and paths_match(call["path"], e["path"])]
        if not owners:
            unmatched.append(call)
        for e in owners:
            matched.setdefault(f"{e['method']} {e['path']}", (e, set()))[1].add(call["file"])
    contract = []
    for key, (endpoint, call_files) in matched.items():
        read = set().union(*(set(names[f]) for f in call_files)) & set(endpoint["response_fields"])
        contract.append({"endpoint": key, "file": endpoint["file"], "response_fields": endpoint["response_fields"],
                         "frontend_files": sorted(call_files), "frontend_reads": sorted(read)})
    return {"stack": detect_stack(files), "endpoints": endpoints, "frontend_calls": calls, "unmatched_calls": unmatched,
            "contract": contract, "frontend_names": names, "selectors": sorted(selectors), "errors": errors}


def build_map(repo: Path, ref: str) -> dict:
    """The map of the app as it is at a commit."""
    wanted = [p for p in git_tool.list_files(repo, ref) if classify_layer(p) in {"backend", "frontend", "dependencies"}]
    files = {p: git_tool.read_file(repo, ref, p) for p in wanted[:MAX_FILES]}
    return build_map_from_files(files)
