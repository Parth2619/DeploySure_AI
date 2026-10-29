# Full app mode: phased plan

Owner: Manc. Written 20 Oct 2026. Goal: DeploySure protects a whole app (frontend plus backend in a git repo), not just Python files. It detects a new commit, scans what changed across the project, lets an AI write tests for the change, runs them on the old and the new commit, and says whether the app breaks and which layer is at fault.

## Decisions already made

- **AI backend is Groq only.** The Ollama and mock backends are removed from the product. Default model `openai/gpt-oss-120b`, changeable with `GROQ_MODEL`. The key comes from the `GROQ_API_KEY` environment variable and is never stored in the repo.
- **Offline fallback:** with no internet or key, every AI step falls back to its deterministic default and the trace says so. The Critic's rule floor still decides.
- **Tests never call Groq.** The test suite uses a stub that only exists in `tests/`.
- **Free tier limit to design for:** about 8,000 tokens per minute on the 120B model, so prompts stay small (diffs are summarised, not pasted whole).
- **Scope:** one supported stack first: a Python FastAPI backend plus a web frontend in a git repo, run locally with dummy data. The current Demo shop stays as a working fallback.
- Not included: other languages, real production systems, secrets (`.env` values are never read, only `.env.example` and config keys).

## Phases

| Phase | Deliverable | Done when |
|---|---|---|
| 1 | Groq-only LLM backend. Ollama and mock removed. Stub for tests. | `ask()` works through Groq with JSON validation, one retry, rate limit wait and deterministic fallback. All existing tests pass with the stub. |
| 2 | A demo app with a real frontend and backend in its own git repo, with commits: safe change, backend break, frontend break, contract break. | Each commit behaves as designed when run by hand and by a test. |
| 3 | Git scan and project map: commits, diff by layer, dependency and config changes, backend endpoints, frontend API calls, contract map. | The map of the demo app is correct and the diff between two commits lists the right files per layer. |
| 4 | App runner: check out a commit, start backend and frontend on free ports, wait until healthy, stop and clean up. | Old and new commit can run side by side, with timeouts and no leftover processes. |
| 5 | AI test generation and differential run: unit, API and browser tests written by the model, validated, run on old and new. | A test counts only if it passes on the old commit. Regressions are the ones that pass old and fail new. |
| 6 | Layer verdict: frontend, backend or connection, from layered runs and network evidence, fed into risk, Decision and Critic. | The demo commits get the right layer and the right DEPLOY, HOLD or BLOCK. |
| 7 | UI: connect a repo, commit timeline, auto-detect new commits, layered verdict display. | You can connect the demo app and watch a new commit get analyzed on its own. |
| 8 | Hardening, notes and demo script. | Full test run green, demo notes updated, a backup recording plan. |

Each phase ends with the test output shown to Manc before the next one starts.
