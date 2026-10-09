# Traject — Revenue Intelligence with Independent AI Critic

Traject ingests customer/subscription/usage/support datasets, identifies compatible product opportunities, verifies model-generated recommendations with an independent critic, and **abstains** when evidence is insufficient. Tenant isolation and a React revenue dashboard are included.

**Single LLM provider:** MAQ-hosted IndiaAI Qwen (`qwen-3.8-27b`) through the OpenAI-compatible Python SDK. No alternative cloud model integration is required. Using the private MAQ gateway requires appropriate authorization and synthetic/demo data.

## Local Windows setup

From `backend/` in PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-core.txt
Copy-Item .env.example .env
notepad .env
python scripts/test_indiaai_connection.py
python -m uvicorn app.main:app --host 127.0.0.1 --port 5001
```

Set `INDIAAI_API_KEY` in `backend/.env`; **never commit the real key**. Use the `.env.example` defaults for JSON mode and the Qwen thinking toggle unless your gateway requires other settings. In another PowerShell window, from `frontend/`, run `npm ci` and `npm run dev`, then open <http://localhost:5173>.

### Demo

Create a tenant with the **Traject Showcase** preset. It contains 12 synthetic SaaS accounts and product records. The `demo_data` directory includes a separate 36-account benchmark. Analyze Northstar Data Labs first, then test risk and missing-evidence cases. The backend rejects critic-vetoed and unverified sales recommendations.

### Troubleshooting an empty model response

The IndiaAI endpoint may return a populated reasoning field but blank final `content`. The shared agent client logs `finish_reason`, completion token usage, and whether reasoning was present, retries an empty response once with a larger token budget, then **abstains safely** if it still fails. Default `LLM_MAX_OUTPUT_TOKENS=2048`; adjust on your deployment after measuring. The `/api/*` routes remain usable without a model, but no unverified opportunity is approved.

See `INDIAAI_SETUP.md` for more detail. This is a local demo, not a production security audit. Live performance must be benchmarked with an authorized account.

## GitHub and updates

Canonical source: <https://github.com/umangmittal24MAQ/AI-Customer-Growth-Intelligence-Recommendation-Platform> (`main`).

To get the latest code in an existing checkout:

```powershell
git pull origin main
```

For a fresh checkout:

```powershell
git clone https://github.com/umangmittal24MAQ/AI-Customer-Growth-Intelligence-Recommendation-Platform.git
```

Then create `backend/.env` from `.env.example` on your own machine. The project uses **IndiaAI Qwen only** for LLM inference; `openai` is the client SDK for the OpenAI-compatible MAQ gateway, not a second model provider. Never commit private gateway keys, internal data, runtime databases, or company code without permission.
