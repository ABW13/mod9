"""Retrieval-augmented generation over per-user documents."""

from pathlib import Path
from typing import Optional

import chromadb
import requests

from .config import settings

CHROMA_PATH = settings.CHROMA_PATH


def iter_paragraphs(text: str):
    """Yield non-empty paragraphs from a document.

    Splitting on blank lines keeps each chunk on a structural boundary, which
    a fixed character window would not.
    """
    for block in text.split("\n\n"):
        cleaned = " ".join(block.split())
        if cleaned:
            yield cleaned


def chunk_text(text: str, chunk_words: Optional[int] = None,
               overlap_words: Optional[int] = None):
    """Split text into overlapping chunks, respecting paragraph boundaries.

    Consecutive chunks share their final ``overlap_words`` words, so a passage
    spanning a boundary appears intact in at least one chunk.
    """
    target = chunk_words or settings.CHUNK_WORDS
    overlap = settings.OVERLAP_WORDS if overlap_words is None else overlap_words

    chunks, current, current_words = [], [], 0

    for para in iter_paragraphs(text):
        para_words = len(para.split())

        if current and current_words + para_words > target:
            chunks.append(" ".join(current))
            if overlap > 0:
                tail = " ".join(current).split()[-overlap:]
                current = [" ".join(tail)] if tail else []
                current_words = len(tail)
            else:
                current, current_words = [], 0

        current.append(para)
        current_words += para_words

    if current:
        chunks.append(" ".join(current))

    return chunks


_client = None


def get_collection():
    """Open the Chroma collection, creating it on first use.

    The client is cached per process; Chroma's PersistentClient is not cheap to
    construct and the store is a single directory.
    """
    global _client
    if _client is None:
        Path(CHROMA_PATH).mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=CHROMA_PATH)
    return _client.get_or_create_collection(
        settings.COLLECTION_NAME,
        configuration={"hnsw": {"space": "cosine"}},
    )


def ingest_file(path: Path, owner_id: int, document_id: int, filename: str):
    """Chunk one file and upsert its chunks under the owner's namespace.

    The owner id goes into every chunk's metadata, which is what lets a query
    be restricted to one user's documents. Ids embed the owner and the document
    so two users uploading the same filename cannot collide.
    """
    collection = get_collection()
    text = path.read_text(encoding="utf-8", errors="replace")
    chunks = chunk_text(text)

    if not chunks:
        return 0

    ids = [f"u{owner_id}:d{document_id}:c{i}" for i in range(len(chunks))]
    metadatas = [
        {
            "owner_id": owner_id,
            "document_id": document_id,
            "source": filename,
            "chunk": i,
            "total_chunks": len(chunks),
        }
        for i in range(len(chunks))
    ]

    collection.upsert(ids=ids, documents=chunks, metadatas=metadatas)
    return len(chunks)


def delete_document_chunks(owner_id: int, document_id: int) -> None:
    """Remove every chunk belonging to one document."""
    collection = get_collection()
    collection.delete(where={"$and": [
        {"owner_id": owner_id},
        {"document_id": document_id},
    ]})


def count_chunks(owner_id: Optional[int] = None) -> int:
    """Count stored chunks, optionally restricted to one owner."""
    collection = get_collection()
    if owner_id is None:
        return collection.count()
    result = collection.get(where={"owner_id": owner_id}, include=[])
    return len(result.get("ids", []))


NO_CONTEXT_ANSWER = (
    "I could not find anything in your documents that answers that question. "
    "Try uploading more material, or rephrasing the question."
)

PROMPT_TEMPLATE = """You are a study assistant. Answer the question using only \
the context provided below.

Rules:
- Base your answer solely on the context.
- If the context does not contain the answer, say so rather than guessing.
- Be concise and specific.

Context:
{context}

Question: {question}

Answer:"""


def _confidence_label(best: Optional[float], threshold: float) -> str:
    """Map the closest distance to a label. Smaller distance is closer."""
    if best is None:
        return "low"
    if best < threshold * 0.6:
        return "high"
    if best < threshold:
        return "medium"
    return "low"


def retrieve(question: str, owner_id: int, n_results: Optional[int] = None):
    """Return the closest chunks from one user's documents.

    The `where` clause restricts the search to chunks this owner ingested, so a
    query can never surface another account's material.
    """
    collection = get_collection()
    total = count_chunks(owner_id=owner_id)
    if total == 0:
        return []

    n = min(n_results or settings.MAX_RESULTS, total)
    results = collection.query(
        query_texts=[question],
        n_results=n,
        where={"owner_id": owner_id},
    )

    documents = results["documents"][0] if results.get("documents") else []
    metadatas = results["metadatas"][0] if results.get("metadatas") else []
    distances = results["distances"][0] if results.get("distances") else []

    sources = []
    for i, text in enumerate(documents):
        meta = metadatas[i] if i < len(metadatas) and metadatas[i] else {}
        sources.append({
            "source": meta.get("source", f"chunk-{i}"),
            "chunk": meta.get("chunk", i),
            "distance": float(distances[i]) if i < len(distances) else None,
            "text": text,
        })
    return sources


def answer_question(question: str, owner_id: int):
    """Retrieve the owner's chunks and generate an answer, or refuse.

    Guardrail: if nothing was retrieved, or the closest match is further than
    CONFIDENCE_THRESHOLD, the question is refused rather than answered from
    unrelated text. Distance is smaller-is-closer, so the test is a maximum.
    """
    sources = retrieve(question, owner_id)
    distances = [s["distance"] for s in sources if s["distance"] is not None]
    best = min(distances) if distances else None
    threshold = settings.CONFIDENCE_THRESHOLD

    if not sources or best is None or best > threshold:
        return {
            "answer": NO_CONTEXT_ANSWER,
            "sources": [],
            "confidence": "low",
            "best_distance": best,
            "guardrail": "rejected_below_threshold",
        }

    context = "\n\n---\n\n".join(s["text"] for s in sources)
    prompt = PROMPT_TEMPLATE.format(context=context, question=question)

    try:
        response = requests.post(
            f"{settings.OLLAMA_URL}/api/generate",
            json={"model": settings.MODEL_NAME, "prompt": prompt, "stream": False},
            timeout=180,
        )
        response.raise_for_status()
        answer = response.json().get("response", "").strip()
    except Exception as exc:
        print(f"Ollama generate failed for {settings.OLLAMA_URL!r}: {exc}")
        answer = f"Could not reach the model: {exc}"

    if not answer:
        answer = "The model returned an empty response."

    return {
        "answer": answer,
        "sources": sources,
        "confidence": _confidence_label(best, threshold),
        "best_distance": best,
        "guardrail": "answered",
    }
