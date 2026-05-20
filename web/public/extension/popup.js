const $ = id => document.getElementById(id);

const dot        = $("dot");
const statusText = $("statusText");
const sessionEl  = $("sessionId");
const btnStart   = $("btnStart");
const btnStop    = $("btnStop");
const urlInput   = $("urlInput");
const logEl      = $("log");
const qualityEl  = $("quality");
const tabInfoEl  = $("tabInfo");
const serverEl   = $("serverStatus");

let _sessionId = null;

// ── Logging ───────────────────────────────────────────────────────────────────
function log(msg, type = "info") {
  const now = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const line = document.createElement("div");
  line.style.cssText = type === "ok"  ? "color:#7fb685" :
                       type === "err" ? "color:#e06c75" : "";
  line.textContent = `[${now}] ${msg}`;
  logEl.appendChild(line);
  logEl.scrollTop = logEl.scrollHeight;
  // cap at 50 lines
  while (logEl.children.length > 50) logEl.removeChild(logEl.firstChild);
}

// ── Status display ────────────────────────────────────────────────────────────
function setActive(active, sid) {
  _sessionId = sid || null;
  if (active) {
    dot.className = "dot on";
    statusText.textContent = "Active — capturing";
    sessionEl.textContent  = sid ? sid.slice(-8) : "";
    btnStart.style.display = "none";
    btnStop.style.display  = "";
    if (qualityEl) qualityEl.disabled = true;
  } else {
    dot.className = "dot off";
    statusText.textContent = "Inactive";
    sessionEl.textContent  = "";
    btnStart.style.display = "";
    btnStop.style.display  = "none";
    if (qualityEl) qualityEl.disabled = false;
  }
}

function setServerStatus(ok) {
  if (!serverEl) return;
  serverEl.textContent = ok ? "Server reachable" : "Server unreachable";
  serverEl.style.color = ok ? "rgba(127,182,133,.7)" : "rgba(224,108,117,.7)";
}

// ── Tab info ──────────────────────────────────────────────────────────────────
function updateTabInfo() {
  chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) => {
    if (!tabInfoEl || !tab) return;
    const url = tab.url || "";
    const title = tab.title || "";
    if (url.startsWith("chrome://") || url.startsWith("chrome-extension://")) {
      tabInfoEl.textContent = "Chrome page — not capturable";
      tabInfoEl.style.color = "rgba(224,108,117,.6)";
    } else {
      tabInfoEl.textContent = title || url;
      tabInfoEl.style.color = "";
    }
  });
}

// ── Restore from storage + background status ──────────────────────────────────
chrome.storage.local.get(["studioUrl", "active", "sessionId", "quality"], data => {
  if (data.studioUrl) urlInput.value = data.studioUrl;
  if (data.quality && qualityEl) qualityEl.value = data.quality;
  if (data.active && data.sessionId) {
    setActive(true, data.sessionId);
    log("Session resumed: " + data.sessionId.slice(-8), "ok");
  }
});

chrome.runtime.sendMessage({ type: "GET_STATUS" }, res => {
  if (chrome.runtime.lastError) return;
  if (res) {
    setActive(res.active, res.sessionId);
    setServerStatus(res.serverOk !== false);
    if (res.quality && qualityEl) qualityEl.value = res.quality;
  }
});

// Check server connectivity
chrome.runtime.sendMessage({ type: "CHECK_SERVER" }, res => {
  if (chrome.runtime.lastError) return;
  setServerStatus(res?.ok === true);
});

updateTabInfo();

// ── Controls ──────────────────────────────────────────────────────────────────
btnStart.addEventListener("click", () => {
  const url     = urlInput.value.trim() || "http://localhost:3456";
  const quality = qualityEl ? parseInt(qualityEl.value) || 60 : 60;
  chrome.storage.local.set({ studioUrl: url });
  chrome.runtime.sendMessage({ type: "START", studioUrl: url, quality }, res => {
    if (chrome.runtime.lastError) {
      log("Error: " + chrome.runtime.lastError.message, "err"); return;
    }
    if (res?.ok) {
      setActive(true, res.sessionId);
      log("Started — session …" + res.sessionId.slice(-8), "ok");
    } else {
      log("Failed to start.", "err");
    }
  });
});

btnStop.addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "STOP" }, res => {
    if (chrome.runtime.lastError) {
      log("Error: " + chrome.runtime.lastError.message, "err"); return;
    }
    setActive(false, null);
    log("Stopped.");
  });
});

// Quality change
if (qualityEl) {
  qualityEl.addEventListener("change", () => {
    const q = parseInt(qualityEl.value) || 60;
    chrome.runtime.sendMessage({ type: "SET_QUALITY", quality: q }, () => {});
    log("Quality → " + q + "%");
  });
}

// Manual capture
const btnCapture = $("btnCapture");
if (btnCapture) {
  btnCapture.addEventListener("click", () => {
    chrome.runtime.sendMessage({ type: "CAPTURE_NOW" }, () => {
      log("Captured.");
    });
  });
}

// Refresh server check periodically while popup is open
setInterval(() => {
  chrome.runtime.sendMessage({ type: "CHECK_SERVER" }, res => {
    if (chrome.runtime.lastError) return;
    setServerStatus(res?.ok === true);
  });
  updateTabInfo();
}, 4000);
