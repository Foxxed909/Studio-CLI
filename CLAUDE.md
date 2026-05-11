# StudioCLI

Python CLI tool that brings Google Gemini into the terminal.

## Stack
- Python 3.12+
- `rich` — rendering (Markdown, Syntax, Panels, Tables)
- `prompt_toolkit` — REPL input, history, keybindings, completions
- Google Generative Language API (`generativelanguage.googleapis.com/v1beta`)
- No external HTTP library — uses `urllib` directly

## Version format
`VERSION = "X.Y"` at top of `aistudio.py` — bump minor for features, major for rewrites.

## Key architecture
- Single-file: everything lives in `aistudio.py`
- `Agent` class handles API calls and context
- `run_repl()` is the main loop
- Commands are `cmd_*` functions (e.g. `cmd_write`, `cmd_patch`, `cmd_run`)
- `render_welcome()` always called at REPL start and after `/clear`
- `track_usage()` called after every AI response — updates profile model_usage, session stats, last_seen
- Profiles stored at `profiles/<user_id>/profile.json` (relative to cwd); default user is `"default"`

## UI styles
7 styles: `studio`, `claude`, `codex`, `gemini`, `ghost`, `nova`, `foxxia`
All are fully Panel-based — no raw f-string width arithmetic with Rich markup content.
`_prompt_box()` returns a `FormattedText` for the prompt_toolkit input prompt. Ghost uses single-line. Nova/foxxia have matching icon headers. Studio/codex/claude/gemini use top+mid box.

## Profile fields (v5.7+)
`user`, `plan`, `ui_style`, `workspace_root`, `dev_type`, `persona`, `first_seen`, `last_seen`,
`session_count`, `login_history` (list, capped 50), `model_usage` (dict model→count),
`total_msgs`, `total_tokens_in`, `total_tokens_out`, `onboarded_at`, `session_msgs`, `balance`

## Commands convention
- All slash commands start with `/`
- Adding a command: add `cmd_<name>` function + register in BOTH dispatch blocks in `run_repl()`
- Show preview before any destructive file operation
- `typewrite()` must NOT embed Rich markup — prints char-by-char, markup is never interpreted as a whole

## Known gotchas
- `_patch_autonomous_writes()` only patches functions that look up `check_write_allowed` as a global
- `typewrite()` + Rich markup = literal output (tags printed verbatim)
- Ghost UI prompt is single-line `FormattedText` — no top/bottom border, avoids Windows Terminal cursor split

## Install
`install_windows.bat` handles pip deps and registers the `studio` / `aistudio` aliases.
