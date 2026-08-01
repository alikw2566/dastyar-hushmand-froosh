"""Deterministic follow-up creation rules with stable deduplication keys."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from ..schemas import SalesAnalysis
from .persian import parse_relative_due
from .pipeline import idempotency_fingerprint


@dataclass(frozen=True, slots=True)
class FollowUpSpec:
    dedupe_key: str
    title: str
    priority: str
    due_at: datetime | None
    task_type: str = "sales_followup"


def build_followup_spec(
    call_id: str,
    analysis: SalesAnalysis,
    *,
    now: datetime | None = None,
) -> FollowUpSpec | None:
    commitments = " ".join(analysis.customer.commitments)
    open_opportunity = analysis.outcome not in {
        "won",
        "lost",
    } and analysis.funnel_stage.casefold() not in {
        "closed",
        "closed_won",
        "closed_lost",
    }
    explicit_followup = bool(
        analysis.customer.followup_at
        or analysis.next_action
        or analysis.outcome == "follow_up"
        or analysis.customer.commitments
        or "پیش فاکتور" in commitments.replace("‌", " ")
        or "تماس" in commitments
        or open_opportunity
    )
    if not explicit_followup:
        return None
    action = analysis.next_action
    title = action.title.strip() if action else "پیگیری تماس فروش"
    priority = action.priority if action else "normal"
    due_at = None
    if analysis.customer.followup_at:
        due_at = analysis.customer.followup_at
    elif action and action.due_hint:
        due_at = parse_relative_due(action.due_hint, now=now or datetime.now(UTC))
    dedupe_key = idempotency_fingerprint(call_id, "sales_followup")[:40]
    return FollowUpSpec(dedupe_key, title, priority, due_at)
