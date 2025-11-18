#!/usr/bin/env python3
"""Generate structured text chunks from OMPL documentation for RAG indexing."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from bs4 import BeautifulSoup


CHUNK_SIZE = 2000
CHUNK_OVERLAP = 200


@dataclass
class SourceDoc:
    path: Path
    text: str
    title: str
    kind: str
    symbol: Optional[str] = None
    namespace: Optional[str] = None


def clean_text(value: str) -> str:
    value = re.sub(r"\r", "\n", value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> Iterable[str]:
    if not text:
        return []
    clean = text
    start = 0
    length = len(clean)
    chunks: List[str] = []
    while start < length:
        end = min(start + chunk_size, length)
        if end < length:
            newline = clean.rfind("\n", start, end)
            if newline > start + 200:
                end = newline
        chunk = clean[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= length:
            break
        start = max(end - overlap, 0)
    return chunks


def detect_metadata(path: Path, soup: BeautifulSoup, title: str) -> Tuple[str, Optional[str], Optional[str]]:
    filename = path.name
    lower = title.lower()
    kind = "page"
    symbol = None

    if filename.startswith("class"):
        kind = "class"
    elif filename.startswith("struct"):
        kind = "struct"
    elif filename.startswith("namespace"):
        kind = "namespace"
    elif filename.startswith("file"):
        kind = "file"
    elif filename.startswith("group__"):
        kind = "tutorial"
    elif "tutorial" in filename:
        kind = "tutorial"

    if "class reference" in lower:
        kind = "class"
        symbol = title.replace("Class Reference", "").strip()
    elif "struct reference" in lower:
        kind = "struct"
        symbol = title.replace("Struct Reference", "").strip()
    elif "namespace reference" in lower:
        kind = "namespace"
        symbol = title.replace("Namespace Reference", "").strip()
    elif "file reference" in lower:
        kind = "file"
        symbol = title.replace("File Reference", "").strip()
    elif "module reference" in lower:
        kind = "module"
        symbol = title.replace("Module Reference", "").strip()

    if not symbol:
        header = soup.find("div", class_="title")
        if header:
            symbol = header.get_text(" ", strip=True)

    namespace = None
    if symbol and "::" in symbol:
        namespace = symbol.rsplit("::", 1)[0]

    return kind, symbol, namespace


def extract_body_text(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "noscript", "header", "footer"]):
        tag.decompose()
    main = soup.select_one("div.contents") or soup.select_one("div#doc-content") or soup.body
    if main is None:
        return ""
    for nav in main.select("div.navpath, div.header, div.headertitle"):
        nav.decompose()
    text = main.get_text("\n", strip=True)
    return clean_text(text)


def parse_html_file(path: Path) -> SourceDoc:
    html = path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else path.stem
    kind, symbol, namespace = detect_metadata(path, soup, title)
    body = extract_body_text(soup)
    header_lines = [f"Title: {title}", f"Kind: {kind}"]
    if symbol:
        header_lines.append(f"Symbol: {symbol}")
    if namespace:
        header_lines.append(f"Namespace: {namespace}")
    text = clean_text("\n".join(header_lines) + "\n\n" + body)
    return SourceDoc(
        path=path,
        text=text,
        title=title,
        kind=kind,
        symbol=symbol,
        namespace=namespace,
    )


def parse_markdown_file(path: Path) -> SourceDoc:
    content = path.read_text(encoding="utf-8", errors="ignore")
    title = path.stem
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("# ").strip() or title
            break
    text = clean_text(content)
    return SourceDoc(path=path, text=text, title=title, kind="markdown", symbol=title, namespace=None)


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
                    "kind": doc.kind,
                    "symbol": doc.symbol,
                    "namespace": doc.namespace,
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
