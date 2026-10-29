# Demo notes

## 60 to 90 second explanation

"When a team releases new code, passing tests is not the same as being safe to ship. This system takes a release and
runs a pipeline. It looks at what is being released, picks the relevant tests, really runs them, turns the evidence into
a risk score from 0 to 100, and applies explicit gate rules to decide DEPLOY, HOLD or BLOCK. Then a separate Critic
checks that decision against the raw test report. If the decision contradicts the evidence, for example DEPLOY while a
critical test failed, the Critic rejects it. I will run it on a good release, then swap in one buggy file and run the
exact same command."

## The stages in plain words

1. **Analyze release:** finds the file being released and compares it with the approved baseline.
2. **Select tests:** chooses the tests that cover the changed component and shows why. The core regression suite always runs.
3. **Execute tests:** runs real pytest and records what passed, what failed and why. A failed assertion is a regression. An error or crash is an execution problem, which is a different thing.
4. **Score risk:** adds up fixed, documented points: failure rate, critical failures, severity, missing evidence.
5. **Deployment gate:** explicit rules turn the evidence into DEPLOY, HOLD or BLOCK.
6. **Critic:** re-derives the least cautious allowed decision from the raw report and compares it with the gate.

## Scenario A (say while it runs)

"This is the approved version. All 13 tests pass, the risk score is 5, which is low, the gate says DEPLOY and the
Critic approves. Nothing about the result is typed in. It comes from running the tests just now."

## While replacing the file

"I am replacing one file only, the pricing module, with a version that has a regression. I am not touching the tests,
the gate or the scoring. The code looks plausible: someone simplified the discount formula and now subtracts the
percentage as a flat amount."

```powershell
Copy-Item .\bug_variants\pricing_buggy.py .\demo_app\pricing.py -Force
python .\scripts\run_demo.py
```

## Scenario B (say when it shows BLOCK)

"Same command, same tests. Now 6 tests fail, 4 of them critical. For example a 10 percent discount on 200 gives 190
instead of 180, and a 100 percent discount gives minus 50. The risk score jumps to 81, but the block does not depend on
the score: a critical test failed, and that alone blocks the release. The Critic checked the report independently and
confirmed that BLOCK is correct."

Recovery after the demo: `Copy-Item .\baseline\pricing.py .\demo_app\pricing.py -Force`

## Four things that are easy to mix up

- **Test failure:** one fact. A specific assertion did not hold.
- **Risk score:** a summary number made from many facts by fixed rules. It helps compare releases, but it is not the decision.
- **Deployment decision:** the action: DEPLOY, HOLD or BLOCK. Rules decide it, and a critical failure always blocks, even if the score would be low.
- **Critic validation:** a second, independent check that the decision matches the evidence. It can overrule a wrong decision.

## Why this is not just a test runner

A test runner reports pass or fail per test and stops there. This system weighs how important the failing behavior is,
decides what to do about the release, gives reasons, and checks its own decision before anyone acts on it. It also
treats "the tests could not run" as unknown (HOLD), not as safe.

## Likely questions

- **Is the BLOCK just hard-coded?** No. Run it on the original file and you get DEPLOY. The tests, gate and scoring are identical in both runs. Only the code under test changes.
- **What if the tests do not cover the bug?** Then the system cannot see it. It gives evidence-based risk assessment, not a guarantee. That is a stated limit.
- **Why a score and a gate?** The score is a transparent summary. The gate has hard rules so a single critical failure can never be hidden by a low average.
- **What does the Critic add if the gate is already correct?** It protects against a wrong decision. It starts from the raw test report and does not trust the gate. The unit tests feed it a wrong DEPLOY and show it rejecting it.
- **Where does AI come in?** This standalone demo is fully deterministic and uses no model, so it runs offline. In the main DeploySure app, models write plans, checks and explanations, while the tests, scores and gate rules stay in plain code.
- **What if pytest itself crashes?** The result is HOLD, exit code 2, because there is no usable evidence.
- **Are the risk weights validated?** No. They are chosen and documented for this demo, not calibrated on real data.
