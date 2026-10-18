import { expect, test } from "@playwright/test";

const uploadAudioPath = process.env.RESONA_UPLOAD_AUDIO;

test("ordinary MP3 audio is prepared locally and transcribed", async ({ page, request }) => {
  test.skip(!uploadAudioPath, "Set RESONA_UPLOAD_AUDIO to an MP3 file to run this check.");
  let sessionId: string | undefined;
  try {
    await page.goto("/simulation");
    await page.getByRole("button", { name: "Upload audio" }).click();
    await page.locator('input[type="file"]').setInputFiles(uploadAudioPath!);
    await expect(page.getByText(/\.mp3$/i)).toBeVisible();

    const createdResponse = page.waitForResponse(
      (response) => response.url().endsWith("/api/sessions") && response.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Transcribe audio" }).click();
    const created = await (await createdResponse).json();
    sessionId = created.data.id;

    await expect(page.getByRole("heading", { name: "Review your record." })).toBeVisible({
      timeout: 120_000,
    });
    await expect(page.getByText(/hola shalom/i)).toBeVisible();
    await expect(page.locator("audio").first()).toBeVisible();
  } finally {
    if (sessionId) await request.delete(`http://127.0.0.1:8000/api/sessions/${sessionId}`);
  }
});
