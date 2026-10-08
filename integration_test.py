"""Integration test: runs the real app against a real PostgreSQL database.

The pipeline runs this inside the freshly built image, on the same Docker
network as a throwaway Postgres container. Exit code 0 = pass, 1 = fail.
"""
import sys

from app import ConfigError, create_app


def check(condition, message):
    if not condition:
        print(f"FAIL: {message}")
        sys.exit(1)
    print(f"ok:   {message}")


def main():
    try:
        client = create_app().test_client()
    except ConfigError as err:
        print(f"ERROR: {err}")
        sys.exit(1)
    except Exception as err:  # for example: database unreachable
        print(f"ERROR: could not start the app: {err}")
        sys.exit(1)

    res = client.get("/health")
    check(res.status_code == 200 and res.get_json()["status"] == "ok", "GET /health is ok")

    res = client.get("/tasks")
    check(res.status_code == 200 and res.get_json()["count"] == 0, "database starts empty")

    res = client.post("/tasks", json={"title": "Write integration test"})
    check(res.status_code == 201, "POST /tasks returns 201")
    task = res.get_json()
    check(task["done"] is False and task["id"] > 0, "new task is not done and has an id")

    res = client.get("/tasks")
    tasks = res.get_json()["tasks"]
    check(len(tasks) == 1 and tasks[0]["title"] == "Write integration test", "task is listed")

    res = client.put(f"/tasks/{task['id']}/done")
    check(res.status_code == 200 and res.get_json()["done"] is True, "task is marked done")

    res = client.get("/tasks")
    check(res.get_json()["tasks"][0]["done"] is True, "done state was saved in the database")

    check(client.put("/tasks/999999/done").status_code == 404, "unknown task returns 404")
    check(client.post("/tasks", json={"title": ""}).status_code == 400, "empty title returns 400")

    print("All integration checks passed")


if __name__ == "__main__":
    main()
