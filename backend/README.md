# Traject backend

This is the **FastAPI** service for Traject, with SQLite persistence, tenant-scoped APIs, CSV ingestion, and two analysis paths: IndiaAI multi-agent reasoning (when configured) and a deterministic rules-based fallback for local demos.

For an accurate quickstart, prerequisite list, onboarding steps, frontend port mapping and security notes, read **`../README.md`**. The technical audit is **`../REVIEW_AND_RUN.md`**.

```bash
python -m venv .venv
# Activate virtual environment
pip install -r requirements-core.txt
python -m pytest tests -q
python -m uvicorn app.main:app --reload --port 5001
```

API documentation: http://127.0.0.1:5001/docs

Optional IndiaAI, calendar and mail integrations require their own dependencies and credentials. The example environment file `backend/.env.example` contains no real secrets. **Never commit your actual `.env` or database files.**

> The codebase retains a few historical names such as `upsell` in legacy scripts and database migrations; the public-facing app is **Traject**. Legacy technical notes may describe superseded code paths.
