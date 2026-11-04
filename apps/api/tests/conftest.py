"""Test fixtures: fresh SQLite database per session, seeded demo data, authenticated clients per role."""
from __future__ import annotations

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

_tmp = tempfile.mkdtemp(prefix="kifaru-test-")
os.environ["KIFARU_ENV"] = "test"
os.environ["KIFARU_DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["KIFARU_JWT_SECRET"] = "test-secret-at-least-16-chars"
os.environ["KIFARU_AUDIT_SAMPLE_RATE"] = "0.0"
os.environ["KIFARU_RATE_LIMIT_PER_MINUTE"] = "100000"

from kifaru.config import get_settings  # noqa: E402

get_settings.cache_clear()

from kifaru.db import reset_engine  # noqa: E402
from kifaru.main import create_app  # noqa: E402
from kifaru.seed import DEMO_PASSWORD, seed  # noqa: E402


@pytest.fixture(scope="session")
def app():
    reset_engine()
    seed(verbose=False)
    return create_app()


@pytest.fixture(scope="session")
def client(app):
    with TestClient(app) as c:
        yield c


def _login(client: TestClient, email: str) -> dict:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": DEMO_PASSWORD})
    assert r.status_code == 200, r.text
    tok = r.json()
    return {"Authorization": f"Bearer {tok['access_token']}", "_refresh": tok["refresh_token"], "_user_id": tok["user_id"], "_org": tok["org_id"]}


@pytest.fixture(scope="session")
def admin(client):
    return _login(client, "admin@demo.invalid")


@pytest.fixture(scope="session")
def operator(client):
    return _login(client, "operator@demo.invalid")


@pytest.fixture(scope="session")
def transporter(client):
    return _login(client, "dispatch@transporter-a.invalid")


@pytest.fixture(scope="session")
def other_transporter(client):
    return _login(client, "dispatch@transporter-b.invalid")


@pytest.fixture(scope="session")
def cargo_owner(client):
    return _login(client, "owner@cargo-a.invalid")


@pytest.fixture(scope="session")
def auditor(client):
    return _login(client, "auditor@demo.invalid")


def h(auth: dict) -> dict:
    return {"Authorization": auth["Authorization"]}
