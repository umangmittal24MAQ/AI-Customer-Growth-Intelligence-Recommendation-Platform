"""Shared LLM provider factory. Historic filename kept to preserve imports.

LLM_PROVIDER=groq or indiaai. All credentials stay on the backend.
"""
from __future__ import annotations
from app import config
import os


class _CompletionProxy:
    """Optional compatibility toggles for OpenAI-compatible private gateways."""
    def __init__(self, original):
        self._original = original

    def _params(self, kwargs):
        kwargs = dict(kwargs)
        # max_completion_tokens may not be supported by all private gateways.
        if "max_completion_tokens" in kwargs:
            kwargs["max_tokens"] = kwargs.pop("max_completion_tokens")
        if os.getenv("INDIAAI_JSON_MODE", "1") == "0":
            kwargs.pop("response_format", None)
        # A reasoning-enabled Qwen deployment can spend all available output
        # tokens before reaching its final JSON. The MAQ gateway's supported
        # request extensions are unknown, so keep this strictly opt-in.
        if os.getenv("INDIAAI_DISABLE_THINKING", "0").lower() in ("1", "true", "yes"):
            style = os.getenv("INDIAAI_THINKING_PARAM", "chat_template_kwargs").lower()
            extra = dict(kwargs.get("extra_body") or {})
            if style == "chat_template_kwargs":
                chat_kwargs = dict(extra.get("chat_template_kwargs") or {})
                chat_kwargs["enable_thinking"] = False
                extra["chat_template_kwargs"] = chat_kwargs
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


class _ChatProxy:
    def __init__(self, client, asynchronous):
        cls = _AsyncCompletionProxy if asynchronous else _CompletionProxy
        self.completions = cls(client.chat.completions)


class _ClientProxy:
    def __init__(self, original, asynchronous):
        self._original = original
        self.chat = _ChatProxy(original, asynchronous)

    def __getattr__(self, name):
        return getattr(self._original, name)



def is_configured() -> bool:
    if config.LLM_PROVIDER == "indiaai":
        return bool(config.INDIAAI_API_KEY)
    return bool(config.GROQ_API_KEY)


def make_client(*, asynchronous: bool = False):
    if config.LLM_PROVIDER == "indiaai":
        if not config.INDIAAI_API_KEY:
            raise RuntimeError("INDIAAI_API_KEY missing in backend/.env")
        try:
            from openai import OpenAI, AsyncOpenAI
        except ImportError as exc:
            raise RuntimeError("OpenAI-compatible SDK missing: pip install openai") from exc
        cls = AsyncOpenAI if asynchronous else OpenAI
        original = cls(
            base_url=config.INDIAAI_BASE_URL,
            api_key=config.INDIAAI_API_KEY,
            timeout=90.0,
            max_retries=0,  # Traject's existing retry/abstention policy handles failures
        )
        return _ClientProxy(original, asynchronous)

    if not config.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY missing in backend/.env")
    try:
        from groq import Groq, AsyncGroq
    except ImportError as exc:
        raise RuntimeError("Groq SDK missing: pip install groq") from exc
    cls = AsyncGroq if asynchronous else Groq
    return cls(api_key=config.GROQ_API_KEY, timeout=45.0, max_retries=0)


def optional_client():
    return make_client() if is_configured() else None
