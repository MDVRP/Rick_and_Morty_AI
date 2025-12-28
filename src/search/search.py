from __future__ import annotations

import json
import math
import sqlite3
from contextlib import closing
from typing import Any, Dict, List, Optional, Tuple

from src.config import DB_PATH
from src.llm.llm import LLMClient


def _l2_normalize(vec: List[float]) -> List[float]:
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b:
        return 0.0
    return float(sum(x * y for x, y in zip(a, b)))


class SearchService:
    """
    Notes search and embedding manager backed by the 'Notes' table:
      - Ensures embeddings exist for new notes
      - Stores LLM responses as notes and embeds them
      - Fuzzy + semantic search for most relevant notes
    Table schema expected:
      CREATE TABLE IF NOT EXISTS Notes (
          notes TEXT,
          embedding TEXT
      );
    """

    def __init__(self, db_path: Optional[str] = None, client: Optional[LLMClient] = None) -> None:
        self.db_path = db_path or DB_PATH
        self.client = client or LLMClient()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _row_to_obj(self, row: Tuple[Any, ...]) -> Dict[str, Any]:
        # Notes table has no id column; return content and parsed embedding
        notes_val, embedding_json = row
        try:
            emb = json.loads(embedding_json) if embedding_json else None
        except Exception:
            emb = None
        return {"notes": notes_val, "embedding": emb}

    # -------------------------------
    # Embedding management
    # -------------------------------
    def refresh_missing_embeddings(self) -> int:
        """
        Generate embeddings for rows with empty embeddings.
        Returns count of rows updated.
        """
        updated = 0
        with closing(self._connect()) as conn, conn:
            cur = conn.execute("SELECT rowid, notes, embedding FROM Notes")
            rows = cur.fetchall()
            for rowid, notes_text, embedding_json in rows:
                needs = not embedding_json or not embedding_json.strip()
                if needs and notes_text:
                    vec = self.client.embed(notes_text)
                    conn.execute(
                        "UPDATE Notes SET embedding=? WHERE rowid=?",
                        (json.dumps(vec, ensure_ascii=False, separators=(",", ":")), int(rowid)),
                    )
                    updated += 1
        return updated

    def store_and_embed_response(self, response_text: str) -> None:
        """
        Store LLM response in Notes and embed it immediately.
        """
        if not response_text or not response_text.strip():
            return
        vec = self.client.embed(response_text)
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO Notes (notes, embedding) VALUES (?, ?)",
                (response_text, json.dumps(vec, ensure_ascii=False, separators=(",", ":"))),
            )

    # -------------------------------
    # Search
    # -------------------------------
    def _semantic_scores(
        self, query_vec: List[float], rows: List[Tuple[Any, ...]]
    ) -> List[Tuple[int, float]]:
        scored: List[Tuple[int, float]] = []
        for idx, (_, embedding_json) in enumerate(rows):
            if not embedding_json:
                scored.append((idx, 0.0))
                continue
            try:
                vec = json.loads(embedding_json)
                if not isinstance(vec, list):
                    scored.append((idx, 0.0))
                    continue
            except Exception:
                scored.append((idx, 0.0))
                continue
            # normalize to be safe
            vec = _l2_normalize([float(v) for v in vec])
            scored.append((idx, _cosine(query_vec, vec)))
        return scored

    def _fuzzy_scores(self, query: str, rows: List[Tuple[Any, ...]]) -> List[Tuple[int, float]]:
        # Simple token overlap ratio
        q_tokens = set((query or "").lower().split())
        scored: List[Tuple[int, float]] = []
        for idx, (note_text, _) in enumerate(rows):
            n_tokens = set((note_text or "").lower().split())
            inter = len(q_tokens & n_tokens)
            denom = len(q_tokens | n_tokens) or 1
            scored.append((idx, inter / denom))
        return scored

    def search(self, query: str, top_k: int = 5, alpha: float = 0.7) -> List[Dict[str, Any]]:
        """
        Search Notes with a blend of semantic (alpha) and fuzzy (1-alpha).
        Returns top_k notes with scores.
        """
        with closing(self._connect()) as conn:
            cur = conn.execute("SELECT notes, embedding FROM Notes")
            rows = cur.fetchall()
        if not rows:
            return []

        query_vec = self.client.embed(query)
        sem = dict(self._semantic_scores(query_vec, rows))
        fuz = dict(self._fuzzy_scores(query, rows))

        combined: List[Tuple[int, float]] = []
        for idx in range(len(rows)):
            s = alpha * sem.get(idx, 0.0) + (1.0 - alpha) * fuz.get(idx, 0.0)
            combined.append((idx, s))
        combined.sort(key=lambda x: x[1], reverse=True)

        results: List[Dict[str, Any]] = []
        for idx, score in combined[: max(top_k, 0)]:
            note_text, embedding_json = rows[idx]
            results.append(
                {
                    "notes": note_text,
                    "score": float(score),
                    "embedding": json.loads(embedding_json) if embedding_json else None,
                }
            )
        return results


