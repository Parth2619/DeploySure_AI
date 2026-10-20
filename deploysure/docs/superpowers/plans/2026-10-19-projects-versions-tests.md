# Projects, Versions and Test Cases Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user add projects, add versions and add test cases from the UI, and analyze any version with the existing agents.

**Architecture:** Plain folders and JSON under `projects/`. The demo shop becomes project `demo-shop`. Tools and agents take a `project_id` from the state and read per-project settings (critical modules, customer-facing weights). A new `project_store` module owns the files, a new `test_cases` module owns test case files, and `server.py` exposes them over HTTP. The UI becomes a two-page hash-routed single file.

**Tech Stack:** Python 3.14, LangGraph 1.2.15, pytest 9.1.1, FastAPI 0.143.2, vanilla JS in `ui/index.html`.

**Spec:** `docs/superpowers/specs/2026-10-19-projects-versions-tests-design.md`

All paths below are relative to the `deploysure/` folder. There is no git repository, so there are no commit steps. The checkpoint after each task is `.venv\Scripts\python -m pytest tests/ -q` from `deploysure/`, using the venv at `deploysure/.venv`.

## Global Constraints

- Python 3.11 or newer, type hints on public functions, paths with `pathlib`, every subprocess call has a timeout.
- No new dependencies. No database. No em dashes in any document or UI text.
- Version name regex: `[A-Za-z0-9][A-Za-z0-9._-]{0,29}`. `project_id` is the name lowercased, runs of other characters turned into `-`, trimmed, at most 40 characters, never empty.
- Folder copy: existing directory, top-level `*.py` and `pytest.ini` only, at most 200 files, each at most 200 KB, skip `__pycache__`, at least one non-test `.py` file.
- Generated test text uses `repr()` for the title and the JSON strings. Module and function must pass `str.isidentifier()` and not be a keyword.
- `run_release_validation` and `stream_release_validation` keep working with one argument. `final_report` keys and the event shape do not change.
- Demo shop must still give: A = risk 12, DEPLOY, `retry_count` 0, 6 tests; B = risk 87, BLOCK, `retry_count` 1, 20 tests, 18 passing.
- The planted failing tests in `projects/demo-shop/versions/v2.2` are not edited.
- Server stays bound to localhost (uvicorn default). CORS stays limited to localhost.

## Review Focus

- A folder path that does not exist, is a file, has spaces or backslashes: a clear 400, nothing created. Pinned in Task 2.
- A project name that slugifies to an empty string, or to an id already used: 400 for empty, 409 for a duplicate. Pinned in Task 2.
- A changed module that no selected test covers (zero tests selected): must not silently run the whole suite or pass as safe. Expected result is HOLD at minimum. Pinned in Task 3.
- A test case whose title or JSON contains quotes, backslashes, newlines or unicode: the generated file stays valid and runs. Pinned in Task 4.
- A version whose code has a syntax error: the analysis ends with a clear error event, not a hang or a blank page. Pinned in Task 5.

---

### Task 1: Move the demo shop into `projects/` and make the tools project-aware

**Files:**
- Move: `demo_project/v2.0`, `v2.1`, `v2.2` to `projects/demo-shop/versions/<same name>/`
- Create: `projects/demo-shop/project.json`, `projects/demo-shop/versions/v2.0/version.json`, `v2.1/version.json`, `v2.2/version.json`
- Delete: `demo_project/`, `releases/`
- Modify: `tools/code_reader.py`, `tools/diff_tool.py`
- Modify tests: `tests/test_diff_tool.py`, `tests/test_dependency_analyzer.py`, `tests/test_test_runner.py` (imports unchanged, paths now resolved by `release_path`)

**Interfaces:**
- Produces in `tools/code_reader.py`:
  - `PROJECTS_ROOT: Path`, `DEFAULT_PROJECT = "demo-shop"`
  - `project_path(project_id: str) -> Path` returns `PROJECTS_ROOT / project_id`
  - `release_path(version: str, project: str = DEFAULT_PROJECT) -> Path` returns `project_path(project) / "versions" / version`, raises `FileNotFoundError` if missing
  - `load_release(version: str, project: str = DEFAULT_PROJECT) -> dict` returns `{"release_id", "baseline", "title", "notes"}` read from `version.json` (`release_id` is the version name)
  - `DEMO_ROOT` and `RELEASES_DIR` are removed.
- `version.json` fields: `version`, `baseline` (name or null), `title`, `notes`, `created` (ISO text). Demo values: v2.0 baseline null, title "Baseline release", notes "Starting point for comparisons."; v2.1 and v2.2 keep baseline `v2.0` and the title and notes from the old release JSON. `created` values `2026-10-01T00:00:00`, `...01T00:00:01`, `...01T00:00:02` so order is stable.
- `project.json` for demo-shop: `{"id": "demo-shop", "name": "Demo shop", "created": "2026-10-01T00:00:00", "critical_modules": ["payment", "checkout", "refund"], "customer_facing": {"payment": 10, "checkout": 10, "refund": 10, "orders": 8, "notification": 8, "auth": 6}}`.

- [ ] **Step 1: Add the failing tests** to `tests/test_diff_tool.py`:
  - `test_test_files_are_not_code_changes(tmp_path)`: two folders where only `test_a.py` and `conftest.py` differ, `diff_releases(old, new)["changed_files"] == []`.
  - `test_load_release_reads_version_json()`: `load_release("v2.2")["baseline"] == "v2.0"` and `load_release("v2.0")["baseline"] is None`.
- [ ] **Step 2: Run them to see them fail**: `.venv\Scripts\python -m pytest tests/test_diff_tool.py -q` expects failures.
- [ ] **Step 3: Move the folders and write the JSON files** (use a shell move, not a copy, then delete the old folders). Do not touch any file inside the moved version folders.
- [ ] **Step 4: Rewrite `tools/code_reader.py`** to the interface above. Keep `read_source` and `python_files` unchanged.
- [ ] **Step 5: In `tools/diff_tool.py`** make `diff_releases` skip files named `test_*.py` or `conftest.py` (a small `_is_code(path)` helper used on both folders).
- [ ] **Step 6: Run the checkpoint.** Expected: tests that used `load_release` or the old paths in `tests/test_api.py`, `tests/test_server.py` and `tests/test_end_to_end.py` may still fail until Task 3 and Task 5. Everything in `test_diff_tool.py`, `test_dependency_analyzer.py`, `test_test_runner.py`, `test_risk_formula.py`, `test_routing.py`, `test_llm.py`, `test_decision_rules.py` passes.

### Task 2: Project store

**Files:**
- Create: `tools/project_store.py`, `tests/test_project_store.py`
- Modify: `pytest.ini` is unchanged. Tests use `tmp_path` and monkeypatch `code_reader.PROJECTS_ROOT` and `project_store.PROJECTS_ROOT` to a temp folder.

**Interfaces:**
- Consumes: `code_reader.PROJECTS_ROOT`, `project_path`, `release_path`.
- Produces in `tools/project_store.py`:
  - `class ProjectError(ValueError)` with attribute `status: int`; constructor `ProjectError(message: str, status: int = 400)`
  - `slugify(name: str) -> str` raises `ProjectError` (400) if the result is empty
  - `check_version_name(version: str) -> None` raises `ProjectError` (400)
  - `copy_snapshot(src: str, dest: Path) -> None` applies the folder copy rules, writes default `pytest.ini` and `conftest.py` when missing (the conftest content is the hook now in `projects/demo-shop/versions/v2.0/conftest.py`; the pytest.ini content is `[pytest]`, `addopts = --import-mode=importlib -p no:cacheprovider`, `pythonpath = .`, and the `critical` marker line)
  - `create_project(name: str, folder_path: str, version: str = "v1.0", critical_modules: list[str] = ()) -> dict` returns the card dict; 409 if the id exists
  - `add_version(project_id: str, version: str, folder_path: str, notes: str) -> dict` baseline is the newest existing version; 404 unknown project; 409 duplicate version; `title` is the first line of notes truncated to 80, or the version name if notes are empty
  - `load_project(project_id: str) -> dict` returns `project.json`, 404 if missing
  - `list_versions(project_id: str) -> list[dict]` version.json contents plus `last_result` (dict or None), ordered by `created`
  - `project_modules(project_id: str) -> list[str]` non-test, non-conftest `.py` stems of the newest version, sorted
  - `list_projects() -> list[dict]` each `{"id", "name", "version_count", "latest_version", "last_result"}` where `last_result` is the newest version's, or None; sorted by name
  - `get_project(project_id: str) -> dict` project fields plus `versions` and `modules`
  - `save_result(project_id: str, version: str, report: dict) -> None` writes `last_result.json` with `decision`, `risk_score`, `risk_level`, `retry_count`, `at`

- [ ] **Step 1: Write failing tests in `tests/test_project_store.py`** (each with a small source folder built in `tmp_path` containing `shop.py` and `test_shop.py`):
  - `test_slugify`: `"My Shop!"` gives `"my-shop"`; `"!!!"` raises `ProjectError` with status 400; 60 characters are cut to 40.
  - `test_create_project_copies_and_writes_defaults`: result `latest_version == "v1.0"`; the version folder has `shop.py`, `pytest.ini`, `conftest.py`; its `version.json` baseline is None.
  - `test_duplicate_project_is_409` and `test_same_slug_collision_is_409` (`"Shop!"` then `"shop"`).
  - `test_bad_folder_paths_are_400_and_create_nothing`: a path that does not exist, a path that is a file, and a folder with only `test_x.py`; afterwards `list_projects() == []`.
  - `test_folder_path_with_spaces_works(tmp_path)`: source folder named `my folder`.
  - `test_copy_limits`: 201 files raises 400; a 300 KB file raises 400; `__pycache__` contents and non-`.py` files are not copied.
  - `test_add_version_baseline_is_previous`: second version has baseline `"v1.0"`; third has the second.
  - `test_bad_version_names`: `".."`, `"a/b"`, `""`, `"x"*31` raise 400; duplicate version is 409; unknown project is 404.
  - `test_title_is_first_note_line`.
  - `test_modules_exclude_tests`: `project_modules(id) == ["shop"]`.
  - `test_list_projects_card_has_last_result_after_save`.
- [ ] **Step 2: Run to see failures**: `.venv\Scripts\python -m pytest tests/test_project_store.py -q`.
- [ ] **Step 3: Implement `tools/project_store.py`** to the interface. Write JSON with `indent=2`. Build all paths from `slugify` or `check_version_name` output only. Resolve `folder_path` with `Path(folder_path).expanduser()`.
- [ ] **Step 4: Run to see passes**, then the checkpoint.

### Task 3: Per-project settings in tools and agents, and the empty selection fix

**Files:**
- Modify: `tools/test_runner.py`, `tools/risk_formula.py`, `orchestration/state.py`, `orchestration/graph.py`, `agents/planner.py`, `agents/change_analyzer.py`, `agents/impact_analyzer.py`, `agents/test_selector.py`, `agents/test_executor.py`, `agents/risk_assessor.py`, `api.py`
- Modify tests: `tests/test_test_runner.py`, `tests/test_risk_formula.py`, `tests/test_end_to_end.py`, `tests/test_api.py` (drop `test_list_releases`)

**Interfaces:**
- Consumes: `load_project`, `release_path`, `load_release` from Tasks 1 and 2.
- Produces:
  - `test_runner.is_critical_file(file: str, critical_modules) -> bool` true when `Path(file).stem == "test_" + m` for an `m` in `critical_modules`
  - `collect_tests(release_dir, timeout=60, critical_modules=frozenset())`, `parse_junit(xml_path, critical_modules=frozenset())`, `run_tests(release_dir, test_ids=None, timeout=..., critical_modules=frozenset())`. A test is critical if its junit property is `True` or `is_critical_file(its file)`.
  - `risk_formula.calculate_risk(..., critical_modules=CRITICAL_MODULES, customer_facing=CUSTOMER_FACING)` keyword parameters added at the end; behavior with defaults unchanged.
  - `ReleaseState` gains `project_id: str`; `graph.initial_state(release_id: str, project_id: str = "demo-shop")`.
  - `api.stream_release_validation(release_id: str, project_id: str = "demo-shop")`, `run_release_validation(release_id, project_id="demo-shop")`, `check_release(release_id, project_id="demo-shop")` (raises `ProjectError` 404 for unknown project or version, 400 for bad id or for a version whose baseline is None). `api.list_releases` is removed.

- [ ] **Step 1: Write failing tests:**
  - `test_runner`: `test_critical_by_module_name(tmp_path)`: a folder with `test_pay.py` (one failing test, no marker); `run_tests(folder, critical_modules={"pay"})["failed_critical"]` has that test, and with no critical modules it is empty.
  - `risk_formula`: `test_custom_weights_and_critical_modules`: `calculate_risk(["ledger"], 0, 0, 0, 0, critical_modules={"ledger"}, customer_facing={"ledger": 7})["score"] == 37`.
  - end to end: change `run()` in `tests/test_end_to_end.py` to pass nothing new (default project) and keep all three scenarios; add `test_change_with_no_covering_tests_holds(monkeypatch, tmp_path)`: build a temporary project (monkeypatch `PROJECTS_ROOT` in `code_reader` and `project_store`) whose second version changes a module that no test imports, run the graph with mock LLM and `DEMO_SEED_WRONG_DECISION=0`, assert final decision is `HOLD` and `test_results["error"]` mentions no tests.
- [ ] **Step 2: Run to see failures.**
- [ ] **Step 3: Implement `test_runner` changes** as above.
- [ ] **Step 4: Implement `risk_formula` keyword parameters.**
- [ ] **Step 5: Thread `project_id` through the graph.** Each agent reads `state["project_id"]` and passes it to `release_path(..., project)` and `load_release(..., project)`. `change_analysis` uses `state["baseline"]` set by `planner` from `load_release(...)["baseline"]`. `test_selection` and `risk_assessment` read `load_project(project_id)["critical_modules"]` and `["customer_facing"]` instead of the module constants. In `risk_assessment`, a changed module missing from the project's `customer_facing` map gets 10 if critical else 5. `test_execution` passes the project's critical modules to `run_tests`.
- [ ] **Step 6: Empty selection.** In `agents/test_executor.py`, if `selected_tests` is empty return a `test_results` with `error: "no tests cover this change"`, total 0, and do not call pytest. The rule engine already turns a test error into HOLD at minimum.
- [ ] **Step 7: Update `api.py`** to the interfaces above (project default, `check_release` using `load_release`, `ProjectError`).
- [ ] **Step 8: Run the checkpoint.** Expected: everything passes except `tests/test_server.py` (fixed in Task 5). Demo scenarios still 12/87 with 6/20 tests.

### Task 4: Test cases

**Files:**
- Create: `tools/test_cases.py`, `tests/test_test_cases.py`
- Modify: `agents/test_selector.py` (call `materialize_tests` first)

**Interfaces:**
- Consumes: `project_store.ProjectError`, `load_project`, `project_modules`; `code_reader.project_path`.
- Produces in `tools/test_cases.py`:
  - `add_test_case(project_id: str, title: str, module: str, function: str, args: str, expected: str, critical: bool) -> dict` stores `projects/<id>/tests/case_<n>.json` with `id` (int, next free), the fields, `critical`; validation per Global Constraints plus: title 1 to 80 characters, `module` must be in `project_modules`, `args` must be valid JSON that parses to a list, `expected` valid JSON
  - `list_test_cases(project_id: str) -> list[dict]` ordered by id
  - `delete_test_case(project_id: str, case_id: int) -> None` 404 if missing
  - `render_test(case: dict) -> str` returns the generated file text from the spec
  - `materialize_tests(project_id: str, version_dir: Path) -> int` removes `test_case_*.py` in `version_dir`, writes `test_case_<id>.py` per case, returns the count
- Generated test id is `test_case_<id>.py::test_case`.

- [ ] **Step 1: Write failing tests** in `tests/test_test_cases.py` (temporary project as in Task 2, module `shop.py` with `def add(a, b): return a + b`):
  - `test_add_and_list`: ids are 1 then 2; `delete_test_case` removes one; deleting again is 404.
  - `test_validation`: module not in project, function `"class"` or `"a b"`, args `"{}"` or `"not json"`, empty title, 81-character title: each raises `ProjectError` 400.
  - `test_generated_test_passes_and_fails_correctly`: add case `add`, args `"[1, 2]"`, expected `"3"`, then `materialize_tests` into the version folder and `run_tests` on it: one passed. A second case with expected `"4"` gives one failed.
  - `test_critical_checkbox_sets_marker`: critical case fails, `failed_critical` has its id.
  - `test_hostile_text_stays_valid`: title `'He said "hi" \\ \n O\'Neil é'`, args `'["a\\"b", 1]'`, expected `'"a\\"b1"'` with function `add`: the generated file compiles (`compile(text, "x", "exec")`) and running it works.
  - `test_materialize_removes_deleted_cases`.
- [ ] **Step 2: Run to see failures.**
- [ ] **Step 3: Implement `tools/test_cases.py`.** `render_test` builds the text with `repr(title)`, `repr(args)`, `repr(expected)` and the validated identifiers only.
- [ ] **Step 4: In `agents/test_selector.py`** call `materialize_tests(state["project_id"], release_dir)` before `collect_tests`.
- [ ] **Step 5: Run the checkpoint.**

### Task 5: HTTP routes and error events

**Files:**
- Modify: `server.py`, `api.py` (`stream_release_validation` calls `save_result` after building the final report)
- Modify tests: `tests/test_server.py`, `tests/test_api.py`

**Interfaces:**
- Consumes: everything from Tasks 2 to 4.
- Produces routes exactly as in the spec: `GET/POST /projects`, `GET /projects/{id}`, `POST /projects/{id}/versions`, `GET/POST /projects/{id}/tests`, `DELETE /projects/{id}/tests/{case_id}`, `POST /projects/{id}/versions/{version}/analyze`. Request bodies are pydantic models. `ProjectError` becomes `HTTPException(status_code=err.status, detail=str(err))` through one exception handler. The `/releases` and `/analyze/{release_id}` routes are removed. The UI mount stays last. `sse()` and `_events` stay.

- [ ] **Step 1: Write failing tests** in `tests/test_server.py` calling the route functions directly with a temporary project root (as in Task 2):
  - `test_create_project_then_list_cards`, `test_add_version_then_get_project_shows_two_versions`, `test_duplicate_project_raises_409`, `test_unknown_project_is_404`, `test_add_and_delete_test_case_routes`.
  - `test_analyze_unknown_version_is_404_before_streaming`; `test_analyze_first_version_is_400` (baseline null).
  - `test_syntax_error_version_gives_error_event`: add a version whose `shop.py` has a syntax error; iterate the response body of `analyze(...)`; the last SSE event has `node == "error"` and a non-empty message.
  - In `tests/test_api.py`: `test_save_result_after_run`: after `run_release_validation("v2.1")`, `list_versions("demo-shop")` shows `last_result.decision == "DEPLOY"`. To keep the repo clean, monkeypatch `save_result` writes into a temp copy, or assert and then restore by re-running; the demo's `last_result.json` files are allowed to exist.
- [ ] **Step 2: Run to see failures.**
- [ ] **Step 3: Implement the routes and the exception handler.**
- [ ] **Step 4: In `api.stream_release_validation`** save the result just before yielding the final event.
- [ ] **Step 5: Run the checkpoint.** All tests pass. Then start the server with `DEPLOYSURE_LLM=mock`, and check with curl: `GET /projects` lists demo-shop; `POST /projects/demo-shop/versions/v2.2/analyze` streams events ending in a `final` event with decision BLOCK and `retry_count` 1.

### Task 6: UI home page, project page and dialogs

**Files:**
- Modify: `ui/index.html` (single file)

**Interfaces:**
- Consumes the Task 5 routes. Hash routes: `#/` home, `#/p/<id>` project.
- Produces: no code interface; behavior per spec UI section.

- [ ] **Step 1: Router and home page.** Cards from `GET /projects` with name, latest version, last verdict and risk (use the existing verdict colors and a word, not color only), version count, last run time. A search box filters by name. An **Add project** button opens a `<dialog>` with name, folder path, first version name, critical modules; server errors show inside the dialog. Empty state text: "No projects yet. Add one to start."
- [ ] **Step 2: Project page.** Keep the existing stage and agent rail. Replace the radio list with a version timeline from `GET /projects/{id}` (newest first, baseline and first note line visible, last verdict word). A version with baseline null shows "Baseline, nothing to compare" and cannot be analyzed. **Add version** dialog: version name, folder path, notes. Analyze posts to `/projects/{id}/versions/{version}/analyze` and uses the existing event handlers. Back link to home.
- [ ] **Step 3: Test cases section** under the ledger: a list (title, module.function, critical word, delete button) and an **Add test case** dialog with a module select (from the project's `modules`), function, arguments JSON (default `[]`), expected JSON, Critical checkbox. In the test grid tooltips and the failed list, show the test case title when the id is `test_case_<n>.py::test_case`.
- [ ] **Step 4: Error event.** The `error` event shows its message in the verdict box and the trace. All server text inserted with `textContent` (keep the `h()` helper).
- [ ] **Step 5: Verify in the browser** (server on localhost with `DEPLOYSURE_LLM=mock`): home shows the demo shop card; open it and analyze v2.1 (DEPLOY, risk 12) and v2.2 (BLOCK, risk 87); check the layout at 1440 and 375 widths with no horizontal scroll.

### Task 7: End-to-end check with a second project, docs and final run

**Files:**
- Modify: `DEMO_NOTES.md`, `requirements.txt` unchanged
- Create (outside the repo, in the scratchpad): a tiny sample project with `calc.py` and `test_calc.py` in two folders `calc_v1` and `calc_v2` where v2 changes `calc.add` to be wrong

- [ ] **Step 1: In the UI**, add project "Calculator" from `calc_v1` (critical module `calc`), add version `v2` from `calc_v2`, add a test case (module `calc`, function `add`, args `[2, 3]`, expected `5`, Critical ticked). Analyze `v2`. Expected: the new test fails as a critical test and the verdict is BLOCK.
- [ ] **Step 2: Update `DEMO_NOTES.md`** with the new flow: how to add a project, a version and a test case, and the limits (flat folders, Python and pytest, function equals expected value, critical modules are a human choice).
- [ ] **Step 3: Run the full suite**: `.venv\Scripts\python -m pytest tests/ -q`. Expected: all pass, and the demo numbers in the Global Constraints still hold in the UI.
