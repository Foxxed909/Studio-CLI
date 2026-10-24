/* StudioCLI web extras (v9.8) — self-contained in-app enhancements.
   Adds a floating quick-dock + shortcuts, built defensively from the
   documented localStorage keys (studioConvos / studioTheme). Safe to load
   anywhere; if an element/global is missing it degrades quietly. */
(function () {
  "use strict";
  if (window.__studioExtras) return;
  window.__studioExtras = true;

  // ── styles ────────────────────────────────────────────────────────────────
  var css = document.createElement("style");
  css.textContent =
    "#qdock{position:fixed;right:14px;bottom:96px;display:flex;flex-direction:column;gap:8px;z-index:60}" +
    "@media(max-width:900px){#qdock,#qcount{display:none!important}}" +
    ".qd-btn{width:38px;height:38px;border-radius:50%;background:var(--surface2,#161a22);" +
    "border:1px solid var(--border,rgba(148,163,184,.2));color:var(--text,#e7ebf0);cursor:pointer;" +
    "font-size:15px;display:flex;align-items:center;justify-content:center;transition:.15s;box-shadow:0 2px 10px rgba(0,0,0,.4)}" +
    ".qd-btn:hover{border-color:var(--acc,#d97757);transform:translateY(-1px)}" +
    "#scOv{position:fixed;inset:0;background:rgba(0,0,0,.55);display:none;align-items:center;justify-content:center;z-index:70}" +
    "#scOv.on{display:flex}#scBox{max-width:440px;width:90%;background:var(--surface,#0f1117);" +
    "border:1px solid var(--border,rgba(148,163,184,.2));border-radius:14px;padding:22px;color:var(--text,#e7ebf0)}" +
    "#scBox h3{margin:0 0 12px}#scBox .k{display:flex;justify-content:space-between;font-size:13px;color:var(--text2,#b9b2a8);padding:4px 0}" +
    "#scBox code{background:#0a0d13;border:1px solid var(--border,#333);border-radius:5px;padding:1px 7px;color:var(--acc,#d97757)}" +
    "#qcount{position:fixed;right:60px;bottom:24px;font-size:11px;color:var(--text2,#b9b2a8);z-index:60;pointer-events:none}" +
    "body.studio-focus .sidebar{display:none!important}";
  document.head.appendChild(css);

  function el(tag, attrs, html) {
    var e = document.createElement(tag);
    if (attrs) for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (html != null) e.innerHTML = html;
    return e;
  }
  function stageToken() {
    try {
      for (var i = 0; i < localStorage.length; i++) {
        var key = localStorage.key(i);
        if (key && key.indexOf("sb-") === 0 && key.endsWith("-auth-token")) {
          var value = JSON.parse(localStorage.getItem(key));
          return (value && (value.access_token || (value.currentSession && value.currentSession.access_token))) || null;
        }
      }
    } catch (e) {}
    return null;
  }

  function toastMsg(m) { try { if (window.toast) return window.toast(m); } catch (e) {} }

  // ── conversation helpers (from localStorage) ────────────────────────────────
  function convos() { try { return JSON.parse(localStorage.getItem("studioConvos") || "[]"); } catch (e) { return []; } }
  function activeConvo() { var c = convos(); return c && c.length ? c[0] : null; }
  function convoToMd(c) {
    if (!c) return "";
    var msgs = c.messages || [];
    return "# " + (c.title || "Conversation") + "\n\n" + msgs.map(function (m) {
      var who = (m.role === "user") ? "You" : "Studio";
      return "**" + who + ":**\n\n" + (m.content || m.text || "");
    }).join("\n\n---\n\n");
  }
  function download(name, text, type) {
    var blob = new Blob([text], { type: type || "text/plain" });
    var url = URL.createObjectURL(blob);
    var a = el("a"); a.href = url; a.download = name; document.body.appendChild(a); a.click();
    setTimeout(function () { a.remove(); URL.revokeObjectURL(url); }, 100);
  }

  // ── feature actions ─────────────────────────────────────────────────────────
  function scrollContainer() {
    // pick the tallest scrollable element, else the window
    var best = null, max = 0;
    document.querySelectorAll("main,section,div").forEach(function (n) {
      if (n.scrollHeight > n.clientHeight + 40 && n.clientHeight > 200) {
        var s = n.scrollHeight; if (s > max) { max = s; best = n; }
      }
    });
    return best;
  }
  window.qdBottom = function () { var c = scrollContainer(); if (c) c.scrollTo({ top: c.scrollHeight, behavior: "smooth" }); else window.scrollTo({ top: 1e9, behavior: "smooth" }); };
  window.qdTop = function () { var c = scrollContainer(); if (c) c.scrollTo({ top: 0, behavior: "smooth" }); else window.scrollTo({ top: 0, behavior: "smooth" }); };
  window.qdCopy = function () {
    var md = convoToMd(activeConvo());
    if (!md) return toastMsg("No conversation to copy");
    (navigator.clipboard ? navigator.clipboard.writeText(md) : Promise.reject()).then(
      function () { toastMsg("📋 Conversation copied as Markdown"); },
      function () { toastMsg("Clipboard unavailable"); }
    );
  };
  window.qdExport = function (fmt) {
    var c = activeConvo();
    if (!c) return toastMsg("No conversation to export");
    var name = (c.title || "conversation").replace(/[^a-z0-9]+/gi, "-").toLowerCase();
    if (fmt === "json") download(name + ".json", JSON.stringify(c, null, 2), "application/json");
    else download(name + ".md", convoToMd(c), "text/markdown");
    toastMsg("⬇ Exported " + fmt.toUpperCase());
  };
  var THEME_POOL = ["nebula","galaxy","aurora-borealis","ocean-depths","fireflies","vaporwave",
                    "matrix-rain","sunrise","thunderstorm","volcano","blizzard","crt"];
  window.qdShuffleTheme = function () {
    var t = THEME_POOL[Math.floor(Math.random() * THEME_POOL.length)];
    try { localStorage.setItem("studioTheme", t); } catch (e) {}
    if (window.applyTheme) { try { window.applyTheme(t); toastMsg("🎲 Theme: " + t); return; } catch (e) {} }
    document.documentElement.setAttribute("data-theme", t); toastMsg("🎲 Theme: " + t);
  };
  window.qdFocus = function () {
    document.body.classList.toggle("studio-focus");
    toastMsg(document.body.classList.contains("studio-focus") ? "🧘 Focus mode on" : "Focus mode off");
  };
  window.qdShortcuts = function () { document.getElementById("scOv").classList.add("on"); };
  window.qdFeedback = function () {
    var ex = document.getElementById("qfb"); if (ex) { ex.style.display = "flex"; return; }
    var ov = el("div", { id: "qfb" });
    ov.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;z-index:80";
    ov.innerHTML =
      '<div style="max-width:420px;width:90%;background:var(--surface,#141416);border:1px solid var(--border,#333);border-radius:16px;padding:22px;color:var(--text,#ededee)">' +
      '<h3 style="margin:0 0 4px">Send feedback</h3>' +
      '<p style="color:var(--text2,#b9b2a8);font-size:13px;margin:0 0 14px">Bugs, ideas, or love — it lands in the team inbox.</p>' +
      '<div style="display:flex;gap:6px;margin-bottom:10px">' +
      ["bug", "idea", "praise", "other"].map(function (k, i) {
        return '<button data-k="' + k + '" class="qfbk-b" style="flex:1;padding:7px;border-radius:8px;border:1px solid var(--border,#333);background:' +
          (i === 0 ? "var(--acc,#d97757);color:#04121a" : "transparent;color:var(--text2,#b9b2a8)") +
          ';cursor:pointer;font:inherit;font-size:12px;text-transform:capitalize">' + k + "</button>";
      }).join("") + "</div>" +
      '<textarea id="qfbm" rows="4" placeholder="What\'s on your mind?" style="width:100%;background:#0a0d13;border:1px solid var(--border,#333);border-radius:10px;color:var(--text,#ededee);padding:11px;font:inherit;font-size:14px;resize:vertical;outline:0"></textarea>' +
      '<div id="qfbe" style="color:#f87171;font-size:12px;min-height:16px;margin-top:6px"></div>' +
      '<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:8px">' +
      '<button class="qfb-cancel" style="background:none;border:1px solid var(--border,#333);color:var(--text2,#b9b2a8);border-radius:9px;padding:9px 15px;cursor:pointer;font:inherit">Cancel</button>' +
      '<button class="qfb-send" style="background:var(--ink,#ededee);color:var(--bg,#0a0a0b);border:0;border-radius:9px;padding:9px 18px;cursor:pointer;font:inherit;font-weight:600">Send</button>' +
      "</div></div>";
    document.body.appendChild(ov);
    var kind = "bug";
    ov.querySelectorAll(".qfbk-b").forEach(function (btn) {
      btn.onclick = function () {
        kind = btn.getAttribute("data-k");
        ov.querySelectorAll(".qfbk-b").forEach(function (b) { b.style.background = "transparent"; b.style.color = "var(--text2,#9aa4b2)"; });
        btn.style.background = "var(--acc,#d97757)"; btn.style.color = "#04121a";
      };
    });
    ov.querySelector(".qfb-cancel").onclick = function () { ov.remove(); };
    ov.addEventListener("click", function (e) { if (e.target === ov) ov.remove(); });
    ov.querySelector(".qfb-send").onclick = function () {
      var msg = ov.querySelector("#qfbm").value.trim();
      if (!msg) { ov.querySelector("#qfbe").textContent = "Please write something first."; return; }
      var token = stageToken();
      var headers = { "Content-Type": "application/json" };
      if (token) headers.Authorization = "Bearer " + token;
      fetch("/api/feedback", { method: "POST", headers: headers,
        body: JSON.stringify({ message: msg, kind: kind, page: location.pathname }) })
        .then(function (r) {
          if (r.ok) return r.json();
          if (r.status === 401) throw new Error("signin");
          throw new Error("http");
        })
        .then(function () { ov.remove(); toastMsg("💬 Thanks — feedback sent!"); })
        .catch(function (err) {
          if (err && err.message === "signin") {
            ov.querySelector("#qfbe").innerHTML = 'Sign in to send hosted feedback. <a href="/login.html?next=%2Findex.html" style="color:inherit;text-decoration:underline">Sign in</a>';
          } else {
            ov.querySelector("#qfbe").textContent = "Couldn't send feedback right now.";
          }
        });
    };
  };

  // ── build dock + shortcuts modal ────────────────────────────────────────────
  function build() {
    if (document.getElementById("qdock")) return;
    var dock = el("div", { id: "qdock" });
    [["⤓", "Scroll to bottom", "qdBottom"],
     ["⤒", "Scroll to top", "qdTop"],
     ["📋", "Copy conversation (Markdown)", "qdCopy"],
     ["⬇", "Download as Markdown", "qdExport", "md"],
     ["🎲", "Shuffle theme", "qdShuffleTheme"],
     ["🧘", "Focus mode", "qdFocus"],
     ["💬", "Send feedback", "qdFeedback"],
     ["⌨", "Shortcuts", "qdShortcuts"]].forEach(function (b) {
      var btn = el("button", { class: "qd-btn", title: b[1] }, b[0]);
      btn.onclick = function () { window[b[2]](b[3]); };
      dock.appendChild(btn);
    });
    document.body.appendChild(dock);

    var ov = el("div", { id: "scOv" });
    ov.appendChild(el("div", { id: "scBox" },
      "<h3>⌨ Quick actions</h3>" +
      "<div class='k'><span>Scroll to bottom / top</span><code>dock ⤓ ⤒</code></div>" +
      "<div class='k'><span>Copy conversation as Markdown</span><code>📋</code></div>" +
      "<div class='k'><span>Download conversation (.md / .json)</span><code>⬇</code></div>" +
      "<div class='k'><span>Shuffle a random theme</span><code>🎲</code></div>" +
      "<div class='k'><span>Focus mode (hide sidebar)</span><code>🧘</code></div>" +
      "<div class='k'><span>Developer tools</span><code>/tools/</code></div>" +
      "<div style='margin-top:14px;text-align:right'><button class='qd-btn' style='width:auto;border-radius:9px;padding:8px 16px' onclick=\"document.getElementById('scOv').classList.remove('on')\">Close</button></div>"));
    ov.addEventListener("click", function (e) { if (e.target === ov) ov.classList.remove("on"); });
    document.body.appendChild(ov);

    // composer character counter
    var cin = document.getElementById("cin");
    if (cin) {
      var counter = el("div", { id: "qcount" }, "");
      document.body.appendChild(counter);
      var upd = function () {
        var v = cin.value || "";
        counter.textContent = v ? (v.length + " chars · " + (v.trim() ? v.trim().split(/\s+/).length : 0) + " words") : "";
      };
      cin.addEventListener("input", upd); upd();
    }

    // Inbox unread badge — server decides whether the signed-in user is an admin.
    try {
      var token = stageToken();
      var badge = document.getElementById("inboxBadge");
      if (token && badge) {
        fetch("/api/feedback", { headers: { "Authorization": "Bearer " + token } })
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (d) { if (d && d.unread > 0) { badge.textContent = d.unread; badge.style.display = "inline-flex"; } })
          .catch(function () {});
      }
    } catch (e) {}
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", build);
  else build();
})();
