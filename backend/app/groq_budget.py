"""Cooperative rolling quota guard for Traject's Groq structured agents.

Limits are conservative knobs, not provider guarantees. Other clients and
schema discovery may consume the same organization's quota. Provider 429s are
retried only with bounded Retry-After-aware delays; failed calls abstain.
"""
import asyncio
from collections import deque
import os
import re
import time

from app.logging_config import get_logger
from app.config import LLM_PROVIDER

log = get_logger(__name__)
_state = None


def _state_for_running_loop():
    global _state
    loop = asyncio.get_running_loop()
    if _state is None or _state[0] is not loop:
        _state = (loop, asyncio.Lock(), deque())
    return _state


async def reserve(input_tokens: int, output_tokens: int):
    if LLM_PROVIDER != 'groq' or os.getenv('GROQ_BUDGET_ENABLED', '1') == '0':
        return
    rpm = max(1, int(os.getenv('GROQ_REQUESTS_PER_MINUTE', '15')))
    input_limit = max(100, int(os.getenv('GROQ_INPUT_TOKENS_PER_MINUTE', '6500')))
    output_limit = max(100, int(os.getenv('GROQ_OUTPUT_TOKENS_PER_MINUTE', '900')))
    _, lock, history = _state_for_running_loop()
    input_tokens = min(input_limit, input_tokens)
    output_tokens = min(output_limit, output_tokens)
    while True:
        async with lock:
            now = time.monotonic()
            while history and now - history[0][0] >= 60:
                history.popleft()
            input_used = sum(v[1] for v in history)
            output_used = sum(v[2] for v in history)
            if (len(history) < rpm and input_used + input_tokens <= input_limit
                    and output_used + output_tokens <= output_limit):
                history.append((now, input_tokens, output_tokens))
                return
            delay = max(0.25, 60 - (now - history[0][0])) if history else 1
        log.info('Groq local token budget reached; scheduling next request in %.1fs.', delay)
        await asyncio.sleep(delay)


def retry_after_seconds(error, attempt: int) -> float:
    response = getattr(error, 'response', None)
    headers = getattr(response, 'headers', {}) or {}
    header = headers.get('retry-after') or headers.get('Retry-After')
    if header:
        try:
            return min(max(float(header), 1.0), 65.0)
        except (TypeError, ValueError):
            pass
    message = str(error)
    match = re.search(r'try again in\s+(\d+(?:\.\d+)?)s', message, flags=re.I)
    if match:
        return min(max(float(match.group(1)) + 1.0, 1.0), 65.0)
    return min(5 * 2**attempt, 45)


async def completion_with_budget(client, **kwargs):
    content = ''.join(str(m.get('content', '')) for m in kwargs.get('messages', []))
    estimated_input = int(len(content) / 3.7) + 75
    reserved_output = max(100, int(os.getenv('GROQ_OUTPUT_TOKEN_RESERVATION', '250')))
    for attempt in range(3):
        await reserve(estimated_input, reserved_output)
        try:
            return await client.chat.completions.create(**kwargs)
        except Exception as exc:
            status = getattr(exc, 'status_code', None)
            if status != 429 or attempt == 2:
                raise
            delay = retry_after_seconds(exc, attempt)
            log.warning('%s 429; waiting %.1fs before retry %d/2.', LLM_PROVIDER, delay, attempt + 1)
            await asyncio.sleep(delay)
