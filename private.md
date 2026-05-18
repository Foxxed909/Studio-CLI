# AI Studio CLI — Private Notes

> Internal only. Do not commit API keys, user data, or revenue figures.

---

## Architecture Decisions

### Single-file monolith (`aistudio.py`)
Intentional — avoids import complexity for a CLI tool distributed as a single script. All logic in one file, all commands as `cmd_*` methods, wired in the big `elif` dispatch block in `run_repl()`.

### Plan system
Plans are purely local / honor-system. No server-side enforcement. The "secret letter check" during onboarding is cosmetic friction, not real auth. Real auth would require a backend.

### Rate limiting
`check_msg_limit()` increments a counter in `~/.aistudio/profile.json`. Users can reset it with `/clear` (which calls `reset_msg_counter`). This is intentional — the Free plan limit is a soft suggestion, not a hard gate.

### Autonomous mode patch
`_patch_autonomous_writes()` monkey-patches the module-level `check_write_allowed`. Functions that import or close over the original reference won't see the patch — known limitation. Only functions that call `check_write_allowed` as a global look-up benefit.

---

## v9.5 — Fixes (2026-05-16)

### Enterprise/plan feature-gate bug — root cause and fix
**Root cause**: `aistudio.py` had a local `PLANS = { ... }` redefinition at the module level (around line 113–206) that shadowed the `PLANS` imported from `studio.data`. This old copy was missing the feature-flag fields (`computer_use`, `web_search`, `deep_research`, `turbo`, `live_code`, `credits`) added to `studio/data.py` in v9.3. Any `PLANS.get(plan, {}).get("computer_use", False)` call would hit the local copy and return `False` for every plan, including Enterprise.

**Fix**: Deleted the duplicate local `PLANS` block from `aistudio.py`. The import `from studio.data import PLANS` now takes effect.

**What to watch**: Any future constant that needs feature flags **must** be added to `studio/data.py`, not duplicated in `aistudio.py`. The pattern of re-declaring things in `aistudio.py` for "standalone" use is the root cause of this class of bug.

### Response rendering fixed
`_clean_terminal_text()` was stripping markdown (converting `## Heading` → `HEADING`, `**bold**` → `bold`) before passing text to Rich's `Markdown()` renderer. The result was plain uppercase text with no formatting. Fixed by removing the clean step from the main `ai_respond` display path and the one-shot path. `_clean_terminal_text` is still defined but no longer used on the primary response path.

### server.js `activeModel` undefined
`estimateCost(activeModel, ...)` at two call sites used `activeModel` (undefined in scope) instead of `resolvedModel`. Cost was always $0. Fixed by replacing with `resolvedModel`.

---

## v9.5 second patch — Fixes & Features (2026-05-18)

### Duplicate-function cleanup (third pass)
Five more blocks of duplicate function declarations were found and removed in `aistudio.py`:
- **Block A** (~line 728–832): `load_profile`, `save_profile`, `load_trial`, `start_trial`, `get_plan`, `set_plan`, `check_msg_limit`, `reset_msg_counter`, `check_img_quota`, `_RICH_TAG_RE`
- **Block B** (~line 822–860): `load_upgrade_slots`, `save_upgrade_slots`, `claim_upgrade_slot`
- **Block C+D** (~line 1257–1309): `save_theme`, `load_last_model`, `save_last_model`, `KEYS_FILE`, `SUPPORTED_PROVIDERS`, `load_all_keys`, `save_all_keys`, `get_key`, `mask_key`
- **Block E** (~line 1622–1673): `load_api_key`, `save_api_key`, `load_or_key`, `save_or_key`, `load_hf_key`, `save_hf_key`
- **Block F** (~line 2109–2127): `USAGE_FILE`, `load_usage`, `save_usage`

`release_upgrade_slot` was NOT removed — it is only in `aistudio.py`, not in `studio.session`.

Also removed the old single-argument `cmd_cost(state)` (last-turn only) in favour of the new `cmd_cost(state, args)` which shows session totals.

### New features (v9.5 second patch)
- `cmd_recap(state, args, history)` — AI session summary; registered at `/recap` in main dispatch
- `cmd_gitdiff(state, args)` — runs `git diff` in workspace root; `args == "stat"` runs `--stat HEAD`
- `cmd_branch(state, args)` — runs `git rev-parse --abbrev-ref HEAD` + `git log --oneline -7` + `git status --short`
- `cmd_setmodel(state, args)` — delegates to `cmd_model`; exposed via `/set model <name>` dispatch
- `cmd_cost(state, args)` — session-total cost panel using `load_usage()` + `MODEL_PRICING`; replaces old last-turn-only version
- `cmd_quicknote(state, args)` / `cmd_quicknotes(state, args)` — session notes stored in `~/.aistudio/notes.json`; exposed as `/qnote` / `/qnotes`
- `cmd_undo_exchange(state, args, history)` — removes last user+model turn pair from history; NOT yet wired to a slash command (conflict with `/undo` which handles file restores)

### Bug fixes
- `cmd_usage`: plan-aware rate limit cap derived from `_rl_caps`/`_rl_windows` dicts matching `check_rate_limit()` limits; was hardcoded `10/hr` for all plans
- `cmd_tokens`: now shows session totals (via `load_usage()`) and estimated cost; was always printing "Usage: /tokens" when no last_turn

### Nova welcome screen
Old: hardcoded fixed-width ASCII art `╔══...══╗` box via `_animate_banner`. VERSION injection was misaligned when VERSION length changed.
New: `Panel()` with `title` and `subtitle`, consistent with all other UI styles.

### Deferred items
- `/undo-exchange` or equivalent — history undo is implemented in `cmd_undo_exchange` but no slash command registered yet (conflict with `/undo` = file restore)
- `rain` and other `_animate_banner`-based welcome screens still use hardcoded-width ASCII boxes — same alignment risk as nova had

## v9.5 patch — Bug Fixes (2026-05-18)

### Re-declaration cleanup (second pass)
After the v9.5 fix that deleted the local `PLANS` block, a second audit found further local re-declarations that shadow studio/ imports:

- **`load_persona` / `save_persona` / `load_memory` / `save_memory`** (lines ~2664-2678): Local `load_persona` returned `PERSONAS["default"]` as fallback when no persona file exists; `studio/session.load_persona` returns `""`. The local version silently injected a system prompt for new users even when no persona had been configured. All four re-declarations removed; imports take effect.

- **`SKIP_DIRS`, `CODE_EXTS`, `MAX_FILE_CHARS`, `MAX_TOTAL_CHARS`** (lines ~11687-11693): Re-declared in the agent/project-scanner section. Identical to `studio/data.py` values but shielded them from upstream changes. Removed.

- **`AGENT_ROSTER`** (lines ~11695-11700): Re-declared with a slightly extended `wizzard` persona. The extra text ("Every answer is a spell that works. Experimental, creative, always shipping.") was moved into `studio/data.py` as the canonical definition. Local re-declaration removed.

- **`OLLAMA_BASE`** (line ~11842): Redundant re-declaration of the same value from `studio/data.py`. Removed.

**Pattern note**: Any module-level `FOO = ...` in `aistudio.py` that duplicates a name already in `studio/` is a silent hazard — the local assignment runs after the `from studio import *` at the top and wins, making `studio/` changes invisible at runtime. Always add new constants to `studio/data.py` only.

### Rate-limit display fix
`cmd_usage` hardcoded `"(free cap: 5/hr)"` in its display string. `check_rate_limit()` has always used limit=10/hr for free. Fixed to `"(free cap: 10/hr)"`.

---

## Known Issues / Technical Debt

- `typewrite()` is broken for strings containing Rich markup when `style=""` — each character is printed in a separate `console.print()` call so markup tags are never interpreted as a whole. Fixed in v5.7 for all known callsites but new `typewrite` calls must not embed Rich markup without a `style=` argument.
- `render_welcome` is now fully `Panel()`-based for all 7 UIs — no raw f-string width arithmetic with markup content.
- `_make_toolbar` runs `load_profile()` and `load_memory()` on every keypress (prompt_toolkit calls `_toolbar()` continuously). Should cache with a short TTL.
- Gemini CLI detection (`detect_gemini_cli()`) runs `shutil.which` on every call — no caching.

---

## v9.1 — Fixes & Internal Notes (2026-05-16)

- **`cmd_beta` double-def bug**: The second `def cmd_beta(state, args, history)` at ~line 7584 shadowed the first (v9 flags manager). Fixed by renaming the second to `cmd_beta_features`. Dispatch now routes `docx/xlsx/screenshot/video/feedback` to `cmd_beta_features`, all others to the flags manager (`cmd_beta`).
- **`cmd_voice` double-def bug**: TTS function (Windows `SpeechSynthesizer`) renamed to `cmd_tts`, exposed at `/tts`. The ultra-gated voice-to-text stub keeps the `/voice` route.
- **`cmd_vision_pro` history keys**: History entries were appended with `"parts"` key (Gemini REST format) instead of `"text"` key (internal format). Downstream `build_system_prompt` and `call_*` functions all expect `"text"`. Fixed.
- **`cmd_autonomous` None crash**: `args.lower()` called without checking if args is None. Fixed with `args = (args or "").strip()` guard.
- **`ensure_onboarded` bare `input()`**: Used `input()` instead of `_safe_input()`. Crashes in non-interactive contexts. Fixed.
- **Complaints invisible in analytics**: `/complain` wrote to `logs/complaints.json` but `/creator` reads `~/.aistudio/feedback_log.json`. Fixed by dual-writing complaints to both paths.
- **Auto-save**: Every AI exchange now calls `_autosave_session(history)` which writes to `~/.aistudio/autosave.json`. `/resume` reloads it.
- **`/alias` expansion at unknown-command fallback**: Unknown `/cmd` now checks `~/.aistudio/aliases.json` before showing "Unknown command" — allows aliases to work as top-level commands.
- **New config files added**: `aliases.json` (user-defined shortcuts), `notes.json` (quick notes), `autosave.json` (last session).

## v5.8 — Secret Changes & Internal Patches

- **Restart crash root cause**: `os.execv` on Windows fails when the process was launched via a `.bat` alias because `sys.argv[0]` may not resolve back to the actual script. Fixed by using `subprocess.Popen([sys.executable, str(script)] + sys.argv[1:])` + `sys.exit(0)` on Windows only.
- **`/vault` security note**: NOT truly encrypted — values are base64-encoded only (reversible without a key). This is obfuscation, not encryption. Real encryption would require `cryptography.fernet` which isn't in the install deps. Noted as "base64-encoded at rest" in the UI to avoid misleading users.
- **`/team` is local-only**: team member list stored in `~/.aistudio/team.json`. No actual email invitations are sent — requires a backend. Message in UI says "requires backend".
- **`_render_pro_welcome`** reads `feedback_log.json` to count unread complaints and shows a red alert badge if any exist. This runs on every startup for Pro users.
- **Feedback read-flagging**: `/creator` sets `entry["read"] = True` and rewrites `feedback_log.json`. The unread count in `_render_pro_welcome` checks `not entry.get("read")`.
- **Pro gate**: `_require_pro(state, feature)` checks `get_plan(state) in ("max", "ultra", "enterprise", "team")`. Returns `False` and prints gate Panel if not Pro.

## v5.7 — Secret Changes & Internal Patches

- Removed `state["api_key"]` / `state["openrouter_key"]` clearing from `cmd_logout` since those are session-only — only disk files are deleted now. The `sys.exit(0)` call after logout means the cleared state doesn't matter anyway.
- `cmd_audit` cap: only reads first 6 files (800 chars each) to stay within context limits. Codebase context window usage can spike badly with full project reads.
- `cmd_search` falls back to AI semantic search only when zero literal matches are found. This prevents unnecessary API calls for exact-match queries.
- `call_gemini_cli` uses `shutil.which("npx")` as fallback — this means on systems without the `gemini` binary it will try `npx @google/generative-ai-cli` which requires Node.js. If Node.js is absent, the error message is shown cleanly.
- `VIBE_PRESETS` dict is the canonical mapping for `/vibe`. Adding new vibes: add entry to `VIBE_PRESETS`, no other changes needed.
- **Markdown rendering fix**: non-streamed `ai_respond` now calls `console.print(Markdown(clean_text))` with a plain-text fallback. Streaming path already rendered inline via `_stream_print` — no change needed there.
- **`/balance` credits are mock/seeded**: `api_credits` is generated with `random.Random(seed + today)` — changes daily but deterministically per user. Not real balance data. Real payment integration would require a backend.
- **Enterprise inquiries** saved to `~/.aistudio/enterprise_inquiries.json` — creator must read this file manually (no server). Reference ID is `abs(hash(name+email)) % 99999` — not cryptographically unique, purely cosmetic.
- **Arena `same` mode**: passes `effort="low"` to thread 0 and `effort="pro"` to thread 1. The `arena_state` is a shallow `dict(state)` copy — mutating it inside the thread won't affect main state.
- **Arena cap**: max 4 models. Side-by-side `Columns` layout only for exactly 2 models; 3–4 models print stacked panels.
- `run_onboarding` now saves `dev_type` and `persona` to profile. The `persona` field is used to pre-set the AI system prompt on first launch if the user sets `/persona` after onboarding.
- **`/models` now includes built-in arrow-key picker**: `cmd_model_picker` is removed as a standalone, merged into `cmd_models`. Dispatch routes `pick`/`model-pick`/`mpick` to `cmd_models` as well.
- **Profile model_usage tracking**: `track_usage()` now increments `profile["model_usage"][model]` and updates `total_msgs`, `total_tokens_in/out`, `last_seen` on every AI call. `login_history` capped at 50 entries.
- **Profile fields added in v5.7+**: `first_seen`, `last_seen`, `total_msgs`, `total_tokens_in`, `total_tokens_out`, `model_usage` (dict), `session_count`, `login_history` (list of ISO timestamps).

---

## Config Files (`~/.aistudio/`)

| File | Purpose |
|------|---------|
| `config` | Gemini API key (raw text) |
| `openrouter_key` | OpenRouter API key |
| `hf_key` | HuggingFace token |
| `cursor_key` | Cursor API key |
| `profile.json` | User profile, plan, session counters |
| `ui_style` | Active UI style name |
| `theme` | Active theme name |
| `stream_mode` | Streaming mode |
| `workspace_root` | Saved workspace directory |
| `memory.json` | Persistent memory entries |
| `history` | prompt_toolkit input history |
| `onboarded` | Timestamp of first onboarding |
| `img_quota.json` | Image generation timestamps (3h window) |
| `trial.json` | Trial activation record |
| `feedback_log.json` | User feedback entries |
| `beta_feedback.json` | Beta feature feedback |
| `edit_perms` | Write permission mode |
| `caps.json` | Token cap settings |
| `debug.log` | Debug output |

---

## Deployment Notes

- Installed via `install_windows.bat` — registers `studio` and `aistudio` aliases in PATH
- No server component — fully local
- Windows Terminal recommended for full Unicode/emoji support
- Python 3.12+ required (`match` statements and `Path.unlink(missing_ok=True)`)
