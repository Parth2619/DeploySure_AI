# DeploySure AI: demo notes

## Numbers the deck must show (measured 16 Oct 2026)

| Item | Scenario A (v2.1) | Scenario B (v2.2) |
|---|---|---|
| Changed file | `notification.py` (`order_confirmation`) | `payment.py` (`refund_amount`) |
| Tests selected | 6 of 20 | 20 of 20 |
| Test result | 6 passed, 0 failed | 18 passed, 2 failed |
| Failed tests | none | `test_refund.py::test_refund`, `test_payment.py::test_refund_amount_is_full` |
| Risk score | 12 (LOW) | 87 (CRITICAL) |
| First decision | DEPLOY | DEPLOY (seeded) |
| Critic | PASS | FAIL, then PASS on the second pass |
| Final decision | DEPLOY | BLOCK |
| `retry_count` | 0 | 1 |

These match the deck figures in CLAUDE.md (6 selected, 20 tests and 18 passing, risk 12 and 87). The deck file `DeploySure_AI_CA3.pptx` is not on this computer, so slides 9 and 10 were NOT compared. Check them against this table.

Honest notes for the slides:
- The risk weights in `tools/risk_formula.py` were chosen so the two scenarios give 12 and 87. Say "calibrated on the demo", not "validated".
- Scenario B's first DEPLOY is forced by `DEMO_SEED_WRONG_DECISION`. Say so out loud.
- Scenario B runs all 20 tests because payment is a critical module, by rule.

## Run times (cold start, this laptop, nothing cached)

| Mode | A | B |
|---|---|---|
| Groq `openai/gpt-oss-120b` (internet and `GROQ_API_KEY`) | not measured yet | not measured yet |

Backup transcripts of six runs (two project releases, four app commit pairs) are in `backup/`. They were made with no key and no internet, so they show the fallback path. Regenerate them with `backup/make_backup.ps1`. A screen recording still has to be made by hand.

## Five minute script

1. Problem (30 s): CI says tests pass or fail, nobody weighs risk or checks the call itself.
2. Run `python -m deploysure.cli v2.1` (30 s): agents tick through, DEPLOY, risk 12, Critic PASS.
3. Run `python -m deploysure.cli v2.2` (90 s): 20 tests, 2 critical failures, risk 87. First decision DEPLOY, point out it is the seeded wrong answer. Critic FAIL, replan, BLOCK, Critic PASS.
4. Architecture (60 s): which nodes use the LLM and which are plain Python.
5. Limits (30 s): evidence based risk assessment, not a guarantee of production safety.

Fallback if Groq or the internet is unavailable: every AI step uses its deterministic default, the trace says so, and the decisions still come from the rules.

## Viva answers

- **Why a Critic?** A single model can be confidently wrong. The Critic is an independent check against a fixed policy, so a wrong decision is caught instead of shipped.
- **What does the LLM do and what does Python do?** The LLM writes the plan, the explanations and the decision recommendation. Python does the diffing, import graph, test selection rule, real pytest runs, the risk score and the Critic's PASS or FAIL.
- **What if the model hallucinates?** It cannot invent test results or tests, those come from pytest. Invalid JSON is retried once, then a deterministic default is used and the trace says so. A wrong decision is rejected by the rule check. After 2 failed retries the run goes to manual review as HOLD.
- **How is it different from normal CI?** CI reports pass or fail per test. This adds impact analysis, a risk score, a deploy decision and a second check on that decision.
- **How is it different from BugTriage?** BugTriage is about sorting reported bugs. This decides whether a release may ship, from evidence gathered by running tests.
- **Known weakness:** the Critic only knows the rules in `minimum_decision`. It cannot catch a risk that the tests and formula do not see. Also, the model prompt includes the policy, so a correct model answer is partly instruction following.
- **Prior art:** closest open projects are a hackathon project called DeployGuard and the TDAD test-impact tool. Their repo details were not fully verified, see `../reports/DeploySure AI build research.md`.

## Projects, versions and test cases (UI)

Start the server from the folder above `deploysure/`, then open http://localhost:8000:

    $env:GROQ_API_KEY = "<your key>"    (set it in this window only, never in a file or in chat)
    .\deploysure\.venv\Scripts\python -m uvicorn deploysure.server:app --port 8000

- **Home page:** one card per project with its latest verdict. Add project takes a name, the folder of the first version, and the critical modules.
- **Project page:** the versions are a list on the left. Add version takes a version name, a folder and notes. Each new version is compared with the one before it. The first version is the baseline and cannot be analyzed alone.
- **Project test files:** in the list, "Edit file" opens a project test file (newest version only, with a syntax check). In the Demo shop, test_payment.py and test_refund.py are locked (View file only) so the planted failing tests stay as they are. The other Demo shop test files can be edited. A copy of the original Demo shop is in backup/demo-shop-original/.
- **Test cases:** The list "All tests in the newest version" shows every test before any analysis. Your own cases have Edit and Delete. Add test case takes a title and your own Python (pytest) code, for example `import payment` then `def test_refund(): assert payment.refund_amount(100.0) == 100.0`. Tick Critical if a failure must block the release. A test case runs against every version.
- **What a new project needs:** Python files directly in the folder (no sub-folders), pytest tests next to them, at most 200 files of 200 KB each. DeploySure copies the code, so the original folder is not touched.
- **Critical modules matter:** list the modules where a failure must block a release (for example payment). Tests in `test_<module>.py` for those modules count as critical. Without any critical modules or critical tests, a failure leads to HOLD, not BLOCK.
- **The demo seed** (forced wrong first DEPLOY) only happens for the Demo shop project.
- **A change that no test covers** ends in HOLD, because untested is not safe.

Limits to say out loud: flat folders only, Python and pytest only, test cases compare one function result with an expected value, and pytest really runs the project's code on this laptop, so only use dummy projects and keep the server on localhost.

## App mode: a whole app (frontend plus backend) in a git repo

Compares two commits of an app and says whether the change breaks it, and which layer is at fault.

    python -m deploysure.app_cli demo_apps/tinyshop v1.2 v2.2-contract-break      (run from the folder above deploysure/)

What it does: scans what changed across the whole repo, lets the AI write API checks and browser click-throughs, starts the old
and the new version side by side, runs the same checks on both, then decides which layer is at fault: **frontend**, **backend**
or **connection** (the frontend and backend no longer agree). The Critic enforces a rule floor in code, like in project mode.

How the agents work together (app mode): they share one state and send each other messages, shown in the UI under
**What the agents told each other** and, with **Expand**, in the pipeline details (a table of which agent writes and which reads each piece of data).
- Change scan tells the Planner what changed. The **Planner reads that scan** and chooses what to test first (api_contract, page_behavior, data_values, config_and_dependencies). Without the AI it chooses by fixed rules.
- The Planner's choice goes into the **Check writer's prompt**, so a different plan gives different checks.
- The Differential run runs old and new. If AI-written checks were **unreliable** (the old version already failed them), it **sends them back to the Check writer once** to be rewritten, then runs again.
- Layer attribution and Risk send their findings to the Decision. The Decision sends its recommendation to the Critic. On FAIL the Critic **challenges** the Decision with the broken rule, up to 2 times.
- Order: change scan, planner, check writer, differential run, layer attribution, risk, decision, critic.

The demo app is `demo_apps/tinyshop` (rebuild it with `python -m deploysure.demo_apps.build_tinyshop <folder>`). Its commits:

| Compare | Expected result |
|---|---|
| v1.1 to v1.2 | DEPLOY, risk 8, no faulty layer (a new field and a config key, nothing breaks) |
| v1.2 to v2.0-backend-bug | HOLD, risk 38, layer backend (the order total ignores the quantity) |
| v1.2 to v2.1-frontend-bug | BLOCK, risk 73, layer frontend (the page calls `/api/product`, which does not exist) |
| v1.2 to v2.2-contract-break | BLOCK, risk 100, layer connection (the API renamed `price`, the page still reads it) |

None of the three breaks is caught by the app's own tests, which pass on every commit. That is the point of the demo.

Limits to say out loud:
- Heuristics read FastAPI and Flask routes and fetch/axios calls. Other stacks are not understood yet.
- The app runs with this laptop's Python and installed packages, so it must work with them. Use dummy apps only.
- Checks only cover the inputs and clicks they try. A bug on an untried path is not found.
- Without internet or a Groq key, the AI steps use deterministic probes and a generic smoke click-through. The results above still hold.
- Browser checks need Playwright and Chromium (`python -m playwright install chromium`).

### App mode in the UI

Open http://localhost:8000. Connect app takes a name and the repo folder (the example buttons fill in the two demo repos).
The app page has the commit timeline on the left, the layer chain (Frontend, Connection, Backend) and the evidence on the right.

- **Watch** (checkbox on the left): while the page is open it checks the repo every 4 seconds. A new commit is flagged "new" and, with Watch on, analyzed against its parent without a click. Say out loud that this is polling in the page, not a git hook or a background service.
- **Live demo repo:** connect `demo_apps/tinyshop_live` (only the good history). Turn Watch on, then "Simulate a developer commit" and pick a change. This adds a real commit to that demo repo only, the server refuses it for any other folder. To reset it, delete the folder and run `python -m deploysure.demo_apps.build_tinyshop live demo_apps/tinyshop_live`.
- **Compare any two commits** takes tags, branches or shas. **Remove this app** forgets it and its saved analyses, the repo is never touched.
- One analysis runs at a time. A second request shows "another app analysis is running".

## Five minute script, app mode (the stronger demo)

1. Problem (30 s): the app's own tests pass on every commit, yet three of the commits break it. Nobody says which layer.
2. Connect `tinyshop_live`, Watch on (20 s).
3. Simulate the frontend bug (60 s): the page notices the commit by itself, agents tick through, BLOCK, risk 73, Frontend highlighted, reason "frontend/app.js calls GET /api/product". Say the AI is not in the verdict: the layer rules and the Critic floor are plain code.
4. Open `tinyshop`, click the contract-break commit (60 s): BLOCK, risk 100, Connection highlighted. The same page change fails because the API renamed `price`. This is the case Manc was asked about: the backend looks broken to the page, the cause is the contract.
5. Architecture and the Critic (60 s): which steps use the AI (plan, check writing, explanations, decision text) and which are code (scan, runs, layer, risk, floor). Seeded wrong decision only exists in project mode, say so.
6. Limits (30 s): evidence based, FastAPI/Flask plus plain frontends only, checks only cover what they try.

## Before you present

- Set `GROQ_API_KEY` in your own window if you have internet. Without it everything still works, the text says "AI not used".
- Rebuild `tinyshop_live` so it has only three commits (see above) and make sure Watch on that app is clean: remove and reconnect it.
- Run `python -m playwright install chromium` once on the demo laptop, and run one analysis before the slot to warm things up.
- Close anything on port 8000, then start the server. If the live demo fails, show `backup/app_*.txt` and `backup/project_*.txt`.
- Real Groq output has not been tested yet. Do one run with the key before the demo and read the Decision and Critic text.
