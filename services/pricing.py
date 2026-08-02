"""Server-side price computation. Mirrors backend2's
app/modules/neet/pricing.py — the client NEVER supplies an amount; the
frontend's promo preview is cosmetic and this recomputation is what gets
charged."""
from datetime import datetime, timezone


def compute_discount(plan, promo):
    """plan/promo are dict rows. Returns (final_paise, discount_paise, error)."""
    amount = plan["amount_paise"]
    if promo is None:
        return amount, 0, None

    now = datetime.now(timezone.utc)
    if not promo["active"]:
        return amount, 0, "This code is not active."
    if promo["plan_id"] and promo["plan_id"] != plan["id"]:
        return amount, 0, "This code is not valid for this plan."
    if promo["starts_at"] and promo["starts_at"] > now:
        return amount, 0, "This code is not live yet."
    if promo["expires_at"] and promo["expires_at"] < now:
        return amount, 0, "This code has expired."
    if promo["max_uses"] is not None and promo["used_count"] >= promo["max_uses"]:
        return amount, 0, "This code has been fully redeemed."

    if promo["kind"] == "percent":
        discount = amount * promo["value"] // 100
    else:
        discount = min(promo["value"], amount - 100)  # never below ₹1
    return amount - discount, discount, None
