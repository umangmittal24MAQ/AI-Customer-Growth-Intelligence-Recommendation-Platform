"""Bounded retries for IndiaAI gateway rate limits and transient failures."""
import asyncio
import re
from app.logging_config import get_logger
log = get_logger(__name__)


def retry_after_seconds(error, attempt: int) -> float:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", {}) or {}
    header = headers.get("retry-after") or headers.get("Retry-After")
    if header:
        try:
            return min(max(float(header), 1.0), 65.0)
        except (TypeError, ValueError):
            pass
    match = re.search(r"try again in\s+(\d+(?:\.\d+)?)s", str(error), flags=re.I)
    if match:
        return min(max(float(match.group(1)) + 1.0, 1.0), 65.0)
    return min(5 * 2**attempt, 45)


async def completion_with_retry(client, **kwargs):
    for attempt in range(3):
        try:
            return await client.chat.completions.create(**kwargs)
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            if status not in (429, 502, 503, 504) or attempt == 2:
                raise
            delay = retry_after_seconds(exc, attempt)
            log.warning("IndiaAI HTTP %s; retrying in %.1fs (%d/2).", status, delay, attempt+1)
            await asyncio.sleep(delay)
