from __future__ import annotations

from src.models import CaseAnalysis
from src.score_case import score_case


def _analysis(**overrides) -> CaseAnalysis:
    base = {
        "case_name": "Acme v. Titan",
        "court": "D. Colo.",
        "docket_number": "1:26-cv-0001",
        "filing_date": "2026-05-01",
        "plaintiffs": ["Acme"],
        "defendants": ["Titan"],
        "plaintiff_counsel": ["Jordan Reyes"],
        "case_category": "Commercial Contract",
        "procedural_posture": "Initial filing",
        "settlement_status": "Active / Unknown",
        "class_certification_status": "Unknown",
        "damages": "Damages in excess of $2,000,000",
        "fee_shifting_signal": None,
        "fee_shifting_basis": None,
        "b2b_signal": None,
        "funding_fit": "Moderate",
        "positive_drivers": [],
        "risk_flags": [],
        "missing_information": [],
        "source_citations": [],
    }
    base.update(overrides)
    return CaseAnalysis(**base)


def test_settled_cases_are_comparable_only() -> None:
    analysis = _analysis(settlement_status="Settled by stipulation")
    scored = score_case(analysis)
    assert scored.lead_score is None
    assert scored.recommended_action == "Comparable Only"


def test_not_settled_phrase_does_not_trigger_comparable_only() -> None:
    analysis = _analysis(settlement_status="No settlement has been reached.")
    scored = score_case(analysis)
    assert scored.lead_score is not None
    assert scored.recommended_action != "Comparable Only"


def test_b2b_granted_class_and_fee_shift_score_as_top_prospect() -> None:
    analysis = _analysis(
        class_certification_status="Granted",
        b2b_signal=True,
        fee_shifting_signal=True,
        positive_drivers=["Class certification granted", "Strong liability facts"],
    )
    scored = score_case(analysis)
    assert scored.lead_score is not None
    assert scored.lead_score >= 75
    assert scored.recommended_action == "Pursue Immediately"


def test_denied_class_with_large_individual_damages_scores_above_non_financeable_case() -> None:
    with_large_damages = _analysis(
        class_certification_status="Denied",
        b2b_signal=True,
        damages="Named plaintiffs each claim $3,250,000 in individual damages.",
    )
    without_large_damages = _analysis(
        class_certification_status="Denied",
        b2b_signal=True,
        damages="Damages requested, amount unspecified.",
    )
    scored_large = score_case(with_large_damages)
    scored_small = score_case(without_large_damages)
    assert scored_large.lead_score is not None
    assert scored_small.lead_score is not None
    assert scored_large.lead_score > scored_small.lead_score

