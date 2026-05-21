const form = document.querySelector("#queryForm");
const questionInput = document.querySelector("#question");
const submitButton = document.querySelector("#submitButton");
const clearButton = document.querySelector("#clearButton");
const llmToggle = document.querySelector("#llmToggle");
const dateFilter = document.querySelector("#dateFilter");
const cctvFilter = document.querySelector("#cctvFilter");
const startTimeFilter = document.querySelector("#startTimeFilter");
const endTimeFilter = document.querySelector("#endTimeFilter");
const csvForm = document.querySelector("#csvForm");
const csvInput = document.querySelector("#csvInput");
const csvFile = document.querySelector("#csvFile");
const runCsvButton = document.querySelector("#runCsvButton");
const exportCsvButton = document.querySelector("#exportCsvButton");
const clearCsvButton = document.querySelector("#clearCsvButton");
const loadCsvSampleButton = document.querySelector("#loadCsvSampleButton");
const sqlForm = document.querySelector("#sqlForm");
const sqlInput = document.querySelector("#sqlInput");
const sqlFile = document.querySelector("#sqlFile");
const convertSqlButton = document.querySelector("#convertSqlButton");
const exportSqlCsvButton = document.querySelector("#exportSqlCsvButton");
const clearSqlButton = document.querySelector("#clearSqlButton");
const loadSqlSampleButton = document.querySelector("#loadSqlSampleButton");
const statusPill = document.querySelector("#statusPill");
const answerOutput = document.querySelector("#answerOutput");
const jsonOutput = document.querySelector("#jsonOutput");
const csvOutput = document.querySelector("#csvOutput");
const sqlTableSelect = document.querySelector("#sqlTableSelect");
const sqlTableHead = document.querySelector("#sqlTableHead");
const sqlRows = document.querySelector("#sqlRows");
const sqlOutput = document.querySelector("#sqlOutput");
const sqlMeta = document.querySelector("#sqlMeta");
const followUpActions = document.querySelector("#followUpActions");
const countMetric = document.querySelector("#countMetric");
const eventMetric = document.querySelector("#eventMetric");
const routeMetric = document.querySelector("#routeMetric");
const summaryOverview = document.querySelector("#summaryOverview");
const summaryTitle = document.querySelector("#summaryTitle");
const summaryHead = document.querySelector("#summaryPanel thead tr");
const summaryRows = document.querySelector("#summaryRows");
const routeList = document.querySelector("#routeList");
const batchRows = document.querySelector("#batchRows");
const clarificationModal = document.querySelector("#clarificationModal");
const clarificationTitle = document.querySelector("#clarificationTitle");
const clarificationMessage = document.querySelector("#clarificationMessage");
const warningList = document.querySelector("#warningList");
const clarificationSelectLabel = document.querySelector("#clarificationSelectLabel");
const clarificationSelect = document.querySelector("#clarificationSelect");
const applyClarificationButton = document.querySelector("#applyClarificationButton");
const dismissClarificationButton = document.querySelector("#dismissClarificationButton");
const keepCurrentAnswerButton = document.querySelector("#keepCurrentAnswerButton");

let latestResult = null;
let latestBatch = null;
let latestSql = null;
let pendingClarification = null;
let activeWarningKey = null;
let suppressNextOptionalFollowUp = false;
let pendingSummaryMode = null;
let summaryModeOverride = null;
let submitQuestionOnly = false;
const acknowledgedWarningKeys = new Set();
const csvSample = `Question ID,CCTV ID,Time Range,Query
Q1,CCTVO1,0.01.00 - 0.10.00,จำนวนรถยนต์แยกตามยี่ห้อและสี
Q2,CCTVO1,0.01.00 - 0.10.00,จำนวนรถยนต์แยกตามยี่ห้อ
Q3,CCTVO1,0.01.00 - 0.10.00,จำนวนรถยนต์แยกตามสี`;

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  summaryModeOverride = pendingSummaryMode;
  pendingSummaryMode = null;
  const question = questionInput.value.trim();
  const questionOnlySubmit = submitQuestionOnly;
  const filters = questionOnlySubmit ? {} : selectedFilters();
  submitQuestionOnly = false;
  if (!question && !hasSelectedFilters(filters)) {
    renderError("กรุณากรอกคำถาม");
    return;
  }
  if ((filters.start_time && !filters.end_time) || (!filters.start_time && filters.end_time)) {
    renderError("กรุณาเลือกเวลาเริ่มและเวลาสิ้นสุดให้ครบ หรือปล่อยว่างทั้งคู่");
    return;
  }

  submitButton.disabled = true;
  statusPill.textContent = "Querying";
  try {
    const response = await fetch("/api/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, ...filters, use_llm: questionOnlySubmit ? false : llmToggle.checked }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Query failed");
    }
    latestResult = payload;
    if (Array.isArray(payload.answers)) {
      latestBatch = payload;
      renderBatchResult(payload);
      setTab("csv");
      showFollowUpDialog(payload);
    } else {
      latestBatch = payload.answers_csv ? { answers_csv: payload.answers_csv } : null;
      renderResult(payload);
      showFollowUpDialog(payload);
    }
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
  dateFilter.value = "";
  cctvFilter.value = "";
  startTimeFilter.value = "";
  endTimeFilter.value = "";
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
    showFollowUpDialog(payload);
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

sqlForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const sqlText = sqlInput.value.trim();
  if (!sqlText) {
    renderError("Please paste or upload SQL first.");
    return;
  }

  convertSqlButton.disabled = true;
  statusPill.textContent = "SQL";
  try {
    const response = await fetch("/api/sql-to-csv", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sql_text: sqlText }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "SQL conversion failed");
    }
    latestSql = payload;
    latestResult = payload;
    renderSqlResult(payload);
    jsonOutput.textContent = JSON.stringify(payload, null, 2);
    setTab("sql");
    statusPill.textContent = "Ready";
  } catch (error) {
    renderError(error.message);
    statusPill.textContent = "Error";
  } finally {
    convertSqlButton.disabled = false;
  }
});

sqlFile.addEventListener("change", async () => {
  const [file] = sqlFile.files || [];
  if (!file) {
    return;
  }
  sqlInput.value = await file.text();
});

loadSqlSampleButton.addEventListener("click", async () => {
  statusPill.textContent = "Loading";
  try {
    const response = await fetch("/api/sql-sample");
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Could not load SQL sample");
    }
    sqlInput.value = [payload.schema_sql, payload.examples_sql].filter(Boolean).join("\n\n");
    sqlInput.focus();
    statusPill.textContent = "Ready";
  } catch (error) {
    renderError(error.message);
    statusPill.textContent = "Error";
  }
});

clearSqlButton.addEventListener("click", () => {
  sqlInput.value = "";
  sqlFile.value = "";
  latestSql = null;
  exportSqlCsvButton.disabled = true;
  sqlTableSelect.innerHTML = "";
  sqlTableHead.innerHTML = "";
  sqlRows.innerHTML = "";
  sqlOutput.textContent = "";
  sqlMeta.textContent = "No SQL table";
});

exportSqlCsvButton.addEventListener("click", () => {
  const table = selectedSqlTable();
  if (!table?.csv) {
    return;
  }
  downloadTextFile(`${table.name}.csv`, table.csv, "text/csv;charset=utf-8");
});

sqlTableSelect.addEventListener("change", renderSelectedSqlTable);

applyClarificationButton.addEventListener("click", () => {
  if (!pendingClarification) {
    closeClarificationModal();
    return;
  }
  const option = pendingClarification.options[Number(clarificationSelect.value)];
  const nextQuestion = buildClarifiedQuestion(
    pendingClarification.result,
    pendingClarification.clarification,
    option
  );
  suppressNextOptionalFollowUp = true;
  closeClarificationModal();
  questionInput.value = nextQuestion;
  form.requestSubmit();
});

dismissClarificationButton.addEventListener("click", closeClarificationModal);
keepCurrentAnswerButton.addEventListener("click", closeClarificationModal);

clarificationModal.addEventListener("click", (event) => {
  if (event.target === clarificationModal) {
    closeClarificationModal();
  }
});

window.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !clarificationModal.hidden) {
    closeClarificationModal();
  }
});

document.querySelectorAll("[data-tab]").forEach((button) => {
  button.addEventListener("click", () => setTab(button.dataset.tab));
});

document.querySelectorAll("[data-summary-mode][data-question]").forEach((button) => {
  button.addEventListener("click", () => runPresetQuestion(button.dataset.question || "", button.dataset.summaryMode || null));
});

followUpActions.addEventListener("click", (event) => {
  const button = event.target.closest("[data-followup-question]");
  if (!button) {
    return;
  }
  submitQuestionOnly = true;
  runPresetQuestion(button.dataset.followupQuestion || "", button.dataset.summaryMode || null);
});

loadMetadata();

function runPresetQuestion(question, summaryMode) {
  pendingSummaryMode = summaryMode;
  questionInput.value = question;
  form.requestSubmit();
}

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
  renderSummaryOverview(result);
  renderSummary(summaryTableRows(result), summaryTableColumns(result), summaryModeLabel(summaryModeForResult(result)));
  renderFollowUpActions(result);
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
  followUpActions.hidden = true;
  followUpActions.innerHTML = "";
  summaryOverview.innerHTML = "";
  summaryTitle.textContent = "Current breakdown";
  summaryHead.innerHTML = "<th>Group</th><th>Value</th><th>Count</th>";
  summaryRows.innerHTML = "";
  renderBatchRows(rows);
  exportCsvButton.disabled = !batch.answers_csv;
}

function renderSqlResult(payload) {
  const tables = payload.tables || [];
  sqlTableSelect.innerHTML = "";
  tables.forEach((table) => {
    const option = document.createElement("option");
    option.value = table.name;
    option.textContent = `${table.name} (${table.row_count || 0})`;
    sqlTableSelect.appendChild(option);
  });
  sqlTableSelect.value = payload.selected_table || tables[0]?.name || "";
  renderSelectedSqlTable();
}

function selectedSqlTable() {
  const tables = latestSql?.tables || [];
  return tables.find((table) => table.name === sqlTableSelect.value) || tables[0] || null;
}

function renderSelectedSqlTable() {
  const table = selectedSqlTable();
  sqlTableHead.innerHTML = "";
  sqlRows.innerHTML = "";
  sqlOutput.textContent = "";
  exportSqlCsvButton.disabled = true;

  if (!table) {
    sqlMeta.textContent = "No SQL table";
    return;
  }

  sqlMeta.textContent = `${table.row_count || 0} rows`;
  const headerRow = document.createElement("tr");
  (table.columns || []).forEach((column) => {
    const cell = document.createElement("th");
    cell.textContent = column;
    headerRow.appendChild(cell);
  });
  sqlTableHead.appendChild(headerRow);

  (table.rows || []).forEach((item) => {
    const row = document.createElement("tr");
    (table.columns || []).forEach((column) => {
      const cell = document.createElement("td");
      cell.textContent = item[column] ?? "";
      row.appendChild(cell);
    });
    sqlRows.appendChild(row);
  });

  sqlOutput.textContent = table.csv || "";
  exportSqlCsvButton.disabled = !table.csv;
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
  if (Array.isArray(result.answer_options) && result.answer_options.length) {
    lines.push("");
    lines.push("คำตอบทางเลือก:");
    result.answer_options.forEach((option, index) => {
      const csv = option.csv_answer ? ` | CSV: ${option.csv_answer}` : "";
      lines.push(`${index + 1}. ${option.answer || option.label || option.id}${csv}`);
    });
  }
  return lines.join("\n");
}

function renderFollowUpActions(result) {
  const actions = followUpActionsForResult(result);
  if (!actions.length) {
    followUpActions.hidden = true;
    followUpActions.innerHTML = "";
    return;
  }

  followUpActions.innerHTML = [
    '<span class="follow-up-label">ใช้ต่อ:</span>',
    ...actions.map((action) => followUpButtonHtml(action)),
  ].join("");
  followUpActions.hidden = false;
}

function followUpActionsForResult(result) {
  const mode = summaryModeForResult(result);
  const eventFocused = mode === "event" || mode === "camera_event" || mode === "hour_event" || Boolean(result.query?.event);
  const withContext = (action) => ({
    ...action,
    question: buildFollowUpQuestion(result.query || {}, action),
  });
  if (!eventFocused) {
    return [
      { label: "ดู Event", question: "รถทั้งหมดตาม event", mode: "event" },
      { label: "ดู Type", question: "รถทั้งหมดตามประเภทรถ", mode: "type" },
      { label: "ดู Color", question: "รถทั้งหมดตามสี", mode: "color" },
      { label: "ดู Country", question: "รถทั้งหมดตามประเทศ", mode: "origin" },
    ].map(withContext);
  }

  return [
    { label: "Camera × Event", question: "แต่ละกล้องมี entry exit pass เท่าไหร่", mode: "camera_event" },
    { label: "Hour × Event", question: "แต่ละชั่วโมงมีรถเข้าออกกี่คัน", mode: "hour_event" },
    { label: "เฉพาะ entry", question: "event entry vehicles", mode: "event" },
    { label: "เฉพาะ exit", question: "event exit vehicles", mode: "event" },
    { label: "เฉพาะ pass", question: "event pass vehicles", mode: "event" },
    { label: "entry ไม่ exit", question: "entry without exit", mode: "event" },
    { label: "entry ไม่ exit × กล้อง", question: "รถที่ entry แล้วไม่ exit แยกตามกล้อง entry", mode: "unclosed_entry_camera" },
  ].map(withContext);
}

function buildFollowUpQuestion(query, action) {
  const actionQuestion = String(action.question || "").toLowerCase();
  const inferredEvent =
    action.event ||
    (actionQuestion.includes("event entry") ? "entry" : "") ||
    (actionQuestion.includes("event exit") ? "exit" : "") ||
    (actionQuestion.includes("event pass") ? "pass" : "");
  return buildStructuredQuestion(query, {
    mode: action.mode,
    event: inferredEvent,
    unclosedEntry: action.unclosedEntry || action.mode === "unclosed_entry_camera" || actionQuestion.includes("entry without exit"),
  });
}

function followUpButtonHtml(action) {
  return `
    <button
      type="button"
      class="quick-chip"
      data-followup-question="${escapeHtml(action.question)}"
      data-summary-mode="${escapeHtml(action.mode || "")}"
    >${escapeHtml(action.label)}</button>
  `;
}

function showFollowUpDialog(payload) {
  if (Array.isArray(payload.answers)) {
    showBatchFollowUpDialog(payload.answers);
    return;
  }

  const clarifications = payload.clarifications || [];
  const warnings = payload.warnings || [];
  const requiredClarification = clarifications.find((item) => item.required);
  if (requiredClarification) {
    suppressNextOptionalFollowUp = false;
    openClarificationDialog("เลือกข้อมูลเพิ่มเติม", requiredClarification, warnings, payload);
    return;
  }

  if (suppressNextOptionalFollowUp) {
    suppressNextOptionalFollowUp = false;
    return;
  }

  const colorClarification = clarifications.find((item) => item.field === "color");
  if (colorClarification) {
    openClarificationDialog("เลือกสีที่ต้องการ", colorClarification, warnings, payload);
    return;
  }

  if (warnings.length) {
    openWarningDialogIfNeeded("คำถามค้นหากว้าง", warnings, warningDialogKey(payload, warnings));
  }
}

function showBatchFollowUpDialog(rows) {
  const requiredRows = rows.filter((row) => row.needs_clarification);
  if (requiredRows.length) {
    openWarningDialog(
      "ต้องระบุข้อมูลเพิ่ม",
      requiredRows.map((row) => `${row.question_id}: ${firstClarificationMessage(row)}`)
    );
    return;
  }

  const warnings = [];
  rows.forEach((row) => {
    (row.warnings || []).forEach((warning) => warnings.push(`${row.question_id}: ${warning}`));
  });
  if (warnings.length) {
    openWarningDialogIfNeeded("คำถามค้นหากว้าง", warnings, batchWarningDialogKey(rows, warnings));
  }
}

function firstClarificationMessage(row) {
  const [clarification] = row.clarifications || [];
  return clarification?.message || "Please clarify this row.";
}

function openClarificationDialog(title, clarification, warnings, result) {
  activeWarningKey = null;
  pendingClarification = {
    result,
    clarification,
    options: clarification.options || [],
  };
  clarificationTitle.textContent = title;
  clarificationMessage.textContent = clarification.message || "";
  renderWarningList(warnings);
  clarificationSelectLabel.hidden = false;
  clarificationSelect.hidden = false;
  applyClarificationButton.hidden = false;
  keepCurrentAnswerButton.hidden = false;
  keepCurrentAnswerButton.textContent = clarification.required ? "ยกเลิก" : "ใช้คำตอบปัจจุบัน";
  renderClarificationOptions(pendingClarification.options);
  clarificationModal.hidden = false;
  clarificationSelect.focus();
}

function openWarningDialogIfNeeded(title, warnings, key) {
  if (suppressNextOptionalFollowUp || acknowledgedWarningKeys.has(key)) {
    suppressNextOptionalFollowUp = false;
    return;
  }
  openWarningDialog(title, warnings, key);
}

function openWarningDialog(title, warnings, key) {
  pendingClarification = null;
  activeWarningKey = key || warningDialogKey(latestResult || {}, warnings);
  clarificationTitle.textContent = title;
  clarificationMessage.textContent = "";
  renderWarningList(warnings);
  clarificationSelectLabel.hidden = true;
  clarificationSelect.hidden = true;
  applyClarificationButton.hidden = true;
  keepCurrentAnswerButton.hidden = false;
  keepCurrentAnswerButton.textContent = "รับทราบ";
  clarificationModal.hidden = false;
  keepCurrentAnswerButton.focus();
}

function closeClarificationModal() {
  if (activeWarningKey) {
    acknowledgedWarningKeys.add(activeWarningKey);
  }
  pendingClarification = null;
  activeWarningKey = null;
  clarificationModal.hidden = true;
}

function warningDialogKey(payload, warnings) {
  const questionKey = payload.normalized_question || payload.original_question || payload.answer || questionInput.value.trim();
  return `${questionKey}::${(warnings || []).join("|")}`;
}

function batchWarningDialogKey(rows, warnings) {
  const rowKey = (rows || []).map((row) => row.question_id || row.composed_question || row.query || "").join("|");
  return `${rowKey}::${(warnings || []).join("|")}`;
}

function renderWarningList(warnings) {
  warningList.innerHTML = "";
  (warnings || []).forEach((warning) => {
    const item = document.createElement("li");
    item.textContent = warning;
    warningList.appendChild(item);
  });
  warningList.hidden = !warnings?.length;
}

function renderClarificationOptions(options) {
  clarificationSelect.innerHTML = "";
  options.forEach((option, index) => {
    const item = document.createElement("option");
    item.value = String(index);
    item.textContent = optionLabel(option);
    clarificationSelect.appendChild(item);
  });
}

function optionLabel(option) {
  const label = option.label || option.value || "";
  return typeof option.count === "number" ? `${label} (${option.count})` : label;
}

function buildClarifiedQuestion(result, clarification, option) {
  const override = {};
  if (clarification.field === "date") {
    override.date = option.date || option.value;
  }
  if (clarification.field === "color") {
    override.colors = option.colors || [option.value];
  }
  return buildStructuredQuestion(result.query || {}, override);
}

function buildStructuredQuestion(query, override = {}) {
  const parts = [];
  const replacingIntent = Boolean(override.mode || override.event || override.unclosedEntry);
  const date = override.date || query.date;
  if (date) {
    parts.push(`date ${date}`);
  }
  if (query.cctv_id) {
    parts.push(query.cctv_id);
  }
  if (query.start_time && query.end_time) {
    parts.push(`from ${query.start_time} to ${query.end_time}`);
  }
  if (query.brand) {
    parts.push(`brand ${query.brand}`);
  }
  if (Array.isArray(query.brand_origins) && query.brand_origins.length) {
    parts.push(`origin ${query.brand_origins.join(" and ")}`);
  }
  const queryColors = Array.isArray(query.colors) && query.colors.length ? query.colors : (query.color ? [query.color] : []);
  const colors = override.colors || queryColors;
  if (colors.length) {
    parts.push(`color ${colors.join(" and ")}`);
  }
  if (query.vehicle_type) {
    parts.push(`type ${query.vehicle_type}`);
  }
  if (override.event) {
    parts.push(`event ${override.event}`);
  } else if (!replacingIntent && query.event) {
    parts.push(`event ${query.event}`);
  }
  if (!replacingIntent && Array.isArray(query.events) && query.events.length) {
    parts.push(`events ${query.events.join(" and ")}`);
  }
  if (query.wants_distinct_vehicle_count) {
    parts.push("distinct vehicles");
  }
  if (override.unclosedEntry && override.mode !== "unclosed_entry_camera") {
    parts.push("entry without exit");
  } else if (!replacingIntent && query.wants_unclosed_entry_count) {
    parts.push("entry without exit");
  }
  if (!replacingIntent && query.wants_event_breakdown) {
    parts.push("by event");
  }
  if (!replacingIntent && query.wants_peak_hour) {
    parts.push("busiest hour");
  }
  if (!replacingIntent && query.wants_peak_camera) {
    parts.push("busiest camera");
  }
  if (!replacingIntent && query.wants_hour_breakdown) {
    parts.push("by hour");
  }
  if (!replacingIntent && query.wants_camera_breakdown) {
    parts.push("by camera");
  }
  if (!replacingIntent && query.wants_vehicle_list) {
    parts.push("list vehicles");
  }
  if (!replacingIntent && query.wants_route) {
    parts.push("route");
  }
  if (override.mode && !override.event && !(override.unclosedEntry && override.mode === "event")) {
    parts.push(followUpModeQuestionPhrase(override.mode));
  } else if (!replacingIntent && Array.isArray(query.cross_breakdowns) && query.cross_breakdowns.length) {
    parts.push(crossBreakdownQuestionPhrase(query.cross_breakdowns[0]));
  } else if (!replacingIntent && query.wants_origin_brand_breakdown) {
    parts.push("by country and brand");
  } else if (!replacingIntent && query.wants_origin_breakdown) {
    parts.push("by country");
  } else if (!replacingIntent && query.wants_brand_color_breakdown) {
    parts.push("by brand and color");
  }
  return parts.join(" ") || query.raw_question || questionInput.value.trim();
}

function crossBreakdownQuestionPhrase(name) {
  return {
    origin_brand: "by country and brand",
    origin_type: "by country and type",
    brand_type: "by brand and type",
    camera_event: "by camera and event",
    hour_event: "by hour and event",
    color_type: "by color and type",
    origin_color: "by country and color",
    route_od: "by route start and end",
    brand_route: "by brand and route",
    unclosed_entry_camera: "entry without exit by camera",
  }[name] || name;
}

function followUpModeQuestionPhrase(mode) {
  if (CROSS_SUMMARY_MODES.has(mode)) {
    return crossBreakdownQuestionPhrase(mode);
  }
  return {
    brand: "by brand",
    color: "by color",
    type: "by type",
    event: "by event",
    origin: "by country",
    brand_color: "by brand and color",
  }[mode] || mode;
}

function selectedFilters() {
  return {
    date: dateFilter.value,
    cctv_id: cctvFilter.value,
    start_time: startTimeFilter.value,
    end_time: endTimeFilter.value,
  };
}

function hasSelectedFilters(filters) {
  return Boolean(filters.date || filters.cctv_id || filters.start_time || filters.end_time);
}

async function loadMetadata() {
  try {
    const response = await fetch("/api/metadata");
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Could not load filters");
    }
    populateSelect(dateFilter, payload.dates || [], "ทุกวันที่");
    populateSelect(cctvFilter, payload.cctv_ids || [], "ทุกกล้อง");
  } catch (error) {
    console.warn(error.message);
  }
}

function populateSelect(select, values, emptyLabel) {
  const currentValue = select.value;
  select.innerHTML = "";
  const empty = document.createElement("option");
  empty.value = "";
  empty.textContent = emptyLabel;
  select.appendChild(empty);
  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.appendChild(option);
  });
  if (values.includes(currentValue)) {
    select.value = currentValue;
  }
}

function summaryModeForResult(result) {
  if (summaryModeOverride) {
    return summaryModeOverride;
  }
  const [crossName] = result.query?.cross_breakdowns || [];
  if (crossName) {
    return crossName;
  }
  const inferred = inferSummaryModeFromQuestion(result.query?.raw_question || result.original_question || "");
  if (inferred) {
    return inferred;
  }
  if (result.query?.wants_event_breakdown) {
    return "event";
  }
  if (result.query?.wants_origin_breakdown) {
    return "origin";
  }
  if (result.query?.wants_brand_color_breakdown) {
    return "brand_color";
  }
  return "brand";
}

function inferSummaryModeFromQuestion(question) {
  const text = String(question || "").toLowerCase();
  const has = (terms) => terms.some((term) => text.includes(term));
  const origin = has(["country", "origin", "region", "ประเทศ", "สัญชาติ"]);
  const brand = has(["brand", "ยี่ห้อ"]);
  const color = has(["color", "colour", "สี"]);
  const type = has(["type", "ประเภทรถ", "ประเภท"]);
  const event = has(["event", "entry", "exit", "pass", "เข้า", "ออก", "ผ่าน"]);
  const camera = has(["camera", "cctv", "กล้อง"]);
  const hour = has(["hour", "time", "ชั่วโมง", "เวลา"]);
  const route = has(["route", "path", "เส้นทาง", "เดินทาง"]);
  const startEnd = has(["start", "end", "from", "to", "ต้นทาง", "ปลายทาง", "จาก", "ไป"]);

  if (origin && brand) return "origin_brand";
  if (origin && type) return "origin_type";
  if (brand && type) return "brand_type";
  if (camera && event) return "camera_event";
  if (hour && event) return "hour_event";
  if (color && type) return "color_type";
  if (origin && color) return "origin_color";
  if (route && startEnd) return "route_od";
  if (brand && route) return "brand_route";
  if (origin) return "origin";
  if (brand && color) return "brand_color";
  if (brand) return "brand";
  if (color) return "color";
  if (type) return "type";
  if (event) return "event";
  return null;
}

function summaryTableRows(result) {
  const mode = summaryModeForResult(result);
  if (CROSS_SUMMARY_MODES.has(mode)) {
    return result.summary?.cross_counts?.[mode] || [];
  }
  if (mode === "brand_color") return result.summary?.brand_color_counts || [];
  if (mode === "brand") return namedSummaryRows(result.summary?.brand_counts);
  if (mode === "color") return namedSummaryRows(result.summary?.color_counts);
  if (mode === "type") return namedSummaryRows(result.summary?.type_counts);
  if (mode === "event") return namedSummaryRows(result.summary?.event_counts);
  if (mode === "origin") return namedSummaryRows(result.summary?.origin_counts);
  return result.summary?.brand_color_counts || [];
}

function summaryTableColumns(result) {
  const mode = summaryModeForResult(result);
  if (CROSS_SUMMARY_MODES.has(mode)) {
    const labels = crossBreakdownColumnLabels(mode);
    return [
      { key: "left", label: labels[0] },
      { key: "right", label: labels[1] },
      { key: "count", label: "Count" },
    ];
  }
  if (mode === "brand_color") {
    return [
      { key: "brand", label: "Brand" },
      { key: "color", label: "Color" },
      { key: "count", label: "Count" },
    ];
  }
  return [
    { key: "name", label: summaryModeLabel(mode) },
    { key: "count", label: "Count" },
  ];
}

const CROSS_SUMMARY_MODES = new Set([
  "origin_brand",
  "origin_type",
  "brand_type",
  "camera_event",
  "hour_event",
  "color_type",
  "origin_color",
  "route_od",
  "brand_route",
  "unclosed_entry_camera",
]);

function crossBreakdownColumnLabels(name) {
  return {
    origin_brand: ["Origin", "Brand"],
    origin_type: ["Origin", "Type"],
    brand_type: ["Brand", "Type"],
    camera_event: ["Camera", "Event"],
    hour_event: ["Hour", "Event"],
    color_type: ["Color", "Type"],
    origin_color: ["Origin", "Color"],
    route_od: ["Start", "End"],
    brand_route: ["Brand", "Route"],
    unclosed_entry_camera: ["Camera", "Status"],
  }[name] || ["Group", "Value"];
}

function summaryModeLabel(mode) {
  return {
    brand: "Brand",
    color: "Color",
    type: "Type",
    event: "Event",
    origin: "Country",
    brand_color: "Brand × Color",
    origin_brand: "Country × Brand",
    origin_type: "Country × Type",
    brand_type: "Brand × Type",
    camera_event: "Camera × Event",
    hour_event: "Hour × Event",
    color_type: "Color × Type",
    origin_color: "Country × Color",
    route_od: "Start × End",
    brand_route: "Brand × Route",
    unclosed_entry_camera: "Open Entry × Camera",
  }[mode] || "Current breakdown";
}

function namedSummaryRows(counts) {
  return Object.entries(counts || {}).map(([name, count]) => ({ name, count }));
}

function renderSummaryOverview(result) {
  const summary = result.summary || {};
  const cards = [
    ["Brands", namedSummaryRows(summary.brand_counts)],
    ["Colors", namedSummaryRows(summary.color_counts)],
    ["Types", namedSummaryRows(summary.type_counts)],
    ["Events", namedSummaryRows(summary.event_counts)],
    ["Countries", namedSummaryRows(summary.origin_counts)],
  ];
  summaryOverview.innerHTML = cards.map(([title, rows]) => summaryCardHtml(title, rows)).join("");
}

function summaryCardHtml(title, rows) {
  const topRows = [...rows].sort((a, b) => Number(b.count) - Number(a.count) || a.name.localeCompare(b.name)).slice(0, 5);
  const items = topRows.length
    ? topRows.map((row) => `<li>${escapeHtml(row.name)} <strong>${escapeHtml(row.count)}</strong></li>`).join("")
    : "<li>No rows</li>";
  return `<section class="summary-card"><h3>${escapeHtml(title)}</h3><ol>${items}</ol></section>`;
}

function renderSummary(rows, columns = summaryTableColumns({}), title = "Current breakdown") {
  summaryTitle.textContent = title;
  summaryHead.innerHTML = columns.map((column) => `<th>${escapeHtml(column.label)}</th>`).join("");
  summaryRows.innerHTML = "";
  if (!rows.length) {
    const row = document.createElement("tr");
    row.innerHTML = `<td colspan="${columns.length}">No rows</td>`;
    summaryRows.appendChild(row);
    return;
  }

  [...rows]
    .sort((a, b) => Number(b.count) - Number(a.count) || String(a.left || a.name || a.brand || "").localeCompare(String(b.left || b.name || b.brand || "")))
    .forEach((item) => {
    const row = document.createElement("tr");
    row.innerHTML = columns.map((column) => `<td>${escapeHtml(item[column.key])}</td>`).join("");
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
  latestSql = null;
  answerOutput.classList.add("error");
  answerOutput.textContent = message;
  jsonOutput.textContent = "{}";
  csvOutput.textContent = "Question ID,Answer";
  exportCsvButton.disabled = true;
  countMetric.textContent = "-";
  eventMetric.textContent = "-";
  routeMetric.textContent = "-";
  followUpActions.hidden = true;
  followUpActions.innerHTML = "";
  summaryRows.innerHTML = "";
  summaryOverview.innerHTML = "";
  summaryTitle.textContent = "Current breakdown";
  routeList.textContent = "";
  batchRows.innerHTML = "";
  sqlTableSelect.innerHTML = "";
  sqlTableHead.innerHTML = "";
  sqlRows.innerHTML = "";
  sqlOutput.textContent = "";
  sqlMeta.textContent = "No SQL table";
  exportSqlCsvButton.disabled = true;
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
