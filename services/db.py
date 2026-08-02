"""Postgres access (same Supabase database the main backend uses).

The service connects with DATABASE_URL (service credentials, bypasses RLS) —
orders and entitlement grants MUST happen server-side; nothing here is
reachable with the browser's anon key.
"""
import os
from contextlib import contextmanager

import psycopg2
import psycopg2.extras

psycopg2.extras.register_uuid()


@contextmanager
def get_conn():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def fetch_one(sql, params=None):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or ())
            return cur.fetchone()


def execute(sql, params=None):
    """Run a statement; returns the first row when the SQL has RETURNING."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or ())
            try:
                return cur.fetchone()
            except psycopg2.ProgrammingError:
                return None
