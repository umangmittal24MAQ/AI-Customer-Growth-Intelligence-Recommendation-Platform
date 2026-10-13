"""Showcase signup must not rely on checked-in tenant CSVs."""
from app import accounts


def test_showcase_preset_generates_four_datasets(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "UPLOADS_DIR", str(tmp_path))
    accounts._seed_domain_dataset("audit-traj", "traject-showcase")
    generated = {p.name for p in (tmp_path / "audit-traj").glob("*.csv")}
    assert generated == {"subscriptions.csv", "product_usage.csv",
                         "support_issues.csv", "product_catalog.csv"}
