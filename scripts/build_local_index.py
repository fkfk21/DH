#!/usr/bin/env python3
"""Create a Chroma vector index from preprocessed OMPL documentation chunks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Iterable, List

import chromadb
from chromadb.utils import embedding_functions
from tqdm import tqdm


def iter_chunks(chunk_file: Path) -> Iterable[Dict]:
    with chunk_file.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            yield json.loads(line)


def batched(iterable: Iterable[Dict], batch_size: int) -> Iterable[List[Dict]]:
    batch: List[Dict] = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def build_index(
    chunk_path: Path,
    persist_dir: Path,
    collection_name: str,
    model_name: str,
    batch_size: int,
    reset: bool,
) -> None:
    persist_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(persist_dir))
    embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=model_name
    )

    if reset:
        try:
            client.delete_collection(name=collection_name)
            print(f"Deleted existing collection '{collection_name}'.")
        except chromadb.errors.NotFoundError:
            pass

    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
        embedding_function=embedding_fn,
    )

    total = sum(1 for _ in chunk_path.open("r", encoding="utf-8"))
    progress = tqdm(total=total, desc="Indexing chunks")
    next_id = 0

    for batch in batched(iter_chunks(chunk_path), batch_size=batch_size):
        documents = [record["text"] for record in batch]
        metadatas = []
        for record in batch:
            metadatas.append(
                {
                    "source": record.get("source"),
                    "title": record.get("title"),
                    "kind": record.get("kind"),
                    "symbol": record.get("symbol"),
                    "namespace": record.get("namespace"),
                    "chunk_index": record.get("chunk_index"),
                }
            )
        ids = [f"chunk-{next_id + i}" for i in range(len(batch))]
        next_id += len(batch)
        collection.upsert(documents=documents, metadatas=metadatas, ids=ids)
        progress.update(len(batch))

    progress.close()
    print(f"Indexed {next_id} chunks into collection '{collection_name}'.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a local Chroma index from OMPL doc chunks."
    )
    parser.add_argument(
        "--chunks",
        type=Path,
        default=Path("rag_data/ompl_doc_chunks.jsonl"),
        help="Path to JSONL file produced by extract_ompl_docs.py",
    )
    parser.add_argument(
        "--persist-dir",
        type=Path,
        default=Path(".chroma"),
        help="Directory where Chroma should persist the index.",
    )
    parser.add_argument(
        "--collection-name",
        type=str,
        default="ompl_docs",
        help="Chroma collection name.",
    )
    parser.add_argument(
        "--model-name",
        type=str,
        default="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        help="SentenceTransformer model to use for embeddings.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=64,
        help="Number of chunks to process per batch.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete the collection before rebuilding.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_index(
        chunk_path=args.chunks,
        persist_dir=args.persist_dir,
        collection_name=args.collection_name,
        model_name=args.model_name,
        batch_size=args.batch_size,
        reset=args.reset,
    )


if __name__ == "__main__":
    main()
