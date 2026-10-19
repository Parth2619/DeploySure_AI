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
| `DEPLOYSURE_LLM=mock` (offline) | 6 s | 11 s |
| `DEPLOYSURE_LLM=ollama` (qwen2.5:7b, local GPU) | 16 s | 20 s |

Backup transcripts of all four runs are in `backup/`. A screen recording still has to be made by hand.

## Five minute script

1. Problem (30 s): CI says tests pass or fail, nobody weighs risk or checks the call itself.
2. Run `python -m deploysure.cli v2.1` (30 s): agents tick through, DEPLOY, risk 12, Critic PASS.
3. Run `python -m deploysure.cli v2.2` (90 s): 20 tests, 2 critical failures, risk 87. First decision DEPLOY, point out it is the seeded wrong answer. Critic FAIL, replan, BLOCK, Critic PASS.
4. Architecture (60 s): which nodes use the LLM and which are plain Python.
5. Limits (30 s): evidence based risk assessment, not a guarantee of production safety.

Fallback if Ollama misbehaves: `DEPLOYSURE_LLM=mock`, same results, no model needed.

## Viva answers

- **Why a Critic?** A single model can be confidently wrong. The Critic is an independent check against a fixed policy, so a wrong decision is caught instead of shipped.
- **What does the LLM do and what does Python do?** The LLM writes the plan, the explanations and the decision recommendation. Python does the diffing, import graph, test selection rule, real pytest runs, the risk score and the Critic's PASS or FAIL.
- **What if the model hallucinates?** It cannot invent test results or tests, those come from pytest. Invalid JSON is retried once, then a deterministic default is used and the trace says so. A wrong decision is rejected by the rule check. After 2 failed retries the run goes to manual review as HOLD.
- **How is it different from normal CI?** CI reports pass or fail per test. This adds impact analysis, a risk score, a deploy decision and a second check on that decision.
- **How is it different from BugTriage?** BugTriage is about sorting reported bugs. This decides whether a release may ship, from evidence gathered by running tests.
- **Known weakness:** the Critic only knows the rules in `minimum_decision`. It cannot catch a risk that the tests and formula do not see. Also, the model prompt includes the policy, so a correct model answer is partly instruction following.
- **Prior art:** closest open projects are a hackathon project called DeployGuard and the TDAD test-impact tool. Their repo details were not fully verified, see `../reports/DeploySure AI build research.md`.
