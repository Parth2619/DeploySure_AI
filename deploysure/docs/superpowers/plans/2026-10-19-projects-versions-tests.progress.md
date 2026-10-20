# SDD ledger: plan: docs/superpowers/plans/2026-10-19-projects-versions-tests.md

Executor: inline (Native). Spec read. Folder `deploysure/` has no git repo and no worktree, so there are no commits, BASE ids or task-start scripts. This file is the record.

Ruling: no git repository: use this ledger and the full test run as the per-task gate instead of commits: a mistake cannot be rolled back by git, so each task ends with a full `pytest tests/` run: cost if wrong: no undo.
Pre-flight: Task 1 produces release_path/load_release(project) consumed by 2, 3, 4. Task 2 produces ProjectError/load_project/project_modules consumed by 3, 4, 5. Task 3 produces project_id state consumed by 4, 5. Task 4 produces materialize_tests consumed by Task 3's test_selector (wired in Task 4). No conflicts found.
Task 1: complete (tests: pytest tests/ --ignore=test_api,test_server -> 62 passed; api/server tests wait for Tasks 3 and 5)
Task 2: complete (tests: test_project_store 14/14; suite excluding api/server green)
Task 3: complete (tests: pytest tests/ --ignore=test_server -> 89 passed; demo 12/87 unchanged). Ruling: decision prompt now carries tests_could_not_run and the mock reads it, so a no-tests change gets HOLD on the first pass instead of 3 Critic rejections - cost if wrong: none (policy floor unchanged).
Task 4: complete (tests: pytest tests/ --ignore=test_server -> 103 passed). Ruling: materialize_tests runs at the start of impact_analysis, not test_selection as the plan said - the import graph is built in impact_analysis and would otherwise not see generated tests (found by a failing end-to-end test) - cost if wrong: none.
Task 5: complete (tests: pytest tests/ -> 114 passed; curl: /projects, analyze v2.2 BLOCK, 404 unknown version, 400 first version, 400 bad path, UI 200)
Task 6: complete (UI verified in browser: home, add project with error then success, add version with suggested name, add test case, analyze, demo-shop v2.2 gives BLOCK risk 87, 375px width no horizontal scroll). Task 7: complete (end-to-end second project 'Calculator' through the UI gave BLOCK on a critical user test; DEMO_NOTES updated; full suite 115 passed). Ruling: demo seed now applies only to project demo-shop - a user's own project should not show a forced wrong answer - cost if wrong: a teacher sees no seed on his project, which is the intent.
Final review: fresh reviewer (opus) found 14 items. Re-graded: 1 Critical (broken test file silently dropped, release can reach DEPLOY), 2 to 7 Important, 8 to 14 Minor.
Final: minor (deferred): 8 concurrent analyses of one version rewrite generated test files
Final: minor (deferred): 9 Windows version names with a trailing dot or device names (NUL) give a raw 500
Final: minor (deferred): 10 a folder path pasted with surrounding quotes is not accepted
Final: minor (deferred): 11 analyze route has no body, so a cross-site POST can trigger it (local demo only)
Final: minor (deferred): 12 cards show a stale verdict after test cases change
Final: minor (deferred): 13 syntax error message has no file name
Final: fixed 1 broken test collection no longer dropped (CollectionError, selection_error gives HOLD) - test_collection_error_is_raised_not_dropped and test_broken_test_collection_never_deploys RED to GREEN, suite 125/125
Final: fixed 2 marker-critical counted without conftest hook (critical_tests passed to the runner) - test_marker_critical_counts_even_without_the_conftest_hook RED to GREEN
Final: fixed 3 changed module with no test now HOLD (uncovered_modules, results.uncovered) - test_uncovered_changed_module_prevents_deploy RED to GREEN
Final: fixed 4 module must be a Python name - test_module_must_be_a_python_name RED to GREEN
Final: fixed 5 damaged JSON gives a clear error and one bad project does not hide the rest - test_damaged_project_file_does_not_hide_other_projects and test_version_file_missing_a_field_is_a_clear_error RED to GREEN
Final: fixed 6 demo shop protected (protected flag in project.json, 403) - test_demo_shop_is_protected_from_new_test_cases and test_protected_project_rejects_new_versions RED to GREEN
Final: fixed 7 failed copy leaves nothing behind - test_failed_copy_leaves_nothing_behind RED to GREEN
Final: fixed 14 em dashes removed from the ledger
