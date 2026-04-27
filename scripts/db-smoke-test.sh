#!/usr/bin/env bash
set -euo pipefail

# Postgres smoke test.
#
# Requires POSTGRES_* vars to be exported in the current shell. Either:
#   set -a && source .env.docker && set +a && bash scripts/db-smoke-test.sh
# or run via the Makefile, which sources the env file for you:
#   make smoke-db
#
# Host prerequisite: `psql` on PATH. On macOS:
#   brew install libpq && brew link --force libpq

# In-container check: proves the daemon is up
docker exec studyverify-postgres pg_isready -U "${POSTGRES_USER:-studyverify}"

# Host check: proves the published port + auth round-trip work
PGPASSWORD="${POSTGRES_PASSWORD}" psql \
  -h localhost \
  -p "${POSTGRES_PORT:-5432}" \
  -U "${POSTGRES_USER:-studyverify}" \
  -d "${POSTGRES_DB:-studyverify}" \
  -c "SELECT version();"

echo "Postgres smoke test passed"
