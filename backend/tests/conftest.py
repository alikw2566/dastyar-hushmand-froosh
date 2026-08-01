from __future__ import annotations

from collections.abc import Callable

import pytest

from app.schemas import SalesAnalysis


@pytest.fixture
def analysis_factory() -> Callable[..., SalesAnalysis]:
    def factory(
        *,
        outcome: str = "unknown",
        funnel_stage: str = "discovery",
        customer: dict | None = None,
        field_evidence: dict | None = None,
        next_action: dict | None = None,
        confidence: float = 0.9,
    ) -> SalesAnalysis:
        return SalesAnalysis.model_validate(
            {
                "role_assessment": {
                    "seller_speaker": "speaker_0",
                    "customer_speaker": "speaker_1",
                    "confidence": 0.91,
                    "reason": "deterministic test",
                },
                "executive_summary": "خلاصه آزمون",
                "funnel_stage": funnel_stage,
                "outcome": outcome,
                "outcome_confidence": confidence,
                "customer": customer or {},
                "score_items": [
                    {
                        "key": "communication",
                        "label": "ارتباط",
                        "weight": 100,
                        "raw_score": 80,
                        "weighted_score": 80,
                        "explanation": "آزمون",
                        "evidence": [],
                    }
                ],
                "overall_score": 80,
                "metrics": [],
                "strengths": [],
                "improvements": [],
                "objections": [],
                "missed_opportunities": [],
                "key_moments": [],
                "next_action": next_action,
                "follow_up_drafts": [],
                "field_evidence": field_evidence or {},
                "limitations": [],
            }
        )

    return factory
