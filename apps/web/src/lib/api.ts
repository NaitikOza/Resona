import type {
  ApiEnvelope,
  ClinicalEvent,
  EventCategory,
  EventState,
  HealthStatus,
  ReportRecord,
  ReviewItem,
  ReviewStatus,
  ScenarioSummary,
  Session,
  SessionMode,
  TranscriptSegment,
} from "./types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";
export const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...init?.headers,
    },
  });
  const responseText = await response.text();
  let payload: ApiEnvelope<T>;
  try {
    payload = JSON.parse(responseText) as ApiEnvelope<T>;
  } catch {
    throw new ApiError(
      response.ok
        ? "The local service returned an unreadable response."
        : "The local service stopped responding. Your recording is still saved.",
      response.status,
    );
  }
  if (!response.ok || !payload.success || payload.data === undefined) {
    throw new ApiError(payload.error ?? `Local API request failed (${response.status})`, response.status);
  }
  return payload.data;
}

export const api = {
  health: () => request<HealthStatus>("/api/health"),
  scenarios: () => request<ScenarioSummary[]>("/api/scenarios"),
  sessions: () => request<Session[]>("/api/sessions"),
  createSession: (caseLabel: string, mode: SessionMode) =>
    request<Session>("/api/sessions", {
      method: "POST",
      body: JSON.stringify({ case_label: caseLabel, mode }),
    }),
  getSession: (sessionId: string) => request<Session>(`/api/sessions/${sessionId}`),
  transition: (sessionId: string, action: "start" | "pause" | "resume" | "finish") =>
    request<Session>(`/api/sessions/${sessionId}/${action}`, { method: "POST" }),
  deleteSession: (sessionId: string) =>
    request<{ deleted: boolean; session_id: string }>(`/api/sessions/${sessionId}`, { method: "DELETE" }),
  transcript: (sessionId: string) => request<TranscriptSegment[]>(`/api/sessions/${sessionId}/transcript`),
  events: (sessionId: string) => request<ClinicalEvent[]>(`/api/sessions/${sessionId}/events`),
  detectSpeakers: (sessionId: string) =>
    request<{ segments: TranscriptSegment[]; speaker_count: number }>(`/api/sessions/${sessionId}/speakers`, { method: "POST" }),
  speakerStatus: (sessionId: string) =>
    request<{ status: "PROCESSING" | "READY" | "SKIPPED" | "FAILED"; speaker_count: number }>(
      `/api/sessions/${sessionId}/speakers/status`,
    ),
  reviewItems: (sessionId: string) => request<ReviewItem[]>(`/api/sessions/${sessionId}/review-items`),
  patchTranscript: (segmentId: string, correctedText: string, speakerLabel: string) =>
    request<TranscriptSegment>(`/api/transcript/${segmentId}`, {
      method: "PATCH",
      body: JSON.stringify({ corrected_text: correctedText, speaker_label: speakerLabel, review_status: "CORRECTED", change_reason: "Reviewer correction" }),
    }),
  patchEvent: (
    eventId: string,
    changes: Partial<{ category: EventCategory; normalized_action: string; state: EventState; utterance_time_ms: number; description: string; reviewer_status: ReviewStatus }>,
  ) => request<ClinicalEvent>(`/api/events/${eventId}`, { method: "PATCH", body: JSON.stringify({ ...changes, change_reason: "Reviewer correction" }) }),
  addManualEvent: (
    sessionId: string,
    payload: {
      category: EventCategory;
      normalized_action: string;
      state: EventState;
      utterance_time_ms: number;
      description: string;
      source_segment_ids: string[];
      evidence_text: string;
    },
  ) => request<ClinicalEvent>(`/api/sessions/${sessionId}/events`, { method: "POST", body: JSON.stringify({ ...payload, asserted_action_time_ms: null, confidence: 1, requires_review: false, entities: [] }) }),
  resolveReviewItem: (itemId: string, resolution: string) =>
    request<ReviewItem>(`/api/review-items/${itemId}`, { method: "PATCH", body: JSON.stringify({ status: "RESOLVED", resolution }) }),
  loadSample: (sessionId: string, slug: string) =>
    request<{ session: Session }>(`/api/sessions/${sessionId}/sample/${slug}`, { method: "POST" }),
  uploadAudio: (sessionId: string, file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<{ session: Session; segments: TranscriptSegment[]; event_count: number; audio_retained: boolean }>(`/api/sessions/${sessionId}/audio/upload`, { method: "POST", body });
  },
  addVoiceAddendum: (sessionId: string, file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<{ session: Session; segments: TranscriptSegment[]; events: ClinicalEvent[] }>(
      `/api/sessions/${sessionId}/audio/addendum`,
      { method: "POST", body },
    );
  },
  generateReport: (sessionId: string) => request<ReportRecord>(`/api/sessions/${sessionId}/reports`, { method: "POST" }),
  exportUrl: (sessionId: string, format: "json" | "csv" | "html") => `${API_URL}/api/sessions/${sessionId}/export?format=${format}`,
  audioUrl: (sessionId: string, segmentId: string) => `${API_URL}/api/sessions/${sessionId}/audio/${segmentId}`,
};

