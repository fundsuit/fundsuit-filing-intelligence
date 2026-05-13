from __future__ import annotations

import re

from .models import CaseAnalysis, ScoredCase


MONEY_PATTERN = re.compile(r"\$?\s?(\d[\d,]{2,})")


def score_case(analysis: CaseAnalysis) -> ScoredCase:
    rationale: list[str] = []

    settlement_text = analysis.settlement_status.lower()
    explicit_not_settled = any(
        token in settlement_text for token in ["not settled", "no settlement", "unsettled", "active"]
    )
    if "settled" in settlement_text and not explicit_not_settled:
        rationale.append("Matter appears settled; treated as comparable only.")
        return ScoredCase(
            lead_score=None,
            recommended_action="Comparable Only",
            score_rationale=rationale,
        )

    score = 50
    rationale.append("Base score set to 50 for active litigation.")

    class_text = analysis.class_certification_status.lower()
    if "granted" in class_text:
        score += 25
        rationale.append("Class certification granted: major positive (+25).")
    elif "denied" in class_text or "struck" in class_text:
        if _independent_damages_financeable(analysis.damages):
            score -= 10
            rationale.append(
                "Class pathway weak but individual damages may be independently financeable (-10)."
            )
        else:
            score -= 30
            rationale.append("Class certification denied/struck with no clear independent damages (-30).")

    if analysis.b2b_signal is True:
        score += 20
        rationale.append("B2B commercial dispute signal: first-class target (+20).")
    elif analysis.b2b_signal is False:
        score -= 10
        rationale.append("Non-B2B framing lowers fit for this strategy (-10).")

    if analysis.fee_shifting_signal is True:
        score += 10
        rationale.append("Prevailing-party fee provision signal present (+10, verify source text).")

    if analysis.risk_flags:
        penalty = min(20, len(analysis.risk_flags) * 5)
        score -= penalty
        rationale.append(f"Risk flag penalty applied (-{penalty}).")

    if analysis.positive_drivers:
        bonus = min(10, len(analysis.positive_drivers) * 2)
        score += bonus
        rationale.append(f"Positive driver bonus applied (+{bonus}).")

    score = max(0, min(100, score))
    action = _recommended_action(score=score)
    rationale.append(f"Final score: {score}. Recommended action: {action}.")

    return ScoredCase(lead_score=score, recommended_action=action, score_rationale=rationale)


def _independent_damages_financeable(damages_text: str) -> bool:
    amounts = []
    for match in MONEY_PATTERN.findall(damages_text or ""):
        try:
            value = int(match.replace(",", ""))
            amounts.append(value)
        except ValueError:
            continue
    return any(amount >= 1_000_000 for amount in amounts)


def _recommended_action(score: int) -> str:
    if score >= 75:
        return "Pursue Immediately"
    if score >= 55:
        return "Monitor / Light Outreach"
    if score >= 35:
        return "Needs More Diligence"
    return "Reject"
