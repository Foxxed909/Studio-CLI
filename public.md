# AI Studio CLI — Public Changelog

## v6.0 — 2026-05-11

### New
- **Web interface** (`web/`) — companion browser UI with SSE streaming, model picker, persona switcher, and dark terminal theme. Run via `npm start` in `web/`
- **README** — full project documentation: install, commands, agents, plans, providers, web setup

### Bug Fixes
- Fixed creator analytics access gate — users with no `role` field could previously bypass the creator/admin/owner check due to `None` in the allowed-roles tuple
- Fixed missing blank line between `track_usage` and `_clean_terminal_text` (caused some static analysis false positives)

### Housekeeping
- Added `.gitignore` — excludes `node_modules/`, `__pycache__/`, `profiles/`, `logs/`, and secrets
- Version bumped from 5.9 → 6.0

---

## v5.8 — 2026-05-06

### New Features
- **v5.8 Pro** — Max, Ultra, Enterprise, and Team plan users get an exclusive Pro welcome overlay at startup showing session stats and unread complaint alerts
- **`/profile`** (alias `/me`) — view your full profile: first/last seen, sessions, total messages, lifetime token counts, per-model usage bar chart, recent login history
- **`/insights`** (alias `/stats`) — usage analytics: lifetime cost estimate, avg messages/session, peak activity hour, top model, rarely-used models
- **`/vault`** — Pro: local encrypted secrets store (`/vault set KEY VALUE` · `/vault get KEY` · `/vault delete KEY` · `/vault list`). Values stored base64-encoded at rest
- **`/team`** — Pro: team management panel (`/team invite <email> [role]` · `/team remove <email>` · `/team list` · `/team role <email> <role>`)
- **Creator dashboard now shows all feedback & complaints** — `/creator` displays a Feedback & Complaints table (unread flagged in red), marks entries as read on view

### Improvements
- **Restart fixed** — `/restart` no longer crashes on Windows. Now uses `subprocess.Popen` + `sys.exit(0)` on Windows (bypasses batch-alias issue), `os.execv` on Unix. Also clears stale `.pyc` before restarting
- Pro banner updated — shows plan name, username, and "Pro" label instead of hardcoded "ULTRA"
- Enterprise negotiation: counter-offer rounds now persist and reference ID included in confirmation

### Bug Fixes
- Fixed `/balance` printing twice (removed the dim-panel "animation" which had no in-place overwrite)
- Fixed welcome banner interleaving with the prompt box — removed `time.sleep()` from `_animate_banner` (delays inside prompt_toolkit event handlers corrupt the terminal display)

---

## v5.7 — 2026-05-06

### New Features
- **Nova UI** (`/ui nova`) — vibrant sci-fi style, magenta/cyan gradient headers, `⚡` icons
- **Foxxia UI** (`/ui foxxia`) — orange/gold Foxxia Dev Studio branding, `🦊` icon
- **New plans**: Starter ($5/mo · 100 msgs), Dev ($35/mo · 2,000 msgs + Cursor API), Enterprise (custom · unlimited)
- **`/vibe <preset>`** — one-shot UI + theme setter (12 presets: foxxia, nova, ghost, matrix, hacker, sakura, ocean, fire, midnight, synthwave, aurora, dracula)
- **`/quickstart`** — 5-step guide panel tailored to your plan and dev type
- **`/changelog`** — in-app version history table
- **`/audit`** — AI security scan of the loaded project
- **`/docs <file>`** — AI generates Markdown documentation for a source file
- **`/search <query>`** — literal + semantic code search across project files
- **`/test <file>`** — AI generates pytest/jest tests for a source file
- **Onboarding redesign** — plan comparison table, dev type question, Rich progress bar, summary card
- **`/balance` redesign** — shows active provider (Gemini/OpenRouter/Cursor), API tier (Dev API vs Teams API), live credit estimate, session token spend
- **Enterprise contact form** — `/upgrade enterprise` opens an inquiry form; submissions saved locally for creator review
- **Arena overhaul** — each model gets its own full-width Panel with Markdown rendering; fastest and most-detailed model badges; summary row; supports up to 4 models; `same` mode compares low vs pro effort

### Improvements
- **All 7 UI styles fully overhauled** (`studio`, `claude`, `codex`, `gemini`, `ghost`, `nova`, `foxxia`) — new panels, session counters, model usage display, animated banners
- **`/models` now includes built-in arrow-key picker** — no more separate `/model-pick`; navigate with ↑↓, Enter to switch, shows per-model usage counts and rarity tags
- **Profile enriched** — profile now tracks `model_usage` (per-model message counts), `total_msgs`, `total_tokens_in/out`, `session_count`, `login_history` (last 50 sessions), `first_seen`, `last_seen`
- **Session login tracking** — each REPL launch updates `last_seen`, `session_count`, and appends to `login_history`
- Prompt input box redesigned for nova/foxxia with matching icon headers; ghost uses ultra-minimal single-line prompt
- Studio box shows session count and per-session message count
- Ghost UI refined — dot-separator rows, per-field alignment, no boxed border clutter
- Toolbar model name no longer displays in italic
- `/logout` now exits the app automatically after clearing credentials

### Bug Fixes
- Fixed raw Rich markup (`[bold cyan]Free[/bold cyan]`) printing literally in `/plan` and onboarding
- Fixed `NameError` crash on `/audit`, `/docs`, `/search`, `/test` (stubs were missing)
- Fixed AI responses printing raw `**bold**` / `### headers` / `|tables|` — non-streamed replies now rendered through `rich.markdown.Markdown`
- Fixed `/analyze` dispatch — was called with no arguments, crashing immediately
- Fixed `_patch_autonomous_writes` — patched function had wrong signature, auto-approve had no effect
- Fixed `/models` — model pool resolution used broken `sys.modules[__name__]` check

---

## v5.6 — 2026-04-30

### New Features
- `/history` — pretty-print session conversation turns
- `/models` — list all available models with routing info
- `/summarize` — AI compresses session into a context summary
- `/autonomous` — toggle auto-approve mode for patch/write operations
- `/creator` — creator analytics dashboard
- `/export` — export chat to HTML or Markdown

### Improvements
- Auto `/enter` on startup when cwd looks like a project
- Fence-stripping in `/write` (no more triple-backtick in saved files)
- Free plan messaging improvements

### Bug Fixes
- Ollama streaming reliability
- HTTP retry on transient errors
- Diffpatch preview polish

---

## v5.5 — 2026-04-20

### New Features
- Multi-provider support: OpenRouter, Cursor API, HuggingFace image generation
- Agent Mesh and squad system (`/squad`, `/broadcast`, `/mesh`)
- Live-FIF file watcher (`/live-fif`)
- Arena mode (`/arena`) — side-by-side model comparison
- Effort levels: `low` / `medium` / `pro` / `high` / `xhigh` / `mxh`
