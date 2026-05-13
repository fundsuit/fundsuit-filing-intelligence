from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import Resource, build
from googleapiclient.http import MediaIoBaseDownload


DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def _load_service_account_info(raw_or_path: str) -> dict[str, Any]:
    raw_or_path = raw_or_path.strip()
    if raw_or_path.startswith("{"):
        return json.loads(raw_or_path)

    path = Path(raw_or_path)
    if not path.exists():
        raise FileNotFoundError(f"Google service account file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


class DriveClient:
    def __init__(self, credentials: str | None = None) -> None:
        source = credentials or os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        if not source:
            raise ValueError("Missing GOOGLE_SERVICE_ACCOUNT_JSON for Drive authentication.")

        info = _load_service_account_info(source)
        creds = service_account.Credentials.from_service_account_info(info, scopes=DRIVE_SCOPES)
        self._service: Resource = build("drive", "v3", credentials=creds, cache_discovery=False)

    def list_pdf_files(self, folder_id: str, page_size: int = 200) -> list[dict[str, str]]:
        query = f"'{folder_id}' in parents and mimeType='application/pdf' and trashed=false"
        response = (
            self._service.files()
            .list(
                q=query,
                pageSize=page_size,
                fields="files(id,name,webViewLink,createdTime,modifiedTime)",
            )
            .execute()
        )
        return response.get("files", [])

    def download_pdf_by_id(self, file_id: str, destination: str | Path) -> Path:
        destination_path = Path(destination)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        request = self._service.files().get_media(fileId=file_id)
        with destination_path.open("wb") as handle:
            downloader = MediaIoBaseDownload(handle, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        return destination_path

