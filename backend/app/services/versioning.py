"""Immutable transcript/analysis snapshots and human-review policy."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select

from ..models import (
    AnalysisEvidence,
    AnalysisVersion,
    Call,
    CallOutcome,
    CallStatus,
    PublicationEvent,
    ReviewCase,
    ReviewEvent,
    TranscriptSegment,
    TranscriptVersion,
    TranscriptVersionSegment,
)

REVIEW_STATUSES = {
    "draft",
    "queued_for_review",
    "in_review",
    "changes_requested",
    "approved",
    "rejected",
    "published",
    "superseded",
    "policy_approved",
}


async def snapshot_transcript(
    session,
    call: Call,
    *,
    source: str,
    actor_email: str | None = None,
    reason: str | None = None,
) -> TranscriptVersion:
    number = (
        await session.scalar(
            select(func.max(TranscriptVersion.version_number)).where(
                TranscriptVersion.tenant_id == call.tenant_id,
                TranscriptVersion.call_id == call.id,
            )
        )
        or 0
    ) + 1
    version = TranscriptVersion(
        tenant_id=call.tenant_id,
        call_id=call.id,
        version_number=number,
        source=source,
        created_by=actor_email,
        change_reason=reason,
    )
    session.add(version)
    await session.flush()
    rows = list(
        (
            await session.scalars(
                select(TranscriptSegment)
                .where(TranscriptSegment.call_id == call.id)
                .order_by(TranscriptSegment.position)
            )
        ).all()
    )
    for row in rows:
        session.add(
            TranscriptVersionSegment(
                tenant_id=call.tenant_id,
                transcript_version_id=version.id,
                position=row.position,
                speaker_id=row.speaker_id or row.speaker_label,
                speaker_label=row.speaker_label,
                speaker_role=row.speaker_role,
                role_confidence=row.speaker_role_confidence,
                start_seconds=row.start_seconds,
                end_seconds=row.end_seconds,
                content=row.content,
                normalized_text=row.normalized_text,
            )
        )
    call.latest_transcript_version_id = version.id
    return version


async def _review_reasons(session, call: Call, analysis, checks: list) -> list[str]:
    reasons: list[str] = []
    human_published = (
        await session.scalar(
            select(func.count(func.distinct(PublicationEvent.call_id))).where(
                PublicationEvent.tenant_id == call.tenant_id,
                PublicationEvent.publication_type == "human_approved",
            )
        )
        or 0
    )
    if human_published < 50:
        reasons.append("pilot_first_50")
    if analysis.outcome_confidence < 0.75:
        reasons.append("low_confidence")
    if any(not check.supported for check in checks):
        reasons.append("unsupported_evidence")
    if analysis.role_assessment.confidence < 0.70:
        reasons.append("ambiguous_speaker_roles")
    if analysis.outcome in {"won", "lost"}:
        reasons.append("critical_outcome")
    customer = analysis.customer
    if (
        any(
            value is not None
            for value in (
                customer.amount,
                customer.exact_amount,
                customer.requested_discount,
                customer.followup_at,
            )
        )
        or customer.risk_flag
    ):
        reasons.append("critical_facts")
    # Stable sampling keeps policy decisions repeatable across retries.
    if human_published >= 50 and call.id.int % 10 == 0:
        reasons.append("quality_sample")
    return list(dict.fromkeys(reasons))


async def create_analysis_version(
    session,
    call: Call,
    transcript_version: TranscriptVersion,
    analysis,
    checks: list,
    *,
    provider: str,
    transcription_model: str,
    analysis_model: str,
    prompt_version: str,
    scorecard_version_id: uuid.UUID | None = None,
    actor_email: str | None = None,
) -> tuple[AnalysisVersion, ReviewCase]:
    number = (
        await session.scalar(
            select(func.max(AnalysisVersion.version_number)).where(
                AnalysisVersion.tenant_id == call.tenant_id,
                AnalysisVersion.call_id == call.id,
            )
        )
        or 0
    ) + 1
    reasons = await _review_reasons(session, call, analysis, checks)
    review_required = bool(reasons)
    version = AnalysisVersion(
        tenant_id=call.tenant_id,
        call_id=call.id,
        transcript_version_id=transcript_version.id,
        version_number=number,
        status="draft" if review_required else "policy_approved",
        provider=provider,
        transcription_model=transcription_model,
        analysis_model=analysis_model,
        prompt_version=prompt_version,
        scorecard_version_id=scorecard_version_id,
        confidence=analysis.outcome_confidence,
        evidence_validated=not any(not check.supported for check in checks),
        outcome=analysis.outcome,
        score=analysis.overall_score,
        analysis_json=analysis.model_dump(mode="json"),
        created_by=actor_email or "ai-worker",
    )
    session.add(version)
    await session.flush()
    for check in checks:
        session.add(
            AnalysisEvidence(
                tenant_id=call.tenant_id,
                analysis_version_id=version.id,
                segment_index=check.evidence.segment_index,
                quote=check.evidence.quote,
                timestamp_seconds=check.evidence.timestamp_seconds,
                supported=check.supported,
                similarity=check.similarity,
                validation_reason=check.reason,
            )
        )
    review = ReviewCase(
        tenant_id=call.tenant_id,
        call_id=call.id,
        analysis_version_id=version.id,
        status="queued_for_review" if review_required else "policy_approved",
        reasons_json=reasons,
        review_required=review_required,
    )
    session.add(review)
    call.latest_analysis_version_id = version.id
    if not review_required:
        call.reviewed_analysis_version_id = version.id
        call.published_analysis_version_id = version.id
        session.add(
            PublicationEvent(
                tenant_id=call.tenant_id,
                call_id=call.id,
                analysis_version_id=version.id,
                actor_email="review-policy",
                publication_type="policy_approved",
            )
        )
    return version, review


async def transition_review(
    session,
    review: ReviewCase,
    call: Call,
    *,
    action: str,
    actor_email: str,
    note: str | None = None,
) -> ReviewCase:
    targets = {
        "assign": "in_review",
        "approve": "approved",
        "reject": "rejected",
        "request_changes": "changes_requested",
        "publish": "published",
    }
    target = targets[action]
    allowed = {
        "assign": {"queued_for_review", "changes_requested"},
        "approve": {"queued_for_review", "in_review", "changes_requested"},
        "reject": {"queued_for_review", "in_review", "changes_requested"},
        "request_changes": {"queued_for_review", "in_review", "approved"},
        "publish": {"approved"},
    }
    if review.status not in allowed[action]:
        raise ValueError(f"invalid_review_transition:{review.status}:{action}")
    previous = review.status
    review.status = target
    review.decision_note = note
    version = await session.get(AnalysisVersion, review.analysis_version_id)
    if version:
        version.status = target
    if action == "approve":
        call.reviewed_analysis_version_id = review.analysis_version_id
    if action == "publish":
        previous_published = call.published_analysis_version_id
        if previous_published and previous_published != review.analysis_version_id:
            old = await session.get(AnalysisVersion, previous_published)
            if old:
                old.status = "superseded"
        call.reviewed_analysis_version_id = review.analysis_version_id
        call.published_analysis_version_id = review.analysis_version_id
        call.outcome_confirmed = True
        if version and call.latest_analysis_version_id == review.analysis_version_id:
            call.outcome = CallOutcome(version.outcome)
            call.score = version.score
            call.status = CallStatus.completed
        session.add(
            PublicationEvent(
                tenant_id=call.tenant_id,
                call_id=call.id,
                analysis_version_id=review.analysis_version_id,
                actor_email=actor_email,
                publication_type="human_approved",
            )
        )
    session.add(
        ReviewEvent(
            tenant_id=review.tenant_id,
            review_case_id=review.id,
            actor_email=actor_email,
            action=action,
            from_status=previous,
            to_status=target,
            note=note,
            metadata_json={"at": datetime.now(UTC).isoformat()},
        )
    )
    return review
