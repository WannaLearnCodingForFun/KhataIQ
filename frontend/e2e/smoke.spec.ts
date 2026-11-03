import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

// Seeded by scripts/seed_dev.py.
const PASSWORD = "khataiq-dev-password";
const OWNER = "owner1@demo.khataiq.dev";
const OFFICER = "officer1@demo.khataiq.dev";
const STATEMENT = path.join(__dirname, "fixtures", "october.csv");

async function signIn(page: Page, email: string) {
  // After "Sign out" the app is already redirecting to /login; navigating again would race it.
  if (!page.url().endsWith("/login")) await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Businesses" })).toBeVisible();
}

test("owner uploads a statement, sees metrics; officer resolves the flag it raised", async ({ page }) => {
  // Owner: upload a statement and watch the pipeline finish.
  await signIn(page, OWNER);
  await page.getByRole("link", { name: "Sharma Kirana Store" }).click();
  await page.getByRole("link", { name: "Upload statement" }).click();
  await page.getByLabel("Statement file").setInputFiles(STATEMENT);
  await expect(page.getByText(/Upload #\d+/)).toBeVisible();
  await expect(page.getByText("processed", { exact: true }).first()).toBeVisible({ timeout: 60_000 });

  // Metrics: October appears with its net business inflow.
  await page.getByRole("link", { name: "Back to overview" }).click();
  const october = page.getByRole("row", { name: /Oct 2026/ });
  await expect(october).toBeVisible();
  await expect(october).toContainText("₹");

  // Officer: the round trip through RAVI TRADERS is in the review queue; dismiss it with a note.
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.waitForURL("**/login");
  await expect(page.getByLabel("Email")).toBeVisible();
  await signIn(page, OFFICER);
  await page.getByRole("link", { name: "Review queue" }).click();
  const flag = page.getByRole("button", { name: /RAVI TRADERS/ });
  await expect(flag).toBeVisible();
  await flag.click();
  const drawer = page.getByRole("dialog");
  await expect(drawer.getByRole("button", { name: "Dismiss" })).toBeDisabled();
  await drawer.getByLabel("Note (required)").fill("Advance returned by supplier; invoice on file.");
  await drawer.getByRole("button", { name: "Dismiss" }).click();
  await expect(page.getByText("Nothing here.")).toBeVisible();
});
