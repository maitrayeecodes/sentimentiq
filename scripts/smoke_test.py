#!/usr/bin/env python3
"""Run non-destructive post-deployment checks against a SentimentIQ URL."""
from __future__ import annotations
import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def request(base: str, path: str, token: str | None = None):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base.rstrip("/") + path, headers=headers)
    with urllib.request.urlopen(req, timeout=12) as response:
        body = response.read()
        return response.status, dict(response.headers), json.loads(body) if body else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.getenv("SENTIMENTIQ_BASE_URL", "http://127.0.0.1:8080"))
    args = parser.parse_args()
    checks = []
    try:
        status, headers, body = request(args.url, "/health")
        checks.append(("liveness", status == 200 and body.get("status") == "ok"))
        normalized_headers = {key.lower(): value for key, value in headers.items()}
        checks.append(("security headers", normalized_headers.get("x-content-type-options") == "nosniff" and normalized_headers.get("x-frame-options") == "DENY"))
        status, _, ready = request(args.url, "/ready")
        checks.append(("database readiness", status == 200 and ready.get("database") == "ok"))
        token = os.getenv("SENTIMENTIQ_SMOKE_TEST_TOKEN", "").strip()
        if token:
            status, _, profile = request(args.url, "/api/v1/auth/me", token)
            checks.append(("authenticated profile", status == 200 and bool(profile.get("user", {}).get("id"))))
        else:
            print("SKIP: authenticated profile check (set SENTIMENTIQ_SMOKE_TEST_TOKEN to enable).")
    except urllib.error.HTTPError as exc:
        print(f"FAIL: HTTP {exc.code} while checking deployment endpoint.")
        return 1
    except Exception as exc:
        print(f"FAIL: could not complete deployment checks ({type(exc).__name__}).")
        return 1
    for label, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'}: {label}")
    failed = sum(not passed for _, passed in checks)
    print(f"Smoke test result: {len(checks)-failed}/{len(checks)} checks passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
