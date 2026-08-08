from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.models import (
    AnalysisVersion,
    Call,
    PublicationEvent,
    ReviewCase,
    ReviewEvent,
    TranscriptVersion,
)
from app.schemas import Evidence
from app.services.evidence import EvidenceCheck
from app.services.versioning import create_analysis_version, transition_review


def call_record() -> Call:
    return Call(
        id=uuid4(),
        tenant_id=uuid4(),
        original_file_name="call.wav",
        object_key="tenant/call.wav",
        mime_type="audio/wav",
        size_bytes=100,
        seller_email="seller@example.com",
    )


@pytest.mark.asyncio
async def test_first_fifty_analysis_is_immutable_draft_for_human_review(analysis_factory):
    call = call_record()
    transcript = TranscriptVersion(
        id=uuid4(), tenant_id=call.tenant_id, call_id=call.id, version_number=1
    )
    session = SimpleNamespace(
        scalar=AsyncMock(side_effect=[0, 0]),
        flush=AsyncMock(),
        add=Mock(),
    )

    version, review = await create_analysis_version(
        session,
        call,
        transcript,
        analysis_factory(),
        [
            EvidenceCheck(
                evidence=Evidence(
                    segment_index=0,
                    quote="سلام",
                    speaker="speaker_0",
                    timestamp_seconds=0,
                ),
                supported=True,
                similarity=1.0,
                reason="supported",
            )
        ],
        provider="openai",
        transcription_model="gpt-4o-transcribe-diarize",
        analysis_model="gpt-4o",
        prompt_version="sales-v1",
    )

    assert version.status == "draft"
    assert review.status == "queued_for_review"
    assert review.reasons_json == ["pilot_first_50"]
    assert call.latest_analysis_version_id == version.id
    assert call.published_analysis_version_id is None


@pytest.mark.asyncio
async def test_publish_supersedes_only_previous_official_version():
    call = call_record()
    previous = AnalysisVersion(
        id=uuid4(),
        tenant_id=call.tenant_id,
        call_id=call.id,
        transcript_version_id=uuid4(),
        version_number=1,
        status="published",
        transcription_model="t",
        analysis_model="a",
        prompt_version="p",
    )
    current = AnalysisVersion(
        id=uuid4(),
        tenant_id=call.tenant_id,
        call_id=call.id,
        transcript_version_id=uuid4(),
        version_number=2,
        status="approved",
        transcription_model="t",
        analysis_model="a",
        prompt_version="p",
    )
    call.published_analysis_version_id = previous.id
    review = ReviewCase(
        id=uuid4(),
        tenant_id=call.tenant_id,
        call_id=call.id,
        analysis_version_id=current.id,
        status="approved",
        reasons_json=["pilot_first_50"],
    )
    added: list[object] = []
    session = SimpleNamespace(
        get=AsyncMock(
            side_effect=lambda _model, identifier: current if identifier == current.id else previous
        ),
        add=Mock(side_effect=added.append),
    )

    await transition_review(
        session,
        review,
        call,
        action="publish",
        actor_email="manager@example.com",
        note="checked against audio",
    )

    assert previous.status == "superseded"
    assert current.status == "published"
    assert call.published_analysis_version_id == current.id
    assert call.reviewed_analysis_version_id == current.id
    assert any(isinstance(row, PublicationEvent) for row in added)
    assert any(isinstance(row, ReviewEvent) for row in added)
