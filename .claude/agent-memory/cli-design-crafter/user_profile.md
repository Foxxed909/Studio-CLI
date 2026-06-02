---
name: user-profile
description: Developer identity, StudioCLI authorship, aesthetic preferences and taste signals
metadata:
  type: user
---

GitHub username: Foxxed909. Author and sole developer of StudioCLI — a Python terminal REPL tool
using Rich + prompt_toolkit.

Aesthetic preferences observed:
- Gravitates toward named-persona UI styles (foxxia, nova, ghost) with strong identity
- Likes animated ASCII banners for bold styles (nova, foxxia use _animate_banner)
- Appreciates glitch/hacker aesthetics — requested Matrix rain theme with neon green + cyan
- Favors sharp-edged box-drawing characters (╔═╗ ╚╝ ║) for panel borders in power styles
- Ghost style is a deliberate minimalist counterpoint — single-line prompt, dim white, no borders
- Studio/codex/claude use top+mid box prompt; nova/foxxia add icon to the top line
- Prompt symbols chosen per persona: ◆ (studio), ⚡ (nova), 🦊 (foxxia), $ (codex), > (claude)

Theme palette philosophy:
- Themes live in data.py THEMES dict; UI styles live in aistudio.py render_welcome + _prompt_box
- A "vibe" preset pairs a UI style with a theme (e.g. matrix vibe = codex UI + matrix theme)
- prompt_user / prompt_arrow fields go through _ptk_style_token which strips "bold " and "bright_"
  and collapses underscores — so use ansi* names or plain hex for PTK, Rich markup for panels
