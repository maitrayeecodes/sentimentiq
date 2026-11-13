#!/usr/bin/env sh
set -eu
: "${DATABASE_URL:?Set DATABASE_URL}"
: "${BACKUP_DIR:=./backups}"
mkdir -p "$BACKUP_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
# DATABASE_URL must be a PostgreSQL URL. pg_dump reads credentials via PGPASSWORD/.pgpass.
DB_URL="$(printf "%s" "$DATABASE_URL" | sed 's#^postgresql+psycopg://#postgresql://#')"
pg_dump --format=custom --no-owner --no-acl "$DB_URL" > "$BACKUP_DIR/sentimentiq-$STAMP.dump"
chmod 600 "$BACKUP_DIR/sentimentiq-$STAMP.dump"
echo "$BACKUP_DIR/sentimentiq-$STAMP.dump"
