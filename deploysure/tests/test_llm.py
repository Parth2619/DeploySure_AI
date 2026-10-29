import json
import os

import httpx
import pytest
from pydantic import BaseModel

from deploysure.models import llm
from tests import fake_llm


class Thing(BaseModel):
    reason: str


def reply(content: str, status: int = 200, headers: dict | None = None) -> httpx.Response:
    body = {"choices": [{"message": {"content": content}}]}
    return httpx.Response(status, json=body, headers=headers or {}, request=httpx.Request("POST", llm.GROQ_URL))


# ---------- ask(): validation, retry, fallback (the AI stub is installed for these) ----------

def test_valid_answer_is_returned_without_fallback(monkeypatch):
    monkeypatch.setattr(llm, "_groq_answer", lambda *a: '{"reason": "fine"}')
    answer, fallback = llm.ask("x", Thing, task="critic", default={"reason": "d"})
    assert answer == {"reason": "fine"} and not fallback


def test_invalid_output_retries_once_then_falls_back(monkeypatch):
    calls = []

    def bad(prompt, schema):
        calls.append(1)
        return "not json"

    monkeypatch.setattr(llm, "_groq_answer", bad)
    answer, fallback = llm.ask("x", Thing, task="critic", default={"reason": "default"})
    assert fallback and answer == {"reason": "default"} and len(calls) == 2


def test_retry_can_recover(monkeypatch):
    replies = iter(["oops", json.dumps({"reason": "ok"})])
    monkeypatch.setattr(llm, "_groq_answer", lambda *a: next(replies))
    answer, fallback = llm.ask("x", Thing, task="critic", default={"reason": "default"})
    assert answer == {"reason": "ok"} and not fallback


def test_no_default_raises(monkeypatch):
    monkeypatch.setattr(llm, "_groq_answer", lambda *a: "oops")
    with pytest.raises(RuntimeError):
        llm.ask("x", Thing, task="critic")


def test_last_error_says_why_the_fallback_happened(monkeypatch):
    def boom(prompt, schema):
        raise RuntimeError("GROQ_API_KEY is not set")

    monkeypatch.setattr(llm, "_groq_answer", boom)
    _, fallback = llm.ask("x", Thing, default={"reason": "d"})
    assert fallback and "GROQ_API_KEY" in llm.last_error
    monkeypatch.setattr(llm, "_groq_answer", lambda *a: json.dumps({"reason": "ok"}))
    llm.ask("x", Thing, default={"reason": "d"})
    assert llm.last_error == ""


def test_stub_decision_follows_the_evidence():
    block = "risk_level: CRITICAL\nfailed_critical: 2\nfailed_noncritical: 0\n"
    low = "risk_level: LOW\nfailed_critical: 0\nfailed_noncritical: 0\n"
    assert fake_llm.decision(block)["decision"] == "BLOCK"
    assert fake_llm.decision(low)["decision"] == "DEPLOY"


# ---------- the real Groq client code, with the HTTP layer faked ----------

@pytest.mark.real_llm
def test_groq_request_shape_and_answer(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "secret-key-123")
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    sent = {}

    def fake_post(url, headers, json, timeout):
        sent.update(url=url, headers=headers, body=json, timeout=timeout)
        return reply('{"reason": "fine"}')

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    answer, fallback = llm.ask("Why?", Thing, task="critic", default={"reason": "d"})
    assert answer == {"reason": "fine"} and not fallback
    assert sent["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert sent["headers"]["Authorization"] == "Bearer secret-key-123"
    body = sent["body"]
    assert body["model"] == "openai/gpt-oss-120b" and body["temperature"] == 0
    assert body["response_format"] == {"type": "json_object"} and body["reasoning_effort"] == "low"
    assert "reason" in body["messages"][0]["content"] and body["messages"][1] == {"role": "user", "content": "Why?"}


@pytest.mark.real_llm
def test_groq_model_can_be_changed_with_an_env_var(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    seen = {}
    monkeypatch.setattr(llm.httpx, "post", lambda url, headers, json, timeout: seen.update(body=json) or reply('{"reason": "x"}'))
    llm.ask("x", Thing, default={"reason": "d"})
    assert seen["body"]["model"] == "llama-3.3-70b-versatile" and "reasoning_effort" not in seen["body"]


@pytest.mark.real_llm
def test_groq_rate_limit_waits_once_then_succeeds(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    responses = iter([reply("", 429, {"retry-after": "3"}), reply('{"reason": "ok"}')])
    waits = []
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: next(responses))
    monkeypatch.setattr(llm.time, "sleep", waits.append)
    answer, fallback = llm.ask("x", Thing, default={"reason": "d"})
    assert answer == {"reason": "ok"} and not fallback and waits == [3.0]


@pytest.mark.real_llm
def test_groq_rate_limit_wait_is_capped(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    responses = iter([reply("", 429, {"retry-after": "600"}), reply('{"reason": "ok"}')])
    waits = []
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: next(responses))
    monkeypatch.setattr(llm.time, "sleep", waits.append)
    llm.ask("x", Thing, default={"reason": "d"})
    assert waits == [llm.MAX_WAIT]


@pytest.mark.real_llm
def test_groq_missing_key_falls_back_and_says_why(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    answer, fallback = llm.ask("x", Thing, default={"reason": "default"})
    assert fallback and answer == {"reason": "default"} and "GROQ_API_KEY" in llm.last_error


def test_every_call_is_logged_with_its_prompt_and_answer_and_the_log_stays_small(monkeypatch):
    llm.call_log.clear()
    answer, fallback = llm.ask("hello", Thing, task="t1", default={"reason": "d"})
    assert llm.call_log[-1]["task"] == "t1" and llm.call_log[-1]["prompt"] == "hello" and llm.call_log[-1]["answer"] == answer
    assert llm.call_log[-1]["fallback"] is fallback
    llm.ask("x" * (llm.MAX_LOGGED_PROMPT + 500), Thing, task="long", default={"reason": "d"})
    assert len(llm.call_log[-1]["prompt"]) < llm.MAX_LOGGED_PROMPT + 20 and llm.call_log[-1]["prompt"].endswith("[cut]")
    for n in range(llm.MAX_LOGGED_CALLS + 10):
        llm.ask(str(n), Thing, task="many", default={"reason": "d"})
    assert len(llm.call_log) == llm.MAX_LOGGED_CALLS
    ids = [c["id"] for c in llm.call_log]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)


def test_a_failed_call_is_logged_as_a_fallback_with_the_reason(monkeypatch):
    def broken(prompt, schema):
        raise RuntimeError("GROQ_API_KEY is not set")
    monkeypatch.setattr(llm, "_groq_answer", broken)
    answer, fallback = llm.ask("p", Thing, task="down", default={"reason": "fixed"})
    entry = llm.call_log[-1]
    assert fallback and entry["fallback"] is True and entry["answer"] == {"reason": "fixed"} and "GROQ_API_KEY" in entry["error"]


def test_the_key_can_come_from_the_project_env_file(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    monkeypatch.setattr(llm, "ENV_FILE", env)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert llm._api_key() == ""  # no file
    env.write_text('OTHER=1\nGROQ_API_KEY = "from-file"\n', encoding="utf-8")
    assert llm._api_key() == "from-file"
    monkeypatch.setenv("GROQ_API_KEY", "from-env")
    assert llm._api_key() == "from-env"  # the environment wins


@pytest.mark.real_llm
def test_groq_http_error_falls_back_without_leaking_the_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "secret-key-123")
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: reply("", 500))
    _, fallback = llm.ask("x", Thing, default={"reason": "d"})
    assert fallback and "500" in llm.last_error and "secret-key-123" not in llm.last_error


@pytest.mark.real_llm
def test_groq_network_failure_falls_back(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")

    def down(*a, **k):
        raise httpx.ConnectError("no internet")

    monkeypatch.setattr(llm.httpx, "post", down)
    _, fallback = llm.ask("x", Thing, default={"reason": "d"})
    assert fallback and "no internet" in llm.last_error


@pytest.mark.real_llm
@pytest.mark.skipif(not os.getenv("GROQ_API_KEY"), reason="needs a real GROQ_API_KEY and internet")
def test_live_groq_smoke():
    answer, fallback = llm.ask('Reply with {"reason": "pong"}', Thing, default={"reason": "d"})
    assert not fallback, llm.last_error
