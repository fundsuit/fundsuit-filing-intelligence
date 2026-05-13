# fundsuit-filing-intelligence

Python-first MVP for daily litigation-filing triage. The pipeline:

1. Reads unprocessed filing records from Google Sheets (`Documents` tab, `status = new`)
2. Downloads PDFs from Google Drive
3. Extracts text with page citations via PyMuPDF
4. Calls OpenAI for structured case extraction (strict JSON schema)
5. Applies deterministic lead-scoring rules
6. Enriches plaintiff counsel contacts (signature blocks + optional web lookup)
7. Writes structured outputs to Google Sheets (`Cases` tab)
8. Generates a daily Markdown + HTML digest

No web UI is included.

## Project Layout

```text
src/
  analyze_case.py
  build_digest.py
  drive_client.py
  enrich_counsel.py
  main.py
  models.py
  pdf_extract.py
  retry_utils.py
  score_case.py
  sheets_client.py
tests/
  test_score_case.py
  test_sheets_mapping.py
sample_data/
  mock_documents.csv
  pdfs/
.github/workflows/daily_digest.yml
```

## Requirements

- Python 3.11+
- Google Cloud service account with Drive + Sheets access
- OpenAI API key

Install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Environment Variables

Required for live mode:

- `OPENAI_API_KEY`
- `GOOGLE_SERVICE_ACCOUNT_JSON` (either raw JSON string or path to JSON file)
- `GOOGLE_SHEET_ID`

Optional:

- `OPENAI_MODEL` (default: `gpt-5-mini`)
- `SEARCH_API_KEY` (enables optional counsel contact web enrichment via SerpAPI)
- `DRY_RUN=true` (equivalent to `--dry-run`)
- `PIPELINE_MAX_RETRIES` (default: `3`)
- `PIPELINE_INITIAL_BACKOFF_SECONDS` (default: `1.0`)
- `PIPELINE_BACKOFF_MULTIPLIER` (default: `2.0`)
- `PIPELINE_MAX_BACKOFF_SECONDS` (default: `20.0`)
- `PIPELINE_JITTER_SECONDS` (default: `0.25`)

## Google Sheet Schema

### Documents tab (input)

Required columns:

- `document_id`
- `drive_file_id`
- `file_name`
- `status` (`new`, `processed`, `failed`)

Recommended columns:

- `drive_link`
- `notes`
- `last_processed_at`

### Cases tab (output)

The pipeline auto-writes/ensures these headers:

- `processed_at`, `document_id`, `drive_file_id`, `file_name`, `drive_link`
- `case_name`, `court`, `docket_number`, `filing_date`
- `case_category`, `procedural_posture`, `settlement_status`
- `class_certification_status`, `damages`, `fee_shifting_signal`, `fee_shifting_basis`
- `b2b_signal`, `funding_fit`, `lead_score`, `recommended_action`
- `positive_drivers`, `risk_flags`, `missing_information`, `source_citations`
- `plaintiff_counsel`, `counsel_contacts`, `score_rationale`

## Local Dry Run (No Google APIs Needed)

Sample rows and local PDFs are included in `sample_data/`.

```bash
python -m src.main --dry-run --skip-openai
```

Output files:

- `output/digest-YYYY-MM-DD.md`
- `output/digest-YYYY-MM-DD.html`
- `output/artifacts/YYYY-MM-DD/<document_id>.json` (per-document analysis/score/error artifact)

Dry run with OpenAI enabled:

```bash
OPENAI_API_KEY=... python -m src.main --dry-run
```

## Live Run (Google + OpenAI)

```bash
export OPENAI_API_KEY=...
export GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account", ... }'
export GOOGLE_SHEET_ID=your_sheet_id
python -m src.main
```

## Deterministic Scoring Rules Implemented

- Settled matters: `Comparable Only` (no investable score)
- Class certification granted: major positive
- Class certification denied/struck: major negative unless independent damages are financeable
- B2B commercial dispute: strong positive
- Prevailing-party fee provision: positive, with verification note

## GitHub Actions (Weekday Batch)

Workflow file: `.github/workflows/daily_digest.yml`

Schedule: weekdays at `13:30 UTC` (Monday-Friday), plus manual `workflow_dispatch`.

Set repository secrets:

- `OPENAI_API_KEY`
- `GOOGLE_SERVICE_ACCOUNT_JSON`
- `GOOGLE_SHEET_ID`

The workflow uploads digest artifacts from `output/` on each run.

## Tests

Run unit tests:

```bash
pytest -q
```

Covered areas:

- Scoring rule behavior in `src/score_case.py`
- Case-row serialization shape/content in `src/sheets_client.py`
