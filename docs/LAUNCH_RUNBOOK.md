# SentimentIQ 1.0.0-rc1 — Launch Runbook

This release is a deployment-ready candidate. It does not deploy itself or create a cloud account, DNS record, domain, SMTP credential, or managed backup service.

## 1. Infrastructure prerequisites

- A Linux VM or host with Docker Engine and the Docker Compose plugin.
- A DNS hostname you control, for example `app.example.com`, with an A record (and an AAAA record only if IPv6 is configured) pointing to the host.
- Inbound TCP ports 80 and 443 open. UDP 443 is optional but enables HTTP/3.
- A persistent disk for Docker volumes and enough space for PostgreSQL, reports and backups.
- A mailbox/SMTP provider if scheduled email delivery is required.

Do not expose PostgreSQL or the API port directly to the public internet. In the production Compose topology, only Caddy publishes ports.

## 2. Configure secrets

From the repository root:

```sh
cp .env.production.example .env
openssl rand -hex 24   # paste into POSTGRES_PASSWORD
openssl rand -hex 32   # paste into SENTIMENTIQ_SECRET_KEY
```

Set `DOMAIN` to the hostname only (no `https://`), and `ACME_EMAIL` to an address that can receive certificate notices. Keep `.env` private; it is excluded by `.gitignore`.

If SMTP is not configured, scheduled PDFs can still be generated and retained in SentimentIQ, but email delivery will not occur.

Run the local configuration check:

```sh
python scripts/preflight.py --env-file .env
```

This validates structure only. It does not contact DNS, the ACME service, SMTP or the database.

## 3. Start the production topology

```sh
docker compose -f docker-compose.production.yml config
docker compose -f docker-compose.production.yml up --build -d
docker compose -f docker-compose.production.yml ps
```

Caddy requests and renews HTTPS certificates automatically after DNS and network prerequisites are met. First issuance can take a short while. Inspect logs with:

```sh
docker compose -f docker-compose.production.yml logs -f caddy backend db
```

Open `https://$DOMAIN` in a browser. Do not consider the service live until HTTPS works and the checks below pass.

## 4. Post-deployment verification

```sh
SENTIMENTIQ_BASE_URL="https://$DOMAIN" python scripts/smoke_test.py
```

For an additional authenticated check, create a test account through the UI, sign in, and export its short-lived token only into the shell environment for the test process:

```sh
SENTIMENTIQ_SMOKE_TEST_TOKEN='your-short-lived-access-token' \\
SENTIMENTIQ_BASE_URL="https://$DOMAIN" python scripts/smoke_test.py
```

The smoke test is non-destructive. It checks liveness, database readiness and important response headers; with a token, it also checks `/api/v1/auth/me`.

## 5. Backup and restore

Configure encrypted off-host backup storage and a retention policy before accepting real customer data. The included PostgreSQL scripts create/restore database dumps but do not upload, encrypt, rotate, or verify them automatically. Complete a restore drill into a separate database and document the result before launch.

See `docs/SECURITY_OPERATIONS.md` for the PostgreSQL backup and restore commands.

## 6. Rollback

1. Record the deployed image tags and current database migration revision.
2. Stop application services while retaining volumes: `docker compose -f docker-compose.production.yml down` (do not add `-v`).
3. Restore the previous application image/build and redeploy.
4. If a migration changed the schema, restore a verified pre-upgrade database backup into a separate recovery database and follow a tested rollback plan. Do not assume Alembic downgrades are safe for every data migration.
5. Run the smoke test and verify a test workspace before reopening traffic.

Never remove the named volumes during an application rollback.

## 7. Launch gates still requiring owner action

- [ ] Domain registered and DNS records verified.
- [ ] Hosting VM provisioned, patched and access restricted.
- [ ] `.env` populated with unique secrets and protected file permissions.
- [ ] TLS certificate successfully issued by Caddy.
- [ ] Production smoke test passes over HTTPS.
- [ ] SMTP tested end-to-end with a real recipient (if email is enabled).
- [ ] Backup copied off-host and restore drill succeeds.
- [ ] Dependency/container CVE scan completed.
- [ ] External penetration test and load test completed.
- [ ] Privacy policy, terms, retention schedule and customer data-processing obligations reviewed.
- [ ] Frontend CDN dependencies reviewed and ideally vendored/self-hosted for supply-chain control.
- [ ] Monitoring, alert routing, incident owner and support contact configured.

A passing local test suite is not equivalent to a completed production launch or security certification.
