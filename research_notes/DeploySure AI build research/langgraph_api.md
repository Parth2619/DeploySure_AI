# LangGraph Python API (Oct 2026) for a bounded critic/retry multi-agent graph

Note on verification: items marked VERIFIED were run locally in a fresh venv on Python 3.14.5 with langgraph 1.2.15 (script outputs below). Other items come from the official docs via fetch.

## 1. Latest version and Python support

### Takeaway
Latest stable is langgraph 1.2.15 (released 2026-10-12), requires Python >=3.10. PyPI classifiers list only up to 3.13, but it installs and runs on Python 3.14.5 (verified).

### Cited Findings
- PyPI JSON: version 1.2.15, requires_python ">=3.10", classifiers 3.10 to 3.13 (CPython and PyPy), no 3.14 classifier — [PyPI JSON](https://pypi.org/pypi/langgraph/json)
- Recent release dates: 1.2.12 on 2026-09-21, 1.2.13 on 2026-10-05, 1.2.14 on 2026-10-06, 1.2.15 on 2026-10-12 — [PyPI JSON](https://pypi.org/pypi/langgraph/json)
- VERIFIED: `python -m venv v; v/Scripts/python.exe -m pip install langgraph` on Python 3.14.5 gave langgraph 1.2.15, langgraph-checkpoint 4.3.0, langgraph-prebuilt 1.1.1, langgraph-sdk 0.4.7, langchain-core 1.6.10, pydantic 2.14.1. All example graphs below ran without error.
- Old docs host `langchain-ai.github.io/langgraph/...` now only returns a redirect; current docs live at `https://docs.langchain.com/oss/python/langgraph/...`.

### Inferences
- Pin `langgraph>=1.2,<2` in requirements.txt. No 3.14 classifier means unofficial support, but nothing failed in testing.

### Gaps
- No official statement of 3.14 support found. GitHub release notes were not read.

## 2. Core syntax: StateGraph, nodes, edges, conditional edges, compile

### Takeaway
Same API shape as 0.2+: `StateGraph(TypedDict)`, `add_node(name, fn)`, `add_edge`, `add_conditional_edges(src, fn, path_map)`, `compile()`. `START`/`END` come from `langgraph.graph`.

### Cited Findings
- Source for snippet: [Graph API docs](https://docs.langchain.com/oss/python/langgraph/graph-api)
```python
from operator import add
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import END, START, StateGraph

class State(TypedDict):
    foo: int
    bar: Annotated[list[str], add]   # reducer: appends

builder = StateGraph(State)
builder.add_node("node_a", node_a)           # name optional; defaults to fn name
builder.add_edge(START, "node_a")
builder.add_conditional_edges("node_a", routing_function, {True: "node_b", False: "node_c"})
builder.add_edge("node_b", END)
graph = builder.compile()                    # required before invoke/stream
```
- The routing function's return value is used as the node name, or as a key into the path map if one is given — [Graph API docs](https://docs.langchain.com/oss/python/langgraph/graph-api)
- A node returns a partial dict; keys not returned are left unchanged — [Graph API docs](https://docs.langchain.com/oss/python/langgraph/graph-api)
- `set_entry_point`/`set_finish_point` still work but docs recommend `add_edge(START, ...)`/`add_edge(..., END)` — [Graph API docs](https://docs.langchain.com/oss/python/langgraph/graph-api)
- Optional `StateGraph(Overall, input_schema=In, output_schema=Out)` — [Graph API docs](https://docs.langchain.com/oss/python/langgraph/graph-api)
- `Command(update=..., goto=...)` from `langgraph.types` is an alternative to conditional edges; docs warn static edges from the same node still run alongside `goto` — [Graph API docs](https://docs.langchain.com/oss/python/langgraph/graph-api)
- A routing function annotated `-> Literal["replan","manual_review"]` plus a path map both worked (VERIFIED).

### Inferences
- For this project use plain `add_conditional_edges` with an explicit path map: it is simplest to explain in a viva and keeps routing in `orchestration/routing.py`.

### Gaps
- None for this section.

## 3. Reducers and state pitfalls

### Takeaway
Keys without `Annotated` are overwritten; `Annotated[list[str], operator.add]` appends. Nodes should return only the new items for reducer keys.

### Cited Findings
- Keys without a reducer replace the value; keys with `Annotated[..., reducer]` combine current (left) and update (right) — [Graph API docs](https://docs.langchain.com/oss/python/langgraph/graph-api)
- To clear a reducer-merged field use `from langgraph.types import Overwrite; return {"errors": Overwrite([])}` — [Graph API docs](https://docs.langchain.com/oss/python/langgraph/graph-api)
- VERIFIED (langgraph 1.2.15, py3.14.5): with `trace: Annotated[list[str], operator.add]`, nodes returning `{"trace": ["x"]}` accumulated across the retry loop into one 12-entry list; invoke result `['plan r=0','decide','critic','replan','plan r=1',...,'manual']`.
- VERIFIED: a node returning a key not in the TypedDict (`{"bogus": 1}`) was silently dropped, no error. Typos in state keys fail silently.
- VERIFIED: a node named the same as a state key (node "decision", key "decision") compiled and ran fine in 1.2.15. Older versions raised "already being used as a state key", so this clash is no longer an error, but avoid it anyway for readability.

### Inferences
- Pitfall: if a node returns the full old trace plus a new line under an `add` reducer, entries duplicate. Return only the new line.
- Pitfall: `retry_count` must NOT have a reducer if `replan` sets it to `n+1` (with `add` you would return `1` instead).
- Initialise reducer keys in the input (`{"trace": []}`) or use `state.get(...)` defensively.
- For the "Every node appends a trace line" rule, `trace: Annotated[list[str], operator.add]` is the right fit.

### Gaps
- Deprecations since 0.2 not exhaustively listed; the docs fetched flag none for these APIs. Not checked: changelog/migration guide.

## 4. Streaming

### Takeaway
`stream_mode="updates"` yields `{node_name: partial_update}` per node finish (default v1 shape). `version="v2"` (needs LangGraph >=1.1) wraps every chunk as `{"type","ns","data"}`.

### Cited Findings
- Modes: `values` (full state after each step), `updates` (state updates after each step), `messages`, `custom`, `checkpoints` (needs checkpointer), `tasks` (needs checkpointer), `debug` — [Streaming docs](https://docs.langchain.com/oss/python/langgraph/streaming)
- v2 format: `{"type": ..., "ns": (), "data": ...}`; for updates, `chunk["data"]` is `{node_name: update}` — [Streaming docs](https://docs.langchain.com/oss/python/langgraph/streaming)
```python
for chunk in graph.stream(inputs, stream_mode="updates", version="v2"):
    if chunk["type"] == "updates":
        for node_name, update in chunk["data"].items(): ...
```
- Multiple modes in v1 yield `(mode, data)` tuples; in v2 use `chunk["type"]` — [Streaming docs](https://docs.langchain.com/oss/python/langgraph/streaming)
- Custom events: `from langgraph.config import get_stream_writer; writer = get_stream_writer(); writer({...})` inside a node, then `stream_mode="custom"` (or in a list). Async on Python <3.11 needs a `writer: StreamWriter` param instead — [Streaming docs](https://docs.langchain.com/oss/python/langgraph/streaming)
- VERIFIED outputs (v1 default, `stream_mode="updates"`): `{'planner': {'trace': ['plan r=0']}}`, `{'decision': {'decision': 'DEPLOY', 'trace': ['decide']}}`, ... one dict per node, key is node name, value is only what that node returned (not full state). VERIFIED v2: `{'type': 'updates', 'ns': (), 'data': {'planner': {...}}}`.

### Inferences
- Mapping to the project contract: for each chunk `for node, update in chunk.items()` yield `{"node": node, "status": "done", "state_update": update, "timestamp": time.time()}`. Merge updates yourself (append `trace`, overwrite others) to build `final_report`, or call `graph.invoke` separately; then emit the `node: "final"` event after the loop. The default v1 shape avoids the version flag; v2 is safer if you also add custom/other modes.
- Note: the same node name appears repeatedly across retries (planner twice, etc.). The UI must handle repeats.
- `stream_mode="values"` gives full state each step, easier for the final report: last chunk is final state.

### Gaps
- Whether v1 stays the default long term is not stated in what I read.

## 5. Critic/retry loop with a hard cap

### Takeaway
Keep `retry_count` in state, increment it in a `replan` node, and route on it in `route_after_critic`. This is deterministic and ends at `manual_review` after 2 retries. Verified working.

### Cited Findings
- Official evaluator-optimizer example uses a generator node, evaluator node and `add_conditional_edges(evaluator, route_fn, {"Accepted": END, "Rejected + Feedback": "generator"})`. It has NO iteration cap, so the cap is your responsibility — [Workflows and agents docs](https://docs.langchain.com/oss/python/langgraph/workflows-agents#evaluator-optimizer)
- Other documented patterns: routing, orchestrator-worker (`Send`), parallelization, prompt chaining — [same page](https://docs.langchain.com/oss/python/langgraph/workflows-agents)
- Recursion limit: set via `graph.invoke(inputs, config={"recursion_limit": N})` (top-level config key, not under `configurable`). Docs say default 1000 since 1.0.6 — [Graph API docs](https://docs.langchain.com/oss/python/langgraph/graph-api); but installed 1.2.15 source has `DEFAULT_RECURSION_LIMIT = int(getenv("LANGGRAPH_DEFAULT_RECURSION_LIMIT", "10007"))` in `langgraph/_internal/_config.py` (VERIFIED by grep). Docs and code disagree.
- VERIFIED: exceeding the limit raises `langgraph.errors.GraphRecursionError: Recursion limit of 5 reached without hitting a stop condition...`.

Verified working pattern (MAX_RETRIES=2 gives exactly 3 passes, then manual_review):
```python
import operator
from typing import Annotated, Literal
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

MAX_RETRIES = 2
class S(TypedDict):
    retry_count: int
    decision: str
    trace: Annotated[list[str], operator.add]

def replan(s): return {"retry_count": s.get("retry_count", 0) + 1, "trace": ["replan"]}
def route_after_critic(s) -> Literal["end", "replan", "manual_review"]:
    if s["critic_result"] == "PASS": return "end"
    return "replan" if s["retry_count"] < MAX_RETRIES else "manual_review"

g = StateGraph(S)  # add_node for planner, decision, critic, replan, manual_review ...
g.add_edge(START, "planner"); g.add_edge("planner", "decision"); g.add_edge("decision", "critic")
g.add_conditional_edges("critic", route_after_critic,
    {"end": END, "replan": "replan", "manual_review": "manual_review"})
g.add_edge("replan", "planner"); g.add_edge("manual_review", END)
app = g.compile()
```
(Test run with an always-rejecting critic: stream showed replan twice, then `manual_review`, then finished; 12 trace entries.)

### Inferences
- Step budget: each pass here is ~8 nodes (planner to critic), so 3 passes plus replans is about 30 steps, far below any default. Still pass a small explicit `recursion_limit` (e.g. 60) as a safety net against routing bugs; the deterministic counter is the real bound.
- Scenario B needs: pass 1 decision DEPLOY (seeded), critic FAIL, replan (retry_count 1), pass 2 BLOCK, critic PASS. `DEMO_SEED_WRONG_DECISION` logic should key off `retry_count == 0` in the decision node.
- Because `route_after_critic` is a pure function of state, it is trivially unit-testable with dict inputs (the three required cases).

### Gaps
- Exact semantic of what counts as a "step" for recursion_limit (superstep per node) not formally confirmed beyond the test (limit 5 failed at an infinite-ish loop).
- Docs (1000) vs source (10007) default mismatch unresolved; irrelevant if you set the limit explicitly.
