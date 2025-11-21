#!/usr/bin/env python3
"""Query the local OMPL RAG index and answer via an Ollama-served LLM."""

from __future__ import annotations

import argparse

from rag.query_pipeline import QueryResult, run_rag_query


def run_query(
    question: str,
    *,
    persist_dir: str = ".chroma",
    collection_name: str = "ompl_docs_en",
    model_name: str = "sentence-transformers/all-mpnet-base-v2",
    ollama_model: str = "deepseek-r1:8b",
    ollama_url: str = "http://localhost:11434",
    top_k: int = 5,
    temperature: float = 0.1,
    auto_filter: bool = True,
) -> tuple[str, str]:
    result: QueryResult = run_rag_query(
        question,
        persist_dir=persist_dir,
        collection_name=collection_name,
        model_name=model_name,
        ollama_model=ollama_model,
        ollama_url=ollama_url,
        top_k=top_k,
        temperature=temperature,
        auto_filter=auto_filter,
    )
    return result.context, result.answer


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
    parser.add_argument(
        "--no-auto-filter",
        action="store_true",
        help="質問文からkindを推定したメタデータフィルタを適用しない。",
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
        auto_filter=not args.no_auto_filter,
    )

    print("\n=== Retrieved Context ===")
    print(context)
    print("\n=== LLM Answer ===")
    print(answer)


if __name__ == "__main__":
    main()
