"""One entry point for every LLM call: ask(). The only backend is Groq (hosted, free tier).

Set GROQ_API_KEY in the environment or in deploysure/.env. Pick another model with GROQ_MODEL.
Every answer is validated against a pydantic schema. On invalid output or any failure we retry once, then return
the caller's deterministic default and report that the fallback was used. last_error says why.
Free tier limits are small (about 8,000 tokens per minute on the 120B model), so keep prompts short.
"""
import itertools
import os
import time
from pathlib import Path

import httpx
from pydantic import BaseModel

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"  # git-ignored, holds GROQ_API_KEY=... for this project only

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-120b"  # the largest production model on Groq at the time of writing
GROQ_TIMEOUT = 60
MAX_WAIT = 20  # longest we wait after a rate limit (429) before one retry

PLAN = ["Analyse code changes", "Find impacted modules", "Select tests", "Run selected tests",
        "Score release risk", "Decide DEPLOY, HOLD or BLOCK", "Critic validation"]

last_error = ""  # why the latest call fell back, empty after a success
call_log: list[dict] = []  # the latest calls with their prompt and answer, so the UI can show what an agent received and said
MAX_LOGGED_CALLS = 40
MAX_LOGGED_PROMPT = 6000
_call_ids = itertools.count(1)


def _log_call(task: str, prompt: str, answer: dict, fallback: bool) -> None:
    call_log.append({"id": next(_call_ids), "task": task, "prompt": prompt[:MAX_LOGGED_PROMPT] + (" [cut]" if len(prompt) > MAX_LOGGED_PROMPT else ""),
                     "answer": answer, "fallback": fallback, "error": last_error[:200] if fallback else ""})
    del call_log[:-MAX_LOGGED_CALLS]  # the key is never part of a prompt, and the log stays small


def _api_key() -> str:
    """The key from the environment, else from deploysure/.env (so it can stay inside this project only)."""
    key = os.getenv("GROQ_API_KEY", "").strip()
    if key or not ENV_FILE.is_file():
        return key
    for line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        name, _, value = line.partition("=")
        if name.strip() == "GROQ_API_KEY":
            return value.strip().strip("\"'")
    return ""


def _groq_answer(prompt: str, schema: type[BaseModel] | None) -> str:
    key = _api_key()
    if not key:
        raise RuntimeError("GROQ_API_KEY is not set")
    model = os.getenv("GROQ_MODEL", DEFAULT_MODEL)
    system = "Reply with one JSON object only, no other text."
    if schema is not None:
        system += " It must match this JSON schema: " + str(schema.model_json_schema())
    body = {
        "model": model, "temperature": 0, "seed": 42, "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
    }
    if "gpt-oss" in model:
        body["reasoning_effort"] = "low"  # faster, and these answers are short
    for attempt in range(2):
        reply = httpx.post(GROQ_URL, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=GROQ_TIMEOUT)
        if reply.status_code == 429 and attempt == 0:  # rate limited: wait as told (capped), then try once more
            time.sleep(min(float(reply.headers.get("retry-after", "2")), MAX_WAIT))
            continue
        reply.raise_for_status()
        return reply.json()["choices"][0]["message"]["content"]


def fallback_note(used: str) -> str:
    """Trace text for a step that fell back: what was used instead, and why the AI was not."""
    return f" (AI not used, {used}. Reason: {last_error[:100]})"


def ask(prompt: str, schema: type[BaseModel] | None = None, *, task: str = "",
        default: dict | None = None) -> tuple[dict, bool]:
    """Returns (answer, fallback_used). Without a schema the answer is {'text': raw}."""
    global last_error
    for _ in range(2):  # first try plus one retry
        try:
            raw = _groq_answer(prompt, schema)
            answer = schema.model_validate_json(raw).model_dump() if schema else {"text": raw}
            last_error = ""
            _log_call(task, prompt, answer, False)
            return answer, False
        except Exception as err:  # bad JSON, schema mismatch, rate limit, timeout, no key or no internet
            last_error = f"{type(err).__name__}: {err}"
    if default is None:
        raise RuntimeError(f"LLM task {task!r} failed twice and no default was given: {last_error}")
    _log_call(task, prompt, default, True)
    return default, True
