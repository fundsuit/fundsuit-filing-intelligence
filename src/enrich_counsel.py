from __future__ import annotations

import os
import re
from typing import Iterable

import requests

from .models import ConfidenceLevel, CounselContact


EMAIL_PATTERN = re.compile(r"([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"(\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}")
FIRM_PATTERN = re.compile(
    r"(?i)(.+\b(?:LLP|LLC|L\.L\.P\.|L\.L\.C\.|P\.C\.|LAW OFFICES?|ATTORNEYS AT LAW)\b.*)"
)


def enrich_counsel_contacts(
    full_text: str, plaintiff_counsel_names: Iterable[str] | None = None
) -> list[CounselContact]:
    blocks = _extract_signature_blocks(full_text)
    contacts: list[CounselContact] = []

    for block in blocks:
        email = _first_match(EMAIL_PATTERN, block)
        phone = _first_match(PHONE_PATTERN, block)
        firm = _first_match(FIRM_PATTERN, block)
        names = _extract_names(block)
        for name in names:
            contact = CounselContact(
                name=name,
                firm=firm,
                email=email,
                phone=phone,
                source_text=block[:350],
                confidence=_assign_confidence(email=email, phone=phone, firm=firm),
            )
            contacts.append(contact)

    if not contacts and plaintiff_counsel_names:
        contacts.extend(
            CounselContact(name=name.strip(), confidence="Low")
            for name in plaintiff_counsel_names
            if name.strip()
        )

    contacts = _dedupe_contacts(contacts)

    if os.getenv("SEARCH_API_KEY"):
        contacts = [_augment_contact_from_web(contact) for contact in contacts]

    return contacts


def _extract_signature_blocks(text: str) -> list[str]:
    lower_text = text.lower()
    markers = ["respectfully submitted", "attorneys for plaintiff", "counsel for plaintiff", "/s/"]
    starts = sorted({lower_text.find(marker) for marker in markers if lower_text.find(marker) != -1})
    if not starts:
        return []

    blocks: list[str] = []
    for start in starts:
        snippet = text[start : start + 1200]
        blocks.append(snippet)
    return blocks


def _extract_names(block: str) -> list[str]:
    patterns = [
        re.compile(r"/s/\s*([^\n\r,]{3,80})"),
        re.compile(r"(?m)^([A-Z][A-Za-z.\-'\s]{4,80}),\s*Esq\.?$"),
        re.compile(r"(?m)^([A-Z][A-Za-z.\-'\s]{4,80})\n(?:Attorney|Counsel)"),
    ]
    names: list[str] = []
    for pattern in patterns:
        for match in pattern.findall(block):
            cleaned = " ".join(match.split())
            if cleaned and cleaned not in names:
                names.append(cleaned)
    return names


def _first_match(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    if isinstance(match.group(0), str):
        return match.group(0).strip()
    return None


def _assign_confidence(email: str | None, phone: str | None, firm: str | None) -> ConfidenceLevel:
    if email and (phone or firm):
        return "High"
    if email or phone or firm:
        return "Medium"
    return "Low"


def _dedupe_contacts(contacts: list[CounselContact]) -> list[CounselContact]:
    deduped: dict[tuple[str, str], CounselContact] = {}
    for contact in contacts:
        key = (contact.name.lower(), (contact.email or "").lower())
        existing = deduped.get(key)
        if not existing:
            deduped[key] = contact
            continue

        if _confidence_rank(contact.confidence) > _confidence_rank(existing.confidence):
            deduped[key] = contact
    return list(deduped.values())


def _confidence_rank(confidence: ConfidenceLevel) -> int:
    return {"Low": 1, "Medium": 2, "High": 3}[confidence]


def _augment_contact_from_web(contact: CounselContact) -> CounselContact:
    api_key = os.getenv("SEARCH_API_KEY")
    if not api_key:
        return contact

    query = " ".join(part for part in [contact.name, contact.firm, "plaintiff attorney contact"] if part)
    try:
        response = requests.get(
            "https://serpapi.com/search.json",
            params={"engine": "google", "q": query, "api_key": api_key},
            timeout=12,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return contact

    snippets = []
    for result in payload.get("organic_results", [])[:5]:
        snippets.append(result.get("snippet", ""))
        snippets.append(result.get("title", ""))
        snippets.append(result.get("link", ""))

    blob = "\n".join(snippets)
    email = contact.email or _first_match(EMAIL_PATTERN, blob)
    phone = contact.phone or _first_match(PHONE_PATTERN, blob)
    confidence = _assign_confidence(email=email, phone=phone, firm=contact.firm)

    return contact.model_copy(update={"email": email, "phone": phone, "confidence": confidence})
