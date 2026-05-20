const form = document.querySelector("#queryForm");
const questionInput = document.querySelector("#question");
const submitButton = document.querySelector("#submitButton");
const clearButton = document.querySelector("#clearButton");
const statusPill = document.querySelector("#statusPill");
const answerOutput = document.querySelector("#answerOutput");
const jsonOutput = document.querySelector("#jsonOutput");
const countMetric = document.querySelector("#countMetric");
const eventMetric = document.querySelector("#eventMetric");
const routeMetric = document.querySelector("#routeMetric");
const summaryRows = document.querySelector("#summaryRows");
const routeList = document.querySelector("#routeList");

let latestResult = null;

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = questionInput.value.trim();
  if (!question) {
    renderError("กรุณากรอกคำถาม");
    return;
  }

  submitButton.disabled = true;
  statusPill.textContent = "Querying";
  try {
    const response = await fetch("/api/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Query failed");
    }
    latestResult = payload;
    renderResult(payload);
    statusPill.textContent = "Ready";
  } catch (error) {
    renderError(error.message);
    statusPill.textContent = "Error";
  } finally {
    submitButton.disabled = false;
  }
});

clearButton.addEventListener("click", () => {
  questionInput.value = "";
  questionInput.focus();
});

document.querySelectorAll("[data-question]").forEach((button) => {
  button.addEventListener("click", () => {
    questionInput.value = button.dataset.question;
    form.requestSubmit();
  });
});

document.querySelectorAll("[data-tab]").forEach((button) => {
  button.addEventListener("click", () => setTab(button.dataset.tab));
});

function setTab(tabName) {
  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === tabName);
  });
  document.querySelectorAll("[data-panel]").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.panel === tabName);
  });
}

function renderResult(result) {
  answerOutput.classList.remove("error");
  answerOutput.textContent = result.answer || "";
  jsonOutput.textContent = JSON.stringify(result, null, 2);
  countMetric.textContent = result.count ?? 0;
  eventMetric.textContent = result.event_count ?? 0;
  routeMetric.textContent = Array.isArray(result.routes) ? result.routes.length : 0;
  renderSummary(result.summary?.brand_color_counts || []);
  renderRoutes(result.routes || []);
}

function renderSummary(rows) {
  summaryRows.innerHTML = "";
  if (!rows.length) {
    const row = document.createElement("tr");
    row.innerHTML = '<td colspan="3">No rows</td>';
    summaryRows.appendChild(row);
    return;
  }

  rows.forEach((item) => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${escapeHtml(item.brand)}</td>
      <td>${escapeHtml(item.color)}</td>
      <td>${item.count}</td>
    `;
    summaryRows.appendChild(row);
  });
}

function renderRoutes(routes) {
  routeList.innerHTML = "";
  if (!routes.length) {
    routeList.textContent = "No routes";
    return;
  }

  routes.forEach((route, index) => {
    const item = document.createElement("article");
    item.className = "route-item";
    const label = `${route.brand} ${route.color} ${route.type}`;
    item.innerHTML = `
      <div class="route-title">
        <span>${index + 1}. ${escapeHtml(label)}</span>
        <span class="route-meta">${escapeHtml(route.start_time)}-${escapeHtml(route.end_time)}</span>
      </div>
      <div class="route-path">${escapeHtml((route.path || []).join(" -> "))}</div>
      <div class="route-meta">${route.event_count || 0} detections</div>
    `;
    routeList.appendChild(item);
  });
}

function renderError(message) {
  latestResult = null;
  answerOutput.classList.add("error");
  answerOutput.textContent = message;
  jsonOutput.textContent = "{}";
  countMetric.textContent = "-";
  eventMetric.textContent = "-";
  routeMetric.textContent = "-";
  summaryRows.innerHTML = "";
  routeList.textContent = "";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

window.addEventListener("load", () => {
  form.requestSubmit();
});
