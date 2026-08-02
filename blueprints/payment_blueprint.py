"""Razorpay payment flow, hardened:

- create-order: requires a Supabase JWT; the price comes from neet_plans (+
  optional promo), never from the client.
- verify: checks Razorpay's payment signature, marks the order paid and grants
  the entitlement (fast path for UX).
- webhook: signature-checked payment.captured handler — the authoritative,
  idempotent path (browsers close mid-checkout; Razorpay retries webhooks).
"""
import os

import razorpay
from flask import Blueprint, request, jsonify, g

from services.get_kolkata_timestamp import get_kolkata_timestamp
from services.supabase_auth import require_supabase_user
from services.pricing import compute_discount
from services import db

payment_bp = Blueprint("payment", __name__)
client = razorpay.Client(auth=(os.getenv("RAZORPAY_KEY_ID"), os.getenv("RAZORPAY_KEY_SECRET")))
client.set_app_details({"title": "Skill 100 AI", "version": "1.0.0"})


@payment_bp.route("/create-order", methods=["POST"])
@require_supabase_user
def create_order():
    data = request.get_json(silent=True) or {}
    plan_id = data.get("plan_id")
    promo_code = (data.get("promo_code") or "").strip().upper() or None
    if not plan_id:
        return jsonify({"error": "plan_id is required"}), 400

    plan = db.fetch_one(
        "select id, title, amount_paise, grants from neet_plans where id = %s and active",
        (plan_id,),
    )
    if not plan:
        return jsonify({"error": "Plan not found"}), 404

    promo = None
    if promo_code:
        promo = db.fetch_one("select * from neet_promo_codes where code = %s", (promo_code,))
        if promo is None:
            return jsonify({"error": "Invalid promo code"}), 400

    final_paise, discount_paise, promo_err = compute_discount(plan, promo)
    if promo_err:
        return jsonify({"error": promo_err}), 400

    order = client.order.create(data={
        "amount": final_paise,
        "currency": "INR",
        "notes": {
            "user_id": g.user_id,
            "plan_id": plan["id"],
            "promo_code": promo_code or "",
            "purchase_initiated_at": get_kolkata_timestamp(),
        },
    })

    db.execute(
        "insert into neet_orders (user_id, plan_id, amount_paise, list_amount_paise, "
        "promo_code, discount_paise, razorpay_order_id) "
        "values (%s, %s, %s, %s, %s, %s, %s)",
        (g.user_id, plan["id"], final_paise, plan["amount_paise"],
         promo_code, discount_paise, order["id"]),
    )

    return jsonify({
        "order_id": order["id"],
        "amount": final_paise,
        "currency": "INR",
        "key_id": os.getenv("RAZORPAY_KEY_ID"),
        "plan_title": plan["title"],
    })


def _grant(order):
    """Mark an order paid and grant its entitlement. Idempotent: the status
    guard stops double promo counting; the unique constraint stops double
    entitlements."""
    updated = db.execute(
        "update neet_orders set status = 'paid', paid_at = now(), razorpay_payment_id = %s "
        "where razorpay_order_id = %s and status <> 'paid' returning id, user_id, plan_id, promo_code",
        (order["payment_id"], order["order_id"]),
    )
    if not updated:
        return  # already processed (verify + webhook both land here)

    plan = db.fetch_one("select grants from neet_plans where id = %s", (updated["plan_id"],))
    db.execute(
        "insert into neet_entitlements (user_id, product, source) values (%s, %s, %s) "
        "on conflict (user_id, product, source) do nothing",
        (updated["user_id"], plan["grants"], f"razorpay:{order['payment_id']}"),
    )
    if updated["promo_code"]:
        db.execute(
            "update neet_promo_codes set used_count = used_count + 1 where code = %s",
            (updated["promo_code"],),
        )


@payment_bp.route("/verify", methods=["POST"])
@require_supabase_user
def verify_payment():
    data = request.get_json(silent=True) or {}
    required = ("razorpay_order_id", "razorpay_payment_id", "razorpay_signature")
    if any(k not in data for k in required):
        return jsonify({"error": "Missing payment verification fields"}), 400

    order = db.fetch_one(
        "select user_id, status from neet_orders where razorpay_order_id = %s",
        (data["razorpay_order_id"],),
    )
    if not order or str(order["user_id"]) != g.user_id:
        return jsonify({"error": "Order not found"}), 404

    try:
        client.utility.verify_payment_signature({
            "razorpay_order_id": data["razorpay_order_id"],
            "razorpay_payment_id": data["razorpay_payment_id"],
            "razorpay_signature": data["razorpay_signature"],
        })
    except razorpay.errors.SignatureVerificationError:
        return jsonify({"error": "Payment verification failed"}), 400

    _grant({"order_id": data["razorpay_order_id"], "payment_id": data["razorpay_payment_id"]})
    return jsonify({"status": "paid"})


@payment_bp.route("/webhook", methods=["POST"])
def webhook():
    secret = os.getenv("RAZORPAY_WEBHOOK_SECRET")
    if not secret:
        return jsonify({"error": "Webhook not configured"}), 503
    try:
        client.utility.verify_webhook_signature(
            request.get_data(as_text=True),
            request.headers.get("X-Razorpay-Signature", ""),
            secret,
        )
    except razorpay.errors.SignatureVerificationError:
        return jsonify({"error": "Bad signature"}), 400

    event = request.get_json(silent=True) or {}
    if event.get("event") == "payment.captured":
        payment = event["payload"]["payment"]["entity"]
        _grant({"order_id": payment["order_id"], "payment_id": payment["id"]})
    return jsonify({"status": "ok"})


@payment_bp.route("/my-entitlements", methods=["GET"])
@require_supabase_user
def my_entitlements():
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select product from neet_entitlements where user_id = %s "
                "and revoked_at is null and (expires_at is null or expires_at > now())",
                (g.user_id,),
            )
            products = [r[0] for r in cur.fetchall()]
    return jsonify({"entitlements": products})
