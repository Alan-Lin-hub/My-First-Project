"""Tests for authentication + role-based access control.

Pure-unit tests cover password hashing, JWT, and the UserStore. Endpoint tests
use a TestClient with an isolated temp user DB and a stubbed RAG query (no
embedding/LLM needed for the auth checks, which short-circuit at the dependency
layer).
"""
from pathlib import Path

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

import auth
from auth import hash_password, verify_password, create_access_token, decode_token
from user_store import UserStore
from config import config

BACKEND_DIR = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# Password hashing
# --------------------------------------------------------------------------- #
def test_password_hash_roundtrip():
    h = hash_password("s3cret!")
    assert h != "s3cret!"                  # never stored in plaintext
    assert verify_password("s3cret!", h)
    assert not verify_password("wrong", h)


# --------------------------------------------------------------------------- #
# JWT
# --------------------------------------------------------------------------- #
def test_jwt_roundtrip(monkeypatch):
    monkeypatch.setattr(config, "JWT_SECRET", "test-secret")
    payload = decode_token(create_access_token("alice", "admin"))
    assert payload["sub"] == "alice"
    assert payload["role"] == "admin"


def test_jwt_tampered_rejected(monkeypatch):
    monkeypatch.setattr(config, "JWT_SECRET", "test-secret")
    token = create_access_token("alice", "user")
    with pytest.raises(pyjwt.PyJWTError):
        decode_token(token + "tampered")


def test_jwt_wrong_secret_rejected(monkeypatch):
    monkeypatch.setattr(config, "JWT_SECRET", "secret-a")
    token = create_access_token("alice", "user")
    monkeypatch.setattr(config, "JWT_SECRET", "secret-b")
    with pytest.raises(pyjwt.PyJWTError):
        decode_token(token)


# --------------------------------------------------------------------------- #
# UserStore
# --------------------------------------------------------------------------- #
@pytest.fixture
def store(tmp_path):
    return UserStore(str(tmp_path / "users.db"))


def test_create_and_verify_login(store):
    store.create_user("bob", "pw", "user")
    assert store.verify_login("bob", "pw")["role"] == "user"
    assert store.verify_login("bob", "nope") is None
    assert store.verify_login("ghost", "pw") is None


def test_duplicate_username_rejected(store):
    store.create_user("bob", "pw")
    with pytest.raises(ValueError):
        store.create_user("bob", "other")


def test_invalid_role_rejected(store):
    with pytest.raises(ValueError):
        store.create_user("bob", "pw", "superuser")


def test_seed_admin_idempotent(store):
    assert store.seed_admin("admin", "pw") is True
    assert store.count_admins() == 1
    assert store.seed_admin("admin", "pw") is False   # an admin already exists
    assert store.count_admins() == 1


def test_list_and_delete(store):
    u = store.create_user("bob", "pw")
    assert any(x["username"] == "bob" for x in store.list_users())
    assert store.delete_user(u["id"]) is True
    assert not any(x["username"] == "bob" for x in store.list_users())


def test_update_password(store):
    u = store.create_user("bob", "oldpw")
    assert store.update_password(u["id"], "newpw123") is True
    assert store.verify_login("bob", "oldpw") is None
    assert store.verify_login("bob", "newpw123")["username"] == "bob"


# --------------------------------------------------------------------------- #
# Endpoint role enforcement
# --------------------------------------------------------------------------- #
@pytest.fixture
def client(tmp_path, monkeypatch):
    # app.py uses cwd-relative paths ("../frontend", "../docs"); it expects to run
    # from backend/. Switch there before importing it.
    monkeypatch.chdir(BACKEND_DIR)
    # Patch config BEFORE importing app (its module-level objects read these).
    monkeypatch.setattr(config, "JWT_SECRET", "test-secret")
    monkeypatch.setattr(config, "USERS_DB_PATH", str(tmp_path / "users.db"))
    monkeypatch.setattr(config, "CHROMA_PATH", str(tmp_path / "chroma"))
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "test-key")

    import app as app_module

    store = UserStore(str(tmp_path / "users.db"))
    store.create_user("admin", "adminpw", "admin")
    store.create_user("regular", "userpw", "user")
    monkeypatch.setattr(app_module, "user_store", store)
    auth.set_user_store(store)

    # Stub the RAG query so the "regular user can query" test needs no LLM.
    monkeypatch.setattr(app_module.rag_system, "query", lambda q, sid=None: ("stub answer", []))

    # No `with` -> startup/lifespan events do not run (no doc load / re-seed).
    return TestClient(app_module.app)


def _bearer(username, role):
    return {"Authorization": f"Bearer {create_access_token(username, role)}"}


def test_login_success(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "adminpw"})
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "admin" and body["access_token"]


def test_login_wrong_password(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "bad"})
    assert r.status_code == 401


def test_me_requires_token(client):
    assert client.get("/api/auth/me").status_code == 401
    r = client.get("/api/auth/me", headers=_bearer("admin", "admin"))
    assert r.status_code == 200 and r.json()["role"] == "admin"


def test_query_requires_login(client):
    assert client.post("/api/query", json={"query": "hi"}).status_code == 401
    r = client.post("/api/query", json={"query": "hi"}, headers=_bearer("regular", "user"))
    assert r.status_code == 200
    assert r.json()["answer"] == "stub answer"


def test_courses_requires_login(client):
    assert client.get("/api/courses").status_code == 401


def test_upload_requires_admin(client):
    files = {"file": ("a.txt", b"Course Title: X\nhello", "text/plain")}
    # Unauthenticated -> 401
    assert client.post("/api/courses/upload", files=files).status_code == 401
    # Regular user -> 403 (rejected at the require_admin dependency, before ingest)
    r = client.post("/api/courses/upload", files=files, headers=_bearer("regular", "user"))
    assert r.status_code == 403


def test_admin_user_management(client):
    # Admin can create a user
    r = client.post(
        "/api/admin/users",
        json={"username": "newbie", "password": "pw", "role": "user"},
        headers=_bearer("admin", "admin"),
    )
    assert r.status_code == 201 and r.json()["username"] == "newbie"

    # Regular user cannot
    r2 = client.post(
        "/api/admin/users",
        json={"username": "x", "password": "pw"},
        headers=_bearer("regular", "user"),
    )
    assert r2.status_code == 403

    # Listing requires admin too
    assert client.get("/api/admin/users").status_code == 401
    assert client.get("/api/admin/users", headers=_bearer("admin", "admin")).status_code == 200


def test_change_own_password(client):
    r = client.post(
        "/api/auth/change-password",
        json={"old_password": "userpw", "new_password": "newpw123"},
        headers=_bearer("regular", "user"),
    )
    assert r.status_code == 204
    # Old password rejected, new one accepted
    assert client.post("/api/auth/login", json={"username": "regular", "password": "userpw"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "regular", "password": "newpw123"}).status_code == 200


def test_change_password_wrong_old(client):
    r = client.post(
        "/api/auth/change-password",
        json={"old_password": "WRONG", "new_password": "newpw123"},
        headers=_bearer("regular", "user"),
    )
    assert r.status_code == 400


def test_change_password_too_short(client):
    r = client.post(
        "/api/auth/change-password",
        json={"old_password": "userpw", "new_password": "123"},
        headers=_bearer("regular", "user"),
    )
    assert r.status_code == 400


def test_change_password_requires_auth(client):
    assert client.post(
        "/api/auth/change-password",
        json={"old_password": "x", "new_password": "yyyyyy"},
    ).status_code == 401


def test_admin_resets_user_password(client):
    users = client.get("/api/admin/users", headers=_bearer("admin", "admin")).json()
    uid = next(u["id"] for u in users if u["username"] == "regular")
    r = client.post(
        f"/api/admin/users/{uid}/password",
        json={"new_password": "reset123"},
        headers=_bearer("admin", "admin"),
    )
    assert r.status_code == 204
    assert client.post("/api/auth/login", json={"username": "regular", "password": "reset123"}).status_code == 200


def test_non_admin_cannot_reset_password(client):
    r = client.post(
        "/api/admin/users/1/password",
        json={"new_password": "reset123"},
        headers=_bearer("regular", "user"),
    )
    assert r.status_code == 403
