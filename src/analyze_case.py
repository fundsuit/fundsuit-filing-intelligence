from __future__ import annotations

import json
import os
from typing import Any

from openai import OpenAI

from .models import CaseAnalysis, DocumentRecord, PageChunk
from .pdf_extract import format_chunks_for_prompt


SYSTEM_PROMPT = """You are a legal analyst for litigation funding triage.
Extract only facts supported by the provided filing text.
Always cite source pages in source_citations.
If information is missing, place it in missing_information instead of guessing.
Return valid JSON that strictly matches the schema."""


class CaseAnalyzer:
    def __init__(self, model: str = "gpt-5-mini", api_key: str | None = None) -> None:
        self.model = model
        self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))

    def analyze(self, document: DocumentRecord, chunks: list[PageChunk]) -> CaseAnalysis:
        if not chunks:
            raise ValueError(f"No extractable text found for document {document.document_id}.")

        text_payload = format_chunks_for_prompt(chunks)
        user_prompt = (
            f"Document ID: {document.document_id}\n"
            f"File Name: {document.file_name}\n\n"
            "Produce:\n"
            "- case metadata\n"
            "- case category\n"
            "- procedural posture\n"
            "- settlement status\n"
            "- class certification status\n"
            "- damages\n"
            "- fee-shifting signal and basis\n"
            "- B2B signal\n"
            "- funding fit\n"
            "- positive drivers\n"
            "- risk flags\n"
            "- missing information\n"
            "- source citations with page numbers and short quotes\n\n"
            "Filing text:\n"
            f"{text_payload}"
        )

        schema = CaseAnalysis.model_json_schema()
        completion = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "case_analysis",
                    "strict": True,
                    "schema": schema,
                },
            },
        )

        message = completion.choices[0].message
        refusal = getattr(message, "refusal", None)
        if refusal:
            raise RuntimeError(f"Model refused request: {refusal}")

        raw = _message_content_to_text(message.content)
        payload: dict[str, Any] = json.loads(raw)
        return CaseAnalysis.model_validate(payload)


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
            elif hasattr(item, "text"):
                parts.append(str(getattr(item, "text")))
        joined = "".join(parts).strip()
        if joined:
            return joined

    return str(content)
