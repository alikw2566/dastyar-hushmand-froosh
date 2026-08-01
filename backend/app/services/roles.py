"""Hybrid deterministic + model-assisted speaker role assignment."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ..schemas import RoleAssessment
from .persian import normalize_persian

SELLER_CUES = (
    "در خدمتتون هستم",
    "شرکت ما",
    "محصول ما",
    "برای شما ارسال می کنم",
    "شماره داخلی",
    "پیشنهاد می کنم",
    "شرایط پرداخت",
)
CUSTOMER_CUES = (
    "قیمتش چنده",
    "بودجه",
    "نیاز دارم",
    "برای شرکت ما",
    "با مدیرم هماهنگ",
    "خرید",
)


@dataclass(frozen=True, slots=True)
class RoleAssignment:
    roles: dict[str, str]
    confidence: float
    method: str
    reason: str


def assign_speaker_roles(
    segments: list[dict],
    assessment: RoleAssessment | None = None,
    *,
    known_agent_speaker: str | None = None,
    minimum_model_confidence: float = 0.70,
) -> RoleAssignment:
    speakers = list(dict.fromkeys(str(item.get("speaker", "unknown")) for item in segments))
    if not speakers:
        return RoleAssignment({}, 0.0, "none", "no speakers")
    if known_agent_speaker in speakers:
        roles = {
            speaker: ("agent" if speaker == known_agent_speaker else "customer")
            for speaker in speakers
        }
        return RoleAssignment(roles, 0.98, "telephony_metadata", "known agent channel/speaker")

    if assessment and assessment.confidence >= minimum_model_confidence:
        seller = assessment.seller_speaker
        customer = assessment.customer_speaker
        if seller in speakers and customer in speakers and seller != customer:
            roles = {speaker: "unknown" for speaker in speakers}
            roles[seller] = "agent"
            roles[customer] = "customer"
            return RoleAssignment(roles, assessment.confidence, "model", assessment.reason)

    scores: dict[str, float] = defaultdict(float)
    for index, item in enumerate(segments):
        speaker = str(item.get("speaker", "unknown"))
        content = normalize_persian(str(item.get("text", "")), keep_punctuation=False)
        scores[speaker] += sum(1.0 for cue in SELLER_CUES if cue in content)
        scores[speaker] -= sum(0.8 for cue in CUSTOMER_CUES if cue in content)
        if index == 0 and any(word in content for word in ("سلام", "وقت بخیر", "در خدمت")):
            scores[speaker] += 0.35
    ranked = sorted(speakers, key=lambda speaker: scores[speaker], reverse=True)
    if len(ranked) == 1:
        return RoleAssignment({ranked[0]: "unknown"}, 0.25, "linguistic", "single speaker")
    margin = scores[ranked[0]] - scores[ranked[1]]
    if margin < 0.5:
        return RoleAssignment(
            {speaker: "unknown" for speaker in speakers}, 0.35, "linguistic", "ambiguous cues"
        )
    roles = {speaker: ("agent" if speaker == ranked[0] else "customer") for speaker in speakers}
    return RoleAssignment(
        roles, min(0.85, 0.55 + margin * 0.08), "linguistic", "sales-language cues"
    )


def apply_roles(segments: list[dict], assignment: RoleAssignment) -> list[dict]:
    return [
        {
            **item,
            "role": assignment.roles.get(str(item.get("speaker")), "unknown"),
            "role_confidence": assignment.confidence,
            "role_method": assignment.method,
        }
        for item in segments
    ]
