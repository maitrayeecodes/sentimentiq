# SentimentIQ 1.0.0-rc1

## Release scope

This release candidate consolidates the ten planned development iterations: workspace authentication, review upload and analysis, multilingual/heuristic NLP, competitor dataset comparison, scheduled PDF reporting, deletion/retention controls, operational security guardrails and production deployment configuration.

## Added in Iteration 10

- Versioned release candidate API.
- Liveness and database-readiness endpoints.
- Production Compose topology with private data/application networks.
- Caddy reverse proxy with automatic HTTPS certificate management.
- Frontend CSP and additional browser security headers.
- Production environment preflight and non-destructive post-deployment smoke tests.
- Release verification script and deployment/rollback runbook.

## Verification performed in the build environment

- Backend automated suite: 28 passed.
- Python compilation: passed.
- Frontend JavaScript syntax: passed.
- Development and production Compose YAML parse: passed with PyYAML.
- Production preflight: passed against temporary structurally valid test values; no production secrets were used.
- Live local API smoke test: liveness, security headers and database readiness all passed (3/3).

## Not performed

- No public cloud deployment or DNS change.
- No real ACME/TLS certificate issuance.
- No Docker Compose runtime test (Docker CLI unavailable in the build environment).
- No live PostgreSQL concurrency or backup restore drill.
- No real SMTP delivery test.
- No external vulnerability scan, penetration test or load test.

This is a release candidate, not a security certification. Complete `docs/LAUNCH_RUNBOOK.md` before accepting production customer data.

## Visual refresh — November 2026
- Reworked the public landing page with a responsive premium SaaS layout, product preview, feature sections, workflow, and clear sign-in/register actions.
- Refreshed the application shell, sidebar, cards, forms, tables, buttons, and responsive layouts with a consistent indigo/lavender design system.
- Added a shared style-string normalizer for HTM/React rendering to prevent invalid React style-prop errors.
- Preserved existing API endpoints and analysis workflows; the landing-page dashboard preview is explicitly illustrative and uses placeholders rather than presenting sample metrics as real customer data.
