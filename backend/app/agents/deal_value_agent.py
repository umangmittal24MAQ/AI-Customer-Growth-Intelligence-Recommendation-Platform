from app.models import DealValue

def compute_deal_value(recommendation: dict, customer: dict, catalog: list, revenue_model: str = "recurring") -> DealValue:
    product = next((p for p in catalog if p["product_name"] == recommendation.get("recommended_product")), None)
    if not product or not customer.get("seats"):
        return DealValue(estimated_value=0.0, anomaly_flag=True, anomaly_reason="missing product or seats")
    multiplier = 1 if revenue_model == "one_time" else 12
    unit_price = product["price_per_seat"]
    current = next((p for p in catalog if p["product_name"] == customer.get("plan_tier")), None)
    if current and current.get("category") and current.get("category") == product.get("category"):
        unit_price = max(0, unit_price - current["price_per_seat"])
    value = round(unit_price * customer["seats"] * multiplier, 2)
    return DealValue(estimated_value=value, anomaly_flag=False, anomaly_reason=None)
