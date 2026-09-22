"""Tests for document ingestion and creator review stamps."""
from __future__ import annotations

import io

import pytest

from brain.documents import DocumentIngestError, extract_document_text
from brain.extractors import extract_candidate_profile, extract_job_intelligence
from models.brain import utc_now
from routers import brain_intelligence


def test_extract_plain_text_document() -> None:
    data = b"Backend Engineer\n\nRequirements\n- Python\n"
    result = extract_document_text(
        data=data,
        filename="jd.txt",
        content_type="text/plain",
    )
    assert "Python" in result.text
    assert result.content_type == "text"
    assert result.warnings == []


def test_rejects_oversized_upload() -> None:
    with pytest.raises(DocumentIngestError, match="exceeds"):
        extract_document_text(
            data=b"x" * (2 * 1024 * 1024 + 1),
            filename="big.txt",
            content_type="text/plain",
        )


def test_rejects_unsupported_binary() -> None:
    with pytest.raises(DocumentIngestError, match="Unsupported"):
        extract_document_text(
            data=b"\x00\x01\x02\x03not-a-document",
            filename="blob.bin",
            content_type="application/octet-stream",
        )


def test_blank_pdf_is_rejected() -> None:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    with pytest.raises(DocumentIngestError, match="little or no extractable text"):
        extract_document_text(
            data=buf.getvalue(),
            filename="blank.pdf",
            content_type="application/pdf",
        )


@pytest.mark.asyncio
async def test_approve_and_confirm_stamp_review_flags() -> None:
    jd = extract_job_intelligence(
        "Junior Backend Engineer\n\nRequirements\n- Python\n"
    )
    approved = await brain_intelligence.approve_jd(
        brain_intelligence.ApproveJobRequest(
            job_intelligence=jd,
            approved_by="creator@example.com",
        )
    )
    assert approved.approved is True
    assert approved.approved_at is not None

    profile = extract_candidate_profile(
        "Projects\n- Billing API\n\nSkills\nPython, FastAPI\n"
    )
    confirmed = await brain_intelligence.confirm_resume(
        brain_intelligence.ConfirmResumeRequest(
            candidate_profile=profile,
            confirmed_by="creator@example.com",
        )
    )
    assert confirmed.confirmed is True
    assert confirmed.confirmed_at is not None
    assert confirmed.claims
    assert all(claim.provenance.confirmed for claim in confirmed.claims)
    assert confirmed.confirmed_at >= utc_now().replace(year=2020)
