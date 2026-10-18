import { expect, test } from "@playwright/test";

test("curated scenario flows through review and report export", async ({ page, request }) => {
  test.setTimeout(60_000);
  await page.addInitScript(() => {
    Object.defineProperty(window, "speechSynthesis", {
      configurable: true,
      value: {
        cancel: () => undefined,
        speak: (utterance: SpeechSynthesisUtterance) => {
          document.documentElement.dataset.spokenText = utterance.text;
        },
      },
    });
  });
  await page.goto("/simulation?mode=sample");
  await expect(page.getByRole("heading", { name: "Choose how to begin." })).toBeVisible();
  const createdResponse = page.waitForResponse(
    (response) => response.url().endsWith("/api/sessions") && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Open sample case" }).click();
  const sessionId = (await (await createdResponse).json()).data.id as string;
  await expect(page.getByRole("heading", { name: "Review your record." })).toBeVisible();
  await expect(page.getByText(/ASR confidence/i)).toHaveCount(0);
  await expect(page.getByText(/Requested|In Progress|Uncertain/, { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Add by voice" }).click();
  await expect(page.getByRole("dialog", { name: "Add a missing detail by voice" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Start recording" })).toBeVisible();
  await page.getByRole("button", { name: "Close dialog" }).click();
  const playAudio = page.getByRole("button", { name: "Play transcript audio" }).first();
  await expect(playAudio).toBeVisible();
  await playAudio.click();
  await expect(page.locator("html")).toHaveAttribute("data-spoken-text", /blood/i);

  const acceptButtons = page.getByRole("button", { name: "Keep", exact: true });
  const count = await acceptButtons.count();
  for (let index = 0; index < count; index += 1) {
    await acceptButtons.first().click();
    await expect(page.getByRole("button", { name: "Kept", exact: true })).toHaveCount(index + 1);
  }
  await expect(page.getByRole("button", { name: "Kept", exact: true })).toHaveCount(count);

  await page.getByRole("button", { name: "Generate report" }).click();
  await expect(page.getByRole("heading", { name: "Resona — Emergency Documentation Report" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Handoff summary" })).toBeVisible();
  await expect(page.getByText(/emergency handoff.*blood request/i)).toBeVisible();
  await page.getByRole("button", { name: "Copy summary" }).click();
  await expect(page.getByRole("button", { name: "Copied" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Emergency record check" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Event map" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Session feedback" })).toBeVisible();
  await expect(page.getByText("What went well", { exact: true })).toBeVisible();
  await expect(page.getByText("Improve next time", { exact: true })).toBeVisible();
  await expect(page.getByText("What was missed", { exact: true })).toBeVisible();
  await expect(page.getByText(/requested blood arrives/i)).toBeVisible();
  await expect(page.getByText(/transfusion start/i).last()).toBeVisible();
  await expect(page.getByLabel("Chronological event map")).toBeVisible();
  await expect(page.getByText(/prototype|fictional|methodology|documentation questions/i)).toHaveCount(0);
  await expect(page.getByRole("link", { name: "JSON" })).toHaveAttribute("href", /format=json/);
  await expect(page.getByRole("link", { name: "CSV" })).toHaveAttribute("href", /format=csv/);
  await expect(page.getByRole("link", { name: "HTML" })).toHaveAttribute("href", /format=html/);

  await page.getByRole("link", { name: "New session" }).click();
  await expect(page.getByRole("heading", { name: "Choose how to begin." })).toBeVisible();
  await expect(page.getByRole("button", { name: "Start recording" })).toBeVisible();
  await request.delete(`http://127.0.0.1:8000/api/sessions/${sessionId}`);
});

