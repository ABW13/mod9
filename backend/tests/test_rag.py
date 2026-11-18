"""Ingestion, retrieval and the confidence guardrail.

Ollama is stubbed, so these tests check the pipeline's own behaviour rather
than whether a model server is available.
"""

DOC = (
    b"Merge sort divides the list in half and merges the sorted halves, "
    b"giving a predictable cost. Quick sort partitions around a pivot and is "
    b"usually faster but can degrade on already sorted input."
)


def _ingest_one(client, auth, name="algorithms.txt", body=DOC):
    client.post(
        "/documents", files={"file": (name, body, "text/plain")}, headers=auth
    )
    return client.post("/ingest", headers=auth)


def test_ingest_chunks_a_document(client, auth):
    r = _ingest_one(client, auth)
    assert r.status_code == 200
    body = r.json()
    assert body["documents"] == 1
    assert body["chunks"] >= 1
    assert body["stored"] == body["chunks"]


def test_ingest_without_documents_is_rejected(client, auth):
    assert client.post("/ingest", headers=auth).status_code == 400


def test_ask_returns_a_structured_answer(client, auth, fake_ollama):
    _ingest_one(client, auth)
    r = client.post(
        "/ask",
        json={"question": "How does merge sort differ from quick sort?"},
        headers=auth,
    )
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"answer", "sources", "confidence", "guardrail"}
    assert body["guardrail"] == "answered"
    assert body["answer"]
    assert body["sources"], "a grounded answer should cite at least one chunk"
    # The stubbed model was called exactly once, with a prompt containing the
    # retrieved document text.
    assert len(fake_ollama) == 1
    assert "Merge sort" in fake_ollama[0]["payload"]["prompt"]


def test_ask_refuses_an_off_topic_question(client, auth, fake_ollama):
    _ingest_one(client, auth)
    body = client.post(
        "/ask",
        json={"question": "What is the capital of France?"},
        headers=auth,
    ).json()
    assert body["guardrail"] == "rejected_below_threshold"
    assert body["sources"] == []
    # The guardrail refused before generation, so the model was never called.
    assert fake_ollama == []


def test_ask_without_documents_is_refused(client, auth, fake_ollama):
    body = client.post(
        "/ask",
        json={"question": "What is merge sort?"},
        headers=auth,
    ).json()
    assert body["guardrail"] == "rejected_below_threshold"
    assert fake_ollama == []


def test_questions_are_recorded_in_history(client, auth, fake_ollama):
    _ingest_one(client, auth)
    client.post("/ask", json={"question": "What is merge sort?"}, headers=auth)
    client.post("/ask", json={"question": "Who won the 2018 World Cup?"}, headers=auth)

    history = client.get("/questions", headers=auth).json()
    assert len(history) == 2
    refused = [q for q in history if q["answer"] is None]
    assert len(refused) == 1
