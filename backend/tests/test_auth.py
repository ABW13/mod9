"""Registration, login and protected-route behaviour."""


def test_register_returns_created_user(client):
    r = client.post(
        "/auth/register",
        json={"email": "new@example.com", "password": "hunter2hunter2"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "new@example.com"
    assert "id" in body
    # The hash must never leave the server.
    assert "hashed_password" not in body
    assert "password" not in body


def test_register_rejects_duplicate_email(client):
    payload = {"email": "dupe@example.com", "password": "hunter2hunter2"}
    assert client.post("/auth/register", json=payload).status_code == 201
    assert client.post("/auth/register", json=payload).status_code == 409


def test_register_rejects_short_password(client):
    r = client.post(
        "/auth/register",
        json={"email": "short@example.com", "password": "abc"},
    )
    assert r.status_code == 422


def test_login_returns_a_token(client):
    client.post(
        "/auth/register",
        json={"email": "login@example.com", "password": "hunter2hunter2"},
    )
    r = client.post(
        "/auth/token",
        data={"username": "login@example.com", "password": "hunter2hunter2"},
    )
    assert r.status_code == 200
    assert "access_token" in r.json()


def test_login_rejects_wrong_password(client):
    client.post(
        "/auth/register",
        json={"email": "wrong@example.com", "password": "hunter2hunter2"},
    )
    r = client.post(
        "/auth/token",
        data={"username": "wrong@example.com", "password": "not-the-password"},
    )
    assert r.status_code == 401


def test_protected_route_requires_a_token(client):
    assert client.get("/documents").status_code == 401


def test_protected_route_rejects_a_bad_token(client):
    r = client.get("/documents", headers={"Authorization": "Bearer nonsense"})
    assert r.status_code == 401


def test_health_needs_no_token(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"
