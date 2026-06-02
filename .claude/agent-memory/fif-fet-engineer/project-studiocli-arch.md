---
name: project-studiocli-arch
description: StudioCLI architecture — single-file monolith, studio/ subpackage, dispatch pattern
metadata:
  type: project
---

## File structure

- `aistudio.py` — 9000+ line monolith, all logic here
- `studio/data.py` — all static data: PLANS, THEMES, PERSONAS, MODEL_PRICING, AGENT_ROSTER, VERSION
- `studio/` — subpackage (console, paths, session, project, providers, agents)
- `profiles/<user_id>/profile.json` — per-user profile
- `~/.aistudio/` — CONFIG_DIR (API keys, settings, analytics)
- `logs/` — LOGS_DIR (feedback, complaints, inbox)
- `web/` — Node/Express companion web UI

## VERSION is in studio/data.py

`VERSION = "9.1"` — bump minor for new features, major for rewrites.
aistudio.py imports it: `from studio.data import VERSION`.

## Command dispatch pattern

All slash commands go through the big `while True` loop in `run_repl()`. Pattern:
```python
elif cmd == "mycommand":
    history = cmd_mycommand(state, args, history)
```
- Must add to BOTH `ALL_COMMANDS` list AND `COMMAND_METADATA` dict (for autocomplete + help)
- Functions that modify history must take and return `history`
- Functions that modify state must take and return `state`

## History format (internal)

```python
{"role": "user",  "text": "the user message"}
{"role": "model", "text": "the AI response"}
```
Never use "parts" key in internal history — that's the Gemini REST API format.

## ai_respond signature

```python
result, history = ai_respond(state, prompt, history, silent=False)
```
Returns (response_text, updated_history).

## Key state keys

- `state["model"]` — current model ID
- `state["api_key"]` — Gemini API key
- `state["openrouter_key"]` — OpenRouter key
- `state["_last_prompt"]` — last user message (for /retry, /regen)
- `state["_last_response"]` — last AI response (for /tts, /clip)
- `state["theme"]` — THEMES[name] dict
- `state["ui_style"]` — "studio"|"claude"|"codex"|"gemini"|"ghost"|"nova"|"foxxia"
- `state["autonomous"]` — bool, skip write permission prompts
- `state["multiline_mode"]` — bool (new v9.1)

## Plan gating pattern

```python
if not _require_tier(state, ("ultra", "enterprise"), "/feature", "/upgrade ultra"):
    return
```
Or:
```python
plan_id = get_plan(state)
if plan_id == "free":
    ...
```
