# Traject file-by-file audit — 12 October 2026

Baseline: 220 tracked files. **Removed 106 and retained 114**;
added this audit and one generator-regression test. Files below were reviewed against
FastAPI imports, React routes, test imports, signup presets and CLI call paths.

Non-runtime tests, reproducible synthetic datasets and CI remain because they
are necessary for continued correctness and developer onboarding.

| Original file | Decision | Why |
|---|---|---|
| `.github/workflows/ci.yml` | Keep | Required automated CI checks |
| `.gitignore` | Keep | Active setup, architecture, API docs, dependency manifest or safe configuration |
| `DEMO_AND_OPTIMIZATION_GUIDE.md` | Remove | One-off publishing helper or redundant/obsolete document |
| `INDIAAI_SETUP.md` | Keep | Active setup, architecture, API docs, dependency manifest or safe configuration |
| `PUBLISH_TO_GITHUB.ps1` | Remove | One-off publishing helper or redundant/obsolete document |
| `README.md` | Keep | Active setup, architecture, API docs, dependency manifest or safe configuration |
| `REVIEW_AND_RUN.md` | Remove | One-off publishing helper or redundant/obsolete document |
| `backend/.env.example` | Keep | Active setup, architecture, API docs, dependency manifest or safe configuration |
| `backend/.gitignore` | Keep | Active setup, architecture, API docs, dependency manifest or safe configuration |
| `backend/README.md` | Remove | Standalone unused generator, outdated migration/export helper or duplicate document |
| `backend/amazon_raw_export.py` | Remove | Standalone unused generator, outdated migration/export helper or duplicate document |
| `backend/app/accounts.py` | Keep | Reachable FastAPI, data ingestion, model gateway, persistence or trust logic |
| `backend/app/agents/__init__.py` | Keep | Active signal, recommendation, Critic, retention or support-agent dependency |
| `backend/app/agents/clients.py` | Keep | Active signal, recommendation, Critic, retention or support-agent dependency |
| `backend/app/agents/confidence.py` | Keep | Active signal, recommendation, Critic, retention or support-agent dependency |
| `backend/app/agents/critic_agent.py` | Keep | Active signal, recommendation, Critic, retention or support-agent dependency |
| `backend/app/agents/deal_value_agent.py` | Keep | Active signal, recommendation, Critic, retention or support-agent dependency |
| `backend/app/agents/payload.py` | Keep | Active signal, recommendation, Critic, retention or support-agent dependency |
| `backend/app/agents/pitch.py` | Keep | Active signal, recommendation, Critic, retention or support-agent dependency |
| `backend/app/agents/recommendation_agent.py` | Keep | Active signal, recommendation, Critic, retention or support-agent dependency |
| `backend/app/agents/retention_agent.py` | Keep | Active signal, recommendation, Critic, retention or support-agent dependency |
| `backend/app/agents/retrieval_agent.py` | Remove | Inactive legacy pipeline, scheduler, or AI retrieval agent |
| `backend/app/agents/signal_agent.py` | Keep | Active signal, recommendation, Critic, retention or support-agent dependency |
| `backend/app/agents/workflow.py` | Keep | Active signal, recommendation, Critic, retention or support-agent dependency |
| `backend/app/auth.py` | Keep | Reachable FastAPI, data ingestion, model gateway, persistence or trust logic |
| `backend/app/calibration.py` | Keep | Reachable FastAPI, data ingestion, model gateway, persistence or trust logic |
| `backend/app/chat_agent.py` | Keep | Reachable FastAPI, data ingestion, model gateway, persistence or trust logic |
| `backend/app/citation.py` | Keep | Reachable FastAPI, data ingestion, model gateway, persistence or trust logic |
| `backend/app/config.py` | Keep | Reachable FastAPI, data ingestion, model gateway, persistence or trust logic |
| `backend/app/data_ingestion.py` | Keep | Reachable FastAPI, data ingestion, model gateway, persistence or trust logic |
| `backend/app/db.py` | Keep | Reachable FastAPI, data ingestion, model gateway, persistence or trust logic |
| `backend/app/domain_detector.py` | Remove | Inactive legacy pipeline, scheduler, or AI retrieval agent |
| `backend/app/dynamic_context.py` | Keep | Reachable FastAPI, data ingestion, model gateway, persistence or trust logic |
| `backend/app/ecommerce_ingestion.py` | Remove | Inactive legacy pipeline, scheduler, or AI retrieval agent |
| `backend/app/email_service.py` | Keep | Reachable FastAPI, data ingestion, model gateway, persistence or trust logic |
| `backend/app/indiaai_client.py` | Keep | Reachable FastAPI, data ingestion, model gateway, persistence or trust logic |
| `backend/app/insight_llm.py` | Keep | Reachable FastAPI, data ingestion, model gateway, persistence or trust logic |
| `backend/app/insights.py` | Keep | Reachable FastAPI, data ingestion, model gateway, persistence or trust logic |
| `backend/app/llm_retry.py` | Keep | Reachable FastAPI, data ingestion, model gateway, persistence or trust logic |
| `backend/app/logging_config.py` | Keep | Reachable FastAPI, data ingestion, model gateway, persistence or trust logic |
| `backend/app/main.py` | Keep | Reachable FastAPI, data ingestion, model gateway, persistence or trust logic |
| `backend/app/meeting_service.py` | Keep | Reachable FastAPI, data ingestion, model gateway, persistence or trust logic |
| `backend/app/models.py` | Keep | Reachable FastAPI, data ingestion, model gateway, persistence or trust logic |
| `backend/app/onboarding.py` | Keep | Reachable FastAPI, data ingestion, model gateway, persistence or trust logic |
| `backend/app/pipeline.py` | Keep | Reachable FastAPI, data ingestion, model gateway, persistence or trust logic |
| `backend/app/prefilter.py` | Keep | Reachable FastAPI, data ingestion, model gateway, persistence or trust logic |
| `backend/app/product_graph.py` | Remove | Inactive legacy pipeline, scheduler, or AI retrieval agent |
| `backend/app/prompt_architect.py` | Keep | Reachable FastAPI, data ingestion, model gateway, persistence or trust logic |
| `backend/app/prompts.py` | Keep | Reachable FastAPI, data ingestion, model gateway, persistence or trust logic |
| `backend/app/rule_engine.py` | Keep | Reachable FastAPI, data ingestion, model gateway, persistence or trust logic |
| `backend/app/scheduler.py` | Remove | Inactive legacy pipeline, scheduler, or AI retrieval agent |
| `backend/app/schema_discovery.py` | Keep | Reachable FastAPI, data ingestion, model gateway, persistence or trust logic |
| `backend/app/schema_mapping.py` | Keep | Reachable FastAPI, data ingestion, model gateway, persistence or trust logic |
| `backend/app/schema_self_correction.py` | Keep | Reachable FastAPI, data ingestion, model gateway, persistence or trust logic |
| `backend/app/trust.py` | Keep | Reachable FastAPI, data ingestion, model gateway, persistence or trust logic |
| `backend/app/universal_analyzer.py` | Remove | Inactive legacy pipeline, scheduler, or AI retrieval agent |
| `backend/app/universal_pipeline.py` | Remove | Inactive legacy pipeline, scheduler, or AI retrieval agent |
| `backend/app/usage_rollup.py` | Keep | Reachable FastAPI, data ingestion, model gateway, persistence or trust logic |
| `backend/app/vector_engine.py` | Keep | Reachable FastAPI, data ingestion, model gateway, persistence or trust logic |
| `backend/app/web_api.py` | Keep | Reachable FastAPI, data ingestion, model gateway, persistence or trust logic |
| `backend/conftest.py` | Keep | Backend regression and decision-safety test |
| `backend/data/generate_amazon_demo.py` | Keep | Data generator used by active signup preset |
| `backend/data/generate_amazon_grocery.py` | Remove | Standalone unused generator, outdated migration/export helper or duplicate document |
| `backend/data/generate_grocery_demo.py` | Remove | Standalone unused generator, outdated migration/export helper or duplicate document |
| `backend/data/generate_industry_demo_csvs.py` | Keep | Data generator used by active signup preset |
| `backend/data/generate_loreal_demo.py` | Remove | Standalone unused generator, outdated migration/export helper or duplicate document |
| `backend/data/generate_sportyzone_demo.py` | Remove | Standalone unused generator, outdated migration/export helper or duplicate document |
| `backend/data/generate_tenant_csvs.py` | Remove | Standalone unused generator, outdated migration/export helper or duplicate document |
| `backend/data/schema.sql` | Keep | Active setup, architecture, API docs, dependency manifest or safe configuration |
| `backend/data/seed_product_catalog.py` | Remove | Standalone unused generator, outdated migration/export helper or duplicate document |
| `backend/data/tenant_uploads/amazon-beauty/product_metadata.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/amazon-beauty/reviews.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/amazon-grocery/grocery_metrics.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/amazon-grocery/grocery_sellers.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/amazon-grocery/product_catalog.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/amazon-grocery/support_tickets.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/amazon/amazon_sellers.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/amazon/product_catalog.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/amazon/seller_metrics.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/amazon/support_tickets.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/brightmart/complaints.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/brightmart/product_catalog.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/brightmart/sales_performance.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/brightmart/store_accounts.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/cultfit-2/customers.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/cultfit-2/product_catalog.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/cultfit-2/support_tickets.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/cultfit-2/usage_metrics.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/cultfit/customers.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/cultfit/product_catalog.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/cultfit/support_tickets.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/cultfit/usage_metrics.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/dec/customers.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/dec/product_catalog.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/dec/support_tickets.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/dec/usage_metrics.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/decathalon/customers.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/decathlon/customers.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/decathlon/product_catalog.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/decathlon/support_tickets.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/decathlon/usage_metrics.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/ironforge-llm/equipment_metrics.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/ironforge-llm/product_catalog.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/ironforge-llm/service_contracts.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/ironforge-llm/service_requests.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/ironforge/equipment_metrics.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/ironforge/product_catalog.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/ironforge/service_contracts.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/ironforge/service_requests.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/loreal/loreal_partners.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/loreal/partner_metrics.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/loreal/product_catalog.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/loreal/support_tickets.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/novasales/accounts.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/novasales/engagement_metrics.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/novasales/product_catalog.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/novasales/support_tickets.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/sportyzone/customers.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/sportyzone/product_catalog.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/sportyzone/support_tickets.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/sportyzone/usage_metrics.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/tata-steel/equipment_metrics.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/tata-steel/product_catalog.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/tata-steel/service_contracts.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/tata-steel/service_requests.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/techflow/product_catalog.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/techflow/product_usage.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/techflow/subscriptions.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/techflow/support_issues.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/traject-demo/product_catalog.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/traject-demo/product_usage.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/traject-demo/subscriptions.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/traject-demo/support_issues.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/traject-showcase/product_catalog.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/traject-showcase/product_usage.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/traject-showcase/subscriptions.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/data/tenant_uploads/traject-showcase/support_issues.csv` | Remove | Pre-generated tenant CSV; generated by signup; curated source data retained in demo_data |
| `backend/docs/er_diagram.md` | Remove | Standalone unused generator, outdated migration/export helper or duplicate document |
| `backend/pytest.ini` | Keep | Backend regression and decision-safety test |
| `backend/requirements-core.txt` | Keep | Active setup, architecture, API docs, dependency manifest or safe configuration |
| `backend/requirements-optional.txt` | Keep | Active setup, architecture, API docs, dependency manifest or safe configuration |
| `backend/requirements.txt` | Keep | Active setup, architecture, API docs, dependency manifest or safe configuration |
| `backend/scripts/generate_dynamic_fields_report.py` | Remove | Standalone unused generator, outdated migration/export helper or duplicate document |
| `backend/scripts/generate_trust_demo.py` | Keep | Required tenant ingest, showcase generation, smoke or gateway diagnostics |
| `backend/scripts/manage_tenants.py` | Remove | Standalone unused generator, outdated migration/export helper or duplicate document |
| `backend/scripts/migrate_to_schema_free.py` | Remove | Standalone unused generator, outdated migration/export helper or duplicate document |
| `backend/scripts/run_tenant_ingestion.py` | Keep | Required tenant ingest, showcase generation, smoke or gateway diagnostics |
| `backend/scripts/smoke_optimized_demo.py` | Keep | Required tenant ingest, showcase generation, smoke or gateway diagnostics |
| `backend/scripts/test_indiaai_connection.py` | Keep | Required tenant ingest, showcase generation, smoke or gateway diagnostics |
| `backend/test.py` | Remove | Standalone unused generator, outdated migration/export helper or duplicate document |
| `backend/tests/test_agents/conftest.py` | Keep | Backend regression and decision-safety test |
| `backend/tests/test_agents/golden_set.json` | Keep | Backend regression and decision-safety test |
| `backend/tests/test_agents/test_clients.py` | Keep | Backend regression and decision-safety test |
| `backend/tests/test_agents/test_critic_agent.py` | Keep | Backend regression and decision-safety test |
| `backend/tests/test_agents/test_recommendation_agent.py` | Keep | Backend regression and decision-safety test |
| `backend/tests/test_agents/test_retention_agent.py` | Keep | Backend regression and decision-safety test |
| `backend/tests/test_agents/test_signal_agent.py` | Keep | Backend regression and decision-safety test |
| `backend/tests/test_client_pool.py` | Keep | Backend regression and decision-safety test |
| `backend/tests/test_indiaai_provider.py` | Keep | Backend regression and decision-safety test |
| `backend/tests/test_lifespan.py` | Keep | Backend regression and decision-safety test |
| `backend/tests/test_prefilter.py` | Keep | Backend regression and decision-safety test |
| `backend/tests/test_regression_rule_based.py` | Keep | Backend regression and decision-safety test |
| `backend/tests/test_tenant_isolation.py` | Keep | Backend regression and decision-safety test |
| `backend/tests/test_traject_demo_onboarding.py` | Keep | Backend regression and decision-safety test |
| `backend/tests/test_trust_gates.py` | Keep | Backend regression and decision-safety test |
| `demo_data/benchmark_36_accounts/product_catalog.csv` | Keep | Curated synthetic input/benchmark or reviewer labels (never upload reviewer labels) |
| `demo_data/benchmark_36_accounts/product_usage.csv` | Keep | Curated synthetic input/benchmark or reviewer labels (never upload reviewer labels) |
| `demo_data/benchmark_36_accounts/reviewer_labels_DO_NOT_UPLOAD.csv` | Keep | Curated synthetic input/benchmark or reviewer labels (never upload reviewer labels) |
| `demo_data/benchmark_36_accounts/subscriptions.csv` | Keep | Curated synthetic input/benchmark or reviewer labels (never upload reviewer labels) |
| `demo_data/benchmark_36_accounts/support_issues.csv` | Keep | Curated synthetic input/benchmark or reviewer labels (never upload reviewer labels) |
| `demo_data/showcase_12_accounts/product_catalog.csv` | Keep | Curated synthetic input/benchmark or reviewer labels (never upload reviewer labels) |
| `demo_data/showcase_12_accounts/product_usage.csv` | Keep | Curated synthetic input/benchmark or reviewer labels (never upload reviewer labels) |
| `demo_data/showcase_12_accounts/reviewer_labels_DO_NOT_UPLOAD.csv` | Keep | Curated synthetic input/benchmark or reviewer labels (never upload reviewer labels) |
| `demo_data/showcase_12_accounts/subscriptions.csv` | Keep | Curated synthetic input/benchmark or reviewer labels (never upload reviewer labels) |
| `demo_data/showcase_12_accounts/support_issues.csv` | Keep | Curated synthetic input/benchmark or reviewer labels (never upload reviewer labels) |
| `docs/PRD.md` | Remove | One-off publishing helper or redundant/obsolete document |
| `docs/api_reference.md` | Keep | Active setup, architecture, API docs, dependency manifest or safe configuration |
| `docs/architecture.md` | Keep | Active setup, architecture, API docs, dependency manifest or safe configuration |
| `docs/churn_scoring_logic.md` | Keep | Active setup, architecture, API docs, dependency manifest or safe configuration |
| `docs/legacy/original_upsell_agent_claude_code_prompt.md` | Remove | One-off publishing helper or redundant/obsolete document |
| `docs/legacy/original_upsell_agent_project_structure.md` | Remove | One-off publishing helper or redundant/obsolete document |
| `docs/project_structure.md` | Remove | One-off publishing helper or redundant/obsolete document |
| `frontend/index.html` | Keep | Frontend source, API layer, style, manifest or build asset |
| `frontend/package-lock.json` | Keep | Frontend source, API layer, style, manifest or build asset |
| `frontend/package.json` | Keep | Frontend source, API layer, style, manifest or build asset |
| `frontend/postcss.config.js` | Keep | Frontend source, API layer, style, manifest or build asset |
| `frontend/public/favicon.svg` | Keep | Frontend source, API layer, style, manifest or build asset |
| `frontend/src/App.jsx` | Keep | Frontend source, API layer, style, manifest or build asset |
| `frontend/src/api/client.js` | Keep | Frontend source, API layer, style, manifest or build asset |
| `frontend/src/api/tenantSession.js` | Keep | Frontend source, API layer, style, manifest or build asset |
| `frontend/src/components/BandwidthPanel.jsx` | Remove | Unreachable from active React router and component import graph |
| `frontend/src/components/BrandMark.jsx` | Keep | Reachable React component |
| `frontend/src/components/ChurnBadge.jsx` | Remove | Unreachable from active React router and component import graph |
| `frontend/src/components/ChurnDistributionChart.jsx` | Remove | Unreachable from active React router and component import graph |
| `frontend/src/components/ConfidenceBreakdown.jsx` | Remove | Unreachable from active React router and component import graph |
| `frontend/src/components/InsightCard.jsx` | Keep | Reachable React component |
| `frontend/src/components/MeetingScheduler.jsx` | Keep | Reachable React component |
| `frontend/src/components/Navbar.jsx` | Remove | Unreachable from active React router and component import graph |
| `frontend/src/components/RecommendationCard.jsx` | Remove | Unreachable from active React router and component import graph |
| `frontend/src/components/RevenueChart.jsx` | Remove | Unreachable from active React router and component import graph |
| `frontend/src/components/Sidebar.jsx` | Keep | Reachable React component |
| `frontend/src/components/TenantLogin.jsx` | Keep | Reachable React component |
| `frontend/src/components/TenantSignup.jsx` | Keep | Reachable React component |
| `frontend/src/components/Topbar.jsx` | Keep | Reachable React component |
| `frontend/src/components/TrajectAuthLayout.jsx` | Keep | Reachable React component |
| `frontend/src/components/UpsellCatalog.jsx` | Remove | Unreachable from active React router and component import graph |
| `frontend/src/context/AppDataContext.jsx` | Keep | Frontend source, API layer, style, manifest or build asset |
| `frontend/src/main.jsx` | Keep | Frontend source, API layer, style, manifest or build asset |
| `frontend/src/pages/ChatAgent.jsx` | Keep | Reachable React route |
| `frontend/src/pages/CustomerDetail.jsx` | Keep | Reachable React route |
| `frontend/src/pages/CustomerList.jsx` | Keep | Reachable React route |
| `frontend/src/pages/Dashboard.jsx` | Keep | Reachable React route |
| `frontend/src/pages/DatasetAnalysis.jsx` | Remove | Unreachable from active React router and component import graph |
| `frontend/src/pages/RecommendationsTracking.jsx` | Remove | Unreachable from active React router and component import graph |
| `frontend/src/pages/Settings.jsx` | Keep | Reachable React route |
| `frontend/src/pages/Tracking.jsx` | Remove | Unreachable from active React router and component import graph |
| `frontend/src/styles/index.css` | Keep | Frontend source, API layer, style, manifest or build asset |
| `frontend/src/utils/bandwidthUtils.js` | Remove | Unreachable from active React router and component import graph |
| `frontend/tailwind.config.js` | Keep | Frontend source, API layer, style, manifest or build asset |
| `frontend/vite.config.js` | Keep | Frontend source, API layer, style, manifest or build asset |
