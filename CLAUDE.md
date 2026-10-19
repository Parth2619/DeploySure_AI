# DeploySure AI

CA-3 Agentic AI proof of concept. A multi-agent system that decides whether a software release is safe to deploy (DEPLOY / HOLD / BLOCK), with a Critic agent that validates the decision and can force a reassessment.

Owner: Manc (Mansi Pradip Koshti). Demo is a 5 minute live slot on 19 to 22 Oct 2026. Address the owner as "Manc". Do not open replies with a greeting.

## Hard requirements (from the course brief)

- Must be an agentic workflow: planning, execution, decision-making, validation, agent collaboration. A chatbot is not enough.
- Python. LangGraph for orchestration. Free local model via Ollama, or a mock model. No paid APIs.
- Dummy or synthetic data only. Never connect to a real production system.
- The UI is built separately by Manc. This repo ships the backend only, plus one clean entrypoint (see Interface).
- Owner must be able to explain every file in a viva. Prefer simple, readable code over clever code.

## Architecture

Layers: UI (not in this repo) -> LangGraph orchestrator -> agents -> tools -> demo codebase.

Agent = reasoning. Tool = execution. LangGraph = orchestration. Do not blur these.

Graph (one shared `ReleaseState`, every node reads and writes it):

```
START -> planner -> change_analysis -> impact_analysis -> test_selection
      -> test_execution -> risk_assessment -> decision -> critic
critic -> PASS    -> END
critic -> FAIL    -> replan -> planner     (retry_count < MAX_RETRIES)
critic -> FAIL    -> manual_review -> END  (retry_count >= MAX_RETRIES)
```

`MAX_RETRIES = 2`. Never allow an unbounded loop.

### Which nodes use the LLM

| Node | LLM | Notes |
|---|---|---|
| planner | yes | Produces the task list. Falls back to a fixed list if the model output is invalid. |
| change_analysis | no | difflib + ast. Deterministic. |
| impact_analysis | partly | Dependency graph via ast imports is deterministic. LLM only writes the short explanation. |
| test_selection | partly | Rule based on impacted modules. LLM may only justify, never add tests that do not exist. |
| test_execution | no | Real `pytest` through `subprocess`. Never let an LLM invent test results. |
| risk_assessment | no | Fixed scoring formula, see below. |
| decision | yes | Recommends DEPLOY, HOLD or BLOCK from the evidence. |
| critic | yes | Independent check of the decision against the evidence. |

### Risk score (deterministic, 0 to 100)

Components: change impact (0 to 25), critical component touched (0 to 30), failed tests severity (0 to 30), customer facing (0 to 10), failure count (0 to 5). Levels: 0 to 30 LOW, 31 to 60 MEDIUM, 61 to 80 HIGH, 81 to 100 CRITICAL. Keep the formula in `tools/risk_formula.py` with unit tests.

### Decision rules the Critic enforces (deterministic floor)

- Any failed critical test, or risk level CRITICAL, means the decision must be BLOCK.
- Risk level HIGH or any non-critical failure means HOLD at minimum.
- DEPLOY only if all selected tests pass and risk is LOW.

The Critic must check the decision against these rules in code first, then use the LLM for the written reasoning. This keeps the demo reliable even with a weak local model.

## Demo scenarios (must always work)

- **Scenario A, safe:** release changes `notification.py` only. All selected tests pass. Risk about 12. DEPLOY. Critic passes.
- **Scenario B, dangerous:** release changes `payment.py`. `test_refund` fails (planted bug). Risk about 87. The first Decision output is DEPLOY (seeded wrong answer), the Critic REJECTS, reassessment gives BLOCK.

Scenario B's wrong first decision must be reproducible. Implement it as a `DEMO_SEED_WRONG_DECISION` setting that makes the Decision node return DEPLOY on the first pass only. Say so openly in the presentation. Do not hide it.

## Interface contract (the UI depends on this, do not break it)

```python
def run_release_validation(release_id: str) -> dict: ...
def stream_release_validation(release_id: str) -> Iterator[dict]: ...
```

`stream_release_validation` yields one event per node as it finishes:
`{"node": "critic", "status": "done", "state_update": {...}, "timestamp": ...}`
so the UI can show agents ticking through live. The final event has `node: "final"` and contains `final_report`.

`final_report` keys: `release_id`, `changed_files`, `impacted_modules`, `selected_tests`, `test_results`, `risk_score`, `risk_level`, `decision`, `decision_reason`, `critic_result`, `critic_reason`, `retry_count`, `trace`.

Optional thin HTTP layer in `server.py` (FastAPI, Server-Sent Events) only after the core works.

## Repo layout

```
deploysure/
  CLAUDE.md
  PLAN.md
  requirements.txt
  agents/        planner.py change_analyzer.py impact_analyzer.py test_selector.py
                 test_executor.py risk_assessor.py decision_agent.py critic.py
  orchestration/ state.py graph.py routing.py
  tools/         code_reader.py diff_tool.py dependency_analyzer.py test_runner.py risk_formula.py
  models/        llm.py          (Ollama client + MockLLM, chosen by env var)
  demo_project/  v2.0/ v2.1/ v2.2/   (each a tiny shop: auth, payment, orders, notification, checkout, refund + tests)
  releases/      release_v2_1.json release_v2_2.json   (metadata and release notes)
  tests/         unit tests for tools, routing, risk formula, and both end-to-end scenarios
  server.py      optional
```

Release naming used in the demo: v2.0 is the baseline, v2.1 is the safe release (Scenario A), v2.2 is the dangerous release (Scenario B). Names are arbitrary.

## Commands

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest tests/ -q                       # project tests (not the demo project's tests)
python -m deploysure.cli v2.1          # run a release from the terminal (add if missing)
DEPLOYSURE_LLM=mock python -m deploysure.cli v2.2   # no Ollama needed
ollama pull qwen2.5:7b                 # real model, optional
```

Run the demo project's own tests only through `tools/test_runner.py`, which calls pytest on a given release folder with a timeout.

## LLM handling

- `models/llm.py` exposes one function, `ask(prompt, schema=None)`. Backend is chosen by `DEPLOYSURE_LLM` = `ollama` or `mock`.
- Ask for JSON and validate it. On invalid output, retry once, then fall back to a deterministic default and record the fallback in the trace.
- Temperature 0. Fixed seed where the backend supports it.
- `MockLLM` returns canned, schema-valid answers per node so every test and the backup demo run offline.
- Default model: `qwen2.5:7b` or `llama3.2:3b` if the laptop is slow. Check speed on Manc's actual machine before choosing.

## Conventions

- Python 3.11 or newer. Type hints on public functions. `TypedDict` for `ReleaseState`.
- Nodes are plain functions `(state) -> partial state dict`. No classes unless needed.
- Every node appends a human readable line to `state["trace"]`. The UI and the viva both rely on this.
- Paths use `pathlib`. Subprocess calls always have a timeout.
- Keep dependencies minimal: `langgraph`, `langchain-ollama` or `ollama`, `pytest`. Add `fastapi` and `uvicorn` only for `server.py`.
- Comments explain why, not what. Short.
- No em dashes in any document or slide text. Use commas, colons or full stops.

## Testing rules

- Tools (diff, dependency, risk formula, test runner parsing) get unit tests.
- `routing.route_after_critic` gets tests for PASS, FAIL under the cap, and FAIL at the cap.
- Two end-to-end tests, one per scenario, run with `DEPLOYSURE_LLM=mock` and assert the final decision, the Critic result, and `retry_count`.
- Before claiming anything works, run the tests and show the output. Do not say "done" from reading code.

## Boundaries

- Do not edit the planted failing test in `demo_project/v2.2` to make it pass. The failure is the point of Scenario B.
- Do not add features not listed here (no auth, no database, no deployment automation) unless Manc asks.
- Do not claim the system guarantees production safety. The limitations slide says it provides evidence based risk assessment only.
- The presentation deck already exists (`DeploySure_AI_CA3.pptx`). Numbers in it (6 tests selected in Scenario A, 20 tests and 18 passing in Scenario B, risk 12 and 87) must match what the system actually produces. If the system output differs, update the deck numbers, not the other way round.
