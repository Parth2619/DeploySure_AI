import json

import pytest
from pydantic import BaseModel

from deploysure.models import llm


class Thing(BaseModel):
    reason: str


def test_mock_answer_is_schema_valid(monkeypatch):
    monkeypatch.setenv("DEPLOYSURE_LLM", "mock")
    answer, fallback = llm.ask("x", Thing, task="critic", default={"reason": "d"})
    assert not fallback and answer["reason"]


def test_invalid_output_retries_once_then_falls_back(monkeypatch):
    calls = []

    def bad(prompt, schema, task):
        calls.append(1)
        return "not json"

    monkeypatch.setattr(llm, "_raw_answer", bad)
    answer, fallback = llm.ask("x", Thing, task="critic", default={"reason": "default"})
    assert fallback and answer == {"reason": "default"} and len(calls) == 2


def test_retry_can_recover(monkeypatch):
    replies = iter(["oops", json.dumps({"reason": "ok"})])
    monkeypatch.setattr(llm, "_raw_answer", lambda *a: next(replies))
    answer, fallback = llm.ask("x", Thing, task="critic", default={"reason": "default"})
    assert answer == {"reason": "ok"} and not fallback


def test_no_default_raises(monkeypatch):
    monkeypatch.setattr(llm, "_raw_answer", lambda *a: "oops")
    with pytest.raises(RuntimeError):
        llm.ask("x", Thing, task="critic")


def test_unknown_backend_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("DEPLOYSURE_LLM", "nope")
    _, fallback = llm.ask("x", Thing, task="critic", default={"reason": "d"})
    assert fallback


def test_mock_decision_follows_evidence():
    block = "risk_level: CRITICAL\nfailed_critical: 2\nfailed_noncritical: 0\n"
    low = "risk_level: LOW\nfailed_critical: 0\nfailed_noncritical: 0\n"
    assert llm._mock_decision(block)["decision"] == "BLOCK"
    assert llm._mock_decision(low)["decision"] == "DEPLOY"
