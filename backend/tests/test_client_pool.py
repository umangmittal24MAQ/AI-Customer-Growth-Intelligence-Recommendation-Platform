"""IndiaAI-only routing must reuse one connection for independent agents."""
import asyncio
from types import SimpleNamespace

from app.agents import clients


def test_both_agent_roles_share_one_qwen_connection(monkeypatch):
    constructed = []
    closed = []

    async def close():
        closed.append(True)

    def make_client(*, asynchronous=False):
        assert asynchronous
        constructed.append(True)
        return SimpleNamespace(close=close)

    monkeypatch.setattr(clients, "make_client", make_client)
    monkeypatch.setattr(clients, "_shared_builder", None)
    first = clients.get_mini_client()
    second = clients.get_strong_client()
    assert first is second
    assert len(constructed) == 1

    asyncio.run(clients.close_clients())
    assert closed == [True]
    assert clients._shared_builder is None
