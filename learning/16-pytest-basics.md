# Primer 16 (part 1): pytest basics

**Analogy:** a test is a smoke alarm. You install it once, and it shouts
whenever someone accidentally breaks the thing it guards, even months later.

## How pytest finds tests

Files named `test_*.py`, containing functions named `test_*`. Inside, plain
`assert` statements: if one is false, the test fails and pytest shows both
values.

```python
def test_live_returns_ok(client):
    response = client.get("/health/live")
    assert response.status_code == 200
```

## Fixtures

A **fixture** is a reusable piece of setup that pytest passes in by matching
the parameter name. `client` in `tests/unit/test_health.py` starts the app
(including its lifespan) and hands each test a `TestClient`.

`conftest.py` is loaded automatically before tests run. Ours points the app at
port 1, where nothing listens, so unit tests can never touch real services.

## monkeypatch

`monkeypatch.setattr(module, "name", replacement)` swaps something out **for
one test only**, then puts it back. We use it to pretend Redis is down without
stopping it.

## TestClient

`TestClient(app)` sends fake HTTP requests straight into the app, with no real
server or port. It needs the `httpx` library.

## Run them

```
uv run python -m pytest -v
```

On this Windows machine, use `python -m pytest`, not `pytest`, because Smart
App Control blocks the `.exe` launcher.

Part 2 (pytest-asyncio and testcontainers, for real Postgres and Redis in
tests) comes with the integration tests.
