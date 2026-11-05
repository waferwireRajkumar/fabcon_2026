import { marked } from "marked";
import DOMPurify from "dompurify";

const $ = (id) => document.getElementById(id);
const number = (value) => Number(value ?? 0).toLocaleString();
let config;
let conversation = crypto.randomUUID();
let busy = false;
let costRequest;

async function request(path, options = {}) {
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`);
  return body;
}

function node(tag, text, className) {
  const result = document.createElement(tag);
  if (text !== undefined) result.textContent = text;
  if (className) result.className = className;
  return result;
}

function selection() {
  return { country: $("country").value, date_from: $("date-from").value, date_to: $("date-to").value };
}

function table(container, rows, columns) {
  container.replaceChildren();
  if (!rows.length) {
    container.append(node("p", "No matching records.", "empty-state"));
    return;
  }
  const element = node("table");
  const head = node("tr");
  columns.forEach(([key, title]) => head.append(node("th", title || key)));
  element.append(node("thead"));
  element.firstChild.append(head);
  const body = node("tbody");
  for (const row of rows) {
    const line = node("tr");
    for (const [key] of columns) {
      const value = row[key];
      const cell = node("td", typeof value === "number" ? number(value) : String(value ?? "—"));
      if (typeof value === "number") cell.className = "numeric";
      line.append(cell);
    }
    body.append(line);
  }
  element.append(body);
  container.append(element);
}

function bars(id, rows, field) {
  const target = $(id);
  target.replaceChildren();
  if (!rows.length) return target.append(node("p", "No matching records.", "empty-state"));
  const largest = Math.max(...rows.map((row) => row.ReturnCases), 1);
  for (const row of rows) {
    const line = node("div", undefined, "bar-row");
    const label = node("span", row[field] || "Not recorded", "bar-label");
    label.title = row[field] || "Not recorded";
    const track = node("div", undefined, "bar-track");
    const fill = node("div", undefined, "bar-fill");
    fill.style.width = `${100 * row.ReturnCases / largest}%`;
    track.append(fill);
    line.append(label, track, node("span", number(row.ReturnCases), "bar-count"));
    target.append(line);
  }
}

function trend(rows) {
  const target = $("trend");
  target.replaceChildren();
  if (!rows.length) return target.append(node("p", "No matching records.", "empty-state"));
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.classList.add("trend-svg");
  svg.setAttribute("viewBox", "0 0 640 220");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Monthly return-case counts");
  const maximum = Math.max(...rows.map((row) => row.ReturnCases), 1);
  const points = rows.map((row, i) => [20 + i * 600 / Math.max(rows.length - 1, 1), 195 - row.ReturnCases / maximum * 170]);
  for (const y of [25, 82, 139, 195]) {
    const line = document.createElementNS(ns, "line");
    for (const [key, value] of Object.entries({ x1: 20, x2: 620, y1: y, y2: y, stroke: "#e7eee9" })) line.setAttribute(key, value);
    svg.append(line);
  }
  const area = document.createElementNS(ns, "path");
  area.setAttribute("d", `M ${points[0][0]},195 L ${points.map((point) => point.join(",")).join(" L ")} L ${points.at(-1)[0]},195 Z`);
  area.setAttribute("fill", "#e0f0e7");
  svg.append(area);
  const path = document.createElementNS(ns, "polyline");
  path.setAttribute("points", points.map((point) => point.join(",")).join(" "));
  path.setAttribute("fill", "none");
  path.setAttribute("stroke", "#087f68");
  path.setAttribute("stroke-width", "3");
  svg.append(path);
  const labels = node("div", undefined, "trend-labels");
  [rows[0], rows[Math.floor(rows.length / 2)], rows.at(-1)].forEach((row) => labels.append(node("span", row.return_month)));
  target.append(svg, labels);
}

async function refreshDashboard() {
  $("apply-filters").disabled = true;
  $("data-status").textContent = "Querying published Gold data...";
  $("dashboard-error").hidden = true;
  try {
    const query = new URLSearchParams(Object.entries(selection()).filter(([, value]) => value));
    const data = await request(`/api/dashboard?${query}`);
    const summary = data.summary;
    const publication = data.lineage.publication;
    $("metrics").replaceChildren();
    [
      ["RETURN CASES", summary.ReturnCases, "Latest revision per return ID"],
      ["UNKNOWN INITIATORS", summary.UnknownOrigins, "Missing provenance remains visible"],
      ["DISTINCT BATTERIES", summary.DistinctBatteries, "A battery can have repeat returns"],
      ["REPLAYS REMOVED", publication.replays_removed, "Whole source snapshot, not filtered"],
    ].forEach(([title, value, subtitle]) => {
      const card = node("div", undefined, "metric");
      card.append(node("div", title, "metric-title"), node("div", number(value), "metric-value"), node("small", subtitle));
      $("metrics").append(card);
    });
    bars("initiators", data.initiators, "originator_type");
    bars("reasons", data.reasons, "reported_reason");
    bars("findings", data.findings, "inspection_finding");
    trend(data.trend);
    table($("batches"), data.batches, [
      ["batch_id", "Batch"], ["product_id", "Product"], ["ReturnCases", "Return cases"],
      ["DistinctBatteries", "Distinct batteries"], ["ShareOfMatchingCases", "% of matching returns"],
    ]);
    table($("cases"), data.cases, [
      ["return_id", "Return ID"], ["battery_serial", "Battery"], ["batch_id", "Batch"],
      ["country", "Country"], ["originator_type", "Original initiator"],
      ["submitted_by_type", "Submitted by"], ["reported_reason", "Reported complaint"],
      ["inspection_finding", "Inspection finding"], ["return_status", "Status"],
    ]);
    const currentCountry = $("country").value;
    const countryOptions = [node("option", "All countries")];
    countryOptions[0].value = "";
    data.countries.sort((a, b) => a.country.localeCompare(b.country)).forEach((row) => {
      const option = node("option", row.country);
      option.value = row.country;
      countryOptions.push(option);
    });
    $("country").replaceChildren(...countryOptions);
    $("country").value = currentCountry;
    $("lineage").replaceChildren();
    [
      [publication.bronze_events, "Bronze events"],
      [publication.quarantined_events, "Quarantined"],
      [publication.silver_events, "Silver events"],
      [publication.gold_cases, "Gold return cases"],
    ].forEach(([value, title], index) => {
      if (index) $("lineage").append(node("span", "→", "lineage-arrow"));
      const item = node("div", undefined, "lineage-step");
      item.append(node("strong", number(value)), node("span", title));
      $("lineage").append(item);
    });
    const first = summary.FirstReturn?.slice(0, 10);
    const last = summary.LastReturn?.slice(0, 10);
    $("data-status").textContent = summary.ReturnCases
      ? `${first} – ${last} · published Gold snapshot · UTC`
      : "No returns match the selected filters";
  } catch (error) {
    $("dashboard-error").textContent = error.message;
    $("dashboard-error").hidden = false;
    $("data-status").textContent = "Could not refresh data";
  } finally {
    $("apply-filters").disabled = false;
  }
}

async function refreshCost() {
  costRequest?.abort();
  const controller = new AbortController();
  costRequest = controller;
  $("cost-values").setAttribute("aria-busy", "true");
  delete $("cost-values").dataset.month;
  try {
    const query = new URLSearchParams({
      sku: $("cost-sku").value, currency: $("cost-currency").value, hours: $("cost-hours").value,
    });
    const data = await request(`/api/cost?${query}`, { signal: controller.signal });
    const money = (value) => new Intl.NumberFormat("en-US", { style: "currency", currency: data.currency, maximumFractionDigits: 2 }).format(value);
    $("cost-values").replaceChildren();
    [["day", "1 day"], ["week", "1 week"], ["month", "1 month (30d)"], ["year", "1 year (365d)"]].forEach(([key, label]) => {
      const item = node("div", undefined, "cost-value");
      item.append(node("span", label), node("strong", money(data.amounts[key])));
      $("cost-values").append(item);
    });
    $("cost-rate").textContent = `Current: FT1 trial. Paid ${data.sku} scenario · ${data.region_label} · ${money(data.capacity_hourly_rate)}/capacity-hour · PAYG · prices checked ${data.retrieved_at.slice(0, 10)}`;
    $("cost-assumptions").replaceChildren(node("p", "Current workspace: FT1 trial. These figures model a hypothetical paid capacity."));
    const list = node("ul");
    data.assumptions.forEach((value) => list.append(node("li", value)));
    const source = node("a", "Official Fabric pricing ↗");
    source.href = data.pricing_page;
    source.target = "_blank";
    source.rel = "noopener noreferrer";
    $("cost-assumptions").append(list, source);
    $("cost-values").dataset.month = data.amounts.month;
    $("cost-values").dataset.currency = data.currency;
  } catch (error) {
    if (error.name !== "AbortError") {
      $("cost-values").textContent = `Pricing unavailable: ${error.message}`;
      $("cost-rate").textContent = "No price has been assumed.";
    }
  } finally {
    if (costRequest === controller) $("cost-values").removeAttribute("aria-busy");
  }
}

function openChat(open = true) {
  $("chat-panel").hidden = !open;
  $("chat-launcher").hidden = open;
  $("chat-launcher").setAttribute("aria-expanded", String(open));
  if (open) $("chat-input").focus();
}

function evidenceDetails(evidence) {
  const details = node("details", undefined, "evidence-panel");
  details.append(node("summary", `${evidence.length} supporting data ${evidence.length === 1 ? "query" : "queries"} · view evidence`));
  for (const result of evidence) {
    const item = node("section", undefined, "evidence-item");
    item.append(node("strong", `[${result.evidence_id}] ${result.source || result.kind || "Verified source"}`));
    if (result.rows?.length) {
      const wrapper = node("div", undefined, "table-wrap");
      table(wrapper, result.rows, Object.keys(result.rows[0]).map((key) => [key, key]));
      item.append(wrapper);
    } else {
      const copy = { ...result };
      delete copy.query;
      item.append(node("pre", JSON.stringify(copy, null, 2)));
    }
    if (result.query) {
      const query = node("details");
      query.append(node("summary", "Executed read-only KQL"), node("pre", result.query));
      item.append(query);
    }
    details.append(item);
  }
  return details;
}

async function ask(message) {
  if (busy || !message.trim()) return;
  busy = true;
  openChat();
  document.querySelectorAll(".welcome,.suggestions").forEach((element) => element.remove());
  const messages = $("chat-messages");
  messages.append(node("div", message, "chat-message user"));
  $("chat-input").value = "";
  $("send-chat").disabled = true;
  $("new-chat").disabled = true;
  $("chat-activity").textContent = "Reading your question...";
  messages.scrollTop = messages.scrollHeight;
  try {
    const response = await request("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": config.csrf_token },
      body: JSON.stringify({ message, conversation_id: conversation, selection: selection() }),
    });
    const deadline = Date.now() + 210000;
    while (Date.now() < deadline) {
      const turn = await request(`/api/turn/${response.turn_id}`);
      $("chat-activity").textContent = turn.activity || "Checking the available evidence...";
      if (turn.status === "failed") throw new Error(turn.error);
      if (turn.status === "completed") {
        const answer = node("div", undefined, "chat-message assistant");
        const text = node("div");
        text.innerHTML = DOMPurify.sanitize(marked.parse(turn.answer), {
          FORBID_TAGS: ["img", "iframe", "style", "form", "input", "button"],
        });
        text.querySelectorAll("a").forEach((link) => { link.target = "_blank"; link.rel = "noopener noreferrer"; });
        answer.append(text);
        if (turn.evidence.length) answer.append(evidenceDetails(turn.evidence));
        messages.append(answer);
        $("chat-activity").textContent = turn.evidence.length
          ? "Answered with supporting evidence"
          : "Explanation only · no fresh data query for this reply";
        messages.scrollTop = messages.scrollHeight;
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 900));
    }
    throw new Error("The assistant took too long. Wait briefly before starting another question.");
  } catch (error) {
    messages.append(node("div", `I couldn't complete that request: ${error.message}`, "chat-message assistant"));
    $("chat-activity").textContent = "Request not completed";
  } finally {
    busy = false;
    $("send-chat").disabled = false;
    $("new-chat").disabled = false;
    $("chat-input").focus();
  }
}

async function main() {
  config = await request("/api/config");
  $("fabric-link").href = config.fabric_url;
  $("chat-launcher").addEventListener("click", () => openChat());
  $("close-chat").addEventListener("click", () => openChat(false));
  $("new-chat").addEventListener("click", () => {
    conversation = crypto.randomUUID();
    $("chat-messages").replaceChildren(node("p", "New conversation. Ask a question about your Gold data.", "muted"));
    $("chat-activity").textContent = "";
    $("chat-input").focus();
  });
  $("chat-form").addEventListener("submit", (event) => { event.preventDefault(); ask($("chat-input").value); });
  $("chat-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); ask($("chat-input").value); }
  });
  document.querySelectorAll("[data-prompt]").forEach((button) => button.addEventListener("click", () => ask(button.dataset.prompt)));
  $("apply-filters").addEventListener("click", refreshDashboard);
  $("reset-filters").addEventListener("click", () => {
    $("country").value = ""; $("date-from").value = ""; $("date-to").value = "";
    refreshDashboard();
  });
  ["cost-sku", "cost-currency", "cost-hours"].forEach((id) => $(id).addEventListener("change", refreshCost));
  await Promise.all([refreshDashboard(), refreshCost()]);
}

main().catch((error) => {
  $("dashboard-error").textContent = error.message;
  $("dashboard-error").hidden = false;
});
