from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class Evidence(BaseModel):
    segment_index: int
    timestamp_seconds: float | None = None
    end_time_seconds: float | None = None
    speaker: str
    quote: str = Field(max_length=220)


class RoleAssessment(BaseModel):
    seller_speaker: str | None
    customer_speaker: str | None
    confidence: float = Field(ge=0, le=1)
    reason: str


class ScoreItem(BaseModel):
    key: str
    label: str
    weight: float = Field(gt=0, le=100)
    raw_score: float = Field(ge=0, le=100)
    weighted_score: float = Field(ge=0, le=100)
    explanation: str
    evidence: list[Evidence] = Field(default_factory=list)


class Metric(BaseModel):
    key: str
    label: str
    value: str | float | int | None
    source: Literal["measured", "inferred", "confirmed", "unavailable"]
    note: str


class CustomerFacts(BaseModel):
    name: str | None = None
    company: str | None = None
    need: str | None = None
    budget: str | None = None
    product: str | None = None
    phone: str | None = None
    alternate_phone: str | None = None
    address: str | None = None
    customer_type: str | None = None
    city: str | None = None
    province: str | None = None
    product_category: str | None = None
    amount: float | None = None
    exact_amount: float | None = None
    budget_min: float | None = None
    budget_max: float | None = None
    requested_discount: float | None = None
    quantity: float | None = None
    unit: str | None = None
    currency: str | None = None
    followup_at: datetime | None = None
    sales_stage: str | None = None
    lead_temperature: Literal["hot", "warm", "cold", "unknown"] | None = None
    sentiment: Literal["positive", "neutral", "negative", "mixed", "unknown"] | None = None
    risk_flag: bool = False
    competitor_name: str | None = None
    purchase_timeline: str | None = None
    lost_reason: str | None = None
    purchase_probability: float | None = Field(default=None, ge=0, le=1)
    pain_points: list[str] = Field(default_factory=list)
    commitments: list[str] = Field(default_factory=list)
    buying_signals: list[str] = Field(default_factory=list)


class Objection(BaseModel):
    title: str
    response_quality: Literal["good", "partial", "poor", "unanswered"]
    better_response: str
    evidence: list[Evidence]


class CoachingItem(BaseModel):
    priority: Literal["high", "medium", "low"]
    title: str
    action: str
    suggested_phrase: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)


class NextAction(BaseModel):
    title: str
    rationale: str
    due_hint: str | None = None
    priority: Literal["critical", "high", "normal", "low"]


class FollowUpDraft(BaseModel):
    channel: Literal["sms", "whatsapp", "email"]
    subject: str | None = None
    content: str


class SalesAnalysis(BaseModel):
    schema_version: Literal["sales-analysis-v1"] = "sales-analysis-v1"
    language: str = "fa"
    role_assessment: RoleAssessment
    executive_summary: str
    funnel_stage: str
    outcome: Literal["won", "lost", "follow_up", "unknown"]
    outcome_confidence: float = Field(ge=0, le=1)
    customer: CustomerFacts
    score_items: list[ScoreItem]
    overall_score: float = Field(ge=0, le=100)
    metrics: list[Metric]
    strengths: list[CoachingItem]
    improvements: list[CoachingItem]
    objections: list[Objection]
    missed_opportunities: list[CoachingItem]
    key_moments: list[Evidence]
    next_action: NextAction | None = None
    follow_up_drafts: list[FollowUpDraft] = Field(default_factory=list)
    field_evidence: dict[str, list[Evidence]] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_weighted_score(self):
        weighted_total = round(sum(item.weighted_score for item in self.score_items), 2)
        if abs(weighted_total - self.overall_score) > 0.5:
            raise ValueError("overall_score must equal the weighted score total")
        return self


class CallRead(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    customer_name: str
    seller_email: str | None
    seller_name: str
    original_file_name: str
    source: str
    status: str
    outcome: str
    outcome_confirmed: bool
    duration_seconds: float | None
    score: float | None
    created_at: datetime
    updated_at: datetime
    call_started_at: datetime | None = None
    direction: str | None = None
    caller_number: str | None = None
    destination_number: str | None = None
    retry_count: int = 0
    next_retry_at: datetime | None = None
    error_code: str | None = None
    manually_corrected: bool = False
    company: str | None = None
    phone: str | None = None
    city: str | None = None
    province: str | None = None
    product: str | None = None
    product_category: str | None = None
    sales_stage: str | None = None
    lead_temperature: str | None = None
    sentiment: str | None = None
    risk_flag: bool = False
    followup_required: bool = False
    followup_due_at: datetime | None = None
    review_status: str | None = None
    latest_analysis_version_id: UUID | None = None
    reviewed_analysis_version_id: UUID | None = None
    published_analysis_version_id: UUID | None = None


class PaginatedCalls(BaseModel):
    items: list[CallRead]
    page: int = 1
    page_size: int = 50
    total: int = 0
    pages: int = 0
    next_cursor: str | None = None


class ScoreCriterion(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9_]+$")
    label: str = Field(min_length=2, max_length=120)
    weight: float = Field(gt=0, le=100)


class ScorecardCreate(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    criteria: list[ScoreCriterion] = Field(min_length=1)

    @model_validator(mode="after")
    def weights_equal_one_hundred(self):
        if abs(sum(item.weight for item in self.criteria) - 100) > 0.01:
            raise ValueError("scorecard weights must total 100")
        return self


class OrganizationSettingsPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=180)
    retention_days: int | None = Field(default=None, ge=1, le=3650)
    automation_mode: Literal["draft", "approval", "automatic"] | None = None


class TaskCreate(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    customer_name: str = Field(default="", max_length=180)
    priority: Literal["low", "normal", "high", "critical"] = "normal"
    due_at: datetime | None = None


class TaskPatch(BaseModel):
    status: Literal["open", "needs_scheduling", "in_progress", "done", "cancelled"]


class MemberCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    email: str = Field(pattern=r"^\S+@\S+\.\S+$", max_length=320)
    role: Literal["admin", "manager", "supervisor", "agent", "seller", "viewer"] = "agent"
    team_id: UUID | None = None
    password: str = Field(min_length=10, max_length=200)


class MemberPatch(BaseModel):
    role: Literal["admin", "manager", "supervisor", "agent", "seller", "viewer"]
    team_id: UUID | None = None
    active: bool = True


class TeamCreate(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    description: str = Field(default="", max_length=1000)
    supervisor_email: str | None = Field(default=None, max_length=320)


class TeamPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=1000)
    supervisor_email: str | None = Field(default=None, max_length=320)
    active: bool | None = None


class AutomationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    event: Literal["call.completed", "call.failed", "score.low", "followup.overdue"]
    action: Literal["task.create", "message.create", "manager.notify"]
    mode: Literal["draft", "approval", "automatic"] = "approval"


class EnabledPatch(BaseModel):
    enabled: bool


class AiSettingsPatch(BaseModel):
    provider: Literal["openai", "avalai"]
    transcription_model: str = Field(min_length=2, max_length=120)
    analysis_model: str = Field(min_length=2, max_length=120)
    min_confidence: float = Field(ge=0.5, le=0.99)


class SecuritySettingsPatch(BaseModel):
    require_consent: bool
    audio_download_enabled: bool


class SegmentCorrection(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    speaker_role: Literal["agent", "seller", "customer", "unknown", "other"]
    reanalyze: bool = True


class SpeakerRoleItem(BaseModel):
    speaker_id: str = Field(min_length=1, max_length=80)
    role: Literal["agent", "seller", "customer", "unknown", "other"]


class SpeakerRolesPatch(BaseModel):
    assignments: list[SpeakerRoleItem] = Field(min_length=1, max_length=20)
    reanalyze: bool = True


class ReprocessRequest(BaseModel):
    mode: Literal["resume", "reanalyze", "full"] = "resume"
    reason: str | None = Field(default=None, max_length=500)


class ProcessingAction(BaseModel):
    action: Literal["retry", "reanalyze", "full_reprocess", "quarantine", "resolve_error"]
    reason: str | None = Field(default=None, max_length=500)


class ReviewActionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=4000)


class ReviewAssignRequest(BaseModel):
    assignee_email: str | None = Field(default=None, max_length=320)
    note: str | None = Field(default=None, max_length=4000)


class TranscriptVersionCreate(BaseModel):
    reason: str = Field(min_length=2, max_length=1000)


class AnalysisVersionCreate(BaseModel):
    reason: str = Field(min_length=2, max_length=1000)


class GlossaryCreate(BaseModel):
    term: str = Field(min_length=1, max_length=240)
    category: Literal[
        "general", "product", "brand", "company", "person", "medical", "sales", "city", "employee"
    ] = "general"
    aliases: list[str] = Field(default_factory=list, max_length=50)
    active: bool = True


class GlossaryPatch(BaseModel):
    term: str | None = Field(default=None, min_length=1, max_length=240)
    category: (
        Literal[
            "general",
            "product",
            "brand",
            "company",
            "person",
            "medical",
            "sales",
            "city",
            "employee",
        ]
        | None
    ) = None
    aliases: list[str] | None = Field(default=None, max_length=50)
    active: bool | None = None
