---
name: project-rain-theme
description: Design decisions for the "rain" UI style — Matrix rain aesthetic, neon green + cyan, glitch effects
metadata:
  type: project
---

Requested vibe: Matrix rain — deep black, neon green #00FF41, cyan #00FFFF secondary, glitch text
via Rich markup (strikethrough, dim alternation, mixed green/cyan), rain/cascade visual metaphors.

Key design decisions made:
- Theme entry key: "rain" in THEMES dict
- UI style name: "rain" added to UI_STYLES tuple
- Prompt symbol: ░ (block shade) — feels like cascading rain data
- Prompt name: "rain" (displayed in prompt box top line)
- Banner uses vertical bar cascade characters (│ ║ ╎) mixed with katakana-esque box chars
- ASCII art header uses green/cyan alternation to simulate column rain
- _prompt_box: double-box style (╔═ ... ═╗) with neon green, cyan arrow symbol ░
- _assistant_heading: uses ▓ (dark shade block) as the response sigil
- VIBE_PRESET "rain": ui=rain, theme=rain

Glitch effects in static Rich markup:
- Use [#00FF41] and [cyan] alternating within the same line for "noise"
- [strike] on occasional chars for corruption feel
- [dim #00FF41] for "faded" rain column text
- [bold #00FF41] for the active/bright column head
- Do NOT use [blink] — flickers badly in Windows Terminal, unreliable cross-platform

Color values confirmed:
- Primary green: #00FF41 (Matrix canonical)
- Secondary/dim green: #00B32C (darker for dim lines)
- Cyan accent: #00FFFF
- Dim text: #1a4d1a (very dark green for background noise feel)
- border Rich string: "#00FF41" (hex works in Rich Panel border_style)
- prompt_user PTK: "ansigreen" (safe cross-platform)
- prompt_arrow PTK: "ansicyan" (safe cross-platform)
