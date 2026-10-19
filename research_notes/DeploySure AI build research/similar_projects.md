# Similar projects, papers and patterns for DeploySure AI

## 1. Open-source projects: LLM/agentic release gating, change risk, test selection, LangGraph CI/CD agents

### Takeaway
No mature, widely starred open-source "multi-agent release gate with Critic" exists that I could find. The closest are small: release-gate (PROMOTE/HOLD/BLOCK verdict CLI), TDAD (AST graph test impact), a LangGraph PR reviewer with a verifier node, and a hackathon multi-agent gate. DeploySure's combination (deterministic floor + Critic forced reassessment + replay-able scenarios) is a defensible niche. Star counts were not retrievable except TDAD (17), so do not quote stars for others.

### Cited Findings
- release-gate (PyPI CLI + GitHub Action): per-PR PROMOTE / HOLD / BLOCK verdict, evidence based, checks only net-new risk, two scores (code safety, governance), lean 3-dependency CLI. Targets AI-agent risk, not general software releases, and is not multi-agent. Worth borrowing: the three-level verdict vocabulary and "show evidence with the verdict". Repo URL and licence not confirmed (PyPI page failed to load on fetch) — [PyPI release-gate](https://pypi.org/project/release-gate/0.9.3/), seen via [search listing](https://socket.dev/pypi/package/release-gate)
- DeployGuard (hackathon, lablab.ai, June 2026): five specialist agents on a PR, a RiskAgent computes a weighted risk score and cross-checks SecurityAgent and challenges it back for re-scan, security-critical decisions come from deterministic code not the model, fails closed (escalates to manual review if it cannot inspect). Almost the same shape as DeploySure (Critic challenge, deterministic floor, manual_review fallback). Public repo/licence unverified — [lablab.ai submission](https://lablab.ai/ai-hackathons/band-of-agents-hackathon/impactonious/deployguard-multi-agent-pr-security-gate)
- TDAD, github.com/pepealonso95/TDAD, 17 stars, MIT: parses Python with `ast` into a graph (files, functions, classes, tests; CALLS, IMPORTS, TESTS, INHERITS edges), ranks impacted tests for changed files, NetworkX backend (no Docker), CLI `tdad index / impact / run-tests`. Ran with a local Qwen3-Coder 30B. Reported test-level regressions 6.08% to 1.82% (72% reduction) on SWE-bench Verified 100 instances. Directly relevant to DeploySure's `dependency_analyzer.py` and `test_selector.py` — [GitHub](https://github.com/pepealonso95/TDAD), paper [arXiv 2603.17973](https://arxiv.org/pdf/2603.17973)
- TDAD limitations (static only, misses dynamic dispatch/monkey-patching, Python-focused): good wording for DeploySure's limitations slide — [secondary guide](https://agentpatterns.ai/verification/pre-change-impact-analysis/) (search-result summary; check before quoting)
- Agentic Pull Request Reviewer (PyPI 0.2.0): LangGraph workflow, LLM proposes structured findings, a verifier critiques them, outputs Markdown review; Python-focused (ruff/pytest). Structural match for propose-then-verify — [PyPI](https://pypi.org/project/agentic-pr-reviewer/0.2.0/)
- Zero-G Reviewer (PyPI): LangGraph, routes large PRs to Security/Performance/Domain sub-agents — [PyPI](https://pypi.org/project/zerog-cr/)
- Krish Naik PR reviewer course project: four parallel review agents (static, security, architecture, style) merged — [krishnaik.in](https://krishnaik.in/project/lfnm)
- Medium walkthrough, multi-agent PR review with LangGraph + FastAPI + webhooks + Docker (tutorial, not repo) — [Medium](https://medium.com/@anilnishad19799/multi-agent-pr-review-system-a9408fe287a9)
- LangChain official CI/CD reference pipeline: unit, integration, E2E tests, offline evals, staged deploy with quality-gated production release via GitHub Actions — [LangSmith docs](https://docs.langchain.com/langsmith/cicd-pipeline-example)
- agentic-qe (proffesor-for-testing/agentic-qe) regression-testing skill: analyze git diff and impact, select tests by change plus risk — [openskillindex listing](https://openskillindex.com/skills/proffesor-for-testing-agentic-qe-regression-testing-b66f58) (third-party index, repo not opened)
- MergeShield: commercial SaaS scoring PR risk across six dimensions, holds high-risk for human review. Not open source; only useful as a feature reference — [G2 listing](https://www.g2.com/sellers/mergeshield)

### Inferences
- DeploySure's genuine differentiators versus the above: a Critic that can force a bounded reassessment loop, and a rule-based floor in code. DeployGuard is the closest prior art; cite it as related work honestly.
- TDAD's graph-from-`ast` approach validates the plan to build the dependency graph deterministically and use the LLM only for explanation.
- For the viva: "static analysis only" is a stated limitation of the nearest comparable tool, so DeploySure having the same limit is normal.

### Gaps
- GitHub star counts and repo URLs for release-gate, DeployGuard, Agentic PR Reviewer, Zero-G: not retrievable (GitHub MCP down, PyPI fetch failed). Verify on GitHub before listing.
- No open-source repo found for "LLM change risk score" with a published formula.

## 2. Established deterministic change-risk factors and test-selection approaches

### Takeaway
Industry practice supports exactly DeploySure's inputs: change size/churn (relative, not absolute), file history and failure history, number of authors, dependency distance between change and tests, and criticality. Test selection is either dependency/call-graph based (Microsoft TIA, Datadog, Harness, TDAD) or ML on history (Meta, Launchable). DeploySure's rule-based approach is the explainable classical one.

### Cited Findings
- Meta Predictive Test Selection (ICSE-SEIP 2019): gradient-boosted decision tree trained on past changes and test outcomes; catches over 99.9% of faulty changes, over 95% of individual test failures, roughly halves test infra cost, runs about a third of the tests that transitively depend on the change. Trees chosen because they are explainable. Features from the paper summary: file change history, historical failure rate, number of distinct authors, minimal distance between files and test targets — [Meta engineering blog](https://engineering.fb.com/2018/11/21/developer-tools/predictive-test-selection/), [paper](https://ar5iv.arxiv.org/html/1810.05286), feature list via [Launchable summary](https://launchableinc.com/eng/predictive-test-selection-efficient-software-test-execution)
- Google "Taming Google-Scale Continuous Testing" (ICSE-SEIP 2017): very few tests ever fail, failing tests are generally closer to the changed code, frequently modified code breaks more, code recently modified by more than 3 developers breaks more often — [Google Research](https://research.google/pubs/taming-google-scale-continuous-testing/)
- Microsoft Test Impact Analysis: identifies changed methods, lists tests that directly or indirectly call them using a store of test-to-method coverage; call-graph based — [Microsoft docs](https://learn.microsoft.com/en-ie/previous-versions/azure/devops/pipelines/test/test-impact-analysis?view=tfs-2017), explainer [Martin Fowler](https://martinfowler.com/articles/rise-test-impact-analysis.html)
- Launchable: ML on test history and changed-file/failure links, change size and file types, no static analysis; claims run 20% of tests for 90% confidence of catching a failure; has an observation (dry run) mode — [Launchable docs](https://docs.launchableinc.com/features/predictive-test-selection/how-launchable-selects-tests) (vendor claims)
- Datadog Test Impact Analysis: skips tests using code coverage plus git metadata — [Datadog docs](https://docs.datadoghq.com/tests)
- Harness Test Intelligence: runs only unit tests relevant to the change, and conservatively runs everything when unsure — [Harness blog](https://harness.io/blog/continuous-integration/test-intelligence). Good rule to copy: "if unsure, widen the test set".
- Nagappan and Ball, ICSE 2005: relative code churn (normalised by LOC, file count, etc.) predicts defect density; absolute churn is a poor predictor; 89% accuracy separating fault-prone from non-fault-prone binaries on Windows Server 2003 — [Microsoft Research](https://microsoft.com/en-us/research/?p=151819)
- Just-in-time defect prediction (Kamei et al.): per-commit metrics covering size, diffusion, history, developer experience — [Kamei EMSE 2015](https://posl.ait.kyushu-u.ac.jp/~kamei/publications/Kamei_EMSE2015.pdf)
- DORA change failure rate: share of production changes that cause degraded service needing a fix (hotfix, rollback, patch). It is a retrospective outcome metric, not a pre-deploy predictor — [Swarmia definition](https://help.swarmia.com/definitions/dora-metrics/change-failure-rate). Performance-band cutoffs seen on glossaries were not verified against the DORA report; do not quote.

### Inferences
- DeploySure's risk components map to literature: change impact = size/diffusion (Kamei) and relative churn (Nagappan); critical component = criticality; test failures = Google's "failures cluster near the change"; customer facing and failure count = domain additions. Present them as "informed by", not "validated by".
- Relative churn is a cheap upgrade: lines changed divided by file size, from `difflib` already used.
- Use DORA CFR only as framing: DeploySure tries to lower change failure rate before deploy.
- Meta/Launchable need months of history; with synthetic data, the rule-based dependency approach is the right choice, and the viva answer is "ML needs history we do not have, rules are explainable".

### Gaps
- Primary DORA report text and band thresholds not fetched.
- Google TAP selection algorithm details not obtained beyond the abstract.
- No published numeric weights for a combined change-risk formula were found; the 0 to 100 formula in CLAUDE.md is custom and should be described as such.

## 3. Critic / reflection / evaluator-optimizer patterns and failure modes

### Takeaway
Evaluator-optimizer and reflection are standard documented patterns, and the literature says an LLM judging its own output without external grounding is unreliable. That is the justification for DeploySure's deterministic rules-first Critic with tests as external evidence.

### Cited Findings
- Anthropic "Building Effective Agents": evaluator-optimizer is one LLM generating, another evaluating and giving feedback in a loop; use when criteria are clear and iteration adds measurable value; agents should have stopping conditions such as a maximum number of iterations; programmatic "gates" between steps act as guardrails — [Anthropic](https://www.anthropic.com/engineering/building-effective-agents)
- LangGraph official evaluator-optimizer example: generator node, evaluator node with Pydantic structured output (`grade` Literal plus `feedback`), a conditional edge returning Accepted to END or Rejected+Feedback back to the generator. The functional version has no iteration cap, so add one — [LangGraph docs](https://docs.langchain.com/oss/python/langgraph/workflows-agents)
- LangChain "Reflection Agents": basic reflection (generator and reflector, fixed number of rounds) and Reflexion (critique grounded in external data) — [LangChain blog](https://blog.langchain.com/reflection-agents). Code uses old `MessageGraph`; use `StateGraph`.
- Huang et al., ICLR 2024: LLMs cannot self-correct reasoning without external feedback, and performance can degrade after self-correction. Self-correction works when grounded in external signals such as a code executor — [arXiv 2310.01798](https://arxiv.org/html/2310.01798v1)
- Self-preference bias: GPT-4 as judge shows significant self-preference, linked to preferring low-perplexity (familiar) text — [Wataoka et al.](https://arxiv.org/pdf/2410.21819)
- Practitioner glossary lists position, verbosity and self-preference biases; mitigations include randomising order and using a different model family as judge (non-peer-reviewed) — [PromptLayer](https://www.promptlayer.com/glossary/llm-as-judge-bias)
- DeployGuard design (above) uses deterministic code for security-critical decisions and fails closed — [lablab.ai](https://lablab.ai/ai-hackathons/band-of-agents-hackathon/impactonious/deployguard-multi-agent-pr-security-gate)
- LangGraph structured-output and retry: pattern is Pydantic model plus `.with_structured_output()`, conditional edge back on invalid output, node-level try/except, `RetryPolicy` for nodes. One report says LangChain structured output did not auto-retry on schema validation errors, so test that path yourself — [machinelearningplus](https://machinelearningplus.com/gen-ai/langgraph-error-handling-retries-fallback-strategies/), [report](https://sftp.thewrap.com/post/langchain-fix-for-no-retry)

### Inferences
- Rubber-stamping risk: a Critic sharing the same model as Decision will tend to agree. DeploySure's code-level rules check first, so the Critic's verdict never depends on the LLM agreeing. Say this in the demo.
- Loop risk: both LangGraph examples show loops ending only on a grade; hence the `MAX_RETRIES = 2` plus manual_review exit is the right mitigation. Add a unit test that the loop terminates even when the mock Critic always FAILs.
- Weak local model reliability recipe (from the above, applied): JSON schema validation, one retry, deterministic fallback, record fallback in trace, temperature 0.
- Make the Critic's evidence external: feed it real pytest results and the rules table, not only the Decision's own reasoning (Reflexion style grounding).

### Gaps
- No source found on "critic rubber-stamping" by that name; the failure mode is inferred from self-preference and self-correction literature.
- No measured schema-failure rates for qwen2.5:7b or llama3.2:3b on Ollama; measure on Manc's machine.
- Ollama structured-output (JSON schema `format`) support was not researched in this pass.

## 4. LangGraph structural references (planner + critic + retry)

### Takeaway
The best structural templates are the official LangGraph evaluator-optimizer example and the reflection tutorials; none include planner plus bounded retry plus manual-review exit, so DeploySure's graph is a small original composition.

### Cited Findings
- Official evaluator-optimizer graph (generator, evaluator, `route_joke` conditional edge) — [LangGraph docs](https://docs.langchain.com/oss/python/langgraph/workflows-agents)
- JBaczuk LangGraph-Tutorial, lesson 5 reflection agent: generator to critic to revision, ends on "SATISFACTORY", includes iteration-limit guidance — [GitHub](https://github.com/JBaczuk/LangGraph-Tutorial)
- Drafter-Critic loop in LangGraph.js (JS, but same shape) — [DEV](https://dev.to/programmingcentral/beyond-linear-chains-building-a-self-correcting-ai-agent-with-langgraphjs-4mjd)
- Agentic PR Reviewer: propose findings then verifier node — [PyPI](https://pypi.org/project/agentic-pr-reviewer/0.2.0/)
- LangGraph supports streaming per-node updates (relevant to `stream_release_validation`); I did not fetch the streaming docs in this pass.

### Inferences
- Use `route_after_critic` as the single conditional edge returning `"end" | "replan" | "manual_review"`, as in the official `route_joke` pattern, and unit test it (matches CLAUDE.md).
- Keep `retry_count` in state and increment in the `replan` node only.

### Gaps
- Stars and maintenance status of the tutorial repos not checked.
- LangGraph streaming mode docs not fetched; confirm `stream_mode="updates"` fits the event contract.

## 5. Ideas to improve the demo (what real tools show)

### Takeaway
Real tools sell trust through evidence shown next to the verdict, a dry-run mode, and conservative fallbacks. All are cheap to add to a trace/report UI.

### Cited Findings
- Evidence-based verdict: release-gate shows the verdict with the evidence behind it and distinguishes net-new risk from inherited debt — [PyPI](https://pypi.org/project/release-gate/0.9.3/)
- Fail closed: escalate to manual review when the change cannot be inspected — [DeployGuard](https://lablab.ai/ai-hackathons/band-of-agents-hackathon/impactonious/deployguard-multi-agent-pr-security-gate)
- Observation / dry-run mode before enforcing — [Launchable](https://launchableinc.com/predictive-test-selection)
- Conservative widening of tests when unsure — [Harness](https://harness.io/blog/continuous-integration/test-intelligence)
- Explainable models preferred for gating (Meta chose decision trees for explainability) — [Meta](https://engineering.fb.com/2018/11/21/developer-tools/predictive-test-selection/)
- MergeShield-style multi-dimension risk scoring and "hold high-risk for human review" — [G2](https://www.g2.com/sellers/mergeshield)

### Inferences
- Risk breakdown table in `final_report`: the five components with points and a one-line reason each, so the 87 is auditable on screen.
- Evidence table: test, selected-because (which impacted module), result.
- Decision timeline: first decision, Critic verdict with the rule that fired, final decision; the seeded wrong first decision is shown openly as a labelled demo setting.
- A "rules fired" list in `critic_result` (e.g. "failed critical test, so BLOCK required").
- Optional "dry run" label for Scenario A to mirror observation mode; low priority.
- Limitations slide: static analysis only (TDAD's same limit), synthetic data, evidence-based assessment not a guarantee.

### Gaps
- No screenshots or UI specs of these tools were examined.
