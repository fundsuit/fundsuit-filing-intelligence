from __future__ import annotations

from datetime import datetime

from src.models import (
    CaseAnalysis,
    CaseResult,
    CounselContact,
    DocumentRecord,
    ScoredCase,
    SourceCitation,
)
from src.sheets_client import CASE_HEADERS, build_case_analysis_row


def _result(
    *,
    lead_score: int | None = 81,
    b2b_signal: bool | None = True,
    fee_shifting_signal: bool | None = True,
) -> CaseResult:
    document = DocumentRecord(
        row_number=2,
        document_id="doc-001",
        drive_file_id="drive-abc",
        file_name="filing.pdf",
        drive_link="https://drive.google.com/file/d/drive-abc/view",
        status="new",
    )
    analysis = CaseAnalysis(
        case_name="Acme Components LLC v. Titan Logistics Inc.",
        court="D. Colo.",
        docket_number="1:26-cv-1184",
        filing_date="2026-05-12",
        plaintiffs=["Acme Components LLC"],
        defendants=["Titan Logistics Inc."],
        plaintiff_counsel=["Jordan M. Reyes"],
        case_category="Commercial Contract",
        procedural_posture="Complaint",
        settlement_status="Active / Unknown",
        class_certification_status="Unknown",
        damages="Damages in excess of $4,500,000",
        fee_shifting_signal=fee_shifting_signal,
        fee_shifting_basis="Prevailing-party clause in supply agreement.",
        b2b_signal=b2b_signal,
        funding_fit="Strong",
        positive_drivers=["B2B commercial dispute"],
        risk_flags=["Arbitration risk"],
        missing_information=["Judge assignment"],
        source_citations=[SourceCitation(page=3, quote="prevailing party may recover attorneys' fees")],
    )
    score = ScoredCase(
        lead_score=lead_score,
        recommended_action="Pursue Immediately" if lead_score else "Comparable Only",
        score_rationale=["Base score set to 50", "Final score computed"],
    )
    contacts = [
        CounselContact(
            name="Jordan M. Reyes",
            firm="REYES & KLINE LLP",
            email="jreyes@reyeskline.com",
            phone="(303) 555-0145",
            confidence="High",
        )
    ]
    return CaseResult(
        processed_at=datetime(2026, 5, 12, 14, 0, 0),
        document=document,
        analysis=analysis,
        score=score,
        counsel_contacts=contacts,
    )


def test_build_case_analysis_row_matches_header_shape() -> None:
    row = build_case_analysis_row(_result())
    assert len(row) == len(CASE_HEADERS)
    assert row[CASE_HEADERS.index("document_id")] == "doc-001"
    assert row[CASE_HEADERS.index("case_name")] == "Acme Components LLC v. Titan Logistics Inc."
    assert row[CASE_HEADERS.index("lead_score")] == "81"
    assert row[CASE_HEADERS.index("b2b_signal")] == "True"
    assert "p.3:" in row[CASE_HEADERS.index("source_citations")]


def test_build_case_analysis_row_handles_optional_blanks() -> None:
    row = build_case_analysis_row(_result(lead_score=None, b2b_signal=None, fee_shifting_signal=None))
    assert row[CASE_HEADERS.index("lead_score")] == ""
    assert row[CASE_HEADERS.index("b2b_signal")] == ""
    assert row[CASE_HEADERS.index("fee_shifting_signal")] == ""

