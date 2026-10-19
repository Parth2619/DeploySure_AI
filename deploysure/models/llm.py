"""One entry point for every LLM call: ask(). Backend is chosen by DEPLOYSURE_LLM (mock or ollama).

Every answer is validated against a pydantic schema. On invalid output we retry once, then
return the caller's deterministic default and report that the fallback was used.
"""
import json
import os
import re

from pydantic import BaseModel

OLLAMA_MODEL = os.getenv("DEPLOYSURE_MODEL", "qwen2.5:7b")
OLLAMA_TIMEOUT = 60

PLAN = ["Analyse code changes", "Find impacted modules", "Select tests", "Run selected tests",
        "Score release risk", "Decide DEPLOY, HOLD or BLOCK", "Critic validation"]


def _mock_decision(prompt: str) -> dict:
    """Stands in for a competent model: reads the evidence lines and applies the policy."""
    def field(name: str) -> str:
        m = re.search(rf"^{name}: (\w+)", prompt, re.MULTILINE)
        return m.group(1) if m else "0"

    if int(field("failed_critical")) > 0 or field("risk_level") == "CRITICAL":
        return {"decision": "BLOCK", "reason": "A critical test failed or risk is CRITICAL, so the release must not ship."}
    if field("risk_level") in ("HIGH", "MEDIUM") or int(field("failed_noncritical")) > 0:
        return {"decision": "HOLD", "reason": "Risk is elevated or a test failed, so the release needs review first."}
    return {"decision": "DEPLOY", "reason": "All selected tests passed and risk is LOW."}


def _mock_answer(prompt: str, task: str) -> dict:
    canned = {
        "planner": {"tasks": PLAN},
        "impact": {"explanation": "Modules that import the changed code can behave differently, so their tests are re-run."},
        "test_selection": {"reason": "Tests were chosen from the impacted modules by the selection rule."},
        "critic": {"reason": "The decision was compared with the release policy rules."},
    }
    return _mock_decision(prompt) if task == "decision" else canned[task]


def _ollama_answer(prompt: str, schema: type[BaseModel] | None) -> str:
    from ollama import Client  # imported here so mock mode works without the server

    reply = Client(timeout=OLLAMA_TIMEOUT).chat(
        model=OLLAMA_MODEL,
        messages=[{"role": "user", "content": prompt}],
        format=schema.model_json_schema() if schema else None,
        options={"temperature": 0, "seed": 42},
        keep_alive="30m",
    )
    return reply.message.content


def _raw_answer(prompt: str, schema: type[BaseModel] | None, task: str) -> str:
    backend = os.getenv("DEPLOYSURE_LLM", "mock")
    if backend == "mock":
        return json.dumps(_mock_answer(prompt, task))
    if backend == "ollama":
        return _ollama_answer(prompt, schema)
    raise ValueError(f"DEPLOYSURE_LLM must be 'mock' or 'ollama', got {backend!r}")


def ask(prompt: str, schema: type[BaseModel] | None = None, *, task: str = "",
        default: dict | None = None) -> tuple[dict, bool]:
    """Returns (answer, fallback_used). Without a schema the answer is {'text': raw}."""
    for _ in range(2):  # first try plus one retry
        try:
            raw = _raw_answer(prompt, schema, task)
            return (schema.model_validate_json(raw).model_dump() if schema else {"text": raw}), False
        except Exception:  # bad JSON, schema mismatch, timeout or server down: all handled the same way
            continue
    if default is None:
        raise RuntimeError(f"LLM task {task!r} failed twice and no default was given")
    return default, True
