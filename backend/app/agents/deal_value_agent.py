from app.models import DealValue

def compute_deal_value(recommendation: dict, customer: dict, catalog: list) -> DealValue:
    product = next((p for p in catalog if p["product_name"] == recommendation.get("recommended_product")), None)
    if not product or not customer.get("seats"):
        return DealValue(estimated_value=0.0, anomaly_flag=True, anomaly_reason="missing product or seats")
    value = round(product["price_per_seat"] * customer["seats"] * 12, 2)
    return DealValue(estimated_value=value, anomaly_flag=False, anomaly_reason=None)