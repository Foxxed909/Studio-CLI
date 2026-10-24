/* Studio Stage mobile/PWA runtime */
(() => {
  "use strict";

  const root = document.documentElement;
  const standalone = () =>
    window.matchMedia?.("(display-mode: standalone)").matches ||
    window.navigator.standalone === true;

  function setViewportHeight() {
    const viewport = window.visualViewport;
    const height = Math.round(viewport?.height || window.innerHeight);
    root.style.setProperty("--app-height", height + "px");
    const keyboardOpen = viewport && viewport.height < window.innerHeight * 0.78;
    document.body?.classList.toggle("soft-keyboard-open", !!keyboardOpen);
  }

  setViewportHeight();
  addEventListener("resize", setViewportHeight, { passive: true });
  addEventListener("orientationchange", () => setTimeout(setViewportHeight, 120), { passive: true });
  window.visualViewport?.addEventListener("resize", setViewportHeight, { passive: true });
  window.visualViewport?.addEventListener("scroll", setViewportHeight, { passive: true });

  let deferredInstall = null;
  const ua = navigator.userAgent || "";
  const isiOS = /iPad|iPhone|iPod/.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);

  function notify(message) {
    if (typeof window.showToast === "function") window.showToast(message, "info");
    else if (typeof window.toast === "function") window.toast(message);
    else console.info(message);
  }

  function ensureInstallAction() {
    if (standalone() || document.getElementById("studioInstallAction")) return;
    const footer = document.querySelector(".sidebar-footer");
    if (!footer) return;

    const button = document.createElement("button");
    button.id = "studioInstallAction";
    button.type = "button";
    button.className = "sf-link";
    button.setAttribute("aria-label", "Install Studio Stage");
    button.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 3v12"/><polyline points="7 10 12 15 17 10"/><path d="M5 21h14"/></svg><span>Install Studio</span>';
    button.addEventListener("click", async () => {
      if (deferredInstall) {
        deferredInstall.prompt();
        await deferredInstall.userChoice.catch(() => null);
        deferredInstall = null;
        button.remove();
        return;
      }
      if (isiOS) {
        notify("On iPhone: tap Share, then Add to Home Screen.");
        return;
      }
      notify("Use your browser menu → Install app / Add to Home screen.");
    });
    footer.prepend(button);
  }

  addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferredInstall = event;
    ensureInstallAction();
  });
  addEventListener("appinstalled", () => {
    deferredInstall = null;
    document.getElementById("studioInstallAction")?.remove();
    notify("Studio Stage installed.");
  });

  addEventListener("DOMContentLoaded", () => {
    document.body.classList.toggle("standalone-app", standalone());
    if (isiOS || deferredInstall) ensureInstallAction();

    // Desktop hover used to hide message actions. Touch has no hover.
    if (matchMedia("(hover: none), (pointer: coarse)").matches) {
      document.body.classList.add("touch-ui");
    }

    // Keep the active input visible when the software keyboard changes viewport height.
    const prompt = document.getElementById("cin");
    prompt?.addEventListener("focus", () => {
      setTimeout(() => prompt.scrollIntoView({ block: "nearest", behavior: "smooth" }), 120);
    });
  });
})();
