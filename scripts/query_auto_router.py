#!/usr/bin/env python3
"""Classify questions and route them to the appropriate RAG index."""

from __future__ import annotations

import argparse

from rag.query_pipeline import QueryResult, classify_question, run_rag_query

OMPL_ROUTING_INSTRUCTIONS = (
    "You are answering implementation-focused questions about motion planning systems. "
    "Reference OMPL (Open Motion Planning Library) classes, planners, configuration steps, or related implementation advice when helpful."
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="自動でOMPL / Motion Planning / Task & Motion / Generalを判定して問い合わせる"
    )
    parser.add_argument("question", type=str, help="質問文")
    parser.add_argument(
        "--ollama-model",
        type=str,
        default="deepseek-r1:8b",
        help="回答と分類で利用する Ollama モデル",
    )
    parser.add_argument(
        "--ollama-url",
        type=str,
        default="http://localhost:11434",
        help="Ollama API ベース URL",
    )
    parser.add_argument(
        "--classifier-model",
        type=str,
        default=None,
        help="分類専用モデル（省略時は --ollama-model を使用）",
    )
    parser.add_argument(
        "--classifier-temperature",
        type=float,
        default=0.0,
        help="分類時の温度",
    )
    parser.add_argument(
        "--default-general-target",
        type=str,
        choices=["ompl", "survey", "skip"],
        default="ompl",
        help="分類がgeneralのときの処理",
    )
    parser.add_argument("--top-k", type=int, default=5, help="Retriever 取得件数")
    parser.add_argument(
        "--temperature", type=float, default=0.1, help="LLM 温度パラメータ"
    )

    # OMPL settings
    parser.add_argument(
        "--ompl-persist-dir", type=str, default=".chroma", help="OMPL index"
    )
    parser.add_argument(
        "--ompl-collection", type=str, default="ompl_docs_en", help="OMPL collection"
    )
    parser.add_argument(
        "--ompl-model",
        type=str,
        default="sentence-transformers/all-mpnet-base-v2",
        help="OMPL 埋め込みモデル",
    )

    # Survey settings
    parser.add_argument(
        "--survey-persist-dir",
        type=str,
        default=".chroma",
        help="Survey index dir",
    )
    parser.add_argument(
        "--survey-collection",
        type=str,
        default="mp_surveys",
        help="Survey collection name",
    )
    parser.add_argument(
        "--survey-model",
        type=str,
        default="sentence-transformers/all-mpnet-base-v2",
        help="Survey embedding model",
    )
    parser.add_argument(
        "--survey-topic",
        type=str,
        choices=["motion_planning", "task_and_motion_planning", "all"],
        default="all",
        help="Survey index topic filter",
    )
    parser.add_argument(
        "--no-auto-filter",
        action="store_true",
        help="Retriever のkind自動判定を無効化",
    )

    args = parser.parse_args()

    classifier_model = args.classifier_model or args.ollama_model
    classification = classify_question(
        args.question,
        ollama_model=classifier_model,
        ollama_url=args.ollama_url,
        temperature=args.classifier_temperature,
    )
    label = classification.get("label", "general")
    reason = classification.get("reason", "")

    survey_topic_override = None
    if label == "implementation":
        target = "ompl"
    elif label == "motion_planning":
        target = "survey"
        survey_topic_override = "motion_planning"
    elif label == "task_and_motion_planning":
        target = "survey"
        survey_topic_override = "task_and_motion_planning"
    else:
        target = args.default_general_target

    print("# Classification")
    print(f"Label: {label}")
    if reason:
        print(f"Reason: {reason}")
    print(f"Routed target: {target}")

    if target == "skip":
        print("General question detected. Skipping retrieval.")
        return

    if target == "ompl":
        metadata_filter = None
        result: QueryResult = run_rag_query(
            args.question,
            persist_dir=args.ompl_persist_dir,
            collection_name=args.ompl_collection,
            model_name=args.ompl_model,
            ollama_model=args.ollama_model,
            ollama_url=args.ollama_url,
            top_k=args.top_k,
            temperature=args.temperature,
            auto_filter=not args.no_auto_filter,
            metadata_filter=metadata_filter,
            answer_instructions=OMPL_ROUTING_INSTRUCTIONS,
        )
        print("\n# OMPL Answer")
    else:
        topic = survey_topic_override or args.survey_topic
        metadata_filter = None
        if topic != "all":
            metadata_filter = {"topic": {"$eq": topic}}
        result = run_rag_query(
            args.question,
            persist_dir=args.survey_persist_dir,
            collection_name=args.survey_collection,
            model_name=args.survey_model,
            ollama_model=args.ollama_model,
            ollama_url=args.ollama_url,
            top_k=args.top_k,
            temperature=args.temperature,
            auto_filter=not args.no_auto_filter,
            metadata_filter=metadata_filter,
        )
        header = "Survey Answer"
        if topic != "all":
            header += f" (topic={topic})"
        print(f"\n# {header}")

    print("## Retrieved Context")
    print(result.context)
    print("\n## LLM Answer")
    print(result.answer)


if __name__ == "__main__":
    main()
