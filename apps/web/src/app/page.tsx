import Link from "next/link";
import { ArrowRight, FileCheck2, Mic2, ScanSearch, Sparkles } from "lucide-react";

const steps = [
  {
    icon: Mic2,
    title: "Record or upload",
    copy: "Speak into your microphone or choose a WAV or MP3 file.",
  },
  {
    icon: ScanSearch,
    title: "See the key moments",
    copy: "Resona separates speakers and builds a clear chronological timeline.",
  },
  {
    icon: FileCheck2,
    title: "Review and export",
    copy: "Edit anything you need, then export a visual event map and report.",
  },
];

const previewStates = {
  REQUESTED: { label: "Requested", className: "border-yellow-200 bg-yellow-50 text-yellow-800" },
  IN_PROGRESS: { label: "In progress", className: "border-sky-200 bg-sky-50 text-sky-800" },
  COMPLETED: { label: "Completed", className: "border-teal-200 bg-teal-50 text-teal-800" },
};

export default function HomePage() {
  return (
    <main>
      <section className="relative overflow-hidden border-b border-slate-200">
        <div className="absolute inset-0 -z-10 bg-[linear-gradient(110deg,rgba(239,252,249,0.85),rgba(247,250,249,0.5)_55%,rgba(255,247,237,0.65))]" />
        <div className="mx-auto grid max-w-[1440px] gap-14 px-5 py-20 lg:grid-cols-[1fr_0.92fr] lg:px-8 lg:py-28">
          <div className="max-w-3xl self-center">
            <div className="mb-7 inline-flex items-center gap-2 rounded-full border border-teal-200 bg-white/80 px-3 py-1.5 text-xs font-semibold text-teal-800 shadow-sm">
              <Sparkles size={14} aria-hidden="true" /> AI-powered emergency documentation
            </div>
            <h1 className="font-display text-5xl font-semibold leading-[1.03] tracking-[-0.035em] text-ink sm:text-6xl lg:text-7xl">
              Turn spoken care into a <span className="text-teal-700">clear record.</span>
            </h1>
            <p className="mt-7 max-w-2xl text-lg leading-8 text-slate-600 sm:text-xl">
              Resona transcribes emergency-care conversations, organizes the key moments, and creates a report you can review and export.
            </p>
            <div className="mt-9 flex flex-col gap-3 sm:flex-row">
              <Link className="button-primary !px-6 !py-3.5" href="/simulation">
                Start a session <ArrowRight size={17} aria-hidden="true" />
              </Link>
              <Link className="button-secondary !px-6 !py-3.5" href="/simulation?mode=sample">
                Open sample case
              </Link>
              <Link className="button-ghost !px-6 !py-3.5" href="/library">
                View library
              </Link>
            </div>
          </div>

          <div className="relative mx-auto w-full max-w-2xl self-center">
            <div className="absolute -inset-8 -z-10 rounded-full bg-teal-200/30 blur-3xl" />
            <div className="overflow-hidden rounded-[28px] border border-white/80 bg-white shadow-soft">
              <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
                <div>
                  <p className="text-xs font-semibold text-slate-500">FICTIONAL SIMULATION</p>
                  <p className="mt-1 font-semibold text-ink">Documentation preview</p>
                </div>
                <span className="status-pill border-slate-200 bg-slate-50 text-slate-600">Sample</span>
              </div>
              <div className="grid gap-0 md:grid-cols-2">
                <div className="border-b border-slate-200 p-5 md:border-b-0 md:border-r">
                  <span className="eyebrow">Transcript</span>
                  <div className="mt-5 space-y-4 text-sm leading-6 text-slate-600">
                    <p>Can somebody get an IV?</p>
                    <p className="rounded-lg bg-teal-50 p-3 text-ink">Starting the IV now.</p>
                    <p>IV is established.</p>
                  </div>
                </div>
                <div className="bg-slate-50/70 p-5">
                  <span className="eyebrow">Timeline</span>
                  <div className="mt-5 space-y-3">
                    <TimelinePreview time="00:04" text="IV access" state="REQUESTED" />
                    <TimelinePreview time="00:09" text="IV access" state="IN_PROGRESS" />
                    <TimelinePreview time="00:15" text="IV access" state="COMPLETED" />
                  </div>
                </div>
              </div>
              <p className="border-t border-slate-200 px-5 py-3 text-xs text-slate-500">Illustrative events · Unverified until reviewed</p>
            </div>
          </div>
        </div>
      </section>

      <section id="how-it-works" className="mx-auto max-w-[1200px] px-5 py-24 lg:px-8">
        <div className="mx-auto max-w-2xl text-center">
          <p className="eyebrow">How it works</p>
          <h2 className="mt-4 font-display text-4xl font-semibold tracking-tight text-ink sm:text-5xl">Simple from start to finish.</h2>
        </div>
        <div className="mt-14 grid gap-5 md:grid-cols-3">
          {steps.map(({ icon: Icon, title, copy }, index) => (
            <article key={title} className="panel p-7">
              <div className="flex items-center justify-between"><span className="grid size-11 place-items-center rounded-xl bg-teal-50 text-teal-700"><Icon size={21} /></span><span className="font-display text-3xl text-slate-200">0{index + 1}</span></div>
              <h3 className="mt-7 text-lg font-bold text-ink">{title}</h3>
              <p className="mt-3 text-sm leading-6 text-slate-600">{copy}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="border-t border-slate-200 bg-slate-50 px-5 py-20 text-center">
        <h2 className="font-display text-4xl font-semibold text-ink">Ready to begin?</h2>
        <p className="mx-auto mt-4 max-w-xl text-slate-600">Use your microphone, upload audio, or explore the sample case.</p>
        <Link className="button-primary mt-8" href="/simulation">Open Resona <ArrowRight size={17} /></Link>
      </section>
    </main>
  );
}

function TimelinePreview({ time, text, state }: { time: string; text: string; state: keyof typeof previewStates }) {
  const { label, className } = previewStates[state];

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-mono text-[11px] text-slate-500">{time}</span>
        <span className={`status-pill ${className}`}>{label}</span>
      </div>
      <p className="mt-2 text-sm font-semibold text-ink">{text}</p>
    </div>
  );
}
