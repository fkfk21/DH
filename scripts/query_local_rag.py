#!/usr/bin/env python3
"""Query the local OMPL RAG index and answer via an Ollama-served LLM."""

from __future__ import annotations

import argparse
import textwrap
from typing import List

import chromadb
from chromadb.utils import embedding_functions
import requests


def format_context(documents: List[str], metadatas: List[dict]) -> str:
    blocks = []
    for idx, (doc, meta) in enumerate(zip(documents, metadatas), start=1):
        source = meta.get("source", "unknown")
        title = meta.get("title", "unknown")
        chunk_index = meta.get("chunk_index")
        header = f"[{idx}] {title} ({source}, chunk {chunk_index})"
        blocks.append(f"{header}\n{doc}")
    return "\n\n".join(blocks)


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
    resp = requests.post(endpoint, json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    return data.get("response", "").strip()


def run_query(
    question: str,
    *,
    persist_dir: str = ".chroma",
    collection_name: str = "ompl_docs",
    model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    ollama_model: str = "deepseek-r1:8b",
    ollama_url: str = "http://localhost:11434",
    top_k: int = 5,
    temperature: float = 0.1,
) -> tuple[str, str]:
    embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=model_name
    )
    client = chromadb.PersistentClient(path=persist_dir)
    collection = client.get_collection(
        collection_name, embedding_function=embedding_fn
    )
    results = collection.query(
        query_texts=[question],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    documents = results["documents"][0]
    metadatas = results["metadatas"][0]
    context = format_context(documents, metadatas)
    prompt = textwrap.dedent(
        f"""
        You are an assistant for motion planning researchers. Use the provided OMPL documentation excerpts to answer the question.
        When possible, cite the source path and chunk number in parentheses.

        Context:
        {context}

        Question:
        {question}

        Answer in Japanese if the user asks in Japanese, otherwise reply in English.
        """
    ).strip()

    answer = call_ollama(
        url=ollama_url,
        model=ollama_model,
        prompt=prompt,
        temperature=temperature,
    )
    return context, answer


def main() -> None:
    parser = argparse.ArgumentParser(description="Query OMPL docs with a local LLM.")
    parser.add_argument("question", type=str, help="質問文（日本語/英語どちらでも可）")
    parser.add_argument(
        "--persist-dir",
        type=str,
        default=".chroma",
        help="Chroma の永続化ディレクトリ。",
    )
    parser.add_argument(
        "--collection-name",
        type=str,
        default="ompl_docs",
        help="使用するコレクション名。",
    )
    parser.add_argument(
        "--model-name",
        type=str,
        default="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        help="埋め込みに利用する SentenceTransformer モデル名。",
    )
    parser.add_argument(
        "--ollama-model",
        type=str,
        default="deepseek-r1:8b",
        help="Ollama 側で動かす LLM 名。",
    )
    parser.add_argument(
        "--ollama-url",
        type=str,
        default="http://localhost:11434",
        help="Ollama API エンドポイントのベース URL。",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Retriever で取得するチャンク数。",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.1,
        help="Ollama 推論時の温度パラメータ。",
    )
    args = parser.parse_args()

    context, answer = run_query(
        args.question,
        persist_dir=args.persist_dir,
        collection_name=args.collection_name,
        model_name=args.model_name,
        ollama_model=args.ollama_model,
        ollama_url=args.ollama_url,
        top_k=args.top_k,
        temperature=args.temperature,
    )

    print("\n=== Retrieved Context ===")
    print(context)
    print("\n=== LLM Answer ===")
    print(answer)


if __name__ == "__main__":
    main()
