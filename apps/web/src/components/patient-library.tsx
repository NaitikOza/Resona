"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  CalendarDays,
  ChevronRight,
  Clock3,
  FileText,
  Folder,
  LoaderCircle,
  Search,
  Users,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { eventTitle } from "@/lib/events";
import { formatDuration } from "@/lib/format";
import type { ClinicalEvent, Session, TranscriptSegment } from "@/lib/types";
import { TimelineGraph, type TimelineGraphItem } from "@/components/timeline-graph";

interface PatientFolder {
  key: string;
  name: string;
  sessions: Session[];
}

export function PatientLibrary() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null);
  const [selectedSession, setSelectedSession] = useState<string | null>(null);
  const [events, setEvents] = useState<ClinicalEvent[]>([]);
  const [segments, setSegments] = useState<TranscriptSegment[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingRecord, setLoadingRecord] = useState(false);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.sessions()
      .then(setSessions)
      .catch((cause: unknown) => setError(messageFrom(cause)))
      .finally(() => setLoading(false));
  }, []);

  const folders = useMemo(() => {
    const grouped = new Map<string, PatientFolder>();
    for (const session of sessions.filter((item) => item.status === "READY_FOR_REVIEW" || item.status === "COMPLETED")) {
      const name = displayPatientName(session.case_label);
      const key = name.toLocaleLowerCase();
      const current = grouped.get(key) ?? { key, name, sessions: [] };
      current.sessions.push(session);
      grouped.set(key, current);
    }
    return [...grouped.values()]
      .map((folder) => ({ ...folder, sessions: folder.sessions.sort((a, b) => b.created_at.localeCompare(a.created_at)) }))
      .filter((folder) => folder.name.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [query, sessions]);

  const activeFolder = folders.find((folder) => folder.key === selectedFolder) ?? null;
  const activeSession = sessions.find((session) => session.id === selectedSession) ?? null;

  async function openSession(session: Session): Promise<void> {
    setSelectedSession(session.id);
    setLoadingRecord(true);
    setError(null);
    try {
      const [nextEvents, nextSegments] = await Promise.all([
        api.events(session.id),
        api.transcript(session.id),
      ]);
      setEvents(nextEvents.filter((event) => event.reviewer_status !== "REJECTED"));
      setSegments(nextSegments);
    } catch (cause: unknown) {
      setError(messageFrom(cause));
    } finally {
      setLoadingRecord(false);
    }
  }

  function openFolder(folder: PatientFolder): void {
    setSelectedFolder(folder.key);
    setEvents([]);
    setSegments([]);
    const latest = folder.sessions[0];
    if (latest) void openSession(latest);
  }

  const graphItems: TimelineGraphItem[] = events.map((event) => {
    const segment = segments.find((item) => event.source_segment_ids.includes(item.id));
    return {
      id: event.id,
      speech_time: formatDuration(event.utterance_time_ms),
      speech_time_ms: event.utterance_time_ms,
      category: event.category,
      summary: eventTitle(event),
      evidence: event.evidence_text,
      speaker: segment?.speaker_label,
    };
  });

  return (
    <main className="mx-auto min-h-[calc(100vh-8rem)] max-w-[1440px] px-5 py-9 lg:px-8">
      <div className="flex flex-col justify-between gap-5 lg:flex-row lg:items-end">
        <div>
          <p className="eyebrow">Library</p>
          <h1 className="mt-3 font-display text-4xl font-semibold tracking-tight text-ink sm:text-5xl">Patient timelines.</h1>
          <p className="mt-3 max-w-2xl text-slate-600">Open a patient folder to revisit past sessions, speakers, and documented events.</p>
        </div>
        <Link className="button-primary" href="/simulation">New session</Link>
      </div>

      {error && <div className="mt-6 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">{error}</div>}

      <div className="mt-8 grid gap-5 lg:grid-cols-[320px_minmax(0,1fr)]">
        <aside className="panel overflow-hidden">
          <div className="border-b border-slate-200 p-4">
            <label className="relative block">
              <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
              <span className="sr-only">Search patients</span>
              <input className="field !py-2.5 !pl-9" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search patients" />
            </label>
          </div>
          <div className="max-h-[680px] space-y-2 overflow-y-auto p-3">
            {loading ? <div className="grid min-h-48 place-items-center"><LoaderCircle className="animate-spin text-teal-700" /></div> : folders.length ? folders.map((folder) => (
              <button
                key={folder.key}
                className={`flex w-full items-center gap-3 rounded-xl border p-3 text-left transition ${selectedFolder === folder.key ? "border-teal-400 bg-teal-50" : "border-transparent hover:border-slate-200 hover:bg-slate-50"}`}
                onClick={() => openFolder(folder)}
              >
                <span className={`grid size-10 shrink-0 place-items-center rounded-xl ${selectedFolder === folder.key ? "bg-teal-700 text-white" : "bg-slate-100 text-slate-500"}`}><Folder size={19} /></span>
                <span className="min-w-0 flex-1"><span className="block truncate text-sm font-bold text-ink">{folder.name}</span><span className="mt-0.5 block text-xs text-slate-500">{folder.sessions.length} {folder.sessions.length === 1 ? "session" : "sessions"}</span></span>
                <ChevronRight size={16} className="text-slate-400" />
              </button>
            )) : <div className="grid min-h-48 place-items-center px-5 text-center"><div><Users className="mx-auto text-slate-300" /><p className="mt-3 text-sm font-bold text-slate-500">No patient folders</p><p className="mt-1 text-xs leading-5 text-slate-400">Completed sessions will appear here.</p></div></div>}
          </div>
        </aside>

        <section className="min-w-0">
          {!activeSession ? (
            <div className="panel grid min-h-[520px] place-items-center p-8 text-center"><div><Folder className="mx-auto text-slate-300" size={34} /><h2 className="mt-4 font-display text-2xl font-semibold text-ink">Choose a patient folder</h2><p className="mt-2 text-sm text-slate-500">Their latest timeline will open here.</p></div></div>
          ) : (
            <div className="space-y-5">
              <div className="panel p-5 sm:p-6">
                <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-start">
                  <div><p className="eyebrow">Patient folder</p><h2 className="mt-2 font-display text-3xl font-semibold text-ink">{displayPatientName(activeSession.case_label)}</h2><div className="mt-3 flex flex-wrap gap-4 text-xs text-slate-500"><span className="inline-flex items-center gap-1.5"><CalendarDays size={14} />{new Date(activeSession.created_at).toLocaleString()}</span><span className="inline-flex items-center gap-1.5"><Clock3 size={14} />{formatDuration(activeSession.duration_ms)}</span><span className="inline-flex items-center gap-1.5"><FileText size={14} />{events.length} events</span></div></div>
                  {activeFolder && activeFolder.sessions.length > 1 && <label className="text-xs font-bold text-ink">Session<select className="field mt-2 min-w-56" value={activeSession.id} onChange={(event) => { const next = sessions.find((item) => item.id === event.target.value); if (next) void openSession(next); }}>{activeFolder.sessions.map((item) => <option key={item.id} value={item.id}>{new Date(item.created_at).toLocaleString()}</option>)}</select></label>}
                </div>
              </div>

              <div className="panel p-5 sm:p-6">
                <div><p className="eyebrow">Event map</p><h3 className="mt-2 font-display text-2xl font-semibold text-ink">Documented sequence</h3></div>
                <div className="mt-5">{loadingRecord ? <div className="grid min-h-48 place-items-center"><LoaderCircle className="animate-spin text-teal-700" /></div> : <TimelineGraph items={graphItems} />}</div>
              </div>

              {!loadingRecord && segments.length > 0 && <div className="panel overflow-hidden"><div className="border-b border-slate-200 p-5"><p className="eyebrow">Transcript</p><h3 className="mt-2 font-display text-2xl font-semibold text-ink">Source conversation</h3></div><div className="max-h-[440px] divide-y divide-slate-100 overflow-y-auto">{segments.map((segment) => <article key={segment.id} className="grid gap-2 p-4 sm:grid-cols-[90px_120px_1fr]"><span className="font-mono text-xs font-bold text-teal-700">{formatDuration(segment.start_ms)}</span><span className="text-xs font-semibold text-slate-500">{segment.speaker_label}</span><p className="text-sm leading-6 text-ink">{segment.corrected_text || segment.raw_text}</p></article>)}</div></div>}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}

function messageFrom(cause: unknown): string {
  if (cause instanceof ApiError || cause instanceof Error) return cause.message;
  return "The patient library could not be loaded.";
}

function displayPatientName(value: string): string {
  return value.replace(/\bfictional\b/gi, "").replace(/\s+/g, " ").trim() || "Patient";
}
