"""Diagnose an IndiaAI/Qwen chat-completions response (synthetic data only).

No credentials are printed.  A successful HTTP request does not necessarily
contain a usable final response, especially with reasoning-enabled models.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import LLM_PROVIDER, LLM_MODEL
from app.indiaai_client import is_configured, make_client


def main():
    if LLM_PROVIDER != "indiaai":
        raise SystemExit("Set LLM_PROVIDER=indiaai in backend/.env first.")
    if not is_configured():
        raise SystemExit("Missing INDIAAI_API_KEY in backend/.env")
    client = make_client()
    started = time.perf_counter()
    max_tokens = int(os.getenv("INDIAAI_TEST_MAX_TOKENS", "1024"))
    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            temperature=0,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Return one short valid JSON object with approved (boolean) and reason (string). No markdown."},
                {"role": "user", "content": "Synthetic test: rising product usage and a compatible upgrade. Is this a candidate for an upsell review?"},
            ],
        )
        latency = time.perf_counter() - started
        if not getattr(response, "choices", None):
            raise SystemExit("Gateway returned no choices. Inspect gateway logs / response schema.")
        choice = response.choices[0]
        message = choice.message
        content = message.content or ""
        reasoning = getattr(message, "reasoning_content", None)
        if reasoning is None:
            reasoning = (getattr(message, "model_extra", None) or {}).get("reasoning_content")
        usage = getattr(response, "usage", None)
        print(f"Provider: {LLM_PROVIDER} | Model: {LLM_MODEL} | Latency: {latency:.2f}s")
        print(f"Finish reason: {choice.finish_reason!r}")
        print(f"Requested max_tokens: {max_tokens}")
        print(f"Output characters: {len(content)} | Reasoning field present: {bool(reasoning)}")
        if usage:
            print("Token usage:", {k: getattr(usage, k, None) for k in ("prompt_tokens", "completion_tokens", "total_tokens")})
        print("Raw content:", content[:1200] if content else "<EMPTY>")
        if not content.strip():
            if choice.finish_reason == "length":
                print("DIAGNOSIS: Output limit reached before a final answer. Try INDIAAI_DISABLE_THINKING=1 and/or a higher output cap.")
            elif reasoning:
                print("DIAGNOSIS: Gateway returned reasoning but no final content. Try INDIAAI_DISABLE_THINKING=1.")
            else:
                print("DIAGNOSIS: Gateway returned empty final content. Check provider response handling; try JSON mode off.")
            raise SystemExit(1)
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            print(f"Not valid JSON: {exc}. Try INDIAAI_JSON_MODE=0 if the gateway has JSON-format issues.")
            raise SystemExit(1)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("approved"), bool) or not isinstance(parsed.get("reason"), str):
            raise SystemExit("Valid JSON, but missing required 'approved' boolean or 'reason' string.")
        print("PASS: structured AI response returned")
    finally:
        client.close()


if __name__ == "__main__":
    main()
