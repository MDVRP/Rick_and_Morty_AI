from src.data_store.read_api import LocationsReader
from src.data_store.store import Store
from src.llm.llm import LLMClient
from src.search.search import SearchService
from contextlib import closing
import streamlit as st
import sqlite3
import re


def ensure_ingested_once() -> Store:
    st.session_state.store = Store()
    if not st.session_state.get("ingested", False):
        with st.spinner("Ingesting Rick and Morty data (first run only)..."):
            reader = LocationsReader()
            st.session_state.store.ingest_from_reader(reader)
        st.session_state.ingested = True
    return st.session_state.store


def main() -> None:
    st.title("Rick & Morty AI")
    st.caption("Ingests data on first run, then lets you query using LLM-generated SQL.")

    store = ensure_ingested_once()
    client = LLMClient()

    query = st.text_area("Ask something or provide an instruction", height=120)
    if st.button("Ask"):
        if not query.strip():
            st.warning("Ask about a charachter or a location , or add a new note about a charachter. It is suggested to provide the exact name .")
            return
        try:
            sql = client.generate_sql_from_schema(query)
            with closing(store._connect()) as conn, conn:
                cur = conn.execute(sql)
                rows = cur.fetchall()
                columns = [d[0] for d in cur.description] if cur.description else []
            print("rows : ",rows)
            print("--------------------------------")
            # Extract image URLs (start with https and end at first .jpeg) from the result set
            img_pattern = re.compile(r"https://.*?\.jpeg", re.IGNORECASE)
            found_imgs = []
            for r in rows:
                for cell in r:
                    if isinstance(cell, str):
                        found_imgs.extend(img_pattern.findall(cell))
            # Deduplicate while preserving order
            if found_imgs:
                unique_imgs = list(dict.fromkeys(found_imgs))
                st.subheader("Related images")
                # Render images in a responsive grid (4 columns per row)
                cols_per_row = 4
                for i in range(0, len(unique_imgs), cols_per_row):
                    row_urls = unique_imgs[i : i + cols_per_row]
                    cols = st.columns(len(row_urls))
                    for idx, url in enumerate(row_urls):
                        with cols[idx]:
                            st.image(url, width=250)
                            st.write("")  # small spacing between rows
            
            # Retrieve relevant notes and add as context
            search = SearchService(client=client)
            try:
                _ = search.refresh_missing_embeddings()
            except Exception:
                pass
            similar_notes = []
            try:
                similar_notes = search.search(query, top_k=5, alpha=0.7)
            except Exception:
                similar_notes = []
            answer = client.answer_from_sql_results(query, columns, rows, extra_context=None, notes=similar_notes)
            # Store the generated answer as a note
            try:
                search.store_and_embed_response(answer)
            except Exception:
                pass
            st.subheader("Answer")
            st.write(answer)
        except sqlite3.Error as e:
            st.error(f"Database error: {e}")


if __name__ == "__main__":
    main()
