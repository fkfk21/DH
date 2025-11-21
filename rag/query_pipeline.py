"""Shared utilities for running RAG queries and routing questions."""

from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

import chromadb
from chromadb.api.models.Collection import Collection
from chromadb.utils import embedding_functions
import requests


DEFAULT_ANSWER_INSTRUCTIONS = textwrap.dedent(
    """
    You are an assistant for motion planning researchers. Use the provided context to answer the question accurately.
    Cite the source path and chunk number in parentheses when possible.
    Always respond in two parts:
    1. An English answer.
    2. A concise Japanese translation of the same answer.
    """
).strip()

CLASSIFICATION_LABELS = (
    "implementation",
    "motion_planning",
    "task_and_motion_planning",
    "general",
)

CLASSIFICATION_CONTEXT = textwrap.dedent(
    """
    Implementation / OMPL documentation collection:
      - Source: Doxygen-generated HTML/Markdown for Open Motion Planning Library.
      - Contents: API descriptions (e.g., ompl::geometric::RRT, ompl::control::SST), planner configuration, namespaces, and tutorials.
      - Usage: Implementation questions about planners, classes, parameters, compilation, or integration with OMPL.

    Motion Planning survey collection:
      - Sources: "Orthey et al. 2024 - Sampling-based motion planning", "Gammell & Strub 2021", etc.
      - Contents: Conceptual overviews of sampling/optimization planners, comparative studies, research trends.

    Task and Motion Planning survey collection:
      - Sources: "Garrett et al. 2021 - Integrated Task and Motion Planning", "Zhao et al. 2024 - Optimization-based TAMP".
      - Contents: Symbolic task planners combined with motion planning, benchmarks, learning-based TAMP.
    """
).strip()


@dataclass
class QueryResult:
    context: str
    answer: str
    inferred_kind: Optional[str]
    applied_filter: Optional[Dict]
    fallback_used: bool


def call_ollama(
    url: str,
    model: str,
    prompt: str,
    temperature: float,
) -> str:
    endpoint = url.rstrip("/") + "/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "temperature": temperature,
        "stream": False,
    }
    response = requests.post(endpoint, json=payload, timeout=120)
    response.raise_for_status()
    return response.json().get("response", "").strip()


def infer_kind_from_question(question: str) -> Optional[str]:
    lower = question.lower()
    if "tutorial" in lower or "example" in lower:
        return "tutorial"
    if "namespace" in lower:
        return "namespace"
    if any(keyword in lower for keyword in ("planner", "class", "algorithm")):
        return "class"
    if any(keyword in lower for keyword in ("function", "method", "api")):
        return "function"
    if "file" in lower:
        return "file"
    return None


def _combine_filters(filters: Iterable[Dict]) -> Optional[Dict]:
    clauses = [f for f in filters if f]
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def _build_filter(
    *,
    question: str,
    auto_filter: bool,
    metadata_filter: Optional[Dict],
) -> Tuple[Optional[Dict], Optional[str]]:
    inferred_kind = infer_kind_from_question(question) if auto_filter else None
    kind_filter = {"kind": {"$eq": inferred_kind}} if inferred_kind else None
    final_filter = _combine_filters([kind_filter, metadata_filter])
    return final_filter, inferred_kind


def format_context(documents: List[str], metadatas: List[dict]) -> str:
    blocks: List[str] = []
    for idx, (doc, meta) in enumerate(zip(documents, metadatas), start=1):
        paper_title = meta.get("paper_title")
        section_title = meta.get("section_title")
        title = meta.get("title")
        label_parts = [part for part in (paper_title, section_title, title) if part]
        label = " / ".join(dict.fromkeys(label_parts)) if label_parts else "unknown"
        chunk_index = meta.get("chunk_index")
        page_start = meta.get("page_start")
        location_bits = []
        if chunk_index is not None:
            location_bits.append(f"chunk {chunk_index}")
        if page_start is not None:
            location_bits.append(f"page {page_start}")
        location = ", ".join(location_bits)
        source = meta.get("source", "unknown")
        meta_info = ", ".join(filter(None, (source, location)))
        header = f"[{idx}] {label}"
        if meta_info:
            header += f" ({meta_info})"
        blocks.append(f"{header}\n{doc}")
    return "\n\n".join(blocks)


def _query_collection(
    collection: Collection,
    question: str,
    *,
    top_k: int,
    where: Optional[Dict],
) -> Dict:
    return collection.query(
        query_texts=[question],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
        where=where,
    )


def run_rag_query(
    question: str,
    *,
    persist_dir: str = ".chroma",
    collection_name: str,
    model_name: str = "sentence-transformers/all-mpnet-base-v2",
    ollama_model: str = "deepseek-r1:8b",
    ollama_url: str = "http://localhost:11434",
    top_k: int = 5,
    temperature: float = 0.1,
    auto_filter: bool = True,
    metadata_filter: Optional[Dict] = None,
    answer_instructions: Optional[str] = None,
) -> QueryResult:
    embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=model_name
    )
    client = chromadb.PersistentClient(path=persist_dir)
    collection = client.get_collection(
        collection_name, embedding_function=embedding_fn
    )

    where_clause, inferred_kind = _build_filter(
        question=question,
        auto_filter=auto_filter,
        metadata_filter=metadata_filter,
    )

    results = None
    fallback_used = False
    try:
        results = _query_collection(
            collection, question, top_k=top_k, where=where_clause
        )
        if not results["documents"][0]:
            raise ValueError("empty results")
    except Exception:
        fallback_used = where_clause is not None
        results = _query_collection(collection, question, top_k=top_k, where=None)
        where_clause = None
        inferred_kind = None

    documents = results["documents"][0]
    metadatas = results["metadatas"][0]
    context = format_context(documents, metadatas)
    instructions = answer_instructions or DEFAULT_ANSWER_INSTRUCTIONS
    prompt = textwrap.dedent(
        f"""
        {instructions}

        Context:
        {context}

        Question:
        {question}
        """
    ).strip()

    answer = call_ollama(
        url=ollama_url,
        model=ollama_model,
        prompt=prompt,
        temperature=temperature,
    )
    return QueryResult(
        context=context,
        answer=answer,
        inferred_kind=inferred_kind,
        applied_filter=where_clause,
        fallback_used=fallback_used,
    )


def _extract_json_object(text: str) -> Optional[Dict]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        snippet = text[start : end + 1]
        try:
            return json.loads(snippet)
        except json.JSONDecodeError:
            return None
    return None


def classify_question(
    question: str,
    *,
    ollama_model: str = "deepseek-r1:8b",
    ollama_url: str = "http://localhost:11434",
    temperature: float = 0.0,
    labels: Tuple[str, ...] = CLASSIFICATION_LABELS,
) -> Dict[str, str]:
    label_list = "\n".join(f"- {label}" for label in labels)
    prompt = textwrap.dedent(
        f"""
        You are a classifier for research questions.
        Read the user question and decide which label best describes it.
        Choose only from:
        {label_list}
        implementation: Practical questions about implementing or configuring motion-planning systems (e.g., OMPL APIs, classes, planners, parameters, compilation/integration details).
        motion_planning: Research questions about motion planning concepts, algorithms, or surveys that are not specifically about OMPL implementation details.
        task_and_motion_planning: Questions about integrated task-and-motion planning, high-level symbolic reasoning combined with motion.
        general: Anything unrelated or too broad to classify.
        Context about available collections:
        {CLASSIFICATION_CONTEXT}
        Respond ONLY in JSON with keys "label" and "reason".

        Question:
        {question}
        """
    ).strip()
    response = call_ollama(
        url=ollama_url,
        model=ollama_model,
        prompt=prompt,
        temperature=temperature,
    )
    parsed = _extract_json_object(response) or {}
    label = str(parsed.get("label", "")).strip().lower()
    if label not in labels:
        label = "general"
    reason = str(parsed.get("reason", "")).strip()
    return {"label": label, "reason": reason, "raw_response": response}
