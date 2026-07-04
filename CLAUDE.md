# StudioCLI

Python CLI tool that brings Google Gemini into the terminal.

## Stack
- Python 3.12+
- `rich` — rendering (Markdown, Syntax, Panels, Tables)
- `prompt_toolkit` — REPL input, history, keybindings, completions
- Google Generative Language API (`generativelanguage.googleapis.com/v1beta`)
- No external HTTP library — uses `urllib` directly

## Version format
`VERSION = "X.Y"` lives in `studio/data.py` and is imported into `aistudio.py`. Bump minor for features, major for rewrites.

## Key architecture
- Core logic in `aistudio.py` (12k+ lines) + `studio/` package (data, session, providers, project, agents, mcp, paths)
- `Agent` class handles API calls and context
- `run_repl()` is the main loop
- Commands are `cmd_*` functions (e.g. `cmd_write`, `cmd_patch`, `cmd_run`)
- AI file writes snapshot through `checkpoint_file()` first — `/undo` restores from `~/.aistudio/checkpoints`
- `@file` mentions expand via `expand_file_mentions()` before free-text prompts hit `ai_respond`
- `/connect` = BYO-subscription hub (claude/codex/gemini CLIs); `/login` = Google OAuth via Studio Stage
- `studio -p "prompt"` = headless mode (plain stdout, stdin piping, `--json`)
- `render_welcome()` always called at REPL start and after `/clear`
- `track_usage()` called after every AI response — updates profile model_usage, session stats, last_seen
- Profiles stored at `profiles/<user_id>/profile.json` (relative to cwd); default user is `"default"`

## UI styles
37 styles in `UI_STYLES` (studio/data.py). All welcomes render through ONE chrome system in aistudio.py:
`_WELCOME_SKINS` spec dict + `_welcome_card` / `_welcome_line` / `_welcome_rule` renderers, plus the
celestial chrome for the 22 celestial/theme-family styles. Adding a style = adding a skin dict entry;
never hand-draw box math. `_prompt_html()` returns the prompt_toolkit prompt per style.

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
- Watch for duplicate `cmd_*` names before adding a command — the LAST def wins silently (this bit `/rewind`: session-history rewind already existed)
- Never re-declare a `studio/` constant or function at module level in `aistudio.py` — the local copy shadows the import
- `_patch_autonomous_writes()` + `_unpatch_autonomous_writes()` swap the global `check_write_allowed` — called by `cmd_autonomous` on toggle
- `typewrite()` uses `sys.stdout.write` with ANSI codes — do NOT pass Rich markup (it gets stripped, but the style lookup uses a small static dict `_TYPEWRITE_ANSI`)
- Ghost UI prompt is single-line `FormattedText` — no top/bottom border, avoids Windows Terminal cursor split

## Install
`install_windows.bat` handles pip deps and registers the `studio` / `aistudio` aliases.
