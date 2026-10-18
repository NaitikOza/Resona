"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  AlertCircle,
  ArrowLeft,
  Check,
  ChevronRight,
  CircleStop,
  ClipboardCheck,
  Copy,
  Download,
  FileAudio,
  FileJson,
  FileSpreadsheet,
  FileText,
  Gauge,
  Headphones,
  LoaderCircle,
  Mic,
  Pause,
  Pencil,
  Play,
  Plus,
  Printer,
  Radio,
  RotateCcw,
  Trash2,
  Upload,
  Volume2,
  X,
} from "lucide-react";
import { api, WS_URL, ApiError } from "@/lib/api";
import { PcmRecorder, packAudioFrame, prepareAudioUpload, recordedFramesToWav } from "@/lib/audio";
import { eventTitle } from "@/lib/events";
import { formatDuration, titleCase } from "@/lib/format";
import { TimelineGraph } from "@/components/timeline-graph";
import type {
  ClinicalEvent,
  EventCategory,
  HealthStatus,
  ReportRecord,
  ScenarioSummary,
  Session,
  SessionMode,
  SocketEnvelope,
  TranscriptSegment,
} from "@/lib/types";

type Phase = "setup" | "live" | "review" | "report";

const categories: EventCategory[] = ["OBSERVATION", "MEASUREMENT", "PROCEDURE", "MEDICATION", "FLUID_OR_BLOOD_PRODUCT", "IMAGING_OR_TEST", "CONSULT_OR_COMMUNICATION", "EQUIPMENT", "OTHER"];
export function SimulationWorkspace() {
  const params = useSearchParams();
  const [phase, setPhase] = useState<Phase>("setup");
  const [mode, setMode] = useState<SessionMode>(params.get("mode") === "sample" ? "SAMPLE_SCENARIO" : "LIVE_MICROPHONE");
  const [caseLabel, setCaseLabel] = useState("Emergency Case");
  const [selectedScenario, setSelectedScenario] = useState("02-blood-request-only");
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [scenarios, setScenarios] = useState<ScenarioSummary[]>([]);
  const [session, setSession] = useState<Session | null>(null);
  const [segments, setSegments] = useState<TranscriptSegment[]>([]);
  const [events, setEvents] = useState<ClinicalEvent[]>([]);
  const [report, setReport] = useState<ReportRecord | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [recordingState, setRecordingState] = useState<"recording" | "paused" | "processing">("recording");
  const [elapsedMs, setElapsedMs] = useState(0);
  const [audioLevel, setAudioLevel] = useState(0);
  const [microphones, setMicrophones] = useState<MediaDeviceInfo[]>([]);
  const [microphoneId, setMicrophoneId] = useState("");
  const [queueState, setQueueState] = useState("Ready");
  const [selectedSegmentId, setSelectedSegmentId] = useState<string | null>(null);
  const [editingEvent, setEditingEvent] = useState<ClinicalEvent | null>(null);
  const [editingSegment, setEditingSegment] = useState<TranscriptSegment | null>(null);
  const [showManualEvent, setShowManualEvent] = useState(false);
  const [showVoiceAddendum, setShowVoiceAddendum] = useState(false);
  const recorderRef = useRef<PcmRecorder | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const drainResolveRef = useRef<(() => void) | null>(null);
  const elapsedBaseRef = useRef(0);
  const activeTimerStartedRef = useRef<number | null>(null);

  useEffect(() => {
    Promise.all([api.health(), api.scenarios()])
      .then(([healthResult, scenarioResult]) => {
        setHealth(healthResult);
        setScenarios(scenarioResult);
      })
      .catch((cause: unknown) => setError(messageFrom(cause)));
  }, []);

  useEffect(() => {
    if (phase !== "live" || recordingState !== "recording") return;
    const timer = window.setInterval(() => {
      const startedAt = activeTimerStartedRef.current;
      if (startedAt !== null) {
        setElapsedMs(elapsedBaseRef.current + Date.now() - startedAt);
      }
    }, 100);
    return () => window.clearInterval(timer);
  }, [phase, recordingState]);

  const refresh = useCallback(async (sessionId: string) => {
    const [nextSession, nextSegments, nextEvents] = await Promise.all([
      api.getSession(sessionId),
      api.transcript(sessionId),
      api.events(sessionId),
    ]);
    setSession(nextSession);
    setSegments(nextSegments);
    setEvents(nextEvents);
  }, []);

  const handleSocketMessage = useCallback((raw: MessageEvent<string>) => {
    const payload = JSON.parse(raw.data) as SocketEnvelope;
    if (payload.type === "transcription_final") {
      const segment = payload.data.segment as TranscriptSegment;
      setSegments((current) => dedupeById([...current, segment]));
      setQueueState("Listening");
    } else if (payload.type === "event_added") {
      const event = payload.data.event as ClinicalEvent;
      setEvents((current) => dedupeById([...current, event]));
    } else if (payload.type === "processing") {
      setQueueState("Processing audio…");
    } else if (payload.type === "warning") {
      setNotice(String(payload.data.warning ?? "Local audio warning"));
    } else if (payload.type === "error") {
      setError(String(payload.data.error ?? "Local audio processing failed"));
      setQueueState("Needs attention");
    } else if (payload.type === "session_state" && payload.data.status === "AUDIO_DRAINED") {
      drainResolveRef.current?.();
      drainResolveRef.current = null;
    }
  }, []);

  async function begin(): Promise<void> {
    if (!caseLabel.trim()) {
      setError("Add a case name.");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    let created: Session | null = null;
    try {
      created = await api.createSession(caseLabel.trim(), mode);
      setSession(created);
      if (mode === "SAMPLE_SCENARIO") {
        await api.loadSample(created.id, selectedScenario);
        await refresh(created.id);
        setPhase("review");
        setNotice("Sample transcript loaded.");
      } else if (mode === "AUDIO_UPLOAD") {
        if (!audioFile) throw new Error("Choose a WAV or MP3 file.");
        setNotice("Preparing audio…");
        const preparedAudio = await prepareAudioUpload(audioFile);
        setNotice("Analyzing audio…");
        await api.uploadAudio(created.id, preparedAudio);
        await refresh(created.id);
        setPhase("review");
      } else {
        const started = await api.transition(created.id, "start");
        setSession(started);
        const socket = await connectSocket(created.id, handleSocketMessage);
        socketRef.current = socket;
        const recorder = new PcmRecorder();
        recorderRef.current = recorder;
        await recorder.start(
          (frame) => {
            if (socket.readyState === WebSocket.OPEN) socket.send(packAudioFrame(frame));
          },
          setAudioLevel,
          microphoneId || undefined,
        );
        elapsedBaseRef.current = 0;
        activeTimerStartedRef.current = Date.now();
        setElapsedMs(0);
        setRecordingState("recording");
        setQueueState(health?.asr.available ? "Listening" : "Audio unavailable");
        setPhase("live");
      }
    } catch (cause: unknown) {
      await recorderRef.current?.stop().catch(() => undefined);
      socketRef.current?.close();
      if (created) await api.deleteSession(created.id).catch(() => undefined);
      setSession(null);
      setError(messageFrom(cause));
    } finally {
      setBusy(false);
    }
  }

  async function pauseOrResume(): Promise<void> {
    if (!session) return;
    setError(null);
    try {
      if (recordingState === "recording") {
        if (activeTimerStartedRef.current !== null) {
          elapsedBaseRef.current += Date.now() - activeTimerStartedRef.current;
          activeTimerStartedRef.current = null;
          setElapsedMs(elapsedBaseRef.current);
        }
        recorderRef.current?.pause();
        const updated = await api.transition(session.id, "pause");
        setSession(updated);
        setRecordingState("paused");
        setQueueState("Capture paused");
      } else if (recordingState === "paused") {
        const updated = await api.transition(session.id, "resume");
        recorderRef.current?.resume();
        activeTimerStartedRef.current = Date.now();
        setSession(updated);
        setRecordingState("recording");
        setQueueState("Listening");
      }
    } catch (cause: unknown) {
      setError(messageFrom(cause));
    }
  }

  async function finish(): Promise<void> {
    if (!session) return;
    setBusy(true);
    setError(null);
    if (activeTimerStartedRef.current !== null) {
      elapsedBaseRef.current += Date.now() - activeTimerStartedRef.current;
      activeTimerStartedRef.current = null;
      setElapsedMs(elapsedBaseRef.current);
    }
    setRecordingState("processing");
    setQueueState("Finishing queued audio…");
    try {
      await recorderRef.current?.stop();
      const socket = socketRef.current;
      if (socket?.readyState === WebSocket.OPEN) {
        const drained = new Promise<void>((resolve) => {
          drainResolveRef.current = resolve;
          window.setTimeout(resolve, 180_000);
        });
        socket.send(JSON.stringify({ type: "finish" }));
        await drained;
        socket.close();
      }
      setQueueState("Finalizing transcript…");
      await api.transition(session.id, "finish");
      let speakerStatus = await api.speakerStatus(session.id);
      for (let attempt = 0; speakerStatus.status === "PROCESSING" && attempt < 180; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 1_000));
        speakerStatus = await api.speakerStatus(session.id);
      }
      await refresh(session.id);
      setPhase("review");
      setNotice("Recording complete. Review the transcript and timeline, then generate your report.");
    } catch (cause: unknown) {
      setError(messageFrom(cause));
    } finally {
      setBusy(false);
    }
  }

  async function discard(): Promise<void> {
    if (!session || !window.confirm("Delete this session, including its transcript and audio?")) return;
    setBusy(true);
    try {
      await recorderRef.current?.stop();
      socketRef.current?.close();
      await api.deleteSession(session.id);
      resetWorkspace();
      setNotice("Session deleted.");
    } catch (cause: unknown) {
      setError(messageFrom(cause));
    } finally {
      setBusy(false);
    }
  }

  function resetWorkspace(): void {
    setSession(null);
    setSegments([]);
    setEvents([]);
    setReport(null);
    setElapsedMs(0);
    elapsedBaseRef.current = 0;
    activeTimerStartedRef.current = null;
    setAudioLevel(0);
    setPhase("setup");
  }

  async function generateReport(): Promise<void> {
    if (!session) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.generateReport(session.id);
      setReport(result);
      setPhase("report");
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (cause: unknown) {
      setError(messageFrom(cause));
    } finally {
      setBusy(false);
    }
  }

  async function updateEvent(eventId: string, changes: Parameters<typeof api.patchEvent>[1]): Promise<void> {
    const updated = await api.patchEvent(eventId, changes);
    setEvents((current) => current.map((event) => (event.id === updated.id ? updated : event)));
  }

  async function updateSegment(segmentId: string, text: string, speaker: string): Promise<void> {
    const updated = await api.patchTranscript(segmentId, text, speaker);
    setSegments((current) => current.map((segment) => (segment.id === updated.id ? updated : segment)));
    setEditingSegment(null);
    setNotice("Transcript correction saved. Existing extracted events retain their original evidence until individually reviewed.");
  }

  async function addVoiceAddendum(file: File): Promise<void> {
    if (!session) return;
    const result = await api.addVoiceAddendum(session.id, file);
    setSession(result.session);
    setSegments((current) => dedupeById([...current, ...result.segments]));
    setEvents((current) => dedupeById([...current, ...result.events]));
    setShowVoiceAddendum(false);
    setNotice("Voice note added. Review the new transcript line and timeline item before generating the report.");
  }

  function jumpToEvidence(event: ClinicalEvent): void {
    const id = event.source_segment_ids[0];
    setSelectedSegmentId(id);
    document.getElementById(`segment-${id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  return (
    <main className="min-h-[calc(100vh-8rem)]">
      {error && <Message tone="error" onClose={() => setError(null)}>{error}</Message>}
      {notice && <Message tone="notice" onClose={() => setNotice(null)}>{notice}</Message>}
      {phase === "setup" && (
        <SetupView
          mode={mode}
          setMode={setMode}
          caseLabel={caseLabel}
          setCaseLabel={setCaseLabel}
          health={health}
          scenarios={scenarios}
          selectedScenario={selectedScenario}
          setSelectedScenario={setSelectedScenario}
          audioFile={audioFile}
          setAudioFile={setAudioFile}
          microphones={microphones}
          setMicrophones={setMicrophones}
          microphoneId={microphoneId}
          setMicrophoneId={setMicrophoneId}
          busy={busy}
          onBegin={begin}
          setNotice={setNotice}
          setError={setError}
        />
      )}
      {phase === "live" && session && (
        <LiveView
          session={session}
          segments={segments}
          events={events}
          elapsedMs={elapsedMs}
          audioLevel={audioLevel}
          queueState={queueState}
          recordingState={recordingState}
          busy={busy}
          onPauseResume={pauseOrResume}
          onFinish={finish}
          onDiscard={discard}
          onEvidence={jumpToEvidence}
          selectedSegmentId={selectedSegmentId}
        />
      )}
      {phase === "review" && session && (
        <ReviewView
          session={session}
          segments={segments}
          events={events}
          busy={busy}
          selectedSegmentId={selectedSegmentId}
          setSelectedSegmentId={setSelectedSegmentId}
          onEditSegment={setEditingSegment}
          onEditEvent={setEditingEvent}
          onUpdateEvent={updateEvent}
          onEvidence={jumpToEvidence}
          onManualEvent={() => setShowManualEvent(true)}
          onVoiceAddendum={() => setShowVoiceAddendum(true)}
          onGenerate={generateReport}
          onDiscard={discard}
        />
      )}
      {phase === "report" && session && report && (
        <ReportView report={report} session={session} onBack={() => setPhase("review")} onNew={resetWorkspace} />
      )}
      {editingEvent && <EventEditor event={editingEvent} onClose={() => setEditingEvent(null)} onSave={async (changes) => { await updateEvent(editingEvent.id, changes); setEditingEvent(null); }} />}
      {editingSegment && <TranscriptEditor segment={editingSegment} onClose={() => setEditingSegment(null)} onSave={updateSegment} />}
      {showManualEvent && session && selectedSegmentId && (
        <ManualEventEditor
          sessionId={session.id}
          segment={segments.find((item) => item.id === selectedSegmentId)!}
          onClose={() => setShowManualEvent(false)}
          onSave={(event) => { setEvents((current) => [...current, event]); setShowManualEvent(false); }}
        />
      )}
      {showVoiceAddendum && session && (
        <VoiceAddendumModal
          microphoneId={microphoneId}
          onClose={() => setShowVoiceAddendum(false)}
          onSave={addVoiceAddendum}
        />
      )}
    </main>
  );
}

function Message({ tone, onClose, children }: { tone: "error" | "notice"; onClose: () => void; children: React.ReactNode }) {
  const classes = tone === "error" ? "border-red-200 bg-red-50 text-red-800" : "border-teal-200 bg-teal-50 text-teal-900";
  return <div className={`no-print mx-auto mt-5 flex max-w-[1380px] items-start justify-between gap-3 rounded-xl border px-4 py-3 text-sm ${classes}`} role={tone === "error" ? "alert" : "status"}><span className="flex items-start gap-2">{tone === "error" ? <AlertCircle size={17} className="mt-0.5 shrink-0" /> : <Check size={17} className="mt-0.5 shrink-0" />}{children}</span><button aria-label="Dismiss message" onClick={onClose}><X size={16} /></button></div>;
}

function SetupView(props: {
  mode: SessionMode; setMode: (mode: SessionMode) => void; caseLabel: string; setCaseLabel: (value: string) => void; health: HealthStatus | null; scenarios: ScenarioSummary[]; selectedScenario: string; setSelectedScenario: (value: string) => void; audioFile: File | null; setAudioFile: (value: File | null) => void; microphones: MediaDeviceInfo[]; setMicrophones: (devices: MediaDeviceInfo[]) => void; microphoneId: string; setMicrophoneId: (id: string) => void; busy: boolean; onBegin: () => void; setNotice: (value: string | null) => void; setError: (value: string | null) => void;
}) {
  const [device, setDevice] = useState<"untested" | "testing" | "ready">("untested");
  async function testDevice() {
    setDevice("testing");
    props.setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: props.microphoneId
          ? { deviceId: { exact: props.microphoneId } }
          : true,
      });
      const track = stream.getAudioTracks()[0];
      const devices = navigator.mediaDevices.enumerateDevices
        ? await navigator.mediaDevices.enumerateDevices()
        : [];
      const inputs = devices.filter((item) => item.kind === "audioinput");
      props.setMicrophones(inputs);
      const activeDeviceId = track.getSettings?.().deviceId;
      if (!props.microphoneId && activeDeviceId) props.setMicrophoneId(activeDeviceId);
      props.setNotice(`Microphone ready: ${track.label || "available device"}. No audio was retained.`);
      stream.getTracks().forEach((item) => item.stop());
      setDevice("ready");
    } catch (cause: unknown) {
      props.setError(messageFrom(cause));
      setDevice("untested");
    }
  }
  const options: Array<{ mode: SessionMode; icon: typeof Mic; title: string; copy: string }> = [
    { mode: "LIVE_MICROPHONE", icon: Mic, title: "Microphone", copy: "Transcribe speech as it happens." },
    { mode: "AUDIO_UPLOAD", icon: Upload, title: "Upload audio", copy: "Choose a WAV or MP3 file." },
    { mode: "SAMPLE_SCENARIO", icon: Play, title: "Sample case", copy: "Explore a ready-made example." },
  ];
  return (
    <div className="mx-auto max-w-[920px] px-5 py-10 lg:px-8 lg:py-14">
      <div className="mb-9 max-w-3xl"><p className="eyebrow">New session</p><h1 className="mt-3 font-display text-4xl font-semibold tracking-tight text-ink sm:text-5xl">Choose how to begin.</h1><p className="mt-4 text-slate-600">Record live, upload audio, or open a sample case.</p></div>
      <section className="panel p-5 sm:p-7">
          <fieldset><legend className="text-sm font-bold text-ink">Capture source</legend><div className="mt-4 grid gap-3 sm:grid-cols-3">{options.map(({ mode, icon: Icon, title, copy }) => <button type="button" key={mode} onClick={() => props.setMode(mode)} className={`rounded-2xl border p-4 text-left transition ${props.mode === mode ? "border-teal-500 bg-teal-50 shadow-sm" : "border-slate-200 bg-white hover:border-slate-300"}`} aria-pressed={props.mode === mode}><Icon className={props.mode === mode ? "text-teal-700" : "text-slate-400"} size={21} /><span className="mt-4 block text-sm font-bold text-ink">{title}</span><span className="mt-1 block text-xs leading-5 text-slate-500">{copy}</span></button>)}</div></fieldset>
          <label className="mt-7 block text-sm font-bold text-ink" htmlFor="case-label">Case name</label><input id="case-label" className="field mt-2" maxLength={120} value={props.caseLabel} onChange={(event) => props.setCaseLabel(event.target.value)} placeholder="e.g. Emergency Case 24" />
          {props.mode === "LIVE_MICROPHONE" && <div className="mt-6 rounded-2xl border border-slate-200 bg-slate-50 p-4"><div className="flex flex-col items-start justify-between gap-3 sm:flex-row sm:items-center"><p className="text-sm font-bold text-ink">Microphone</p><button className="button-secondary !px-3.5 !py-2.5" type="button" onClick={testDevice} disabled={device === "testing"}>{device === "testing" ? <LoaderCircle className="animate-spin" size={16} /> : device === "ready" ? <Check size={16} /> : <Gauge size={16} />} {device === "ready" ? "Test again" : "Device test"}</button></div>{props.microphones.length > 0 && <div className="mt-4 border-t border-slate-200 pt-4"><label className="text-xs font-bold text-ink" htmlFor="microphone-device">Input device</label><select id="microphone-device" className="field mt-2" value={props.microphoneId} onChange={(event) => { props.setMicrophoneId(event.target.value); setDevice("untested"); }}>{props.microphones.map((microphone, index) => <option key={microphone.deviceId || index} value={microphone.deviceId}>{microphone.label || `Microphone ${index + 1}`}</option>)}</select><p className="mt-2 text-xs leading-5 text-slate-500">Choose the microphone closest to the speaker for the clearest transcript.</p></div>}</div>}
          {props.mode === "AUDIO_UPLOAD" && <label className="mt-6 flex cursor-pointer flex-col items-center rounded-2xl border-2 border-dashed border-slate-300 bg-slate-50 px-5 py-8 text-center hover:border-teal-400"><FileAudio className="text-teal-700" /><span className="mt-3 text-sm font-bold text-ink">{props.audioFile?.name ?? "Choose an audio file"}</span><span className="mt-1 text-xs text-slate-500">WAV or MP3</span><input className="sr-only" type="file" accept="audio/wav,audio/mpeg,.wav,.mp3" onChange={(event) => props.setAudioFile(event.target.files?.[0] ?? null)} /></label>}
          {props.mode === "SAMPLE_SCENARIO" && <div className="mt-6"><label htmlFor="scenario" className="text-sm font-bold text-ink">Sample case</label><select id="scenario" className="field mt-2" value={props.selectedScenario} onChange={(event) => props.setSelectedScenario(event.target.value)}>{props.scenarios.map((scenario) => <option key={scenario.slug} value={scenario.slug}>{scenario.title}</option>)}</select></div>}
          {props.health && !props.health.asr.available && props.mode !== "SAMPLE_SCENARIO" && <p className="mt-5 rounded-xl bg-amber-50 p-3 text-sm text-amber-800">Audio transcription is unavailable. Check the local service and try again.</p>}
          <div className="mt-7 flex justify-end"><button className="button-primary" type="button" onClick={props.onBegin} disabled={props.busy || (props.mode !== "SAMPLE_SCENARIO" && props.health !== null && !props.health.asr.available)}>{props.busy ? <LoaderCircle className="animate-spin" size={17} /> : props.mode === "LIVE_MICROPHONE" ? <Radio size={17} /> : <ChevronRight size={17} />}{props.busy ? "Preparing…" : props.mode === "LIVE_MICROPHONE" ? "Start recording" : props.mode === "AUDIO_UPLOAD" ? "Transcribe audio" : "Open sample case"}</button></div>
      </section>
    </div>
  );
}

function LiveView(props: { session: Session; segments: TranscriptSegment[]; events: ClinicalEvent[]; elapsedMs: number; audioLevel: number; queueState: string; recordingState: "recording" | "paused" | "processing"; busy: boolean; onPauseResume: () => void; onFinish: () => void; onDiscard: () => void; onEvidence: (event: ClinicalEvent) => void; selectedSegmentId: string | null }) {
  return <div className="mx-auto max-w-[1320px] px-4 py-6 lg:px-6"><div className="mb-5 flex flex-col justify-between gap-4 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm lg:flex-row lg:items-center"><div className="flex items-center gap-4"><div className={`grid size-11 place-items-center rounded-xl ${props.recordingState === "recording" ? "bg-red-50 text-red-600" : "bg-slate-100 text-slate-500"}`}><Radio className={props.recordingState === "recording" ? "animate-pulse" : ""} /></div><div><p className="text-xs font-bold uppercase tracking-wider text-slate-400">{props.session.case_label}</p><div className="mt-1 flex items-center gap-3"><span className="font-mono text-2xl font-bold tabular-nums text-ink">{formatDuration(props.elapsedMs)}</span><span className="text-xs font-semibold text-slate-500">{props.queueState}</span></div></div></div><div className="flex flex-wrap items-center gap-2"><AudioMeter level={props.audioLevel} /><button className="button-secondary !px-3.5 !py-2.5" onClick={props.onPauseResume} disabled={props.busy || props.recordingState === "processing"}>{props.recordingState === "paused" ? <Play size={16} /> : <Pause size={16} />}{props.recordingState === "paused" ? "Resume" : "Pause"}</button><button className="button-primary !bg-coral !px-3.5 !py-2.5 hover:!bg-red-600" onClick={props.onFinish} disabled={props.busy}>{props.busy ? <LoaderCircle className="animate-spin" size={16} /> : <CircleStop size={16} />}Finish</button><button className="button-ghost text-red-600" onClick={props.onDiscard}><Trash2 size={16} />Delete</button></div></div><div className="grid min-h-[650px] gap-4 lg:grid-cols-2"><TranscriptPanel segments={props.segments} selectedId={props.selectedSegmentId} continuous /><TimelinePanel events={props.events} onEvidence={props.onEvidence} /></div></div>;
}

function AudioMeter({ level }: { level: number }) { return <div className="flex items-center gap-2 rounded-xl border border-slate-200 px-3 py-2" aria-label={`Microphone level ${Math.round(level * 100)} percent`}><Volume2 size={16} className="text-teal-700" /><div className="flex h-5 items-end gap-0.5">{[0.15, 0.3, 0.45, 0.6, 0.75, 0.9].map((threshold) => <span key={threshold} className={`w-1 rounded-full transition ${level >= threshold ? "bg-teal-500" : "bg-slate-200"}`} style={{ height: `${7 + threshold * 12}px` }} />)}</div></div>; }

function TranscriptPanel({ segments, selectedId, onEdit, selectable = false, onSelect, showAudio = false, samplePlayback = false, continuous = false }: { segments: TranscriptSegment[]; selectedId: string | null; onEdit?: (segment: TranscriptSegment) => void; selectable?: boolean; onSelect?: (id: string) => void; showAudio?: boolean; samplePlayback?: boolean; continuous?: boolean }) {
  const continuousText = segments.map((segment) => segment.corrected_text || segment.raw_text).join(" ");
  return <section className="panel flex min-h-[500px] flex-col overflow-hidden"><div className="flex items-center justify-between border-b border-slate-200 p-4"><div><p className="eyebrow">Transcript</p><p className="mt-1 text-xs text-slate-500">{continuous ? "Speech appears here as you record" : "Select a line to review or edit it"}</p></div><Headphones size={18} className="text-slate-400" /></div><div className="max-h-[680px] flex-1 space-y-2 overflow-y-auto p-3" aria-live="polite">{continuous && segments.length ? <article className="rounded-xl bg-slate-50 p-4"><p className="text-base leading-8 text-ink">{continuousText}</p></article> : segments.length ? segments.map((segment) => <article id={`segment-${segment.id}`} key={segment.id} onClick={() => selectable && onSelect?.(segment.id)} className={`group rounded-xl border p-3 transition ${selectedId === segment.id ? "border-teal-400 bg-teal-50 ring-2 ring-teal-100" : "border-transparent hover:border-slate-200 hover:bg-slate-50"} ${selectable ? "cursor-pointer" : ""}`}><div className="flex items-center justify-between gap-3"><div className="flex items-center gap-2"><span className="font-mono text-[11px] font-semibold text-teal-700">{formatDuration(segment.start_ms)}</span><span className="text-[11px] font-semibold text-slate-400">{segment.speaker_label}</span>{segment.corrected_text && <span className="text-[10px] font-semibold uppercase tracking-wide text-teal-700">Edited</span>}</div>{onEdit && <button className="button-ghost !p-1.5 opacity-60 group-hover:opacity-100" aria-label="Edit transcript segment" onClick={(event) => { event.stopPropagation(); onEdit(segment); }}><Pencil size={14} /></button>}</div><p className="mt-2 text-sm leading-6 text-ink">{segment.corrected_text || segment.raw_text}</p>{showAudio && !segment.asr_engine.includes("/voice-addendum") && (samplePlayback ? <button type="button" className="button-ghost mt-2 !px-2 !py-1.5 text-teal-700" aria-label="Play transcript audio" onClick={(event) => { event.stopPropagation(); speakText(segment.corrected_text || segment.raw_text); }}><Volume2 size={15} />Play audio</button> : <audio className="mt-3 h-8 w-full" controls preload="none" src={api.audioUrl(segment.session_id, segment.id)} onClick={(event) => event.stopPropagation()}>Audio playback is unavailable in this browser.</audio>)}</article>) : <Empty icon={WavesPlaceholder} title="Listening" copy="Your transcript will appear here." />}</div></section>;
}

function speakText(text: string): void {
  if (!("speechSynthesis" in window) || !("SpeechSynthesisUtterance" in window)) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = 0.95;
  window.speechSynthesis.speak(utterance);
}

function WavesPlaceholder({ size = 22 }: { size?: number }) { return <Radio size={size} />; }

function TimelinePanel({ events, onEvidence, onEdit, onUpdate }: { events: ClinicalEvent[]; onEvidence: (event: ClinicalEvent) => void; onEdit?: (event: ClinicalEvent) => void; onUpdate?: (eventId: string, changes: Parameters<typeof api.patchEvent>[1]) => Promise<void> }) {
  return <section className="panel flex min-h-[500px] flex-col overflow-hidden"><div className="flex items-center justify-between border-b border-slate-200 p-4"><div><p className="eyebrow">Timeline</p><p className="mt-1 text-xs text-slate-500">Key moments found in the transcript</p></div><span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-bold text-slate-600">{events.length}</span></div><div className="max-h-[680px] flex-1 space-y-3 overflow-y-auto p-4">{events.filter((event) => event.reviewer_status !== "REJECTED").length ? events.filter((event) => event.reviewer_status !== "REJECTED").map((event) => <EventCard key={event.id} event={event} onEvidence={() => onEvidence(event)} onEdit={onEdit ? () => onEdit(event) : undefined} onUpdate={onUpdate} />) : <Empty icon={FileText} title="No events yet" copy="Important moments will appear here." />}</div></section>;
}

function EventCard({ event, onEvidence, onEdit, onUpdate }: { event: ClinicalEvent; onEvidence: () => void; onEdit?: () => void; onUpdate?: (eventId: string, changes: Parameters<typeof api.patchEvent>[1]) => Promise<void> }) {
  const kept = event.reviewer_status === "ACCEPTED";
  return <article className={`rounded-2xl border bg-white p-4 shadow-sm transition ${kept ? "border-teal-300 ring-1 ring-teal-100" : "border-slate-200"}`}><div className="flex flex-wrap items-center gap-2"><span className="font-mono text-[11px] font-bold text-slate-400">{formatDuration(event.utterance_time_ms)}</span><span className="text-[10px] font-bold uppercase tracking-wide text-slate-400">{titleCase(event.category)}</span>{kept && <span className="ml-auto inline-flex items-center gap-1 rounded-full bg-teal-50 px-2 py-1 text-[10px] font-bold uppercase tracking-wide text-teal-700"><Check size={12} />Kept</span>}</div><p className="mt-3 text-sm font-semibold leading-5 text-ink">{eventTitle(event)}</p><button onClick={onEvidence} className="mt-3 block w-full rounded-lg border-l-2 border-teal-400 bg-slate-50 px-3 py-2 text-left text-xs italic leading-5 text-slate-600 hover:bg-teal-50">“{event.evidence_text}” <span className="not-italic text-teal-700">View in transcript</span></button>{(onEdit || onUpdate) && <div className="mt-3 flex flex-wrap items-center justify-end gap-2 border-t border-slate-100 pt-3"><div className="flex gap-1">{onUpdate && <><button className="button-ghost !px-2 !py-1.5 text-teal-700" disabled={kept} onClick={() => void onUpdate(event.id, { reviewer_status: "ACCEPTED" })}><Check size={14} />{kept ? "Kept" : "Keep"}</button><button className="button-ghost !px-2 !py-1.5 text-red-600" onClick={() => void onUpdate(event.id, { reviewer_status: "REJECTED" })}><X size={14} />Remove</button></>}{onEdit && <button className="button-ghost !px-2 !py-1.5" onClick={onEdit}><Pencil size={14} />Edit</button>}</div></div>}</article>;
}

function ReviewView(props: { session: Session; segments: TranscriptSegment[]; events: ClinicalEvent[]; busy: boolean; selectedSegmentId: string | null; setSelectedSegmentId: (id: string | null) => void; onEditSegment: (segment: TranscriptSegment) => void; onEditEvent: (event: ClinicalEvent) => void; onUpdateEvent: (eventId: string, changes: Parameters<typeof api.patchEvent>[1]) => Promise<void>; onEvidence: (event: ClinicalEvent) => void; onManualEvent: () => void; onVoiceAddendum: () => void; onGenerate: () => void; onDiscard: () => void }) {
  return <div className="mx-auto max-w-[1320px] px-4 py-7 lg:px-6"><div className="mb-6 flex flex-col justify-between gap-4 lg:flex-row lg:items-end"><div><p className="eyebrow">Review</p><h1 className="mt-2 font-display text-4xl font-semibold text-ink">Review your record.</h1><p className="mt-2 text-sm text-slate-500">{props.session.case_label} · {formatDuration(props.session.duration_ms)}</p></div><div className="flex flex-wrap gap-2"><button className="button-secondary" onClick={props.onVoiceAddendum}><Mic size={16} />Add by voice</button>{props.selectedSegmentId && <button className="button-secondary" onClick={props.onManualEvent}><Plus size={16} />Add timeline item</button>}<button className="button-secondary" onClick={props.onDiscard}><Trash2 size={16} />Delete</button><button className="button-primary" onClick={props.onGenerate} disabled={props.busy}>{props.busy ? <LoaderCircle className="animate-spin" size={16} /> : <FileCheck2Icon />}Generate report</button></div></div><div className="grid gap-4 lg:grid-cols-2"><TranscriptPanel segments={props.segments} selectedId={props.selectedSegmentId} onEdit={props.onEditSegment} selectable onSelect={props.setSelectedSegmentId} showAudio samplePlayback={props.session.mode === "SAMPLE_SCENARIO"} /><TimelinePanel events={props.events} onEvidence={props.onEvidence} onEdit={props.onEditEvent} onUpdate={props.onUpdateEvent} /></div></div>;
}

function FileCheck2Icon() { return <ClipboardCheck size={17} />; }

function ReportView({ report, session, onBack, onNew }: { report: ReportRecord; session: Session; onBack: () => void; onNew: () => void }) {
  const data = report.structured_json;
  const feedback = data.session_feedback ?? { done_well: [], improvements: [], missing: [] };
  const [copied, setCopied] = useState(false);

  async function copyHandoff(): Promise<void> {
    try {
      await navigator.clipboard.writeText(data.handoff_summary);
    } catch {
      const fallback = document.createElement("textarea");
      fallback.value = data.handoff_summary;
      fallback.style.position = "fixed";
      fallback.style.opacity = "0";
      document.body.appendChild(fallback);
      fallback.select();
      document.execCommand("copy");
      fallback.remove();
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1_800);
  }

  return (
    <div className="mx-auto max-w-[1100px] px-5 py-8 lg:px-8">
      <div className="no-print mb-6 flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <button className="button-ghost" onClick={onBack}><ArrowLeft size={16} />Back to review</button>
        <div className="flex flex-wrap gap-2">
          <a className="button-secondary !px-3.5 !py-2.5" href="/library">Library</a>
          <a className="button-secondary !px-3.5 !py-2.5" href={api.exportUrl(session.id, "json")}><FileJson size={16} />JSON</a>
          <a className="button-secondary !px-3.5 !py-2.5" href={api.exportUrl(session.id, "csv")}><FileSpreadsheet size={16} />CSV</a>
          <a className="button-secondary !px-3.5 !py-2.5" href={api.exportUrl(session.id, "html")}><Download size={16} />HTML</a>
          <button className="button-primary !px-3.5 !py-2.5" onClick={() => window.print()}><Printer size={16} />Print / PDF</button>
        </div>
      </div>

      <article className="rounded-2xl border border-slate-200 bg-white p-6 shadow-panel sm:p-10">
        <div className="border-b border-slate-200 pb-7">
          <p className="eyebrow">Report</p>
          <h1 className="mt-3 font-display text-4xl font-semibold text-ink">{data.title}</h1>
          <p className="mt-3 text-sm text-slate-500">Generated {new Date(data.generated_at).toLocaleString()}</p>
        </div>

        <section className="my-6 grid gap-4 rounded-xl bg-slate-50 p-5 sm:grid-cols-3">
          <ReportFact label="Case" value={data.case_label} />
          <ReportFact label="Duration" value={formatDuration(data.duration_ms)} />
          <ReportFact label="Timeline items" value={String(data.timeline.length)} />
        </section>

        <section className="mt-8 rounded-2xl border border-teal-200 bg-teal-50/70 p-5 sm:p-6">
          <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
            <div>
              <h2 className="font-display text-2xl font-semibold text-ink">Handoff summary</h2>
              <p className="mt-1 text-sm text-slate-500">A concise summary of the documented emergency care.</p>
            </div>
            <button className="button-secondary no-print shrink-0" onClick={() => void copyHandoff()}>
              {copied ? <Check size={16} /> : <Copy size={16} />}{copied ? "Copied" : "Copy summary"}
            </button>
          </div>
          <p className="mt-4 text-[15px] leading-7 text-ink">{data.handoff_summary}</p>
        </section>

        <section className="mt-10">
          <h2 className="font-display text-2xl font-semibold text-ink">Event map</h2>
          <p className="mt-1 text-sm text-slate-500">A visual path through the documented sequence.</p>
          <div className="mt-4"><TimelineGraph items={data.timeline} /></div>
        </section>

        <section className="mt-10">
          <h2 className="font-display text-2xl font-semibold text-ink">Timeline details</h2>
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[760px] border-collapse text-left text-sm">
              <thead><tr className="border-b-2 border-slate-200 text-xs uppercase tracking-wide text-slate-500"><th className="py-3 pr-4">Time</th><th className="py-3 pr-4">Event</th><th className="py-3 pr-4">Speaker</th><th className="py-3">Transcript</th></tr></thead>
              <tbody>{data.timeline.map((event) => <tr key={event.id} className="border-b border-slate-100 align-top"><td className="py-4 pr-4 font-mono text-xs text-slate-500">{event.speech_time}</td><td className="py-4 pr-5"><p className="font-semibold text-ink">{event.summary}</p><p className="mt-1 text-xs text-slate-500">{titleCase(event.category)}</p></td><td className="py-4 pr-5 text-slate-600">{event.speaker}</td><td className="py-4 italic leading-5 text-slate-600">“{event.evidence}”</td></tr>)}</tbody>
            </table>
          </div>
        </section>

        <section className="mt-10">
          <h2 className="font-display text-2xl font-semibold text-ink">Session feedback</h2>
          <p className="mt-1 text-sm text-slate-500">Case-specific clinical review based on the documented actions, findings, and outcomes.</p>
          <div className="mt-4 grid gap-3 md:grid-cols-3"><FeedbackCard title="What went well" items={feedback.done_well} tone="teal" /><FeedbackCard title="Improve next time" items={feedback.improvements} tone="amber" /><FeedbackCard title="What was missed" items={feedback.missing} tone="slate" /></div>
        </section>
      </article>

      <div className="no-print mt-7 flex justify-center"><button className="button-secondary" onClick={onNew}><RotateCcw size={16} />Start a new session</button></div>
    </div>
  );
}

function FeedbackCard({ title, items, tone }: { title: string; items: string[]; tone: "teal" | "amber" | "slate" }) {
  const colors = tone === "teal" ? "border-teal-200 bg-teal-50" : tone === "amber" ? "border-amber-200 bg-amber-50" : "border-slate-200 bg-slate-50";
  return <section className={`rounded-xl border p-4 ${colors}`}><h3 className="text-sm font-bold text-ink">{title}</h3><ul className="mt-3 space-y-2 text-sm leading-5 text-slate-600">{items.map((item) => <li key={item} className="flex gap-2"><span aria-hidden="true">•</span><span>{item}</span></li>)}</ul></section>;
}

function ReportFact({ label, value }: { label: string; value: string }) { return <div><p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">{label}</p><p className="mt-1 text-sm font-semibold text-ink">{value}</p></div>; }

function EventEditor({ event, onClose, onSave }: { event: ClinicalEvent; onClose: () => void; onSave: (changes: Parameters<typeof api.patchEvent>[1]) => Promise<void> }) {
  const [category, setCategory] = useState<EventCategory>(event.category); const [description, setDescription] = useState(eventTitle(event)); const [time, setTime] = useState(event.utterance_time_ms); const [saving, setSaving] = useState(false);
  return <Modal title="Edit timeline item" onClose={onClose}><p className="rounded-xl border-l-2 border-teal-400 bg-slate-50 p-3 text-sm italic text-slate-600">“{event.evidence_text}”</p><div className="mt-5 grid gap-4 sm:grid-cols-2"><Field label="Category"><select className="field" value={category} onChange={(e) => setCategory(e.target.value as EventCategory)}>{categories.map((item) => <option key={item}>{titleCase(item)}</option>)}</select></Field><Field label="Time (ms)"><input className="field" type="number" min={0} value={time} onChange={(e) => setTime(Number(e.target.value))} /></Field><Field label="Title"><textarea className="field min-h-24" value={description} onChange={(e) => setDescription(e.target.value)} /></Field></div><div className="mt-6 flex justify-end gap-2"><button className="button-secondary" onClick={onClose}>Cancel</button><button className="button-primary" disabled={saving || !description.trim()} onClick={async () => { setSaving(true); await onSave({ category, description: description.trim(), utterance_time_ms: time, reviewer_status: "EDITED" }); setSaving(false); }}>{saving && <LoaderCircle className="animate-spin" size={16} />}Save</button></div></Modal>;
}

function TranscriptEditor({ segment, onClose, onSave }: { segment: TranscriptSegment; onClose: () => void; onSave: (id: string, text: string, speaker: string) => Promise<void> }) {
  const [text, setText] = useState(segment.corrected_text || segment.raw_text); const [speaker, setSpeaker] = useState(segment.speaker_label); const [saving, setSaving] = useState(false);
  return <Modal title="Correct transcript source" onClose={onClose}><div className="rounded-xl bg-slate-50 p-3 text-xs text-slate-500"><strong>Original ASR text is retained:</strong> “{segment.raw_text}”</div><div className="mt-5 space-y-4"><Field label="Corrected text"><textarea className="field min-h-28" value={text} onChange={(e) => setText(e.target.value)} /></Field><Field label="Reviewer-assigned speaker label"><input className="field" value={speaker} onChange={(e) => setSpeaker(e.target.value)} /></Field></div><div className="mt-6 flex justify-end gap-2"><button className="button-secondary" onClick={onClose}>Cancel</button><button className="button-primary" disabled={saving || !text.trim()} onClick={async () => { setSaving(true); await onSave(segment.id, text.trim(), speaker.trim() || "Unknown"); setSaving(false); }}>{saving && <LoaderCircle className="animate-spin" size={16} />}Save source correction</button></div></Modal>;
}

function VoiceAddendumModal({ microphoneId, onClose, onSave }: { microphoneId: string; onClose: () => void; onSave: (file: File) => Promise<void> }) {
  const [state, setState] = useState<"ready" | "recording" | "processing">("ready");
  const [elapsed, setElapsed] = useState(0);
  const [level, setLevel] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const recorder = useRef<PcmRecorder | null>(null);
  const frames = useRef<Int16Array[]>([]);
  const startedAt = useRef<number | null>(null);

  useEffect(() => {
    if (state !== "recording") return;
    const timer = window.setInterval(() => {
      if (startedAt.current !== null) setElapsed(Date.now() - startedAt.current);
    }, 100);
    return () => window.clearInterval(timer);
  }, [state]);

  useEffect(() => () => { void recorder.current?.stop(); }, []);

  async function start(): Promise<void> {
    setError(null);
    frames.current = [];
    setElapsed(0);
    const nextRecorder = new PcmRecorder();
    recorder.current = nextRecorder;
    try {
      await nextRecorder.start(
        (frame) => frames.current.push(new Int16Array(frame.pcm)),
        setLevel,
        microphoneId || undefined,
      );
      startedAt.current = Date.now();
      setState("recording");
    } catch (cause) {
      setError(messageFrom(cause));
      setState("ready");
    }
  }

  async function stopAndAdd(): Promise<void> {
    setState("processing");
    setError(null);
    try {
      await recorder.current?.stop();
      const sampleCount = frames.current.reduce((total, frame) => total + frame.length, 0);
      if (sampleCount < 3_200) throw new Error("Record a little more detail before adding the voice note.");
      const file = new File(
        [recordedFramesToWav(frames.current)],
        "voice-addendum.wav",
        { type: "audio/wav" },
      );
      await onSave(file);
    } catch (cause) {
      setError(messageFrom(cause));
      setState("ready");
      recorder.current = null;
    }
  }

  return <Modal title="Add a missing detail by voice" onClose={state === "processing" ? () => undefined : onClose}><p className="text-sm leading-6 text-slate-600">Record the missing sentence. Start with a role when helpful, such as “Nurse, blood was given.” You can review the transcription before generating the report.</p>{error && <p className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}<div className="mt-6 flex min-h-36 flex-col items-center justify-center rounded-2xl border border-slate-200 bg-slate-50 p-5"><div className={`grid size-12 place-items-center rounded-full ${state === "recording" ? "bg-red-100 text-red-600" : "bg-white text-teal-700"}`}><Mic className={state === "recording" ? "animate-pulse" : ""} /></div><p className="mt-3 font-mono text-2xl font-bold tabular-nums text-ink">{formatDuration(elapsed)}</p><p className="mt-1 text-xs text-slate-500">{state === "recording" ? "Recording voice note" : state === "processing" ? "Adding to transcript…" : "Ready when you are"}</p>{state === "recording" && <div className="mt-4"><AudioMeter level={level} /></div>}</div><div className="mt-6 flex justify-end gap-2"><button className="button-secondary" onClick={onClose} disabled={state === "processing"}>Cancel</button>{state === "ready" ? <button className="button-primary" onClick={() => void start()}><Radio size={16} />Start recording</button> : <button className="button-primary !bg-coral hover:!bg-red-600" disabled={state === "processing"} onClick={() => void stopAndAdd()}>{state === "processing" ? <LoaderCircle className="animate-spin" size={16} /> : <CircleStop size={16} />}{state === "processing" ? "Adding…" : "Stop and add"}</button>}</div></Modal>;
}

function ManualEventEditor({ sessionId, segment, onClose, onSave }: { sessionId: string; segment: TranscriptSegment; onClose: () => void; onSave: (event: ClinicalEvent) => void }) {
  const [category, setCategory] = useState<EventCategory>("OTHER"); const [description, setDescription] = useState(""); const [saving, setSaving] = useState(false); const [error, setError] = useState<string | null>(null);
  const evidence = segment.corrected_text || segment.raw_text;
  return <Modal title="Add timeline item" onClose={onClose}>{error && <p className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}<p className="rounded-xl border-l-2 border-teal-400 bg-slate-50 p-3 text-sm italic text-slate-600">“{evidence}”</p><div className="mt-5 grid gap-4 sm:grid-cols-2"><Field label="Category"><select className="field" value={category} onChange={(e) => setCategory(e.target.value as EventCategory)}>{categories.map((item) => <option key={item}>{titleCase(item)}</option>)}</select></Field><Field label="Title"><textarea className="field min-h-24" value={description} onChange={(e) => setDescription(e.target.value)} /></Field></div><div className="mt-6 flex justify-end gap-2"><button className="button-secondary" onClick={onClose}>Cancel</button><button className="button-primary" disabled={saving || !description.trim()} onClick={async () => { setSaving(true); setError(null); try { const event = await api.addManualEvent(sessionId, { category, state: "REPORTED", normalized_action: "reviewer_documented_event", utterance_time_ms: segment.start_ms, description: description.trim(), source_segment_ids: [segment.id], evidence_text: evidence }); onSave(event); } catch (cause) { setError(messageFrom(cause)); } finally { setSaving(false); } }}>{saving && <LoaderCircle className="animate-spin" size={16} />}Add</button></div></Modal>;
}

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) { return <div className="fixed inset-0 z-50 grid place-items-center bg-ink/45 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-label={title} onMouseDown={(event) => { if (event.currentTarget === event.target) onClose(); }}><div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl bg-white p-5 shadow-2xl sm:p-7"><div className="mb-5 flex items-center justify-between"><h2 className="font-display text-2xl font-semibold text-ink">{title}</h2><button className="button-ghost !p-2" onClick={onClose} aria-label="Close dialog"><X size={18} /></button></div>{children}</div></div>; }
function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label className="block text-sm font-bold text-ink">{label}<span className="mt-2 block font-normal">{children}</span></label>; }
function Empty({ icon: Icon, title, copy }: { icon: React.ElementType; title: string; copy: string }) { return <div className="grid min-h-48 place-items-center text-center"><div><Icon className="mx-auto text-slate-300" size={28} /><p className="mt-3 text-sm font-bold text-slate-500">{title}</p><p className="mt-1 max-w-52 text-xs leading-5 text-slate-400">{copy}</p></div></div>; }

async function connectSocket(sessionId: string, onMessage: (event: MessageEvent<string>) => void): Promise<WebSocket> {
  const url = new URL(WS_URL);
  url.pathname = `/ws/sessions/${sessionId}/audio`;
  url.search = "";
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(url);
    socket.binaryType = "arraybuffer";
    socket.onmessage = onMessage;
    socket.onopen = () => resolve(socket);
    socket.onerror = () => reject(new Error("Could not connect to the local audio service."));
  });
}

function messageFrom(cause: unknown): string {
  if (cause instanceof ApiError || cause instanceof Error) return cause.message;
  return "An unexpected local error occurred.";
}

function dedupeById<T extends { id: string }>(items: T[]): T[] { return [...new Map(items.map((item) => [item.id, item])).values()].sort((a, b) => ("start_ms" in a && "start_ms" in b ? Number(a.start_ms) - Number(b.start_ms) : "utterance_time_ms" in a && "utterance_time_ms" in b ? Number(a.utterance_time_ms) - Number(b.utterance_time_ms) : 0)); }

