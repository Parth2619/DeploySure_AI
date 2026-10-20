# Projects, versions and test cases: design

Date: 19 Oct 2026. Owner: Manc. Status: waiting for review.

## Goal

Today DeploySure only knows the demo shop. Manc wants a teacher to be able to add any small Python project, add later versions of it, and add test cases, all from the UI, then analyze a version with the same agents and Critic.

Success looks like this:
- A home page lists projects as cards and has an Add project form.
- A project page shows its versions as a timeline, with Add version and Analyze.
- A project has test cases that can be added from the UI and run against every version.
- The demo shop is the first project and still gives risk 12 and 87 with the same decisions.
- The public interface in CLAUDE.md does not break.

Not included: zip upload, editing or deleting projects and versions, tests that expect an error, logins, a database, non-Python projects, nested package folders. Deleting a test case is allowed.

Research used: project cards with last status and search (CircleCI, Bitrise), version timelines with an Add version flow (Jira releases), test case fields title, priority, steps and expected result (Zephyr, TestRail).

## Storage: plain folders and JSON

```
projects/<project_id>/project.json
projects/<project_id>/versions/<version>/*.py        code snapshot (top level files only)
projects/<project_id>/versions/<version>/version.json
projects/<project_id>/versions/<version>/last_result.json
projects/<project_id>/tests/case_<n>.json            test case definitions
```

- `project.json`: `id`, `name`, `created`, `critical_modules` (list), `customer_facing` (module to 0..10, optional).
- `version.json`: `version`, `baseline` (a version name or null), `title`, `notes`, `created`.
- `last_result.json`: `decision`, `risk_score`, `risk_level`, `retry_count`, `at`. Written when an analysis finishes. Used by the cards.
- `project_id` is the project name made lowercase with every run of other characters turned into `-`, at most 40 characters. A duplicate id is an error.
- A version name must match `[A-Za-z0-9][A-Za-z0-9._-]{0,29}`. This makes `..` and path separators impossible.
- The demo moves in as project `demo-shop`: `demo_project/v2.x` becomes `projects/demo-shop/versions/v2.x`, and each `releases/release_v2_x.json` becomes that version's `version.json`. v2.0 has baseline null. v2.1 and v2.2 keep baseline `v2.0`. The old `demo_project/` and `releases/` folders are removed.
- demo-shop `critical_modules` is payment, checkout, refund. Its `customer_facing` map is the one now in `tools/risk_formula.py`, so scores do not change.

## Behavior

**Add project.** Fields: name, folder path of the first version, first version name (default `v1.0`), critical modules (comma separated, optional). The folder is copied into `versions/<version>/`. That version has baseline null.

**Add version.** Fields: version name, folder path, release notes. The baseline is the newest earlier version. The title is the first line of the notes, at most 80 characters.

**Folder copy rules.** The path must be an existing directory. Copy only top-level `*.py` files and `pytest.ini`. At most 200 files, each at most 200 KB. Skip `__pycache__`. The folder must contain at least one non-test `.py` file. If no `pytest.ini` was copied, write one with `pythonpath = .`, `--import-mode=importlib -p no:cacheprovider` and the `critical` marker. If no `conftest.py` was copied, write the one that reports the critical marker into the junit XML.

**Critical tests.** A test is critical if it has the `critical` marker, or if its file is `test_<m>.py` for a module `m` in the project's critical modules. This replaces the fixed `CRITICAL_MODULES` constant in the agents.

**Customer facing weight.** The project's map is used. A changed module missing from it gets 10 if critical, else 5.

**Add test case.** Fields: title (1 to 80 characters), module (a module of the project's newest version), function name, arguments as a JSON array, expected result as JSON, and a Critical checkbox. Module and function must be valid Python identifiers and not keywords. Arguments must parse as a JSON list. The definition is saved as `case_<n>.json`. Test cases belong to the project, not to a version.

**Generated test.** At the start of the test selection step the agent deletes old `test_case_*.py` in the version folder and writes one per test case:
```python
import json
import pytest
import <module>

TITLE = <repr(title)>

@pytest.mark.critical        # only if Critical is ticked
def test_case():
    assert <module>.<function>(*json.loads(<repr(args_json)>)) == json.loads(<repr(expected_json)>)
```
The JSON text and title are inserted with `repr`, so they stay string literals. The UI shows the title for a result by looking up the test id `test_case_<n>.py::test_case`.

**Analyze.** Runs the existing graph on `(project_id, version)` against that version's baseline. A version with baseline null cannot be analyzed and the UI disables the button. The diff ignores `test_*.py` and `conftest.py`, so generated tests never count as code changes.

## Interfaces

Python (backward compatible, project defaults to `demo-shop`):
```python
run_release_validation(release_id: str, project_id: str = "demo-shop") -> dict
stream_release_validation(release_id: str, project_id: str = "demo-shop") -> Iterator[dict]
```
`final_report` keys and the event shape are unchanged. `ReleaseState` gains `project_id`. `release_path`, `load_release` and the agents take the project from the state.

HTTP (`server.py`). Errors are `{"detail": "..."}` with 400 for bad input, 404 for unknown project or version, 409 for a duplicate:
```
GET    /projects                                  cards: id, name, version count, latest version, last_result
POST   /projects                                  {name, folder_path, version?, critical_modules?}
GET    /projects/{id}                             project, versions with last_result, modules
POST   /projects/{id}/versions                    {version, folder_path, notes}
GET    /projects/{id}/tests                       list of test cases
POST   /projects/{id}/tests                       {title, module, function, args, expected, critical}
DELETE /projects/{id}/tests/{case_id}
POST   /projects/{id}/versions/{version}/analyze  SSE, same events as today
```
The old `GET /releases` and `POST /analyze/{release_id}` are replaced by these routes.

## UI

One page, hash routes. `#/` is the home page. `#/p/<id>` is the project page.
- **Home:** project cards (name, latest version, last verdict and risk, how many versions, when last run), search, Add project dialog, empty state.
- **Project page:** the current console. The left rail shows a version timeline (newest first, each with baseline, notes and last verdict) in place of the two release buttons, plus Add version and Analyze. A Test cases section lists cases with delete and has an Add test case dialog.
- Dialogs are `<dialog>` elements. Errors from the server appear inside the dialog. All text is inserted with `textContent`.

## Safety

Pytest executes the project's own code and the generated tests on this laptop. This is accepted for a local demo with dummy data. The server stays bound to localhost (the uvicorn default) and CORS stays limited to localhost. Folder copying is restricted as above. Ids and names are checked before any path is built. No code from the UI is pasted into a file: only validated identifiers and `repr`-quoted strings.

## Testing

New unit tests: project store (create, versions, baseline, duplicate, bad names, copy limits), test case validation and generated file content (including a title and JSON containing quotes), critical detection by module name, risk weights default, the new routes. Existing tests are updated for the new paths. Must pass: all tests, demo-shop A is risk 12 DEPLOY, B is risk 87 BLOCK with `retry_count` 1, and a manual run of the UI creating a second small project, adding a version and a test case, then analyzing it.

## Open limits to state in the viva

Flat folders only, Python and pytest only, tests compare a function result to an expected value only, and critical modules are a human choice.
