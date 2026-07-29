import asyncio
import tempfile
from pathlib import Path
from uuid import UUID

from celery import Celery
from sqlalchemy import delete, select

from .config import get_settings
from .database import tenant_session
from .models import Call, CallOutcome, CallStatus, MessageDraft, Task, TranscriptSegment
from .services.ai import ai_provider
from .services.metrics import calculate_metrics
from .services.storage import storage


settings = get_settings()
celery_app = Celery("mokalemeban", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(task_track_started=True, task_acks_late=True, worker_prefetch_multiplier=1)


@celery_app.task(bind=True, autoretry_for=(ConnectionError, TimeoutError), retry_backoff=True, retry_kwargs={"max_retries": 3})
def process_call(self, call_id: str, tenant_id: str):
    return asyncio.run(_process_call(UUID(call_id), UUID(tenant_id)))


async def _process_call(call_id: UUID, tenant_id: UUID):
    async for session in tenant_session(str(tenant_id)):
        call = await session.scalar(select(Call).where(Call.id == call_id, Call.tenant_id == tenant_id))
        if not call:
            return {"status": "missing"}
        if call.status == CallStatus.completed:
            return {"status": "already_completed"}
        try:
            call.status = CallStatus.transcribing
            call.error_message = None
            await session.commit()

            with tempfile.TemporaryDirectory(prefix="mokalemeban-") as temp_dir:
                audio_path = Path(temp_dir) / call.original_file_name
                await storage.download(call.object_key, audio_path)
                segments = await asyncio.to_thread(ai_provider.transcribe, audio_path)
                if not segments:
                    raise RuntimeError("transcription_returned_no_segments")
                measured = calculate_metrics(segments)

                call.status = CallStatus.analyzing
                await session.commit()
                analysis = await asyncio.to_thread(ai_provider.analyze, segments, measured)

            await session.execute(delete(TranscriptSegment).where(TranscriptSegment.call_id == call.id))
            session.add_all([
                TranscriptSegment(
                    tenant_id=tenant_id, call_id=call.id, position=item["position"],
                    speaker_label=item["speaker"], start_seconds=item["start"],
                    end_seconds=item["end"], content=item["text"],
                ) for item in segments
            ])
            call.status = CallStatus.review_needed if analysis.outcome_confidence < 0.75 else CallStatus.completed
            call.outcome = CallOutcome(analysis.outcome)
            call.customer_name = analysis.customer.name or call.customer_name
            call.score = analysis.overall_score
            call.analysis_version = settings.analysis_prompt_version
            call.analysis_json = analysis.model_dump(mode="json")
            call.duration_seconds = measured.get("call_span_seconds")

            if analysis.next_action:
                session.add(Task(
                    tenant_id=tenant_id, call_id=call.id, customer_name=call.customer_name,
                    title=analysis.next_action.title, priority=analysis.next_action.priority,
                    ai_suggested=True,
                ))
            for draft in analysis.follow_up_drafts:
                session.add(MessageDraft(
                    tenant_id=tenant_id, call_id=call.id, channel=draft.channel,
                    subject=draft.subject, content=draft.content, status="pending_approval",
                ))
            await session.commit()
            return {"status": call.status.value, "score": call.score}
        except Exception as exc:
            await session.rollback()
            call.status = CallStatus.failed
            call.error_message = str(exc)[:2000]
            await session.commit()
            raise
