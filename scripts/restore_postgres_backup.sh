#!/usr/bin/env bash
# Restore a pg_dumpall/pg_dump SQL file into the docker-compose postgres
# service, then bring the schema up to the current Alembic head.
#
# NDA NOTE: a real backup of this project's dev database will contain
# TrueData-sourced candle rows (market_candles.source = 'truedata'). Per the
# project's hard rule, that data never gets pushed to GitHub or baked into a
# Docker image. This script only bind-mounts/streams the file into a running
# container -- it is never COPYed by any Dockerfile, and *.sql / backups/ are
# gitignored at the repo root. Keep the dump file itself out of version
# control, full stop.
#
# Usage: scripts/restore_postgres_backup.sh /path/to/backup.sql
#
# What this does NOT do: it does not verify the dump's internal consistency
# (checksums, row counts, FK integrity) beyond what psql/Postgres itself
# enforces while replaying it -- V3 Phase 11's restore-rehearsal checklist
# (checksum, format/version, roles/extensions, sequences, foreign keys,
# counts, coverage) still needs a human pass over the output below.

set -euo pipefail

DUMP_FILE="${1:?Usage: $0 /path/to/backup.sql}"
COMPOSE_PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ ! -f "$DUMP_FILE" ]; then
    echo "error: dump file not found: $DUMP_FILE" >&2
    exit 1
fi

cd "$COMPOSE_PROJECT_DIR"

echo "== bringing up postgres only =="
docker compose up -d postgres
docker compose exec -T postgres bash -c 'until pg_isready -U postgres; do sleep 1; done'

echo "== restoring $DUMP_FILE (this is a full pg_dumpall -- includes roles + every database in the dump, not just equity_research) =="
docker compose exec -T postgres psql -U postgres -v ON_ERROR_STOP=1 < "$DUMP_FILE"

echo "== current alembic_version in the restored equity_research DB =="
docker compose exec -T postgres psql -U postgres -d equity_research -t -c \
    "SELECT version_num FROM alembic_version;"

echo "== running alembic upgrade head against the restored database =="
docker compose run --rm backend alembic upgrade head

echo "== post-restore sanity counts (compare against your own record of what the dump should contain) =="
docker compose exec -T postgres psql -U postgres -d equity_research -c "
SELECT 'market_candles' AS table, count(*) FROM market_candles
UNION ALL SELECT 'instruments', count(*) FROM instruments
UNION ALL SELECT 'recommendations', count(*) FROM recommendations
UNION ALL SELECT 'users', count(*) FROM users;
"

echo "== done. Restore rehearsal checklist still to do by hand (V3 Phase 11 / section 22): =="
echo "   - confirm row counts above match what you expected from the source system"
echo "   - spot-check a few foreign-key relationships (e.g. a recommendation's instrument_id resolves)"
echo "   - confirm sequences/extensions (pgcrypto) are present: \\dx in psql"
echo "   - never commit or push $DUMP_FILE -- it is gitignored, keep it that way"
