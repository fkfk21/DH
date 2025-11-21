#!/usr/bin/env python3
"""Convenience wrapper for querying the OMPL documentation index."""

from __future__ import annotations

import argparse

from rag.query_pipeline import QueryResult, run_rag_query


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Query the OMPL documentation Chroma collection."
    )
    parser.add_argument("question", type=str, help="質問文（日本語/英語どちらでも可）")
    parser.add_argument(
        "--persist-dir",
        type=str,
        default=".chroma",
        help="Chroma 永続化ディレクトリ",
    )
    parser.add_argument(
        "--collection-name",
        type=str,
        default="ompl_docs_en",
        help="OMPL 用コレクション名",
    )
    parser.add_argument(
        "--model-name",
        type=str,
        default="sentence-transformers/all-mpnet-base-v2",
        help="埋め込みモデル",
    )
    parser.add_argument(
        "--ollama-model",
        type=str,
        default="deepseek-r1:8b",
        help="Ollama で稼働中の LLM 名",
    )
    parser.add_argument(
        "--ollama-url",
        type=str,
        default="http://localhost:11434",
        help="Ollama API ベース URL",
    )
    parser.add_argument("--top-k", type=int, default=5, help="Retriever の取得件数")
    parser.add_argument(
        "--temperature", type=float, default=0.1, help="LLM 温度パラメータ"
    )
    parser.add_argument(
        "--no-auto-filter",
        action="store_true",
        help="質問文からkindを推定するフィルタを無効化",
    )
    args = parser.parse_args()

    result: QueryResult = run_rag_query(
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

    print("# OMPL Query Result")
    if result.inferred_kind:
        print(f"Inferred kind filter: {result.inferred_kind}")
    if result.fallback_used:
        print("(Fallback to unfiltered search)")
    print("\n## Retrieved Context")
    print(result.context)
    print("\n## LLM Answer")
    print(result.answer)


if __name__ == "__main__":
    main()
