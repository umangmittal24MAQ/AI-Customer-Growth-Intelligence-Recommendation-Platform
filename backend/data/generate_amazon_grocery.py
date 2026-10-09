import os
import random
from faker import Faker
import pandas as pd

fake = Faker()

NUM_SELLERS = 500
NUM_PRODUCTS = 300
NUM_ORDERS = 5000
NUM_TICKETS = 1500

os.makedirs("amazon", exist_ok=True)

# --------------------------
# Product Catalog
# --------------------------

categories = {
    "Grocery": ["Rice", "Flour", "Sugar", "Oil", "Salt"],
    "Beverages": ["Coffee", "Tea", "Juice", "Soft Drink"],
    "Snacks": ["Chips", "Cookies", "Chocolate", "Nuts"],
    "Household": ["Detergent", "Cleaner", "Tissue", "Soap"],
    "Personal Care": ["Shampoo", "Face Wash", "Toothpaste", "Body Wash"],
    "Baby": ["Diapers", "Baby Wipes", "Formula"],
    "Pet": ["Dog Food", "Cat Food", "Pet Treats"],
    "Frozen": ["Pizza", "Ice Cream", "Nuggets"],
}

plans = ["Starter", "Professional", "Enterprise"]

products = []

for i in range(NUM_PRODUCTS):

    cat = random.choice(list(categories.keys()))
    name = random.choice(categories[cat])

    products.append({
        "product_id": f"P{i+1:04}",
        "product_name": f"{name} Premium",
        "category": cat,
        "brand": random.choice(["Amazon Fresh","Whole Foods","Nestle","Kellogg","Pepsi","Coca Cola"]),
        "price": round(random.uniform(5,200),2),
        "cost_price": round(random.uniform(2,100),2),
        "rating": round(random.uniform(3.5,5),1),
        "stock": random.randint(20,1000),
        "subscription": random.choice(["Yes","No"]),
        "min_plan": random.choice(plans),
        "min_monthly_revenue": random.randint(1000,50000),
        "min_order_frequency": random.randint(2,30),
        "description": fake.sentence()
    })

product_df = pd.DataFrame(products)
product_df.to_csv("amazon/product_catalog.csv",index=False)

# --------------------------
# Sellers
# --------------------------

seller_rows=[]

for i in range(NUM_SELLERS):

    revenue=random.randint(3000,80000)
    orders=random.randint(20,1000)

    seller_rows.append({
        "seller_id":f"SELL{i+1:04}",
        "seller_name":fake.name(),
        "business_name":fake.company(),
        "email":fake.email(),
        "phone":fake.phone_number(),
        "country":"USA",
        "city":fake.city(),
        "category":random.choice(list(categories.keys())),
        "plan":random.choice(plans),
        "join_date":fake.date_between("-5y","today"),
        "monthly_revenue":revenue,
        "monthly_orders":orders,
        "avg_order_value":round(revenue/orders,2),
        "seller_rating":round(random.uniform(3.5,5),1),
        "account_manager":fake.name()
    })

seller_df=pd.DataFrame(seller_rows)
seller_df.to_csv("amazon/amazon_sellers.csv",index=False)

# --------------------------
# Metrics
# --------------------------

metric_rows=[]

for seller in seller_rows:

    churn=round(random.uniform(0.05,0.9),2)

    metric_rows.append({
        "seller_id":seller["seller_id"],
        "feature_adoption_pct":random.randint(20,100),
        "monthly_active_buyers":random.randint(100,5000),
        "repeat_customer_pct":random.randint(20,90),
        "order_growth_pct":random.randint(-30,40),
        "avg_order_value":seller["avg_order_value"],
        "cart_abandonment_pct":random.randint(5,40),
        "return_rate_pct":random.randint(1,15),
        "delivery_success_pct":random.randint(80,100),
        "customer_rating":round(random.uniform(3.5,5),1),
        "support_score":random.randint(50,100),
        "predicted_churn":churn,
        "bandwidth_utilization_pct":random.randint(20,95),
        "revenue_opportunity":random.randint(100,10000),
        "confidence_score":random.randint(70,99),
        "last_updated":fake.date_this_year()
    })

metric_df=pd.DataFrame(metric_rows)
metric_df.to_csv("amazon/seller_metrics.csv",index=False)

# --------------------------
# Support Tickets
# --------------------------

ticket_rows=[]

for i in range(NUM_TICKETS):

    seller=random.choice(seller_rows)

    created=fake.date_between("-1y","today")

    ticket_rows.append({
        "ticket_id":f"TKT{i+1:05}",
        "seller_id":seller["seller_id"],
        "ticket_type":random.choice([
            "Inventory",
            "Delivery",
            "Payment",
            "Return",
            "Product Issue",
            "Account"
        ]),
        "priority":random.choice(["Low","Medium","High"]),
        "status":random.choice(["Open","Resolved","Closed"]),
        "created_date":created,
        "resolved_date":fake.date_between(created,"today"),
        "resolution_time_hours":random.randint(2,120),
        "sentiment":random.choice(["Positive","Neutral","Negative"])
    })

ticket_df=pd.DataFrame(ticket_rows)
ticket_df.to_csv("amazon/support_tickets.csv",index=False)

# --------------------------
# Orders
# --------------------------

orders=[]

for i in range(NUM_ORDERS):

    seller=random.choice(seller_rows)

    orders.append({
        "order_id":f"ORD{i+1:06}",
        "seller_id":seller["seller_id"],
        "customer_id":f"CUST{random.randint(1,5000):05}",
        "order_date":fake.date_between("-2y","today"),
        "order_status":random.choice(["Completed","Delivered","Cancelled"]),
        "payment_method":random.choice(["Card","UPI","NetBanking","Wallet"]),
        "delivery_status":random.choice(["Delivered","In Transit","Cancelled"]),
        "total_items":random.randint(1,10),
        "order_value":round(random.uniform(20,500),2),
        "discount":round(random.uniform(0,40),2)
    })

orders_df=pd.DataFrame(orders)
orders_df.to_csv("amazon/orders.csv",index=False)

# --------------------------
# Order Items
# --------------------------

items=[]

count=1

for order in orders:

    for _ in range(random.randint(1,5)):

        product=random.choice(products)

        qty=random.randint(1,5)

        items.append({
            "order_item_id":f"OI{count:07}",
            "order_id":order["order_id"],
            "product_id":product["product_id"],
            "quantity":qty,
            "unit_price":product["price"],
            "total_price":round(product["price"]*qty,2)
        })

        count+=1

items_df=pd.DataFrame(items)
items_df.to_csv("amazon/order_items.csv",index=False)

print("✅ Dataset Generated Successfully!")
print("amazon/")
print("├── amazon_sellers.csv")
print("├── product_catalog.csv")
print("├── seller_metrics.csv")
print("├── support_tickets.csv")
print("├── orders.csv")
print("└── order_items.csv")