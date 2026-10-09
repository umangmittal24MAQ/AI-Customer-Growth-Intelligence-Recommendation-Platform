"""Check private OpenAI-compatible gateway routing without sending network traffic."""
import asyncio
import sys
from types import ModuleType, SimpleNamespace

from app import config
from app import indiaai_client
import pytest

@pytest.fixture(autouse=True)
def endpoint(monkeypatch):
    monkeypatch.setattr(config, "INDIAAI_BASE_URL", "https://example.invalid/v1")



def test_indiaai_sync_provider(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "indiaai")
    monkeypatch.setattr(config, "INDIAAI_API_KEY", "local-fake-token")
    monkeypatch.setattr(config, "INDIAAI_BASE_URL", "https://example.invalid/v1")
    completions = SimpleNamespace(create=lambda **kwargs: kwargs)
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions), close=lambda: None)
    fake_openai = ModuleType("openai")
    def factory(**kwargs):
        assert kwargs["base_url"] == "https://example.invalid/v1"
        assert kwargs["api_key"] == "local-fake-token"
        return fake_client
    fake_openai.OpenAI = factory
    fake_openai.AsyncOpenAI = factory
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    monkeypatch.setenv("INDIAAI_JSON_MODE", "0")
    monkeypatch.setenv("INDIAAI_DISABLE_THINKING", "0")
    client = indiaai_client.make_client()
    assert client.chat.completions.create(model="qwen-3.8-27b", max_completion_tokens=300,
                                          response_format={"type": "json_object"}) == {
        "model": "qwen-3.8-27b", "max_tokens": 300,
    }
    client.close()


def test_indiaai_async_provider(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "indiaai")
    monkeypatch.setattr(config, "INDIAAI_API_KEY", "local-fake-token")
    async def create(**kwargs):
        return kwargs
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    fake_openai = ModuleType("openai")
    fake_openai.AsyncOpenAI = lambda **kwargs: fake_client
    fake_openai.OpenAI = lambda **kwargs: fake_client
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    monkeypatch.setenv("INDIAAI_JSON_MODE", "1")
    client = indiaai_client.make_client(asynchronous=True)
    result = asyncio.run(client.chat.completions.create(model="qwen-3.8-27b", response_format={"type": "json_object"}))
    assert result["response_format"] == {"type": "json_object"}


def test_indiaai_rate_limit_retry(monkeypatch):
    from app.llm_retry import completion_with_retry
    class RateLimit(Exception):
        status_code = 429
        response = SimpleNamespace(headers={"retry-after": "1"})
    class FakeCompletions:
        calls = 0
        async def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RateLimit()
            return kwargs
    completions = FakeCompletions()
    fake = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    async def noop(_): return None
    monkeypatch.setattr("app.llm_retry.asyncio.sleep", noop)
    result = asyncio.run(completion_with_retry(fake, model="qwen-3.8-27b"))
    assert result["model"] == "qwen-3.8-27b"
    assert completions.calls == 2


def test_indiaai_disable_thinking_vllm(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "indiaai")
    monkeypatch.setattr(config, "INDIAAI_API_KEY", "local-fake-token")
    monkeypatch.setenv("INDIAAI_DISABLE_THINKING", "1")
    monkeypatch.setenv("INDIAAI_THINKING_PARAM", "chat_template_kwargs")
    captured = {}
    def create(**kwargs):
        captured.update(kwargs)
        return kwargs
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=lambda: None)
    fake_openai = ModuleType("openai")
    fake_openai.OpenAI = lambda **kwargs: fake_client
    fake_openai.AsyncOpenAI = lambda **kwargs: fake_client
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    client = indiaai_client.make_client()
    result = client.chat.completions.create(model="qwen-3.8-27b", extra_body={"trace": "test"})
    assert result["extra_body"] == {"trace": "test", "chat_template_kwargs": {"enable_thinking": False}}
    client.close()


def test_indiaai_disable_thinking_direct(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "indiaai")
    monkeypatch.setattr(config, "INDIAAI_API_KEY", "local-fake-token")
    monkeypatch.setenv("INDIAAI_DISABLE_THINKING", "1")
    monkeypatch.setenv("INDIAAI_THINKING_PARAM", "enable_thinking")
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: kwargs)), close=lambda: None)
    fake_openai = ModuleType("openai")
    fake_openai.OpenAI = lambda **kwargs: fake_client
    fake_openai.AsyncOpenAI = lambda **kwargs: fake_client
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    client = indiaai_client.make_client()
    result = client.chat.completions.create(model="qwen-3.8-27b")
    assert result["extra_body"] == {"enable_thinking": False}
    client.close()
