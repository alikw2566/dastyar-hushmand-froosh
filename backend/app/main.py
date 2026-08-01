import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy import asc, desc, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .database import engine, tenant_session
from .models import (
    AiSetting,
    AuditLog,
    AutomationRule,
    Base,
    Call,
    CallExtraction,
    CallOutcome,
    CallStatus,
    ExtractionEvidence,
    GlossaryTerm,
    Integration,
    Membership,
    MessageDraft,
    Organization,
    PipelineEvent,
    ProcessingError,
    Role,
    ScorecardVersion,
    SecuritySetting,
    Task,
    Team,
    TranscriptCorrection,
    TranscriptSegment,
    UsageLedger,
    WatcherHeartbeat,
)
from .schemas import (
    AiSettingsPatch,
    AutomationCreate,
    CallRead,
    EnabledPatch,
    GlossaryCreate,
    GlossaryPatch,
    IntegrationCreate,
    IntegrationStatusPatch,
    MemberCreate,
    MemberPatch,
    OrganizationSettingsPatch,
    PaginatedCalls,
    ProcessingAction,
    ReprocessRequest,
    ScorecardCreate,
    SecuritySettingsPatch,
    SegmentCorrection,
    SpeakerRolesPatch,
    TaskCreate,
    TaskPatch,
    TeamCreate,
    TeamPatch,
)
from .security import Principal, current_principal, require_roles
from .services.exports import render_call_pdf, render_call_xlsx, render_calls_xlsx
from .services.integrations import secret_box
from .services.keycloak import keycloak_admin
from .services.logging import configure_logging
from .services.persian import normalize_persian
from .services.storage import storage
from .tasks import process_call

settings = get_settings()
configure_logging(settings.log_level)


def add_audit(
    session: AsyncSession,
    principal: Principal,
    action: str,
    entity_type: str,
    entity_id=None,
    metadata=None,
):
    session.add(
        AuditLog(
            tenant_id=principal.tenant_id,
            actor_email=principal.email,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id else None,
            metadata_json=metadata,
        )
    )


def _call_read(call: Call, extraction: CallExtraction | None = None) -> CallRead:
    payload = {
        "id": call.id,
        "customer_name": call.customer_name,
        "seller_email": call.seller_email,
        "seller_name": call.seller_name,
        "original_file_name": call.original_file_name,
        "source": call.source,
        "status": call.status.value if hasattr(call.status, "value") else call.status,
        "outcome": call.outcome.value if hasattr(call.outcome, "value") else call.outcome,
        "outcome_confirmed": call.outcome_confirmed,
        "duration_seconds": call.duration_seconds,
        "score": call.score,
        "created_at": call.created_at,
        "updated_at": call.updated_at,
        "call_started_at": call.call_started_at,
        "direction": call.direction,
        "caller_number": call.caller_number,
        "destination_number": call.destination_number,
        "retry_count": call.retry_count,
        "next_retry_at": call.next_retry_at,
        "error_code": call.error_code,
        "manually_corrected": call.manually_corrected,
    }
    if extraction:
        payload.update(
            {
                "company": extraction.company,
                "phone": extraction.phone,
                "city": extraction.city,
                "province": extraction.province,
                "product": extraction.product,
                "product_category": extraction.product_category,
                "sales_stage": extraction.sales_stage,
                "lead_temperature": extraction.lead_temperature,
                "sentiment": extraction.sentiment,
                "risk_flag": extraction.risk_flag,
                "followup_required": extraction.followup_required,
                "followup_due_at": extraction.followup_due_at,
            }
        )
    return CallRead.model_validate(payload)


def _call_scope(principal: Principal) -> list:
    conditions = [Call.tenant_id == principal.tenant_id]
    if principal.role in {Role.seller, Role.agent}:
        conditions.append(Call.seller_email == principal.email)
    return conditions


def _effective_seller_email(principal: Principal, requested: str | None) -> str | None:
    if principal.role in {Role.seller, Role.agent}:
        return principal.email
    return requested.strip().lower() if requested else None


async def _upload_size(audio: UploadFile) -> int:
    if audio.size is not None:
        return int(audio.size)

    def measure() -> int:
        position = audio.file.tell()
        audio.file.seek(0, 2)
        size = audio.file.tell()
        audio.file.seek(position)
        return size

    return await asyncio.to_thread(measure)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.environment == "development":
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            if settings.auth_disabled:
                await connection.execute(
                    text("""
                        INSERT INTO organizations (id, name, plan, monthly_minute_limit, retention_days, automation_mode)
                        VALUES (:id, :name, 'free', 120, 30, 'approval')
                        ON CONFLICT (id) DO NOTHING
                    """),
                    {"id": settings.development_tenant_id, "name": settings.default_tenant_name},
                )
            policy_file = (
                Path(__file__).resolve().parent.parent / "sql" / "001_row_level_security.sql"
            )
            await connection.exec_driver_sql(policy_file.read_text(encoding="utf-8"))
        await storage.ensure_bucket()
    yield


app = FastAPI(
    title="Mokalemeban Sales Conversation Intelligence API",
    version="1.0.0",
    openapi_url="/api/v1/openapi.json",
    docs_url="/api/v1/docs",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Recording-Consent"],
)


async def db_session(
    principal: Annotated[Principal, Depends(current_principal)],
) -> AsyncIterator[AsyncSession]:
    async for session in tenant_session(str(principal.tenant_id)):
        yield session


@app.get("/health")
async def health():
    return {"status": "ok", "service": "mokalemeban-api", "version": "1.0.0"}


@app.get("/health/live")
async def health_live():
    return {"status": "ok", "service": "mokalemeban-api"}


@app.get("/health/ready")
async def health_ready():
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database_unavailable") from exc
    return {"status": "ready", "database": "ok"}


@app.get("/metrics")
async def prometheus_metrics():
    return Response(
        "mokalemeban_api_up 1\n",
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@app.get("/health/details")
async def health_details(
    principal: Annotated[
        Principal, Depends(require_roles(Role.admin, Role.manager, Role.supervisor))
    ],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    now = datetime.now(UTC)
    watcher = await session.scalar(
        select(WatcherHeartbeat)
        .where(WatcherHeartbeat.tenant_id == principal.tenant_id)
        .order_by(WatcherHeartbeat.updated_at.desc())
        .limit(1)
    )
    queued = (
        await session.scalar(
            select(func.count(Call.id)).where(
                Call.tenant_id == principal.tenant_id,
                Call.status.in_([CallStatus.queued, CallStatus.retry_scheduled]),
            )
        )
        or 0
    )
    failed = (
        await session.scalar(
            select(func.count(Call.id)).where(
                Call.tenant_id == principal.tenant_id, Call.status == CallStatus.failed
            )
        )
        or 0
    )
    watcher_age = (
        (now - watcher.updated_at).total_seconds() if watcher and watcher.updated_at else None
    )
    watcher_ok = watcher_age is not None and watcher_age <= settings.watcher_stale_after_seconds
    return {
        "status": "healthy"
        if settings.issabel_import_mode == "disabled" or watcher_ok
        else "degraded",
        "database": {"status": "ok"},
        "queue": {"status": "observable", "queued_calls": queued},
        "worker": {
            "status": "unknown",
            "note": "Celery remote-control heartbeat is deployment-dependent",
        },
        "watcher": {
            "status": "disabled"
            if settings.issabel_import_mode == "disabled"
            else ("ok" if watcher_ok else "stale"),
            "last_scan_at": watcher.last_scan_at if watcher else None,
            "age_seconds": watcher_age,
        },
        "storage": {"status": "configured", "bucket": settings.s3_bucket},
        "external_model": {"status": "configured" if settings.openai_api_key else "not_configured"},
        "failed_calls": failed,
    }


@app.get("/api/v1/overview")
async def overview(
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    scope = _call_scope(principal)
    total = await session.scalar(select(func.count()).select_from(Call).where(*scope)) or 0
    completed = (
        await session.scalar(
            select(func.count())
            .select_from(Call)
            .where(*scope, Call.status == CallStatus.completed)
        )
        or 0
    )
    average_score = await session.scalar(select(func.avg(Call.score)).where(*scope))
    won = (
        await session.scalar(
            select(func.count())
            .select_from(Call)
            .where(*scope, Call.outcome == CallOutcome.won, Call.outcome_confirmed.is_(True))
        )
        or 0
    )
    return {
        "total_calls": total,
        "completed_calls": completed,
        "average_score": round(float(average_score), 1) if average_score is not None else None,
        "confirmed_conversion_rate": round(won / total * 100, 1) if total else None,
    }


@app.get("/api/v1/calls", response_model=PaginatedCalls)
async def list_calls(
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(db_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    sort: str = "created_at",
    order: str = "desc",
    q: Annotated[str | None, Query(max_length=300)] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    seller: Annotated[str | None, Query(max_length=320)] = None,
    customer: Annotated[str | None, Query(max_length=180)] = None,
    company: Annotated[str | None, Query(max_length=240)] = None,
    phone: Annotated[str | None, Query(max_length=64)] = None,
    city: Annotated[str | None, Query(max_length=120)] = None,
    province: Annotated[str | None, Query(max_length=120)] = None,
    product: Annotated[str | None, Query(max_length=240)] = None,
    product_category: Annotated[str | None, Query(max_length=180)] = None,
    outcome: CallOutcome | None = None,
    sales_stage: Annotated[str | None, Query(max_length=80)] = None,
    lead_temperature: Annotated[str | None, Query(max_length=24)] = None,
    followup_required: bool | None = None,
    followup_overdue: bool | None = None,
    min_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    max_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    sentiment: Annotated[str | None, Query(max_length=24)] = None,
    risk_flag: bool | None = None,
    status_filter: Annotated[CallStatus | None, Query(alias="status")] = None,
    direction: Annotated[str | None, Query(max_length=16)] = None,
    min_duration: Annotated[float | None, Query(ge=0)] = None,
    max_duration: Annotated[float | None, Query(ge=0)] = None,
    source_filename: Annotated[str | None, Query(max_length=500)] = None,
    has_error: bool | None = None,
    manually_corrected: bool | None = None,
):
    if min_score is not None and max_score is not None and min_score > max_score:
        raise HTTPException(status_code=422, detail="invalid_score_range")
    if min_duration is not None and max_duration is not None and min_duration > max_duration:
        raise HTTPException(status_code=422, detail="invalid_duration_range")
    conditions = _call_scope(principal)
    if status_filter:
        conditions.append(Call.status == status_filter)
    if outcome:
        conditions.append(Call.outcome == outcome)
    if date_from:
        conditions.append(Call.created_at >= datetime.combine(date_from, time.min, tzinfo=UTC))
    if date_to:
        conditions.append(
            Call.created_at < datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=UTC)
        )
    text_filters = (
        (
            seller,
            or_(Call.seller_name.ilike(f"%{seller}%"), Call.seller_email.ilike(f"%{seller}%"))
            if seller
            else None,
        ),
        (customer, Call.customer_name.ilike(f"%{customer}%") if customer else None),
        (company, CallExtraction.company.ilike(f"%{company}%") if company else None),
        (phone, CallExtraction.phone.ilike(f"%{phone}%") if phone else None),
        (city, CallExtraction.city.ilike(f"%{city}%") if city else None),
        (province, CallExtraction.province.ilike(f"%{province}%") if province else None),
        (product, CallExtraction.product.ilike(f"%{product}%") if product else None),
        (
            product_category,
            CallExtraction.product_category.ilike(f"%{product_category}%")
            if product_category
            else None,
        ),
        (sales_stage, CallExtraction.sales_stage == sales_stage if sales_stage else None),
        (
            lead_temperature,
            CallExtraction.lead_temperature == lead_temperature if lead_temperature else None,
        ),
        (sentiment, CallExtraction.sentiment == sentiment if sentiment else None),
        (direction, Call.direction == direction if direction else None),
        (
            source_filename,
            Call.original_file_name.ilike(f"%{source_filename}%") if source_filename else None,
        ),
    )
    conditions.extend(
        expression for value, expression in text_filters if value and expression is not None
    )
    if q:
        normalized_q = normalize_persian(q)
        pattern = f"%{normalized_q}%"
        conditions.append(
            or_(
                Call.customer_name.ilike(pattern),
                Call.seller_name.ilike(pattern),
                Call.original_file_name.ilike(pattern),
                CallExtraction.company.ilike(pattern),
                CallExtraction.product.ilike(pattern),
                CallExtraction.phone.ilike(pattern),
            )
        )
    if followup_required is not None:
        conditions.append(CallExtraction.followup_required.is_(followup_required))
    if followup_overdue is not None:
        overdue = CallExtraction.followup_required.is_(True) & (
            CallExtraction.followup_due_at < datetime.now(UTC)
        )
        conditions.append(overdue if followup_overdue else ~overdue)
    if risk_flag is not None:
        conditions.append(CallExtraction.risk_flag.is_(risk_flag))
    if min_score is not None:
        conditions.append(Call.score >= min_score)
    if max_score is not None:
        conditions.append(Call.score <= max_score)
    if min_duration is not None:
        conditions.append(Call.duration_seconds >= min_duration)
    if max_duration is not None:
        conditions.append(Call.duration_seconds <= max_duration)
    if has_error is not None:
        conditions.append(Call.error_code.is_not(None) if has_error else Call.error_code.is_(None))
    if manually_corrected is not None:
        conditions.append(Call.manually_corrected.is_(manually_corrected))

    sort_columns = {
        "created_at": Call.created_at,
        "updated_at": Call.updated_at,
        "score": Call.score,
        "duration": Call.duration_seconds,
        "customer": Call.customer_name,
        "seller": Call.seller_name,
        "outcome": Call.outcome,
        "followup_due_at": CallExtraction.followup_due_at,
    }
    if sort not in sort_columns or order not in {"asc", "desc"}:
        raise HTTPException(status_code=422, detail="invalid_sort")
    base = (
        select(Call, CallExtraction)
        .outerjoin(CallExtraction, CallExtraction.call_id == Call.id)
        .where(*conditions)
    )
    total = (
        await session.scalar(
            select(func.count(Call.id))
            .outerjoin(CallExtraction, CallExtraction.call_id == Call.id)
            .where(*conditions)
        )
        or 0
    )
    ordering = asc(sort_columns[sort]) if order == "asc" else desc(sort_columns[sort])
    rows = (
        await session.execute(
            base.order_by(ordering, Call.id).offset((page - 1) * page_size).limit(page_size)
        )
    ).all()
    pages = (total + page_size - 1) // page_size
    return PaginatedCalls(
        items=[_call_read(call, extraction) for call, extraction in rows],
        page=page,
        page_size=page_size,
        total=total,
        pages=pages,
        next_cursor=str(page + 1) if page < pages else None,
    )


@app.post("/api/v1/calls", response_model=CallRead, status_code=status.HTTP_202_ACCEPTED)
async def create_call(
    principal: Annotated[
        Principal,
        Depends(require_roles(Role.admin, Role.manager, Role.supervisor, Role.agent, Role.seller)),
    ],
    session: Annotated[AsyncSession, Depends(db_session)],
    audio: Annotated[UploadFile, File()],
    recording_consent: Annotated[bool, Form()] = False,
    seller_email: Annotated[str | None, Form()] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    security_settings = await session.scalar(
        select(SecuritySetting).where(SecuritySetting.tenant_id == principal.tenant_id)
    )
    if (security_settings is None or security_settings.require_consent) and not recording_consent:
        raise HTTPException(status_code=422, detail="recording_consent_required")
    if not audio.content_type or not audio.content_type.startswith("audio/"):
        raise HTTPException(status_code=415, detail="unsupported_audio_type")
    if idempotency_key:
        existing = await session.scalar(
            select(Call).where(
                Call.tenant_id == principal.tenant_id, Call.external_id == idempotency_key
            )
        )
        if existing:
            return existing

    size_bytes = await _upload_size(audio)
    if size_bytes > settings.max_audio_bytes:
        raise HTTPException(status_code=413, detail="audio_too_large")
    if size_bytes <= 0:
        raise HTTPException(status_code=422, detail="audio_empty")
    await audio.seek(0)
    resolved_seller_email = _effective_seller_email(principal, seller_email)
    if resolved_seller_email and principal.role not in {Role.seller, Role.agent}:
        seller_membership = await session.scalar(
            select(Membership).where(
                Membership.tenant_id == principal.tenant_id,
                Membership.email == resolved_seller_email,
                Membership.active.is_(True),
                Membership.role.in_([Role.agent, Role.seller]),
            )
        )
        if seller_membership is None:
            raise HTTPException(status_code=422, detail="seller_not_found")
    call = Call(
        tenant_id=principal.tenant_id,
        external_id=idempotency_key,
        original_file_name=audio.filename or "call-audio",
        object_key="pending",
        mime_type=audio.content_type,
        size_bytes=size_bytes,
        seller_email=resolved_seller_email,
        source="api",
        status=CallStatus.uploaded,
    )
    session.add(call)
    await session.flush()

    call.object_key = await storage.upload(
        principal.tenant_id, call.id, call.original_file_name, call.mime_type, audio.file
    )
    call.status = CallStatus.queued
    await session.commit()
    await session.refresh(call)
    process_call.delay(str(call.id), str(principal.tenant_id))
    return call


@app.get("/api/v1/calls/{call_id}")
async def get_call(
    call_id: uuid.UUID,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    call = await session.scalar(
        select(Call).where(Call.id == call_id, Call.tenant_id == principal.tenant_id)
    )
    if not call or (
        principal.role in {Role.seller, Role.agent} and call.seller_email != principal.email
    ):
        raise HTTPException(status_code=404, detail="call_not_found")
    segments = list(
        (
            await session.scalars(
                select(TranscriptSegment)
                .where(TranscriptSegment.call_id == call.id)
                .order_by(TranscriptSegment.position)
            )
        ).all()
    )
    extraction = await session.scalar(
        select(CallExtraction).where(CallExtraction.call_id == call.id)
    )
    evidence = list(
        (
            await session.scalars(
                select(ExtractionEvidence)
                .where(ExtractionEvidence.call_id == call.id)
                .order_by(ExtractionEvidence.field_name, ExtractionEvidence.segment_position)
            )
        ).all()
    )
    events = list(
        (
            await session.scalars(
                select(PipelineEvent)
                .where(PipelineEvent.call_id == call.id)
                .order_by(PipelineEvent.created_at)
            )
        ).all()
    )
    errors = list(
        (
            await session.scalars(
                select(ProcessingError)
                .where(ProcessingError.call_id == call.id)
                .order_by(ProcessingError.created_at.desc())
            )
        ).all()
    )
    tasks = list(
        (
            await session.scalars(
                select(Task).where(Task.call_id == call.id).order_by(Task.created_at.desc())
            )
        ).all()
    )
    security_settings = await session.scalar(
        select(SecuritySetting).where(SecuritySetting.tenant_id == principal.tenant_id)
    )
    return {
        "call": _call_read(call, extraction),
        "analysis": call.analysis_json,
        "extraction": {
            "customer_name": extraction.customer_name,
            "phone": extraction.phone,
            "company": extraction.company,
            "city": extraction.city,
            "province": extraction.province,
            "product": extraction.product,
            "product_category": extraction.product_category,
            "amount": extraction.amount,
            "currency": extraction.currency,
            "followup_due_at": extraction.followup_due_at,
            "followup_required": extraction.followup_required,
            "sales_stage": extraction.sales_stage,
            "lead_temperature": extraction.lead_temperature,
            "sentiment": extraction.sentiment,
            "risk_flag": extraction.risk_flag,
            "need": extraction.need,
            "budget": extraction.budget_text,
            "promise": extraction.promise_text,
            "confidence": extraction.confidence,
            "validated": extraction.validated,
        }
        if extraction
        else None,
        "evidence": [
            {
                "field": item.field_name,
                "value": item.value_text,
                "segment_position": item.segment_position,
                "quote": item.quote,
                "timestamp_seconds": item.timestamp_seconds,
                "confidence": item.confidence,
                "supported": item.supported,
            }
            for item in evidence
        ],
        "segments": [
            {
                "id": item.id,
                "position": item.position,
                "speaker": item.speaker_label,
                "speaker_id": item.speaker_id,
                "role": "seller" if item.speaker_role == "agent" else item.speaker_role,
                "canonical_role": item.speaker_role,
                "role_confidence": item.speaker_role_confidence,
                "start": item.start_seconds,
                "end": item.end_seconds,
                "content": item.content,
                "normalized_text": item.normalized_text,
                "manually_corrected": item.is_manually_corrected,
                "corrected_at": item.corrected_at,
                "edited_by": item.edited_by,
            }
            for item in segments
        ],
        "followups": [
            {
                "id": item.id,
                "title": item.title,
                "priority": item.priority,
                "status": item.status,
                "due_at": item.due_at,
                "assignee_email": item.assignee_email,
                "ai_suggested": item.ai_suggested,
            }
            for item in tasks
        ],
        "processing": {
            "retry_count": call.retry_count,
            "next_retry_at": call.next_retry_at,
            "last_successful_stage": call.last_successful_stage,
            "events": [
                {
                    "id": item.id,
                    "from_state": item.from_state,
                    "to_state": item.to_state,
                    "stage": item.stage,
                    "attempt": item.attempt,
                    "started_at": item.started_at,
                    "finished_at": item.finished_at,
                    "duration_ms": item.duration_ms,
                    "metadata": item.metadata_json,
                }
                for item in events
            ],
            "errors": [
                {
                    "id": item.id,
                    "stage": item.stage,
                    "code": item.code,
                    "category": item.category,
                    "transient": item.transient,
                    "attempt": item.attempt,
                    "message": item.message,
                    "resolved_at": item.resolved_at,
                    "created_at": item.created_at,
                }
                for item in errors
            ],
        },
        "audio_url": await storage.signed_url(call.object_key)
        if security_settings is None or security_settings.audio_download_enabled
        else None,
    }


@app.post("/api/v1/calls/{call_id}/reprocess", status_code=202)
async def reprocess_call(
    call_id: uuid.UUID,
    payload: ReprocessRequest | None,
    principal: Annotated[
        Principal, Depends(require_roles(Role.admin, Role.manager, Role.supervisor))
    ],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    call = await session.scalar(
        select(Call).where(Call.id == call_id, Call.tenant_id == principal.tenant_id)
    )
    if not call or (
        principal.role in {Role.seller, Role.agent} and call.seller_email != principal.email
    ):
        raise HTTPException(status_code=404, detail="call_not_found")
    mode = payload.mode if payload else "resume"
    call.status = CallStatus.queued
    call.error_message = None
    call.error_code = None
    call.next_retry_at = None
    if mode == "full":
        call.retry_count = 0
    add_audit(
        session,
        principal,
        "call.reprocess_requested",
        "call",
        call.id,
        {"mode": mode, "reason": payload.reason if payload else None},
    )
    await session.commit()
    process_call.delay(str(call.id), str(principal.tenant_id), mode)
    return {"status": "queued", "mode": mode}


@app.patch("/api/v1/calls/{call_id}/outcome")
async def confirm_outcome(
    call_id: uuid.UUID,
    outcome: CallOutcome,
    principal: Annotated[
        Principal,
        Depends(require_roles(Role.admin, Role.manager, Role.supervisor, Role.agent, Role.seller)),
    ],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    call = await session.scalar(
        select(Call).where(Call.id == call_id, Call.tenant_id == principal.tenant_id)
    )
    if not call or (
        principal.role in {Role.seller, Role.agent} and call.seller_email != principal.email
    ):
        raise HTTPException(status_code=404, detail="call_not_found")
    call.outcome = outcome
    call.outcome_confirmed = True
    await session.commit()
    return {"outcome": outcome, "confirmed": True}


@app.patch("/api/v1/transcript-segments/{segment_id}")
async def edit_segment(
    segment_id: uuid.UUID,
    payload: SegmentCorrection,
    principal: Annotated[
        Principal,
        Depends(require_roles(Role.admin, Role.manager, Role.supervisor, Role.agent, Role.seller)),
    ],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    segment = await session.scalar(
        select(TranscriptSegment).where(
            TranscriptSegment.id == segment_id, TranscriptSegment.tenant_id == principal.tenant_id
        )
    )
    if not segment:
        raise HTTPException(status_code=404, detail="segment_not_found")
    call = await session.scalar(
        select(Call).where(Call.id == segment.call_id, Call.tenant_id == principal.tenant_id)
    )
    if not call or (
        principal.role in {Role.seller, Role.agent} and call.seller_email != principal.email
    ):
        raise HTTPException(status_code=404, detail="call_not_found")
    canonical_role = "agent" if payload.speaker_role == "seller" else payload.speaker_role
    session.add(
        TranscriptCorrection(
            tenant_id=principal.tenant_id,
            call_id=segment.call_id,
            segment_id=segment.id,
            actor_email=principal.email,
            old_content=segment.content,
            new_content=payload.content.strip(),
            old_role=segment.speaker_role,
            new_role=canonical_role,
        )
    )
    segment.content = payload.content.strip()
    segment.normalized_text = normalize_persian(segment.content)
    segment.speaker_role = canonical_role
    segment.edited_by = principal.email
    segment.is_manually_corrected = True
    segment.correction_user_id = principal.email
    segment.corrected_at = datetime.now(UTC)
    call.manually_corrected = True
    call.status = CallStatus.queued if payload.reanalyze else CallStatus.review_needed
    add_audit(
        session,
        principal,
        "transcript.corrected",
        "transcript_segment",
        segment.id,
        {"call_id": str(call.id), "reanalyze": payload.reanalyze},
    )
    await session.commit()
    if payload.reanalyze:
        process_call.delay(str(call.id), str(principal.tenant_id), "reanalyze")
    return {"status": "updated", "reanalyze_queued": payload.reanalyze}


@app.patch("/api/v1/calls/{call_id}/speaker-roles")
async def update_speaker_roles(
    call_id: uuid.UUID,
    payload: SpeakerRolesPatch,
    principal: Annotated[
        Principal,
        Depends(require_roles(Role.admin, Role.manager, Role.supervisor, Role.agent, Role.seller)),
    ],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    call = await session.scalar(
        select(Call).where(Call.id == call_id, Call.tenant_id == principal.tenant_id)
    )
    if not call or (
        principal.role in {Role.seller, Role.agent} and call.seller_email != principal.email
    ):
        raise HTTPException(status_code=404, detail="call_not_found")
    assignments = {
        item.speaker_id: ("agent" if item.role == "seller" else item.role)
        for item in payload.assignments
    }
    segments = list(
        (
            await session.scalars(
                select(TranscriptSegment).where(TranscriptSegment.call_id == call.id)
            )
        ).all()
    )
    changed = 0
    now = datetime.now(UTC)
    for segment in segments:
        identity = segment.speaker_id or segment.speaker_label
        new_role = assignments.get(identity)
        if new_role is None or new_role == segment.speaker_role:
            continue
        session.add(
            TranscriptCorrection(
                tenant_id=principal.tenant_id,
                call_id=call.id,
                segment_id=segment.id,
                actor_email=principal.email,
                old_content=segment.content,
                new_content=segment.content,
                old_role=segment.speaker_role,
                new_role=new_role,
            )
        )
        segment.speaker_role = new_role
        segment.speaker_role_confidence = 1.0
        segment.is_manually_corrected = True
        segment.correction_user_id = principal.email
        segment.edited_by = principal.email
        segment.corrected_at = now
        changed += 1
    if changed == 0:
        raise HTTPException(status_code=422, detail="no_matching_speakers")
    call.manually_corrected = True
    call.status = CallStatus.queued if payload.reanalyze else CallStatus.review_needed
    add_audit(
        session,
        principal,
        "speaker_roles.corrected",
        "call",
        call.id,
        {"changed_segments": changed, "reanalyze": payload.reanalyze},
    )
    await session.commit()
    if payload.reanalyze:
        process_call.delay(str(call.id), str(principal.tenant_id), "reanalyze")
    return {"status": "updated", "changed_segments": changed, "reanalyze_queued": payload.reanalyze}


@app.post("/api/v1/messages/{message_id}/approve")
async def approve_message(
    message_id: uuid.UUID,
    principal: Annotated[
        Principal, Depends(require_roles(Role.admin, Role.manager, Role.supervisor))
    ],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    draft = await session.scalar(
        select(MessageDraft).where(
            MessageDraft.id == message_id, MessageDraft.tenant_id == principal.tenant_id
        )
    )
    if not draft:
        raise HTTPException(status_code=404, detail="message_not_found")
    if draft.status != "pending_approval":
        raise HTTPException(status_code=409, detail="message_not_pending")
    draft.status = "approved"
    draft.approved_by = principal.email
    await session.commit()
    return {"status": "approved"}


@app.get("/api/v1/search")
async def search_calls(
    q: Annotated[str, Query(min_length=2, max_length=300)],
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    normalized = normalize_persian(q)
    rows = (
        (
            await session.execute(
                text("""
            SELECT s.call_id, s.position, s.start_seconds, s.speaker_label, s.content
            FROM transcript_segments s
            JOIN calls c ON c.id = s.call_id
            WHERE s.tenant_id = :tenant_id
              AND (:seller_email IS NULL OR c.seller_email = :seller_email)
              AND (s.content ILIKE :query OR s.normalized_text ILIKE :query)
            ORDER BY s.call_id, s.position LIMIT 50
        """),
                {
                    "tenant_id": principal.tenant_id,
                    "seller_email": principal.email
                    if principal.role in {Role.seller, Role.agent}
                    else None,
                    "query": f"%{normalized}%",
                },
            )
        )
        .mappings()
        .all()
    )
    return {"query": normalized, "mode": "hybrid-ready", "evidence": list(rows)}


@app.get("/api/v1/tasks")
async def list_tasks(
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(db_session)],
    bucket: Annotated[
        str | None,
        Query(
            pattern="^(all|today|needs_attention|overdue|unscheduled|upcoming|completed|done|cancelled)$"
        ),
    ] = "all",
    seller: Annotated[str | None, Query(max_length=320)] = None,
    customer: Annotated[str | None, Query(max_length=180)] = None,
):
    query = (
        select(Task)
        .where(Task.tenant_id == principal.tenant_id)
        .order_by(Task.created_at.desc())
        .limit(100)
    )
    if principal.role in {Role.seller, Role.agent}:
        query = query.where(Task.assignee_email == principal.email)
    elif seller:
        query = query.where(Task.assignee_email.ilike(f"%{seller}%"))
    if customer:
        query = query.where(Task.customer_name.ilike(f"%{customer}%"))
    now = datetime.now(UTC)
    if bucket == "needs_attention":
        query = query.where(
            or_(
                Task.status == "needs_scheduling",
                (Task.due_at < now) & Task.status.notin_(["done", "cancelled"]),
            )
        )
    elif bucket == "overdue":
        query = query.where(Task.due_at < now, Task.status.notin_(["done", "cancelled"]))
    elif bucket == "today":
        today = datetime.combine(now.date(), time.min, tzinfo=UTC)
        tomorrow = datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=UTC)
        query = query.where(
            Task.due_at >= today, Task.due_at < tomorrow, Task.status.notin_(["done", "cancelled"])
        )
    elif bucket == "unscheduled":
        query = query.where(
            or_(Task.status == "needs_scheduling", Task.due_at.is_(None)),
            Task.status.notin_(["done", "cancelled"]),
        )
    elif bucket == "upcoming":
        query = query.where(Task.due_at >= now, Task.status.notin_(["done", "cancelled"]))
    elif bucket in {"completed", "done"}:
        query = query.where(Task.status == "done")
    elif bucket == "cancelled":
        query = query.where(Task.status == "cancelled")
    rows = list((await session.scalars(query)).all())
    base = Task.tenant_id == principal.tenant_id
    role_filter = (
        Task.assignee_email == principal.email
        if principal.role in {Role.seller, Role.agent}
        else text("TRUE")
    )
    overdue_count = (
        await session.scalar(
            select(func.count(Task.id)).where(
                base, role_filter, Task.due_at < now, Task.status.notin_(["done", "cancelled"])
            )
        )
        or 0
    )
    unscheduled_count = (
        await session.scalar(
            select(func.count(Task.id)).where(base, role_filter, Task.status == "needs_scheduling")
        )
        or 0
    )
    return {
        "items": [
            {
                "id": row.id,
                "call_id": row.call_id,
                "title": row.title,
                "customer": row.customer_name,
                "priority": row.priority,
                "status": row.status,
                "due_at": row.due_at,
                "overdue": bool(
                    row.due_at and row.due_at < now and row.status not in {"done", "cancelled"}
                ),
            }
            for row in rows
        ],
        "bucket": bucket,
        "counts": {
            "overdue": overdue_count,
            "needs_scheduling": unscheduled_count,
            "needs_attention": overdue_count + unscheduled_count,
        },
    }


@app.post("/api/v1/tasks", status_code=201)
async def create_task(
    payload: TaskCreate,
    principal: Annotated[
        Principal,
        Depends(require_roles(Role.admin, Role.manager, Role.supervisor, Role.agent, Role.seller)),
    ],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    task = Task(
        tenant_id=principal.tenant_id,
        customer_name=payload.customer_name.strip(),
        title=payload.title.strip(),
        assignee_email=principal.email,
        priority=payload.priority,
        status="open",
        due_at=payload.due_at,
        ai_suggested=False,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return {"id": task.id, "title": task.title, "status": task.status}


@app.patch("/api/v1/tasks/{task_id}")
async def update_task(
    task_id: uuid.UUID,
    payload: TaskPatch,
    principal: Annotated[
        Principal,
        Depends(require_roles(Role.admin, Role.manager, Role.supervisor, Role.agent, Role.seller)),
    ],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    query = select(Task).where(Task.id == task_id, Task.tenant_id == principal.tenant_id)
    if principal.role in {Role.seller, Role.agent}:
        query = query.where(Task.assignee_email == principal.email)
    task = await session.scalar(query)
    if not task:
        raise HTTPException(status_code=404, detail="task_not_found")
    task.status = payload.status
    await session.commit()
    return {"id": task.id, "status": task.status}


@app.get("/api/v1/messages")
async def list_messages(
    principal: Annotated[
        Principal, Depends(require_roles(Role.admin, Role.manager, Role.supervisor))
    ],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    rows = list(
        (
            await session.scalars(
                select(MessageDraft)
                .where(MessageDraft.tenant_id == principal.tenant_id)
                .order_by(MessageDraft.created_at.desc())
                .limit(100)
            )
        ).all()
    )
    return {
        "items": [
            {
                "id": row.id,
                "channel": row.channel,
                "subject": row.subject,
                "content": row.content,
                "status": row.status,
            }
            for row in rows
        ]
    }


@app.get("/api/v1/integrations")
async def list_integrations(
    principal: Annotated[
        Principal, Depends(require_roles(Role.admin, Role.manager, Role.supervisor))
    ],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    rows = list(
        (
            await session.scalars(
                select(Integration)
                .where(Integration.tenant_id == principal.tenant_id)
                .order_by(Integration.created_at.desc())
            )
        ).all()
    )
    return {
        "items": [
            {"id": row.id, "kind": row.kind, "name": row.name, "status": row.status} for row in rows
        ]
    }


@app.post("/api/v1/integrations", status_code=201)
async def create_integration(
    payload: IntegrationCreate,
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    integration = Integration(
        tenant_id=principal.tenant_id,
        kind=payload.kind,
        name=payload.name,
        status="inactive",
        encrypted_config=secret_box.encrypt(payload.config) if payload.config else None,
    )
    session.add(integration)
    await session.commit()
    await session.refresh(integration)
    return {
        "id": integration.id,
        "kind": integration.kind,
        "name": integration.name,
        "status": integration.status,
    }


@app.get("/api/v1/admin/organization")
async def organization_settings(
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    organization = await session.scalar(
        select(Organization).where(Organization.id == principal.tenant_id)
    )
    if not organization:
        raise HTTPException(status_code=404, detail="organization_not_found")
    usage = (
        await session.scalar(
            select(func.sum(UsageLedger.quantity)).where(
                UsageLedger.tenant_id == principal.tenant_id,
                UsageLedger.metric == "transcription_minutes",
            )
        )
        or 0
    )
    return {
        "id": organization.id,
        "name": organization.name,
        "plan": organization.plan,
        "monthly_minute_limit": organization.monthly_minute_limit,
        "retention_days": organization.retention_days,
        "automation_mode": organization.automation_mode,
        "used_minutes": round(float(usage), 2),
    }


@app.patch("/api/v1/admin/organization")
async def update_organization_settings(
    payload: OrganizationSettingsPatch,
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    organization = await session.scalar(
        select(Organization).where(Organization.id == principal.tenant_id)
    )
    if not organization:
        raise HTTPException(status_code=404, detail="organization_not_found")
    if payload.retention_days is not None:
        organization.retention_days = payload.retention_days
    if payload.name is not None:
        organization.name = payload.name.strip()
    if payload.automation_mode is not None:
        organization.automation_mode = payload.automation_mode
    add_audit(
        session,
        principal,
        "organization.updated",
        "organization",
        organization.id,
        payload.model_dump(exclude_none=True),
    )
    await session.commit()
    return {"status": "updated"}


@app.get("/api/v1/admin/overview")
async def admin_overview(
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    members = (
        await session.scalar(
            select(func.count(Membership.id)).where(
                Membership.tenant_id == principal.tenant_id, Membership.active.is_(True)
            )
        )
        or 0
    )
    teams = (
        await session.scalar(
            select(func.count(Team.id)).where(
                Team.tenant_id == principal.tenant_id, Team.active.is_(True)
            )
        )
        or 0
    )
    calls = (
        await session.scalar(
            select(func.count(Call.id)).where(Call.tenant_id == principal.tenant_id)
        )
        or 0
    )
    seconds = (
        await session.scalar(
            select(func.coalesce(func.sum(Call.duration_seconds), 0)).where(
                Call.tenant_id == principal.tenant_id
            )
        )
        or 0
    )
    storage_bytes = (
        await session.scalar(
            select(func.coalesce(func.sum(Call.size_bytes), 0)).where(
                Call.tenant_id == principal.tenant_id
            )
        )
        or 0
    )
    pending_tasks = (
        await session.scalar(
            select(func.count(Task.id)).where(
                Task.tenant_id == principal.tenant_id, Task.status.notin_(["done", "cancelled"])
            )
        )
        or 0
    )
    active_integrations = (
        await session.scalar(
            select(func.count(Integration.id)).where(
                Integration.tenant_id == principal.tenant_id, Integration.status == "active"
            )
        )
        or 0
    )
    active_rules = (
        await session.scalar(
            select(func.count(AutomationRule.id)).where(
                AutomationRule.tenant_id == principal.tenant_id, AutomationRule.enabled.is_(True)
            )
        )
        or 0
    )
    return {
        "members": members,
        "teams": teams,
        "calls": calls,
        "used_minutes": round(float(seconds) / 60, 1),
        "storage_bytes": storage_bytes,
        "pending_tasks": pending_tasks,
        "active_integrations": active_integrations,
        "active_rules": active_rules,
    }


@app.get("/api/v1/admin/members")
async def admin_members(
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    rows = list(
        (
            await session.scalars(
                select(Membership)
                .where(Membership.tenant_id == principal.tenant_id)
                .order_by(Membership.display_name)
            )
        ).all()
    )
    teams = {
        row.id: row.name
        for row in (
            await session.scalars(select(Team).where(Team.tenant_id == principal.tenant_id))
        ).all()
    }
    return {
        "items": [
            {
                "id": row.id,
                "email": row.email,
                "full_name": row.display_name,
                "role": row.role.value,
                "active": row.active,
                "team_id": row.team_id,
                "team_name": teams.get(row.team_id),
                "last_login_at": None,
            }
            for row in rows
        ]
    }


@app.post("/api/v1/admin/members", status_code=201)
async def create_admin_member(
    payload: MemberCreate,
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    email = payload.email.strip().lower()
    if await session.scalar(
        select(Membership).where(
            Membership.tenant_id == principal.tenant_id, Membership.email == email
        )
    ):
        raise HTTPException(status_code=409, detail="email_exists")
    if payload.team_id and not await session.scalar(
        select(Team).where(Team.id == payload.team_id, Team.tenant_id == principal.tenant_id)
    ):
        raise HTTPException(status_code=404, detail="team_not_found")
    try:
        await keycloak_admin.create_user(
            email,
            payload.full_name.strip(),
            payload.password,
            tenant_id=str(principal.tenant_id),
            realm_role=payload.role,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail="identity_provider_unavailable") from exc
    member = Membership(
        tenant_id=principal.tenant_id,
        email=email,
        display_name=payload.full_name.strip(),
        role=Role(payload.role),
        team_id=payload.team_id,
        active=True,
    )
    session.add(member)
    await session.flush()
    add_audit(
        session,
        principal,
        "member.created",
        "member",
        member.id,
        {"email": email, "role": payload.role},
    )
    await session.commit()
    await session.refresh(member)
    return {
        "member": {
            "id": member.id,
            "email": member.email,
            "full_name": member.display_name,
            "role": member.role.value,
            "active": member.active,
            "team_id": member.team_id,
        }
    }


@app.patch("/api/v1/admin/members/{member_id}")
async def update_admin_member(
    member_id: uuid.UUID,
    payload: MemberPatch,
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    member = await session.scalar(
        select(Membership).where(
            Membership.id == member_id, Membership.tenant_id == principal.tenant_id
        )
    )
    if not member:
        raise HTTPException(status_code=404, detail="member_not_found")
    if payload.team_id and not await session.scalar(
        select(Team).where(Team.id == payload.team_id, Team.tenant_id == principal.tenant_id)
    ):
        raise HTTPException(status_code=404, detail="team_not_found")
    if member.role == Role.admin and (payload.role != "admin" or not payload.active):
        count = (
            await session.scalar(
                select(func.count(Membership.id)).where(
                    Membership.tenant_id == principal.tenant_id,
                    Membership.role == Role.admin,
                    Membership.active.is_(True),
                )
            )
            or 0
        )
        if count <= 1:
            raise HTTPException(status_code=409, detail="last_admin_protected")
    member.role = Role(payload.role)
    member.team_id = payload.team_id
    member.active = payload.active
    add_audit(
        session, principal, "member.updated", "member", member.id, payload.model_dump(mode="json")
    )
    await session.commit()
    return {"status": "updated"}


@app.get("/api/v1/admin/teams")
async def admin_teams(
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    rows = list(
        (
            await session.scalars(
                select(Team)
                .where(Team.tenant_id == principal.tenant_id)
                .order_by(Team.created_at.desc())
            )
        ).all()
    )
    result = []
    for row in rows:
        count = (
            await session.scalar(
                select(func.count(Membership.id)).where(
                    Membership.tenant_id == principal.tenant_id, Membership.team_id == row.id
                )
            )
            or 0
        )
        result.append(
            {
                "id": row.id,
                "name": row.name,
                "description": row.description,
                "supervisor_email": row.supervisor_email,
                "active": row.active,
                "member_count": count,
            }
        )
    return {"items": result}


@app.post("/api/v1/admin/teams", status_code=201)
async def create_admin_team(
    payload: TeamCreate,
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    if await session.scalar(
        select(Team).where(Team.tenant_id == principal.tenant_id, Team.name == payload.name.strip())
    ):
        raise HTTPException(status_code=409, detail="team_exists")
    team = Team(
        tenant_id=principal.tenant_id,
        name=payload.name.strip(),
        description=payload.description.strip(),
        supervisor_email=payload.supervisor_email,
    )
    session.add(team)
    await session.flush()
    add_audit(session, principal, "team.created", "team", team.id, {"name": team.name})
    await session.commit()
    return {"id": team.id}


@app.patch("/api/v1/admin/teams/{team_id}")
async def update_admin_team(
    team_id: uuid.UUID,
    payload: TeamPatch,
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    team = await session.scalar(
        select(Team).where(Team.id == team_id, Team.tenant_id == principal.tenant_id)
    )
    if not team:
        raise HTTPException(status_code=404, detail="team_not_found")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(team, field, value.strip() if isinstance(value, str) else value)
    add_audit(
        session, principal, "team.updated", "team", team.id, payload.model_dump(exclude_none=True)
    )
    await session.commit()
    return {"status": "updated"}


@app.get("/api/v1/admin/scorecards")
async def list_scorecards(
    principal: Annotated[
        Principal, Depends(require_roles(Role.admin, Role.manager, Role.supervisor))
    ],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    rows = list(
        (
            await session.scalars(
                select(ScorecardVersion)
                .where(ScorecardVersion.tenant_id == principal.tenant_id)
                .order_by(ScorecardVersion.version.desc())
            )
        ).all()
    )
    return {
        "items": [
            {
                "id": row.id,
                "version": row.version,
                "name": row.name,
                "criteria": row.criteria_json,
                "active": row.active,
            }
            for row in rows
        ]
    }


@app.post("/api/v1/admin/scorecards", status_code=201)
async def create_scorecard(
    payload: ScorecardCreate,
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    latest = (
        await session.scalar(
            select(func.max(ScorecardVersion.version)).where(
                ScorecardVersion.tenant_id == principal.tenant_id
            )
        )
        or 0
    )
    previous = list(
        (
            await session.scalars(
                select(ScorecardVersion).where(
                    ScorecardVersion.tenant_id == principal.tenant_id,
                    ScorecardVersion.active.is_(True),
                )
            )
        ).all()
    )
    for item in previous:
        item.active = False
    version = ScorecardVersion(
        tenant_id=principal.tenant_id,
        version=latest + 1,
        name=payload.name,
        criteria_json=[item.model_dump() for item in payload.criteria],
        active=True,
    )
    session.add(version)
    await session.commit()
    await session.refresh(version)
    return {"id": version.id, "version": version.version, "active": version.active}


@app.post("/api/v1/admin/scorecards/{scorecard_id}/activate")
async def activate_scorecard(
    scorecard_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    target = await session.scalar(
        select(ScorecardVersion).where(
            ScorecardVersion.id == scorecard_id, ScorecardVersion.tenant_id == principal.tenant_id
        )
    )
    if not target:
        raise HTTPException(status_code=404, detail="scorecard_not_found")
    for row in (
        await session.scalars(
            select(ScorecardVersion).where(ScorecardVersion.tenant_id == principal.tenant_id)
        )
    ).all():
        row.active = row.id == target.id
    add_audit(session, principal, "scorecard.activated", "scorecard", target.id)
    await session.commit()
    return {"status": "activated"}


@app.get("/api/v1/admin/automations")
async def admin_automations(
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    rows = (
        await session.scalars(
            select(AutomationRule)
            .where(AutomationRule.tenant_id == principal.tenant_id)
            .order_by(AutomationRule.created_at.desc())
        )
    ).all()
    return {
        "items": [
            {
                "id": row.id,
                "name": row.name,
                "event": row.event,
                "action": row.action,
                "mode": row.mode,
                "enabled": row.enabled,
            }
            for row in rows
        ]
    }


@app.post("/api/v1/admin/automations", status_code=201)
async def create_admin_automation(
    payload: AutomationCreate,
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    rule = AutomationRule(
        tenant_id=principal.tenant_id,
        name=payload.name.strip(),
        event=payload.event,
        action=payload.action,
        mode=payload.mode,
        conditions_json={},
        enabled=True,
    )
    session.add(rule)
    await session.flush()
    add_audit(session, principal, "automation.created", "automation", rule.id, {"name": rule.name})
    await session.commit()
    return {"id": rule.id}


@app.patch("/api/v1/admin/automations/{rule_id}")
async def update_admin_automation(
    rule_id: uuid.UUID,
    payload: EnabledPatch,
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    rule = await session.scalar(
        select(AutomationRule).where(
            AutomationRule.id == rule_id, AutomationRule.tenant_id == principal.tenant_id
        )
    )
    if not rule:
        raise HTTPException(status_code=404, detail="automation_not_found")
    rule.enabled = payload.enabled
    add_audit(
        session, principal, "automation.toggled", "automation", rule.id, {"enabled": rule.enabled}
    )
    await session.commit()
    return {"status": "updated"}


@app.get("/api/v1/admin/integrations")
async def admin_integrations(
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    return await list_integrations(principal, session)


@app.post("/api/v1/admin/integrations", status_code=201)
async def create_admin_integration(
    payload: IntegrationCreate,
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    result = await create_integration(payload, principal, session)
    add_audit(
        session,
        principal,
        "integration.created",
        "integration",
        result["id"],
        {"name": payload.name, "kind": payload.kind},
    )
    await session.commit()
    return result


@app.patch("/api/v1/admin/integrations/{integration_id}")
async def update_admin_integration(
    integration_id: uuid.UUID,
    payload: IntegrationStatusPatch,
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    integration = await session.scalar(
        select(Integration).where(
            Integration.id == integration_id, Integration.tenant_id == principal.tenant_id
        )
    )
    if not integration:
        raise HTTPException(status_code=404, detail="integration_not_found")
    integration.status = payload.status
    add_audit(
        session,
        principal,
        "integration.toggled",
        "integration",
        integration.id,
        {"status": integration.status},
    )
    await session.commit()
    return {"status": integration.status}


@app.get("/api/v1/admin/ai-settings")
async def admin_ai_settings(
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    row = await session.scalar(select(AiSetting).where(AiSetting.tenant_id == principal.tenant_id))
    return {
        "provider": row.provider if row else "openai",
        "transcription_model": row.transcription_model if row else settings.transcription_model,
        "analysis_model": row.analysis_model if row else settings.analysis_model,
        "min_confidence": row.min_confidence if row else 0.75,
    }


@app.patch("/api/v1/admin/ai-settings")
async def update_admin_ai_settings(
    payload: AiSettingsPatch,
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    row = await session.scalar(select(AiSetting).where(AiSetting.tenant_id == principal.tenant_id))
    if not row:
        row = AiSetting(tenant_id=principal.tenant_id)
        session.add(row)
    row.provider = payload.provider
    row.transcription_model = payload.transcription_model
    row.analysis_model = payload.analysis_model
    row.min_confidence = payload.min_confidence
    add_audit(
        session,
        principal,
        "ai_settings.updated",
        "ai_settings",
        principal.tenant_id,
        payload.model_dump(),
    )
    await session.commit()
    return {"status": "updated"}


@app.get("/api/v1/admin/security")
async def admin_security(
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    row = await session.scalar(
        select(SecuritySetting).where(SecuritySetting.tenant_id == principal.tenant_id)
    )
    return {
        "require_consent": row.require_consent if row else True,
        "audio_download_enabled": row.audio_download_enabled if row else True,
    }


@app.patch("/api/v1/admin/security")
async def update_admin_security(
    payload: SecuritySettingsPatch,
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    row = await session.scalar(
        select(SecuritySetting).where(SecuritySetting.tenant_id == principal.tenant_id)
    )
    if not row:
        row = SecuritySetting(tenant_id=principal.tenant_id)
        session.add(row)
    row.require_consent = payload.require_consent
    row.audio_download_enabled = payload.audio_download_enabled
    add_audit(
        session,
        principal,
        "security.updated",
        "security",
        principal.tenant_id,
        payload.model_dump(),
    )
    await session.commit()
    return {"status": "updated"}


@app.get("/api/v1/admin/audit-logs")
async def admin_audit_logs(
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    rows = (
        await session.scalars(
            select(AuditLog)
            .where(AuditLog.tenant_id == principal.tenant_id)
            .order_by(AuditLog.created_at.desc())
            .limit(100)
        )
    ).all()
    return {
        "items": [
            {
                "id": row.id,
                "actor_email": row.actor_email,
                "action": row.action,
                "entity_type": row.entity_type,
                "entity_id": row.entity_id,
                "created_at": row.created_at,
            }
            for row in rows
        ]
    }


@app.get("/api/v1/calls/{call_id}/export.pdf")
async def export_call_pdf(
    call_id: uuid.UUID,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    call = await session.scalar(
        select(Call).where(Call.id == call_id, Call.tenant_id == principal.tenant_id)
    )
    if not call or (
        principal.role in {Role.seller, Role.agent} and call.seller_email != principal.email
    ):
        raise HTTPException(status_code=404, detail="call_not_found")
    segments = list(
        (
            await session.scalars(
                select(TranscriptSegment)
                .where(TranscriptSegment.call_id == call.id)
                .order_by(TranscriptSegment.position)
            )
        ).all()
    )
    content = render_call_pdf(call, segments, call.analysis_json, font_path=settings.pdf_font_path)
    return Response(
        content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="call-{call.id}.pdf"'},
    )


@app.get("/api/v1/calls/{call_id}/export.xlsx")
async def export_call_excel(
    call_id: uuid.UUID,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    call = await session.scalar(
        select(Call).where(Call.id == call_id, Call.tenant_id == principal.tenant_id)
    )
    if not call or (
        principal.role in {Role.seller, Role.agent} and call.seller_email != principal.email
    ):
        raise HTTPException(status_code=404, detail="call_not_found")
    extraction = await session.scalar(
        select(CallExtraction).where(CallExtraction.call_id == call.id)
    )
    segments = list(
        (
            await session.scalars(
                select(TranscriptSegment)
                .where(TranscriptSegment.call_id == call.id)
                .order_by(TranscriptSegment.position)
            )
        ).all()
    )
    tasks = list((await session.scalars(select(Task).where(Task.call_id == call.id))).all())
    segment_payload = [
        {
            "position": row.position,
            "start": row.start_seconds,
            "end": row.end_seconds,
            "speaker": row.speaker_label,
            "role": row.speaker_role,
            "content": row.content,
            "manually_corrected": row.is_manually_corrected,
        }
        for row in segments
    ]
    task_payload = [
        {"title": row.title, "priority": row.priority, "status": row.status, "due_at": row.due_at}
        for row in tasks
    ]
    content = render_call_xlsx(
        _call_read(call, extraction).model_dump(mode="json"),
        segment_payload,
        call.analysis_json,
        task_payload,
    )
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="call-{call.id}.xlsx"'},
    )


@app.get("/api/v1/exports/calls.xlsx")
async def export_filtered_calls_excel(
    principal: Annotated[
        Principal, Depends(require_roles(Role.admin, Role.manager, Role.supervisor))
    ],
    session: Annotated[AsyncSession, Depends(db_session)],
    q: Annotated[str | None, Query(max_length=300)] = None,
    sort: str = "created_at",
    order: str = "desc",
    status_filter: Annotated[CallStatus | None, Query(alias="status")] = None,
    outcome: CallOutcome | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    seller: Annotated[str | None, Query(max_length=320)] = None,
    customer: Annotated[str | None, Query(max_length=180)] = None,
    company: Annotated[str | None, Query(max_length=240)] = None,
    phone: Annotated[str | None, Query(max_length=64)] = None,
    city: Annotated[str | None, Query(max_length=120)] = None,
    province: Annotated[str | None, Query(max_length=120)] = None,
    product: Annotated[str | None, Query(max_length=240)] = None,
    product_category: Annotated[str | None, Query(max_length=180)] = None,
    sales_stage: Annotated[str | None, Query(max_length=80)] = None,
    lead_temperature: Annotated[str | None, Query(max_length=24)] = None,
    followup_required: bool | None = None,
    followup_overdue: bool | None = None,
    min_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    max_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    sentiment: Annotated[str | None, Query(max_length=24)] = None,
    risk_flag: bool | None = None,
    direction: Annotated[str | None, Query(max_length=16)] = None,
    min_duration: Annotated[float | None, Query(ge=0)] = None,
    max_duration: Annotated[float | None, Query(ge=0)] = None,
    source_filename: Annotated[str | None, Query(max_length=500)] = None,
    has_error: bool | None = None,
    manually_corrected: bool | None = None,
):
    if min_score is not None and max_score is not None and min_score > max_score:
        raise HTTPException(status_code=422, detail="invalid_score_range")
    if min_duration is not None and max_duration is not None and min_duration > max_duration:
        raise HTTPException(status_code=422, detail="invalid_duration_range")
    conditions = [Call.tenant_id == principal.tenant_id]
    if status_filter:
        conditions.append(Call.status == status_filter)
    if outcome:
        conditions.append(Call.outcome == outcome)
    if date_from:
        conditions.append(Call.created_at >= datetime.combine(date_from, time.min, tzinfo=UTC))
    if date_to:
        conditions.append(
            Call.created_at < datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=UTC)
        )
    text_filters = (
        (
            seller,
            or_(Call.seller_name.ilike(f"%{seller}%"), Call.seller_email.ilike(f"%{seller}%"))
            if seller
            else None,
        ),
        (customer, Call.customer_name.ilike(f"%{customer}%") if customer else None),
        (company, CallExtraction.company.ilike(f"%{company}%") if company else None),
        (phone, CallExtraction.phone.ilike(f"%{phone}%") if phone else None),
        (city, CallExtraction.city.ilike(f"%{city}%") if city else None),
        (province, CallExtraction.province.ilike(f"%{province}%") if province else None),
        (product, CallExtraction.product.ilike(f"%{product}%") if product else None),
        (
            product_category,
            CallExtraction.product_category.ilike(f"%{product_category}%")
            if product_category
            else None,
        ),
        (sales_stage, CallExtraction.sales_stage == sales_stage if sales_stage else None),
        (
            lead_temperature,
            CallExtraction.lead_temperature == lead_temperature if lead_temperature else None,
        ),
        (sentiment, CallExtraction.sentiment == sentiment if sentiment else None),
        (direction, Call.direction == direction if direction else None),
        (
            source_filename,
            Call.original_file_name.ilike(f"%{source_filename}%") if source_filename else None,
        ),
    )
    conditions.extend(
        expression for value, expression in text_filters if value and expression is not None
    )
    if followup_required is not None:
        conditions.append(CallExtraction.followup_required.is_(followup_required))
    if followup_overdue is not None:
        overdue = CallExtraction.followup_required.is_(True) & (
            CallExtraction.followup_due_at < datetime.now(UTC)
        )
        conditions.append(overdue if followup_overdue else ~overdue)
    if risk_flag is not None:
        conditions.append(CallExtraction.risk_flag.is_(risk_flag))
    if min_score is not None:
        conditions.append(Call.score >= min_score)
    if max_score is not None:
        conditions.append(Call.score <= max_score)
    if min_duration is not None:
        conditions.append(Call.duration_seconds >= min_duration)
    if max_duration is not None:
        conditions.append(Call.duration_seconds <= max_duration)
    if has_error is not None:
        conditions.append(Call.error_code.is_not(None) if has_error else Call.error_code.is_(None))
    if manually_corrected is not None:
        conditions.append(Call.manually_corrected.is_(manually_corrected))
    if q:
        pattern = f"%{normalize_persian(q)}%"
        conditions.append(
            or_(
                Call.customer_name.ilike(pattern),
                Call.seller_name.ilike(pattern),
                CallExtraction.company.ilike(pattern),
                CallExtraction.product.ilike(pattern),
            )
        )
    sort_columns = {
        "created_at": Call.created_at,
        "updated_at": Call.updated_at,
        "score": Call.score,
        "duration": Call.duration_seconds,
        "customer": Call.customer_name,
        "seller": Call.seller_name,
        "outcome": Call.outcome,
        "followup_due_at": CallExtraction.followup_due_at,
    }
    if sort not in sort_columns or order not in {"asc", "desc"}:
        raise HTTPException(status_code=422, detail="invalid_sort")
    ordering = asc(sort_columns[sort]) if order == "asc" else desc(sort_columns[sort])
    rows = (
        await session.execute(
            select(Call, CallExtraction)
            .outerjoin(CallExtraction, CallExtraction.call_id == Call.id)
            .where(*conditions)
            .order_by(ordering, Call.id)
            .limit(10_000)
        )
    ).all()
    content = render_calls_xlsx(
        [_call_read(call, extraction).model_dump(mode="json") for call, extraction in rows]
    )
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="calls.xlsx"'},
    )


@app.get("/api/v1/admin/processing-operations")
async def processing_operations(
    principal: Annotated[
        Principal, Depends(require_roles(Role.admin, Role.manager, Role.supervisor))
    ],
    session: Annotated[AsyncSession, Depends(db_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    status_filter: Annotated[CallStatus | None, Query(alias="status")] = None,
):
    conditions = [Call.tenant_id == principal.tenant_id]
    if status_filter:
        conditions.append(Call.status == status_filter)
    else:
        conditions.append(
            Call.status.in_(
                [
                    CallStatus.queued,
                    CallStatus.retry_scheduled,
                    CallStatus.failed,
                    CallStatus.quarantined,
                ]
            )
        )
    total = await session.scalar(select(func.count(Call.id)).where(*conditions)) or 0
    rows = list(
        (
            await session.scalars(
                select(Call)
                .where(*conditions)
                .order_by(Call.updated_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return {
        "items": [
            {
                "id": row.id,
                "file_name": row.original_file_name,
                "status": row.status,
                "stage": row.last_successful_stage,
                "retry_count": row.retry_count,
                "next_retry_at": row.next_retry_at,
                "error_code": row.error_code,
                "error_message": row.error_message,
                "updated_at": row.updated_at,
            }
            for row in rows
        ],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@app.post("/api/v1/admin/processing-operations/{call_id}/actions", status_code=202)
async def processing_action(
    call_id: uuid.UUID,
    payload: ProcessingAction,
    principal: Annotated[
        Principal, Depends(require_roles(Role.admin, Role.manager, Role.supervisor))
    ],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    call = await session.scalar(
        select(Call).where(Call.id == call_id, Call.tenant_id == principal.tenant_id)
    )
    if not call:
        raise HTTPException(status_code=404, detail="call_not_found")
    if payload.action == "resolve_error":
        errors = list(
            (
                await session.scalars(
                    select(ProcessingError).where(
                        ProcessingError.call_id == call.id, ProcessingError.resolved_at.is_(None)
                    )
                )
            ).all()
        )
        now = datetime.now(UTC)
        for error in errors:
            error.resolved_at = now
        await session.commit()
        return {"status": "resolved", "count": len(errors)}
    if payload.action == "quarantine":
        call.status = CallStatus.quarantined
        call.next_retry_at = None
        await session.commit()
        return {"status": "quarantined"}
    mode = {"retry": "resume", "reanalyze": "reanalyze", "full_reprocess": "full"}[payload.action]
    call.status = CallStatus.queued
    call.error_code = None
    call.error_message = None
    call.next_retry_at = None
    if mode == "full":
        call.retry_count = 0
    add_audit(
        session,
        principal,
        "processing.action",
        "call",
        call.id,
        {"action": payload.action, "reason": payload.reason},
    )
    await session.commit()
    process_call.delay(str(call.id), str(principal.tenant_id), mode)
    return {"status": "queued", "mode": mode}


@app.get("/api/v1/admin/accuracy")
async def accuracy_status(
    principal: Annotated[
        Principal, Depends(require_roles(Role.admin, Role.manager, Role.supervisor))
    ],
):
    return {
        "measured": False,
        "wer": None,
        "cer": None,
        "entity_accuracy": None,
        "message": "Accuracy requires a reviewed real-call evaluation dataset; no percentage is claimed.",
    }


@app.get("/api/v1/admin/glossary")
async def list_glossary(
    principal: Annotated[
        Principal, Depends(require_roles(Role.admin, Role.manager, Role.supervisor))
    ],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    rows = list(
        (
            await session.scalars(
                select(GlossaryTerm)
                .where(GlossaryTerm.tenant_id == principal.tenant_id)
                .order_by(GlossaryTerm.term)
            )
        ).all()
    )
    return {
        "items": [
            {
                "id": row.id,
                "term": row.term,
                "category": row.category,
                "aliases": row.aliases_json,
                "active": row.active,
            }
            for row in rows
        ]
    }


@app.post("/api/v1/admin/glossary", status_code=201)
async def create_glossary(
    payload: GlossaryCreate,
    principal: Annotated[Principal, Depends(require_roles(Role.admin, Role.manager))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    normalized = normalize_persian(payload.term).casefold()
    if await session.scalar(
        select(GlossaryTerm.id).where(
            GlossaryTerm.tenant_id == principal.tenant_id,
            GlossaryTerm.normalized_term == normalized,
        )
    ):
        raise HTTPException(status_code=409, detail="glossary_term_exists")
    row = GlossaryTerm(
        tenant_id=principal.tenant_id,
        term=payload.term.strip(),
        normalized_term=normalized,
        category=payload.category,
        aliases_json=list(dict.fromkeys(payload.aliases)),
        active=payload.active,
    )
    session.add(row)
    await session.flush()
    add_audit(session, principal, "glossary.created", "glossary_term", row.id, {"term": row.term})
    await session.commit()
    return {"id": row.id}


@app.patch("/api/v1/admin/glossary/{term_id}")
async def update_glossary(
    term_id: uuid.UUID,
    payload: GlossaryPatch,
    principal: Annotated[Principal, Depends(require_roles(Role.admin, Role.manager))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    row = await session.scalar(
        select(GlossaryTerm).where(
            GlossaryTerm.id == term_id, GlossaryTerm.tenant_id == principal.tenant_id
        )
    )
    if not row:
        raise HTTPException(status_code=404, detail="glossary_term_not_found")
    if payload.term is not None:
        row.term = payload.term.strip()
        row.normalized_term = normalize_persian(row.term).casefold()
    if payload.category is not None:
        row.category = payload.category
    if payload.aliases is not None:
        row.aliases_json = list(dict.fromkeys(payload.aliases))
    if payload.active is not None:
        row.active = payload.active
    add_audit(session, principal, "glossary.updated", "glossary_term", row.id)
    await session.commit()
    return {"status": "updated"}


@app.delete("/api/v1/admin/glossary/{term_id}", status_code=204)
async def delete_glossary(
    term_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_roles(Role.admin, Role.manager))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    row = await session.scalar(
        select(GlossaryTerm).where(
            GlossaryTerm.id == term_id, GlossaryTerm.tenant_id == principal.tenant_id
        )
    )
    if not row:
        raise HTTPException(status_code=404, detail="glossary_term_not_found")
    await session.delete(row)
    add_audit(session, principal, "glossary.deleted", "glossary_term", row.id)
    await session.commit()
    return Response(status_code=204)


@app.get("/api/v1/admin/issabel-settings")
async def issabel_settings(
    principal: Annotated[Principal, Depends(require_roles(Role.admin, Role.manager))],
):
    return {
        "mode": settings.issabel_import_mode,
        "import_mode": settings.issabel_import_mode,
        "read_only": True,
        "configuration_source": "environment",
        "recordings_path": settings.issabel_recordings_path,
        "sftp_host": settings.issabel_sftp_host,
        "sftp_port": settings.issabel_sftp_port,
        "sftp_username": settings.issabel_sftp_username,
        "sftp_password_configured": bool(settings.issabel_sftp_password),
        "sftp_private_key_configured": bool(settings.issabel_sftp_private_key),
        "sftp_remote_path": settings.issabel_sftp_remote_path,
        "poll_interval": settings.issabel_poll_interval,
        "file_stability_seconds": settings.issabel_file_stability_seconds,
        "allowed_extensions": sorted(settings.issabel_extensions),
        "quarantine_path": settings.issabel_quarantine_path,
    }


@app.post("/api/v1/admin/issabel-settings/test")
async def test_issabel_settings(
    principal: Annotated[Principal, Depends(require_roles(Role.admin, Role.manager))],
):
    if settings.issabel_import_mode in {"local", "shared_folder"}:
        path = Path(settings.issabel_recordings_path).expanduser()
        return {
            "ok": path.is_dir(),
            "mode": settings.issabel_import_mode,
            "path": str(path),
            "readable": path.is_dir(),
        }
    if settings.issabel_import_mode == "sftp":
        return {"ok": False, "mode": "sftp", "error": "sftp_puller_not_installed"}
    return {"ok": False, "mode": "disabled", "error": "issabel_import_disabled"}
