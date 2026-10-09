# Traject — Demo and trust safeguards

* `backend/`: FastAPI, IndiaAI Qwen agent workflow, tenant-isolated SQLite, CSV ingestion, catalog eligibility, critic-veto enforcement.
* `frontend/`: React revenue dashboard.
* `demo_data/showcase_12_accounts/`: synthetic 12-account showcase including negative controls.
* `demo_data/benchmark_36_accounts/`: 36-account synthetic labeled benchmark.

Use the setup in `README.md`. First analyze a single eligible case (Northstar Data Labs), then compare at-risk cases such as Vela Infrastructure. The expected behavior for risky/unsupported products is **no recommendation**, not an arbitrary alternative. Reviewer labels are ground truth for evaluating model behavior and should not be ingested as customer data.

The live IndiaAI model is an externally hosted service; API latency and compatibility must be validated in your authorized environment.
