"""Turning a paid order into rows of access.

Access truth is users.active_products — a JSONB array of items. A bundle grants
several products from one payment, so the amount paid is apportioned across
them; the remainder goes to the first item so the parts always reconcile
against neet_orders, which stays the financial record of truth.

`source` is the idempotency marker. Razorpay retries webhooks, and without it a
retry appends a second copy of every product.
"""
from decimal import ROUND_HALF_UP, Decimal

# NEET buyers live in the single existing tenant/school of the legacy users table.
NEET_TENANT_ID = "9769b4ab-351c-47e7-ae3e-c18790424d0d"
NEET_SCHOOL_ID = "b2af8e86-7363-4963-927a-8a58f7e7ddad"


def _rupees(paise: int) -> str:
    return str((Decimal(paise) / Decimal(100)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP))


def build_grant_items(plan: dict, order: dict, payment_id: str,
                      paid_total_paise: int,
                      payment_type: str = "razorpay") -> list[dict]:
    """One item per product key in the plan, apportioning what was paid."""
    products = list(plan["grants"])
    n = len(products)
    share, remainder = divmod(paid_total_paise, n)
    purchase_date = str(order.get("created_at", ""))[:10]
    expiration = str(plan["access_until"])[:10] if plan.get("access_until") else None

    items = []
    for i, product in enumerate(products):
        amount = share + (remainder if i == 0 else 0)
        items.append({
            "product_name": product,
            "purchase_date": purchase_date,
            "expiration_date": expiration,
            "payment_type": payment_type,
            "payment_amount": _rupees(amount),
            "order_id": str(order["id"]),
            "source": (f"razorpay:{payment_id}" if payment_type == "razorpay"
                       else f"{payment_type}:{payment_id}"),
            "revoked_at": None,
        })
    return items
