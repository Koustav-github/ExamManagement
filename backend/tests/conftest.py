"""Shared pytest fixtures.

Requires TEST_DATABASE_URL pointing to a separate Postgres database. The test
suite WIPES the public schema of that DB at session start — never point it at
your real Neon URL.
"""
import os
import sys
from pathlib import Path

# Make backend/ importable and force HTTP cookies (Secure would block the
# refresh cookie over the test client's http:// scheme).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["SECURE_COOKIES"] = "false"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from database import Base, get_database
import models
from main import app, hash_password


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    raise RuntimeError(
        "TEST_DATABASE_URL env var not set — point it at a DEDICATED test DB."
    )
if TEST_DATABASE_URL == os.getenv("DATABASE_URL"):
    raise RuntimeError("TEST_DATABASE_URL must differ from DATABASE_URL.")

engine = create_engine(TEST_DATABASE_URL)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session", autouse=True)
def create_schema():
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    Base.metadata.create_all(bind=engine)
    yield
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))


@pytest.fixture(autouse=True)
def truncate_tables():
    names = [t.name for t in reversed(Base.metadata.sorted_tables)]
    with engine.begin() as conn:
        conn.execute(
            text(f"TRUNCATE TABLE {', '.join(names)} RESTART IDENTITY CASCADE")
        )
    yield


def _override_get_database():
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    app.dependency_overrides[get_database] = _override_get_database
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def db():
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def super_admin(db):
    admin = models.Admins(
        name="Super",
        admin_id="SA001",
        email_id="super@test.com",
        mobile_number="0000000000",
        password_hash=hash_password("super-pass"),
        super_admin=True,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


@pytest.fixture
def admin_headers(client, super_admin):
    resp = client.post(
        "/user/signin",
        json={
            "email": "super@test.com",
            "password": "super-pass",
            "role": "admin",
        },
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}
