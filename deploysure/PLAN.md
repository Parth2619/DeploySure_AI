# DeploySure AI: Build Plan

Goal: a working backend and demo for the CA-3 presentation (19 to 22 Oct 2026), built with Claude Code. Today is 15 Oct. Working time is about 4 days. Each phase ends with something you can run and check.

## Research already done

- Current package versions on PyPI: langgraph 1.2.15, langchain-ollama 1.1.0, ollama 0.6.3, pytest 9.1.1, fastapi 0.143.2, uvicorn 0.54.0. Pin these in `requirements.txt`, then confirm they install on your machine.
- LangGraph pieces needed: `StateGraph`, `add_node`, `add_edge`, `add_conditional_edges`, `compile()`, and `graph.stream(..., stream_mode="updates")` for live progress. Check the current docs when wiring, since the API moves between versions.

## Research still to do (Claude Code should do this first, 15 min)

1. Read the current LangGraph docs for conditional edges and `stream_mode="updates"`. Write a 20 line toy graph with a retry loop and run it.
2. Check Ollama is installed on Manc's laptop (`ollama --version`). Pull one small model and time one JSON answer. If it takes more than about 8 seconds, use the smaller model or rely on mock mode for the live demo.
3. Confirm `pytest` can be run on a folder through `subprocess` and its output parsed (use `--tb=no -q` and `-rA`, or `--junitxml`).

## Phases

### Phase 0: Setup (30 min)
- Create the repo with the layout in CLAUDE.md. Virtualenv. `requirements.txt` with pinned versions.
- Copy `CLAUDE.md` and this plan into the repo root.
- Done when: `pytest` runs (even with zero tests) and `python -c "import langgraph"` works.

### Phase 1: Demo project (2 hours)
- Build the tiny shop in `demo_project/v2.0`: `auth.py`, `payment.py`, `orders.py`, `notification.py`, `checkout.py`, `refund.py`, each with 2 to 5 small functions and real imports between them (checkout imports payment, orders imports payment, refund imports payment).
- Write about 20 tests across the modules, tagged in the test name or a marker as critical or non-critical (payment, refund, checkout are critical).
- `v2.1`: copy of v2.0 with a harmless edit to `notification.py`. All tests pass.
- `v2.2`: copy of v2.0 with an edit to `payment.py` that breaks `test_refund` (and one more payment test).
- Done when: pytest on v2.0 and v2.1 is all green, pytest on v2.2 shows exactly the planted failures.

### Phase 2: Tools (3 hours, all deterministic, all unit tested)
- `diff_tool`: compare two release folders, return changed files and changed functions (difflib plus `ast`).
- `dependency_analyzer`: build an import graph with `ast`, return modules that depend on a changed module.
- `test_runner`: run pytest on a release folder for a list of tests, return passed, failed, failure names, with a timeout.
- `risk_formula`: the scoring function from CLAUDE.md with tests that hit scores near 12 and 87 for the two scenarios.
- Done when: unit tests pass and each tool prints sensible output for v2.1 and v2.2 from the command line.

### Phase 3: State, LLM wrapper, and graph with mock LLM (3 hours)
- `ReleaseState` TypedDict, `routing.py`, `graph.py` with all nodes wired, retry cap, and manual review exit.
- `models/llm.py` with `MockLLM` first. Write the agents against `ask()` so the real model plugs in later.
- Decision node with the `DEMO_SEED_WRONG_DECISION` option. Critic with the deterministic rule check first.
- Done when: both end-to-end tests pass in mock mode. Scenario A ends DEPLOY with `retry_count` 0. Scenario B shows Decision DEPLOY, Critic reject, then BLOCK with `retry_count` 1.

### Phase 4: Real LLM via Ollama (3 hours)
- Implement the Ollama backend in `llm.py` with JSON validation, one retry, and deterministic fallback.
- Switch planner, impact explanation, decision, and critic to the real model. Keep the deterministic floor so a weak answer cannot flip a BLOCK to DEPLOY unnoticed.
- Run both scenarios 10 times each. Record how often the outputs match the expected decisions and how long a run takes.
- Done when: both scenarios give the expected final decision on every run, and a full run is under about 60 seconds. If not, use a smaller model or mock for the live demo and say which one in the presentation.

### Phase 5: Interface for the UI (2 hours)
- `run_release_validation` and `stream_release_validation` as specified in CLAUDE.md, plus a small `cli.py` that prints the streamed events.
- Optional `server.py`: FastAPI with `GET /releases`, `POST /analyze/{release_id}` returning Server-Sent Events from the stream. Enable CORS for the local UI.
- Done when: the CLI shows each agent finishing in order, and (if built) `curl -N` shows the same events over HTTP.

### Phase 6: Your UI (your own time, about 1 day)
- Release picker, Analyze button, live agent checklist, panels for change analysis, test results, risk score, Critic validation, and a final verdict banner. Layout reference is in the original idea document, section 13.
- Start with an ugly working page, then style it.

### Phase 7: Demo hardening and presentation prep (half a day)
- Record a clean screen capture of both scenarios as backup.
- Check the numbers on slides 9 and 10 against real output and fix the deck if they differ.
- Dry run the 5 minute script twice with a timer. Prepare answers for the viva questions: why a Critic, what the LLM does versus Python, what if the model hallucinates, how is this different from normal CI, how is it different from BugTriage.
- Done when: you can run the full demo from a cold start in under a minute, offline.

## Suggested schedule

| Day | Phases |
|---|---|
| Thu 15 Oct (tonight) | Phase 0, start Phase 1 |
| Fri 16 Oct | Phase 1, 2, 3 |
| Sat 17 Oct | Phase 4, 5 |
| Sun 18 Oct | Phase 6, 7 |
| Mon 19 Oct onward | Presentation window, polish only |

## Risks and fallbacks

| Risk | Fallback |
|---|---|
| Ollama too slow or fails on the demo laptop | `DEPLOYSURE_LLM=mock`, plus the recorded video |
| Local model gives invalid JSON | Validation, one retry, deterministic default, logged in the trace |
| Scenario B does not reproduce the Critic rejection | Seeded wrong first decision, disclosed in the talk |
| Time runs short | Cut the FastAPI server and run the UI through direct Python calls, or demo from the CLI with the streamed trace |
| Numbers on slides differ from real output | Update the slides, not the system |

## How to start with Claude Code

1. Make a new folder, put `CLAUDE.md` and `PLAN.md` in it, open Claude Code there.
2. First message: "Read CLAUDE.md and PLAN.md. Do the research items first, then Phase 0 and Phase 1. Stop after each phase and show me the test output."
3. Work one phase at a time and check the "done when" line before moving on.
