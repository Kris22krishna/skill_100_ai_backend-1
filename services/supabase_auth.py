"""Supabase JWT verification for payment routes.

The project signs access tokens with ES256 (asymmetric JWT signing keys), so
verification uses the public JWKS endpoint — fetched once and cached by
PyJWKClient. HS256 with the legacy shared secret is kept as a fallback for
tokens minted before a signing-key migration.

Every money-touching route requires a real logged-in Supabase user. Webhook
routes are exempt — they authenticate via Razorpay's signature instead.
"""
import os
from functools import lru_cache
from functools import wraps

import jwt
from flask import request, jsonify, g


@lru_cache(maxsize=1)
def _jwks_client():
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/auth/v1/.well-known/jwks.json"
    return jwt.PyJWKClient(url, cache_keys=True)


def _decode(token: str) -> dict:
    alg = jwt.get_unverified_header(token).get("alg", "")
    if alg == "HS256":
        return jwt.decode(token, os.environ["SUPABASE_JWT_SECRET"],
                          algorithms=["HS256"], audience="authenticated")
    key = _jwks_client().get_signing_key_from_jwt(token).key
    return jwt.decode(token, key, algorithms=["ES256", "RS256"], audience="authenticated")


def require_supabase_user(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"error": "Login required"}), 401
        try:
            claims = _decode(auth[7:])
        except jwt.PyJWTError:
            return jsonify({"error": "Invalid or expired session"}), 401
        g.user_id = claims["sub"]
        g.user_email = claims.get("email")
        return f(*args, **kwargs)
    return wrapper
