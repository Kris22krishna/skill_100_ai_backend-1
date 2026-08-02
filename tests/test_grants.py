"""Grant items are what a customer's access is made of. The apportionment and
the idempotency marker are the two things that must not be wrong: a bundle
must produce four items summing to exactly what was charged, and a webhook
retry must be recognisable as already-applied."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.grants import build_grant_items

PLAN = {
    "id": "neet-complete-2027",
    "grants": ["neet-biology", "neet-physics", "neet-chemistry", "neet-test-series"],
    "access_until": "2027-05-31",
}
ORDER = {"id": "b3f1c8a2-0000-0000-0000-000000000001", "created_at": "2026-08-02"}


def test_bundle_produces_one_item_per_product():
    items = build_grant_items(PLAN, ORDER, "pay_Nxyz123", 2943156)
    assert [i["product_name"] for i in items] == PLAN["grants"]


def test_every_item_carries_the_five_required_fields():
    item = build_grant_items(PLAN, ORDER, "pay_Nxyz123", 2943156)[0]
    for field in ("product_name", "purchase_date", "expiration_date",
                  "payment_type", "payment_amount"):
        assert field in item, f"missing {field}"


def test_apportioned_amounts_sum_to_the_total_charged():
    items = build_grant_items(PLAN, ORDER, "pay_Nxyz123", 2943156)
    total = sum(round(float(i["payment_amount"]) * 100) for i in items)
    assert total == 2943156


def test_indivisible_total_loses_no_paise():
    """A discounted bundle rarely divides by four. The remainder must land on
    an item rather than vanish, or the grants won't reconcile against the
    order and the books drift by a few paise per sale."""
    items = build_grant_items(PLAN, ORDER, "pay_Nxyz123", 2943157)
    total = sum(round(float(i["payment_amount"]) * 100) for i in items)
    assert total == 2943157
    assert items[0]["payment_amount"] == "7357.90"   # remainder joins the first


def test_single_product_gets_the_whole_amount():
    plan = {"id": "neet-biology-2027", "grants": ["neet-biology"],
            "access_until": "2027-05-31"}
    items = build_grant_items(plan, ORDER, "pay_A", 981052)
    assert items[0]["payment_amount"] == "9810.52"


def test_source_marks_the_payment_for_idempotency():
    items = build_grant_items(PLAN, ORDER, "pay_Nxyz123", 2943156)
    assert all(i["source"] == "razorpay:pay_Nxyz123" for i in items)


def test_expiration_comes_from_the_plan():
    items = build_grant_items(PLAN, ORDER, "pay_A", 2943156)
    assert all(i["expiration_date"] == "2027-05-31" for i in items)


def test_order_id_is_recorded_for_audit():
    items = build_grant_items(PLAN, ORDER, "pay_A", 2943156)
    assert all(i["order_id"] == ORDER["id"] for i in items)


def test_payment_type_is_razorpay_by_default():
    items = build_grant_items(PLAN, ORDER, "pay_A", 2943156)
    assert all(i["payment_type"] == "razorpay" for i in items)


def test_admin_grant_payment_type_is_supported():
    items = build_grant_items(PLAN, ORDER, "scholarship-2026", 0,
                              payment_type="admin-grant")
    assert all(i["payment_type"] == "admin-grant" for i in items)
    assert all(i["payment_amount"] == "0.00" for i in items)
