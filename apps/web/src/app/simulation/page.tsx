import { Suspense } from "react";
import { SimulationWorkspace } from "@/components/simulation-workspace";

export default function SimulationPage() {
  return (
    <Suspense fallback={<div className="mx-auto min-h-[70vh] max-w-[1440px] px-5 py-10 text-sm text-slate-500">Loading local workspace…</div>}>
      <SimulationWorkspace />
    </Suspense>
  );
}

