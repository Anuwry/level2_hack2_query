const form = document.querySelector("#queryForm");
const questionInput = document.querySelector("#question");
const submitButton = document.querySelector("#submitButton");
const clearButton = document.querySelector("#clearButton");
const llmToggle = document.querySelector("#llmToggle");
const csvForm = document.querySelector("#csvForm");
const csvInput = document.querySelector("#csvInput");
const csvFile = document.querySelector("#csvFile");
const runCsvButton = document.querySelector("#runCsvButton");
const exportCsvButton = document.querySelector("#exportCsvButton");
const clearCsvButton = document.querySelector("#clearCsvButton");
const loadCsvSampleButton = document.querySelector("#loadCsvSampleButton");
const statusPill = document.querySelector("#statusPill");
const answerOutput = document.querySelector("#answerOutput");
const jsonOutput = document.querySelector("#jsonOutput");
const csvOutput = document.querySelector("#csvOutput");
const countMetric = document.querySelector("#countMetric");
const eventMetric = document.querySelector("#eventMetric");
const routeMetric = document.querySelector("#routeMetric");
const summaryRows = document.querySelector("#summaryRows");
const routeList = document.querySelector("#routeList");
const batchRows = document.querySelector("#batchRows");

let latestResult = null;
let latestBatch = null;
const csvSample = `Question ID,CCTV ID,Time Range,Query
Q1,CCTVO1,0.01.00 - 0.10.00,จำนวนรถยนต์แยกตามยี่ห้อและสี
Q2,CCTVO1,0.01.00 - 0.10.00,จำนวนรถยนต์แยกตามยี่ห้อ
Q3,CCTVO1,0.01.00 - 0.10.00,จำนวนรถยนต์แยกตามสี`;

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
      body: JSON.stringify({ question, use_llm: llmToggle.checked }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Query failed");
    }
    latestResult = payload;
    latestBatch = payload.answers_csv ? { answers_csv: payload.answers_csv } : null;
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

csvForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const csvText = csvInput.value.trim();
  if (!csvText) {
    renderError("Please paste or upload a CSV question file.");
    return;
  }

  runCsvButton.disabled = true;
  statusPill.textContent = "CSV";
  try {
    const response = await fetch("/api/batch-query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ csv_text: csvText, use_llm: llmToggle.checked }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "CSV query failed");
    }
    latestBatch = payload;
    latestResult = payload;
    renderBatchResult(payload);
    setTab("csv");
    statusPill.textContent = "Ready";
  } catch (error) {
    renderError(error.message);
    statusPill.textContent = "Error";
  } finally {
    runCsvButton.disabled = false;
  }
});

csvFile.addEventListener("change", async () => {
  const [file] = csvFile.files || [];
  if (!file) {
    return;
  }
  csvInput.value = await file.text();
});

loadCsvSampleButton.addEventListener("click", () => {
  csvInput.value = csvSample;
  csvInput.focus();
});

clearCsvButton.addEventListener("click", () => {
  csvInput.value = "";
  csvFile.value = "";
  latestBatch = null;
  exportCsvButton.disabled = true;
  csvOutput.textContent = "Question ID,Answer";
  batchRows.innerHTML = "";
});

exportCsvButton.addEventListener("click", () => {
  if (!latestBatch?.answers_csv) {
    return;
  }
  downloadTextFile("cctv_answers.csv", latestBatch.answers_csv, "text/csv;charset=utf-8");
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
  answerOutput.textContent = answerText(result);
  jsonOutput.textContent = JSON.stringify(result, null, 2);
  csvOutput.textContent = result.answers_csv || "Question ID,Answer";
  renderBatchRows(
    result.csv_answer
      ? [
          {
            question_id: result.question_id || "Q1",
            answer: result.answer || "",
            csv_answer: result.csv_answer,
          },
        ]
      : []
  );
  exportCsvButton.disabled = !result.answers_csv;
  countMetric.textContent = result.count ?? 0;
  eventMetric.textContent = result.event_count ?? 0;
  routeMetric.textContent = Array.isArray(result.routes) ? result.routes.length : 0;
  renderSummary(result.summary?.brand_color_counts || []);
  renderRoutes(result.routes || []);
}

function renderBatchResult(batch) {
  const rows = batch.answers || [];
  answerOutput.classList.remove("error");
  answerOutput.textContent = rows
    .map((row) => `${row.question_id}: ${row.answer}\nCSV: ${row.csv_answer}`)
    .join("\n\n");
  jsonOutput.textContent = JSON.stringify(batch, null, 2);
  csvOutput.textContent = batch.answers_csv || "Question ID,Answer";
  countMetric.textContent = rows.length;
  eventMetric.textContent = rows.reduce((total, row) => total + (row.event_count || 0), 0);
  routeMetric.textContent = "-";
  renderBatchRows(rows);
  exportCsvButton.disabled = !batch.answers_csv;
}

function answerText(result) {
  const lines = [];
  const normalization = result.llm_normalization || {};
  if (normalization.used && normalization.changed) {
    lines.push(`Normalized: ${result.normalized_question || normalization.normalized_question}`);
    lines.push("");
  }
  if (normalization.error) {
    lines.push(`LLM fallback: ${normalization.error}`);
    lines.push("");
  }
  lines.push(result.answer || "");
  return lines.join("\n");
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

function renderBatchRows(rows) {
  batchRows.innerHTML = "";
  if (!rows.length) {
    const row = document.createElement("tr");
    row.innerHTML = '<td colspan="3">No rows</td>';
    batchRows.appendChild(row);
    return;
  }

  rows.forEach((item) => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${escapeHtml(item.question_id)}</td>
      <td>${escapeHtml(item.answer)}</td>
      <td><code>${escapeHtml(item.csv_answer)}</code></td>
    `;
    batchRows.appendChild(row);
  });
}

function renderError(message) {
  latestResult = null;
  latestBatch = null;
  answerOutput.classList.add("error");
  answerOutput.textContent = message;
  jsonOutput.textContent = "{}";
  csvOutput.textContent = "Question ID,Answer";
  exportCsvButton.disabled = true;
  countMetric.textContent = "-";
  eventMetric.textContent = "-";
  routeMetric.textContent = "-";
  summaryRows.innerHTML = "";
  routeList.textContent = "";
  batchRows.innerHTML = "";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function downloadTextFile(filename, content, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function loadHealth() {
  try {
    const response = await fetch("/api/health");
    const payload = await response.json();
    llmToggle.checked = Boolean(payload.llm_enabled);
    statusPill.textContent = llmToggle.checked ? "LLM" : "Local";
    statusPill.title = payload.llm_model ? `${payload.llm_model} @ ${payload.llm_base_url}` : "";
  } catch (error) {
    statusPill.textContent = "Local";
  }
}

window.addEventListener("load", async () => {
  await loadHealth();
  form.requestSubmit();
});
