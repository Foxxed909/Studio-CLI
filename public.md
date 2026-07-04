# AI Studio CLI — Public Changelog

## v11.0 — 2026-07-04

### Bring your own subscription — /connect
One hub for riding the AI plans you already pay for. `/connect` shows what's
installed; `/connect claude` routes prompts through Claude Code (Claude
Pro/Max), `/connect codex` through the Codex CLI (ChatGPT Plus/Pro), and
`/connect gemini` through the Gemini CLI (Google account). Sign in once with
the vendor's own CLI — your credentials never touch Studio.

### Sign in with Google — /login
`/login` opens Studio Stage, you sign in with Google (or GitHub/Discord), and
paste the token back into the terminal. The CLI verifies it against the Stage
backend and syncs your account. `/logout-cloud` disconnects.
Also fixed: web OAuth used to redirect to a page that didn't exist — every
Google sign-in on the web dead-ended in a 404. It works now.

### Checkpoints — /undo, upgraded
Every AI file write snapshots the previous version first (last 50, in
`~/.aistudio/checkpoints`). `/undo` lists them with previews; `/undo 3`
restores. The old `.bak` flow still works as a fallback.

### @file mentions
`explain @src/app.py` attaches the file to your prompt — with tab-completion
on `@`. No more /read round-trips for quick questions.

### Headless mode — studio -p
`studio -p "prompt"` prints the plain answer and exits. Pipe-friendly
(`cat error.log | studio -p "explain this"`), `--json` for scripts, proper
exit codes for CI.

### One welcome chrome, every style
All UI styles now share a single welcome-card system — same layout skeleton,
each style keeps its palette, icon, and motif. Every card shows your git
branch, and the toolbar gained a live context-token meter that nudges
`/compact` when the session gets heavy.

### Studio Stage (web)
The web app has a name now. Stage Beta is capped at 10 seats, enforced
server-side — the v10 badge claims a seat when you flip it on. The testing
hub is Studio Testing (`/testing`).

### Removed
Fake-enterprise theater is gone: `/sso`, `/policy`, `/priority-queue` wrote
config files that nothing ever read. 4.3 MB of stale screenshots, two dead
UI experiments, and 7 duplicate commands also left the building.


## v10.0 — 2026-05-20

### Web UI — 4 Model Tiers
The model selector is now organized into 4 **intent-based response modes** — each backed by a different model and system prompt tuned for that style:

| Tier | Description | Access |
|------|-------------|--------|
| ⚡ **Flash-Lite** | Instant answers, no fluff — free tier | Free |
| 🔥 **Flash** | Fast and sharp, everyday tasks | Pro |
| ✦ **Auto** | Context-aware smart routing | Pro |
| 🧠 **Deep Thinking** | Chain-of-thought, extended reasoning | Max |

Each tier injects a purpose-built system prompt automatically — no configuration needed.

### Web UI — Canvas
The **Live Code Preview** is now the **Canvas** — a full in-browser IDE for generated apps:

- **Live Preview tab** — see your generated HTML/CSS/JS running in real-time
- **Split view** — code + preview side by side
- **Download** — save the finished app as a standalone HTML file
- **Suggest Fix** — type a change ("make the button blue", "add dark mode") and the AI rewrites the code in-place; preview updates automatically



## v9.5 (second patch) — 2026-05-18

### Bug Fixes
- **`/usage` now shows plan-aware rate limit** — the rate window cap is now derived from your actual plan (`free: 10/hr`, `pro: 200/5hr`, `max: 500/10hr`) instead of always displaying "free cap: 10/hr" for all plans.
- **`/tokens` now shows session totals** — instead of printing just "Usage: /tokens", the command now displays a proper panel with session token counts (in, out, total) and an estimated session cost based on the active model's pricing.
- **Removed 5 blocks of duplicate function declarations** in `aistudio.py` that were silently shadowing correctly imported functions from `studio/session.py`. Affected: `load_profile`, `save_profile`, `load_trial`, `get_plan`, `check_msg_limit`, `load_usage`, `save_usage`, `load_api_key`, `load_or_key`, `load_hf_key`, and more. No behavioral regression — the shadowing copies were equivalent — but this was dead weight that masked the import-based architecture.

### New Commands
- **`/recap`** — ask the AI for a one-paragraph summary of the current session: what was worked on, key decisions, open threads.
- **`/gitdiff`** — show the current git working-tree diff in a syntax-highlighted panel. Use `/gitdiff stat` for a summary view.
- **`/branch`** — show the current git branch name, last 7 commits, and working-tree status in one panel.
- **`/set model <name>`** — inline model switch without navigating to `/models`. Alias for `/model`.
- **`/cost`** — improved session cost panel: shows token totals (in, out, combined), per-1M rate for the current model, and estimated session spend. Replaces the last-turn-only display.
- **`/qnote <text>`** — save a quick text note to `~/.aistudio/notes.json`. Use `/qnotes` to list.
- **`/qnotes`** — list all quick notes. `/qnotes del <n>` to remove.

### UI
- **Nova welcome screen redesigned** — removed the fixed-width ASCII art box that misaligned on narrow terminals. Now uses a `Panel()` with title/subtitle, matching the studio/foxxia/codex pattern.

## v9.6 — 2026-05-18

### Web UI — New Themes
- **8 theme swatches in Settings → Appearance** — Dark, Light, Midnight (GitHub blue), Ocean (teal), Rose (pink), Forest (green), Neon (cyberpunk), Purple. Replaces the light/dark toggle.
- Default theme is now **Dark**. Theme persists across sessions.

### Web UI — Group Chat
- **Group button in the feature toolbar** — select 2–4 models to respond to the same prompt in parallel.
- Responses render side-by-side in color-coded columns, each labeled with the model name.
- Supports all free and paid OpenRouter models. Errors per-column (one model failing does not block others).

### Web UI — Incident Notice (redesigned)
- High-load banner is now a **compact corner toast** (bottom-right, 300px, slides in) instead of a full-width banner that pushed content down.
- Auto-dismisses 30 seconds after load clears. Cooldown prevents repeated pop-ups.

### Web UI — Fetch Timeout
- AI requests now have a **45-second client-side timeout** — shows a clear "Request timed out" message instead of hanging indefinitely.

### Server Hardening (v9.6)
- Rate limiting, CORS, and Helmet headers from v9.5 stress-tested at **5,000 requests / 200 concurrency** — zero 5xx errors.
- `highLoad` detection and `/api/health` polling verified under sustained traffic.

---

## v9.5 (patch) — 2026-05-18

### Bug Fixes
- **`/usage` rate limit display corrected** — was incorrectly showing "free cap: 5/hr"; actual rate limit is 10 requests/hr. Display now matches the enforced limit.
- **Agent persona sync fixed** — `Wizzard` agent now consistently uses the extended persona ("Every answer is a spell that works. Experimental, creative, always shipping.") in all code paths, not just some.

---

## v9.5 — 2026-05-16

### Bug Fixes
- **Enterprise/Max plan features now work correctly** — `/computer-use`, `/turbo`, `/extension`, `/search`, `/research` were incorrectly gating Enterprise and Team users as if they were on Free. Fixed.
- **AI responses now render as rich Markdown** — bold, headers, lists, inline code, and code blocks with syntax highlighting all render properly in the terminal. Previously the response text was stripped before rendering.
- **Web cost tracking fixed** — cost per message now correctly references the active model instead of always returning $0.

### New CLI Commands
- **`/extension`** — Chrome Extension manager (Max+ plans). Install and manage the Studio browser extension for automated web actions.

### What was already there (v9.3 feature listing)
- **`/search` / `/websearch`** — web-augmented responses via Perplexity Sonar (Pro+)
- **`/research`** — multi-step deep research with synthesis (Pro+)
- **`/turbo`** — 2x fast mode, 2.5x credit cost (Pro+)
- **`/credits`** — monthly credit balance and usage breakdown
- **`/computer-use`** — AI desktop automation stub (Max+)
- Live Code Preview in Web UI — HTML/CSS/JS code blocks get a "Live Preview" button

---

## v9.4 — 2026-05-16

### New CLI Commands
- **`/pr-review [branch|range]`** — structured git diff code review with BLOCKER / WARNING / SUGGESTION severity labels; optionally saves to `.pr_review.md`
- **`/git-suggest`** — AI reads your last 20 commits, current diff, and branch list, then recommends squash candidates, PR split points, and rebase vs merge strategy
- **`/test-coverage [file]`** — auto-detects pytest or jest, runs coverage, and generates targeted tests for uncovered lines; offer to apply via `/patch`
- **`/safety-check [file|dir]`** — fast regex pre-scan (hardcoded secrets, SQL concat, `eval`, `exec`, `pickle.loads`, `os.system`, `subprocess shell=True`, MD5, SHA1, HTTP) + AI OWASP deep review with CWE IDs and exact fix code

### Web UI — Message Editing & Deletion
- **Edit user messages** — pencil icon appears on hover; click to enter inline edit mode with an Update / Cancel button; re-sends AI response from that point automatically
- **Delete any message** — trash icon on all message bubbles; removes from history and re-indexes remaining messages

### Web UI — File Upload
- Attach button now accepts code and text files: `.py .js .ts .jsx .tsx .md .txt .json .yaml .toml .csv .html .css .sh` in addition to images
- File content is injected as a fenced code block context prefix in your message (max 200KB)
- File pill shows filename and size, with a one-click remove button

### Web UI — Advanced Generation Settings
- Settings modal Generation section adds: **Top P**, **Frequency Penalty**, **Presence Penalty** sliders and a **Stop Sequences** text input
- All settings persist in localStorage and are forwarded to OpenRouter on every request

### Web UI — Cost & Token Tracking
- Each AI response now shows estimated cost (`~$0.0012 · 340 tok`) in dim text beneath the message
- Session total cost accumulates in localStorage
- Dashboard "Session Cost" card shows your estimated spend

### Bug Fixes
- `cmd_tts` — args default changed to `None` with `(args or "").strip()` guard; prevents crash when called without arguments
- Removed orphaned `"_effort"` key reads — all effort references now consistently use `state["effort"]`

---

## v9.1 — 2026-05-16

### New Features
- **`/alias`** — define custom prompt shortcuts (`/alias set greet Say hello!`), run them with `/greet`, list with `/alias list`, delete with `/alias del greet`
- **`/multiline`** — toggle multiline input mode; paste several lines and submit with a blank line
- **`/note`** — save quick notes during a session (`/note list` to view, `/note clear` to wipe)
- **`/regen`** — regenerate the last AI response with a fresh model sample (removes the previous answer from context and resubmits)
- **`/context-bar`** — show context window usage as a progress bar with token count and percentage
- **`/resume`** — restore your last auto-saved session (auto-save now happens after every message exchange)
- **`/history-search`** (alias `/hs`) — search through messages in the current history for a keyword
- **`/compact [N]`** — compress old history into an AI-generated summary, keeping the last N turns (default 10)
- **`/clip`** — copy the last AI response to clipboard (Windows `clip` / Linux `xclip`)
- **`/tts`** — speak the last AI response aloud using Windows Speech Synthesis

### Bug Fixes
- Fixed `/beta` command crash — second `def cmd_beta` was silently overwriting the first (v9 feature flags manager), making `/beta on <flag>` and `/beta reset` unreachable with a `TypeError`. The old feature definitions (`/beta docx`, `/beta xlsx`, `/beta screenshot`, etc.) are now routed correctly.
- Fixed `/voice` crash — the Windows TTS implementation was shadowed by the voice-to-text stub, making it completely unreachable. TTS is now at `/tts`; `/voice` routes to the voice-to-text system (ultra plan).
- Fixed `/vision-pro` appending history entries with wrong keys — used `"parts"` (Gemini REST format) instead of `"text"` (internal format), causing downstream crashes when the history was reused.
- Fixed `/autonomous` crashing with `AttributeError: 'NoneType' object has no attribute 'lower'` when called with no arguments.
- Fixed onboarding launch prompt using bare `input()` — replaced with `_safe_input()` to survive non-interactive environments.
- Fixed complaints never appearing in `/creator` analytics — `/complain` was writing to `logs/complaints.json` while analytics read `~/.aistudio/feedback_log.json`. Complaints now dual-write to both paths.

---

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
