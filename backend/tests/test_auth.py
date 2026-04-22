"""Auth flow tests: signin, refresh rotation, logout revocation."""
import models


def test_signin_valid_returns_access_and_sets_refresh_cookie(client, super_admin):
    resp = client.post(
        "/user/signin",
        json={
            "email": "super@test.com",
            "password": "super-pass",
            "role": "admin",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0
    assert "refresh_token" in resp.cookies


def test_signin_wrong_password_returns_401(client, super_admin):
    resp = client.post(
        "/user/signin",
        json={
            "email": "super@test.com",
            "password": "not-it",
            "role": "admin",
        },
    )
    assert resp.status_code == 401


def test_signin_nonexistent_user_returns_401(client):
    resp = client.post(
        "/user/signin",
        json={
            "email": "ghost@test.com",
            "password": "whatever",
            "role": "admin",
        },
    )
    assert resp.status_code == 401


def test_refresh_rotates_jti_and_returns_new_access(client, super_admin, db):
    signin = client.post(
        "/user/signin",
        json={
            "email": "super@test.com",
            "password": "super-pass",
            "role": "admin",
        },
    )
    assert signin.status_code == 200
    first_access = signin.json()["access_token"]

    db.refresh(super_admin)
    old_jti = super_admin.refresh_jti
    assert old_jti is not None

    resp = client.post("/auth/refresh")
    assert resp.status_code == 200, resp.text
    new_access = resp.json()["access_token"]
    assert new_access
    assert "refresh_token" in resp.cookies

    db.refresh(super_admin)
    assert super_admin.refresh_jti is not None
    assert super_admin.refresh_jti != old_jti


def test_refresh_without_cookie_returns_401(client):
    resp = client.post("/auth/refresh")
    assert resp.status_code == 401


def test_logout_revokes_refresh_and_blocks_subsequent_refresh(
    client, super_admin, db
):
    client.post(
        "/user/signin",
        json={
            "email": "super@test.com",
            "password": "super-pass",
            "role": "admin",
        },
    )
    db.refresh(super_admin)
    assert super_admin.refresh_jti is not None

    resp = client.post("/auth/logout")
    assert resp.status_code == 204

    db.refresh(super_admin)
    assert super_admin.refresh_jti is None

    followup = client.post("/auth/refresh")
    assert followup.status_code == 401
