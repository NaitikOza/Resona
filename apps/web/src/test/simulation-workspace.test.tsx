import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SimulationWorkspace } from "@/components/simulation-workspace";

const getUserMedia = vi.fn();
const apiMocks = vi.hoisted(() => ({
  health: vi.fn(),
  scenarios: vi.fn(),
  createSession: vi.fn(),
  loadSample: vi.fn(),
  getSession: vi.fn(),
  transcript: vi.fn(),
  events: vi.fn(),
  reviewItems: vi.fn(),
}));

vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams() }));
vi.mock("@/lib/api", async () => {
  const original = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...original,
    api: {
      ...original.api,
      health: apiMocks.health,
      scenarios: apiMocks.scenarios,
      createSession: apiMocks.createSession,
      loadSample: apiMocks.loadSample,
      getSession: apiMocks.getSession,
      transcript: apiMocks.transcript,
      events: apiMocks.events,
      reviewItems: apiMocks.reviewItems,
    },
  };
});

const session = {
  id: "session-1",
  case_label: "Emergency Case",
  mode: "SAMPLE_SCENARIO" as const,
  status: "READY_FOR_REVIEW" as const,
  created_at: new Date().toISOString(),
  started_at: null,
  ended_at: new Date().toISOString(),
  simulation_flag: true,
  consent_recorded: false,
  model_versions: { extraction: "rules-v1" },
  duration_ms: 6000,
  revision: 2,
};

describe("SimulationWorkspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia } });
    apiMocks.health.mockResolvedValue({ status: "ok", scope: "documentation", asr: { available: true, engine: "whisper.cpp", model_path: null, detail: "Ready" }, rules_engine: "ready" });
    apiMocks.scenarios.mockResolvedValue([{ slug: "02-blood-request-only", title: "Blood preparation", description: "Test", duration_ms: 6000, simulated: true }]);
    apiMocks.createSession.mockResolvedValue(session);
    apiMocks.loadSample.mockResolvedValue({ session });
    apiMocks.getSession.mockResolvedValue(session);
    apiMocks.transcript.mockResolvedValue([]);
    apiMocks.events.mockResolvedValue([]);
    apiMocks.reviewItems.mockResolvedValue([]);
  });

  it("does not request microphone access on render", async () => {
    render(<SimulationWorkspace />);
    await screen.findByText("Choose how to begin.");
    expect(getUserMedia).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /start recording/i })).toBeEnabled();
  });

  it("requests permission only after the explicit device-test action", async () => {
    const stop = vi.fn();
    getUserMedia.mockResolvedValue({ getAudioTracks: () => [{ label: "Test microphone" }], getTracks: () => [{ stop }] });
    render(<SimulationWorkspace />);
    await userEvent.click(await screen.findByRole("button", { name: /device test/i }));
    await waitFor(() => expect(getUserMedia).toHaveBeenCalledTimes(1));
    expect(stop).toHaveBeenCalled();
  });

  it("runs the curated sample into the review workspace", async () => {
    render(<SimulationWorkspace />);
    await userEvent.click(await screen.findByRole("button", { name: /sample case/i }));
    await userEvent.click(screen.getByRole("button", { name: /open sample case/i }));
    expect(await screen.findByText("Review your record.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add by voice/i })).toBeEnabled();
    expect(apiMocks.createSession).toHaveBeenCalledWith("Emergency Case", "SAMPLE_SCENARIO");
    expect(apiMocks.loadSample).toHaveBeenCalledWith("session-1", "02-blood-request-only");
  });
});

