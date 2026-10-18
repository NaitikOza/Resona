import { expect, test } from "@playwright/test";

test("browser microphone audio reaches local ASR and evidence timeline", async ({ page, request }) => {
  let sessionId: string | undefined;
  try {
    await page.goto("/simulation");
    await expect(page.getByRole("button", { name: "Device test" })).toBeVisible();

    const createdResponse = page.waitForResponse(
      (response) => response.url().endsWith("/api/sessions") && response.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Start recording" }).click();
    const created = await (await createdResponse).json();
    sessionId = created.data.id;

    await expect(page.getByRole("button", { name: "Finish" })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/^00:0[1-9]$/)).toBeVisible({ timeout: 4_000 });
    await expect(page.getByText(/blood pressure is 90 over 60/i).first()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/^00:1[1-9]$/)).toBeVisible({ timeout: 20_000 });

    await page.getByRole("button", { name: "Finish" }).click();
    await expect(page.getByRole("heading", { name: "Review your record." })).toBeVisible({
      timeout: 120_000,
    });
    const eventPayload = await (await request.get(`http://127.0.0.1:8000/api/sessions/${sessionId}/events`)).json();
    expect(eventPayload.data.some((event: { normalized_action: string; state: string }) => event.normalized_action === "establish_iv_access" && event.state === "COMPLETED")).toBe(true);
    expect(eventPayload.data.some((event: { normalized_action: string; state: string }) => event.normalized_action.includes("blood") && event.state === "COMPLETED")).toBe(false);
    const transcriptPayload = await (await request.get(`http://127.0.0.1:8000/api/sessions/${sessionId}/transcript`)).json();
    const transcript = transcriptPayload.data.map((segment: { raw_text: string }) => segment.raw_text);
    const fullTranscript = transcript.join(" ");
    expect(fullTranscript).toMatch(/blood pressure is 90 over 60/i);
    expect(fullTranscript).toMatch(/can somebody get an IV/i);
    expect(fullTranscript).toMatch(/starting the IV now/i);
    expect(fullTranscript).toMatch(/IV is established/i);
    expect(fullTranscript).toMatch(/prepare (two|2) units of blood/i);
    expect(fullTranscript).toMatch(/did the blood arrive/i);
    expect(transcript).not.toContain("an IV?");
    expect(transcript).not.toContain("units of");
  } finally {
    if (sessionId) await request.delete(`http://127.0.0.1:8000/api/sessions/${sessionId}`);
  }
});
