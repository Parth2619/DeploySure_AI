# DeploySure AI: project guide

Owner: Manc. A multi-agent system that decides whether a software change is safe to ship (DEPLOY, HOLD or BLOCK), and a Critic agent that checks the decision. This guide explains what was built, what it uses and how every part works. The app part (mode 2) gets the most space.

## 1. What it is, in short

DeploySure has two modes that share one idea: gather real evidence with plain code, let an AI recommend a decision, then let a Critic check that decision against fixed rules.

| | Mode 1: Python projects | Mode 2: Apps (the main part) |
|---|---|---|
| Input | A Python project with versions (v2.0, v2.1 ...) | A whole web app in a git repo: frontend and backend |
| Compares | Two versions in folders | Two commits |
| Evidence | Real `pytest` runs | The old and new app run side by side: API calls and a real browser |
| Finds | Whether the release is safe | Whether the change is safe, and which layer is at fault: frontend, backend or the connection |
| Demo | The Demo shop | TinyShop and PriceRight |

The rule that runs through the whole project: **an agent reasons, a tool executes, LangGraph orchestrates.** The AI never invents test results, never runs code and can never be less cautious than the rules.

## 2. What is used

| Part | Technology | Why |
|---|---|---|
| Language | Python 3.11 or newer | Course requirement |
| Orchestration | LangGraph 1.2 (`StateGraph`) | Agents as graph nodes, a shared state, conditional edges and loops with a cap |
| AI | Groq API, model `openai/gpt-oss-120b`, through plain `httpx` | Free tier, large model. Temperature 0, fixed seed, JSON replies validated with pydantic |
| Web server | FastAPI + uvicorn, Server-Sent Events | Streams each agent's result to the page as it finishes |
| Browser checks | Playwright 1.64 with Chromium | A real browser clicks through the old and new page |
| Git | The `git` command, read-only | Commits, diffs, archives of a commit |
| Tests | pytest | 451 tests, none of them calls Groq |
| UI | One HTML page, plain CSS and JavaScript, no framework | Easy to explain, nothing to build |
| Deploy (optional) | EC2, nginx with a password, systemd | See `deploy/AWS_GUIDE.md` |

There is no database. Everything is files and JSON.

## 3. The AI handling (`models/llm.py`)

One function, `ask(prompt, schema, task=..., default=...)`:
- Sends the prompt to Groq and asks for JSON only. The reply is validated against a pydantic schema.
- On a bad answer or any error it retries once, then returns the caller's fixed default and says the AI was not used. The trace line says why, for example "AI not used, used fixed rules. Reason: ...".
- The key comes from the `GROQ_API_KEY` environment variable, or from `deploysure/.env` (git-ignored). It is never in the code and never in a prompt.
- Every call is logged with its prompt and answer (`call_log`, last 40). The pipeline details view in the UI uses this.

With no key or no internet, every AI step uses its fixed default, and the verdicts still come out right.

## 4. Repository layout

```
deploysure/
  agents/         the reasoning steps
                  mode 1: planner, change_analyzer, impact_analyzer, test_selector, test_executor,
                          risk_assessor, decision_agent, critic
                  mode 2: app_nodes.py (scanner, planner, test writer, test runner),
                          app_judge.py (fault finder, risk scorer, decider, critic), check_writer.py
  orchestration/  the LangGraph graphs and state
                  graph.py + state.py (mode 1), app_graph.py + app_state.py (mode 2), routing.py
  tools/          the execution: git_tool, app_map, app_scan, app_runner, api_checks, browser_checks,
                  layer_verdict, app_policy, app_store, project_store, test_runner, risk_formula ...
  models/llm.py   the one place that talks to Groq
  api.py          entry points for mode 1: run/stream_release_validation
  app_api.py      entry points for mode 2: run/stream_app_validation
  server.py       FastAPI app for mode 1 and the UI files
  server_apps.py  the routes for mode 2 (apps)
  web_common.py   shared server helpers (SSE format, header guard)
  cli.py, app_cli.py   run a check from the terminal
  ui/             index.html, app-mode.js, app-mode.css
  demo_apps/      build_tinyshop.py (builds the TinyShop demo repos)
  projects/       mode 1 projects (the Demo shop lives here)
  apps/           mode 2 registry: one folder per connected app (created at run time, git-ignored)
  tests/          28 test files and a stub AI (fake_llm.py)
  backup/         saved outputs for the demo if something fails
  deploy/         AWS files
presentation/     the demos for the presentation (see section 10)
```

## 5. Mode 1: Python projects (brief)

A project is a folder of Python files with pytest tests, kept as versions. Choosing a version compares it with the one before it.

The workflow (`orchestration/graph.py`):
```
planner > change_analysis > impact_analysis > test_selection > test_execution > risk_assessment > decision > critic
critic PASS: end.  critic FAIL: replan and try again, at most 2 times, then manual review.
```
- **Plain code:** change analysis (`difflib`, `ast`), the import graph, the test selection rule, real `pytest` runs and the risk score.
- **AI:** the plan, short explanations and the decision recommendation.
- **Risk score 0 to 100:** change impact (0 to 25), critical component (0 to 30), failed-test severity (0 to 30), customer facing (0 to 10), failure count (0 to 5). LOW up to 30, MEDIUM 31 to 60, HIGH 61 to 80, CRITICAL above 80.
- **Critic rules in code:** a failed critical test or CRITICAL risk means BLOCK. HIGH risk or any other failure means HOLD at least. DEPLOY only if all tests passed and risk is LOW.
- **Demo shop:** v2.1 changes `notification.py` and gives DEPLOY at risk 12. v2.2 changes `payment.py` and gives BLOCK at risk 87 (a planted failing test). In v2.2 the first Decision is a **deliberately wrong DEPLOY** (`DEMO_SEED_WRONG_DECISION`, Demo shop only), the Critic rejects it and the second try gives BLOCK. This is stated openly in the presentation.
- Users can add projects and versions in the UI, and add or edit tests (JSON test cases or Python test files). The Demo shop's two planted tests are locked.

## 6. Mode 2: Apps (the main part)

### 6.1 Connecting an app and finding new commits
- **Connect app** takes a **GitHub link** (a public repo) or a **folder** on the computer the server runs on. **Browse** lists the server's folders inside the page.
- A GitHub link is cloned into `apps/<id>/repo` (default branch only). The link is checked strictly: only `https://github.com/owner/repo`, no other host, no login in the link. A private or missing repo gives a clear message.
- The registry is plain files: `apps/<id>/app.json` (name, path, watch on or off, source) and `apps/<id>/analyses/<old>_<new>.json` (saved results).
- The page shows a **commit timeline**. The server checks GitHub (`git fetch`) at most every 10 seconds, and the page asks for new commits every 4 seconds. With **Analyze new commits automatically** on, a new commit is analyzed against its parent without a click. This is polling while the page is open, not a git hook.
- Removing an app deletes its registry folder and any GitHub copy. A folder you pointed to is never touched.

### 6.2 The eight agents
All agents read and write one shared `AppState` (a `TypedDict`) and add a log line. Agents also send each other short messages (`from`, `to`, `kind`, `text`), kept in the state.

```
Scanner > Planner > Test writer > Test runner > Fault finder > Risk scorer > Decider > Critic
          Test runner > Test writer   once, if AI-written checks were unreliable (repair)
          Critic FAIL > Decider       at most 2 times (retry), then manual review ends as HOLD
```

| # | Agent (code name) | Type | Reads | Writes | Message to |
|---|---|---|---|---|---|
| 1 | Scanner (`change_scan`) | code | repo, old, new | `scan` | Planner |
| 2 | Planner (`planner`) | AI, fixed-rule fallback | `scan` | `focus` | Test writer |
| 3 | Test writer (`check_writing`) | AI proposes, code validates | `scan`, `focus` | `api_checks`, `browser_checks` | Test runner |
| 4 | Test runner (`differential_run`) | code | the checks | `api_report`, `browser_report`, errors | Fault finder, and Test writer if checks were unreliable |
| 5 | Fault finder (`layer_attribution`) | code, fixed rules | scan, reports, errors | `layer_verdict` | Decider |
| 6 | Risk scorer (`risk_assessment`) | code, fixed formula | scan, reports, errors | risk score, level, parts | Decider |
| 7 | Decider (`decision`) | AI, limited by rules | risk, verdict, messages, Critic feedback | `decision`, reason | Critic |
| 8 | Critic (`critic`) | code rules, AI writes the sentence | decision and all evidence | PASS or FAIL, reason, feedback | Decider if FAIL |

(The names in the first column are the suggested simple names. On screen the app still uses the code-style names such as Change scan and Check writer.)

What each agent does:
1. **Scanner** reads the git diff, sorts changed files into layers (frontend, backend, config, dependencies, tests) and builds an **app map** of both commits: the backend routes (FastAPI or Flask, read with `ast`), the calls the page makes (`fetch` or `axios`, read with patterns) and the fields the page reads. It reports **contract issues**: a page calling a route the backend does not serve, or reading a field the backend no longer returns. Only the names of changed environment keys are reported, never the values.
2. **Planner** reads the scan and chooses 1 to 4 focus areas: `api_contract`, `page_behavior`, `data_values`, `config_and_dependencies`. Without the AI it chooses by fixed rules from what changed.
3. **Test writer** asks the AI for API checks (a request and what to expect) and browser scenarios (click-throughs), told to focus on the Planner's choice. The AI writes data only, never code. Code validates them: at most 12 API checks, 6 scenarios, and only allowed steps. Fixed **probes** are always added: every plain GET, each write route with sample bodies built from its model, and a generic "open the page and press the first button". In a repair round it also reads the Test runner's complaint.
4. **Test runner** checks out the old and the new commit into temporary folders (`git archive`), starts both on free ports with a limited environment, runs every API check on both and every browser scenario in real Chromium on both, and compares. Each check gets a verdict: `regression`, `unchanged`, `benign_change` (for example a new field), `ui_changed` or `unreliable` (the old version already failed it). A check only counts if it holds on the old version. It always stops the processes and removes the folders.
5. **Fault finder** applies fixed rules. A static contract issue means the **connection** (or the frontend if only the page changed). An API regression with no page change means the **backend**. A broken page is blamed on the frontend only if a page file changed, otherwise it is treated as a symptom of the API change. It also reports a confidence level.
6. **Risk scorer** adds up fixed parts: change impact (up to 15), contract break (30 each, up to 40), API regression (up to 40), broken page (up to 40), not fully verified (10), new version does not start (100). Levels are the same as in mode 1.
7. **Decider** gets the evidence counts, the risk, the layer verdict, the other agents' notes and any Critic feedback, and answers DEPLOY, HOLD or BLOCK with a reason. Without the AI it uses the rules' minimum.
8. **Critic** works out in code the least cautious decision allowed. A failed start, a contract issue, a broken page or a breaking API change means BLOCK. A changed value or incomplete checks means HOLD at least. DEPLOY only if nothing regressed and risk is LOW. If the Decider is less cautious it is FAIL, the Critic sends the broken rule back, and the Decider tries again. The AI only writes the explaining sentence.

How the agents work together:
- The Scanner's findings reach the Planner, and the Planner's focus changes what the Test writer is asked.
- The Test runner can send unreliable checks back to the Test writer, once (and only if the AI wrote the checks).
- The Fault finder and Risk scorer brief the Decider. The Decider briefs the Critic. The Critic can challenge the Decider.
- In the UI, the panel **What the agents told each other** lists the messages, and **Expand** shows each agent's input, output, AI prompt and AI answer, plus a table of which agent writes and which reads each piece of data.

### 6.3 The tools (execution)
| File | Job |
|---|---|
| `tools/git_tool.py` | Read-only git: commits, diffs, file contents. Refs and paths are checked. Real `.env` files are never read |
| `tools/app_map.py` | Builds the app map: routes, page calls, selectors, contract |
| `tools/app_scan.py` | The change scan: layers, config and dependency changes, endpoint changes, contract issues |
| `tools/app_runner.py` | Starts an app from a commit in a temporary folder, with a limited environment and a timeout, and always cleans up |
| `tools/api_checks.py` | Validates and runs the API checks on both apps and compares the answers |
| `tools/browser_checks.py` | Runs the browser scenarios in Chromium on both apps and compares what the page showed |
| `tools/layer_verdict.py` | The Fault finder's rules |
| `tools/app_policy.py` | The risk formula and the Critic's rule floor |
| `tools/app_store.py` | The registry: connect, list, clone from GitHub, sync, save and load analyses |

### 6.4 What the page shows
- **Connect dialog:** GitHub link, folder with Browse, and the demo repos as examples.
- **Commit timeline** with each commit's saved result, and a button to analyze it.
- **Live agent list** that ticks through as events arrive, with an elapsed timer.
- **Verdict banner**, the **layer chain** (Frontend, Connection, Backend, with the faulty layer highlighted), and panels for what changed, frontend and backend, API checks, browser checks, risk, decision and Critic, and the agents' messages.
- **Expand** for each agent's input and output. Details are saved with each analysis, so they can be opened later.
- **Demo box** (demo repos only) to simulate a developer commit.

### 6.5 The server (`server_apps.py`)
`GET/POST /apps`, `GET/DELETE /apps/{id}`, `PUT /apps/{id}/watch`, `GET /apps/{id}/analyses/{old}/{new}`, `POST /apps/{id}/analyze` (streams events), `GET /app-examples`, `GET /browse-folders`, `POST /apps/{id}/demo-commit`. Mode 1 routes are in `server.py`.

An analysis streams one event per agent: `{"node": ..., "state_update": ..., "io": {input, ai calls, seconds, messages}}`, then a `final` event with the report. Only one app analysis runs at a time because it starts two copies of the app and a browser.

## 7. Safety model
- Git is used read-only, so no git hook ever runs. Real `.env` files are never read or listed.
- Apps run with a limited environment: only a short allowed list of variables plus the values from `.env.example`. The Groq key is never passed on.
- The server accepts only `localhost` and `127.0.0.1` host names and localhost cross-site requests. The routes that run code or read folders also need the `X-DeploySure` header.
- GitHub links are validated by a strict pattern. A repo that has to be downloaded is cloned with passwords disabled.
- Every subprocess has a timeout. Retries are capped. Nothing loops forever.
- On AWS the site sits behind an nginx password and a firewall.
- DeploySure runs the code of what it analyzes, so use **dummy apps only**.

## 8. Testing
- 451 tests pass (1 skipped: the live Groq test, which needs a key). They use real git, real apps and a real browser. Only the AI is a stub (`tests/fake_llm.py`), and no test calls Groq.
- Mode 2 tests cover the tools, the graph (messages, the repair loop, retries, no key, no browser), the registry, GitHub apps (using a local repo as "GitHub"), the routes and the layer rules.
- The suite also passed in an Ubuntu 24.04 container, so the code runs on Linux.
- A real Groq run has been checked by hand in the UI.

## 9. How to run
```powershell
cd "D:\STUDY\FAAI\Project\DeploySure AI"
deploysure\.venv\Scripts\python -m uvicorn deploysure.server:app --port 8000     # then open http://localhost:8000
deploysure\.venv\Scripts\python -m deploysure.app_cli deploysure\demo_apps\tinyshop v1.2 v2.1-frontend-bug   # terminal run
deploysure\.venv\Scripts\python -m deploysure.cli v2.2        # mode 1 from the terminal
deploysure\.venv\Scripts\python -m pytest deploysure/tests -q  # the tests, about 10 minutes
```
Put the key in `deploysure\.env` as `GROQ_API_KEY=...` (never in chat or in the code).

## 10. The demos
- **TinyShop** (`demo_apps/tinyshop`, built by `build_tinyshop.py`): a small shop with a FastAPI backend and a plain HTML and JavaScript frontend, with three good commits and three broken ones. Its own tests pass on every commit, which is the point.

| Compare | Result |
|---|---|
| v1.1 to v1.2 | DEPLOY, risk 8 |
| v1.2 to v2.0-backend-bug | HOLD, risk 38, backend (the total ignores quantity) |
| v1.2 to v2.1-frontend-bug | BLOCK, risk 73, frontend (the page calls a route that does not exist) |
| v1.2 to v2.2-contract-break | BLOCK, risk 100, connection (the API renamed `price`) |

- **PriceRight** (`presentation/stage_app`): a discount calculator with a page and a FastAPI backend, also on GitHub as `Parth2619/priceright-demo`. The bug (`bug_variants/pricing_buggy.py`) forgets to divide the percentage by 100. The result is BLOCK, risk 83, backend. `presentation/github_demo.ps1 bug` pushes the bug to GitHub, and `reset` puts `main` back.
- **Terminal demo** (`presentation/terminal_demo`): a standalone pricing gate with its own pipeline, run with `scripts/run_demo.py`. Original file gives DEPLOY at risk 5. The swapped buggy file gives BLOCK at risk 81.
- `backup/` has saved outputs of six runs in case the live demo fails.

## 11. Limits, said honestly
- Only FastAPI and Flask backends with plain frontends are understood.
- Checks cover only what they try. A bug on an untried path is not found.
- The risk weights were chosen for the demos. They are calibrated, not validated on real data.
- The app runs with this computer's Python and packages.
- The Groq free tier limits how much it can be used per minute.
- The result is evidence-based risk assessment. It does not guarantee production safety.
- Polling finds new commits only while the page is open.

## 12. Glossary
- **Agent:** a step that reasons or decides, here also a node in the graph.
- **Tool:** code that does real work, such as git or running an app.
- **Shared state:** the one object every agent reads and writes.
- **Contract:** the routes and fields the page and the backend both rely on.
- **Differential run:** running the old and the new version and comparing.
- **Regression:** something that worked in the old version and breaks in the new one.
- **Critic floor:** the least cautious decision the rules allow. The AI can go above it, never below.
