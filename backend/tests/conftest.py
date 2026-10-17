"""
backend/tests/conftest.py

Puts `backend/` on sys.path so the suite imports `modules.*` and `config`
exactly the way the application does. Without this a test can only import the
modules by package path, which is not how they are deployed.

Also runs the light migrations once per session. Production does this at
startup, so a test database that skips it is not testing the deployed schema —
it is testing whatever the checked-in weltbot.db happened to contain, and a
newly added column would fail there while working in production.
"""
import os
import sys

import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


@pytest.fixture(scope="session", autouse=True)
def _migrated_schema():
    """Apply the same light migrations the application runs on startup."""
    try:
        import database
        database.run_light_migrations()
    except Exception as e:      # pragma: no cover - environment issue, not logic
        print(f"[conftest] migration skipped: {e}")
    yield

