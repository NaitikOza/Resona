import type { EventCategory } from "@/lib/types";
import { titleCase } from "@/lib/format";

export interface TimelineGraphItem {
  id: string;
  speech_time: string;
  speech_time_ms: number;
  category: EventCategory;
  summary: string;
  evidence: string;
  speaker?: string;
}

const categoryStyles: Record<EventCategory, { dot: string; badge: string }> = {
  OBSERVATION: { dot: "bg-sky-600 ring-sky-100", badge: "bg-sky-50 text-sky-700" },
  MEASUREMENT: { dot: "bg-violet-600 ring-violet-100", badge: "bg-violet-50 text-violet-700" },
  PROCEDURE: { dot: "bg-teal-600 ring-teal-100", badge: "bg-teal-50 text-teal-700" },
  MEDICATION: { dot: "bg-rose-600 ring-rose-100", badge: "bg-rose-50 text-rose-700" },
  FLUID_OR_BLOOD_PRODUCT: { dot: "bg-red-600 ring-red-100", badge: "bg-red-50 text-red-700" },
  IMAGING_OR_TEST: { dot: "bg-indigo-600 ring-indigo-100", badge: "bg-indigo-50 text-indigo-700" },
  CONSULT_OR_COMMUNICATION: { dot: "bg-amber-600 ring-amber-100", badge: "bg-amber-50 text-amber-700" },
  EQUIPMENT: { dot: "bg-cyan-600 ring-cyan-100", badge: "bg-cyan-50 text-cyan-700" },
  OTHER: { dot: "bg-slate-600 ring-slate-100", badge: "bg-slate-100 text-slate-700" },
};

export function TimelineGraph({ items }: { items: TimelineGraphItem[] }) {
  if (!items.length) {
    return <div className="rounded-2xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">No timeline items yet.</div>;
  }

  return (
    <div className="overflow-x-auto pb-3" aria-label="Chronological event map">
      <div className="relative pt-1" style={{ minWidth: `${Math.max(720, items.length * 210)}px` }}>
        <span className="absolute left-[9%] right-[9%] top-[19px] h-0.5 bg-gradient-to-r from-teal-200 via-teal-500 to-teal-200" aria-hidden="true" />
        <ol className="grid gap-0" style={{ gridTemplateColumns: `repeat(${items.length}, minmax(190px, 1fr))` }}>
          {items.map((item, index) => {
            const styles = categoryStyles[item.category];
            return (
              <li key={item.id} className="relative px-2 pt-11">
                <span className={`absolute left-1/2 top-3 size-4 -translate-x-1/2 rounded-full ring-4 ${styles.dot}`} aria-hidden="true" />
                <article className="h-full rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-xs font-bold text-teal-800">{item.speech_time}</span>
                    <span className="text-[10px] font-semibold text-slate-400">{index + 1}</span>
                  </div>
                  <p className="mt-3 text-sm font-bold leading-5 text-ink">{item.summary}</p>
                  <span className={`mt-3 inline-flex rounded-full px-2 py-1 text-[9px] font-bold uppercase tracking-wide ${styles.badge}`}>{titleCase(item.category)}</span>
                  {item.speaker && item.speaker !== "Unknown" && <p className="mt-3 text-xs font-semibold text-slate-500">{item.speaker}</p>}
                  <p className="mt-2 line-clamp-3 text-xs italic leading-5 text-slate-500">“{item.evidence}”</p>
                </article>
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}
