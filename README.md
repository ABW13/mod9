# Study Buddy

A study assistant that answers questions from your own course notes and shows
which passage each answer came from. Built with FastAPI, SQLAlchemy, ChromaDB,
Ollama and Streamlit, and it runs with one command.

## What it does

You upload text documents, the app splits them into passages and stores them as
vectors, and when you ask a question it retrieves the closest passages, asks a
local language model to answer from them, and returns the answer with citations
and a confidence label. Questions the documents cannot answer are refused rather
than answered from unrelated text.

## Architecture

    Browser
       |  port 8501
       v
  +------------------+          +------------------+
  | Streamlit        |  HTTP    | FastAPI          |
  | frontend         | -------> | backend          |
  | :8501            |          | :8000            |
  +------------------+          +--------+---------+
                                         |
                        +----------------+----------------+
                        |                                 |
                        v                                 v
              +------------------+              +------------------+
              | Ollama           |              | SQLite           |
              | :11434           |              | users            |
              | llama3.2:1b      |              | documents        |
              +--------+---------+              | questions        |
                       |                        +------------------+
                       v                                 |
              +------------------+              +------------------+
              | ollama_data vol  |              | ChromaDB         |
              | model weights    |              | chunk vectors    |
              +------------------+              | + metadata       |
                                                +------------------+
                                                         |
                                                +------------------+
                                                | sqlite_data vol  |
                                                | SQLite + Chroma  |
                                                | + uploaded files |
                                                +------------------+

Three services on one Compose network, addressed by service name. The frontend
never touches the database or the vector store; it talks to the backend only.

## Request flow

1. `POST /auth/token` returns a bearer token. The frontend holds it for the
   session.
2. `POST /documents` stores an uploaded file and records it against the caller.
3. `POST /ingest` reads each uploaded file, splits it on paragraph boundaries
   into overlapping chunks, embeds them, and stores them in ChromaDB with the
   owner's id in the metadata.
4. `POST /ask` embeds the question, retrieves the closest chunks **restricted to
   the caller's own documents**, and compares the best distance against a
   confidence threshold.
5. If the closest chunk is within the threshold, the chunks are assembled into a
   grounded prompt and sent to Ollama. Otherwise the question is refused.
6. The question, answer, confidence and distance are written to the database, so
   history survives the session.

## Prerequisites

Docker Desktop with the WSL 2 backend, and about 2 GB of free disk for the
model.

## Setup

    git clone git@github.com:ABW13/study-buddy.git
    cd study-buddy
    cp .env.example .env
    docker compose up --build

Two values in `.env` need attention before this is anything but a local demo:

- `SECRET_KEY` is blank in the example file. Set it to a long random string;
  it signs every JWT the app issues.
- `OLLAMA_URL` is already set to the Compose service name, which is correct
  inside the stack. It would be wrong on a host machine, where the container
  name does not resolve.

Then pull the model. The Ollama image ships with **no** models, so this step is
required. Without it the server answers requests about its own status and
returns a not-found error when asked to generate.

    docker compose exec ollama ollama pull llama3.2:1b
    docker compose exec ollama ollama list

Then index the corpus. From the UI there is a **Re-index documents** button;
from the command line:

    docker compose exec backend python -c "
    from fastapi.testclient import TestClient
    from app.main import app
    from pathlib import Path
    c = TestClient(app)
    c.post('/auth/register', json={'email': 'you@example.com', 'password': 'changeme123'})
    t = c.post('/auth/token', data={'username': 'you@example.com', 'password': 'changeme123'}).json()['access_token']
    h = {'Authorization': f'Bearer {t}'}
    for p in sorted(Path('/app/docs').glob('*.txt')):
        c.post('/documents', files={'file': (p.name, p.read_bytes(), 'text/plain')}, headers=h)
    print(c.post('/ingest', headers=h).json())
    "

## Usage

Open the frontend in a browser on port 8501. Register an account, then:

- The **sidebar** shows API status, Ollama status, and how many chunks are
  indexed. It lists your documents with their chunk counts, lets you delete one,
  and has a **Re-index documents** button.
- The **chat box** takes a question. The answer appears with a **Sources**
  expander showing each cited passage, its source file, its position in that
  file, and the distance of the match.
- **Recent questions** in the sidebar shows the last few, including refused ones.

## API

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `/auth/register` | POST | no | Create an account |
| `/auth/token` | POST | no | Exchange credentials for a JWT |
| `/documents` | GET | bearer | List your documents |
| `/documents` | POST | bearer | Upload a text file |
| `/documents/{id}` | DELETE | bearer | Delete a document and its chunks |
| `/documents/{id}/chunks` | GET | bearer | The indexed chunks for one document |
| `/ingest` | POST | bearer | Chunk and index your documents |
| `/ask` | POST | bearer | Answer a question from your documents |
| `/questions` | GET | bearer | Your question history |
| `/health` | GET | no | Service status |

Interactive API documentation is served by the backend on port 8000 at `/docs`.

## Configuration

Every value comes from the environment. `backend/app/config.py` defines the
settings and their defaults, `.env` supplies the values, and Compose loads it
with `env_file`. The three agree — a default in code that differs from the value
documented here would be a bug.

| Variable | Value | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./data/study_buddy.db` | Relational store |
| `CHROMA_PATH` | `./data/chroma` | Vector store directory |
| `COLLECTION_NAME` | `documents` | ChromaDB collection |
| `UPLOAD_DIR` | `./data/uploads` | Uploaded files |
| `OLLAMA_URL` | `http://ollama:11434` | Model server, by Compose service name |
| `MODEL_NAME` | `llama3.2:1b` | Model to generate with |
| `CHUNK_WORDS` | `220` | Target chunk size |
| `OVERLAP_WORDS` | `50` | Words repeated between consecutive chunks |
| `MAX_RESULTS` | `5` | Chunks retrieved per question |
| `CONFIDENCE_THRESHOLD` | `0.75` | Distance above which a question is refused |
| `SECRET_KEY` | *(blank by default)* | Signs JWTs — set this |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | Token lifetime |

Because the environment is applied when containers are created rather than when
images are built, changing a value and running `docker compose up -d` is enough.
No rebuild.

## Chunking

Documents are split on paragraph boundaries, targeting 220 words per chunk with
50 words of overlap. Splitting on structure rather than on a fixed character
window keeps each chunk coherent, and the overlap means a passage that straddles
a boundary appears intact in at least one chunk.

The corpus of five documents and 3,852 words produces **24 chunks**: five each
from the algorithms, data structures, testing and web API notes, and four from
the version control notes.

Every chunk is stored with `owner_id`, `document_id`, `source`, `chunk` and
`total_chunks` in its metadata. The owner id is what makes per-user retrieval
possible, and the source and index are what make a citation possible.

## The guardrail

ChromaDB returns a cosine **distance**: smaller means closer. After retrieval the
best distance is compared against `CONFIDENCE_THRESHOLD`. If it exceeds the
threshold the question is refused, rather than answered from whatever text
happened to come back.

The threshold was measured rather than guessed. Ten questions were asked against
the indexed corpus — five it covers, five it does not:

| Question | Answerable | Best distance | Result |
|---|---|---|---|
| Merge sort compared with quick sort | yes | 0.295 | answered |
| Hash table compared with a list | yes | 0.441 | answered |
| Why tests should be independent | yes | 0.360 | answered |
| Difference between 401 and 403 | yes | 0.358 | answered |
| Rebasing on a shared branch | yes | 0.486 | answered |
| Who won the 2018 World Cup | no | 0.909 | refused |
| Boiling point of mercury | no | 0.918 | refused |
| Baking sourdough bread | no | 0.919 | refused |
| Capital of France | no | 0.958 | refused |
| Author of Pride and Prejudice | no | 0.963 | refused |

Answerable questions land at or below 0.486; unanswerable ones at or above 0.909.
The threshold sits at **0.75**, in the middle of that gap.

Two limits are worth stating. The separation is a property of this corpus and
would need re-measuring on different material. And a distance threshold catches
*retrieval* failure, not drift in generation: a model given a good match can
still add a claim the passage does not support. Citing the sources is what makes
that visible to a reader.

## Tests

    docker compose exec backend sh -c "cd /app && python -m pytest tests/ -v"

Twenty-two tests in three files:

- `tests/test_auth.py` — registration, duplicate rejection, login, invalid
  credentials, protected routes refusing a missing or malformed token, and the
  public health endpoint.
- `tests/test_crud.py` — upload, unsupported file types, listing, the chunks
  endpoint, duplicate uploads replacing rather than accumulating, and the
  ownership rules: another account cannot list, delete, or inspect your documents.
- `tests/test_rag.py` — chunking, ingestion, a structured answer with citations,
  the guardrail refusing, and questions being recorded in history.

**The tests do not require Ollama.** Generation is stubbed, so the suite runs
without a model pulled and without the network. Verified by stopping the model
server and running the suite again: same twenty passes either way. What the
tests check is the pipeline's own behaviour — which chunks were retrieved, what
prompt was built, whether the guardrail short-circuited before generation — not
whether an external service happened to be reachable.

Each test starts from an empty database and an empty vector store, so no test
depends on another test running first.

## Project layout

    study-buddy/
    |-- docker-compose.yml
    |-- .env                      (not committed)
    |-- .env.example
    |-- README.md
    |-- backend/
    |   |-- Dockerfile
    |   |-- requirements.txt
    |   |-- app/
    |   |   |-- main.py           FastAPI app and route registration
    |   |   |-- config.py         environment-driven settings
    |   |   |-- database.py       engine, session, Base
    |   |   |-- models.py         users, documents, questions
    |   |   |-- schemas.py        Pydantic request and response models
    |   |   |-- security.py       bcrypt hashing and JWT
    |   |   |-- dependencies.py   get_current_user
    |   |   |-- rag.py            chunking, retrieval, generation, guardrail
    |   |   `-- routers/
    |   |       |-- auth.py
    |   |       |-- documents.py
    |   |       `-- ask.py
    |   |-- docs/                 the study corpus, 5 documents
    |   `-- tests/
    |       |-- conftest.py
    |       |-- test_auth.py
    |       |-- test_crud.py
    |       `-- test_rag.py
    `-- frontend/
        |-- Dockerfile
        |-- requirements.txt
        |-- app.py                Streamlit interface
        `-- api_client.py         every API call, in one place

## Dependencies

Backend: `fastapi==0.109.0`, `uvicorn==0.27.0`, `sqlalchemy==2.0.36`,
`chromadb==1.5.9`, `bcrypt==4.2.1`, `python-jose[cryptography]==3.3.0`,
`python-multipart==0.0.20`, `pydantic-settings==2.7.1`,
`email-validator==2.2.0`, `requests==2.31.0`.

Frontend: `streamlit==1.67.0`, `requests==2.31.0`. Test dependencies:
`pytest`, `httpx<0.28`.

Four of these pins are load-bearing:

- **`chromadb==1.5.9`** — the collection is created with a `configuration`
  dictionary carrying an hnsw space of cosine. That parameter exists only from
  chromadb 0.5.4 onward; the commonly cited 0.4.22 raises at import, before the
  server binds its port, which makes it look like a networking fault.
- **`bcrypt` rather than `passlib`** — passlib's last release was in 2020 and its
  version probe fails against bcrypt 4.x with a misleading
  "password cannot be longer than 72 bytes" error. Calling bcrypt directly
  removes the dependency and the failure.
- **`httpx<0.28`** — Starlette's `TestClient` depends on a client API that 0.28
  removed. Without the pin the test suite fails at collection with an
  unexpected-keyword-argument error.
- **Python 3.11 in the containers** — SQLAlchemy 2.0.36 cannot parse annotated
  column unions on Python 3.14. The containers and CI both run 3.11;
  running the app on a newer host interpreter can fail in ways the container
  does not.

## Persistence

One named volume holds everything the app writes:

| Volume | Contents |
|---|---|
| `sqlite_data` | the SQLite database, the Chroma store and uploaded files |
| `ollama_data` | downloaded model weights, about 1.3 GB |

Both survive a plain `docker compose down`. `docker compose down -v` deletes
them, and afterwards the model must be pulled again and documents re-uploaded.

## What I would improve

- **Chunking is paragraph-based and fixed.** Sentence-aware or heading-aware
  splitting would likely retrieve better on longer documents.
- **One embedding model serves everything.** A code-specific model would suit a
  technical corpus better than a general one.
- **The threshold is fitted to this corpus.** Measuring it automatically, or
  adding a reranking step before generation, would make it portable.
- **No conversation memory.** Each question is answered independently, so a
  follow-up cannot refer to an earlier turn.
- **The guardrail checks retrieval, not the answer.** An entailment check
  comparing the generated answer against the cited passages would catch the
  drift the distance threshold cannot see.

## Design decisions

A few choices shaped how this works, and each has a cost worth naming.

### Chunking at 220 words with 50 words of overlap

A few hundred words is the usual starting point for text chunks, and 220 sits
inside that band. Smaller chunks match a question precisely but can lose the
surrounding sentence that makes them intelligible; larger ones carry context but
dilute the embedding, since a vector for a thousand words is a summary of all of
them and may resemble the query only weakly.

The fifty-word overlap exists because an idea that straddles a chunk boundary
would otherwise be split in two, with neither half complete. Repeating the tail
of each chunk at the head of the next guarantees that any passage spanning a
boundary appears intact somewhere.

These are starting values, not measured ones. Tuning them would mean running the
same question set at different settings and comparing the distances — the method
used for the confidence threshold above.

### llama3.2:1b

Speed on CPU. Generation is the slowest part of the pipeline and the difference
between a one-billion and a three-billion parameter model is several times the
response time on the same hardware. For a pipeline that supplies the relevant
passages and asks for a grounded answer, the smaller model is good enough, and
the retrieved context does the work that a larger model's world knowledge would
otherwise cover.

The trade-off is real: a smaller model is likelier to drift from the supplied
text, which is why the citations matter.

### Refusing rather than answering with a caveat

When retrieval finds nothing close enough, the application refuses instead of
generating an answer from whatever came back. The alternative — answering with a
warning attached — is worse for this use case, because a confident wrong answer
reads exactly like a correct one and a study tool that occasionally invents
things is not one you would rely on.

The cost is false refusals: a question the corpus does cover can be turned away
if nothing retrieved resembles it, which usually traces back to chunking. That
is the failure to watch for, and it is why retrieval runs against a question set
with known answers rather than being assumed to work.

### Citing sources on every answer

The distance threshold catches retrieval failure, not drift in generation. A
model given a good match can still add a claim the passage does not support, and
nothing in the numeric guardrail detects that.

Returning the cited passages is what makes it visible: a reader can compare the
answer against what it was drawn from and see the gap. It does not prevent a bad
answer, it makes one detectable, which is the more useful property for a system
whose weakness is confident fabrication.

### One volume for the database and the vector store

Both are generated state that must survive a restart, and splitting them across
two volumes buys nothing here — they are written and read together. One
`sqlite_data` volume holding SQLite, ChromaDB and the uploaded files means a
single `docker compose down -v` resets the application cleanly, which is what
you want during development and what the setup instructions rely on.
