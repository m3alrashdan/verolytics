"""Password hashing + token generation (stdlib only — no external crypto deps).

Passwords use PBKDF2-HMAC-SHA256 with a per-password random salt; the stored
string is self-describing (algo$iterations$salt$hash) so the cost can evolve.
Session tokens are opaque, cryptographically-random strings stored server-side.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets

_ALGO = "pbkdf2_sha256"
_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"{_ALGO}${_ITERATIONS}${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_b64, hash_b64 = stored.split("$")
        if algo != _ALGO:
            return False
        salt, expected = _unb64(salt_b64), _unb64(hash_b64)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(dk, expected)  # constant-time
    except (ValueError, TypeError):
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))
