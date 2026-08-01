from datetime import UTC, datetime

import pytest

from app.schemas import CoachingItem, Evidence, RoleAssessment
from app.services.evidence import check_evidence, validate_analysis_evidence
from app.services.pipeline import (
    ERRORS,
    InvalidTransition,
    RetryPolicy,
    classify_exception,
    ensure_transition,
    idempotency_fingerprint,
)
from app.services.roles import assign_speaker_roles


def test_state_transitions_and_retry_policy():
    ensure_transition("queued", "preprocessing")
    ensure_transition("retry_scheduled", "transcribing")
    with pytest.raises(InvalidTransition):
        ensure_transition("queued", "completed")
    policy = RetryPolicy((30, 120), jitter_ratio=0.1, random_value=lambda: 0.5)
    decision = policy.decide(
        ERRORS["transcription_timeout"], 0, now=datetime(2026, 8, 1, tzinfo=UTC)
    )
    assert decision.retry is True
    assert decision.delay_seconds == 30
    assert policy.decide(ERRORS["audio_corrupt"], 0).retry is False
    assert policy.decide(ERRORS["transcription_timeout"], 2).retry is False
    assert (
        classify_exception(RuntimeError("empty_transcript"), "transcribing")
        == ERRORS["empty_transcript"]
    )
    assert idempotency_fingerprint("CALL-1", " FollowUp ") == idempotency_fingerprint(
        "call-1", "followup"
    )


def test_role_assignment_is_canonical_agent_not_legacy_seller():
    segments = [
        {"speaker": "A", "text": "سلام در خدمتتون هستم، محصول ما شرایط پرداخت خوبی دارد"},
        {"speaker": "B", "text": "قیمتش چنده و برای شرکت ما تخفیف دارید؟"},
    ]
    heuristic = assign_speaker_roles(segments)
    assert heuristic.roles == {"A": "agent", "B": "customer"}
    metadata = assign_speaker_roles(segments, known_agent_speaker="B")
    assert metadata.roles["B"] == "agent"
    model = assign_speaker_roles(
        segments,
        RoleAssessment(seller_speaker="A", customer_speaker="B", confidence=0.95, reason="model"),
    )
    assert model.roles["A"] == "agent"


def test_evidence_validator_removes_unsupported_customer_facts(analysis_factory):
    segments = [
        {
            "speaker": "speaker_1",
            "text": "اسم من علی است و برای خرید نرم افزار تماس گرفتم",
            "start": 0.0,
            "end": 5.0,
        }
    ]
    analysis = analysis_factory(
        customer={"name": "علی", "company": "شرکت خیالی"},
        field_evidence={
            "name": [
                {
                    "segment_index": 0,
                    "timestamp_seconds": 1,
                    "speaker": "speaker_1",
                    "quote": "اسم من علی است",
                }
            ],
            "company": [
                {
                    "segment_index": 0,
                    "timestamp_seconds": 1,
                    "speaker": "speaker_1",
                    "quote": "شرکت خیالی",
                }
            ],
        },
    )
    sanitized, checks = validate_analysis_evidence(analysis, segments)
    assert sanitized.customer.name == "علی"
    assert sanitized.customer.company is None
    assert any(check.supported for check in checks)
    assert any(not check.supported for check in checks)
    assert "unsupported_customer_field:company" in sanitized.limitations


def test_evidence_rejects_bad_segment_and_timestamp():
    segments = [{"speaker": "A", "text": "قیمت صد میلیون تومان", "start": 2.0, "end": 4.0}]
    missing = check_evidence(Evidence(segment_index=2, speaker="A", quote="قیمت"), segments)
    assert missing.reason == "segment_out_of_range"
    timestamp = check_evidence(
        Evidence(segment_index=0, timestamp_seconds=20, speaker="A", quote="قیمت صد میلیون تومان"),
        segments,
    )
    assert timestamp.supported is False
    assert timestamp.reason == "timestamp_mismatch"


def test_unsupported_coaching_and_scores_are_suppressed(analysis_factory):
    analysis = analysis_factory()
    analysis.improvements = [
        CoachingItem(
            priority="high",
            title="ادعای بدون شاهد",
            action="کاری انجام بده",
            evidence=[Evidence(segment_index=0, speaker="A", quote="عبارتی که وجود ندارد")],
        )
    ]
    sanitized, _ = validate_analysis_evidence(
        analysis, [{"speaker": "A", "text": "سلام مشتری", "start": 0, "end": 2}]
    )
    assert sanitized.improvements == []
    assert sanitized.score_items == []
    assert sanitized.overall_score == 0
    assert "unsupported_claim_removed:improvements" in sanitized.limitations
