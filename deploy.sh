#!/bin/sh
# Deploy one environment: ./deploy.sh <dev|prod> <image-tag>
# Needs: DB_PASSWORD in the environment. Optional: IMAGE (default task-tracker).
#
# 1. makes a private network and a data volume for the environment
# 2. starts PostgreSQL if it is not already running (data lives in the volume)
# 3. replaces the app container with the new image tag
# 4. waits for Docker's health check; if the app never becomes healthy,
#    removes it and restarts the previous version (rollback), then exits 1
set -eu

usage() {
  echo "Usage: DB_PASSWORD=... $0 <dev|prod> <image-tag>" >&2
  exit 2
}

ENVIRONMENT="${1:-}"
TAG="${2:-}"
IMAGE="${IMAGE:-task-tracker}"

case "$ENVIRONMENT" in
  dev)  PORT=3301 ;;
  prod) PORT=3302 ;;
  *)    usage ;;
esac
[ -n "$TAG" ] || usage
: "${DB_PASSWORD:?ERROR: DB_PASSWORD must be set}"

NET="tt-$ENVIRONMENT-net"
DB="tt-$ENVIRONMENT-db"
APP="tt-$ENVIRONMENT-app"
VOL="tt-$ENVIRONMENT-data"

if ! docker image inspect "$IMAGE:$TAG" >/dev/null 2>&1; then
  echo "ERROR: image $IMAGE:$TAG does not exist" >&2
  exit 1
fi

start_app() {
  docker rm -f "$APP" >/dev/null 2>&1 || true
  docker run -d --name "$APP" --network "$NET" --restart unless-stopped \
    -p "$PORT:5000" \
    -e APP_ENV="$ENVIRONMENT" \
    -e DB_HOST="$DB" \
    -e DB_PASSWORD="$DB_PASSWORD" \
    "$1" >/dev/null
}

wait_healthy() {
  n=0
  while [ "$n" -lt 40 ]; do
    running="$(docker inspect -f '{{.State.Running}}' "$APP" 2>/dev/null || echo false)"
    if [ "$running" != "true" ]; then
      return 1
    fi
    status="$(docker inspect -f '{{.State.Health.Status}}' "$APP" 2>/dev/null || echo unknown)"
    if [ "$status" = "healthy" ]; then
      return 0
    fi
    if [ "$status" = "unhealthy" ]; then
      return 1
    fi
    n=$((n + 1))
    sleep 2
  done
  return 1
}

# --- network, volume and database --------------------------------------
docker network inspect "$NET" >/dev/null 2>&1 || docker network create "$NET" >/dev/null

if [ -z "$(docker ps -aq -f "name=^${DB}\$")" ]; then
  echo "Starting database $DB (volume $VOL)"
  docker run -d --name "$DB" --network "$NET" --restart unless-stopped \
    -v "$VOL:/var/lib/postgresql/data" \
    -e POSTGRES_PASSWORD="$DB_PASSWORD" \
    -e POSTGRES_DB=tasks \
    postgres:16 >/dev/null
elif [ "$(docker inspect -f '{{.State.Running}}' "$DB")" != "true" ]; then
  echo "Restarting database $DB"
  docker start "$DB" >/dev/null
fi

# -h 127.0.0.1 matters: during first start Postgres runs a temporary server that
# only listens on a socket, and a plain pg_isready would report "ready" too early.
i=0
until docker exec "$DB" pg_isready -h 127.0.0.1 -U postgres >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -ge 30 ]; then
    echo "ERROR: database $DB did not become ready" >&2
    docker logs --tail 20 "$DB" >&2 || true
    exit 1
  fi
  sleep 2
done

# --- app: remember what is running, deploy the new tag, verify -----------
PREV=""
if docker inspect "$APP" >/dev/null 2>&1; then
  PREV="$(docker inspect -f '{{.Config.Image}}' "$APP")"
fi

echo "Deploying $IMAGE:$TAG to $ENVIRONMENT on port $PORT (previous: ${PREV:-none})"
start_app "$IMAGE:$TAG"

if wait_healthy; then
  echo "Deploy OK: $ENVIRONMENT is running $IMAGE:$TAG at http://localhost:$PORT"
  exit 0
fi

echo "ERROR: $IMAGE:$TAG is not healthy. Last log lines:" >&2
docker logs --tail 30 "$APP" >&2 || true

if [ -n "$PREV" ] && [ "$PREV" != "$IMAGE:$TAG" ]; then
  echo "Rolling back to $PREV" >&2
  start_app "$PREV"
  if wait_healthy; then
    echo "Rollback OK: $ENVIRONMENT is running $PREV again" >&2
  else
    echo "ERROR: rollback to $PREV is also unhealthy" >&2
  fi
else
  docker rm -f "$APP" >/dev/null 2>&1 || true
  echo "No previous version to roll back to; failed container removed" >&2
fi
exit 1
