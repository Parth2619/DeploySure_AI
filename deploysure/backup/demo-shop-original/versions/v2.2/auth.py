"""Login helpers for the demo shop (synthetic, not real security)."""
import hashlib


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password: str, hashed: str) -> bool:
    return hash_password(password) == hashed


def make_token(user: str) -> str:
    return f"tok-{user}"


def is_valid_token(token: str) -> bool:
    return token.startswith("tok-") and len(token) > 4
