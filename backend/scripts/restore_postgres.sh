#!/usr/bin/env sh
set -eu
: "${DATABASE_URL:?Set DATABASE_URL}"
: "${BACKUP_FILE:?Set BACKUP_FILE to a trusted .dump backup}"
[ -f "$BACKUP_FILE" ] || { echo "Backup file not found" >&2; exit 1; }
DB_URL="$(printf "%s" "$DATABASE_URL" | sed 's#^postgresql+psycopg://#postgresql://#')"
echo "WARNING: this replaces objects in the target database."
pg_restore --clean --if-exists --no-owner --no-acl --dbname "$DB_URL" "$BACKUP_FILE"
