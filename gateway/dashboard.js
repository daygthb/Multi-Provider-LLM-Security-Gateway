"use strict";

const key = document.getElementById("key");
const button = document.getElementById("connect");
const status = document.getElementById("status");
const metrics = document.getElementById("metrics");
const providers = document.getElementById("providers");
const providerRows = providers.querySelector("tbody");
const providerEmpty = document.getElementById("provider-empty");
let activeRequest = null;

const metricFields = [
  ["gateway_requests_total", "Requests", "count"],
  ["gateway_blocked_requests_total", "Policy blocks", "count"],
  ["gateway_rate_limit_rejections_total", "Quota rejections", "count"],
  ["gateway_fallback_usage_total", "Fallback selections", "count"],
  ["gateway_estimated_cost_dollars_total", "Estimated cost (USD)", "cost"],
  ["gateway_provider_latency_seconds_count", "Provider attempts", "count"],
  ["gateway_provider_latency_seconds_sum", "Total provider latency", "seconds"]
];

function renderMetrics(values) {
  metrics.replaceChildren();
  for (const [name, label, kind] of metricFields) {
    const row = document.createElement("div");
    row.className = "metric-row";
    const term = document.createElement("dt");
    const description = document.createElement("dd");
    term.textContent = label;
    const value = values[name];
    description.textContent = typeof value !== "number" || !Number.isFinite(value) ? "—" :
      kind === "cost" ? "$" + value.toFixed(5) :
      kind === "seconds" ? value.toLocaleString(undefined, {maximumFractionDigits: 3}) + " s" :
      value.toLocaleString(undefined, {maximumFractionDigits: 0});
    row.append(term, description);
    metrics.append(row);
  }
}

function clearResults(message) {
  renderMetrics({});
  providerRows.replaceChildren();
  providerEmpty.hidden = false;
  providerEmpty.textContent = message;
}

function renderProviders(values) {
  providerRows.replaceChildren();
  providerEmpty.hidden = Object.keys(values).length > 0;
  providerEmpty.textContent = "No providers reported.";
  for (const [name, health] of Object.entries(values)) {
    const row = document.createElement("tr");
    const provider = document.createElement("td");
    const state = document.createElement("td");
    const circuit = document.createElement("td");
    const indicator = document.createElement("span");
    provider.textContent = name;
    indicator.className = health.healthy ? "health" : "health unavailable";
    indicator.textContent = health.healthy ? "Healthy" : "Unavailable";
    state.append(indicator);
    circuit.textContent = health.circuit_open ? "Open" : "Closed";
    if (health.circuit_open) circuit.className = "circuit-open";
    row.append(provider, state, circuit);
    providerRows.append(row);
  }
}

async function refresh() {
  if (button.disabled) return;
  clearResults("Refresh metrics to load provider health.");
  if (!key.value.trim()) {
    status.textContent = "Enter an operator key to connect.";
    status.dataset.state = "error";
    key.focus();
    return;
  }
  button.disabled = true;
  providers.setAttribute("aria-busy", "true");
  status.dataset.state = "loading";
  status.textContent = "Refreshing metrics…";
  const controller = new AbortController();
  activeRequest = controller;
  const timeout = setTimeout(() => controller.abort(), 15000);
  let failureMessage = "Could not refresh metrics. Check the service and try again.";
  try {
    const response = await fetch("/operator/summary", {
      headers: {Authorization: "Bearer " + key.value.trim()},
      cache: "no-store",
      signal: controller.signal
    });
    if (activeRequest !== controller) return;
    if (!response.ok) {
      failureMessage = response.status === 401 || response.status === 403 ?
        "Access denied. Check your operator key and permissions." :
        "Could not refresh metrics. The service is unavailable; try again.";
      throw new Error("Summary request rejected");
    }
    const data = await response.json();
    if (activeRequest !== controller) return;
    renderMetrics(data.metrics);
    renderProviders(data.providers);
    status.dataset.state = "ready";
    status.textContent = "Updated " + new Date().toLocaleTimeString();
  } catch {
    if (activeRequest !== controller) return;
    clearResults("Provider health is unavailable.");
    status.dataset.state = "error";
    // Never echo response bodies or JSON parse errors into the operator UI.
    status.textContent = failureMessage;
  } finally {
    clearTimeout(timeout);
    if (activeRequest === controller) {
      activeRequest = null;
      button.disabled = false;
      providers.setAttribute("aria-busy", "false");
    }
  }
}

clearResults("Refresh metrics to load provider health.");
button.addEventListener("click", refresh);
key.addEventListener("keydown", event => {
  if (event.key === "Enter") {
    event.preventDefault();
    refresh();
  }
});
// Do not let a back/forward-cache restoration retain a credential or stale snapshot.
window.addEventListener("pagehide", () => {
  activeRequest?.abort();
  activeRequest = null;
  button.disabled = false;
  providers.setAttribute("aria-busy", "false");
  key.value = "";
  clearResults("Refresh metrics to load provider health.");
  status.textContent = "Enter an operator key to connect.";
  status.dataset.state = "idle";
});
