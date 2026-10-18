import type { Metadata } from "next";
import Link from "next/link";
import { Activity } from "lucide-react";
import "./globals.css";

export const metadata: Metadata = {
  title: "Resona — Emergency documentation",
  description:
    "Turn emergency-care conversations into clear transcripts, timelines, and reports.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <header className="no-print border-b border-slate-200/80 bg-white/85 backdrop-blur-xl">
          <div className="mx-auto flex h-16 max-w-[1440px] items-center justify-between px-5 lg:px-8">
            <Link href="/" className="flex items-center gap-2.5 font-bold tracking-tight text-ink">
              <span className="grid size-9 place-items-center rounded-xl bg-ink text-white">
                <Activity size={19} aria-hidden="true" />
              </span>
              <span className="text-lg">Resona</span>
            </Link>
            <nav className="flex items-center gap-1" aria-label="Primary navigation">
              <Link className="button-ghost hidden sm:inline-flex" href="/#how-it-works">How it works</Link>
              <Link className="button-ghost" href="/library">Library</Link>
              <a className="button-primary !px-4 !py-2.5" href="/simulation">New session</a>
            </nav>
          </div>
        </header>
        {children}
        <footer className="no-print border-t border-slate-200 bg-white">
          <div className="mx-auto max-w-[1440px] px-5 py-7 text-xs text-slate-500 lg:px-8">Resona · Clear documentation from spoken care.</div>
        </footer>
      </body>
    </html>
  );
}

