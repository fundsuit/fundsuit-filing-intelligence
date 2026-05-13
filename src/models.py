from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ConfidenceLevel = Literal["High", "Medium", "Low"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PageChunk(StrictModel):
    page_number: int = Field(..., ge=1)
    citation: str
    text: str


class DocumentRecord(StrictModel):
    row_number: int = Field(..., ge=2, description="1-based row index in the sheet.")
    document_id: str
    drive_file_id: str
    file_name: str
    drive_link: str | None = None
    status: str = "new"
    notes: str | None = None


class SourceCitation(StrictModel):
    page: int = Field(..., ge=1)
    quote: str
    context: str | None = None


class CaseAnalysis(StrictModel):
    case_name: str
    court: str | None = None
    docket_number: str | None = None
    filing_date: str | None = None
    plaintiffs: list[str] = Field(default_factory=list)
    defendants: list[str] = Field(default_factory=list)
    plaintiff_counsel: list[str] = Field(default_factory=list)
    case_category: str
    procedural_posture: str
    settlement_status: str
    class_certification_status: str
    damages: str
    fee_shifting_signal: bool | None = None
    fee_shifting_basis: str | None = None
    b2b_signal: bool | None = None
    funding_fit: str
    positive_drivers: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    source_citations: list[SourceCitation] = Field(default_factory=list)


class ScoredCase(StrictModel):
    lead_score: int | None = Field(default=None, ge=0, le=100)
    recommended_action: str
    score_rationale: list[str] = Field(default_factory=list)


class CounselContact(StrictModel):
    name: str
    firm: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    source_text: str | None = None
    confidence: ConfidenceLevel = "Low"


class CaseResult(StrictModel):
    processed_at: datetime
    document: DocumentRecord
    analysis: CaseAnalysis
    score: ScoredCase
    counsel_contacts: list[CounselContact] = Field(default_factory=list)
