#!/usr/bin/env sh
set -eu
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"
printf '\n== Python compilation ==\n'
python -m compileall -q backend/app backend/migrations
printf '\n== Backend tests ==\n'
(cd backend && python -m pytest -q)
printf '\n== Frontend syntax ==\n'
node --check js/app.js
printf '\n== Production environment preflight ==\n'
if [ -f .env ]; then
  python scripts/preflight.py --env-file .env
else
  echo 'SKIP: .env not present; copy .env.production.example to .env and run preflight.'
fi
printf '\n== Compose validation ==\n'
if command -v docker >/dev/null 2>&1; then
  docker compose -f docker-compose.production.yml config -q
  echo 'PASS: production Compose configuration parsed.'
else
  echo 'SKIP: Docker is not installed; Compose runtime was not tested.'
fi
printf '\nRelease checks completed. A successful local check is not a public deployment or security certification.\n'
