"""Shared pytest setup, loaded automatically before any test file.

Points the app at addresses where nothing listens (port 1), so unit tests can
never touch your real Postgres or Redis. This must run before `app.main` is
imported, because settings are read at import time.
"""

import os

# Plain assignment (not setdefault), so values already in your shell can't
# leak real services into the tests.
os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://test:test@127.0.0.1:1/test"
os.environ["REDIS_URL"] = "redis://:test@127.0.0.1:1/0"
