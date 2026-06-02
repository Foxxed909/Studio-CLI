---
name: project-studiocli-bugs
description: Recurring bug patterns, high-risk areas, and known gotchas in aistudio.py
metadata:
  type: project
---

## Recurring bug: double function definitions

aistudio.py is 9000+ lines. Functions that were added in multiple feature rounds have been defined twice, with the second shadowing the first. Confirmed cases (fixed in v9.1):
- `cmd_beta` — defined at ~line 6651 (v9 flags, 2-arg) and ~line 7584 (legacy features, 3-arg). Second shadowed first.
- `cmd_voice` — defined at ~line 4737 (Windows TTS, 1-arg) and ~line 6697 (voice-to-text stub, 2-arg). Second shadowed first.

**Why:** The file has been extended by concatenation across multiple sessions without checking for name collisions.
**How to apply:** Before adding any new `cmd_*` function, grep for existing definitions. Run `python -c "import ast; ..."` to check for AST-level duplicate `FunctionDef` names.

---

## High-risk area: history entry format

Internal history uses `{"role": "user"|"model", "text": "..."}`.
The Gemini REST API uses `{"role": "user"|"model", "parts": [{"text": "..."}]}`.

Code that builds history entries for ai_respond MUST use the internal `"text"` key format.
Code that calls the Gemini API directly (e.g. vision, arena) must convert history to `"parts"` format.

`cmd_vision_pro` had this bug (used `"parts"` key in history entries — fixed v9.1).

---

## High-risk area: None args in cmd_* functions

Many `cmd_*` functions receive `args` from the dispatch as `parts[1].strip() if len(parts) > 1 else ""`. But some call paths pass `None` (e.g. when the function is called internally, not from the REPL).

Pattern to always use at top of any cmd that takes args:
```python
args = (args or "").strip()
```

Confirmed bug: `cmd_autonomous` called `args.lower()` without None guard. Fixed v9.1.

---

## Known gotcha: typewrite() and Rich markup

`typewrite()` prints char-by-char. Rich markup tags like `[bold]` will be printed literally, not rendered. Never pass Rich markup strings to `typewrite()`.

---

## Known gotcha: _patch_autonomous_writes()

Only patches functions that look up `check_write_allowed` as a global name (module-level lookup). Functions that imported or closed over `check_write_allowed` at definition time won't see the patch.

---

## Known gotcha: complaint logging path mismatch (fixed v9.1)

`cmd_complain` wrote to `LOGS_DIR / "complaints.json"`.
`cmd_creator_analytics` and `_render_pro_welcome` read from `CONFIG_DIR / "feedback_log.json"`.
These are different directories and files — complaints were invisible in analytics.

Fix: `cmd_complain` now dual-writes to both paths.

---

## Recurring bug: module-level re-declarations shadow studio/ imports (v9.5 patch, 2026-05-18)

`aistudio.py` uses `from studio import *` at the top, but throughout the file there are module-level re-declarations of the same names. Since module-level code runs top-to-bottom, any `FOO = ...` assignment after the star-import overwrites the imported binding in the module namespace. Functions that reference `FOO` as a global see the local copy, not the studio/ version.

Confirmed cases removed in v9.5 patch:
- `PLANS` (removed v9.5): was missing feature flags from v9.3, broke plan gating for all paid plans
- `load_persona` / `save_persona` / `load_memory` / `save_memory` (removed v9.5 patch): local `load_persona` returned `PERSONAS["default"]` fallback instead of `""` — silently injected persona for new users
- `SKIP_DIRS`, `CODE_EXTS`, `MAX_FILE_CHARS`, `MAX_TOTAL_CHARS` (removed v9.5 patch): shadowed project-scanner constants from studio/data.py
- `AGENT_ROSTER` (removed v9.5 patch): had slightly different wizzard persona vs studio/data.py
- `OLLAMA_BASE` (removed v9.5 patch): redundant same-value re-declaration

**Why it keeps happening**: The file has been extended by appending new sections without checking if names are already imported. The section at line 11683+ ("AGENT SYSTEM + PROJECT SCANNER") historically contained its own copy of all the scanner constants.

**How to apply**: When auditing aistudio.py, grep for any `^[A-Z_]+ =` module-level assignments and cross-check against `studio/data.py` exports. Also grep for `^def load_\|^def save_` to catch function re-declarations.

Quick audit command:
```bash
python -c "
import ast, pathlib
tree = ast.parse(pathlib.Path('aistudio.py').read_text())
names = {}
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Assign)):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.setdefault(t.id, []).append(node.lineno)
        else:
            names.setdefault(node.name, []).append(node.lineno)
for k, v in names.items():
    if len(v) > 1:
        print(k, v)
"
```

---

## Stale display string: rate limit (fixed v9.5 second patch)

`cmd_usage` hardcoded `"(free cap: 10/hr)"` for all plans. Fixed to derive cap from `_rl_caps = {"free":10, "pro":200, "max":500, "ultra":1000, "enterprise":9999}` matching `check_rate_limit()`.

**Lesson**: Any hardcoded display string for a limit value must be kept in sync with the actual enforcement logic. Better to derive the display from the same constant dict used for enforcement.

---

## Recurring pattern: existing cmd_* functions before adding new ones

Before writing a new `cmd_<name>` function, grep for it first. Several names already exist with different semantics:
- `cmd_cost(state)` — existed as last-turn-only; needed replacement with session-total version
- `cmd_export(state, history)` — existed as interactive HTML exporter; new version with args was a duplicate
- `cmd_pin(state, args)` — existed as file-pinning (not note-pinning); new note feature needs a different name

**Quick audit before adding a feature**:
```bash
grep -n "^def cmd_<name>" aistudio.py
```
If found: check the signature and behavior. Either enhance the existing function or use a different name.

---

## f-string gotcha: dict literals inside f-strings

`f"... {{'key': val}.get(x, default)} ..."` — the double braces `{{}}` escape correctly for the literal `{}` delimiters, but Python f-string parsing can still fail if the inner expression is complex. Always pre-compute into a local variable before using in f-strings.

BAD: `f"cap: {{'free':10}.get(plan,10)}/hr"`
GOOD:
```python
_caps = {"free": 10, "pro": 200}
cap = _caps.get(plan, 10)
f"cap: {cap}/hr"
```

---

## Config files added in v9.1

- `~/.aistudio/aliases.json` — user-defined slash command shortcuts
- `~/.aistudio/notes.json` — quick session notes
- `~/.aistudio/autosave.json` — auto-saved session history (updated after every AI exchange)
