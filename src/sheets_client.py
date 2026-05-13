from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import Resource, build

from .models import CaseResult, DocumentRecord


SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

CASE_HEADERS = [
    "processed_at",
    "document_id",
    "drive_file_id",
    "file_name",
    "drive_link",
    "case_name",
    "court",
    "docket_number",
    "filing_date",
    "case_category",
    "procedural_posture",
    "settlement_status",
    "class_certification_status",
    "damages",
    "fee_shifting_signal",
    "fee_shifting_basis",
    "b2b_signal",
    "funding_fit",
    "lead_score",
    "recommended_action",
    "positive_drivers",
    "risk_flags",
    "missing_information",
    "source_citations",
    "plaintiff_counsel",
    "counsel_contacts",
    "score_rationale",
]


def build_case_analysis_row(result: CaseResult) -> list[str]:
    citation_value = "; ".join(
        f"p.{citation.page}: {citation.quote}" for citation in result.analysis.source_citations
    )
    contacts_value = "; ".join(
        f"{contact.name} ({contact.firm or 'Unknown firm'}) <{contact.email or 'n/a'}> [{contact.confidence}]"
        for contact in result.counsel_contacts
    )
    return [
        result.processed_at.isoformat(),
        result.document.document_id,
        result.document.drive_file_id,
        result.document.file_name,
        result.document.drive_link or "",
        result.analysis.case_name,
        result.analysis.court or "",
        result.analysis.docket_number or "",
        result.analysis.filing_date or "",
        result.analysis.case_category,
        result.analysis.procedural_posture,
        result.analysis.settlement_status,
        result.analysis.class_certification_status,
        result.analysis.damages,
        "" if result.analysis.fee_shifting_signal is None else str(result.analysis.fee_shifting_signal),
        result.analysis.fee_shifting_basis or "",
        "" if result.analysis.b2b_signal is None else str(result.analysis.b2b_signal),
        result.analysis.funding_fit,
        "" if result.score.lead_score is None else str(result.score.lead_score),
        result.score.recommended_action,
        "; ".join(result.analysis.positive_drivers),
        "; ".join(result.analysis.risk_flags),
        "; ".join(result.analysis.missing_information),
        citation_value,
        "; ".join(result.analysis.plaintiff_counsel),
        contacts_value,
        "; ".join(result.score.score_rationale),
    ]


def _load_service_account_info(raw_or_path: str) -> dict[str, Any]:
    raw_or_path = raw_or_path.strip()
    if raw_or_path.startswith("{"):
        return json.loads(raw_or_path)
    with open(raw_or_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _normalize_header(value: str) -> str:
    return value.strip().lower().replace(" ", "_")


def _index_to_column(index: int) -> str:
    label = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        label = chr(65 + remainder) + label
    return label


class SheetsClient:
    def __init__(self, spreadsheet_id: str, credentials: str | None = None) -> None:
        source = credentials or os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        if not source:
            raise ValueError("Missing GOOGLE_SERVICE_ACCOUNT_JSON for Sheets authentication.")

        info = _load_service_account_info(source)
        creds = service_account.Credentials.from_service_account_info(info, scopes=SHEETS_SCOPES)
        self._service: Resource = build("sheets", "v4", credentials=creds, cache_discovery=False)
        self.spreadsheet_id = spreadsheet_id

    def _get_values(self, range_name: str) -> list[list[str]]:
        response = (
            self._service.spreadsheets()
            .values()
            .get(spreadsheetId=self.spreadsheet_id, range=range_name)
            .execute()
        )
        return response.get("values", [])

    def _update_values(self, range_name: str, values: list[list[str]]) -> None:
        (
            self._service.spreadsheets()
            .values()
            .update(
                spreadsheetId=self.spreadsheet_id,
                range=range_name,
                valueInputOption="RAW",
                body={"values": values},
            )
            .execute()
        )

    def _append_values(self, range_name: str, values: list[list[str]]) -> None:
        (
            self._service.spreadsheets()
            .values()
            .append(
                spreadsheetId=self.spreadsheet_id,
                range=range_name,
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": values},
            )
            .execute()
        )

    def read_new_documents(self, documents_tab: str = "Documents") -> list[DocumentRecord]:
        values = self._get_values(f"{documents_tab}!A:Z")
        if not values:
            return []

        headers = [_normalize_header(value) for value in values[0]]
        records: list[DocumentRecord] = []
        for row_number, row_values in enumerate(values[1:], start=2):
            row_dict: dict[str, str] = {}
            for idx, header in enumerate(headers):
                row_dict[header] = row_values[idx].strip() if idx < len(row_values) else ""

            status = row_dict.get("status", "").lower()
            if status != "new":
                continue

            drive_file_id = (
                row_dict.get("drive_file_id")
                or row_dict.get("file_id")
                or row_dict.get("pdf_file_id")
                or ""
            )
            file_name = row_dict.get("file_name") or row_dict.get("document_name") or ""
            if not drive_file_id or not file_name:
                continue

            records.append(
                DocumentRecord(
                    row_number=row_number,
                    document_id=row_dict.get("document_id") or f"doc-{row_number}",
                    drive_file_id=drive_file_id,
                    file_name=file_name,
                    drive_link=row_dict.get("drive_link") or row_dict.get("file_link") or None,
                    status=status,
                    notes=row_dict.get("notes") or None,
                )
            )
        return records

    def ensure_case_headers(self, cases_tab: str = "Cases") -> None:
        first_row = self._get_values(f"{cases_tab}!1:1")
        if not first_row:
            self._update_values(f"{cases_tab}!A1", [CASE_HEADERS])

    def write_case_analysis_rows(self, results: list[CaseResult], cases_tab: str = "Cases") -> None:
        if not results:
            return
        self.ensure_case_headers(cases_tab=cases_tab)

        rows = [build_case_analysis_row(result) for result in results]

        self._append_values(f"{cases_tab}!A:A", rows)

    def update_document_status(
        self,
        row_number: int,
        status: str,
        documents_tab: str = "Documents",
        notes: str | None = None,
    ) -> None:
        header_row = self._get_values(f"{documents_tab}!1:1")
        if not header_row:
            raise ValueError(f"{documents_tab} tab appears empty.")
        headers = [_normalize_header(value) for value in header_row[0]]

        status_idx = headers.index("status") if "status" in headers else None
        notes_idx = headers.index("notes") if "notes" in headers else None
        processed_idx = (
            headers.index("last_processed_at") if "last_processed_at" in headers else None
        )
        if status_idx is None:
            raise ValueError("Documents tab must have a status column.")

        updates = []
        status_col = _index_to_column(status_idx)
        updates.append(
            {
                "range": f"{documents_tab}!{status_col}{row_number}",
                "values": [[status]],
            }
        )

        if notes_idx is not None:
            notes_col = _index_to_column(notes_idx)
            updates.append(
                {
                    "range": f"{documents_tab}!{notes_col}{row_number}",
                    "values": [[notes or ""]],
                }
            )

        if processed_idx is not None:
            processed_col = _index_to_column(processed_idx)
            updates.append(
                {
                    "range": f"{documents_tab}!{processed_col}{row_number}",
                    "values": [[datetime.utcnow().isoformat()]],
                }
            )

        (
            self._service.spreadsheets()
            .values()
            .batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={"valueInputOption": "RAW", "data": updates},
            )
            .execute()
        )
