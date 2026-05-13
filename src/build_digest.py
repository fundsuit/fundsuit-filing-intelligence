from __future__ import annotations

from datetime import date
from pathlib import Path

import markdown

from .models import CaseResult


def build_daily_digest(
    results: list[CaseResult],
    output_dir: str | Path = "output",
    run_date: date | None = None,
) -> tuple[Path, Path]:
    run_date = run_date or date.today()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    md_content = _render_markdown(results=results, run_date=run_date)
    md_path = output_dir / f"digest-{run_date.isoformat()}.md"
    html_path = output_dir / f"digest-{run_date.isoformat()}.html"

    md_path.write_text(md_content, encoding="utf-8")
    html_body = markdown.markdown(md_content, extensions=["tables", "fenced_code"])
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FundSuit Daily Digest {run_date.isoformat()}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 2rem auto; max-width: 980px; line-height: 1.5; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #ddd; padding: 0.5rem; text-align: left; vertical-align: top; }}
    th {{ background: #f3f3f3; }}
    code {{ background: #f6f8fa; padding: 0.1rem 0.25rem; }}
  </style>
</head>
<body>
{html_body}
</body>
</html>
"""
    html_path.write_text(html, encoding="utf-8")
    return md_path, html_path


def _render_markdown(results: list[CaseResult], run_date: date) -> str:
    top_prospects = [
        result
        for result in results
        if result.score.lead_score is not None and result.score.lead_score >= 75
    ]
    monitor_only = [
        result
        for result in results
        if result.score.recommended_action in {"Monitor / Light Outreach", "Needs More Diligence"}
    ]
    rejected = [result for result in results if result.score.recommended_action == "Reject"]
    comparable = [result for result in results if result.score.recommended_action == "Comparable Only"]

    lines = [
        f"# FundSuit Filing Intelligence Digest - {run_date.isoformat()}",
        "",
        f"Processed documents: **{len(results)}**",
        "",
        "## Top Prospects",
        *_case_bullets(top_prospects),
        "",
        "## Monitor-Only Cases",
        *_case_bullets(monitor_only),
        "",
        "## Rejected Cases",
        *_case_bullets(rejected),
        "",
        "## Comparable-Only Cases",
        *_case_bullets(comparable),
        "",
        "## Counsel Contacts",
        _contacts_table(results),
        "",
        "## Recommended Next Actions",
        *_actions_bullets(results),
    ]
    return "\n".join(lines)


def _case_bullets(results: list[CaseResult]) -> list[str]:
    if not results:
        return ["- None"]
    bullets = []
    for result in results:
        link = result.document.drive_link or f"https://drive.google.com/file/d/{result.document.drive_file_id}/view"
        bullets.append(
            f"- **{result.analysis.case_name}** | Score: `{result.score.lead_score}` | "
            f"Action: `{result.score.recommended_action}` | [PDF]({link})"
        )
    return bullets


def _contacts_table(results: list[CaseResult]) -> str:
    header = "| Case | Counsel | Firm | Email | Phone | Confidence |\n|---|---|---|---|---|---|"
    rows: list[str] = []
    for result in results:
        if not result.counsel_contacts:
            continue
        for contact in result.counsel_contacts:
            rows.append(
                f"| {result.analysis.case_name} | {contact.name} | {contact.firm or ''} | "
                f"{contact.email or ''} | {contact.phone or ''} | {contact.confidence} |"
            )
    if not rows:
        return header + "\n| - | - | - | - | - | - |"
    return header + "\n" + "\n".join(rows)


def _actions_bullets(results: list[CaseResult]) -> list[str]:
    if not results:
        return ["- No actions today."]
    actions = []
    for result in results:
        actions.append(
            f"- {result.analysis.case_name}: {result.score.recommended_action}. "
            f"Key drivers: {', '.join(result.analysis.positive_drivers[:3]) or 'n/a'}."
        )
    return actions

