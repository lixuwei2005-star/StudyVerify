# Docker Runbook — Postgres + Redis

Local infra for StudyVerify dev: Postgres 16 + Redis 7 in containers, FastAPI runs on the host.

## Prerequisites

- Docker Desktop (Compose v2: `docker compose`, NOT `docker-compose`).
- Host CLIs for the smoke tests:
  ```bash
  brew install libpq redis
  brew link --force libpq   # libpq is keg-only; this puts psql on PATH
  ```

## First-time setup

```bash
cp .env.docker.example .env.docker
# Replace BOTH passwords with strong randoms:
#   POSTGRES_PASSWORD=$(openssl rand -base64 24)
#   REDIS_PASSWORD=$(openssl rand -base64 24)
# Edit .env.docker by hand, or regenerate with:
#   sed -i '' "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(openssl rand -base64 24)|" .env.docker
#   sed -i '' "s|^REDIS_PASSWORD=.*|REDIS_PASSWORD=$(openssl rand -base64 24)|"       .env.docker

make compose-config   # sanity-check vars resolve
docker compose --env-file .env.docker pull
make compose-up
make smoke-all
```

Verify `git check-ignore -v .env.docker` prints the matching ignore rule before you put real secrets in there.

## Daily commands

| Action | Command |
| --- | --- |
| Start services | `make compose-up` |
| Stop (keep data) | `make compose-down` |
| Tail all logs | `make compose-logs` |
| Status | `make compose-ps` |
| Resolved config | `make compose-config` |
| Smoke tests | `make smoke-all` |

All wrap `docker compose --env-file .env.docker …`.

## Connect interactively

```bash
# Postgres
docker exec -it studyverify-postgres psql -U studyverify

# Redis (password comes from your shell env)
set -a && source .env.docker && set +a
docker exec -it studyverify-redis redis-cli -a "$REDIS_PASSWORD"
```

## Logs for one service

```bash
docker compose --env-file .env.docker logs -f postgres
docker compose --env-file .env.docker logs -f redis
```

## Reset all data (DESTRUCTIVE)

```bash
make compose-down-volumes   # prompts for "yes"
make compose-up             # re-creates fresh volumes
```

`compose-down-volumes` is interactive only — do NOT call it from CI. CI should invoke `docker compose --env-file .env.docker down -v` directly.

## Smoke tests

The `make` targets source `.env.docker` for you. To run the scripts directly:

```bash
set -a && source .env.docker && set +a
bash scripts/db-smoke-test.sh
bash scripts/redis-smoke-test.sh
```

## Production nginx timeout configuration

The Oracle VM runs nginx as a reverse proxy in front of the FastAPI container
(`127.0.0.1:8000`). nginx config is managed by BaoTa panel at:

```text
/www/server/panel/vhost/nginx/proxy/api.005917.xyz/*.conf
```

The proxy location block MUST include extended timeouts, because LLM-backed
endpoints (`/solve`, `/verify`, `/hint`, `/generate-test-cases`) can exceed
nginx's default 60s `proxy_read_timeout`:

```nginx
location ^~ /
{
    proxy_pass http://127.0.0.1:8000;
    proxy_connect_timeout 75s;
    proxy_send_timeout 300s;
    proxy_read_timeout 300s;
    ...
}
```

Without these, intermittent 504 Gateway Timeout occurs on slow LLM calls.
Diagnosed in Step 13 from nginx `error.log`:
`upstream timed out (110: Connection timed out) while reading response header
from upstream` -- roughly 80 occurrences over a week, almost all on
`/api/v1/hint`.

After editing, validate and reload:

```bash
nginx -t
nginx -s reload
```

## Troubleshooting

- **Port 5432 / 6379 already in use** — something else (Postgres.app, system Redis) is bound. Diagnose with `lsof -nP -i :5432 -i :6379`. Either stop the conflicting service or bump `POSTGRES_PORT` / `REDIS_PORT` in `.env.docker` and `make compose-up` again. No code change needed.
- **`POSTGRES_PASSWORD required` on `make compose-config`** — the env-file isn't being loaded. Ensure you're using the Makefile or passing `--env-file .env.docker` explicitly; bare `docker compose config` reads `.env`, not `.env.docker`.
- **Container restarts in a loop** — check `docker compose --env-file .env.docker logs <service>`. Common causes: corrupted volume after a crash (`make compose-down-volumes` and re-up), or password mismatch after rotating the env file (volume retains the old password — wipe with `down -v`).
- **`platform mismatch` on Apple Silicon** — both `postgres:16-alpine` and `redis:7-alpine` ship native arm64; check `docker version` shows `arm64`. If not, reinstall Docker Desktop.
- **`psql: command not found`** — finish the `brew link --force libpq` step from prerequisites.
