#!/usr/bin/env python3
"""Chunk survey papers into structured JSONL for RAG."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

import fitz  # PyMuPDF


CHUNK_SIZE = 1800
CHUNK_OVERLAP = 200
REFERENCE_HEADING_PATTERN = re.compile(
    r"(?im)^\s*(references|literature\s+cited|bibliography)\s*$"
)


@dataclass
class SectionText:
    title: str
    level: int
    page_start: int
    page_end: int
    text: str


def clean_text(value: str) -> str:
    value = re.sub(r"\r", "\n", value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def chunk_text(text: str, chunk_size: int, overlap: int) -> Iterable[str]:
    if not text:
        return []
    start = 0
    text_len = len(text)
    chunks: List[str] = []
    while start < text_len:
        end = min(start + chunk_size, text_len)
        if end < text_len:
            newline = text.rfind("\n", start, end)
            if newline > start + 200:
                end = newline
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= text_len:
            break
        start = max(end - overlap, 0)
    return chunks


def is_reference_section(title: str) -> bool:
    lower = title.lower()
    return (
        "reference" in lower
        or "bibliograph" in lower
        or "literature cited" in lower
    )


def split_reference_entries(text: str) -> List[str]:
    pattern = re.compile(r"^\s*(\[\d+\]|\d+\.)")
    lines = text.splitlines()
    entries: List[List[str]] = []
    current: List[str] = []

    def flush(buffer: List[str]) -> None:
        cleaned = [line for line in buffer if line.strip()]
        if cleaned:
            entries.append(cleaned)

    for line in lines:
        if pattern.match(line):
            if current:
                flush(current)
            current = [line]
        else:
            current.append(line)
    if current:
        flush(current)

    flat_entries = ["\n".join(entry).strip() for entry in entries if entry]
    if flat_entries:
        return flat_entries
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    return blocks or [text.strip()]


def chunk_reference_section(
    header_text: str, entries: List[str], chunk_size: int
) -> List[str]:
    prefix = clean_text(header_text)
    if not entries:
        return [prefix]
    base = prefix + "\n\n"
    limit = max(chunk_size - len(prefix) - 2, chunk_size // 2)
    if limit <= 0:
        limit = chunk_size
    chunks: List[str] = []
    current: List[str] = []
    current_len = 0
    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue
        addition_len = len(entry) + (2 if current else 0)
        if current and current_len + addition_len > limit:
            chunk_body = "\n\n".join(current)
            chunks.append(clean_text(base + chunk_body))
            current = [entry]
            current_len = len(entry)
        else:
            if not current:
                current_len = len(entry)
            else:
                current_len += addition_len
            current.append(entry)
    if current:
        chunk_body = "\n\n".join(current)
        chunks.append(clean_text(base + chunk_body))
    return chunks


def extract_page_texts(doc: fitz.Document) -> List[str]:
    pages: List[str] = []
    for idx in range(doc.page_count):
        page = doc.load_page(idx)
        text = page.get_text("text")
        pages.append(clean_text(text))
    return pages


def section_ranges_from_toc(
    toc: Sequence[Sequence[int | str]],
    total_pages: int,
) -> List[SectionText]:
    sections: List[SectionText] = []
    if not toc:
        return sections
    for idx, entry in enumerate(toc):
        if len(entry) < 3:
            continue
        level = int(entry[0])
        title = str(entry[1]).strip() or "Untitled"
        start_page = max(int(entry[2]), 1)
        start_idx = min(start_page - 1, total_pages)
        end_idx = total_pages
        for next_entry in toc[idx + 1 :]:
            if len(next_entry) < 3:
                continue
            next_page = max(int(next_entry[2]), 1) - 1
            if next_page > start_idx:
                end_idx = next_page
                break
        if end_idx <= start_idx:
            continue
        sections.append(
            SectionText(
                title=title,
                level=level,
                page_start=start_page,
                page_end=end_idx,
                text="",  # placeholder, filled later
            )
        )
    return sections


def fill_section_texts(sections: List[SectionText], pages: List[str]) -> List[SectionText]:
    if not sections:
        return sections
    total_pages = len(pages)
    for idx, section in enumerate(sections):
        start_idx = min(section.page_start - 1, total_pages)
        end_idx = min(section.page_end, total_pages)
        section.text = clean_text("\n\n".join(pages[start_idx:end_idx]))
    return [sec for sec in sections if sec.text]


def fallback_sections(pages: List[str], paper_title: str) -> List[SectionText]:
    return [
        SectionText(
            title=paper_title,
            level=1,
            page_start=1,
            page_end=len(pages),
            text=clean_text("\n\n".join(pages)),
        )
    ]


def infer_topic(paper_title: str) -> str:
    lower = paper_title.lower()
    if "task and" in lower or "task-and" in lower or "tam" in lower:
        return "task_and_motion_planning"
    if "task" in lower and "motion" in lower:
        return "task_and_motion_planning"
    return "motion_planning"


def extract_reference_tail(text: str) -> Optional[tuple[str, str, str]]:
    matches = list(REFERENCE_HEADING_PATTERN.finditer(text))
    if not matches:
        return None
    match = matches[-1]
    tail = text[match.end() :].strip()
    if not tail:
        return None
    body = text[: match.start()].rstrip()
    heading = match.group(0).strip()
    if not heading:
        heading = "References"
    return body, heading, tail


def expand_reference_sections(sections: List[SectionText]) -> List[SectionText]:
    expanded: List[SectionText] = []
    for section in sections:
        if is_reference_section(section.title):
            expanded.append(section)
            continue
        result = extract_reference_tail(section.text)
        if not result:
            expanded.append(section)
            continue
        body, heading, refs = result
        if body.strip():
            expanded.append(
                SectionText(
                    title=section.title,
                    level=section.level,
                    page_start=section.page_start,
                    page_end=section.page_end,
                    text=body.strip(),
                )
            )
        expanded.append(
            SectionText(
                title=heading,
                level=max(section.level + 1, 1),
                page_start=section.page_end,
                page_end=section.page_end,
                text=refs,
            )
        )
    return expanded


def process_pdf(
    pdf_path: Path,
    *,
    chunk_size: int,
    overlap: int,
) -> List[dict]:
    doc = fitz.open(pdf_path)
    paper_title = doc.metadata.get("title") or pdf_path.stem
    page_texts = extract_page_texts(doc)
    toc = doc.get_toc(simple=False) or doc.get_toc()
    sections = section_ranges_from_toc(toc, len(page_texts))
    sections = fill_section_texts(sections, page_texts)
    if not sections:
        sections = fallback_sections(page_texts, paper_title)
    sections = expand_reference_sections(sections)

    topic = infer_topic(paper_title)
    records: List[dict] = []
    for section in sections:
        header_lines = [
            f"Paper: {paper_title}",
            f"Section: {section.title}",
            f"Level: {section.level}",
            f"Pages: {section.page_start}-{section.page_end}",
        ]
        header_text = "\n".join(header_lines)
        body_text = clean_text(section.text)
        if is_reference_section(section.title):
            entries = split_reference_entries(body_text)
            section_chunks = chunk_reference_section(header_text, entries, chunk_size)
        else:
            section_text = clean_text(header_text + "\n\n" + body_text)
            section_chunks = chunk_text(section_text, chunk_size, overlap)
        for idx, chunk in enumerate(section_chunks):
            records.append(
                {
                    "source": str(pdf_path),
                    "title": section.title,
                    "paper_title": paper_title,
                    "section_title": section.title,
                    "section_level": section.level,
                    "page_start": section.page_start,
                    "page_end": section.page_end,
                    "topic": topic,
                    "kind": "paper",
                    "chunk_index": idx,
                    "text": chunk,
                }
            )
    return records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract structured chunks from survey papers."
    )
    parser.add_argument(
        "--pdf-dir",
        type=Path,
        default=Path("paper"),
        help="Directory containing survey PDFs.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("rag_data/survey_papers_chunks.jsonl"),
        help="Destination JSONL file.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=CHUNK_SIZE,
        help="Maximum characters per chunk.",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=CHUNK_OVERLAP,
        help="Overlap size between chunks.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pdf_dir = args.pdf_dir
    if not pdf_dir.exists():
        raise SystemExit(f"PDF directory not found: {pdf_dir}")
    output_path = args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    total_docs = 0
    total_chunks = 0
    with output_path.open("w", encoding="utf-8") as handle:
        for pdf_path in sorted(pdf_dir.glob("*.pdf")):
            records = process_pdf(
                pdf_path, chunk_size=args.chunk_size, overlap=args.chunk_overlap
            )
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(f"Processed {pdf_path.name}: {len(records)} chunks")
            total_docs += 1
            total_chunks += len(records)
    print(
        f"Wrote {total_chunks} chunks from {total_docs} papers to {output_path.resolve()}"
    )


if __name__ == "__main__":
    main()
