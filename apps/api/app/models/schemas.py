from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SessionMode(StrEnum):
    LIVE = "LIVE_MICROPHONE"
    UPLOAD = "AUDIO_UPLOAD"
    SAMPLE = "SAMPLE_SCENARIO"


class SessionStatus(StrEnum):
    CREATED = "CREATED"
    RECORDING = "RECORDING"
    PAUSED = "PAUSED"
    PROCESSING = "PROCESSING"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"


class EventCategory(StrEnum):
    OBSERVATION = "OBSERVATION"
    MEASUREMENT = "MEASUREMENT"
    PROCEDURE = "PROCEDURE"
    MEDICATION = "MEDICATION"
    FLUID_OR_BLOOD_PRODUCT = "FLUID_OR_BLOOD_PRODUCT"
    IMAGING_OR_TEST = "IMAGING_OR_TEST"
    CONSULT_OR_COMMUNICATION = "CONSULT_OR_COMMUNICATION"
    EQUIPMENT = "EQUIPMENT"
    OTHER = "OTHER"


class EventState(StrEnum):
    PROPOSED = "PROPOSED"
    REQUESTED = "REQUESTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NEGATED = "NEGATED"
    UNCERTAIN = "UNCERTAIN"
    REPORTED = "REPORTED"


class ReviewStatus(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    ACCEPTED = "ACCEPTED"
    EDITED = "EDITED"
    REJECTED = "REJECTED"


class SegmentReviewStatus(StrEnum):
    RAW = "RAW"
    CORRECTED = "CORRECTED"
    VERIFIED = "VERIFIED"


class ReviewItemStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class SessionCreate(BaseModel):
    case_label: str = Field(min_length=1, max_length=120)
    mode: SessionMode
    consent_recorded: bool = False

    @field_validator("case_label")
    @classmethod
    def clean_case_label(cls, value: str) -> str:
        clean = " ".join(value.split())
        if not clean:
            raise ValueError("A case name is required")
        return clean


class SessionRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_label: str
    mode: SessionMode
    status: SessionStatus
    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    simulation_flag: bool = True
    consent_recorded: bool
    model_versions: dict[str, str]
    duration_ms: int = 0
    revision: int = 0


class TranscriptSegmentCreate(BaseModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    raw_text: str = Field(min_length=1)
    speaker_label: str = "Unknown"
    asr_engine: str = "manual"
    confidence: float = Field(default=1.0, ge=0, le=1)

    @field_validator("end_ms")
    @classmethod
    def valid_duration(cls, value: int, info: Any) -> int:
        start = info.data.get("start_ms", 0)
        if value <= start:
            raise ValueError("end_ms must be greater than start_ms")
        return value


class TranscriptSegment(BaseModel):
    id: str
    session_id: str
    start_ms: int
    end_ms: int
    raw_text: str
    corrected_text: str | None = None
    speaker_label: str
    asr_engine: str
    confidence: float
    review_status: SegmentReviewStatus
    created_at: datetime

    @property
    def display_text(self) -> str:
        return self.corrected_text or self.raw_text


class TranscriptPatch(BaseModel):
    corrected_text: str | None = Field(default=None, max_length=4000)
    speaker_label: str | None = Field(default=None, max_length=80)
    review_status: SegmentReviewStatus | None = None
    change_reason: str = Field(default="Reviewer correction", max_length=240)


class EventEntity(BaseModel):
    entity_type: str
    normalized_name: str | None = None
    verbatim_value: str
    numeric_value: float | None = None
    unit: str | None = None
    source_span: tuple[int, int]


class ClinicalEventCreate(BaseModel):
    category: EventCategory
    normalized_action: str
    state: EventState
    utterance_time_ms: int = Field(ge=0)
    asserted_action_time_ms: int | None = Field(default=None, ge=0)
    description: str = Field(min_length=1, max_length=500)
    source_segment_ids: list[str] = Field(min_length=1)
    evidence_text: str = Field(min_length=1)
    confidence: float = Field(default=1.0, ge=0, le=1)
    requires_review: bool = True
    entities: list[EventEntity] = Field(default_factory=list)


class ClinicalEvent(ClinicalEventCreate):
    id: str
    session_id: str
    reviewer_status: ReviewStatus
    origin: str
    created_at: datetime
    updated_at: datetime


class EventPatch(BaseModel):
    category: EventCategory | None = None
    normalized_action: str | None = Field(default=None, max_length=160)
    state: EventState | None = None
    utterance_time_ms: int | None = Field(default=None, ge=0)
    description: str | None = Field(default=None, max_length=500)
    reviewer_status: ReviewStatus | None = None
    change_reason: str = Field(default="Reviewer correction", max_length=240)


class ReviewItem(BaseModel):
    id: str
    session_id: str
    related_event_ids: list[str]
    question: str
    reason: str
    severity: str
    status: ReviewItemStatus
    resolution: str | None = None
    created_at: datetime


class ReviewItemPatch(BaseModel):
    status: ReviewItemStatus
    resolution: str | None = Field(default=None, max_length=1000)


class AuditEntry(BaseModel):
    id: str
    event_id: str
    changed_at: datetime
    previous_value: dict[str, Any]
    updated_value: dict[str, Any]
    actor: str
    change_reason: str


class ReportRecord(BaseModel):
    id: str
    session_id: str
    generated_at: datetime
    source_revision: int
    reviewed_status: str
    structured_json: dict[str, Any]
    final_text: str


class ModelStatus(BaseModel):
    available: bool
    engine: str
    model_path: str | None = None
    detail: str


class DiarizationStatus(BaseModel):
    available: bool
    engine: str = "pyannote.audio"
    model_path: str | None = None
    detail: str


T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    success: bool
    data: T | None = None
    error: str | None = None


class WebSocketMessage(BaseModel):
    type: str
    message_id: str
    data: dict[str, Any] = Field(default_factory=dict)

