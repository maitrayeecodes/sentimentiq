# SentimentIQ — Security and operations runbook (Iteration 9)

## Security controls in this build

- API responses include `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, and `Permissions-Policy` headers.
- API responses use `Cache-Control: no-store` to reduce the chance of sensitive review data being cached by intermediaries.
- A lightweight in-process rate limiter applies separate limits to authentication, uploads, general API requests, and other requests. It is a best-effort guardrail, **not a distributed rate limiter**; production deployments with multiple API replicas should put a shared rate limiter (for example, Redis-backed) at the edge.
- Upload parsing is moved off the async event loop. Existing 10 MB compressed upload, 100 MB Excel expansion, and 20,000-row limits remain in place.
- Analysis deletion removes linked report schedules and retained report-delivery PDFs. Workspace owners can inspect deletion audit events and purge analyses older than a chosen retention period (minimum 30 days), with explicit confirmation.
- PostgreSQL advisory locking ensures only one scheduler worker runs when several API replicas share the same PostgreSQL database. SQLite deployments should run as a single backend process.
- Database indexes support due-schedule polling and workspace audit history.

## Production deployment checklist

1. Use PostgreSQL, not SQLite, for shared or multi-instance deployments.
2. Generate a unique `SENTIMENTIQ_SECRET_KEY` of at least 32 random characters and a strong database password. Keep `.env` out of source control.
3. Terminate HTTPS at a trusted reverse proxy/load balancer. Do not expose the backend port directly to the public internet.
4. Configure `SENTIMENTIQ_CORS_ORIGINS` with exact trusted frontend origins; do not use `*` with credentials.
5. Configure SMTP credentials through a secret manager or protected environment variables. Verify delivery with a real mailbox before enabling schedules.
6. Use a shared rate limiter and central log aggregation before running multiple public API replicas.
7. Configure database backups, off-host retention, restore drills, and monitoring. A backup is not verified until a restore has succeeded.
8. Review data retention obligations before setting a purge cadence. Purging is permanent and also removes associated scheduled report records and retained PDF deliveries.
9. Rotate secrets after suspected exposure and invalidate user sessions by rotating the signing secret.
10. Run dependency and container image vulnerability scans before public launch.

## PostgreSQL backup and restore

Set `DATABASE_URL` to a PostgreSQL URL and install PostgreSQL client tools (`pg_dump`, `pg_restore`).

```sh
DATABASE_URL='postgresql+psycopg://user:password@host:5432/sentimentiq' \
BACKUP_DIR='./backups' backend/scripts/backup_postgres.sh
```

Restore only into a verified target database. This command replaces matching objects:

```sh
DATABASE_URL='postgresql+psycopg://user:password@host:5432/sentimentiq' \
BACKUP_FILE='./backups/sentimentiq-YYYYMMDDTHHMMSSZ.dump' \
backend/scripts/restore_postgres.sh
```

Store backups encrypted and separately from the application host. The scripts do not configure cloud object storage, encryption, or automatic retention by themselves.

## Rate limiting notes

The built-in limiter is process-local and memory-backed. It resets on restart and does not coordinate across workers. Keep a conservative edge limit in production and replace or augment this limiter with a shared store before scaling horizontally.

## Deletion and audit API

- `DELETE /api/v1/analyses/{analysis_id}` permanently deletes an analysis and its associated schedules and report deliveries within the active workspace.
- `GET /api/v1/audit-events` returns the latest 100 workspace audit events; workspace-owner role required.
- `POST /api/v1/data-retention/purge` accepts `{ "older_than_days": 180, "confirm": true }`; workspace-owner role required. The minimum is 30 days.

Deletion audit events record the action and dataset name, not review text. Audit history is retained until its workspace is deleted or database retention is applied operationally.

## Known limitations

This is a production-hardening iteration, not a security certification. No external penetration test, DAST, dependency CVE scan, live PostgreSQL concurrency test, backup restore drill, SMTP provider test, or multi-replica load test was performed in the build environment. The rate limiter is in-process. Configure TLS, edge controls, centralized monitoring, and restore testing before launch.
