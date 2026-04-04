"""Shared test fixtures."""

import pytest
from app.scrim_db import init_db


@pytest.fixture(autouse=True, scope="session")
def setup_db():
    """Initialize the SQLite DB schema before any test that needs it."""
    init_db()
