"""Document upload, listing, scoping and deletion."""

SAMPLE = b"Chunking splits a document into passages so retrieval returns a useful unit."


def test_upload_returns_a_document(client, auth):
    r = client.post(
        "/documents",
        files={"file": ("notes.txt", SAMPLE, "text/plain")},
        headers=auth,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["filename"] == "notes.txt"
    assert body["chunk_count"] == 0  # not indexed yet


def test_upload_rejects_an_unsupported_type(client, auth):
    r = client.post(
        "/documents",
        files={"file": ("bad.pdf", b"%PDF-1.4", "application/pdf")},
        headers=auth,
    )
    assert r.status_code == 400


def test_listing_returns_only_your_documents(client, auth):
    client.post(
        "/documents", files={"file": ("mine.txt", SAMPLE, "text/plain")}, headers=auth
    )
    client.post(
        "/auth/register",
        json={"email": "other@example.com", "password": "hunter2hunter2"},
    )
    other = client.post(
        "/auth/token",
        data={"username": "other@example.com", "password": "hunter2hunter2"},
    ).json()["access_token"]
    other_header = {"Authorization": f"Bearer {other}"}

    assert [d["filename"] for d in client.get("/documents", headers=auth).json()] == ["mine.txt"]
    assert client.get("/documents", headers=other_header).json() == []


def test_deleting_someone_elses_document_is_not_found(client, auth):
    doc = client.post(
        "/documents", files={"file": ("mine.txt", SAMPLE, "text/plain")}, headers=auth
    ).json()
    client.post(
        "/auth/register",
        json={"email": "other2@example.com", "password": "hunter2hunter2"},
    )
    other = client.post(
        "/auth/token",
        data={"username": "other2@example.com", "password": "hunter2hunter2"},
    ).json()["access_token"]

    r = client.delete(
        f"/documents/{doc['id']}",
        headers={"Authorization": f"Bearer {other}"},
    )
    assert r.status_code == 404


def test_delete_removes_your_document(client, auth):
    doc = client.post(
        "/documents", files={"file": ("gone.txt", SAMPLE, "text/plain")}, headers=auth
    ).json()
    assert client.delete(f"/documents/{doc['id']}", headers=auth).status_code == 204
    assert client.get("/documents", headers=auth).json() == []
