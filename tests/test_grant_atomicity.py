"""_grant() must be all-or-nothing.

If the order is marked paid in its own committed transaction and the grant
items are written in separate ones, a failure partway leaves a paid order with
some products granted — and the status guard then refuses Razorpay's retry, so
the buyer is permanently short. These tests hold the whole thing inside one
transaction that rolls back as a unit.
"""
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import blueprints.payment_blueprint as pb

ORDER_ROW = {"id": "b3f1c8a2-0000-0000-0000-000000000001",
             "user_id": "11111111-1111-1111-1111-111111111111",
             "plan_id": "neet-complete-2027", "promo_code": None,
             "amount_paise": 2943156, "created_at": "2026-08-02"}
PLAN_ROW = {"id": "neet-complete-2027", "access_until": "2027-05-31",
            "grants": ["neet-biology", "neet-physics", "neet-chemistry",
                       "neet-test-series"]}


class FakeCursor:
    def __init__(self, rows, fail_on_statement=None):
        self.rows = list(rows)
        self.statements = []
        self.fail_on_statement = fail_on_statement

    def execute(self, sql, params=None):
        self.statements.append(sql)
        if self.fail_on_statement == len(self.statements):
            raise RuntimeError("connection dropped mid-grant")

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None


def install(monkeypatch, cursor):
    """Replace db.transaction with a fake that records commit/rollback."""
    outcome = []

    @contextmanager
    def fake_transaction():
        outcome.append("enter")
        try:
            yield cursor
        except Exception:
            outcome.append("rollback")
            raise
        else:
            outcome.append("commit")

    monkeypatch.setattr(pb.db, "transaction", fake_transaction)
    return outcome


def test_grant_runs_inside_exactly_one_transaction(monkeypatch):
    cur = FakeCursor([ORDER_ROW, PLAN_ROW])
    outcome = install(monkeypatch, cur)

    pb._grant({"order_id": "order_1", "payment_id": "pay_Nxyz"})

    assert outcome.count("enter") == 1, "grant must not span multiple transactions"
    assert outcome[-1] == "commit"


def test_all_four_bundle_products_are_written(monkeypatch):
    cur = FakeCursor([ORDER_ROW, PLAN_ROW])
    install(monkeypatch, cur)

    pb._grant({"order_id": "order_1", "payment_id": "pay_Nxyz"})

    appends = [s for s in cur.statements if "active_products = active_products ||" in s]
    assert len(appends) == 4


def test_failure_midway_rolls_back_the_paid_flag_too(monkeypatch):
    """Statement 5 is the second product append. The order-paid update is
    statement 1 — it must roll back with everything else so the retry can
    redo the whole grant."""
    cur = FakeCursor([ORDER_ROW, PLAN_ROW], fail_on_statement=5)
    outcome = install(monkeypatch, cur)

    with pytest.raises(RuntimeError):
        pb._grant({"order_id": "order_1", "payment_id": "pay_Nxyz"})

    assert "rollback" in outcome
    assert "commit" not in outcome


def test_already_paid_order_is_a_no_op(monkeypatch):
    """The status guard returns no row; nothing further may be issued."""
    cur = FakeCursor([None])
    outcome = install(monkeypatch, cur)

    pb._grant({"order_id": "order_1", "payment_id": "pay_Nxyz"})

    assert len(cur.statements) == 1
    assert outcome[-1] == "commit"
