"""Razorpay for public event registrations (Math Dasara first).

The caller is a trusted SERVER — skill100-web's API routes — never a browser.
It owns the registration record and the price; this service only talks to
Razorpay. Every route needs the shared `X-Service-Key` header (env
EVENTS_SERVICE_KEY); with that variable unset the routes answer 503, so a
misconfigured deploy fails closed.

- POST /events/orders        create an order for an amount the caller priced
- POST /events/verify        check a checkout's signature against Razorpay
- POST /events/order-status  is this order paid? (reconciles a closed tab)
"""
import hmac
import os
from functools import wraps

import razorpay
from flask import Blueprint, jsonify, request

from services.get_kolkata_timestamp import get_kolkata_timestamp

events_bp = Blueprint("events", __name__)
client = razorpay.Client(auth=(os.getenv("RAZORPAY_KEY_ID"), os.getenv("RAZORPAY_KEY_SECRET")))
client.set_app_details({"title": "Skill 100 AI", "version": "1.0.0"})

# A registration is a handful of ₹100 seats; anything above this is a bug.
MAX_AMOUNT_PAISE = 5_000_000  # ₹50,000


def require_service_key(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        expected = os.getenv("EVENTS_SERVICE_KEY")
        if not expected:
            return jsonify({"error": "Events API not configured"}), 503
        given = request.headers.get("X-Service-Key", "")
        if not hmac.compare_digest(given.encode(), expected.encode()):
            return jsonify({"error": "Unauthorized"}), 401
        return view(*args, **kwargs)
    return wrapped


def _notes(raw):
    """Razorpay allows 15 notes of up to 256 chars; keep strings only."""
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key, value in list(raw.items())[:14]:
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            out[str(key)[:40]] = str(value)[:256]
    return out


@events_bp.route("/orders", methods=["POST"])
@require_service_key
def create_order():
    data = request.get_json(silent=True) or {}
    amount = data.get("amount_paise")
    receipt = str(data.get("receipt") or "").strip()[:40]
    if not isinstance(amount, int) or isinstance(amount, bool):
        return jsonify({"error": "amount_paise must be an integer"}), 400
    if amount < 100 or amount > MAX_AMOUNT_PAISE:
        return jsonify({"error": "amount_paise out of range"}), 400
    if not receipt:
        return jsonify({"error": "receipt is required"}), 400

    notes = _notes(data.get("notes"))
    notes["purchase_initiated_at"] = get_kolkata_timestamp()
    order = client.order.create(data={
        "amount": amount,
        "currency": "INR",
        "receipt": receipt,
        "notes": notes,
    })
    return jsonify({
        "order_id": order["id"],
        "amount": order["amount"],
        "currency": order["currency"],
        "key_id": os.getenv("RAZORPAY_KEY_ID"),
    })


@events_bp.route("/verify", methods=["POST"])
@require_service_key
def verify():
    data = request.get_json(silent=True) or {}
    required = ("razorpay_order_id", "razorpay_payment_id", "razorpay_signature")
    if any(not isinstance(data.get(k), str) or not data.get(k) for k in required):
        return jsonify({"error": "Missing payment verification fields"}), 400
    try:
        client.utility.verify_payment_signature({k: data[k] for k in required})
    except razorpay.errors.SignatureVerificationError:
        return jsonify({"valid": False, "error": "Payment verification failed"}), 400

    # The signature proves Razorpay issued this payment for this order; the
    # payment itself says how much was actually taken.
    payment = client.payment.fetch(data["razorpay_payment_id"])
    if payment.get("order_id") != data["razorpay_order_id"]:
        return jsonify({"valid": False, "error": "Payment does not match order"}), 400
    return jsonify({
        "valid": True,
        "status": payment.get("status"),
        "amount": payment.get("amount"),
        "method": payment.get("method"),
    })


@events_bp.route("/order-status", methods=["POST"])
@require_service_key
def order_status():
    data = request.get_json(silent=True) or {}
    order_id = data.get("order_id")
    if not isinstance(order_id, str) or not order_id:
        return jsonify({"error": "order_id is required"}), 400
    order = client.order.fetch(order_id)
    payment_id = None
    if order.get("status") == "paid":
        payments = client.order.payments(order_id).get("items", [])
        captured = [p for p in payments if p.get("status") == "captured"]
        payment_id = captured[0]["id"] if captured else None
    return jsonify({
        "status": order.get("status"),
        "amount": order.get("amount"),
        "amount_paid": order.get("amount_paid"),
        "payment_id": payment_id,
    })
