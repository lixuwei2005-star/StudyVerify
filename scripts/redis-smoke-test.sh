#!/usr/bin/env bash
set -euo pipefail

# Redis smoke test.
#
# Requires REDIS_* vars to be exported in the current shell. Either:
#   set -a && source .env.docker && set +a && bash scripts/redis-smoke-test.sh
# or run via the Makefile, which sources the env file for you:
#   make smoke-redis
#
# Host prerequisite: `redis-cli` on PATH. On macOS:
#   brew install redis

# In-container PING
docker exec studyverify-redis redis-cli -a "${REDIS_PASSWORD}" --no-auth-warning ping

# Host SET/GET/DEL roundtrip
KEY="smoke-test"
VAL="hello-$(date +%s)"

redis-cli -h localhost -p "${REDIS_PORT:-6379}" -a "${REDIS_PASSWORD}" --no-auth-warning \
  SET "$KEY" "$VAL"
redis-cli -h localhost -p "${REDIS_PORT:-6379}" -a "${REDIS_PASSWORD}" --no-auth-warning \
  GET "$KEY"
redis-cli -h localhost -p "${REDIS_PORT:-6379}" -a "${REDIS_PASSWORD}" --no-auth-warning \
  DEL "$KEY"

echo "Redis smoke test passed"
