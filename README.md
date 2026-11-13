# SentimentIQ — Customer Feedback Intelligence

## Iteration 10 — Launch and Deployment Release Candidate

- Versioned API release candidate (`1.0.0-rc1`) and separate liveness (`/health`) and database readiness (`/ready`) probes.
- Production Compose topology in `docker-compose.production.yml`: PostgreSQL on a private data network, API and frontend on private application networks, and Caddy as the only public ingress.
- Caddy automatic HTTPS using ACME; requires a real DNS hostname pointing to the server and inbound TCP ports 80/443 (plus UDP 443 for HTTP/3).
- Nginx security headers and a Content Security Policy constrained to the CDN/font origins currently used by the frontend.
- Proxy-aware Uvicorn configuration for correct client IP forwarding behind the private Nginx/Caddy chain.
- `scripts/preflight.py` validates required production secrets and hostname/email configuration without printing secret values.
- `scripts/smoke_test.py` checks public liveness, readiness, response security headers and optionally an authenticated profile.
- `scripts/verify_release.sh` runs compilation, the backend suite, frontend syntax validation and available Compose/preflight checks.
- Deployment and rollback instructions in `docs/LAUNCH_RUNBOOK.md`.
- **Release status:** deployment-ready candidate, not publicly deployed. DNS, hosting credentials, TLS issuance, live PostgreSQL, SMTP, restore drills and external security/load testing still require verification in the target environment.

SentimentIQ turns uploaded customer reviews into sentiment, topic, complaint and trend summaries. Iteration 9 adds API security headers, request throttling, permanent deletion controls, workspace audit history, retention purging, PostgreSQL scheduler leader locking and backup/restore runbooks, alongside the reporting and customer-intelligence features from earlier iterations.


## Iteration 9 — Production Engineering

- API security headers (`nosniff`, frame denial, referrer policy and permissions policy); API responses are marked `no-store`.
- In-process request throttling with separate auth, upload and general API budgets. This is a best-effort per-process guardrail, not a distributed rate limiter.
- Review analysis runs in a worker thread so CPU-heavy parsing/scoring does not block the async request loop.
- Permanent single-analysis deletion from the Overview page, including associated report schedules and retained delivery PDFs.
- Workspace-owner audit history for deletion and retention events.
- Workspace-owner data-retention purge with explicit confirmation and a 30-day minimum retention window.
- PostgreSQL advisory lock prevents multiple API replicas from running duplicate report scheduler workers. SQLite should remain single-process.
- Database indexes for due report schedules and workspace audit queries.
- PostgreSQL backup and restore scripts under `backend/scripts/`, plus `docs/SECURITY_OPERATIONS.md` production runbook.
- **Still required before public launch:** external shared rate limiting, TLS/edge configuration, centralized monitoring, dependency/container scanning, live PostgreSQL concurrency testing, real backup restore drill, SMTP verification and security review.

## Iteration 8 — Reporting & Automation

- Download a formatted, workspace-scoped PDF executive report for any saved analysis.
- Create weekly or monthly report schedules with UTC send time and recipient email.
- Scheduled reports follow the newest saved analysis in the workspace with the same dataset name, so re-uploading an updated file under the same name refreshes the next report.
- Optional negative-sentiment threshold flags the scheduled email subject when the latest analysis meets or exceeds the configured share. This is a simple threshold alert, not an incident prediction.
- Report PDFs are retained in workspace-scoped delivery history, including when SMTP is not configured or email delivery fails.
- Configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD` and `SMTP_FROM` in `.env` to enable email attachments. Without SMTP, schedules still generate and retain PDFs for download.
- The scheduler checks due jobs once per minute. PostgreSQL deployments use a database advisory lock so only one API replica owns the scheduler; SQLite should run as a single backend process. Schedules use UTC and monthly dates are limited to days 1–28.

## Iteration 7 — Competitive Intelligence

- Compare 2–8 saved review datasets inside the current workspace; dataset names are displayed as brand labels.
- Side-by-side review counts, positive/neutral/negative shares, net sentiment points and high/critical priority share.
- Topic-level comparison with mention counts and negative/positive shares.
- Evidence-conscious relative signals highlight highest/lowest net sentiment and topic areas worth investigating.
- Download a comparison CSV.
- `POST /api/v1/competitive/benchmark` validates workspace access for every selected analysis.
- Important scope: this compares datasets the user has uploaded. It does not scrape competitor websites, estimate market share, or establish causal performance differences. Use comparable sources, time periods, review volumes and sampling methods for meaningful comparisons.

## Iteration 6 features

- Heuristic language detection for English, Spanish, French and Hindi, with small transparent sentiment lexicons for Spanish, French and Hindi.
- Multilingual keyword additions for Delivery, Product Quality, Pricing and Customer Support.
- Similar-review discovery using a locally configured sentence-transformer model when available; otherwise TF-IDF word/phrase similarity is used. Processing is capped at 800 reviews per run for this feature.
- Optional labelled evaluation using `expected_sentiment` (aliases: `label`, `ground_truth_sentiment`): accuracy, macro-F1, per-class precision/recall/F1 and a confusion matrix.
- Review Explorer displays detected language; Topic Intelligence displays similarity clusters; Reports shows labelled evaluation metrics when labels are present.
- Includes `sample-data/labelled-evaluation-template.csv` as a small upload template.

## Iteration 5 features

- Indicative emotion cues (Frustration, Trust, Delight, Confusion, Urgency and Disappointment) using transparent keyword lexicons.
- Review priority triage (Critical / High / Medium / Low) using urgency phrases and a small negative-sentiment adjustment; each review includes matched signals and a bounded 0–5 score.
- Exact duplicate detection after case-folding and punctuation normalization; duplicate groups and review IDs are retained for human verification.
- Exploratory repeated unigram/bigram discovery outside the fixed topic taxonomy, with example snippets; these are leads, not validated emerging topics.
- Workspace dashboard and Topic Intelligence views show priority queue, emotion distribution, duplicate groups and emerging terms.
- Review Explorer displays priority and exposes emotion/urgency/duplicate metadata. CSV and JSON exports include the new signals.

## Iteration 4 features

- Upload CSV (`.csv`) and Excel (`.xlsx`) workbooks.
- Upload guardrails: 10 MB file size and 20,000 review-row maximum.
- Topic/aspect sentiment: matching sentences are scored separately for each detected topic, so a mixed review can show positive product quality and negative delivery at the same time.
- Topic-level positive, neutral and negative counts use aspect sentiment rather than copying the overall review label.
- Evidence snippets are retained for each review-topic pair and shown in Review Explorer.
- Complaint cards include practical, topic-specific suggested next steps.
- Review CSV exports now include topic-level sentiment; JSON exports include full analysis evidence.

## Iteration 3 features

- Email/password registration and sign-in.
- Passwords stored as salted PBKDF2-HMAC-SHA256 hashes (600,000 rounds); raw passwords are never stored.
- Signed HS256 bearer access tokens with a 12-hour expiry.
- A business workspace is created during registration; users can create additional workspaces through the API.
- Every analysis belongs to one workspace and the user who created it.
- All analysis list/detail/upload operations require authentication and validate membership in the selected workspace.
- PostgreSQL 16 service and persistent Docker volume; SQLAlchemy ORM and Alembic migration baseline.
- Browser login/register screen, workspace switcher and sign-out.
- SQLite remains available for local development and automated tests.
- Existing review analysis: CSV/Excel upload, VADER sentiment baseline, explainable topic taxonomy, complaint examples, trends and CSV/JSON exports.

## Run with Docker Compose (recommended)

1. Install Docker Desktop or Docker Engine with the Compose plugin.
2. From this repository root, create a `.env` file. Generate unique secrets (hex strings avoid URL-escaping problems in the database connection string):

```bash
openssl rand -hex 24   # use as POSTGRES_PASSWORD
openssl rand -hex 32   # use as SENTIMENTIQ_SECRET_KEY
```

Then fill in `.env`:

```dotenv
POSTGRES_PASSWORD=
SENTIMENTIQ_SECRET_KEY=
ENVIRONMENT=production

# Optional: configure these to email scheduled report PDFs
SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM=
```

3. Start the services:

```bash
docker compose up --build -d
```

4. Open [http://localhost:8080](http://localhost:8080), choose **Create an account**, and register your business workspace.

The database runs on the internal Docker network and is not published to the host. PostgreSQL data persists in the `sentimentiq_postgres` named volume. The API container runs `alembic upgrade head` before starting FastAPI.

To stop services without deleting data:

```bash
docker compose down
```

To permanently delete the database volume (destructive):

```bash
docker compose down -v
```

## Run locally without Docker

Requirements: Python 3.11+, PostgreSQL 16 (or use the default local SQLite database).

```bash
cd backend
python -m venv .venv
```

Windows PowerShell: `.venv\\Scripts\\Activate.ps1`  
macOS/Linux: `source .venv/bin/activate`

Install dependencies and run:

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

By default, the backend creates a local SQLite database under `backend/data/sentimentiq.db`. For PostgreSQL, set `DATABASE_URL` and `SENTIMENTIQ_SECRET_KEY` in the environment before starting. For example:

```bash
DATABASE_URL=postgresql+psycopg://sentimentiq:password@localhost:5432/sentimentiq
SENTIMENTIQ_SECRET_KEY=use-a-unique-random-secret-of-at-least-32-characters
```

Serve the repository root with VS Code Live Server or another static HTTP server. `config.js` points to `http://127.0.0.1:8000` by default. The Docker frontend uses same-origin API routing through Nginx.

## Authentication and workspace API

- `POST /api/v1/auth/register` — `{full_name,email,password,workspace_name}`; password minimum 10 characters.
- `POST /api/v1/auth/login` — `{email,password}`.
- `GET /api/v1/auth/me` — current account and memberships.
- `GET /api/v1/workspaces` — list memberships.
- `POST /api/v1/workspaces` — create another workspace for the signed-in account.

Protected analysis endpoints require `Authorization: Bearer <access_token>`. Send `X-Workspace-ID: <workspace_id>` to choose a workspace; if omitted, the account's first workspace is selected. Membership is checked on every request.

- `GET /health` — service health/version.
- `POST /api/v1/analyses` — authenticated multipart CSV or `.xlsx` upload; fields `file` and optional `dataset_name`.
- `GET /api/v1/analyses` — list runs in the active workspace.
- `GET /api/v1/analyses/{analysis_id}` — retrieve a run only if it belongs to the active workspace.
- `DELETE /api/v1/analyses/{analysis_id}` — permanently delete the run and its linked report schedules/deliveries.
- `POST /api/v1/competitive/benchmark` — compare 2–8 analysis IDs from the active workspace; request body: `{ "analysis_ids": ["<id-1>", "<id-2>"] }`.
- `GET /api/v1/reports/{analysis_id}.pdf` — download a PDF executive report.
- `POST /api/v1/report-schedules` / `GET /api/v1/report-schedules` / `DELETE /api/v1/report-schedules/{id}` — manage weekly/monthly report schedules.
- `POST /api/v1/report-schedules/{id}/run` — manually generate and attempt to email a scheduled report.
- `GET /api/v1/report-deliveries` / `GET /api/v1/report-deliveries/{id}.pdf` — view delivery history and download retained PDFs.
- `GET /api/v1/audit-events` — workspace-owner audit history (latest 100 events).
- `POST /api/v1/data-retention/purge` — permanently purge workspace analyses older than the requested days; requires `{ "older_than_days": 180, "confirm": true }` and workspace-owner permission.

Interactive API documentation: `http://127.0.0.1:8000/docs`.

## Competitive benchmark sample data

Two synthetic sample datasets are included for trying the benchmark screen: `sample-data/benchmark-brand-alpha.csv` and `sample-data/benchmark-brand-beta.csv`. Upload each as a separate dataset and use the suggested brand names. These records are fictional test data and must not be presented as real market or customer research.

## Upload format

A ready-to-upload Excel example is included at `sample-data/sentimentiq-sample-reviews.xlsx`.


CSV and Excel `.xlsx` workbooks are supported (legacy `.xls` is not). For Excel, the first worksheet and its first row are used as the header row. Maximum file size is 10 MB and maximum review rows per upload is 20,000. Required text column: `review_text`, `review`, `text`, `comment` or `feedback`. Optional: `review_id`/`id`, `rating`/`stars`, `date`/`created_at`, `category`/`product_category`, and `expected_sentiment`/`label`/`ground_truth_sentiment` for optional evaluation.

```csv
review_id,review_text,rating,date,category
R001,"The product quality is excellent",5,2026-10-10,Electronics
R002,"Delivery was extremely slow",2,2026-10-11,Electronics
R003,"Customer support was disappointing",1,2026-10-12,Home
```

Optional columns: `review_id`/`id`, `rating`/`stars`, `date`/`created_at`, `category`/`product_category`, and `expected_sentiment`/`label`/`ground_truth_sentiment` for optional evaluation.

### Optional local sentence-transformer embeddings

The default similarity discovery uses TF-IDF. To use semantic embeddings, install the optional package and point the backend at a model directory that is already present on the machine; the app does not download models at runtime:

```bash
pip install "sentence-transformers>=3,<6"
export SENTIMENTIQ_EMBEDDING_MODEL=/path/to/local/sentence-transformer
```

For Windows PowerShell, set the environment variable with `$env:SENTIMENTIQ_EMBEDDING_MODEL="C:\path\to\local\model"`. If the model cannot load, the analyzer falls back to TF-IDF similarity.

## Tests


```bash
cd backend
python -m pytest -q
```

The test suite covers baseline analysis, emotion cues, priority scoring, duplicate detection, repeated-term discovery, multilingual sentiment/topic hints, similar-review clustering, labelled evaluation metrics, registration/login, protected routes, CSV upload persistence, Excel `.xlsx` upload, topic-level sentiment evidence, unsupported file rejection and cross-workspace access isolation, competitive benchmark aggregation and competitor dataset isolation, PDF generation, workspace-scoped report downloads, schedule creation, manual report runs, retained delivery downloads and UTC recurrence calculation.

## Important limitations before production customer data

- This is an MVP foundation, not a production security certification. Arrange a security review before storing sensitive or regulated customer data.
- Email verification, password reset, MFA, invitations, account recovery, billing and centralized abuse monitoring are not implemented. Rate limiting is currently per-process and should be replaced or augmented with a shared edge limiter before horizontal scaling.
- Workspace role values are stored, but a full role/permission matrix and team invitation management are not implemented.
- The browser stores the short-lived bearer token in `sessionStorage`. A production frontend should consider a same-site, secure, HttpOnly cookie architecture and a stricter Content Security Policy.
- Configure TLS, strong unique secrets, managed database backups, restore drills, monitoring and restricted database/network access in the hosting environment.
- Emotion labels are keyword cues, not validated psychological measurements. Priority scores are rule-based triage aids, not calibrated risk scores. Exact duplicate matching misses paraphrases. Repeated terms are exploratory and are not statistically validated emerging topics. Human review is required before acting on these signals.
- The sentiment classifier is a VADER or multilingual lexicon/rule-based baseline, not a trained domain-specific model. Its absolute compound score is not a calibrated probability. Topic detection uses an explainable keyword taxonomy, not unsupervised topic modelling. Topic-level sentiment scores the sentence(s) that match each topic; it is an explainable heuristic, not a trained aspect-based sentiment model. Sarcasm, code-switching, dialects, implicit references and nuanced multilingual context remain limitations.
- Evaluation metrics are produced only when user-supplied labels are included. The included small template is illustrative, not a benchmark. Use a representative held-out, human-labelled dataset before making accuracy claims.
- The frontend still loads React/HTM and fonts from public CDNs; bundle and self-host dependencies for a hardened offline/controlled production deployment.
- No public cloud deployment has been performed by this build process. Docker Compose is configured, but requires a machine with Docker and your own production secrets/domain/TLS setup. Follow `docs/SECURITY_OPERATIONS.md` before launch.
- The scheduled-report worker currently runs in the FastAPI process and is designed for a single backend instance. Before horizontal scaling, move scheduling to a dedicated worker with a shared job queue or database locking. SMTP delivery has not been tested against a real provider in this environment.

### Iteration 2 SQLite data note

If the existing Iteration 2 SQLite database is detected, the old unscoped `analyses` table is renamed to `legacy_analyses` so its records are preserved for manual recovery. Those historical rows are not automatically assigned to a workspace because their original owner is unknown. Back up the database before upgrading.

## Production deployment with automatic HTTPS

See `docs/LAUNCH_RUNBOOK.md`. The production topology is started with `docker compose -f docker-compose.production.yml up --build -d` after `.env` is configured and the domain points to the host. Do not use the development `docker-compose.yml` as the public ingress configuration.
