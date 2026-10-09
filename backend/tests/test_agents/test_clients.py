"""Provider migration contract tests: no network required."""
import asyncio
import json
from types import SimpleNamespace

import pytest
from app import config
from app.agents import clients
from app.indiaai_client import make_client
from app.models import SignalVerdict


def test_missing_key_has_actionable_message(monkeypatch):
    monkeypatch.setattr(config, "INDIAAI_API_KEY", "")
    with pytest.raises(RuntimeError, match="INDIAAI_API_KEY"):
        make_client(asynchronous=True)


class FakeCompletions:
    def __init__(self, content):
        self.content = content
        self.requests = []

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))])


@pytest.mark.parametrize("content,expected_fallback", [
    ('{"proceed": true, "reason": "Growth", "urgency": "low"}', False),
    ('{"proceed": "no", "reason": "Growth", "urgency": "invalid"}', True),
])
def test_indiaai_agent_validates_and_traces_fallback(content, expected_fallback):
    completions = FakeCompletions(content)
    fake = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    real = clients.IndiaAIStructuredAgent(fake, "qwen-3.8-27b", "signal", "Decide account", SignalVerdict)
    agent = clients.wrap_agent(real, clients.build_signal_fallback, name="signal")
    result = asyncio.run(agent.run(json.dumps({"customer_profile": {"name": "ACME"}})))
    assert result.used_fallback is expected_fallback
    assert isinstance(result.value, SignalVerdict)
    assert len(completions.requests) == 1
    req = completions.requests[0]
    assert req["model"] == "qwen-3.8-27b"
    assert req["response_format"] == {"type": "json_object"}


def test_indiaai_provider_config_wires_sync_and_async(monkeypatch):
    import sys
    import types
    monkeypatch.setattr(config, "INDIAAI_API_KEY", "fake-token")
    monkeypatch.setattr(config, "INDIAAI_BASE_URL", "https://example.invalid/v1")
    fake_sdk = types.ModuleType("openai")
    captured = []
    def factory(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **k: k)))
    fake_sdk.OpenAI = factory
    fake_sdk.AsyncOpenAI = factory
    monkeypatch.setitem(sys.modules, "openai", fake_sdk)
    assert make_client().chat.completions.create(model="qwen-3.8-27b")["model"] == "qwen-3.8-27b"
    assert len(captured) == 1
    assert captured[0]["api_key"] == "fake-token"
    make_client(asynchronous=True)
    assert len(captured) == 2


def test_indiaai_agent_retries_empty_final_content():
    class Recover:
        def __init__(self): self.requests=[]
        async def create(self, **kwargs):
            self.requests.append(kwargs)
            content = None if len(self.requests)==1 else '{"proceed": true, "reason": "Growth", "urgency": "low"}'
            msg = SimpleNamespace(content=content, reasoning_content="thinking" if content is None else None)
            choice = SimpleNamespace(message=msg, finish_reason="length" if content is None else "stop")
            return SimpleNamespace(choices=[choice], usage=SimpleNamespace(completion_tokens=kwargs["max_tokens"]))
    endpoint=Recover()
    agent=clients.IndiaAIStructuredAgent(SimpleNamespace(chat=SimpleNamespace(completions=endpoint)),
                                         "qwen-3.8-27b", "signal", "Decide account", SignalVerdict)
    result=asyncio.run(agent.run('{"customer": "Acme"}'))
    assert result.value.proceed is True
    assert len(endpoint.requests)==2
    assert endpoint.requests[1]["max_tokens"] > endpoint.requests[0]["max_tokens"]


def test_indiaai_empty_response_never_approves():
    class Empty:
        async def create(self, **kwargs):
            msg=SimpleNamespace(content=None, reasoning_content="internal")
            return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")],
                                   usage=SimpleNamespace(completion_tokens=1700))
    real=clients.IndiaAIStructuredAgent(SimpleNamespace(chat=SimpleNamespace(completions=Empty())),
                                        "qwen-3.8-27b", "signal", "Decide account", SignalVerdict)
    wrapped=clients.wrap_agent(real, clients.build_signal_fallback, name="signal")
    result=asyncio.run(wrapped.run('{"customer": "Acme"}'))
    assert result.used_fallback
