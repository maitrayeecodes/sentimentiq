from __future__ import annotations
import base64, hashlib, hmac, json, os, secrets, time
from fastapi import HTTPException, status

SECRET_KEY = os.getenv("SENTIMENTIQ_SECRET_KEY", "")
if os.getenv("ENVIRONMENT", "development") == "production" and (len(SECRET_KEY) < 32 or SECRET_KEY.startswith("replace-") or SECRET_KEY == ""):
    raise RuntimeError("SENTIMENTIQ_SECRET_KEY must be set to a unique value of at least 32 characters in production")
if len(SECRET_KEY) < 32:
    SECRET_KEY = "development-only-change-this-secret-key-before-deploying"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)
    return "pbkdf2_sha256$600000$" + base64.urlsafe_b64encode(salt).decode() + "$" + base64.urlsafe_b64encode(digest).decode()


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, rounds, salt_b64, digest_b64 = encoded.split("$")
        if scheme != "pbkdf2_sha256": return False
        salt = base64.urlsafe_b64decode(salt_b64.encode())
        expected = base64.urlsafe_b64decode(digest_b64.encode())
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(rounds))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def create_access_token(user_id: str) -> str:
    now = int(time.time())
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64(json.dumps({"sub": user_id, "iat": now, "exp": now + 60 * 60 * 12}, separators=(",", ":")).encode())
    signing = f"{header}.{payload}"
    signature = _b64(hmac.new(SECRET_KEY.encode(), signing.encode(), hashlib.sha256).digest())
    return f"{signing}.{signature}"


def decode_access_token(token: str) -> str:
    try:
        header, payload, signature = token.split(".")
        signing = f"{header}.{payload}"
        expected = _b64(hmac.new(SECRET_KEY.encode(), signing.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected): raise ValueError("signature")
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if claims.get("exp", 0) < time.time() or not claims.get("sub"): raise ValueError("expired")
        return claims["sub"]
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired access token", headers={"WWW-Authenticate": "Bearer"})
