from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base, Call, CallStatus, Organization, SourceImport, Task
from app.services.watcher import DatabaseWatcherRepository
from app.tasks import _create_followups


@pytest.mark.asyncio
async def test_followup_database_rule_is_idempotent_and_marks_missing_schedule(analysis_factory):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(Organization(id=tenant_id, name="Tenant"))
        call = Call(
            tenant_id=tenant_id,
            original_file_name="call.wav",
            object_key=f"{tenant_id}/call.wav",
            mime_type="audio/wav",
            size_bytes=100,
            customer_name="مشتری",
            status=CallStatus.queued,
        )
        session.add(call)
        await session.flush()
        analysis = analysis_factory(
            outcome="follow_up",
            next_action={
                "title": "تماس مجدد",
                "rationale": "درخواست مشتری",
                "priority": "high",
                "due_hint": None,
            },
        )
        await _create_followups(session, call, analysis)
        await _create_followups(session, call, analysis)
        await session.commit()
        count = await session.scalar(select(func.count(Task.id)))
        task = await session.scalar(select(Task))
        assert count == 1
        assert task.status == "needs_scheduling"
        assert task.dedupe_key
    await engine.dispose()


@pytest.mark.asyncio
async def test_watcher_file_stability_survives_repository_restart(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id = uuid.uuid4()

    async def sessions(_tenant_id):
        async with session_factory() as session:
            yield session

    recording = tmp_path / "recording.wav"
    recording.write_bytes(b"still-being-observed")
    first_seen = datetime(2026, 8, 1, 10, tzinfo=UTC)
    repository_before_restart = DatabaseWatcherRepository(
        tenant_id, watcher_id="test-watcher", session_provider=sessions
    )
    first = await repository_before_restart.observe(str(recording), recording, first_seen, 15)
    assert first.stable is False

    repository_after_restart = DatabaseWatcherRepository(
        tenant_id, watcher_id="test-watcher", session_provider=sessions
    )
    second = await repository_after_restart.observe(
        str(recording), recording, first_seen + timedelta(seconds=16), 15
    )
    assert second.stable is True
    assert second.detected_at == first_seen
    async with session_factory() as session:
        source = await session.scalar(select(SourceImport))
        assert source.status == "discovered"
        assert source.detected_at.replace(tzinfo=UTC) == first_seen
    await engine.dispose()
