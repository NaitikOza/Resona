import { expect, test } from "@playwright/test";

test("patient folder opens its saved event timeline", async ({ page, request }) => {
  const created = await request.post("http://127.0.0.1:8000/api/sessions", {
    data: { case_label: "Patient Alpha", mode: "SAMPLE_SCENARIO" },
  });
  expect(created.ok()).toBe(true);
  const session = (await created.json()).data as { id: string };

  try {
    const loaded = await request.post(`http://127.0.0.1:8000/api/sessions/${session.id}/sample/01-closed-loop-iv`);
    expect(loaded.ok()).toBe(true);

    await page.goto("/library");
    await expect(page.getByRole("heading", { name: "Patient timelines." })).toBeVisible();
    await page.getByRole("button", { name: /Patient Alpha/ }).click();
    await expect(page.getByRole("heading", { name: "Patient Alpha" })).toBeVisible();
    await expect(page.getByLabel("Chronological event map")).toBeVisible();
    await expect(page.getByText("IV access", { exact: true }).first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "Source conversation" })).toBeVisible();
  } finally {
    await request.delete(`http://127.0.0.1:8000/api/sessions/${session.id}`);
  }
});
