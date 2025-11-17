#!/usr/bin/env python3
"""Generate text chunks from OMPL documentation for downstream RAG indexing."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, List, Tuple


NEWLINE_TAGS = {
    "p",
    "br",
    "li",
    "div",
    "section",
    "tr",
    "td",
    "th",
    "pre",
    "code",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
}


class _SimpleHTMLStripper(HTMLParser):
    """Minimal HTML-to-text converter so we avoid non-standard dependencies."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: List[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        if tag in NEWLINE_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        if tag in NEWLINE_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:  # type: ignore[override]
        if data.strip():
            self._parts.append(data)

    def get_text(self) -> str:
        return unescape("".join(self._parts))


@dataclass
class SourceDoc:
    path: Path
    text: str
    title: str
    doc_type: str


def parse_html_file(path: Path) -> SourceDoc:
    html = path.read_text(encoding="utf-8", errors="ignore")
    parser = _SimpleHTMLStripper()
    parser.feed(html)
    parser.close()
    text = parser.get_text()
    match = re.search(r"<title>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    title = match.group(1).strip() if match else path.stem
    return SourceDoc(path=path, text=text, title=title, doc_type="html")


def parse_markdown_file(path: Path) -> SourceDoc:
    content = path.read_text(encoding="utf-8", errors="ignore")
    title = path.stem
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("# ").strip() or title
            break
    return SourceDoc(path=path, text=content, title=title, doc_type="markdown")


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 200) -> Iterable[str]:
    clean = normalize_whitespace(text)
    if not clean:
        return []
    start = 0
    end = 0
    length = len(clean)
    chunks: List[str] = []
    while start < length:
        end = min(start + chunk_size, length)
        if end < length:
            space = clean.rfind(" ", start, end)
            if space > start + chunk_size // 2:
                end = space
        if end <= start:
            end = min(start + chunk_size, length)
        chunk = clean[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= length:
            break
        start = max(end - overlap, 0)
    return chunks


def discover_documents(html_dir: Path, markdown_dir: Path) -> Iterable[SourceDoc]:
    if html_dir.exists():
        for path in sorted(html_dir.rglob("*.htm*")):
            yield parse_html_file(path)
    if markdown_dir.exists():
        for path in sorted(markdown_dir.rglob("*.md")):
            yield parse_markdown_file(path)


def write_chunks(docs: Iterable[SourceDoc], output_path: Path) -> Tuple[int, int]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc_count = 0
    chunk_count = 0
    with output_path.open("w", encoding="utf-8") as fh:
        for doc in docs:
            chunks = chunk_text(doc.text)
            if not chunks:
                continue
            for idx, chunk in enumerate(chunks):
                record = {
                    "source": str(doc.path),
                    "doc_type": doc.doc_type,
                    "title": doc.title,
                    "chunk_index": idx,
                    "text": chunk,
                }
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                chunk_count += 1
            doc_count += 1
    return doc_count, chunk_count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract OMPL documentation into plain-text chunks."
    )
    parser.add_argument(
        "--html-dir",
        type=Path,
        default=Path("ompl/build/doc/ompl_doc"),
        help="Path to generated HTML doc directory.",
    )
    parser.add_argument(
        "--markdown-dir",
        type=Path,
        default=Path("ompl/doc/markdown"),
        help="Path to OMPL markdown sources.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("rag_data/ompl_doc_chunks.jsonl"),
        help="Output JSONL file for text chunks.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    docs = list(discover_documents(args.html_dir, args.markdown_dir))
    doc_count, chunk_count = write_chunks(docs, args.output)
    print(
        f"Wrote {chunk_count} chunks from {doc_count} documents to {args.output.resolve()}"
    )


if __name__ == "__main__":
    main()
