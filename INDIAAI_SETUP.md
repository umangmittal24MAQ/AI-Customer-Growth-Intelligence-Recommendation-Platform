# IndiaAI-only Traject setup

This version uses the MAQ-hosted IndiaAI Qwen endpoint exclusively. Ensure you have permission to access the gateway.

`backend/.env`:

```dotenv
INDIAAI_API_KEY=your_real_key_here
INDIAAI_BASE_URL=https://YOUR_AUTHORIZED_GATEWAY/v1
INDIAAI_MODEL=qwen-3.8-27b
LLM_MAX_OUTPUT_TOKENS=2048
INDIAAI_JSON_MODE=1
INDIAAI_DISABLE_THINKING=1
INDIAAI_THINKING_PARAM=chat_template_kwargs
INDIAAI_CONCURRENCY=1
```

From `backend/`, run `python -m pip install -r requirements-core.txt` then `python scripts/test_indiaai_connection.py`. The OpenAI SDK appends `/chat/completions` to the `/v1` base URL. After the test shows valid JSON, run `python -m uvicorn app.main:app --host 127.0.0.1 --port 5001` and run the React frontend separately.

**Empty content:** Qwen may return reasoning content with an empty final answer. Agent calls report finish_reason/token usage and retry once with a larger output allowance, then abstain without fabricating a sale. If the gateway rejects the nonstandard thinking option, set `INDIAAI_DISABLE_THINKING=0` and use the larger output limit. An API connection test is not the same as a successful full account-analysis test.
