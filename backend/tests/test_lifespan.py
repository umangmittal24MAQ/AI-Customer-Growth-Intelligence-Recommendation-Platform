"""Ensure startup initialization and pooled-client cleanup are paired."""
from fastapi.testclient import TestClient


def test_lifespan_calls_startup_and_close(monkeypatch):
    from app import main
    from app.agents import clients

    calls = []
    monkeypatch.setattr(main, "_log_startup", lambda: calls.append("startup"))

    async def close():
        calls.append("closed")
    monkeypatch.setattr(clients, "close_clients", close)

    with TestClient(main.app) as client:
        assert client.get("/").status_code == 200
        assert calls == ["startup"]
    assert calls == ["startup", "closed"]
