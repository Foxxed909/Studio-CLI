// StudioCLI Companion — content script
let _cursor = null;
let _busy = false;

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "EXECUTE_ACTIONS") {
    if (_busy) { sendResponse({ ok: false, reason: "busy" }); return; }
    _busy = true;
    executeActions(msg.actions, msg.sessionId).then(result => {
      chrome.runtime.sendMessage({ type: "ACTION_RESULT", result });
      sendResponse({ ok: true });
      _busy = false;
    }).catch(() => { _busy = false; });
    return true;
  }
});

async function executeActions(actions, sessionId) {
  const results = [];
  for (const action of actions) {
    try {
      const r = await doAction(action);
      results.push({ action: action.type, ok: true, ...r });
      await sleep(action.delay ?? 120);
    } catch (e) {
      results.push({ action: action.type, ok: false, error: e.message });
    }
  }
  return results;
}

async function doAction(action) {
  switch (action.type) {

    case "click": {
      const el = elementAtPoint(action.x, action.y);
      showCursorFlash(action.x, action.y, "#d97757");
      if (el) {
        el.focus();
        el.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, clientX: action.x, clientY: action.y }));
        el.dispatchEvent(new MouseEvent("mouseup",   { bubbles: true, clientX: action.x, clientY: action.y }));
        el.click();
      } else {
        simulateClick(action.x, action.y);
      }
      return { x: action.x, y: action.y };
    }

    case "dblclick": {
      const el = elementAtPoint(action.x, action.y);
      showCursorFlash(action.x, action.y, "#d97757");
      if (el) {
        el.focus();
        el.dispatchEvent(new MouseEvent("dblclick", { bubbles: true, clientX: action.x, clientY: action.y }));
      }
      return { x: action.x, y: action.y };
    }

    case "type": {
      const el = document.activeElement;
      if (!el) return { text: action.text };
      if (el.isContentEditable) {
        // Use execCommand to avoid nuking child nodes
        el.focus();
        document.execCommand("insertText", false, action.text);
      } else if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") {
        const start = el.selectionStart ?? el.value.length;
        const end   = el.selectionEnd   ?? el.value.length;
        el.value = el.value.slice(0, start) + action.text + el.value.slice(end);
        el.selectionStart = el.selectionEnd = start + action.text.length;
        el.dispatchEvent(new Event("input",  { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
      } else {
        for (const ch of action.text) {
          el.dispatchEvent(new KeyboardEvent("keydown",  { key: ch, bubbles: true }));
          el.dispatchEvent(new KeyboardEvent("keypress", { key: ch, bubbles: true }));
          el.dispatchEvent(new KeyboardEvent("keyup",    { key: ch, bubbles: true }));
        }
      }
      return { text: action.text };
    }

    case "clear": {
      const el = document.activeElement;
      if (!el) return {};
      if (el.isContentEditable) {
        el.focus();
        document.execCommand("selectAll", false, null);
        document.execCommand("delete", false, null);
      } else if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") {
        el.value = "";
        el.dispatchEvent(new Event("input",  { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
      }
      return {};
    }

    case "key": {
      const target = document.activeElement || document.body;
      const opts = {
        key: action.key,
        code: action.code || action.key,
        ctrlKey:  !!action.ctrl,
        shiftKey: !!action.shift,
        altKey:   !!action.alt,
        metaKey:  !!action.meta,
        bubbles:  true,
        cancelable: true,
      };
      target.dispatchEvent(new KeyboardEvent("keydown", opts));
      target.dispatchEvent(new KeyboardEvent("keyup",   opts));
      return { key: action.key };
    }

    case "scroll": {
      const el = elementAtPoint(action.x, action.y) || document.scrollingElement;
      el.scrollBy({ top: action.dy || 0, left: action.dx || 0, behavior: action.smooth !== false ? "smooth" : "auto" });
      return { dy: action.dy, dx: action.dx };
    }

    case "scroll_to": {
      const el = action.selector ? document.querySelector(action.selector) : document.scrollingElement;
      if (el) el.scrollTo({ top: action.y ?? 0, left: action.x ?? 0, behavior: "smooth" });
      return {};
    }

    case "hover": {
      showCursorFlash(action.x, action.y, "#58a6ff");
      const el = elementAtPoint(action.x, action.y);
      if (el) {
        el.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
        el.dispatchEvent(new MouseEvent("mousemove", { bubbles: true, clientX: action.x, clientY: action.y }));
      }
      return { x: action.x, y: action.y };
    }

    case "navigate": {
      // Validate URL before navigating
      try { new URL(action.url); } catch { return { error: "invalid url" }; }
      window.location.href = action.url;
      return { url: action.url };
    }

    case "select": {
      const el = document.querySelector(action.selector);
      if (el) { el.focus(); el.click(); }
      return { selector: action.selector, found: !!el };
    }

    case "wait": {
      await sleep(action.ms || 500);
      return { ms: action.ms || 500 };
    }

    case "screenshot_mark": {
      showCursorFlash(action.x, action.y, action.color || "#d97757");
      return { x: action.x, y: action.y };
    }

    case "read_text": {
      const el = action.selector ? document.querySelector(action.selector) : document.body;
      return { text: el ? (el.innerText || el.textContent || "").slice(0, 2000) : "" };
    }

    default:
      return {};
  }
}

function elementAtPoint(x, y) {
  return document.elementFromPoint(x, y);
}

function simulateClick(x, y) {
  const target = elementAtPoint(x, y) || document.body;
  ["mousedown", "mouseup", "click"].forEach(t => {
    target.dispatchEvent(new MouseEvent(t, { clientX: x, clientY: y, bubbles: true, cancelable: true }));
  });
}

function showCursorFlash(x, y, color = "#d97757") {
  if (_cursor) _cursor.remove();
  _cursor = document.createElement("div");
  Object.assign(_cursor.style, {
    position:      "fixed",
    left:          `${x - 10}px`,
    top:           `${y - 10}px`,
    width:         "20px",
    height:        "20px",
    borderRadius:  "50%",
    background:    color,
    opacity:       "0.75",
    pointerEvents: "none",
    zIndex:        "2147483647",
    transition:    "opacity 0.4s",
    boxShadow:     `0 0 0 4px ${color}44`,
  });
  document.body.appendChild(_cursor);
  setTimeout(() => {
    if (_cursor) {
      _cursor.style.opacity = "0";
      setTimeout(() => _cursor?.remove(), 400);
    }
  }, 350);
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
