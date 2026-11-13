#!/usr/bin/env python3
"""Validate required production environment values without printing secrets."""
from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env", help="Environment file to validate (default: .env)")
    args = parser.parse_args()
    values = read_env(Path(args.env_file))
    values = {**values, **{k: v for k, v in __import__("os").environ.items() if k in {
        "POSTGRES_PASSWORD", "SENTIMENTIQ_SECRET_KEY", "DOMAIN", "ACME_EMAIL", "SMTP_HOST", "SMTP_FROM"
    }}}
    errors: list[str] = []
    warnings: list[str] = []

    password = values.get("POSTGRES_PASSWORD", "")
    if len(password) < 24 or not re.fullmatch(r"[A-Za-z0-9_-]+", password):
        errors.append("POSTGRES_PASSWORD must be at least 24 URL-safe characters (generate with: openssl rand -hex 24).")

    secret = values.get("SENTIMENTIQ_SECRET_KEY", "")
    if len(secret) < 32 or secret.lower().startswith(("replace", "change", "your-", "example")):
        errors.append("SENTIMENTIQ_SECRET_KEY must be a unique secret of at least 32 characters (generate with: openssl rand -hex 32).")

    domain = values.get("DOMAIN", "")
    if not domain or "://" in domain or "/" in domain or " " in domain or "." not in domain:
        errors.append("DOMAIN must be a hostname only, e.g. app.example.com (no scheme or path).")

    email = values.get("ACME_EMAIL", "")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        errors.append("ACME_EMAIL must be a valid email address for TLS certificate notices.")

    if not values.get("SMTP_HOST") or not values.get("SMTP_FROM"):
        warnings.append("SMTP is not fully configured; scheduled reports can be generated and retained, but email delivery will not work.")

    for message in errors:
        print(f"FAIL: {message}")
    for message in warnings:
        print(f"WARN: {message}")
    if errors:
        print(f"Preflight failed: {len(errors)} blocking issue(s). No secrets were printed.")
        return 1
    print("PASS: required production settings are present and structurally valid.")
    print("NOTE: this check does not verify DNS, TLS issuance, database connectivity, SMTP credentials or cloud-provider access.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
