"""Task Tracker API.

A tiny Flask REST API that stores tasks in PostgreSQL.
All settings come from environment variables, nothing is hard-coded.
"""
import os
import sys
import time

from flask import Flask, jsonify, request


class ConfigError(Exception):
    """Raised when an environment variable is missing or invalid."""


def load_config(env=None):
    """Read settings from environment variables (or from a dict, for tests)."""
    env = os.environ if env is None else env

    password = env.get("DB_PASSWORD", "")
    if not password:
        raise ConfigError("DB_PASSWORD is required")

    def as_port(name, default):
        raw = env.get(name, default)
        try:
            value = int(raw)
        except ValueError:
            raise ConfigError(f"{name} must be a number, got '{raw}'")
        if not 1 <= value <= 65535:
            raise ConfigError(f"{name} must be between 1 and 65535, got {value}")
        return value

    return {
        "app_env": env.get("APP_ENV", "dev"),
        "app_port": as_port("APP_PORT", "5000"),
        "db_host": env.get("DB_HOST", "localhost"),
        "db_port": as_port("DB_PORT", "5432"),
        "db_name": env.get("DB_NAME", "tasks"),
        "db_user": env.get("DB_USER", "postgres"),
        "db_password": password,
    }


class PostgresStore:
    """Stores tasks in PostgreSQL. Retries the first connection, because the
    database container may still be starting when the app starts."""

    def __init__(self, config, retries=30, delay=1.0):
        import psycopg2  # imported here so unit tests do not need it

        self._psycopg2 = psycopg2
        self._dsn = {
            "host": config["db_host"],
            "port": config["db_port"],
            "dbname": config["db_name"],
            "user": config["db_user"],
            "password": config["db_password"],
        }
        self._wait_for_database(retries, delay)
        self._create_table()

    def _connect(self):
        return self._psycopg2.connect(connect_timeout=3, **self._dsn)

    def _wait_for_database(self, retries, delay):
        last_error = None
        for attempt in range(1, retries + 1):
            try:
                self._connect().close()
                return
            except self._psycopg2.OperationalError as err:
                last_error = err
                print(f"Waiting for database ({attempt}/{retries})...", file=sys.stderr)
                time.sleep(delay)
        raise RuntimeError(f"Could not connect to the database: {last_error}")

    def _query(self, sql, params=(), fetch="all"):
        conn = self._connect()
        try:
            with conn:  # commits on success, rolls back on error
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    if fetch == "all":
                        return cur.fetchall()
                    if fetch == "one":
                        return cur.fetchone()
                    return None
        finally:
            conn.close()

    def _create_table(self):
        self._query(
            """CREATE TABLE IF NOT EXISTS tasks (
                   id SERIAL PRIMARY KEY,
                   title TEXT NOT NULL,
                   done BOOLEAN NOT NULL DEFAULT FALSE,
                   created_at TIMESTAMPTZ NOT NULL DEFAULT now()
               )""",
            fetch=None,
        )

    @staticmethod
    def _as_dict(row):
        return {"id": row[0], "title": row[1], "done": row[2]}

    def add(self, title):
        row = self._query(
            "INSERT INTO tasks (title) VALUES (%s) RETURNING id, title, done",
            (title,),
            fetch="one",
        )
        return self._as_dict(row)

    def list(self):
        rows = self._query("SELECT id, title, done FROM tasks ORDER BY id")
        return [self._as_dict(r) for r in rows]

    def mark_done(self, task_id):
        row = self._query(
            "UPDATE tasks SET done = TRUE WHERE id = %s RETURNING id, title, done",
            (task_id,),
            fetch="one",
        )
        return self._as_dict(row) if row else None

    def ping(self):
        try:
            self._query("SELECT 1", fetch="one")
            return True
        except Exception:
            return False


def create_app(store=None, config=None):
    """Build the Flask app. Tests pass in a fake store; production uses Postgres."""
    if config is None:
        config = {"app_env": "test"} if store is not None else load_config()
    if store is None:
        store = PostgresStore(config)

    app = Flask(__name__)

    @app.get("/health")
    def health():
        if store.ping():
            return jsonify(status="ok", env=config["app_env"])
        return jsonify(status="unhealthy", env=config["app_env"]), 503

    @app.post("/tasks")
    def add_task():
        data = request.get_json(silent=True) or {}
        title = data.get("title")
        if not isinstance(title, str) or not title.strip():
            return jsonify(error="title is required"), 400
        title = title.strip()
        if len(title) > 200:
            return jsonify(error="title must be 200 characters or fewer"), 400
        return jsonify(store.add(title)), 201

    @app.get("/tasks")
    def list_tasks():
        tasks = store.list()
        return jsonify(tasks=tasks, count=len(tasks))

    @app.put("/tasks/<int:task_id>/done")
    def finish_task(task_id):
        task = store.mark_done(task_id)
        if task is None:
            return jsonify(error=f"task {task_id} not found"), 404
        return jsonify(task)

    @app.errorhandler(404)
    def not_found(_err):
        return jsonify(error="not found"), 404

    return app
