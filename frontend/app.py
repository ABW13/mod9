"""Study Buddy — chat with your own study documents."""

import streamlit as st

import api_client as api

st.set_page_config(page_title="Study Buddy", page_icon="📚", layout="wide")


# --- session state -----------------------------------------------------------

if "token" not in st.session_state:
    st.session_state.token = None
    st.session_state.email = None
if "messages" not in st.session_state:
    st.session_state.messages = []


def sign_out() -> None:
    """Clear the session and start over."""
    st.session_state.token = None
    st.session_state.email = None
    st.session_state.messages = []
    st.rerun()


def sign_in_screen() -> None:
    """Registration and login, shown when there is no token."""
    left, right = st.columns([1, 1])

    with left:
        st.subheader("Sign in")
        with st.form("login"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Sign in"):
                try:
                    st.session_state.token = api.login(email, password)
                    st.session_state.email = email
                    st.rerun()
                except api.ApiError as exc:
                    st.error(str(exc))

    with right:
        st.subheader("Create an account")
        with st.form("register"):
            new_email = st.text_input("Email", key="reg_email")
            new_password = st.text_input("Password", key="reg_pass", type="password")
            if st.form_submit_button("Register"):
                try:
                    api.register(new_email, new_password)
                    st.session_state.token = api.login(new_email, new_password)
                    st.session_state.email = new_email
                    st.rerun()
                except api.ApiError as exc:
                    st.error(str(exc))


if st.session_state.token is None:
    st.title("Study Buddy")
    st.caption("Ask questions of your own study notes and see which passage each answer came from.")
    sign_in_screen()
    st.stop()


# --- sidebar -----------------------------------------------------------------

with st.sidebar:
    st.title("📚 Study Buddy")
    st.caption(st.session_state.email)

    try:
        info = api.health()
        st.success("API connected")
        st.write(f"Ollama: {info.get('ollama', 'unknown')}")
        st.metric("Chunks indexed", info.get("chunks", 0))
    except api.ApiError as exc:
        st.error(f"API unavailable: {exc}")

    st.divider()
    st.subheader("Documents")

    try:
        docs = api.list_documents(st.session_state.token)
        if docs:
            for doc in docs:
                cols = st.columns([4, 1])
                cols[0].write(f"{doc['filename']}")
                cols[0].caption(f"{doc['chunk_count']} chunks")
                if cols[1].button("✕", key=f"del{doc['id']}"):
                    api.delete_document(st.session_state.token, doc["id"])
                    st.rerun()
        else:
            st.caption("No documents yet.")
    except api.ApiError as exc:
        st.error(str(exc))

    uploaded = st.file_uploader("Add a .txt file", type=["txt"])
    if uploaded is not None and st.button("Upload"):
        try:
            api.upload_document(st.session_state.token, uploaded.name, uploaded.getvalue())
            st.success(f"Uploaded {uploaded.name}")
            st.rerun()
        except api.ApiError as exc:
            st.error(str(exc))

    if st.button("Re-index documents"):
        try:
            result = api.ingest(st.session_state.token)
            st.success(f"Indexed {result['chunks']} chunks from {result['documents']} document(s)")
            st.rerun()
        except api.ApiError as exc:
            st.error(str(exc))

    st.divider()
    st.subheader("Recent questions")
    try:
        for item in api.history(st.session_state.token)[:5]:
            label = item["confidence"] or "refused"
            st.caption(f"{label} \u00b7 {item['question'][:40]}")
    except api.ApiError as exc:
        st.error(str(exc))

    if st.button("Sign out"):
        sign_out()


# --- chat --------------------------------------------------------------------

st.title("Ask your documents")

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.write(message["content"])
        if message.get("sources"):
            label = message.get("confidence", "unknown")
            with st.expander(f"Sources ({label} confidence)"):
                for src in message["sources"]:
                    dist = src.get("distance")
                    caption = f"{src['source']} · chunk {src['chunk']}"
                    if dist is not None:
                        caption += f" · distance {dist:.3f}"
                    st.caption(caption)
                    st.write(src["text"][:300] + "…")

if prompt := st.chat_input("Ask a question about your notes…"):
    if not prompt.strip():
        st.warning("Please enter a question.")
        st.stop()

    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Searching your documents…"):
            try:
                result = api.ask(st.session_state.token, prompt)
                st.write(result["answer"])
                sources = result.get("sources", [])
                if sources:
                    label = result.get("confidence", "unknown")
                    with st.expander(f"Sources ({label} confidence)"):
                        for src in sources:
                            dist = src.get("distance")
                            caption = f"{src['source']} · chunk {src['chunk']}"
                            if dist is not None:
                                caption += f" · distance {dist:.3f}"
                            st.caption(caption)
                            st.write(src["text"][:300] + "…")
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": result["answer"],
                    "sources": sources,
                    "confidence": result.get("confidence"),
                })
            except api.ApiError as exc:
                st.error(f"Error: {exc}")
