# 3D Appearance Plan

## Goal

Give Studio physical presence without turning the product into a GPU-heavy demo. Depth must improve hierarchy, recognition, and delight while preserving fast chat interaction on Android 11+ and iPhone.

## Phase 1 — CSS depth system (implemented foundation)

Use semantic elevation instead of arbitrary shadows:

- **z0 canvas:** flat warm background.
- **z1 work surface:** subtle inner highlight + soft 8–28 px downward shadow.
- **z2 active:** slightly stronger border/contrast, minimal lift.
- **z3 transient:** sheet/dialog shadow plus backdrop separation.

Objects that receive depth: logo mark, composer, active sheet, selected model control, primary action. Long text, message bodies, navigation labels, and every card do not.

Performance target: no continuous paint-heavy filters in chat. Prefer transform/opacity for motion.

## Phase 2 — Studio Prism

Create one authored 3D brand object for landing/onboarding: a compact geometric 'S' / prism derived from the Studio mark.

Behavior:

- Desktop: very small pointer-parallax range (2–4 degrees), springs back on leave.
- Touch: no gyro permission request by default. One gentle entrance orientation only.
- Reduced Motion: static render.
- Low-power / save-data: static WebP/AVIF poster.
- Core chat: object is not rendered.

Implementation candidate: Three.js only if the compressed scene + runtime budget is justified; otherwise pre-rendered layered CSS/AVIF wins.

Budgets:

- Added JS for the 3D path: <= 90 KB gzip preferred.
- First meaningful render must not wait for 3D.
- Keep 3D frame work out of the chat route.
- Target 60 fps on representative mid-range Android hardware; disable live rendering when the tab is hidden.

## Phase 3 — Native polish track

If Studio graduates from PWA to Capacitor/native wrappers:

- Android: Material 3 elevation semantics, edge-to-edge window insets, predictive back, system haptics.
- iOS: system materials, safe-area navigation, native sheets, edge-swipe back, Dynamic Type.
- Do not force identical navigation chrome across platforms. Carry the Studio brand through tint, type accents, icons, and artwork.

## Acceptance checklist

1. Depth communicates hierarchy without being necessary to understand UI state.
2. No gradient text.
3. No decorative glow behind normal controls.
4. No 3D renderer on the chat critical path.
5. Reduced Motion yields an equally understandable interface.
6. Android 11 device remains responsive while keyboard is open.
7. iPhone home-indicator and notch never cover controls.
8. Light and dark themes remain legible.
