const HISTORY_KEY = "analysisHistory";
const THEME_KEY = "weblensTheme";
const HISTORY_LIMIT = 10;
const UI_REQUEST_TIMEOUT_MS = 35000;
const STAGE_ADVANCE_DELAY_MS = 700;

const state = {
  currentResultText: "",
  currentView: "smart",
};

const modeSelect = document.getElementById("modeSelect");
const taskInput = document.getElementById("taskInput");
const taskLabel = document.getElementById("taskLabel");
const languageSelect = document.getElementById("languageSelect");
const languageLabel = document.getElementById("languageLabel");
const detailSelect = document.getElementById("detailSelect");
const detailLabel = document.getElementById("detailLabel");
const outputEl = document.getElementById("output");
const rawOutputEl = document.getElementById("rawOutput");
const statusEl = document.getElementById("status");
const historyListEl = document.getElementById("historyList");
const analyzeBtn = document.getElementById("analyzeBtn");
const copyBtn = document.getElementById("copyBtn");
const downloadBtn = document.getElementById("downloadBtn");
const clearHistoryBtn = document.getElementById("clearHistoryBtn");
const smartViewBtn = document.getElementById("smartViewBtn");
const rawViewBtn = document.getElementById("rawViewBtn");
const reportModePill = document.getElementById("reportModePill");
const themeToggleBtn = document.getElementById("themeToggleBtn");
const iconMoon = document.getElementById("iconMoon");
const iconSun = document.getElementById("iconSun");
const stageRailEl = document.getElementById("stageRail");
const stageChipEls = stageRailEl ? Array.from(stageRailEl.querySelectorAll("[data-stage-chip]")) : [];

function isTaskMode(mode) {
  return mode === "fact_check";
}

function isTranslateMode(mode) {
  return mode === "translate";
}

function applyTheme(theme) {
  const normalized = theme === "dark" ? "dark" : "light";
  document.body.setAttribute("data-theme", normalized);
  if (themeToggleBtn) {
    themeToggleBtn.setAttribute("aria-label", normalized === "dark" ? "Switch to light mode" : "Switch to dark mode");
  }
  if (iconMoon && iconSun) {
    iconMoon.classList.toggle("hidden", normalized === "dark");
    iconSun.classList.toggle("hidden", normalized !== "dark");
  }
}

function initTheme() {
  chrome.storage.local.get([THEME_KEY], (data) => {
    const saved = data[THEME_KEY];
    applyTheme(saved || "light");
  });
}

function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.className = isError ? "status error" : "status";
}

function setRunning(isRunning) {
  analyzeBtn.disabled = isRunning;
  analyzeBtn.textContent = isRunning ? "Running..." : "Run";
}

function updateTaskVisibility() {
  const showTask = isTaskMode(modeSelect.value);
  const showLanguage = isTranslateMode(modeSelect.value);

  taskInput.style.display = showTask ? "block" : "none";
  taskLabel.style.display = showTask ? "block" : "none";
  languageSelect.style.display = showLanguage ? "block" : "none";
  languageLabel.style.display = showLanguage ? "block" : "none";

  // Detail controls are visible for all modes to keep output tuning simple.
  detailSelect.style.display = "block";
  detailLabel.style.display = "block";
}

function setStage(stage) {
  const order = ["extract", "analyze", "format"];
  const activeIndex = order.indexOf(stage);

  stageChipEls.forEach((chip, index) => {
    chip.classList.remove("active", "done");
    if (activeIndex < 0) {
      return;
    }
    if (index < activeIndex) {
      chip.classList.add("done");
      return;
    }
    if (index === activeIndex) {
      chip.classList.add("active");
    }
  });
}

function resetStage() {
  stageChipEls.forEach((chip) => chip.classList.remove("active", "done"));
}

async function copyText(text, successMessage = "Copied.") {
  try {
    await navigator.clipboard.writeText(text);
    setStatus(successMessage);
  } catch (error) {
    setStatus(`Copy failed: ${error.message}`, true);
  }
}

function createSection(title, copySourceFn) {
  const section = document.createElement("section");
  section.className = "report-section";

  const head = document.createElement("div");
  head.className = "section-head";

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "section-toggle";
  toggle.textContent = "Hide";

  const sectionTitle = document.createElement("h5");
  sectionTitle.className = "section-title";
  sectionTitle.textContent = title;

  const copy = document.createElement("button");
  copy.type = "button";
  copy.className = "section-copy";
  copy.textContent = "Copy";

  const body = document.createElement("div");
  body.className = "section-body";

  toggle.addEventListener("click", () => {
    const collapsed = body.classList.toggle("collapsed");
    toggle.textContent = collapsed ? "Show" : "Hide";
  });

  copy.addEventListener("click", () => {
    const text = (copySourceFn ? copySourceFn() : body.innerText || "").trim();
    if (!text) {
      setStatus("Nothing to copy in this section.", true);
      return;
    }
    copyText(text, `Copied section: ${title}`);
  });

  head.appendChild(toggle);
  head.appendChild(sectionTitle);
  head.appendChild(copy);
  section.appendChild(head);
  section.appendChild(body);
  return { section, body };
}

function normalizeLines(text) {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

function splitIntoSentences(text) {
  return text
    .split(/(?<=[.!?])\s+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

function createPointItem(text) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "point-item";
  if (/reason:|error|invalid|missing|timeout/i.test(text)) {
    btn.classList.add("warning");
  }

  const marker = document.createElement("span");
  marker.className = "point-marker";
  marker.textContent = "*";

  const body = document.createElement("span");
  body.className = "point-text";
  body.textContent = text;

  btn.appendChild(marker);
  btn.appendChild(body);
  btn.addEventListener("click", () => btn.classList.toggle("done"));
  return btn;
}

function renderJsonReport(parsed) {
  const card = document.createElement("div");
  card.className = "report-card";

  const heading = document.createElement("h4");
  heading.className = "report-title";
  heading.textContent = parsed.title || "Extracted Report";
  card.appendChild(heading);

  if (parsed.summary) {
    const summary = document.createElement("p");
    summary.className = "report-lead";
    summary.textContent = parsed.summary;
    card.appendChild(summary);
  }

  if (Array.isArray(parsed.key_points) && parsed.key_points.length) {
    const sectionCtrl = createSection("Key Points", () => parsed.key_points.join("\n"));
    parsed.key_points.forEach((point) => sectionCtrl.body.appendChild(createPointItem(point)));
    card.appendChild(sectionCtrl.section);
  }

  if (Array.isArray(parsed.entities) && parsed.entities.length) {
    const chips = document.createElement("div");
    chips.className = "report-chips";
    parsed.entities.forEach((entity) => {
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.textContent = entity;
      chips.appendChild(chip);
    });
    card.appendChild(chips);
  }

  outputEl.appendChild(card);
}

function renderTextReport(text) {
  const lines = normalizeLines(text);
  if (!lines.length) {
    outputEl.innerHTML = '<p class="report-placeholder">No content yet.</p>';
    return;
  }

  const card = document.createElement("div");
  card.className = "report-card";
  outputEl.appendChild(card);

  let currentSection = null;

  const ensureSection = (title) => {
    const sectionCtrl = createSection(title);
    card.appendChild(sectionCtrl.section);
    return sectionCtrl.body;
  };

  lines.forEach((line, index) => {
    const headingMatch = line.match(/^[A-Za-z][A-Za-z0-9\s\/\-]{1,80}:$/);
    const bullet = line.match(/^[-•]\s+(.*)$/);
    const numbered = line.match(/^\d+\.\s+(.*)$/);

    if (headingMatch) {
      currentSection = ensureSection(line.replace(/:$/, ""));
      return;
    }

    if (!currentSection) {
      currentSection = ensureSection(index === 0 ? "Highlights" : "Details");
    }

    if (bullet) {
      currentSection.appendChild(createPointItem(bullet[1]));
      return;
    }

    if (numbered) {
      currentSection.appendChild(createPointItem(numbered[1]));
      return;
    }

    if (line.length > 140 && /[.!?]/.test(line)) {
      splitIntoSentences(line)
        .slice(0, 4)
        .forEach((sentence) => currentSection.appendChild(createPointItem(sentence)));
      return;
    }

    const para = document.createElement("p");
    para.className = index === 0 ? "report-lead" : "report-paragraph";
    para.textContent = line;
    currentSection.appendChild(para);
  });
}

function renderReport(text) {
  state.currentResultText = text || "";
  rawOutputEl.textContent = state.currentResultText;
  outputEl.innerHTML = "";

  if (!state.currentResultText.trim()) {
    outputEl.innerHTML = '<p class="report-placeholder">Run an analysis to see an interactive report.</p>';
    return;
  }

  try {
    const parsed = JSON.parse(state.currentResultText);
    renderJsonReport(parsed);
  } catch (error) {
    renderTextReport(state.currentResultText);
  }
}

function setView(view) {
  state.currentView = view;
  const smart = view === "smart";

  smartViewBtn.classList.toggle("active", smart);
  rawViewBtn.classList.toggle("active", !smart);

  outputEl.classList.toggle("hidden", !smart);
  rawOutputEl.classList.toggle("hidden", smart);

  reportModePill.textContent = smart ? "Smart" : "Raw";
}

function saveHistoryEntry(entry) {
  chrome.storage.local.get([HISTORY_KEY], (data) => {
    const items = Array.isArray(data[HISTORY_KEY]) ? data[HISTORY_KEY] : [];
    const next = [entry, ...items].slice(0, HISTORY_LIMIT);
    chrome.storage.local.set({ [HISTORY_KEY]: next }, () => renderHistory(next));
  });
}

function renderHistory(items) {
  historyListEl.innerHTML = "";

  if (!items.length) {
    const li = document.createElement("li");
    li.className = "history-empty";
    li.textContent = "No history yet.";
    historyListEl.appendChild(li);
    return;
  }

  items.forEach((item) => {
    const li = document.createElement("li");
    li.className = "history-item";
    const tagParts = [item.mode];
    if (item.mode === "translate" && item.language) {
      tagParts.push(item.language);
    }
    if (item.detail) {
      tagParts.push(item.detail);
    }
    li.textContent = `[${tagParts.join(" • ")}] ${item.result.slice(0, 90)}${item.result.length > 90 ? "..." : ""}`;
    li.title = new Date(item.timestamp).toLocaleString();
    li.addEventListener("click", () => {
      renderReport(item.result);
      setStatus(`Loaded from history (${new Date(item.timestamp).toLocaleTimeString()}).`);
    });
    historyListEl.appendChild(li);
  });
}

function loadHistory() {
  chrome.storage.local.get([HISTORY_KEY], (data) => {
    const items = Array.isArray(data[HISTORY_KEY]) ? data[HISTORY_KEY] : [];
    renderHistory(items);
  });
}

analyzeBtn.addEventListener("click", () => {
  const mode = modeSelect.value;
  const task = taskInput.value.trim();
  const language = (languageSelect.value || "Hindi").trim();
  const detail = (detailSelect.value || "short").trim();

  if (isTaskMode(mode) && !task) {
    setStatus("Please add a task for this mode.", true);
    return;
  }

  setRunning(true);
  setStatus("Extracting readable content...");
  setStage("extract");

  const stageTimer = setTimeout(() => {
    setStatus("Analyzing with model...");
    setStage("analyze");
  }, STAGE_ADVANCE_DELAY_MS);

  const watchdog = setTimeout(() => {
    clearTimeout(stageTimer);
    setRunning(false);
    resetStage();
    setStatus("Request took too long. Check backend server logs and try again.", true);
  }, UI_REQUEST_TIMEOUT_MS);

  chrome.runtime.sendMessage(
    {
      action: "ANALYZE_PAGE",
      mode,
      task,
      language,
      detail,
    },
    (response) => {
      clearTimeout(stageTimer);
      clearTimeout(watchdog);
      setRunning(false);
      setStage("format");

      if (chrome.runtime.lastError) {
        renderReport("");
        resetStage();
        setStatus(`Runtime error: ${chrome.runtime.lastError.message}`, true);
        return;
      }

      if (!response || !response.result) {
        renderReport("");
        resetStage();
        setStatus("No result returned.", true);
        return;
      }

      renderReport(response.result);
      setStatus("Done.");
      setTimeout(resetStage, 900);

      saveHistoryEntry({
        timestamp: Date.now(),
        mode,
        task,
        language,
        detail,
        result: response.result,
      });
    }
  );
});

copyBtn.addEventListener("click", async () => {
  if (!state.currentResultText.trim()) {
    setStatus("Nothing to copy yet.", true);
    return;
  }

  await copyText(state.currentResultText, "Copied to clipboard.");
});

downloadBtn.addEventListener("click", () => {
  const content = state.currentResultText.trim();
  if (!content) {
    setStatus("Nothing to download yet.", true);
    return;
  }

  const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `weblens-${modeSelect.value}-${Date.now()}.txt`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  setStatus("Downloaded result.");
});

clearHistoryBtn.addEventListener("click", () => {
  chrome.storage.local.set({ [HISTORY_KEY]: [] }, () => {
    renderHistory([]);
    setStatus("History cleared.");
  });
});

themeToggleBtn.addEventListener("click", () => {
  const current = document.body.getAttribute("data-theme") || "light";
  const next = current === "dark" ? "light" : "dark";
  applyTheme(next);
  chrome.storage.local.set({ [THEME_KEY]: next });
});

smartViewBtn.addEventListener("click", () => setView("smart"));
rawViewBtn.addEventListener("click", () => setView("raw"));

modeSelect.addEventListener("change", updateTaskVisibility);
initTheme();
updateTaskVisibility();
setView("smart");
resetStage();
loadHistory();
