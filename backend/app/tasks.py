"""Idempotent, observable Celery pipeline for one sales call."""

from __future__ import annotations

import asyncio
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from celery import Celery
from sqlalchemy import delete, select

from .config import get_settings
from .database import tenant_session
from .models import (
    Call,
    CallExtraction,
    CallOutcome,
    CallStatus,
    ExtractionEvidence,
    GlossaryTerm,
    MessageDraft,
    PipelineEvent,
    ProcessingError,
    Task,
    TranscriptSegment,
)
from .services.ai import SalesAIProvider, get_ai_provider
from .services.audio import preprocess_audio, validate_audio
from .services.evidence import validate_analysis_evidence
from .services.followups import build_followup_spec
from .services.glossary import GlossaryEntry, apply_glossary
from .services.logging import configure_logging, get_logger
from .services.metrics import calculate_metrics
from .services.persian import normalize_persian
from .services.pipeline import PipelineState, RetryPolicy, classify_exception, ensure_transition
from .services.roles import apply_roles, assign_speaker_roles
from .services.storage import ObjectStorage, storage

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger(__name__)
celery_app = Celery("mokalemeban", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=settings.processing_stage_timeout_seconds,
    task_time_limit=settings.processing_stage_timeout_seconds + 30,
)


class RetryablePipelineError(RuntimeError):
    def __init__(self, message: str, delay_seconds: int):
        super().__init__(message)
        self.delay_seconds = delay_seconds


@celery_app.task(bind=True, max_retries=settings.processing_max_retries)
def process_call(self, call_id: str, tenant_id: str, mode: str = "resume"):
    try:
        return asyncio.run(_process_call(UUID(call_id), UUID(tenant_id), mode=mode))
    except RetryablePipelineError as exc:
        raise self.retry(exc=exc, countdown=exc.delay_seconds)


async def _transition(
    session, call: Call, target: CallStatus, *, metadata: dict | None = None
) -> PipelineEvent:
    now = datetime.now(UTC)
    previous = call.status.value if hasattr(call.status, "value") else str(call.status)
    ensure_transition(PipelineState(previous), PipelineState(target.value))
    previous_event = await session.scalar(
        select(PipelineEvent)
        .where(PipelineEvent.call_id == call.id, PipelineEvent.finished_at.is_(None))
        .order_by(PipelineEvent.started_at.desc())
        .limit(1)
    )
    if previous_event:
        previous_event.finished_at = now
        previous_event.duration_ms = max(
            0, int((now - previous_event.started_at).total_seconds() * 1000)
        )
    call.status = target
    event = PipelineEvent(
        tenant_id=call.tenant_id,
        call_id=call.id,
        from_state=previous,
        to_state=target.value,
        stage=target.value,
        attempt=call.retry_count + 1,
        started_at=now,
        finished_at=now
        if target
        in {
            CallStatus.completed,
            CallStatus.review_needed,
            CallStatus.failed,
            CallStatus.quarantined,
        }
        else None,
        duration_ms=0
        if target
        in {
            CallStatus.completed,
            CallStatus.review_needed,
            CallStatus.failed,
            CallStatus.quarantined,
        }
        else None,
        metadata_json=metadata,
    )
    session.add(event)
    await session.flush()
    return event


def run_provider_pipeline(
    provider: SalesAIProvider,
    audio_path: Path,
    glossary: list[GlossaryEntry] | None = None,
) -> tuple[list[dict], dict, object, list]:
    """External-provider boundary kept deterministic and directly unit-testable."""

    segments = provider.transcribe(audio_path)
    if not segments:
        raise RuntimeError("empty_transcript")
    glossary = glossary or []
    segments = apply_glossary(segments, glossary)
    measured = calculate_metrics(segments)
    heuristic = assign_speaker_roles(segments)
    segments = apply_roles(segments, heuristic)
    analysis = provider.analyze(segments, measured, [item.as_prompt_item() for item in glossary])
    refined = assign_speaker_roles(segments, analysis.role_assessment)
    segments = apply_roles(segments, refined)
    validated, checks = validate_analysis_evidence(analysis, segments)
    return segments, measured, validated, checks


async def _upsert_segments(session, call: Call, segments: list[dict]) -> None:
    existing_rows = list(
        (
            await session.scalars(
                select(TranscriptSegment).where(TranscriptSegment.call_id == call.id)
            )
        ).all()
    )
    existing = {row.position: row for row in existing_rows}
    seen: set[int] = set()
    for index, item in enumerate(segments):
        position = int(item.get("position", index))
        seen.add(position)
        row = existing.get(position)
        if row is None:
            row = TranscriptSegment(tenant_id=call.tenant_id, call_id=call.id, position=position)
            session.add(row)
        row.speaker_label = str(item.get("speaker", "unknown"))
        row.start_seconds = item.get("start")
        row.end_seconds = item.get("end")
        row.speaker_id = str(item.get("speaker", "unknown"))
        row.speaker_role_confidence = item.get("role_confidence")
        row.normalized_text = str(
            item.get("normalized_text") or normalize_persian(str(item.get("text", "")))
        )
        if not row.is_manually_corrected:
            row.content = str(item.get("text", "")).strip()
            row.speaker_role = str(item.get("role", "unknown"))
    for position, row in existing.items():
        if position not in seen and not row.is_manually_corrected:
            await session.delete(row)


async def _persist_extraction(session, call: Call, analysis, checks: list) -> None:
    extraction = await session.scalar(
        select(CallExtraction).where(
            CallExtraction.tenant_id == call.tenant_id,
            CallExtraction.call_id == call.id,
        )
    )
    if extraction is None:
        extraction = CallExtraction(tenant_id=call.tenant_id, call_id=call.id)
        session.add(extraction)
        await session.flush()
    customer = analysis.customer
    extraction.customer_name = customer.name
    extraction.phone = customer.phone
    extraction.alternate_phone = customer.alternate_phone
    extraction.company = customer.company
    extraction.address = customer.address
    extraction.customer_type = customer.customer_type
    extraction.city = customer.city
    extraction.province = customer.province
    extraction.product = customer.product
    extraction.product_category = customer.product_category
    extraction.quantity = customer.quantity
    extraction.unit = customer.unit
    extraction.amount = customer.amount
    extraction.exact_amount = customer.exact_amount or customer.amount
    extraction.budget_min = customer.budget_min
    extraction.budget_max = customer.budget_max
    extraction.requested_discount = customer.requested_discount
    extraction.currency = customer.currency
    extraction.followup_due_at = customer.followup_at
    extraction.followup_required = (
        analysis.outcome == "follow_up" or analysis.next_action is not None
    )
    extraction.sales_stage = customer.sales_stage or analysis.funnel_stage
    extraction.lead_temperature = customer.lead_temperature
    extraction.sentiment = customer.sentiment
    extraction.risk_flag = customer.risk_flag
    extraction.competitor_name = customer.competitor_name
    extraction.purchase_timeline = customer.purchase_timeline
    extraction.lost_reason = customer.lost_reason
    extraction.purchase_probability = customer.purchase_probability
    extraction.pain_points_json = customer.pain_points
    extraction.objections_json = [item.model_dump(mode="json") for item in analysis.objections]
    extraction.commitments_json = customer.commitments
    extraction.strengths_json = [item.model_dump(mode="json") for item in analysis.strengths]
    extraction.weaknesses_json = [item.model_dump(mode="json") for item in analysis.improvements]
    extraction.coaching_json = [item.model_dump(mode="json") for item in analysis.improvements]
    extraction.score_breakdown_json = [
        item.model_dump(mode="json") for item in analysis.score_items
    ]
    extraction.need = customer.need
    extraction.budget_text = customer.budget
    extraction.promise_text = " | ".join(customer.commitments) or None
    extraction.confidence = analysis.outcome_confidence
    extraction.validated = not any(not check.supported for check in checks)
    extraction.validation_status = "verified" if extraction.validated else "partially_supported"
    extraction.raw_json = customer.model_dump(mode="json")
    await session.execute(delete(ExtractionEvidence).where(ExtractionEvidence.call_id == call.id))
    segment_rows = {
        row.position: row
        for row in (
            await session.scalars(
                select(TranscriptSegment).where(TranscriptSegment.call_id == call.id)
            )
        ).all()
    }
    for field_name, evidences in analysis.field_evidence.items():
        value = getattr(customer, field_name, None)
        if value is None:
            continue
        for evidence in evidences:
            source_segment = segment_rows.get(evidence.segment_index)
            session.add(
                ExtractionEvidence(
                    tenant_id=call.tenant_id,
                    call_id=call.id,
                    extraction_id=extraction.id,
                    field_name=field_name,
                    value_text=str(value),
                    segment_position=evidence.segment_index,
                    source_segment_id=source_segment.id if source_segment else None,
                    source_segment_ids_json=[str(source_segment.id)] if source_segment else [],
                    quote=evidence.quote,
                    timestamp_seconds=evidence.timestamp_seconds,
                    end_time_seconds=evidence.end_time_seconds,
                    confidence=1.0,
                    supported=True,
                    extraction_method="ai",
                    validation_status="supported",
                )
            )


async def _create_followups(session, call: Call, analysis) -> None:
    spec = build_followup_spec(str(call.id), analysis)
    if spec:
        existing = await session.scalar(
            select(Task.id).where(
                Task.tenant_id == call.tenant_id,
                Task.call_id == call.id,
                Task.dedupe_key == spec.dedupe_key,
            )
        )
        if existing is None:
            session.add(
                Task(
                    tenant_id=call.tenant_id,
                    call_id=call.id,
                    customer_name=call.customer_name,
                    title=spec.title,
                    priority=spec.priority,
                    status="open" if spec.due_at else "needs_scheduling",
                    due_at=spec.due_at,
                    ai_suggested=True,
                    dedupe_key=spec.dedupe_key,
                    task_type=spec.task_type,
                    assignee_email=call.seller_email,
                )
            )
    for draft in analysis.follow_up_drafts:
        duplicate = await session.scalar(
            select(MessageDraft.id).where(
                MessageDraft.tenant_id == call.tenant_id,
                MessageDraft.call_id == call.id,
                MessageDraft.channel == draft.channel,
                MessageDraft.content == draft.content,
            )
        )
        if duplicate is None:
            session.add(
                MessageDraft(
                    tenant_id=call.tenant_id,
                    call_id=call.id,
                    channel=draft.channel,
                    subject=draft.subject,
                    content=draft.content,
                    status="pending_approval",
                )
            )


async def _process_call(
    call_id: UUID,
    tenant_id: UUID,
    *,
    mode: str = "resume",
    provider: SalesAIProvider | None = None,
    object_storage: ObjectStorage | None = None,
):
    if mode not in {"resume", "reanalyze", "full"}:
        raise ValueError("invalid processing mode")
    provider = provider or get_ai_provider()
    object_storage = object_storage or storage
    async for session in tenant_session(str(tenant_id)):
        call = await session.scalar(
            select(Call).where(Call.id == call_id, Call.tenant_id == tenant_id)
        )
        if not call:
            return {"status": "missing"}
        if call.status == CallStatus.completed and mode == "resume":
            return {"status": "already_completed"}
        stage = "queued"
        try:
            glossary_rows = list(
                (
                    await session.scalars(
                        select(GlossaryTerm).where(
                            GlossaryTerm.tenant_id == tenant_id, GlossaryTerm.active.is_(True)
                        )
                    )
                ).all()
            )
            glossary = [
                GlossaryEntry(row.term, tuple(row.aliases_json or []), row.category)
                for row in glossary_rows
            ]
            glossary_payload = [item.as_prompt_item() for item in glossary]
            call.error_message = None
            call.error_code = None
            call.next_retry_at = None
            await _transition(
                session,
                call,
                CallStatus.preprocessing if mode != "reanalyze" else CallStatus.analyzing,
                metadata={"mode": mode},
            )
            await session.commit()

            if mode == "reanalyze":
                rows = list(
                    (
                        await session.scalars(
                            select(TranscriptSegment)
                            .where(TranscriptSegment.call_id == call.id)
                            .order_by(TranscriptSegment.position)
                        )
                    ).all()
                )
                if not rows:
                    raise RuntimeError("empty_transcript")
                segments = [
                    {
                        "position": row.position,
                        "speaker": row.speaker_label,
                        "role": row.speaker_role,
                        "start": row.start_seconds,
                        "end": row.end_seconds,
                        "text": row.content,
                        "normalized_text": row.normalized_text,
                    }
                    for row in rows
                ]
                measured = calculate_metrics(segments)
                stage = "analyzing"
                analysis = await asyncio.to_thread(
                    provider.analyze, segments, measured, glossary_payload
                )
                stage = "validating"
                analysis, checks = validate_analysis_evidence(analysis, segments)
            else:
                with tempfile.TemporaryDirectory(prefix="mokalemeban-") as temp_dir:
                    source_path = Path(temp_dir) / Path(call.original_file_name).name
                    processed_path = Path(temp_dir) / "processed.wav"
                    await object_storage.download(call.object_key, source_path)
                    metadata = validate_audio(
                        source_path,
                        allowed_extensions=settings.issabel_extensions
                        | {source_path.suffix.lower()},
                        max_bytes=settings.max_audio_bytes,
                        min_duration_seconds=settings.audio_min_duration_seconds,
                        ffprobe_path=settings.audio_ffprobe_path,
                    )
                    result = await asyncio.to_thread(
                        preprocess_audio,
                        source_path,
                        processed_path,
                        metadata,
                        target_sample_rate=settings.audio_target_sample_rate,
                        ffmpeg_path=settings.audio_ffmpeg_path,
                        ffprobe_path=settings.audio_ffprobe_path,
                        timeout_seconds=settings.processing_stage_timeout_seconds,
                    )
                    await _transition(
                        session, call, CallStatus.transcribing, metadata=result.trace()
                    )
                    await session.commit()
                    stage = "transcribing"
                    segments = await asyncio.to_thread(provider.transcribe, processed_path)
                    if not segments:
                        raise RuntimeError("empty_transcript")
                    segments = apply_glossary(segments, glossary)
                    measured = calculate_metrics(segments)
                    await _transition(session, call, CallStatus.assigning_roles)
                    heuristic = assign_speaker_roles(segments)
                    segments = apply_roles(segments, heuristic)
                    await _transition(
                        session,
                        call,
                        CallStatus.analyzing,
                        metadata={
                            "role_method": heuristic.method,
                            "role_confidence": heuristic.confidence,
                        },
                    )
                    await session.commit()
                    stage = "analyzing"
                    analysis = await asyncio.to_thread(
                        provider.analyze, segments, measured, glossary_payload
                    )
                    refined = assign_speaker_roles(segments, analysis.role_assessment)
                    segments = apply_roles(segments, refined)
                    stage = "validating"
                    analysis, checks = validate_analysis_evidence(analysis, segments)

            await _transition(
                session,
                call,
                CallStatus.validating,
                metadata={"unsupported_evidence": sum(not check.supported for check in checks)},
            )
            await _upsert_segments(session, call, segments)
            call.outcome = CallOutcome(analysis.outcome)
            call.customer_name = analysis.customer.name or call.customer_name
            call.score = analysis.overall_score
            call.analysis_version = settings.analysis_prompt_version
            call.analysis_json = analysis.model_dump(mode="json")
            call.duration_seconds = measured.get("call_span_seconds")
            await _persist_extraction(session, call, analysis, checks)
            await _transition(session, call, CallStatus.creating_followups)
            stage = "creating_followups"
            await _create_followups(session, call, analysis)
            final_status = (
                CallStatus.review_needed
                if analysis.outcome_confidence < 0.75
                else CallStatus.completed
            )
            await _transition(session, call, final_status)
            call.last_successful_stage = final_status.value
            call.retry_count = 0
            await session.commit()
            return {"status": final_status.value, "score": call.score}
        except Exception as exc:
            await session.rollback()
            call = await session.scalar(
                select(Call).where(Call.id == call_id, Call.tenant_id == tenant_id)
            )
            if call is None:
                raise
            descriptor = classify_exception(exc, stage)
            policy = RetryPolicy(settings.retry_schedule)
            decision = policy.decide(descriptor, call.retry_count)
            call.retry_count += 1
            call.error_code = descriptor.code
            call.error_message = descriptor.safe_message
            session.add(
                ProcessingError(
                    tenant_id=tenant_id,
                    call_id=call.id,
                    stage=stage,
                    code=descriptor.code,
                    category=descriptor.category.value,
                    transient=descriptor.transient,
                    attempt=call.retry_count,
                    message=descriptor.safe_message,
                    exception_type=type(exc).__name__,
                    context_json=getattr(exc, "context", None),
                )
            )
            target_status = CallStatus.retry_scheduled if decision.retry else CallStatus.failed
            ensure_transition(PipelineState(call.status.value), PipelineState(target_status.value))
            if decision.retry:
                call.status = target_status
                call.next_retry_at = decision.scheduled_at
            else:
                call.status = target_status
                call.next_retry_at = None
            now = datetime.now(UTC)
            open_event = await session.scalar(
                select(PipelineEvent)
                .where(PipelineEvent.call_id == call.id, PipelineEvent.finished_at.is_(None))
                .order_by(PipelineEvent.started_at.desc())
                .limit(1)
            )
            if open_event:
                open_event.finished_at = now
                open_event.duration_ms = max(
                    0, int((now - open_event.started_at).total_seconds() * 1000)
                )
            session.add(
                PipelineEvent(
                    tenant_id=tenant_id,
                    call_id=call.id,
                    from_state=stage,
                    to_state=call.status.value,
                    stage=stage,
                    attempt=call.retry_count,
                    started_at=now,
                    finished_at=now,
                    duration_ms=0,
                    metadata_json={"error_code": descriptor.code},
                )
            )
            await session.commit()
            logger.exception(
                "call_processing_failed",
                call_id=str(call.id),
                stage=stage,
                code=descriptor.code,
            )
            if decision.retry and decision.delay_seconds:
                raise RetryablePipelineError(
                    descriptor.safe_message, decision.delay_seconds
                ) from exc
            return {"status": "failed", "error_code": descriptor.code}
