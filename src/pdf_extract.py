from __future__ import annotations

from pathlib import Path

import fitz

from .models import PageChunk


def _split_text(text: str, max_chars: int, overlap: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunks.append(text[start:end].strip())
        if end == len(text):
            break
        start = max(0, end - overlap)
    return [chunk for chunk in chunks if chunk]


def extract_text_chunks(
    pdf_path: str | Path, max_chars: int = 5000, overlap: int = 500
) -> list[PageChunk]:
    pdf_path = Path(pdf_path)
    chunks: list[PageChunk] = []

    with fitz.open(pdf_path) as document:
        for page_index, page in enumerate(document, start=1):
            text = page.get_text("text").strip()
            if not text:
                continue
            for chunk_index, chunk in enumerate(_split_text(text, max_chars=max_chars, overlap=overlap), start=1):
                suffix = f".{chunk_index}" if chunk_index > 1 else ""
                citation = f"p.{page_index}{suffix}"
                chunks.append(PageChunk(page_number=page_index, citation=citation, text=chunk))

    return chunks


def format_chunks_for_prompt(chunks: list[PageChunk]) -> str:
    return "\n\n".join(f"[{chunk.citation}]\n{chunk.text}" for chunk in chunks)

