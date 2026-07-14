"""Ingestion routes — Humble Objects over the use-case (SPEC §4).

The endpoint parses the multipart request, calls ``IngestStatement.execute``, and shapes
the response. No parsing, decryption, dedup or money logic here — all of that lives in the
ingestion/domain layers behind the injected use-case.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile

from coffer.api.dependencies import get_ingest_use_case
from coffer.api.schemas import IngestResponse
from coffer.domain.enums import UploadedVia
from coffer.ingestion.pipeline import IngestStatement

router = APIRouter(prefix="/api", tags=["ingestion"])


@router.post("/statements", response_model=IngestResponse)
async def upload_statement(
    file: UploadFile = File(...),
    account_id: int = Form(...),
    password: str | None = Form(default=None),
    uploaded_by_member_id: int | None = Form(default=None),
    use_case: IngestStatement = Depends(get_ingest_use_case),
) -> IngestResponse:
    """Web upload (SPEC §4). The account is selected manually up front (``account_id``);
    the password, if the PDF is encrypted, is entered at runtime and never stored."""
    raw_bytes = await file.read()
    result = use_case.execute(
        raw_bytes=raw_bytes,
        account_id=account_id,
        uploaded_via=UploadedVia.WEB,
        password=password,
        uploaded_by_member_id=uploaded_by_member_id,
    )
    return IngestResponse.from_result(result)
