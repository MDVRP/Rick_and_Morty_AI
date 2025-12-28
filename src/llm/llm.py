from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence

import requests

from src.config import (
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_NUM_PREDICT,
    OLLAMA_TEMPERATURE,
    SCHEMA_JSON_PATH,
    OLLAMA_EMBED_MODEL,
)
from src.config import SQL_SYSTEM_MESSAGE, ANSWER_SYSTEM_MESSAGE


class LLMClient:
    """
    Lightweight client for Ollama chat API with helpers to:
    - Generate SQL from a provided SQLite schema and NL query
    - Compose an answer from provided SQL result context
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self.base_url = base_url or OLLAMA_BASE_URL
        self.model = model or OLLAMA_MODEL
        self.session = requests.Session()

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = OLLAMA_TEMPERATURE,
        num_predict: int = OLLAMA_NUM_PREDICT,
    ) -> str:
        url = f"{self.base_url}/api/chat"
        headers = {"Content-Type": "application/json"}
        payload = {
            "model": str(self.model),
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": float(temperature),
                "num_predict": int(num_predict),
            },
        }
        resp = self.session.post(url, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        msg = (data or {}).get("message") or {}
        content = msg.get("content")
        if not content:
            raise RuntimeError(f"Unexpected response: {data}")
        return content

    def embed(self, text: str, model: Optional[str] = None, timeout: int = 60) -> List[float]:
        """
        Get an embedding vector for the given text using Ollama's embeddings API.
        Returns a normalized vector (cosine comparable). Empty text returns [].
        """
        if not text or not text.strip():
            return []
        url = f"{self.base_url}/api/embeddings"
        payload = {"model": str(model or OLLAMA_EMBED_MODEL or "nomic-embed-text"), "prompt": text}
        resp = self.session.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        vec = data.get("embedding") or []
        try:
            vec = [float(v) for v in vec]
        except Exception:
            return []
        # L2 normalize
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        return [v / norm for v in vec]

    def generate_sql_from_schema(
        self,
        user_query: str,
        dialect: str = "sqlite",
    ) -> str:
        """
        Create an SQL query for the given user question using the saved DB schema JSON.
        Returns SQL as a string (without fenced code blocks).
        """
        with open(SCHEMA_JSON_PATH, "r", encoding="utf-8") as f:
            schema_data: Dict[str, Any] = json.load(f)
        schema_str = self._format_schema(schema_data)
        system_msg = f"{SQL_SYSTEM_MESSAGE} Target SQL dialect: {dialect}."
        user_msg = f"Schema:\n{schema_str}\n\n User:\n{user_query}\n\nSQL:"
        content = self.chat_completion(
            [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.1,
        )
        return self._extract_sql(content)

    def answer_from_sql_results(
        self,
        user_query: str,
        column_names: Sequence[str],
        rows: Sequence[Sequence[Any]],
        extra_context: Optional[str] = None,
        notes: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Compose a natural-language answer only from the provided rows (and optional extra_context).
        """
        table_preview = self._format_rows_as_table(column_names, rows, max_rows=50)
        system_msg = ANSWER_SYSTEM_MESSAGE
        ctx = f"Data:\n{table_preview}"
        if extra_context:
            ctx += f"\n\nAdditional context:\n{extra_context}"
        if notes:
            # Add top notes as additional grounded context
            try:
                top_notes = "\n".join(f"- {n.get('notes')}" for n in notes if n and n.get("notes"))
            except Exception:
                top_notes = ""
            if top_notes:
                ctx += f"\n\nNotes:\n{top_notes}"
        user_msg = f"{ctx}\n\nUser:\n{user_query}\n\nResponse:"
        return self.chat_completion(
            [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
        )

    # ---- internal helpers ----
    def _format_schema(self, schema: Dict[str, Any]) -> str:
        """
        Pretty-prints a table->columns schema for prompting.
        Accepts format from Store.dump_all_table_schemas().
        """
        parts: List[str] = []
        for table, cols in schema.items():
            parts.append(f"TABLE {table}")
            for c in cols:
                col_name = c.get("name")
                col_type = c.get("type")
                parts.append(f"  - {col_name} {col_type}")
        return "\n".join(parts)

    def _extract_sql(self, content: str) -> str:
        """
        Extracts SQL from a model reply (handles ```sql fenced blocks or plain text).
        """
        if not content:
            return ""
        fence = re.findall(r"```sql\s+([\s\S]*?)```", content, flags=re.IGNORECASE)
        if fence:
            return fence[0].strip().rstrip(";")
        fence_any = re.findall(r"```\s*([\s\S]*?)```", content)
        if fence_any:
            return fence_any[0].strip().rstrip(";")
        return content.strip().rstrip(";")

    def _format_rows_as_table(
        self, columns: Sequence[str], rows: Sequence[Sequence[Any]], max_rows: int = 50
    ) -> str:
        if not columns:
            return "(no columns)"
        rows = list(rows)[: max_rows if max_rows is not None else len(rows)]
        # Simple TSV format for compactness
        out: List[str] = []
        out.append("\t".join(str(c) for c in columns))
        for r in rows:
            out.append("\t".join("" if v is None else str(v) for v in r))
        return "\n".join(out)


