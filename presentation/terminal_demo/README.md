# Deployment risk demo (standalone)

A small, self-contained demo of a deployment gate. It has no connection to the rest of the repository, needs no
key, no network and no database, and everything runs locally and gives the same result every time.

Pipeline: Analyze release, select tests, run tests, score risk, deployment gate, Critic checks the decision.

The fictional app is a pricing module (`demo_app/pricing.py`): a percentage discount and a cart total.

## Setup (once, Windows PowerShell)

```powershell
cd presentation\terminal_demo

python -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install -r requirements.txt

python .\scripts\verify_setup.py
```

`verify_setup.py` checks Python, pytest, every file, that the pricing tests can be collected, and that the buggy
file is a drop-in replacement (same function names and signatures).

## Scenario A: safe release

```powershell
python .\scripts\run_demo.py
```

Expected: all 13 tests pass, risk score 5/100 (LOW), gate DEPLOY, Critic APPROVED, exit code 0.

## Scenario B: buggy release

Replace only the pricing file, then run the same command again. Do not touch the tests, the gate or the scoring.

```powershell
Copy-Item .\bug_variants\pricing_buggy.py .\demo_app\pricing.py -Force
python .\scripts\run_demo.py
```

Expected: 6 tests fail (4 of them critical), risk score 81/100 (CRITICAL), gate BLOCK, Critic CONFIRMED, exit code 1.
The failing assertions are printed with their real values, for example `assert 190.0 == 180.0`.

## Recovery (after the presentation, or to run Scenario A again)

```powershell
Copy-Item .\baseline\pricing.py .\demo_app\pricing.py -Force
python .\scripts\run_demo.py
```

This restores the correct file. It does not need a reinstall and the tests are never edited.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | DEPLOY |
| 1 | BLOCK |
| 2 | HOLD (no usable evidence, or a non-critical failure) |
| 3 | The Critic rejected the gate's decision |

## The rules

Tests: `tests/test_pricing.py` always runs. A test named `test_critical_*` guards revenue.

Risk score (`app/risk_scorer.py`, 0 to 100, the same rules in both scenarios):

| Factor | Points |
|---|---|
| Component criticality (pricing handles money) | 5 |
| Failure rate | 35 x failed / all tests |
| Critical regression (a critical test failed) | 30 |
| Assertion severity | 10 per failed critical test, 3 per other failure, capped at 25 |
| Missing evidence (tests could not run) | 45 |
| Unreviewed change (file differs from `baseline/pricing.py`) | 5 |

Levels: 0 to 30 LOW, 31 to 60 MEDIUM, 61 to 80 HIGH, 81 to 100 CRITICAL.

Gate (`app/deployment_gate.py`, the first rule that applies wins):

1. A critical test failed: BLOCK, whatever the score says.
2. Risk score 81 or more: BLOCK.
3. Release file missing, or the tests could not run (errors, crash, no tests): HOLD.
4. Any other test failed: HOLD.
5. Risk score above 30: HOLD.
6. Otherwise: DEPLOY.

Critic (`app/critic.py`): works out the least cautious decision the raw test report allows, without calling the gate,
and rejects the gate if its decision is weaker (for example DEPLOY with a critical failure) or if the report is
inconsistent. A rejected decision is replaced by the Critic's minimum and the exit code is 3.

A file is never blocked only because it changed or because of its name. The decision comes from the executed tests.

## Run the demo's own tests

```powershell
python -m pytest -q
```

`tests/test_deployment_gate.py` runs every scenario on a temporary copy, so it passes whichever pricing file is
currently in `demo_app/`. `tests/test_pricing.py` tests the live `demo_app/pricing.py`, so it fails in Scenario B on purpose.

## Connect app

This terminal demo is a pricing module only, so it is not meant for Connect app. The web version of the same idea,
built for Connect app, is in `..\stage_app` (see `..\README.md`).
