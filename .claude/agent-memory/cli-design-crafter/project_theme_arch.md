---
name: project-theme-arch
description: Exact architecture of THEMES dict, UI_STYLES tuple, _prompt_box, render_welcome, _assistant_heading in StudioCLI
metadata:
  type: project
---

## THEMES dict (studio/data.py)
Each key is a theme name, value is a dict with these exact fields:
  name, banner_color, accent, prompt_user, prompt_arrow, border, success, error,
  warning, dim, banner_sub, icon, prompt_name

- accent: Rich markup color string used in Panel borders and inline highlights
- prompt_user / prompt_arrow: passed through _ptk_style_token which strips "bold " and "bright_"
  and replaces "_" with "" — so ansi* tokens or plain hex work; "bright_green" becomes "brightgreen"
- border: used as border_style in Rich Panels — plain color name (no "bold")
- prompt_name: short string shown in the prompt box top line (e.g. "studio", "rain", "h4ck3r")

## UI_STYLES tuple (aistudio.py line 681)
("claude", "gemini", "codex", "studio", "ghost", "nova", "foxxia")
Adding a new UI style requires: tuple entry, render_welcome branch, _prompt_box branch,
_prompt_html branch, _assistant_heading branch.

## _prompt_box (aistudio.py line 9037)
Returns FormattedText list of (style_str, text) tuples.
Style strings are PTK format: "fg:#hexcolor" or "fg:ansigreen bold" etc.
- studio/nova/foxxia: double-box top ╔═ ... ═╗ + ║ mid line (no bottom)
- claude/gemini/codex: rounded top ╭─ ... ─╮ + │ mid + ╰─ ... ─╯ bottom
- ghost: single-line, no box, just dim symbols

## render_welcome (aistudio.py line 8683)
Uses _animate_banner for nova/foxxia (ASCII banner lines + Rich color wrapper).
_animate_banner delay param is ignored (kept for API compat) — no sleep in PTK context.
Nova/foxxia: print ASCII banner then a Rich Panel with info lines below.
Ghost: flat console.print lines, no Panel.
Studio: Rich Panel with title.
Claude: Panel wrapping Columns([left, right]).
Codex: Panel with green $> header and ─ dividers.

## _assistant_heading (aistudio.py line 3084)
Per-UI heading printed before each AI response. Returns a formatted string with Rich markup.
Nova uses ⚡, foxxia uses 🦊, ghost uses ◌, codex uses >, claude uses ▸, studio uses ●.

## VIBE_PRESETS (aistudio.py/data.py)
Dict mapping vibe name -> {"ui": ui_style_name, "theme": theme_name}
cmd_vibe applies both and re-renders welcome.

**Why:** Understanding the full pipeline prevents color format bugs (PTK vs Rich), incorrect
field names, and missing branches.
**How to apply:** When adding "rain" UI style, touch all 4 functions + tuple + VIBE_PRESETS.
