"""Server-side price computation — the only place money is decided.

Order of operations: list price -> standing sale -> promo code -> GST.
Discounts reduce the taxable value and GST is charged on what the customer
actually pays, which matches Indian GST treatment of an on-invoice discount.

A promo applies to the SALE price, not the list price. Stacking a code on top
of an already-discounted plan against list can sell below cost.

This file is byte-identical to skill_100_ai_backend/services/pricing.py; the
two services deploy separately and cannot import each other.
tests/test_pricing_mirror.py fails if they drift.
"""
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

MIN_TAXABLE_PAISE = 100  # ₹1 — Razorpay rejects zero-value orders


def _round_paise(value: Decimal) -> int:
    """Half-up, never banker's rounding (Python's round(0.5) == 0)."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _promo_rejection(plan: dict, promo: dict, now: datetime) -> str | None:
    if not promo["active"]:
        return "This code is not active."
    if promo["plan_id"] and promo["plan_id"] != plan["id"]:
        return "This code is not valid for this plan."
    if promo["starts_at"] and promo["starts_at"] > now:
        return "This code is not live yet."
    if promo["expires_at"] and promo["expires_at"] < now:
        return "This code has expired."
    if promo["max_uses"] is not None and promo["used_count"] >= promo["max_uses"]:
        return "This code has been fully redeemed."
    return None


def compute_price(plan: dict, promo: dict | None = None,
                  now: datetime | None = None) -> dict:
    """Full price breakdown in integer paise.

    plan:  id, amount_paise, sale_amount_paise, sale_ends_at, gst_bps
    promo: plan_id, kind ('percent'|'flat'), value, max_uses, used_count,
           starts_at, expires_at, active   (None = no code supplied)

    `value` is a percentage for kind='percent' and PAISE for kind='flat'.
    """
    now = now or datetime.now(timezone.utc)
    list_paise = plan["amount_paise"]
    gst_bps = plan.get("gst_bps", 1800)

    sale = plan.get("sale_amount_paise")
    sale_ends = plan.get("sale_ends_at")
    # An out-of-range sale price is ignored rather than honoured: too high is
    # not a discount, and below the ₹1 floor would put a sub-rupee order in
    # front of Razorpay. Both fall back to the list price.
    sale_active = (
        sale is not None
        and MIN_TAXABLE_PAISE <= sale < list_paise
        and (sale_ends is None or sale_ends > now)
    )
    effective_base = sale if sale_active else list_paise
    if effective_base < MIN_TAXABLE_PAISE:
        raise ValueError(
            f"Plan {plan['id']!r} is priced below the ₹1 floor "
            f"({effective_base} paise); it cannot be sold.")

    promo_ok, promo_reason, discount = False, None, 0
    if promo is not None:
        promo_reason = _promo_rejection(plan, promo, now)
        if promo_reason is None:
            promo_ok = True
            if promo["kind"] == "percent":
                discount = _round_paise(
                    Decimal(effective_base) * Decimal(promo["value"]) / Decimal(100))
            else:
                discount = promo["value"]

    max_discount = max(effective_base - MIN_TAXABLE_PAISE, 0)
    discount_capped = discount > max_discount
    if discount_capped:
        discount = max_discount

    taxable = effective_base - discount
    gst = _round_paise(Decimal(taxable) * Decimal(gst_bps) / Decimal(10_000))

    return {
        "list_paise": list_paise,
        "effective_base_paise": effective_base,
        "sale_active": sale_active,
        "promo_discount_paise": discount,
        "taxable_paise": taxable,
        "gst_paise": gst,
        "total_paise": taxable + gst,
        "promo_ok": promo_ok,
        "promo_reason": promo_reason,
        "discount_capped": discount_capped,
    }
