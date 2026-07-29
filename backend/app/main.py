import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .database import engine, tenant_session
from .models import AiSetting, AuditLog, AutomationRule, Base, Call, CallOutcome, CallStatus, Integration, Membership, MessageDraft, Organization, Role, ScorecardVersion, SecuritySetting, Task, Team, TranscriptSegment, UsageLedger
from .schemas import AiSettingsPatch, AutomationCreate, CallRead, EnabledPatch, IntegrationCreate, IntegrationStatusPatch, MemberCreate, MemberPatch, OrganizationSettingsPatch, PaginatedCalls, ScorecardCreate, SecuritySettingsPatch, TaskCreate, TaskPatch, TeamCreate, TeamPatch
from .security import Principal, current_principal, require_roles
from .services.storage import storage
from .services.integrations import secret_box
from .services.keycloak import keycloak_admin
from .tasks import process_call


settings = get_settings()


def add_audit(session: AsyncSession, principal: Principal, action: str, entity_type: str, entity_id=None, metadata=None):
    session.add(AuditLog(tenant_id=principal.tenant_id, actor_email=principal.email, action=action,
                         entity_type=entity_type, entity_id=str(entity_id) if entity_id else None,
                         metadata_json=metadata))
app = FastAPI(
    title="Mokalemeban Sales Conversation Intelligence API",
    version="1.0.0",
    openapi_url="/api/v1/openapi.json",
    docs_url="/api/v1/docs",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Recording-Consent"],
)


@app.on_event("startup")
async def startup():
    if settings.environment == "development":
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.execute(
                text("""
                    INSERT INTO organizations (id, name, plan, monthly_minute_limit, retention_days, automation_mode)
                    VALUES (:id, 'فرازما', 'business', 2000, 30, 'approval')
                    ON CONFLICT (id) DO NOTHING
                """),
                {"id": settings.development_tenant_id},
            )
            policy_file = Path(__file__).resolve().parent.parent / "sql" / "001_row_level_security.sql"
            await connection.exec_driver_sql(policy_file.read_text(encoding="utf-8"))
        await storage.ensure_bucket()


async def db_session(
    principal: Annotated[Principal, Depends(current_principal)],
) -> AsyncIterator[AsyncSession]:
    async for session in tenant_session(str(principal.tenant_id)):
        yield session


@app.get("/health")
async def health():
    return {"status": "ok", "service": "mokalemeban-api", "version": "1.0.0"}


@app.get("/api/v1/overview")
async def overview(
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    base = Call.tenant_id == principal.tenant_id
    total = await session.scalar(select(func.count()).select_from(Call).where(base)) or 0
    completed = await session.scalar(
        select(func.count()).select_from(Call).where(base, Call.status == CallStatus.completed)
    ) or 0
    average_score = await session.scalar(select(func.avg(Call.score)).where(base))
    won = await session.scalar(
        select(func.count()).select_from(Call).where(base, Call.outcome == CallOutcome.won, Call.outcome_confirmed.is_(True))
    ) or 0
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
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    status_filter: CallStatus | None = None,
):
    query = select(Call).where(Call.tenant_id == principal.tenant_id).order_by(Call.created_at.desc()).limit(limit)
    if principal.role == Role.seller:
        query = query.where(Call.seller_email == principal.email)
    if status_filter:
        query = query.where(Call.status == status_filter)
    rows = list((await session.scalars(query)).all())
    return PaginatedCalls(items=[CallRead.model_validate(row) for row in rows])


@app.post("/api/v1/calls", response_model=CallRead, status_code=status.HTTP_202_ACCEPTED)
async def create_call(
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(db_session)],
    audio: Annotated[UploadFile, File()],
    recording_consent: Annotated[bool, Form()] = False,
    seller_email: Annotated[str | None, Form()] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    security_settings = await session.scalar(select(SecuritySetting).where(SecuritySetting.tenant_id == principal.tenant_id))
    if (security_settings is None or security_settings.require_consent) and not recording_consent:
        raise HTTPException(status_code=422, detail="recording_consent_required")
    if not audio.content_type or not audio.content_type.startswith("audio/"):
        raise HTTPException(status_code=415, detail="unsupported_audio_type")
    if idempotency_key:
        existing = await session.scalar(
            select(Call).where(Call.tenant_id == principal.tenant_id, Call.external_id == idempotency_key)
        )
        if existing:
            return existing

    content = await audio.read(settings.max_audio_bytes + 1)
    if len(content) > settings.max_audio_bytes:
        raise HTTPException(status_code=413, detail="audio_too_large")
    call = Call(
        tenant_id=principal.tenant_id,
        external_id=idempotency_key,
        original_file_name=audio.filename or "call-audio",
        object_key="pending",
        mime_type=audio.content_type,
        size_bytes=len(content),
        seller_email=seller_email,
        source="api",
        status=CallStatus.uploaded,
    )
    session.add(call)
    await session.flush()
    from io import BytesIO

    call.object_key = await storage.upload(
        principal.tenant_id, call.id, call.original_file_name, call.mime_type, BytesIO(content)
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
    call = await session.scalar(select(Call).where(Call.id == call_id, Call.tenant_id == principal.tenant_id))
    if not call or (principal.role == Role.seller and call.seller_email != principal.email):
        raise HTTPException(status_code=404, detail="call_not_found")
    segments = list((await session.scalars(
        select(TranscriptSegment).where(TranscriptSegment.call_id == call.id).order_by(TranscriptSegment.position)
    )).all())
    security_settings = await session.scalar(select(SecuritySetting).where(SecuritySetting.tenant_id == principal.tenant_id))
    return {
        "call": CallRead.model_validate(call),
        "analysis": call.analysis_json,
        "segments": [
            {"id": item.id, "position": item.position, "speaker": item.speaker_label,
             "role": item.speaker_role, "start": item.start_seconds, "end": item.end_seconds,
             "content": item.content}
            for item in segments
        ],
        "audio_url": await storage.signed_url(call.object_key) if security_settings is None or security_settings.audio_download_enabled else None,
    }


@app.post("/api/v1/calls/{call_id}/reprocess", status_code=202)
async def reprocess_call(
    call_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_roles(Role.admin, Role.supervisor))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    call = await session.scalar(select(Call).where(Call.id == call_id, Call.tenant_id == principal.tenant_id))
    if not call:
        raise HTTPException(status_code=404, detail="call_not_found")
    call.status = CallStatus.queued
    call.error_message = None
    await session.commit()
    process_call.delay(str(call.id), str(principal.tenant_id))
    return {"status": "queued"}


@app.patch("/api/v1/calls/{call_id}/outcome")
async def confirm_outcome(
    call_id: uuid.UUID,
    outcome: CallOutcome,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    call = await session.scalar(select(Call).where(Call.id == call_id, Call.tenant_id == principal.tenant_id))
    if not call:
        raise HTTPException(status_code=404, detail="call_not_found")
    call.outcome = outcome
    call.outcome_confirmed = True
    await session.commit()
    return {"outcome": outcome, "confirmed": True}


@app.patch("/api/v1/transcript-segments/{segment_id}")
async def edit_segment(
    segment_id: uuid.UUID,
    content: str,
    speaker_role: str,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    segment = await session.scalar(
        select(TranscriptSegment).where(TranscriptSegment.id == segment_id, TranscriptSegment.tenant_id == principal.tenant_id)
    )
    if not segment:
        raise HTTPException(status_code=404, detail="segment_not_found")
    if speaker_role not in {"seller", "customer", "unknown"}:
        raise HTTPException(status_code=422, detail="invalid_speaker_role")
    segment.content = content.strip()
    segment.speaker_role = speaker_role
    segment.edited_by = principal.email
    await session.commit()
    return {"status": "updated"}


@app.post("/api/v1/messages/{message_id}/approve")
async def approve_message(
    message_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require_roles(Role.admin, Role.supervisor))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    draft = await session.scalar(
        select(MessageDraft).where(MessageDraft.id == message_id, MessageDraft.tenant_id == principal.tenant_id)
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
    normalized = q.replace("ي", "ی").replace("ك", "ک")
    rows = (await session.execute(
        text("""
            SELECT s.call_id, s.position, s.start_seconds, s.speaker_label, s.content
            FROM transcript_segments s
            WHERE s.tenant_id = :tenant_id AND s.content ILIKE :query
            ORDER BY s.call_id, s.position LIMIT 50
        """),
        {"tenant_id": principal.tenant_id, "query": f"%{normalized}%"},
    )).mappings().all()
    return {"query": normalized, "mode": "hybrid-ready", "evidence": list(rows)}


@app.get("/api/v1/tasks")
async def list_tasks(
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    query = select(Task).where(Task.tenant_id == principal.tenant_id).order_by(Task.created_at.desc()).limit(100)
    if principal.role == Role.seller:
        query = query.where(Task.assignee_email == principal.email)
    rows = list((await session.scalars(query)).all())
    return {"items": [{"id": row.id, "title": row.title, "customer": row.customer_name, "priority": row.priority, "status": row.status, "due_at": row.due_at} for row in rows]}


@app.post("/api/v1/tasks", status_code=201)
async def create_task(
    payload: TaskCreate,
    principal: Annotated[Principal, Depends(current_principal)],
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
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    query = select(Task).where(Task.id == task_id, Task.tenant_id == principal.tenant_id)
    if principal.role == Role.seller:
        query = query.where(Task.assignee_email == principal.email)
    task = await session.scalar(query)
    if not task:
        raise HTTPException(status_code=404, detail="task_not_found")
    task.status = payload.status
    await session.commit()
    return {"id": task.id, "status": task.status}


@app.get("/api/v1/messages")
async def list_messages(
    principal: Annotated[Principal, Depends(require_roles(Role.admin, Role.supervisor))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    rows = list((await session.scalars(
        select(MessageDraft).where(MessageDraft.tenant_id == principal.tenant_id).order_by(MessageDraft.created_at.desc()).limit(100)
    )).all())
    return {"items": [{"id": row.id, "channel": row.channel, "subject": row.subject, "content": row.content, "status": row.status} for row in rows]}


@app.get("/api/v1/integrations")
async def list_integrations(
    principal: Annotated[Principal, Depends(require_roles(Role.admin, Role.supervisor))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    rows = list((await session.scalars(
        select(Integration).where(Integration.tenant_id == principal.tenant_id).order_by(Integration.created_at.desc())
    )).all())
    return {"items": [{"id": row.id, "kind": row.kind, "name": row.name, "status": row.status} for row in rows]}


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
    return {"id": integration.id, "kind": integration.kind, "name": integration.name, "status": integration.status}


@app.get("/api/v1/admin/organization")
async def organization_settings(
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    organization = await session.scalar(select(Organization).where(Organization.id == principal.tenant_id))
    if not organization:
        raise HTTPException(status_code=404, detail="organization_not_found")
    usage = await session.scalar(
        select(func.sum(UsageLedger.quantity)).where(
            UsageLedger.tenant_id == principal.tenant_id,
            UsageLedger.metric == "transcription_minutes",
        )
    ) or 0
    return {"id": organization.id, "name": organization.name, "plan": organization.plan,
            "monthly_minute_limit": organization.monthly_minute_limit,
            "retention_days": organization.retention_days,
            "automation_mode": organization.automation_mode,
            "used_minutes": round(float(usage), 2)}


@app.patch("/api/v1/admin/organization")
async def update_organization_settings(
    payload: OrganizationSettingsPatch,
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    organization = await session.scalar(select(Organization).where(Organization.id == principal.tenant_id))
    if not organization:
        raise HTTPException(status_code=404, detail="organization_not_found")
    if payload.retention_days is not None:
        organization.retention_days = payload.retention_days
    if payload.name is not None:
        organization.name = payload.name.strip()
    if payload.automation_mode is not None:
        organization.automation_mode = payload.automation_mode
    add_audit(session, principal, "organization.updated", "organization", organization.id,
              payload.model_dump(exclude_none=True))
    await session.commit()
    return {"status": "updated"}


@app.get("/api/v1/admin/overview")
async def admin_overview(
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    members = await session.scalar(select(func.count(Membership.id)).where(Membership.tenant_id == principal.tenant_id, Membership.active.is_(True))) or 0
    teams = await session.scalar(select(func.count(Team.id)).where(Team.tenant_id == principal.tenant_id, Team.active.is_(True))) or 0
    calls = await session.scalar(select(func.count(Call.id)).where(Call.tenant_id == principal.tenant_id)) or 0
    seconds = await session.scalar(select(func.coalesce(func.sum(Call.duration_seconds), 0)).where(Call.tenant_id == principal.tenant_id)) or 0
    storage_bytes = await session.scalar(select(func.coalesce(func.sum(Call.size_bytes), 0)).where(Call.tenant_id == principal.tenant_id)) or 0
    pending_tasks = await session.scalar(select(func.count(Task.id)).where(Task.tenant_id == principal.tenant_id, Task.status.notin_(["done", "cancelled"]))) or 0
    active_integrations = await session.scalar(select(func.count(Integration.id)).where(Integration.tenant_id == principal.tenant_id, Integration.status == "active")) or 0
    active_rules = await session.scalar(select(func.count(AutomationRule.id)).where(AutomationRule.tenant_id == principal.tenant_id, AutomationRule.enabled.is_(True))) or 0
    return {"members": members, "teams": teams, "calls": calls, "used_minutes": round(float(seconds) / 60, 1),
            "storage_bytes": storage_bytes, "pending_tasks": pending_tasks,
            "active_integrations": active_integrations, "active_rules": active_rules}


@app.get("/api/v1/admin/members")
async def admin_members(
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    rows = list((await session.scalars(select(Membership).where(Membership.tenant_id == principal.tenant_id).order_by(Membership.display_name))).all())
    teams = {row.id: row.name for row in (await session.scalars(select(Team).where(Team.tenant_id == principal.tenant_id))).all()}
    return {"items": [{"id": row.id, "email": row.email, "full_name": row.display_name, "role": row.role.value,
                       "active": row.active, "team_id": row.team_id, "team_name": teams.get(row.team_id),
                       "last_login_at": None} for row in rows]}


@app.post("/api/v1/admin/members", status_code=201)
async def create_admin_member(
    payload: MemberCreate,
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    email = payload.email.strip().lower()
    if await session.scalar(select(Membership).where(Membership.tenant_id == principal.tenant_id, Membership.email == email)):
        raise HTTPException(status_code=409, detail="email_exists")
    if payload.team_id and not await session.scalar(select(Team).where(Team.id == payload.team_id, Team.tenant_id == principal.tenant_id)):
        raise HTTPException(status_code=404, detail="team_not_found")
    try:
        await keycloak_admin.create_user(email, payload.full_name.strip(), payload.password)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="identity_provider_unavailable") from exc
    member = Membership(tenant_id=principal.tenant_id, email=email, display_name=payload.full_name.strip(), role=Role(payload.role), team_id=payload.team_id, active=True)
    session.add(member); await session.flush(); add_audit(session, principal, "member.created", "member", member.id, {"email": email, "role": payload.role})
    await session.commit(); await session.refresh(member)
    return {"member": {"id": member.id, "email": member.email, "full_name": member.display_name, "role": member.role.value, "active": member.active, "team_id": member.team_id}}


@app.patch("/api/v1/admin/members/{member_id}")
async def update_admin_member(
    member_id: uuid.UUID, payload: MemberPatch,
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    member = await session.scalar(select(Membership).where(Membership.id == member_id, Membership.tenant_id == principal.tenant_id))
    if not member: raise HTTPException(status_code=404, detail="member_not_found")
    if payload.team_id and not await session.scalar(select(Team).where(Team.id == payload.team_id, Team.tenant_id == principal.tenant_id)):
        raise HTTPException(status_code=404, detail="team_not_found")
    if member.role == Role.admin and (payload.role != "admin" or not payload.active):
        count = await session.scalar(select(func.count(Membership.id)).where(Membership.tenant_id == principal.tenant_id, Membership.role == Role.admin, Membership.active.is_(True))) or 0
        if count <= 1: raise HTTPException(status_code=409, detail="last_admin_protected")
    member.role = Role(payload.role); member.team_id = payload.team_id; member.active = payload.active
    add_audit(session, principal, "member.updated", "member", member.id, payload.model_dump(mode="json")); await session.commit()
    return {"status": "updated"}


@app.get("/api/v1/admin/teams")
async def admin_teams(
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    rows = list((await session.scalars(select(Team).where(Team.tenant_id == principal.tenant_id).order_by(Team.created_at.desc()))).all())
    result = []
    for row in rows:
        count = await session.scalar(select(func.count(Membership.id)).where(Membership.tenant_id == principal.tenant_id, Membership.team_id == row.id)) or 0
        result.append({"id": row.id, "name": row.name, "description": row.description, "supervisor_email": row.supervisor_email, "active": row.active, "member_count": count})
    return {"items": result}


@app.post("/api/v1/admin/teams", status_code=201)
async def create_admin_team(
    payload: TeamCreate,
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    if await session.scalar(select(Team).where(Team.tenant_id == principal.tenant_id, Team.name == payload.name.strip())):
        raise HTTPException(status_code=409, detail="team_exists")
    team = Team(tenant_id=principal.tenant_id, name=payload.name.strip(), description=payload.description.strip(), supervisor_email=payload.supervisor_email)
    session.add(team); await session.flush(); add_audit(session, principal, "team.created", "team", team.id, {"name": team.name}); await session.commit(); return {"id": team.id}


@app.patch("/api/v1/admin/teams/{team_id}")
async def update_admin_team(
    team_id: uuid.UUID, payload: TeamPatch,
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    team = await session.scalar(select(Team).where(Team.id == team_id, Team.tenant_id == principal.tenant_id))
    if not team: raise HTTPException(status_code=404, detail="team_not_found")
    for field, value in payload.model_dump(exclude_none=True).items(): setattr(team, field, value.strip() if isinstance(value, str) else value)
    add_audit(session, principal, "team.updated", "team", team.id, payload.model_dump(exclude_none=True)); await session.commit(); return {"status": "updated"}


@app.get("/api/v1/admin/scorecards")
async def list_scorecards(
    principal: Annotated[Principal, Depends(require_roles(Role.admin, Role.supervisor))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    rows = list((await session.scalars(
        select(ScorecardVersion).where(ScorecardVersion.tenant_id == principal.tenant_id).order_by(ScorecardVersion.version.desc())
    )).all())
    return {"items": [{"id": row.id, "version": row.version, "name": row.name, "criteria": row.criteria_json, "active": row.active} for row in rows]}


@app.post("/api/v1/admin/scorecards", status_code=201)
async def create_scorecard(
    payload: ScorecardCreate,
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    latest = await session.scalar(
        select(func.max(ScorecardVersion.version)).where(ScorecardVersion.tenant_id == principal.tenant_id)
    ) or 0
    previous = list((await session.scalars(
        select(ScorecardVersion).where(ScorecardVersion.tenant_id == principal.tenant_id, ScorecardVersion.active.is_(True))
    )).all())
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
    target = await session.scalar(select(ScorecardVersion).where(ScorecardVersion.id == scorecard_id, ScorecardVersion.tenant_id == principal.tenant_id))
    if not target: raise HTTPException(status_code=404, detail="scorecard_not_found")
    for row in (await session.scalars(select(ScorecardVersion).where(ScorecardVersion.tenant_id == principal.tenant_id))).all(): row.active = row.id == target.id
    add_audit(session, principal, "scorecard.activated", "scorecard", target.id); await session.commit(); return {"status": "activated"}


@app.get("/api/v1/admin/automations")
async def admin_automations(
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    rows = (await session.scalars(select(AutomationRule).where(AutomationRule.tenant_id == principal.tenant_id).order_by(AutomationRule.created_at.desc()))).all()
    return {"items": [{"id": row.id, "name": row.name, "event": row.event, "action": row.action, "mode": row.mode, "enabled": row.enabled} for row in rows]}


@app.post("/api/v1/admin/automations", status_code=201)
async def create_admin_automation(
    payload: AutomationCreate,
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    rule = AutomationRule(tenant_id=principal.tenant_id, name=payload.name.strip(), event=payload.event, action=payload.action, mode=payload.mode, conditions_json={}, enabled=True)
    session.add(rule); await session.flush(); add_audit(session, principal, "automation.created", "automation", rule.id, {"name": rule.name}); await session.commit(); return {"id": rule.id}


@app.patch("/api/v1/admin/automations/{rule_id}")
async def update_admin_automation(
    rule_id: uuid.UUID, payload: EnabledPatch,
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    rule = await session.scalar(select(AutomationRule).where(AutomationRule.id == rule_id, AutomationRule.tenant_id == principal.tenant_id))
    if not rule: raise HTTPException(status_code=404, detail="automation_not_found")
    rule.enabled = payload.enabled; add_audit(session, principal, "automation.toggled", "automation", rule.id, {"enabled": rule.enabled}); await session.commit(); return {"status": "updated"}


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
    add_audit(session, principal, "integration.created", "integration", result["id"], {"name": payload.name, "kind": payload.kind}); await session.commit(); return result


@app.patch("/api/v1/admin/integrations/{integration_id}")
async def update_admin_integration(
    integration_id: uuid.UUID, payload: IntegrationStatusPatch,
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    integration = await session.scalar(select(Integration).where(Integration.id == integration_id, Integration.tenant_id == principal.tenant_id))
    if not integration: raise HTTPException(status_code=404, detail="integration_not_found")
    integration.status = payload.status; add_audit(session, principal, "integration.toggled", "integration", integration.id, {"status": integration.status}); await session.commit(); return {"status": integration.status}


@app.get("/api/v1/admin/ai-settings")
async def admin_ai_settings(
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    row = await session.scalar(select(AiSetting).where(AiSetting.tenant_id == principal.tenant_id))
    return {"provider": row.provider if row else "openai", "transcription_model": row.transcription_model if row else settings.transcription_model,
            "analysis_model": row.analysis_model if row else settings.analysis_model, "min_confidence": row.min_confidence if row else 0.75}


@app.patch("/api/v1/admin/ai-settings")
async def update_admin_ai_settings(
    payload: AiSettingsPatch,
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    row = await session.scalar(select(AiSetting).where(AiSetting.tenant_id == principal.tenant_id))
    if not row: row = AiSetting(tenant_id=principal.tenant_id); session.add(row)
    row.provider = payload.provider; row.transcription_model = payload.transcription_model; row.analysis_model = payload.analysis_model; row.min_confidence = payload.min_confidence
    add_audit(session, principal, "ai_settings.updated", "ai_settings", principal.tenant_id, payload.model_dump()); await session.commit(); return {"status": "updated"}


@app.get("/api/v1/admin/security")
async def admin_security(
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    row = await session.scalar(select(SecuritySetting).where(SecuritySetting.tenant_id == principal.tenant_id))
    return {"require_consent": row.require_consent if row else True, "audio_download_enabled": row.audio_download_enabled if row else True}


@app.patch("/api/v1/admin/security")
async def update_admin_security(
    payload: SecuritySettingsPatch,
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    row = await session.scalar(select(SecuritySetting).where(SecuritySetting.tenant_id == principal.tenant_id))
    if not row: row = SecuritySetting(tenant_id=principal.tenant_id); session.add(row)
    row.require_consent = payload.require_consent; row.audio_download_enabled = payload.audio_download_enabled
    add_audit(session, principal, "security.updated", "security", principal.tenant_id, payload.model_dump()); await session.commit(); return {"status": "updated"}


@app.get("/api/v1/admin/audit-logs")
async def admin_audit_logs(
    principal: Annotated[Principal, Depends(require_roles(Role.admin))],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    rows = (await session.scalars(select(AuditLog).where(AuditLog.tenant_id == principal.tenant_id).order_by(AuditLog.created_at.desc()).limit(100))).all()
    return {"items": [{"id": row.id, "actor_email": row.actor_email, "action": row.action, "entity_type": row.entity_type, "entity_id": row.entity_id, "created_at": row.created_at} for row in rows]}
