"""Unit tests. They use an in-memory fake store, so no database is needed."""
import unittest

from app import ConfigError, create_app, load_config


class MemoryStore:
    """A fake store with the same methods as PostgresStore."""

    def __init__(self, healthy=True):
        self.tasks = []
        self.healthy = healthy

    def add(self, title):
        task = {"id": len(self.tasks) + 1, "title": title, "done": False}
        self.tasks.append(task)
        return dict(task)

    def list(self):
        return [dict(t) for t in self.tasks]

    def mark_done(self, task_id):
        for task in self.tasks:
            if task["id"] == task_id:
                task["done"] = True
                return dict(task)
        return None

    def ping(self):
        return self.healthy


class ConfigTests(unittest.TestCase):
    def test_password_is_required(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config({})
        self.assertIn("DB_PASSWORD", str(ctx.exception))

    def test_defaults(self):
        cfg = load_config({"DB_PASSWORD": "secret"})
        self.assertEqual(cfg["app_port"], 5000)
        self.assertEqual(cfg["db_port"], 5432)
        self.assertEqual(cfg["db_name"], "tasks")
        self.assertEqual(cfg["app_env"], "dev")

    def test_values_come_from_environment(self):
        cfg = load_config(
            {"DB_PASSWORD": "x", "DB_HOST": "db1", "APP_ENV": "prod", "APP_PORT": "8080"}
        )
        self.assertEqual(cfg["db_host"], "db1")
        self.assertEqual(cfg["app_env"], "prod")
        self.assertEqual(cfg["app_port"], 8080)

    def test_bad_port_is_rejected(self):
        with self.assertRaises(ConfigError):
            load_config({"DB_PASSWORD": "x", "APP_PORT": "lots"})
        with self.assertRaises(ConfigError):
            load_config({"DB_PASSWORD": "x", "DB_PORT": "70000"})


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.client = create_app(store=self.store).test_client()

    def test_health_ok(self):
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "ok")

    def test_health_unhealthy_when_database_is_down(self):
        self.store.healthy = False
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.get_json()["status"], "unhealthy")

    def test_create_task(self):
        res = self.client.post("/tasks", json={"title": "  Buy milk  "})
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.get_json(), {"id": 1, "title": "Buy milk", "done": False})

    def test_create_task_rejects_bad_input(self):
        for body in ({}, {"title": ""}, {"title": "   "}, {"title": 5}, {"title": "x" * 201}):
            res = self.client.post("/tasks", json=body)
            self.assertEqual(res.status_code, 400, body)
        res = self.client.post("/tasks", data="not json", content_type="text/plain")
        self.assertEqual(res.status_code, 400)

    def test_list_tasks(self):
        self.client.post("/tasks", json={"title": "A"})
        self.client.post("/tasks", json={"title": "B"})
        data = self.client.get("/tasks").get_json()
        self.assertEqual(data["count"], 2)
        self.assertEqual([t["title"] for t in data["tasks"]], ["A", "B"])

    def test_mark_done(self):
        self.client.post("/tasks", json={"title": "A"})
        res = self.client.put("/tasks/1/done")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["done"])

    def test_mark_done_unknown_task(self):
        res = self.client.put("/tasks/99/done")
        self.assertEqual(res.status_code, 404)

    def test_unknown_route_returns_json(self):
        res = self.client.get("/nope")
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.get_json(), {"error": "not found"})


if __name__ == "__main__":
    unittest.main()
