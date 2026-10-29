> Obsolete: these results were measured with the old local Ollama backend, which was removed on 20 Oct 2026 in favour of Groq.

# Phase 4 results: real model (Ollama, qwen2.5:7b)

Measured on Manc's laptop (i7-14650HX, RTX 4060 8 GB, model runs 100% on GPU), 16 Oct 2026.
Model load on a cold start: about 10 to 45 s, once. Each run below is warm. Temperature 0, seed 42.

| Setting | Scenario | Expected | Matches | Mean run time | Max | Fallbacks |
|---|---|---|---|---|---|---|
| Seed ON (demo mode) | A, v2.1 | DEPLOY, Critic PASS, retry 0 | 10/10 | 10.2 s | 10.7 s | 0 |
| Seed ON (demo mode) | B, v2.2 | BLOCK, Critic PASS, retry 1 | 10/10 | 22.1 s | 23.5 s | 0 |
| Seed OFF (model alone) | A, v2.1 | DEPLOY, Critic PASS, retry 0 | 10/10 | 11.5 s | 12.2 s | 0 |
| Seed OFF (model alone) | B, v2.2 | BLOCK, Critic PASS, retry 0 | 10/10 | 11.1 s | 12.2 s | 0 |

What this shows and does not show:
- With the seed on, the first decision is forced to DEPLOY, so the model's own judgement is only exercised on B's second pass. The seed-off rows test the model's unaided decision.
- The model is given the policy in its prompt, so correct answers here are partly instruction following. The Critic's rule check in code is the real safety net.
- Run time is mostly pytest start-up, not the model. Scenario B is slower because the retry reruns the whole pipeline.
- 20 of 20 runs per setting is a small sample on one machine. It is not a guarantee.
