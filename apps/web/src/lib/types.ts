export type SessionMode = "LIVE_MICROPHONE" | "AUDIO_UPLOAD" | "SAMPLE_SCENARIO";
export type SessionStatus = "CREATED" | "RECORDING" | "PAUSED" | "PROCESSING" | "READY_FOR_REVIEW" | "COMPLETED" | "ERROR";
export type EventCategory = "OBSERVATION" | "MEASUREMENT" | "PROCEDURE" | "MEDICATION" | "FLUID_OR_BLOOD_PRODUCT" | "IMAGING_OR_TEST" | "CONSULT_OR_COMMUNICATION" | "EQUIPMENT" | "OTHER";
export type EventState = "PROPOSED" | "REQUESTED" | "ACKNOWLEDGED" | "IN_PROGRESS" | "COMPLETED" | "CANCELLED" | "NEGATED" | "UNCERTAIN" | "REPORTED";
export type ReviewStatus = "UNVERIFIED" | "ACCEPTED" | "EDITED" | "REJECTED";

export interface Session {
  id: string;
  case_label: string;
  mode: SessionMode;
  status: SessionStatus;
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
  simulation_flag: boolean;
  consent_recorded: boolean;
  model_versions: Record<string, string>;
  duration_ms: number;
  revision: number;
}

export interface TranscriptSegment {
  id: string;
  session_id: string;
  start_ms: number;
  end_ms: number;
  raw_text: string;
  corrected_text: string | null;
  speaker_label: string;
  asr_engine: string;
  confidence: number;
  review_status: "RAW" | "CORRECTED" | "VERIFIED";
  created_at: string;
}

export interface EventEntity {
  entity_type: string;
  normalized_name: string | null;
  verbatim_value: string;
  numeric_value: number | null;
  unit: string | null;
  source_span: [number, number];
}

export interface ClinicalEvent {
  id: string;
  session_id: string;
  category: EventCategory;
  normalized_action: string;
  state: EventState;
  utterance_time_ms: number;
  asserted_action_time_ms: number | null;
  description: string;
  source_segment_ids: string[];
  evidence_text: string;
  confidence: number;
  requires_review: boolean;
  entities: EventEntity[];
  reviewer_status: ReviewStatus;
  origin: "rules" | "reviewer" | "optional-llm";
  created_at: string;
  updated_at: string;
}

export interface ReviewItem {
  id: string;
  session_id: string;
  related_event_ids: string[];
  question: string;
  reason: string;
  severity: string;
  status: "OPEN" | "RESOLVED";
  resolution: string | null;
  created_at: string;
}

export interface ReportRecord {
  id: string;
  session_id: string;
  generated_at: string;
  source_revision: number;
  reviewed_status: string;
  structured_json: {
    title: string;
    generated_at: string;
    case_label: string;
    duration_ms: number;
    handoff_summary: string;
    timeline: Array<{
      id: string;
      speech_time_ms: number;
      speech_time: string;
      category: EventCategory;
      action: string;
      summary: string;
      evidence: string;
      speaker: string;
      entities: EventEntity[];
    }>;
    session_feedback: {
      done_well: string[];
      improvements: string[];
      missing: string[];
    };
    reviewer_edits: Array<Record<string, unknown>>;
  };
  final_text: string;
}

export interface ScenarioSummary {
  slug: string;
  title: string;
  description: string;
  duration_ms: number;
  simulated: boolean;
}

export interface HealthStatus {
  status: string;
  scope: string;
  asr: { available: boolean; engine: string; model_path: string | null; detail: string };
  speaker_detection: { available: boolean; engine: string; model_path: string | null; detail: string };
  rules_engine: string;
}

export interface ApiEnvelope<T> {
  success: boolean;
  data?: T;
  error?: string;
}

export interface SocketEnvelope {
  type: "ack" | "processing" | "transcription_final" | "event_added" | "event_updated" | "warning" | "error" | "session_state";
  message_id: string;
  data: Record<string, unknown>;
}

