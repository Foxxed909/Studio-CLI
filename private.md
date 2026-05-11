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

## Known Issues / Technical Debt

- `typewrite()` is broken for strings containing Rich markup when `style=""` — each character is printed in a separate `console.print()` call so markup tags are never interpreted as a whole. Fixed in v5.7 for all known callsites but new `typewrite` calls must not embed Rich markup without a `style=` argument.
- `render_welcome` is now fully `Panel()`-based for all 7 UIs — no raw f-string width arithmetic with markup content.
- `_make_toolbar` runs `load_profile()` and `load_memory()` on every keypress (prompt_toolkit calls `_toolbar()` continuously). Should cache with a short TTL.
- Gemini CLI detection (`detect_gemini_cli()`) runs `shutil.which` on every call — no caching.

---

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
