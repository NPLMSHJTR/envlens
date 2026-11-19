"""Minimal demo app: reads four variables and one dynamic key."""

from __future__ import annotations

import os

DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
SENTRY_DSN = os.getenv("SENTRY_DSN")

# The key name comes from configuration, so it cannot be resolved statically.
_selected = os.environ["PROFILE_NAME"]
DYNAMIC = os.environ[_selected]
