# Studio Design System

Studio is a developer workspace, not a generic AI SaaS dashboard. It should feel sharp, technical, warm, fast, and trustworthy.

## Visual direction

- Base: warm near-black canvas with warm gray surfaces.
- Accent: Studio terracotta (`#d97757`) for primary actions, selection, focus, and active state.
- Type: IBM Plex Sans for interface text; IBM Plex Mono for model IDs, code-adjacent metadata, and compact status.
- Contrast: WCAG AA is the floor for body text and interactive labels. Muted text is still readable text, not decoration.
- Depth: directional elevation, not glow. Use a small inner highlight plus a soft downward shadow when an object is physically above another surface.
- Gradients: not for text or generic AI decoration. They are reserved for authored artwork only.
- Borders: use tone changes first; borders define interactive or structural boundaries, not every container.
- Radius: modest and consistent. Avoid nested-card stacks.

## Elevation model

Studio has four semantic depth levels:

1. **Canvas / z0** — app background and long-form content.
2. **Work surface / z1** — composer, selected sidebar rows, settings controls.
3. **Active / z2** — focused composer, open selector, active tool, draggable media.
4. **Transient / z3** — sheets, dialogs, command palettes, authorization flows.

Depth must communicate state or hierarchy. A shadow without a semantic reason is a defect.

## Motion

- Small state feedback: 120–180 ms.
- Sheets, drawers, structural transitions: 180–260 ms.
- Preferred easing: `cubic-bezier(.16,1,.3,1)`.
- Animate transform and opacity whenever practical.
- No continuous decorative motion in the core chat surface.
- `prefers-reduced-motion: reduce` must preserve all state changes without spatial motion.

## Mobile

### Android 11+

- Touch targets: at least 48 dp where native geometry is controllable; the web/PWA floor is 44 CSS px and primary mobile actions are 44–48 px.
- Respect status/navigation bars, display cutouts, keyboard/IME viewport changes, portrait and landscape.
- No hover-only interaction.
- Back/navigation must remain browser/PWA-native until a native shell exists.

### iPhone / iPad

- Respect safe-area insets and the home indicator.
- Text inputs must stay at least 16 CSS px to avoid Safari focus zoom.
- Do not interfere with browser/system back gestures.
- Honor Reduce Motion.
- PWA install is supported through Add to Home Screen; native App Store packaging is a separate release track.

## 3D rule

3D is a focal layer, not the base language. The application shell uses CSS elevation. An optional authored 3D object may appear on the marketing/onboarding surface, never behind dense chat content.

See `docs/3D_APPEARANCE_PLAN.md`.
