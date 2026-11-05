import assert from "node:assert/strict";
import fs from "node:fs/promises";
import { chromium } from "playwright";

const browser = await chromium.launch({ channel: "msedge", headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: "en-US" });
const page = await context.newPage();
const errors = [];
const report = { tested_at: new Date().toISOString(), checks: [], answers: [] };
page.on("pageerror", (error) => errors.push(error.message));
page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
page.setDefaultTimeout(90000);

function passed(check, details) {
  report.checks.push({ check, passed: true, details });
  console.log("PASS", check);
}

async function ask(question) {
  const previous = await page.locator(".chat-message.assistant").count();
  await page.locator("#chat-input").fill(question);
  const responsePromise = page.waitForResponse((response) =>
    response.url().endsWith("/api/chat") && response.request().method() === "POST");
  await page.locator("#send-chat").click();
  const response = await responsePromise;
  assert.equal(response.status(), 202);
  const { turn_id } = await response.json();
  await page.waitForFunction((previous) =>
    document.querySelectorAll(".chat-message.assistant").length > previous, previous, { timeout: 210000 });
  const turn = await (await context.request.get(`http://localhost:8765/api/turn/${turn_id}`)).json();
  assert.equal(turn.status, "completed", turn.error || await page.locator(".chat-message.assistant").last().innerText());
  assert.ok(!turn.answer.includes("couldn't complete that request"));
  report.answers.push({ question, answer: turn.answer, evidence: turn.evidence });
  console.log("AI", turn.answer);
  return turn;
}

try {
  await page.goto("http://localhost:8765");
  await page.waitForFunction(() => document.querySelector(".metric-value")?.textContent === "12,000");
  assert.equal(await page.locator(".metric-value").nth(1).innerText(), "381");
  assert.equal(await page.locator("#batches tbody tr").count(), 30);
  assert.equal(await page.locator("#cases tbody tr").count(), 30);
  assert.equal(await page.locator("#initiators .bar-row").count(), 5);
  assert.ok(await page.locator("#trend svg polyline").count());
  assert.equal(await page.locator(".lineage-step strong").first().innerText(), "46,442");
  assert.equal(await page.locator(".lineage-step strong").last().innerText(), "12,000");
  passed("Gold-backed charts, case traceability and pipeline lineage");

  await page.waitForFunction(() => document.querySelector("#cost-values").dataset.month === "288");
  assert.deepEqual(await page.locator(".cost-value strong").allTextContents(), ["$9.60", "$67.20", "$288.00", "$3,504.00"]);
  const costBox = await page.locator(".cost-card").boundingBox();
  assert.ok(costBox.x > 800 && costBox.y < 150);
  await page.locator("#cost-hours").fill("8");
  await page.locator("#cost-hours").dispatchEvent("change");
  await page.waitForFunction(() => document.querySelector("#cost-values").dataset.month === "96");
  await page.locator("#cost-sku").selectOption("F4");
  await page.waitForFunction(() => document.querySelector("#cost-values").dataset.month === "192");
  await page.locator("#cost-currency").selectOption("INR");
  await page.waitForFunction(() => document.querySelector("#cost-values").dataset.currency === "INR");
  const inr = await (await context.request.get("http://localhost:8765/api/cost?sku=F4&hours=8&currency=INR")).json();
  assert.equal(Number(await page.locator("#cost-values").getAttribute("data-month")), inr.amounts.month);
  await page.locator(".cost-details summary").click();
  await page.locator("#cost-assumptions").waitFor({ state: "visible" });
  assert.match(await page.locator("#cost-assumptions").innerText(), /Excludes OneLake/);
  await page.locator(".cost-details summary").click();
  passed("Top-right cost card: four periods, SKU, charged hours, INR and exclusions", inr);

  await page.locator("#country").selectOption("India");
  await page.locator("#apply-filters").click();
  await page.waitForFunction(() => {
    const count = Number(document.querySelector(".metric-value").textContent.replaceAll(",", ""));
    return count > 0 && count < 12000 && !document.querySelector("#apply-filters").disabled;
  });
  const india = await (await context.request.get("http://localhost:8765/api/dashboard?country=India")).json();
  assert.equal(await page.locator(".metric-value").first().innerText(), india.summary.ReturnCases.toLocaleString("en-US"));
  assert.ok((await page.locator("#cases tbody tr td:nth-child(4)").allTextContents()).every((country) => country === "India"));
  await page.locator("#date-from").fill("2030-01-01");
  await page.locator("#date-to").fill("2030-01-31");
  await page.locator("#apply-filters").click();
  await page.waitForFunction(() => document.querySelector(".metric-value")?.textContent === "0");
  assert.match(await page.locator("#cases").innerText(), /No matching records/);
  await page.locator("#reset-filters").click();
  await page.waitForFunction(() => document.querySelector(".metric-value")?.textContent === "12,000");
  passed("Country filters query Gold; empty date ranges render honestly; reset restores all cases", { india_cases: india.summary.ReturnCases });

  await page.locator("#cost-sku").selectOption("F2");
  await page.locator("#cost-hours").fill("24");
  await page.locator("#cost-hours").dispatchEvent("change");
  await page.locator("#cost-currency").selectOption("USD");
  await page.waitForFunction(() => {
    const quote = document.querySelector("#cost-values");
    return quote.dataset.currency === "USD" && quote.dataset.month === "288";
  });
  await page.screenshot({ path: "tests\\dashboard-desktop.png", fullPage: true });
  await page.locator("#chat-launcher").click();
  const overview = await ask("How many return cases are there, and how many have an unknown original initiator? Query Gold and cite the evidence.");
  assert.match(overview.answer, /12,?000/);
  assert.match(overview.answer, /381/);
  assert.ok(overview.evidence.some((item) => item.rows?.some((row) => row.ReturnCases === 12000 && row.UnknownOrigins === 381)));
  assert.ok(await page.locator(".evidence-panel").count());
  await page.locator(".evidence-panel > summary").last().click();
  assert.ok(await page.locator(".evidence-panel .table-wrap").last().isVisible());
  passed("Real Copilot answer with executed Gold query and visible supporting evidence");

  const followup = await ask("Break down those unknown-initiator cases by country. Show each country count, keeping the same two-year population.");
  const breakdown = followup.evidence.find((item) => item.rows?.length && "country" in item.rows[0]);
  assert.ok(breakdown, "Follow-up must actually retrieve a country breakdown.");
  assert.equal(breakdown.rows.reduce((total, row) => total + row.UnknownOrigins, 0), 381);
  assert.match(followup.answer, /381/);
  passed("Conversational follow-up retains the unknown-initiator population");

  const limits = await ask("Can you tell me the true defect rate for the batch with the most returns?");
  assert.match(limits.answer, /cannot|can't|can’t|unable|not (available|possible)|need|missing/i);
  assert.match(limits.answer, /sold|denominator|shipped|population|produced/i);
  passed("Assistant distinguishes return counts from unsupported defect rates");

  const missing = await ask("Look up the exact return ID NO-SUCH-RETURN-8765. Do not substitute any other return.");
  assert.ok(missing.evidence.some((item) =>
    item.query?.includes('return_id =~ "NO-SUCH-RETURN-8765"') &&
    (item.rows.length === 0 || item.rows.every((row) => row.ReturnCases === 0))));
  assert.match(missing.answer, /no |not found|couldn.t find|doesn.t (exist|match)|not.*(found|present)/i);
  passed("Missing return IDs do not produce invented records");
  await page.screenshot({ path: "tests\\dashboard-with-chat.png", fullPage: true });

  await page.locator("#close-chat").click();
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
  await page.locator("#chat-launcher").click();
  const chatBox = await page.locator("#chat-panel").boundingBox();
  assert.ok(chatBox.x >= 0 && chatBox.x + chatBox.width <= 390);
  await page.screenshot({ path: "tests\\dashboard-mobile.png", fullPage: true });
  passed("Responsive mobile dashboard and chat fit the viewport");
  assert.deepEqual(errors, [], "Unexpected browser JavaScript/console errors");
  report.passed = true;
} catch (error) {
  report.passed = false;
  report.error = error.stack;
  await page.screenshot({ path: "tests\\browser-failure.png", fullPage: true });
  throw error;
} finally {
  report.browser_errors = errors;
  await fs.writeFile("browser-verification.json", JSON.stringify(report, null, 2));
  await browser.close();
}
