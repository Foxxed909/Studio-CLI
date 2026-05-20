// StudioCLI Companion — background service worker
let studioUrl = "http://localhost:3456";
let sessionId = null;
let captureInterval = null;
let isActive = false;
let _quality = 60;      // jpeg quality 10–90
let _serverOk = true;   // tracks server reachability
let _failStreak = 0;    // consecutive fetch failures
let _reconnectTimer = null;

// ── Keyboard shortcut: Ctrl+Shift+S toggles capture ──────────────────────────
chrome.commands.onCommand.addListener((command) => {
  if (command === "toggle-capture") {
    if (isActive) {
      stopCapture();
      chrome.storage.local.set({ active: false, sessionId: null });
    } else {
      sessionId = "cs_" + Date.now().toString(36);
      isActive  = true;
      chrome.storage.local.set({ active: true, sessionId });
      startCapture();
    }
  }
});

// ── Restore state after service worker restart ────────────────────────────────
chrome.storage.local.get(["studioUrl", "sessionId", "active", "quality"], data => {
  if (data.studioUrl) studioUrl = data.studioUrl;
  if (data.sessionId) sessionId = data.sessionId;
  if (data.quality)   _quality  = data.quality;
  if (data.active && sessionId) {
    isActive = true;
    startCapture();
  }
});

// ── Message bus from popup + content scripts ──────────────────────────────────
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "START") {
    studioUrl = msg.studioUrl || studioUrl;
    _quality  = msg.quality  || _quality;
    sessionId = "cs_" + Date.now().toString(36);
    isActive  = true;
    chrome.storage.local.set({ active: true, sessionId, studioUrl, quality: _quality });
    startCapture();
    sendResponse({ ok: true, sessionId });
  }

  if (msg.type === "STOP") {
    stopCapture();
    chrome.storage.local.set({ active: false, sessionId: null });
    sendResponse({ ok: true });
  }

  if (msg.type === "GET_STATUS") {
    sendResponse({ active: isActive, sessionId, studioUrl, serverOk: _serverOk, quality: _quality });
  }

  if (msg.type === "SET_QUALITY") {
    _quality = Math.min(90, Math.max(10, msg.quality || 60));
    chrome.storage.local.set({ quality: _quality });
    sendResponse({ ok: true, quality: _quality });
  }

  if (msg.type === "CAPTURE_NOW") {
    captureAndSend().then(() => sendResponse({ ok: true }));
    return true;
  }

  if (msg.type === "CHECK_SERVER") {
    fetch(`${studioUrl}/api/health`, { signal: AbortSignal.timeout(3000) })
      .then(r => sendResponse({ ok: r.ok }))
      .catch(() => sendResponse({ ok: false }));
    return true;
  }

  if (msg.type === "ACTION_RESULT") {
    fetch(`${studioUrl}/api/computer/result`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessionId, result: msg.result })
    }).catch(() => {});
  }

  return true;
});

function startCapture() {
  stopCapture();
  captureAndSend();
  captureInterval = setInterval(async () => {
    await captureAndSend();
    await pollActions();
  }, 1500);
}

function stopCapture() {
  isActive = false;
  if (captureInterval) { clearInterval(captureInterval); captureInterval = null; }
  if (_reconnectTimer)  { clearTimeout(_reconnectTimer);  _reconnectTimer  = null; }
}

function _onServerFail() {
  _failStreak++;
  if (_failStreak >= 4 && _serverOk) {
    _serverOk = false;
    chrome.action.setBadgeText({ text: "!" });
    chrome.action.setBadgeBackgroundColor({ color: "#d97757" });
    // Poll for recovery every 5s
    _scheduleReconnect();
  }
}

function _onServerOk() {
  if (!_serverOk) {
    _serverOk = true;
    _failStreak = 0;
    chrome.action.setBadgeText({ text: "" });
    if (_reconnectTimer) { clearTimeout(_reconnectTimer); _reconnectTimer = null; }
  } else {
    _failStreak = 0;
  }
}

function _scheduleReconnect() {
  if (_reconnectTimer) return;
  _reconnectTimer = setTimeout(async () => {
    _reconnectTimer = null;
    try {
      const r = await fetch(`${studioUrl}/api/health`, { signal: AbortSignal.timeout(3000) });
      if (r.ok) { _onServerOk(); }
      else { _scheduleReconnect(); }
    } catch { _scheduleReconnect(); }
  }, 5000);
}

async function captureAndSend() {
  if (!isActive) return;
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.id) return;
    if (tab.url?.startsWith("chrome-extension://") || tab.url?.startsWith("chrome://")) return;

    const dataUrl = await chrome.tabs.captureVisibleTab(null, { format: "jpeg", quality: _quality });
    const r = await fetch(`${studioUrl}/api/computer/screenshot`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: AbortSignal.timeout(5000),
      body: JSON.stringify({
        sessionId,
        screenshot: dataUrl,
        url:    tab.url,
        title:  tab.title,
        width:  tab.width  || screen.width  || 1280,
        height: tab.height || screen.height || 720,
      })
    });
    if (r.ok) { _onServerOk(); }
    else      { _onServerFail(); }
  } catch (e) {
    if (e.name !== "AbortError") _onServerFail();
  }
}

async function pollActions() {
  if (!isActive || !sessionId) return;
  try {
    const r = await fetch(`${studioUrl}/api/computer/actions?session=${sessionId}`,
      { signal: AbortSignal.timeout(4000) });
    if (!r.ok) return;
    const { actions } = await r.json();
    if (!actions?.length) return;

    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id) return;

    await chrome.tabs.sendMessage(tab.id, { type: "EXECUTE_ACTIONS", actions, sessionId });
  } catch (e) {}
}
