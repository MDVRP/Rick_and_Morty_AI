from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.llm.llm import LLMClient


def _token_set(text: str) -> set:
    return set(re.findall(r"\w+", (text or "").lower()))


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b:
        return 0.0
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return float(sum(x * y for x, y in zip(a, b))) / (na * nb)


def build_context_text(
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
    notes: Optional[List[Dict[str, Any]]] = None,
    max_rows: int = 50,
) -> str:
    """Compose a plain-text context from SQL rows plus optional notes."""
    lines: List[str] = []
    if columns:
        lines.append("\t".join(map(str, columns)))
    for r in list(rows)[: max_rows if max_rows is not None else len(rows)]:
        lines.append("\t".join("" if v is None else str(v) for v in r))
    notes_text = ""
    if notes:
        notes_text = "\n".join(
            f"- {n.get('notes')}" for n in notes if isinstance(n, dict) and n.get("notes")
        )
    ctx = "\n".join(lines)
    if notes_text:
        ctx += "\n\n" + notes_text
    return ctx


def evaluate_answer(
    client: LLMClient,
    question: str,
    answer: str,
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
    notes: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[Dict[str, float], str]:
    """
    Compute simple metrics (coverage, relevance, completeness) and return (metrics, context_text).
    - coverage: token overlap between answer and context
    - relevance: cosine similarity between embeddings of answer and question
    - completeness: fraction of significant question tokens present in answer
    """
    context_text = build_context_text(columns, rows, notes=notes, max_rows=50)

    ans_tokens = _token_set(answer)
    ctx_tokens = _token_set(context_text)
    q_tokens = {t for t in _token_set(question) if len(t) >= 3}

    coverage = (len(ans_tokens & ctx_tokens) / (len(ans_tokens) or 1))

    ans_vec = client.embed(answer)
    qry_vec = client.embed(question)
    relevance = _cosine(ans_vec, qry_vec)

    completeness = (len(q_tokens & ans_tokens) / (len(q_tokens) or 1))

    return (
        {
            "coverage": float(coverage),
            "relevance": float(relevance),
            "completeness": float(completeness),
        },
        context_text,
    )


