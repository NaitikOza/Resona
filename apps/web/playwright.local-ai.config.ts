import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

const audioPath = process.env.RESONA_FAKE_AUDIO;

if (!audioPath) {
  throw new Error("Set RESONA_FAKE_AUDIO to an absolute mono PCM WAV path.");
}

export default defineConfig({
  testDir: "./e2e-local-ai",
  fullyParallel: false,
  retries: 0,
  timeout: 180_000,
  use: {
    ...devices["Desktop Chrome"],
    baseURL: "http://127.0.0.1:3000",
    permissions: ["microphone"],
    launchOptions: {
      args: [
        "--use-fake-ui-for-media-stream",
        "--use-fake-device-for-media-stream",
        `--use-file-for-fake-audio-capture=${path.resolve(audioPath)}`,
      ],
    },
  },
  webServer: [
    {
      command: "cd ../api && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000",
      url: "http://127.0.0.1:8000/api/health",
      reuseExistingServer: true,
    },
    {
      command: "pnpm dev --hostname 127.0.0.1",
      url: "http://127.0.0.1:3000",
      reuseExistingServer: true,
    },
  ],
  projects: [{ name: "chromium-local-ai" }],
});
