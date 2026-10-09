"""IndiaAI Qwen API client. No provider selection or embedded credentials."""
from __future__ import annotations
import os
from app import config


class _CompletionProxy:
    def __init__(self, original):
        self._original = original

    def _params(self, kwargs):
        kwargs = dict(kwargs)
        if "max_completion_tokens" in kwargs:
            kwargs["max_tokens"] = kwargs.pop("max_completion_tokens")
        if os.getenv("INDIAAI_JSON_MODE", "1") == "0":
            kwargs.pop("response_format", None)
        if os.getenv("INDIAAI_DISABLE_THINKING", "1").lower() in ("1", "true", "yes"):
            style = os.getenv("INDIAAI_THINKING_PARAM", "chat_template_kwargs").lower()
            extra = dict(kwargs.get("extra_body") or {})
            if style == "chat_template_kwargs":
                options = dict(extra.get("chat_template_kwargs") or {})
                options["enable_thinking"] = False
                extra["chat_template_kwargs"] = options
            elif style == "enable_thinking":
                extra["enable_thinking"] = False
            else:
                raise ValueError("INDIAAI_THINKING_PARAM must be chat_template_kwargs or enable_thinking")
            kwargs["extra_body"] = extra
        return kwargs

    def create(self, **kwargs):
        return self._original.create(**self._params(kwargs))


class _AsyncCompletionProxy(_CompletionProxy):
    async def create(self, **kwargs):
        return await self._original.create(**self._params(kwargs))


class _ClientProxy:
    def __init__(self, original, asynchronous):
        self._original = original
        completions = _AsyncCompletionProxy if asynchronous else _CompletionProxy
        class ChatProxy:
            pass
        self.chat = ChatProxy()
        self.chat.completions = completions(original.chat.completions)

    def __getattr__(self, name):
        return getattr(self._original, name)


def is_configured():
    return bool(config.INDIAAI_API_KEY)


def make_client(*, asynchronous=False):
    if not is_configured():
        raise RuntimeError("INDIAAI_API_KEY missing in backend/.env")
    if not config.INDIAAI_BASE_URL or "YOUR_AUTHORIZED_GATEWAY" in config.INDIAAI_BASE_URL:
        raise RuntimeError("INDIAAI_BASE_URL missing or placeholder in backend/.env")
    try:
        from openai import OpenAI, AsyncOpenAI
    except ImportError as exc:
        raise RuntimeError("OpenAI-compatible SDK missing: pip install openai") from exc
    cls = AsyncOpenAI if asynchronous else OpenAI
    original = cls(
        base_url=config.INDIAAI_BASE_URL,
        api_key=config.INDIAAI_API_KEY,
        timeout=float(os.getenv("INDIAAI_TIMEOUT_SECONDS", "120")),
        max_retries=0,
    )
    return _ClientProxy(original, asynchronous)


def optional_client():
    return make_client() if is_configured() else None
