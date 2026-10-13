"use strict";
document.getElementById("connect").addEventListener("click", async () => {
  const status = document.getElementById("status");
  try {
    const response = await fetch("/operator/summary", {
      headers: {Authorization: "Bearer " + document.getElementById("key").value},
      cache: "no-store"
    });
    if (!response.ok) throw new Error("Access denied or service unavailable (" + response.status + ").");
    const data = await response.json();
    const metrics = document.getElementById("metrics"); metrics.replaceChildren();
    for (const [name, value] of Object.entries(data.metrics)) {
      const term = document.createElement("dt"), description = document.createElement("dd");
      term.textContent = name.replace(/^gateway_/, "").replaceAll("_", " ");
      description.textContent = Number(value).toLocaleString(undefined, {maximumFractionDigits: 5});
      metrics.append(term, description);
    }
    const providers = document.getElementById("providers"); providers.replaceChildren();
    for (const [name, health] of Object.entries(data.providers)) {
      const item = document.createElement("p");
      item.textContent = name + ": " + (health.healthy ? "healthy" : "unavailable") +
        (health.circuit_open ? " · circuit open" : " · circuit closed"); providers.append(item);
    }
    status.textContent = "Updated " + new Date().toLocaleTimeString();
  } catch (error) { status.textContent = error.message; }
});
