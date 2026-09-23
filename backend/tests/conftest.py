"""Test configuration.

The app lifespan constructs `Settings` from the environment, so the required
variables must exist before any app is built. `setdefault` keeps a real
environment (if a developer exports their own) authoritative; these point
nowhere live — tests needing a real dependency stub it.
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:5432/twinlab")
os.environ.setdefault("CLAB_API_URL", "http://localhost:8090")
os.environ.setdefault("CLAB_API_USERNAME", "tester")
os.environ.setdefault("CLAB_API_PASSWORD", "secret")
os.environ.setdefault("NETLAB_RUNNER_URL", "http://localhost:8001")
os.environ.setdefault("BOOTSTRAP_ADMIN_USERNAME", "admin")
os.environ.setdefault("BOOTSTRAP_ADMIN_PASSWORD", "admin-secret")
os.environ.setdefault("BOOTSTRAP_ADMIN_EMAIL", "admin@example.com")
os.environ.setdefault("FRONTEND_BASE_PATH", "")
