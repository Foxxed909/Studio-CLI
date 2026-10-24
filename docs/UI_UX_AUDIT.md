# Studio Stage UI/UX Audit

⚠️ DEGRADED: single-context (no sub-agent tool exposed)

The requested ten-agent review was run as ten independent critique lenses in one context, plus the installed Impeccable deterministic detector. This is intentionally not described as ten literal agents.

## Evidence

Impeccable was installed project-wide for both Claude and Codex. Its first deterministic scan found the main Stage surface had 76 low-contrast findings, 68 undersized UI-text findings, 6 tiny-text findings, 3 cramped-padding findings, plus gradient-text, glow, pulsing-dot, and palette warnings. Landing, pricing, and Studio Testing showed the same pattern at lower counts.

The common problem was not lack of effects. It was hierarchy debt: muted text was too muted, small labels carried real information, touch affordances depended on hover, and desktop popovers were being squeezed onto phone screens.

## Ten review lenses

### 1. Information architecture — P1

**Finding:** Chat is the strong center, but settings, testing, beta, admin, and tool surfaces accumulated independently. Important infrastructure actions were hidden behind unrelated menus.

**Change:** Connections now has its own Settings destination. Phone Settings restructures into a horizontal category rail rather than shrinking the desktop two-pane layout.

**Next:** Collapse internal/test-only navigation behind one Development entry and keep the main sidebar task-oriented.

### 2. Mobile ergonomics — P0

**Finding:** 32–36 px controls, hover-only message actions, fixed desktop popovers, `100vh`, and missing safe-area handling made the interface fragile on phones.

**Change:** Touch/coarse-pointer targets, safe-area insets, dynamic software-keyboard height, thumb-reachable model selection, mobile sheets, compact landscape behavior, and touch-visible message actions were added.

**Acceptance:** Android 11+ Chrome/PWA and modern iPhone Safari/PWA must complete chat, model switch, settings, attach, login, and install flows without hidden controls.

### 3. Typography and visual hierarchy — P0

**Finding:** Muted tokens fell below WCAG AA and 9–11 px labels often carried meaningful state.

**Change:** Core Stage secondary/tertiary tokens were raised; high-value microcopy and status labels were enlarged. Filled terracotta actions use dark foreground text.

**Next:** Continue replacing one-off low-opacity colors on older marketing/testing pages with semantic tokens.

### 4. Motion and transitions — P1

**Finding:** Motion styles came from several generations of the app: bounce typing, pop/slide variants, pulsing indicators, and generic `transition: all`.

**Change:** Mobile/primary transitions use short transform/opacity feedback and `cubic-bezier(.16,1,.3,1)`. Reduced Motion now collapses the effect layer.

**Next:** Replace remaining `transition: all` declarations in the legacy Stage CSS with property-specific transitions.

### 5. Accessibility — P0

**Finding:** Contrast and pointer modality were the biggest accessibility failures. Focus visibility was inconsistent.

**Change:** Stronger text tokens, explicit `:focus-visible`, touch affordances, 16 px phone inputs, reduced-motion support, and safe-area layout were added.

**Next:** Run a screen-reader/name audit and make icon-only controls carry explicit accessible labels consistently.

### 6. Onboarding and empty states — P1

**Finding:** The product assumed users already understood BYOK, hosted plans, testing, beta, and installation.

**Change:** PWA install guidance is exposed in-app. Connector states explain Connected / Ready / Needs setup instead of failing silently.

**Next:** One first-run checklist: sign in, choose model, optional BYOK, optional connector, send first prompt. It should be dismissible and never block chat.

### 7. Model choice and trust — P1

**Finding:** Model discovery is feature-rich but can feel like a catalog rather than a decision aid.

**Change:** Nemotron 3 Ultra is clearly labeled as free with 550B/55B-active and 1M-context copy. Mobile model choice becomes a bottom-reachable surface.

**Next:** Add three top-level filters: Free, Fast, Deep. Keep provider/model IDs as secondary metadata.

### 8. Connectors and permissions — P0

**Finding:** The product had no coherent account-linked connector experience.

**Change:** Vercel Connect-backed GitHub, Google/Gmail, and Vercel integration hooks now use signed-in Studio user IDs server-side. Browser APIs expose authorization URLs/status, never provider tokens.

**Next:** Attach/create the team connectors in Vercel and request least-privilege scopes per action.

### 9. Performance and installed-app behavior — P0

**Finding:** The old PWA shell was too thin for a reliable phone install and stale caches could pin broken frontend state.

**Change:** Network-only API behavior, app-shell cache, offline screen, dynamic viewport runtime, maskable icon, install flow, and orientation-any manifest were added.

**Next:** Measure startup on a low-end Android 11 device. Keep shipped JavaScript below the threshold where interaction latency becomes noticeable.

### 10. Visual consistency and 3D — P1

**Finding:** Some older surfaces used generic AI gradients/glows while Stage's strongest visual identity is warm, restrained, and technical.

**Change:** Gradient headline treatments and decorative glow usage are being removed; primary depth now comes from directional elevation.

**Next:** Build the optional Studio Prism only for landing/onboarding and benchmark it before shipping. Core chat should remain CSS-only.

## Priority backlog

### P0 before a store/native release

- Physical Android 11/12 test and current Android test.
- Current iPhone Safari/PWA test, including keyboard and rotation.
- VoiceOver/TalkBack pass.
- Connector project attachment and provider authorization.
- Native icon/splash assets if Capacitor/TWA packaging is started.
- Store privacy/permissions review.

### P1

- Finish tokenizing landing/pricing/testing colors.
- Replace remaining generic animation patterns.
- Simplify model discovery.
- First-run onboarding.
- Responsive tablet layout.

### P2

- Optional Studio Prism authored 3D focal object.
- Haptics and native share/clipboard only if a native wrapper is adopted.
- Tablet/foldable multi-pane optimizations.
