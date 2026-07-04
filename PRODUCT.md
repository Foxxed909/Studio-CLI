# Product

## Register

product

## Users

Developers who live in the terminal. They open Studio to chat with a model,
patch a file, run an agent, or check usage — usually mid-task, in a hurry,
often on Windows Terminal or Termux. On the web (Studio Stage) the same
people reach for a quick chat, group-model comparison, or deep research run
when a terminal isn't handy.

## Product Purpose

Studio is an AI terminal + companion web app. One tool that talks to many
providers (OpenRouter, Gemini, Ollama, Claude CLI, Gemini CLI) and rides the
subscriptions the user already pays for. Success: a developer's default
scratchpad for AI work — faster to open than a browser tab, honest about
what's local vs. backed by a server.

Product line: **Studio CLI** (terminal), **Studio Stage** (web),
**Studio Stage Beta** (capped 10-user testing channel), **Studio Testing**
(the Studio Lab feedback/testing hub).

## Brand Personality

Sharp, technical, alive. Terminal-native confidence — a power tool with a
pulse. Precise chrome, quick wit in microcopy, never corporate, never cute.

## Anti-references

- Generic AI-chat SaaS: purple-blue gradients, glassmorphism cards, hero
  metrics, identical feature-card grids.
- Fake-enterprise theater: features that pretend a backend exists. If it's
  local-only, the UI says so.
- 2023 "hacker aesthetic" clichés: rainbow ANSI spam, boxes inside boxes,
  emoji confetti in every panel.

## Design Principles

1. **The response is the interface.** Chrome exists to frame model output,
   never to compete with it. One accent color per style, most pixels are
   content.
2. **Honest surfaces.** Local features look local; server features look
   connected. No simulated enterprise.
3. **Fast glances beat dashboards.** Status lives in one toolbar line and
   compact panels — no screen-filling banners after first launch.
4. **One chrome system, many skins.** Every UI style is a palette + motif on
   the same layout skeleton; nothing hand-draws its own box math.
5. **Terminal constraints are the brief.** Design for 80 columns, monospace,
   no mouse — degradation is a feature, not an edge case.

## Accessibility & Inclusion

- Never encode meaning in color alone; pair with symbols/text (✓ ✗ ⚠).
- Respect NO_COLOR and dumb terminals; Rich handles fallback — don't fight it.
- Web: WCAG AA contrast (≥4.5:1 body text), prefers-reduced-motion honored,
  keyboard-first interactions.
