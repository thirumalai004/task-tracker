# Task Tracker: Jenkins + Docker pipeline project

A small real-time web app (Flask + PostgreSQL). Open it in two browser tabs and
watch changes appear in both instantly. Jenkins builds it,
tests it against a throwaway database, tags it with the build number, deploys
it as `dev` or `prod`, health-checks it, and rolls back if the new version is unhealthy.

## Structure

```
task-tracker/
├── app.py                # Flask API, live-update broker (SSE), PostgreSQL store, env-var config
├── static/index.html     # the web page (live list, no refresh needed)
├── test_app.py           # unit tests (fake store, no database)
├── integration_test.py   # runs the real app against a real Postgres
├── requirements.txt
├── Dockerfile            # stages: base -> test -> final (HEALTHCHECK included)
├── deploy.sh             # network + volume + database + app + health check + rollback
├── Jenkinsfile           # the pipeline
├── .dockerignore  .gitignore  .gitattributes
└── README.md
```

## API

| Method | Path | Result |
|---|---|---|
| GET | `/` | the web page |
| GET | `/events` | live stream (Server-Sent Events): `task_added`, `task_done`, `task_deleted`, `viewers` |
| GET | `/health` | `200 {"status":"ok"}`, or `503` if the database is unreachable |
| POST | `/tasks` | body `{"title":"Buy milk"}` -> `201` with the task; `400` if the title is empty or over 200 chars |
| GET | `/tasks` | `{"tasks":[...],"count":N}` |
| PUT | `/tasks/<id>/done` | the updated task, or `404` |
| DELETE | `/tasks/<id>` | `{"deleted": id}`, or `404` |

## Configuration (environment variables only)

| Variable | Default | Where the value comes from |
|---|---|---|
| `DB_PASSWORD` | none (required) | Jenkins parameter, passed by `deploy.sh` to both containers |
| `DB_HOST` | `db` | `deploy.sh` sets it to `tt-<env>-db` |
| `APP_ENV` | `dev` | `deploy.sh` sets it to the chosen environment |
| `APP_PORT` | `5000` | Dockerfile `ENV` (container side) |
| `DB_NAME` / `DB_USER` / `DB_PORT` | `tasks` / `postgres` / `5432` | Dockerfile `ENV` |

| Environment | Host port | Containers | Volume |
|---|---|---|---|
| dev | 3301 | `tt-dev-app`, `tt-dev-db` | `tt-dev-data` |
| prod | 3302 | `tt-prod-app`, `tt-prod-db` | `tt-prod-data` |

## Run locally without Jenkins

```
python -m unittest -v                                   # unit tests (needs: pip install Flask)
docker build --target test -t task-tracker:test .
docker build -t task-tracker:1 .
set DB_PASSWORD=mypass                                  # Windows; use export on Linux/macOS
sh deploy.sh dev 1
curl.exe http://localhost:3301/health
```

## Jenkins setup

1. The Jenkins container needs the Docker CLI and the host's `/var/run/docker.sock`.
   Check with a job that runs `docker ps`.
2. New Item -> Pipeline -> `task-tracker` -> Pipeline script from SCM -> Git -> your repo, branch `*/main`, Script Path `Jenkinsfile`.
3. Build Now once (registers the parameters), then Build with Parameters.

## How the live updates work

1. The page opens `/events` with `EventSource`. The connection stays open.
2. Each open connection gets its own queue inside the app (`EventBroker`).
3. When anyone adds, completes or deletes a task, the app publishes an event to every queue
   and each browser receives it immediately.
4. If the connection drops (for example during a redeploy), the browser reconnects by itself
   and reloads the list, so nothing is missed.

Limits: the broker lives in one process's memory, so gunicorn runs one worker with 32 threads
(each open tab uses one thread). To run several app containers, replace the broker with
Redis pub/sub or PostgreSQL LISTEN/NOTIFY.

## Notes

- The database password is set only when the volume is first created. Changing
  `DB_PASSWORD` on a later deploy makes the app unable to connect, so the health
  check fails and the rollback runs. To reset: `docker rm -f tt-dev-db tt-dev-app && docker volume rm tt-dev-data`.
- `deploy.sh` passes the password with `docker run -e`, fine for learning. Real
  projects use Docker secrets or Jenkins credentials.
- `integration_test.py` ships inside the image so the pipeline can run it there.
