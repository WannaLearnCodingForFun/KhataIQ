import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

// Captures the README screenshots. Run with demo data:
//   E2E_DEMO_DATA=1 scripts/e2e.sh screenshots.spec.ts
test.skip(!process.env.E2E_DEMO_DATA, "needs E2E_DEMO_DATA=1");

const OUT = path.join(__dirname, "..", "..", "docs", "screenshots");
const PASSWORD = "khataiq-dev-password";

async function signIn(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Businesses" })).toBeVisible();
}

test.use({ viewport: { width: 1360, height: 900 } });

test("screenshots", async ({ page }) => {
  await signIn(page, "officer1@demo.khataiq.dev");
  await page.goto("/businesses/1");
  await expect(page.getByRole("row", { name: /Oct 2026/ })).toBeVisible();
  await page.waitForTimeout(800); // let the chart animate in
  await page.screenshot({ path: path.join(OUT, "overview.png"), fullPage: true });

  await page.goto("/businesses/1/transactions");
  await expect(page.getByRole("table", { name: "Transactions" })).toBeVisible();
  await page.getByLabel("Evidence").selectOption("verified");
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(OUT, "transactions.png") });

  await page.goto("/flags");
  const first = page.locator("ul button").first();
  await expect(first).toBeVisible();
  await first.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.screenshot({ path: path.join(OUT, "review-queue.png") });

  await page.goto("/businesses/1/evidence?from=2026-08-01&to=2026-08-30");
  await page.getByLabel("From").fill("2026-08-01");
  await page.getByLabel("To").fill("2026-08-30");
  await page.waitForTimeout(2_500); // cytoscape layout
  await page.screenshot({ path: path.join(OUT, "evidence-graph.png") });
});
