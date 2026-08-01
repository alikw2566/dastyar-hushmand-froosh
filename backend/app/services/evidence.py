"""Ground model claims in exact transcript segments before persistence."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from ..schemas import Evidence, SalesAnalysis
from .persian import normalize_persian


@dataclass(frozen=True, slots=True)
class EvidenceCheck:
    evidence: Evidence
    supported: bool
    similarity: float
    reason: str


def check_evidence(
    evidence: Evidence, segments: list[dict], *, threshold: float = 0.72
) -> EvidenceCheck:
    if evidence.segment_index < 0 or evidence.segment_index >= len(segments):
        return EvidenceCheck(evidence, False, 0.0, "segment_out_of_range")
    segment = segments[evidence.segment_index]
    segment_text = normalize_persian(
        str(segment.get("text", "")), keep_punctuation=False
    ).casefold()
    quote = normalize_persian(evidence.quote, keep_punctuation=False).casefold()
    if not quote or not segment_text:
        return EvidenceCheck(evidence, False, 0.0, "empty_text")
    if quote in segment_text:
        similarity = 1.0
    else:
        quote_tokens = set(quote.split())
        segment_tokens = set(segment_text.split())
        token_coverage = len(quote_tokens & segment_tokens) / max(1, len(quote_tokens))
        sequence = SequenceMatcher(None, quote, segment_text).ratio()
        similarity = max(token_coverage, sequence)
    timestamp = evidence.timestamp_seconds
    start = segment.get("start")
    end = segment.get("end")
    timestamp_valid = (
        timestamp is None or start is None or end is None or start - 1 <= timestamp <= end + 1
    )
    supported = similarity >= threshold and timestamp_valid
    return EvidenceCheck(
        evidence,
        supported,
        round(similarity, 4),
        "supported"
        if supported
        else ("timestamp_mismatch" if not timestamp_valid else "quote_mismatch"),
    )


def _filter(
    values: list[Evidence], segments: list[dict]
) -> tuple[list[Evidence], list[EvidenceCheck]]:
    checks = [check_evidence(value, segments) for value in values]
    return [check.evidence for check in checks if check.supported], checks


def validate_analysis_evidence(
    analysis: SalesAnalysis, segments: list[dict]
) -> tuple[SalesAnalysis, list[EvidenceCheck]]:
    """Return a sanitized copy; unsupported facts become null, never authoritative."""

    sanitized = analysis.model_copy(deep=True)
    checks: list[EvidenceCheck] = []
    for collection_name in (
        "score_items",
        "strengths",
        "improvements",
        "objections",
        "missed_opportunities",
    ):
        retained = []
        for item in getattr(sanitized, collection_name):
            supported, item_checks = _filter(item.evidence, segments)
            item.evidence = supported
            checks.extend(item_checks)
            if supported:
                retained.append(item)
            else:
                sanitized.limitations.append(f"unsupported_claim_removed:{collection_name}")
        setattr(sanitized, collection_name, retained)
    sanitized.overall_score = round(sum(item.weighted_score for item in sanitized.score_items), 2)
    sanitized.key_moments, key_checks = _filter(sanitized.key_moments, segments)
    checks.extend(key_checks)

    fact_names = (
        "name",
        "company",
        "need",
        "budget",
        "product",
        "phone",
        "alternate_phone",
        "address",
        "customer_type",
        "city",
        "province",
        "product_category",
        "quantity",
        "unit",
        "amount",
        "exact_amount",
        "budget_min",
        "budget_max",
        "requested_discount",
        "currency",
        "followup_at",
        "sales_stage",
        "lead_temperature",
        "sentiment",
        "competitor_name",
        "purchase_timeline",
        "lost_reason",
        "purchase_probability",
    )
    for field_name in fact_names:
        value = getattr(sanitized.customer, field_name)
        if value is None:
            continue
        evidence_values = sanitized.field_evidence.get(field_name, [])
        supported, fact_checks = _filter(evidence_values, segments)
        checks.extend(fact_checks)
        sanitized.field_evidence[field_name] = supported
        if not supported:
            setattr(sanitized.customer, field_name, None)
            sanitized.limitations.append(f"unsupported_customer_field:{field_name}")
    for list_field in ("commitments", "buying_signals", "pain_points"):
        values = getattr(sanitized.customer, list_field)
        if not values:
            continue
        supported, list_checks = _filter(sanitized.field_evidence.get(list_field, []), segments)
        checks.extend(list_checks)
        sanitized.field_evidence[list_field] = supported
        if not supported:
            setattr(sanitized.customer, list_field, [])
            sanitized.limitations.append(f"unsupported_customer_field:{list_field}")
    if sanitized.outcome != "unknown":
        outcome_evidence, outcome_checks = _filter(
            sanitized.field_evidence.get("outcome", []), segments
        )
        checks.extend(outcome_checks)
        sanitized.field_evidence["outcome"] = outcome_evidence
        if not outcome_evidence:
            sanitized.outcome = "unknown"
            sanitized.outcome_confidence = min(sanitized.outcome_confidence, 0.49)
            sanitized.limitations.append("unsupported_outcome_reset")
    if sanitized.next_action is not None:
        next_evidence, next_checks = _filter(
            sanitized.field_evidence.get("next_action", []), segments
        )
        checks.extend(next_checks)
        sanitized.field_evidence["next_action"] = next_evidence
        if not next_evidence:
            sanitized.next_action = None
            sanitized.limitations.append("unsupported_next_action_removed")
    if any(not item.supported for item in checks):
        sanitized.limitations.append("unsupported_evidence_removed")
    if any(value.startswith("unsupported_") for value in sanitized.limitations):
        sanitized.outcome_confidence = min(sanitized.outcome_confidence, 0.49)
    sanitized.limitations = list(dict.fromkeys(sanitized.limitations))
    return sanitized, checks
