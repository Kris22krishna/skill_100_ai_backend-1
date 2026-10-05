"""The events API is a server-to-server Razorpay gateway. What must not be
wrong: it refuses callers without the shared key (and fails closed when the
key is unset), it never creates an order for a nonsense amount, and verify
only says `valid` when the signature checks AND the payment belongs to the
order."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import razorpay

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import Flask  # noqa: E402

from blueprints import events_blueprint as ev  # noqa: E402

KEY = "test-service-key"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("EVENTS_SERVICE_KEY", KEY)
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_abc")
    app = Flask(__name__)
    app.register_blueprint(ev.events_bp, url_prefix="/events")
    return app.test_client()


def post(c, path, body, key=KEY):
    headers = {"X-Service-Key": key} if key is not None else {}
    return c.post(path, json=body, headers=headers)


def test_missing_or_wrong_key_is_refused(client):
    assert post(client, "/events/orders", {}, key=None).status_code == 401
    assert post(client, "/events/orders", {}, key="nope").status_code == 401


def test_unset_key_fails_closed(client, monkeypatch):
    monkeypatch.delenv("EVENTS_SERVICE_KEY")
    assert post(client, "/events/orders", {}, key="").status_code == 503


@pytest.mark.parametrize("amount", [None, "10000", 10000.0, True, 99, 5_000_001])
def test_order_refuses_bad_amounts(client, amount):
    r = post(client, "/events/orders", {"amount_paise": amount, "receipt": "MD26-4001"})
    assert r.status_code == 400


def test_order_requires_a_receipt(client):
    assert post(client, "/events/orders", {"amount_paise": 10000}).status_code == 400


def test_order_is_created_for_the_callers_amount(client):
    fake = {"id": "order_1", "amount": 20000, "currency": "INR"}
    with patch.object(ev.client.order, "create", return_value=fake) as create:
        r = post(client, "/events/orders", {
            "amount_paise": 20000, "receipt": "MD26-4001",
            "notes": {"registration_id": "abc", "nested": {"x": 1}, "flag": True},
        })
    assert r.status_code == 200
    assert r.get_json() == {"order_id": "order_1", "amount": 20000,
                            "currency": "INR", "key_id": "rzp_test_abc"}
    sent = create.call_args.kwargs["data"]
    assert sent["amount"] == 20000 and sent["receipt"] == "MD26-4001"
    assert sent["notes"]["registration_id"] == "abc"
    assert "nested" not in sent["notes"] and "flag" not in sent["notes"]


SIG = {"razorpay_order_id": "order_1", "razorpay_payment_id": "pay_1",
       "razorpay_signature": "sig"}


def test_verify_rejects_a_bad_signature(client):
    err = razorpay.errors.SignatureVerificationError("bad")
    with patch.object(ev.client.utility, "verify_payment_signature", side_effect=err):
        r = post(client, "/events/verify", SIG)
    assert r.status_code == 400 and r.get_json()["valid"] is False


def test_verify_rejects_a_payment_for_another_order(client):
    with patch.object(ev.client.utility, "verify_payment_signature", return_value=True), \
         patch.object(ev.client.payment, "fetch", return_value={"order_id": "order_2"}):
        r = post(client, "/events/verify", SIG)
    assert r.status_code == 400 and r.get_json()["valid"] is False


def test_verify_reports_the_amount_taken(client):
    pay = {"order_id": "order_1", "status": "captured", "amount": 20000, "method": "upi"}
    with patch.object(ev.client.utility, "verify_payment_signature", return_value=True), \
         patch.object(ev.client.payment, "fetch", return_value=pay):
        r = post(client, "/events/verify", SIG)
    assert r.get_json() == {"valid": True, "status": "captured", "amount": 20000, "method": "upi"}


def test_verify_needs_all_three_fields(client):
    assert post(client, "/events/verify", {"razorpay_order_id": "o"}).status_code == 400


def test_order_status_names_the_captured_payment(client):
    order = {"status": "paid", "amount": 10000, "amount_paid": 10000}
    pays = {"items": [{"id": "pay_f", "status": "failed"}, {"id": "pay_ok", "status": "captured"}]}
    with patch.object(ev.client.order, "fetch", return_value=order), \
         patch.object(ev.client.order, "payments", return_value=pays):
        r = post(client, "/events/order-status", {"order_id": "order_1"})
    assert r.get_json()["payment_id"] == "pay_ok"
