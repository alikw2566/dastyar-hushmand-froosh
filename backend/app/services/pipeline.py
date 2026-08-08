"""Observable call-processing state machine and retry/error policy."""

from __future__ import annotations

import enum
import hashlib
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import openai
from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy.exc import DBAPIError, OperationalError


class PipelineState(str, enum.Enum):
    discovered = "discovered"
    waiting_for_file = "waiting_for_file"
    uploaded = "uploaded"
    queued = "queued"
    preprocessing = "preprocessing"
    diarizing = "diarizing"
    transcribing = "transcribing"
    assigning_roles = "assigning_roles"
    analyzing = "analyzing"
    validating = "validating"
    creating_followups = "creating_followups"
    review_needed = "review_needed"
    completed = "completed"
    retry_scheduled = "retry_scheduled"
    failed = "failed"
    quarantined = "quarantined"


_FORWARD: dict[PipelineState, frozenset[PipelineState]] = {
    PipelineState.discovered: frozenset(
        {PipelineState.waiting_for_file, PipelineState.queued, PipelineState.quarantined}
    ),
    PipelineState.waiting_for_file: frozenset(
        {PipelineState.queued, PipelineState.quarantined, PipelineState.failed}
    ),
    PipelineState.uploaded: frozenset({PipelineState.queued, PipelineState.quarantined}),
    PipelineState.queued: frozenset(
        {PipelineState.preprocessing, PipelineState.analyzing, PipelineState.failed}
    ),
    PipelineState.preprocessing: frozenset(
        {
            PipelineState.diarizing,
            PipelineState.transcribing,
            PipelineState.retry_scheduled,
            PipelineState.failed,
            PipelineState.quarantined,
        }
    ),
    PipelineState.diarizing: frozenset(
        {PipelineState.transcribing, PipelineState.retry_scheduled, PipelineState.failed}
    ),
    PipelineState.transcribing: frozenset(
        {PipelineState.assigning_roles, PipelineState.retry_scheduled, PipelineState.failed}
    ),
    PipelineState.assigning_roles: frozenset(
        {PipelineState.analyzing, PipelineState.retry_scheduled, PipelineState.failed}
    ),
    PipelineState.analyzing: frozenset(
        {PipelineState.validating, PipelineState.retry_scheduled, PipelineState.failed}
    ),
    PipelineState.validating: frozenset(
        {PipelineState.creating_followups, PipelineState.review_needed, PipelineState.failed}
    ),
    PipelineState.creating_followups: frozenset(
        {PipelineState.completed, PipelineState.review_needed, PipelineState.failed}
    ),
    PipelineState.retry_scheduled: frozenset(
        {
            PipelineState.queued,
            PipelineState.preprocessing,
            PipelineState.transcribing,
            PipelineState.analyzing,
            PipelineState.failed,
        }
    ),
    PipelineState.review_needed: frozenset(
        {PipelineState.queued, PipelineState.analyzing, PipelineState.completed}
    ),
    PipelineState.completed: frozenset({PipelineState.queued, PipelineState.analyzing}),
    PipelineState.failed: frozenset(
        {PipelineState.queued, PipelineState.analyzing, PipelineState.quarantined}
    ),
    PipelineState.quarantined: frozenset({PipelineState.queued}),
}


class InvalidTransition(ValueError):
    pass


def ensure_transition(current: str | PipelineState, target: str | PipelineState) -> None:
    current_state = PipelineState(current)
    target_state = PipelineState(target)
    if target_state not in _FORWARD.get(current_state, frozenset()):
        raise InvalidTransition(
            f"invalid pipeline transition: {current_state.value} -> {target_state.value}"
        )


class ErrorCategory(str, enum.Enum):
    input = "input"
    storage = "storage"
    database = "database"
    queue = "queue"
    transcription = "transcription"
    analysis = "analysis"
    validation = "validation"
    configuration = "configuration"
    internal = "internal"


@dataclass(frozen=True, slots=True)
class ErrorDescriptor:
    code: str
    category: ErrorCategory
    transient: bool
    safe_message: str


class PipelineFailure(RuntimeError):
    def __init__(self, descriptor: ErrorDescriptor, *, context: dict | None = None):
        super().__init__(descriptor.safe_message)
        self.descriptor = descriptor
        self.context = context or {}


ERRORS = {
    "audio_corrupt": ErrorDescriptor(
        "audio_corrupt", ErrorCategory.input, False, "audio file is corrupt"
    ),
    "audio_too_short": ErrorDescriptor(
        "audio_too_short", ErrorCategory.input, False, "audio is too short"
    ),
    "unsupported_audio": ErrorDescriptor(
        "unsupported_audio", ErrorCategory.input, False, "audio format is unsupported"
    ),
    "storage_unavailable": ErrorDescriptor(
        "storage_unavailable", ErrorCategory.storage, True, "object storage is unavailable"
    ),
    "transcription_timeout": ErrorDescriptor(
        "transcription_timeout", ErrorCategory.transcription, True, "transcription timed out"
    ),
    "transcription_unavailable": ErrorDescriptor(
        "transcription_unavailable",
        ErrorCategory.transcription,
        True,
        "transcription provider is unavailable",
    ),
    "empty_transcript": ErrorDescriptor(
        "empty_transcript", ErrorCategory.transcription, False, "transcription returned no speech"
    ),
    "analysis_invalid": ErrorDescriptor(
        "analysis_invalid", ErrorCategory.analysis, True, "analysis response is invalid"
    ),
    "analysis_unavailable": ErrorDescriptor(
        "analysis_unavailable", ErrorCategory.analysis, True, "analysis provider is unavailable"
    ),
    "unsupported_evidence": ErrorDescriptor(
        "unsupported_evidence",
        ErrorCategory.validation,
        False,
        "analysis lacks transcript evidence",
    ),
    "configuration_invalid": ErrorDescriptor(
        "configuration_invalid",
        ErrorCategory.configuration,
        False,
        "service configuration is invalid",
    ),
    "internal_error": ErrorDescriptor(
        "internal_error", ErrorCategory.internal, False, "unexpected processing failure"
    ),
}


def classify_exception(exc: Exception, stage: str) -> ErrorDescriptor:
    if isinstance(exc, PipelineFailure):
        return exc.descriptor
    if str(exc) == "empty_transcript":
        return ERRORS["empty_transcript"]
    if isinstance(exc, openai.APITimeoutError):
        return ERRORS[
            "transcription_timeout" if stage == "transcribing" else "analysis_unavailable"
        ]
    if isinstance(
        exc,
        (
            openai.APIConnectionError,
            openai.RateLimitError,
            openai.InternalServerError,
        ),
    ):
        return ERRORS[
            "transcription_unavailable" if stage == "transcribing" else "analysis_unavailable"
        ]
    if isinstance(exc, (BotoCoreError, ClientError)):
        return ERRORS["storage_unavailable"]
    if isinstance(exc, (OperationalError, DBAPIError)):
        return ErrorDescriptor(
            "database_unavailable",
            ErrorCategory.database,
            True,
            "database is temporarily unavailable",
        )
    if isinstance(exc, (TimeoutError, ConnectionError)):
        code = (
            "transcription_timeout"
            if stage == "transcribing" and isinstance(exc, TimeoutError)
            else f"{stage}_unavailable"
        )
        if code in ERRORS:
            return ERRORS[code]
        return ErrorDescriptor(
            code, ErrorCategory.internal, True, f"{stage} temporarily unavailable"
        )
    if isinstance(exc, (ValueError, TypeError)) and stage == "validating":
        return ERRORS["unsupported_evidence"]
    return ERRORS["internal_error"]


@dataclass(frozen=True, slots=True)
class RetryDecision:
    retry: bool
    delay_seconds: int | None
    scheduled_at: datetime | None


class RetryPolicy:
    def __init__(
        self,
        schedule_seconds: tuple[int, ...] = (30, 120, 600, 1800, 7200),
        *,
        jitter_ratio: float = 0.1,
        random_value: Callable[[], float] = random.random,
    ):
        if not schedule_seconds or any(value <= 0 for value in schedule_seconds):
            raise ValueError("retry schedule must contain positive seconds")
        if not 0 <= jitter_ratio <= 1:
            raise ValueError("jitter_ratio must be between 0 and 1")
        self.schedule_seconds = schedule_seconds
        self.jitter_ratio = jitter_ratio
        self.random_value = random_value

    def decide(
        self,
        descriptor: ErrorDescriptor,
        attempt: int,
        *,
        now: datetime | None = None,
    ) -> RetryDecision:
        if not descriptor.transient or attempt >= len(self.schedule_seconds):
            return RetryDecision(False, None, None)
        base = self.schedule_seconds[attempt]
        jitter = (self.random_value() * 2 - 1) * self.jitter_ratio
        delay = max(1, round(base * (1 + jitter)))
        now = now or datetime.now(UTC)
        return RetryDecision(True, delay, now + timedelta(seconds=delay))


def idempotency_fingerprint(*parts: str) -> str:
    canonical = "\x1f".join(part.strip().lower() for part in parts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
