# Deterministic tooling for DeploySure: pytest runner, test tagging, AST diff, import graph (Oct 2026)

Note: items marked VERIFIED LOCALLY were run on this machine (Windows 11, Python 3.14.5, pytest 9.1.1) in a scratch experiment with two release folders holding identically named modules (v2.0 passing, v2.2 with a failing test). Those are my own test results, not a published source.

## 1. pytest version, Python 3.14 support, machine-readable output

### Takeaway
Latest pytest is 9.1.1 (June 2026), supports Python 3.14 (since 8.4.0). Use `--junitxml` parsed with `xml.etree.ElementTree`: no extra dependency, stable format, gives per-test status.

### Cited Findings
- PyPI lists pytest 9.1.1 as latest, requires_python >=3.10, with a "Python :: 3.14" classifier — [PyPI JSON](https://pypi.org/pypi/pytest/json)
- Changelog: 9.1.1 released 2026-06-19 (bug fixes), 9.1.0 on 2026-06-13 (adds official Python 3.15 support), 9.0.0 on 2025-11-05 (drops Python 3.9), 8.4.0 on 2025-06-02 (added official Python 3.14 support) — [pytest changelog](https://docs.pytest.org/en/stable/changelog.html)
- Exit codes: 0 all passed, 1 some failed, 2 interrupted, 3 internal error, 4 usage error, 5 no tests collected — [pytest exit codes](https://docs.pytest.org/en/stable/reference/exit-codes.html)
- `--junit-xml=path` writes an XML report (since pytest 4.0). testcase attributes: classname, file, line, name, time. Children: properties, skipped (0 or 1), error, failure, system-out, system-err — [pytest output docs](https://docs.pytest.org/en/stable/how-to/output.html)
- `record_property("k", v)` adds a `<property>` under `<properties>` on the testcase. A conftest hook can also fill `item.user_properties` — same page.
- Node ids: `pytest path::func`, `path::Class::method`, `path::func[param]` — [pytest usage](https://docs.pytest.org/en/stable/how-to/usage.html)
- `python -m pytest` adds the current directory to `sys.path`; plain `pytest` does not — [pytest pythonpath explanation](https://docs.pytest.org/en/stable/explanation/pythonpath.html)
- VERIFIED LOCALLY: the junit `file` attribute is absent with default settings, so use `classname` + `name`. The classname is dotted from the rootdir-relative path (`test_payment`; a file in `tests/` gives `tests.test_payment`).

### Recommended runner (VERIFIED LOCALLY)
```python
import subprocess, sys, tempfile, pathlib
import xml.etree.ElementTree as ET

def run_pytest(folder, node_ids=None, timeout=120):
    xml = pathlib.Path(tempfile.mkdtemp()) / "r.xml"
    cmd = [sys.executable, "-m", "pytest", "-q", "--tb=short", f"--junitxml={xml}", *(node_ids or [])]
    p = subprocess.run(cmd, cwd=folder, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    tests = []
    if xml.exists():                      # absent on exit code 3/4 (internal/usage error)
        for tc in ET.parse(xml).getroot().iter("testcase"):   # iter works for <testsuites> or <testsuite> root
            bad = tc.find("failure") is not None or tc.find("error") is not None
            status = "failed" if bad else "skipped" if tc.find("skipped") is not None else "passed"
            tests.append((tc.get("classname"), tc.get("name"), status))
    return p.returncode, tests, p.stdout
```
- Results observed: v2.0 returned rc 0 with both tests passed. v2.2 returned rc 1 with `test_refund` failed and `test_other` passed. Running one id returned rc 0 with one test. A nonexistent id (`::test_nope`) returned rc 4 with an empty list, so treat rc 4/5 as "selection error", not as pass.
- Counts: derive passed, failed and skipped from the tuples. Do not trust the summary line.
- Other options: `-rA` and `-q --tb=no` need text-scraping of the summary lines, which is fragile. pytest-json-report is a third-party plugin and needs an install. I did not research the plugin; skip it since junitxml needs no dependency.

### Inferences
- Use junitxml and treat the exit code only as a sanity check (rc 1 with no failed testcase means something odd).

### Gaps
- Exact upload date of 9.1.1 on PyPI not read (the changelog date, 2026-06-19, is used).
- `junit_family` default behaviour not covered by the fetched docs; observed output was the xunit2-style testcase (no `file` attribute).

## 2. Selected node ids, timeout, process killing, name collisions across v2.0/v2.1/v2.2

### Takeaway
Run each release with `cwd=<release folder>`, a per-release `pytest.ini` (or CLI flags) with `-p no:cacheprovider --import-mode=importlib` and `pythonpath = .`, via `sys.executable -m pytest`. For timeouts, `subprocess.run(timeout=)` is enough for simple cases, but on Windows use Popen plus `taskkill /F /T` to kill the whole tree.

### Cited Findings
- `subprocess.run` passes timeout to `communicate()`; on expiry the child is killed and waited for, then `TimeoutExpired` is re-raised. `exc.stdout`/`stderr` are always `bytes` (or None) even with `text=True` — [subprocess docs](https://docs.python.org/3/library/subprocess.html)
- With raw `Popen.communicate(timeout)`, the child is not killed. Pattern: catch `TimeoutExpired`, call `proc.kill()`, then `communicate()` again — same page.
- On Windows `kill()` and `terminate()` both call `TerminateProcess()`, which hits only that process. The docs say nothing about killing grandchildren; with `shell=True`, `pid` is the shell's — same page.
- Text mode default encoding is `locale.getpreferredencoding(False)`; pass `encoding=` and `errors=` explicitly — same page.
- Import modes: `prepend` (default) puts each test file's dir on `sys.path`; without `__init__.py` files, test basenames must be unique or pytest errors. `importlib` does not touch `sys.path` and derives names from the rootdir-relative path, so duplicate names are fine. Caveats: test modules cannot import each other, and helper modules in test dirs are not importable (fixtures in conftest are fine) — [pytest import mechanisms](https://docs.pytest.org/en/stable/explanation/pythonpath.html)
- `-p no:name` disables a plugin (docs example is `-p no:doctest`) — [usage](https://docs.pytest.org/en/stable/how-to/usage.html). The docs page fetched does not describe `cacheprovider` itself. It is the plugin behind `.pytest_cache`.
- VERIFIED LOCALLY: `taskkill /F /T /PID <pid>` killed a child that had spawned a grandchild, and `wait()` returned promptly (rc 1).
- VERIFIED LOCALLY: Python 3.14.5 on this machine has `locale.getpreferredencoding(False) == 'cp1252'` and UTF-8 mode off, so the default decode would be cp1252.

### Recommended pytest.ini per release folder (VERIFIED LOCALLY)
```ini
[pytest]
markers =
    critical: tests guarding critical behaviour
addopts = --strict-markers -p no:cacheprovider --import-mode=importlib
pythonpath = .
```
Pass a rootdir-relative id, e.g. `test_payment.py::test_refund` or `tests/test_payment.py::test_refund`. Both release folders with identical module names (`payment.py`, `test_payment.py`) ran in separate processes without collision. Each pytest run is its own process, so collisions only matter inside one run; separate processes plus cwd per release already isolate them.

### Windows tree-kill pattern
```python
proc = subprocess.Popen(cmd, cwd=folder, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, encoding="utf-8", errors="replace")
try:
    out, _ = proc.communicate(timeout=timeout)
except subprocess.TimeoutExpired:
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    out, _ = proc.communicate()
    # mark result: {"timed_out": True}
```
Set `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8` in `env=` for the child if test output has non-ASCII.

### Inferences
- With the pytest.ini in each release folder, `pythonpath = .` makes `from payment import refund` resolve to that release's own file. This was confirmed for v2.0 vs v2.2 (v2.2 failed, v2.0 passed).
- A pure `subprocess.run(timeout=)` is likely adequate for the demo (plain tests, no grandchildren). The Popen plus taskkill version is the safe upgrade; I did not reproduce a hang from orphaned grandchildren.

### Gaps
- `rootdir` and conftest discovery details were not given in the fetched docs; I relied on the local experiment (cwd = release folder with its own ini).
- Pytest's own docs on `-p no:cacheprovider` not found in fetched pages.

## 3. Tagging tests critical vs non-critical

### Takeaway
Use a registered marker `@pytest.mark.critical` with `--strict-markers`. Read it either via `pytest --collect-only -q -m critical` (set difference against full collect), or via a small conftest hook that writes it into the junit XML as a property.

### Cited Findings
- Markers are registered under `markers =` in pytest.ini (text after `:` is the description) or via `config.addinivalue_line("markers", ...)`; unregistered marks warn by default, and `--strict-markers` (or `strict_markers = true`) makes them errors. `pytest --markers` lists them; `-m` selects — [pytest marks](https://docs.pytest.org/en/stable/how-to/mark.html)
- A conftest hook can copy values into `item.user_properties`; they appear as `<property>` in junit XML (warning: not strictly valid against the latest JUnit schema) — [pytest output docs](https://docs.pytest.org/en/stable/how-to/output.html)
- VERIFIED LOCALLY: `pytest --collect-only -q -m critical` prints node ids one per line (`test_payment.py::test_refund`) followed by `1/2 tests collected (1 deselected)`.
- VERIFIED LOCALLY: this conftest produced `<property name="critical" value="True"/>` on critical tests and `False` on others in the junit XML:
```python
# conftest.py in each demo release folder
def pytest_collection_modifyitems(items):
    for it in items:
        it.user_properties.append(("critical", it.get_closest_marker("critical") is not None))
```
Parsing: `{p.get("name"): p.get("value") for p in tc.iterfind("properties/property")}`; `critical = props.get("critical") == "True"`.

### Inferences
- Simplest for the viva: one junit run gives status and critical flag together. The marker only works if each release folder carries the conftest (or the project's runner injects it with `-p`/`--confcutdir`; I did not test that). The alternative needs no conftest: run `--collect-only -q -m critical` once, keep the set of ids, and look up each failed test in it.
- A naming convention (`test_critical_*`) needs no pytest config but is easy to break by renaming. The marker is explicit and checked by `--strict-markers`.

### Gaps
- Did not test a collect-only `-q` parse when collection errors occur (lines other than ids appear; filter on `"::" in line`).

## 4. AST-based "which functions changed"

### Takeaway
Parse both versions, build `{function name: ast.dump(node)}` and compare. `ast.dump` ignores comments, whitespace and line numbers by default, so formatting-only edits are not flagged.

### Cited Findings
- VERIFIED LOCALLY (own experiment; the `ast.dump` default of omitting position attributes is standard Python behaviour, see [ast docs](https://docs.python.org/3/library/ast.html)): old `def f(x):\n return x+1  # c` vs new `def f(x):\n  return x + 1` was not flagged; `g` with changed constant and new `h` were flagged, output `['g', 'h']`.
```python
import ast
def funcs(src):
    out = {}
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if ast.get_docstring(n):                    # docstring-only edits are not logic changes
                n.body = n.body[1:] or [ast.Pass()]
            out[n.name] = ast.dump(n)
    return out
def changed(old_src, new_src):
    a, b = funcs(old_src), funcs(new_src)
    return sorted([k for k in b if a.get(k) != b[k]] + [k for k in a if k not in b])  # modified, added, removed
```
- Use `difflib.unified_diff` only for the human-readable diff text in the report; use the AST compare for the decision.

### Inferences
- `ast.walk` flattens nested functions and methods under their bare name. If two classes have the same method name, they collide; key by `Class.method` if the demo project has such cases. Module-level constants (e.g. a fee rate) are not functions, so also compare `ast.dump` of non-function top-level statements, or fall back to whole-module dump equality as "file changed".
- Fixed in-place mutation: the docstring strip mutates the tree, which is fine here since the tree is thrown away.

### Gaps
- No external source for edge cases (decorators, nested classes); not tested.

## 5. Import dependency graph and reverse transitive impact

### Takeaway
Walk each module with `ast`, collect `Import` and `ImportFrom` top-level names that match local module names, invert the graph, then do a BFS from the changed modules.

### Cited Findings
- VERIFIED LOCALLY (own test; node classes per [ast docs](https://docs.python.org/3/library/ast.html)): the snippet below handles `import payment`, `import payment.x`, `from payment import charge`, and `from . import payment`. Run on graph `checkout -> {payment, orders}`, `orders -> payment`, `test_payment -> payment`, a change in `payment` impacted `{checkout, orders, test_payment}`.
```python
import ast, pathlib
def imports(path, known):                    # known = set of local module names (file stems)
    deps = set()
    for n in ast.walk(ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))):
        if isinstance(n, ast.Import):
            deps |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            if n.level == 0 and n.module:
                deps.add(n.module.split(".")[0])
            elif n.level > 0 and n.module is None:      # from . import payment
                deps |= {a.name for a in n.names}
    return deps & known

def impacted(graph, changed):                # graph: {module: set(modules it imports)}
    rev = {}
    for m, ds in graph.items():
        for d in ds: rev.setdefault(d, set()).add(m)
    seen, stack = set(), list(changed)
    while stack:
        for m in rev.get(stack.pop(), ()):
            if m not in seen: seen.add(m); stack.append(m)   # seen set also stops cycles
    return seen
```
- The `seen` set makes cycles safe. Test modules appear in the graph as importers, so impacted test files are directly derivable; this lines up with the "test_selection" rule (impacted modules, so tests that import them).

### Inferences
- `from .payment import x` (level 1 with module set) is not caught by the snippet above; add `elif n.level > 0 and n.module: deps.add(n.module.split(".")[0])` if the demo project uses relative imports. Using flat modules and absolute imports in the demo project avoids this.
- Dynamic imports (`importlib.import_module`, imports inside `try`) are partly seen by `ast.walk` but dynamic strings are invisible; state this as a limitation.

### Gaps
- No source found comparing approaches (e.g. `modulefinder`, `grimp`); stdlib `ast` chosen to keep it explainable.

## 6. Windows pitfalls

### Takeaway
Always set `encoding="utf-8", errors="replace"` and `cwd=` explicitly, use `pathlib`, `sys.executable`, and a Popen plus taskkill for timeouts.

### Cited Findings
- Default text decoding is the locale encoding (cp1252 here, VERIFIED LOCALLY), so non-ASCII output from pytest (assert diffs, box characters) could mis-decode or raise without `errors="replace"` — [subprocess docs](https://docs.python.org/3/library/subprocess.html)
- Read and write source with `read_text(encoding="utf-8")`; the default is the locale encoding too (same reasoning as above; the docs claim comes from the subprocess page for subprocess only — for `read_text` it is my inference).
- Use `sys.executable -m pytest`, not `pytest`, so the same venv interpreter is used; `-m` also adds cwd to `sys.path` — [pythonpath docs](https://docs.python.org/3/library/subprocess.html) is not the source here; see [pytest pythonpath explanation](https://docs.pytest.org/en/stable/explanation/pythonpath.html).
- Pass the command as a list (no `shell=True`) so paths with spaces (the project path `DeploySure AI` contains a space) are not split. Node ids use forward slashes (`tests/test_x.py::t`); pytest also accepts backslashes on Windows but I did not test this.
- `Popen.kill()` and `terminate()` on Windows both call `TerminateProcess` and do not kill descendants — [subprocess docs](https://docs.python.org/3/library/subprocess.html); use `taskkill /F /T` (VERIFIED LOCALLY).
- Use `tempfile.mkdtemp()` for the junit xml path so parallel or repeated runs do not clash, and parse after the process exits.

### Inferences
- The CLAUDE.md rule "subprocess calls always have a timeout" is met by `subprocess.run(timeout=...)`. Consider catching `TimeoutExpired` and returning a result with `timed_out=True`, treated as a failed run in the risk formula.

### Gaps
- Did not test Git Bash vs PowerShell path-style differences when launching Python; calls with `cwd=` and `pathlib.Path` avoid the issue.
