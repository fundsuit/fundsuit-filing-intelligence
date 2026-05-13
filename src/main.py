from __future__ import annotations

import argparse
import csv
import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .analyze_case import CaseAnalyzer
from .build_digest import build_daily_digest
from .drive_client import DriveClient
from .enrich_counsel import enrich_counsel_contacts
from .models import CaseAnalysis, CaseResult, DocumentRecord, SourceCitation
from .pdf_extract import extract_text_chunks
from .retry_utils import RetryConfig, retry_with_backoff
from .score_case import score_case
from .sheets_client import SheetsClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FundSuit filing intelligence pipeline.")
    parser.add_argument("--dry-run", action="store_true", help="Use local sample rows and PDFs.")
    parser.add_argument("--sheet-id", default=os.getenv("GOOGLE_SHEET_ID"), help="Google Spreadsheet ID.")
    parser.add_argument("--documents-tab", default="Documents")
    parser.add_argument("--cases-tab", default="Cases")
    parser.add_argument("--sample-csv", default="sample_data/mock_documents.csv")
    parser.add_argument("--sample-pdf-dir", default="sample_data/pdfs")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--limit", type=int, default=0, help="Optional max document count.")
    parser.add_argument(
        "--skip-openai",
        action="store_true",
        help="Skip OpenAI analysis and use deterministic local mock extraction.",
    )
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-5-mini"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dry_run = args.dry_run or os.getenv("DRY_RUN", "false").lower() == "true"
    retry_config = RetryConfig.from_env()
    run_date = date.today()

    documents: list[DocumentRecord]
    sheets_client: SheetsClient | None = None
    drive_client: DriveClient | None = None

    if dry_run:
        documents = load_mock_documents(args.sample_csv, args.sample_pdf_dir)
    else:
        if not args.sheet_id:
            raise ValueError("GOOGLE_SHEET_ID (or --sheet-id) is required outside dry-run mode.")
        sheets_client = SheetsClient(spreadsheet_id=args.sheet_id)
        drive_client = DriveClient()
        documents = sheets_client.read_new_documents(documents_tab=args.documents_tab)

    if args.limit > 0:
        documents = documents[: args.limit]

    if not documents:
        print("No new documents found.")
        return 0

    analyzer = None if args.skip_openai else _maybe_build_analyzer(args.model)
    results: list[CaseResult] = []

    for document in documents:
        stage = "resolve_pdf"
        pdf_path: Path | None = None
        chunk_count = 0
        try:
            pdf_path = retry_with_backoff(
                lambda: resolve_pdf_path(
                    document=document,
                    dry_run=dry_run,
                    sample_pdf_dir=args.sample_pdf_dir,
                    drive_client=drive_client,
                ),
                operation_name=f"{document.document_id}:resolve_pdf",
                config=retry_config,
            )
            stage = "extract_text"
            chunks = retry_with_backoff(
                lambda: extract_text_chunks(pdf_path),
                operation_name=f"{document.document_id}:extract_text",
                config=retry_config,
            )
            chunk_count = len(chunks)
            full_text = "\n".join(chunk.text for chunk in chunks)

            if analyzer is not None:
                stage = "openai_analysis"
                analysis = retry_with_backoff(
                    lambda: analyzer.analyze(document=document, chunks=chunks),
                    operation_name=f"{document.document_id}:openai_analysis",
                    config=retry_config,
                )
            else:
                analysis = mock_analysis(document=document, text=full_text, chunks=chunks)

            stage = "score_case"
            score = score_case(analysis)

            stage = "enrich_counsel"
            counsel_contacts = retry_with_backoff(
                lambda: enrich_counsel_contacts(full_text, analysis.plaintiff_counsel),
                operation_name=f"{document.document_id}:enrich_counsel",
                config=retry_config,
            )
            result = CaseResult(
                processed_at=datetime.utcnow(),
                document=document,
                analysis=analysis,
                score=score,
                counsel_contacts=counsel_contacts,
            )
            results.append(result)
            write_document_artifact(
                output_dir=args.output_dir,
                run_date=run_date,
                document=document,
                status="processed",
                stage="completed",
                result=result,
                pdf_path=pdf_path,
                chunk_count=chunk_count,
            )

            if sheets_client and not dry_run:
                retry_with_backoff(
                    lambda: sheets_client.update_document_status(
                        row_number=document.row_number,
                        status="processed",
                        documents_tab=args.documents_tab,
                        notes="OK",
                    ),
                    operation_name=f"{document.document_id}:update_status_processed",
                    config=retry_config,
                )
        except Exception as exc:
            print(f"[ERROR] {document.document_id} ({stage}): {exc}")
            write_document_artifact(
                output_dir=args.output_dir,
                run_date=run_date,
                document=document,
                status="failed",
                stage=stage,
                error=str(exc),
                pdf_path=pdf_path,
                chunk_count=chunk_count,
            )
            if sheets_client and not dry_run:
                try:
                    retry_with_backoff(
                        lambda: sheets_client.update_document_status(
                            row_number=document.row_number,
                            status="failed",
                            documents_tab=args.documents_tab,
                            notes=f"{stage}: {str(exc)[:430]}",
                        ),
                        operation_name=f"{document.document_id}:update_status_failed",
                        config=retry_config,
                    )
                except Exception as status_exc:
                    print(f"[ERROR] {document.document_id} (status_update_failed): {status_exc}")

    if sheets_client and results and not dry_run:
        retry_with_backoff(
            lambda: sheets_client.write_case_analysis_rows(results=results, cases_tab=args.cases_tab),
            operation_name="write_case_analysis_rows",
            config=retry_config,
        )

    md_path, html_path = build_daily_digest(results=results, output_dir=args.output_dir)
    print(f"Processed {len(results)} document(s).")
    print(f"Digest (Markdown): {md_path}")
    print(f"Digest (HTML): {html_path}")
    return 0


def _maybe_build_analyzer(model: str) -> CaseAnalyzer | None:
    if not os.getenv("OPENAI_API_KEY"):
        return None
    return CaseAnalyzer(model=model)


def write_document_artifact(
    *,
    output_dir: str,
    run_date: date,
    document: DocumentRecord,
    status: str,
    stage: str,
    result: CaseResult | None = None,
    error: str | None = None,
    pdf_path: Path | None = None,
    chunk_count: int | None = None,
) -> Path:
    artifacts_dir = Path(output_dir) / "artifacts" / run_date.isoformat()
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    safe_document_id = re.sub(r"[^A-Za-z0-9._-]+", "_", document.document_id).strip("_") or (
        f"row_{document.row_number}"
    )
    artifact_path = artifacts_dir / f"{safe_document_id}.json"

    payload: dict[str, Any] = {
        "status": status,
        "stage": stage,
        "document": document.model_dump(mode="json"),
        "pdf_path": str(pdf_path) if pdf_path else None,
        "chunk_count": chunk_count,
        "created_at": datetime.utcnow().isoformat(),
    }
    if result is not None:
        payload["processed_at"] = result.processed_at.isoformat()
        payload["analysis"] = result.analysis.model_dump(mode="json")
        payload["score"] = result.score.model_dump(mode="json")
        payload["counsel_contacts"] = [
            contact.model_dump(mode="json") for contact in result.counsel_contacts
        ]
    if error:
        payload["error"] = error

    artifact_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return artifact_path


def load_mock_documents(csv_path: str, sample_pdf_dir: str) -> list[DocumentRecord]:
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Mock CSV not found: {path}")

    documents: list[DocumentRecord] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for idx, row in enumerate(reader, start=2):
            if row.get("status", "").strip().lower() != "new":
                continue
            file_name = row.get("file_name", "").strip()
            drive_file_id = row.get("drive_file_id", "").strip()
            if not file_name or not drive_file_id:
                continue

            pdf_path = row.get("pdf_path", "").strip()
            if not pdf_path:
                pdf_path = str(Path(sample_pdf_dir) / file_name)
            documents.append(
                DocumentRecord(
                    row_number=idx,
                    document_id=row.get("document_id", f"mock-{idx}").strip(),
                    drive_file_id=drive_file_id,
                    file_name=file_name,
                    drive_link=row.get("drive_link", "").strip() or None,
                    status="new",
                    notes=pdf_path,
                )
            )
    return documents


def resolve_pdf_path(
    document: DocumentRecord,
    dry_run: bool,
    sample_pdf_dir: str,
    drive_client: DriveClient | None = None,
) -> Path:
    if dry_run:
        if document.notes:
            path = Path(document.notes)
        else:
            path = Path(sample_pdf_dir) / document.file_name
        if not path.exists():
            raise FileNotFoundError(f"Local PDF missing: {path}")
        return path

    if not drive_client:
        raise RuntimeError("Drive client required for non-dry-run processing.")

    tmp_dir = Path("/tmp/fundsuit-filing-intelligence")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    destination = tmp_dir / f"{document.drive_file_id}.pdf"
    return drive_client.download_pdf_by_id(file_id=document.drive_file_id, destination=destination)


def mock_analysis(document: DocumentRecord, text: str, chunks: list) -> CaseAnalysis:
    lowered = text.lower()
    case_name = _first_line(text) or document.file_name
    category = _category_from_text(lowered)
    if any(token in lowered for token in ["no settlement", "not settled", "unsettled"]):
        settlement_status = "Active / Unknown"
    elif "settled" in lowered or "settlement reached" in lowered:
        settlement_status = "Settled"
    else:
        settlement_status = "Active / Unknown"
    if "class certification granted" in lowered or "certified class" in lowered:
        class_status = "Granted"
    elif any(
        phrase in lowered
        for phrase in [
            "class certification denied",
            "denies class certification",
            "class claims are struck",
            "strikes class allegations",
        ]
    ):
        class_status = "Denied/Struck"
    else:
        class_status = "Unknown"

    damages = _extract_damages(lowered)
    fee_shift = "prevailing party" in lowered or "fee shifting" in lowered or "attorneys' fees" in lowered
    b2b = any(term in lowered for term in ["breach of contract", "commercial dispute", "supply agreement"])

    positive_drivers = []
    if class_status == "Granted":
        positive_drivers.append("Class certification granted")
    if b2b:
        positive_drivers.append("B2B commercial dispute profile")
    if fee_shift:
        positive_drivers.append("Potential prevailing-party fee provision")

    risk_flags = []
    if class_status == "Denied/Struck":
        risk_flags.append("Class certification denied or struck")
    if "arbitration" in lowered:
        risk_flags.append("Arbitration clause may limit court recovery")

    citations = []
    for chunk in chunks[:3]:
        quote = " ".join(chunk.text.split()[:20])
        citations.append(SourceCitation(page=chunk.page_number, quote=quote))

    counsel = _extract_counsel_names_fallback(text)

    return CaseAnalysis(
        case_name=case_name,
        court="Unknown",
        docket_number=None,
        filing_date=None,
        plaintiffs=[],
        defendants=[],
        plaintiff_counsel=counsel,
        case_category=category,
        procedural_posture="Initial filing review",
        settlement_status=settlement_status,
        class_certification_status=class_status,
        damages=damages,
        fee_shifting_signal=fee_shift if fee_shift else None,
        fee_shifting_basis="Detected keyword mention; verify in source text." if fee_shift else None,
        b2b_signal=b2b if b2b else None,
        funding_fit="Strong" if b2b and class_status != "Denied/Struck" else "Moderate",
        positive_drivers=positive_drivers,
        risk_flags=risk_flags,
        missing_information=["Court", "Docket number", "Filing date"],
        source_citations=citations,
    )


def _first_line(text: str) -> str | None:
    for line in text.splitlines():
        clean = line.strip()
        if clean:
            return clean[:180]
    return None


def _category_from_text(lowered_text: str) -> str:
    if "antitrust" in lowered_text:
        return "Antitrust"
    if "breach of contract" in lowered_text:
        return "Commercial Contract"
    if "securities" in lowered_text:
        return "Securities"
    if "employment" in lowered_text:
        return "Employment"
    if "consumer" in lowered_text:
        return "Consumer Protection"
    return "General Commercial Litigation"


def _extract_damages(lowered_text: str) -> str:
    money_matches = re.findall(r"\$[\d,]+", lowered_text)
    if money_matches:
        return "Claimed damages include " + ", ".join(money_matches[:3])
    if "damages" in lowered_text:
        return "Damages requested, amount unspecified."
    return "No explicit damages amount identified."


def _extract_counsel_names_fallback(text: str) -> list[str]:
    matches = re.findall(r"/s/\s*([^\n\r,]{4,80})", text)
    return [" ".join(match.split()) for match in matches[:5]]


if __name__ == "__main__":
    raise SystemExit(main())
