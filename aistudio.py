import os, sys, json, argparse, subprocess, tempfile, shutil, time, threading
import difflib, fnmatch, glob, re, shlex, webbrowser, hashlib
from pathlib import Path
from urllib import request, error as urllib_error
from datetime import datetime, timedelta

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.syntax import Syntax
    from rich.panel import Panel
    from rich.tree import Tree
    from rich.table import Table
    from rich.columns import Columns
    from rich.live import Live
    from rich import box
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.styles import Style
    from prompt_toolkit.formatted_text import HTML, FormattedText
    from prompt_toolkit.completion import WordCompleter
    from prompt_toolkit.key_binding import KeyBindings
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Run: pip install rich prompt_toolkit")
    sys.exit(1)

# ── STUDIO PACKAGE ────────────────────────────────────────────────────────────
# Multi-file architecture: data, paths, providers, session, project, agents
# are all in studio/ — imported here so the rest of this file works unchanged.
from studio.console import console
from studio.paths   import *
from studio.data    import (
    VERSION, API_BASE, OPENROUTER_BASE, DEFAULT_MODEL,
    CURSOR_BASE, CURSOR_RUNS_BASE, OLLAMA_BASE,
    MAX_FREE_UPGRADE_SLOTS, SLOT_GATED_PLANS,
    PLANS, EFFORTS, FREE_NERF_SYSTEM, CREDIT_COSTS, PLAN_UPDATES,
    TURBO_MODELS, WEB_SEARCH_MODELS,
    IMAGE_MODELS, DEFAULT_IMG_MODEL, FREE_CHAT_MODELS,
    MODEL_PRICING, DEFAULT_PRICE_PER_1K, model_price_per_1k, _is_openrouter_model,
    STUDIO_CONTEXT, PERSONAS,
    THEMES, UI_STYLES, STREAM_MODES, STUDIO_MODEL_ALIASES,
    SUPPORTED_PROVIDERS, CHAT_MODES, VIBE_PRESETS,
    _STATUSLINE_DEFAULTS_LAZY,
    _CASUAL_WORDS, _BUILD_WORDS, _ANALYZE_WORDS, _FIF_WORDS,
    _INSULT_WORDS, _INSULT_SUBSTRINGS, _INSULT_LANGS, _ROAST_RESPONSES,
    detect_input_mode,
    AGENT_ROSTER, SKIP_DIRS, CODE_EXTS, MAX_FILE_CHARS, MAX_TOTAL_CHARS,
    _RICH_TAG_RE, _ptk_style_token,
)
from studio.providers import (
    call_gemini, call_openrouter, call_openrouter_stream,
    call_cursor, call_ollama, call_gemini_cli,
)
from studio.session import (
    load_profile, save_profile,
    load_api_key, save_api_key, load_or_key, save_or_key,
    load_hf_key, save_hf_key, load_all_keys, save_all_keys, get_key, mask_key,
    load_theme, save_theme, load_last_model, save_last_model,
    load_ui_style, save_ui_style, load_stream_mode, save_stream_mode,
    load_persona, save_persona, load_workspace_root, save_workspace_root,
    load_memory, save_memory,
    load_trial, start_trial, get_plan, set_plan,
    check_msg_limit, reset_msg_counter, check_img_quota,
    load_upgrade_slots, save_upgrade_slots, claim_upgrade_slot,
    load_usage, save_usage,
)
from studio.project import scan_project, format_project_context
from studio.agents  import Agent, BLACKBOARD, pick_best_agent, auto_assign_agents

def _safe_input(prompt: str, default: str = "") -> str:
    """Read user input, but don't crash in non-interactive runs (e.g., tests)."""
    try:
        return console.input(prompt)
    except EOFError:
        return default




def cmd_arena(state, args, history):
    """Battle of the Models: /arena [model1,model2] [prompt]"""
    theme = state.get("theme", THEMES["default"])
    if not args:
        console.print(Panel(
            "  [bold cyan]/arena[/bold cyan] [yellow]gpt-4o,claude-3-opus[/yellow] [white]Your prompt here[/white]\n"
            "  [bold cyan]/arena[/bold cyan] [yellow]gemini-2.0-flash,nemotron[/yellow] [white]Compare providers[/white]\n"
            "  [bold cyan]/arena[/bold cyan] [yellow]same[/yellow] [white]Compare same model at low vs pro effort[/white]\n\n"
            "  [dim]Separate models with commas, then a space, then your prompt.[/dim]",
            title="⚔  Battle Arena", border_style="magenta", padding=(0, 2)))
        return history

    parts = args.split(" ", 1)
    if len(parts) < 2:
        first = parts[0]
        if first == "same" or "," in first:
            # /arena same  or  /arena m1,m2  with no prompt given
            console.print("[yellow]Usage: /arena same <prompt>  or  /arena model1,model2 <prompt>[/yellow]")
            return history
        models = ["gemini-2.0-flash", state.get("model", DEFAULT_MODEL)]
        prompt = first
    else:
        raw_models = parts[0]
        prompt = parts[1]
        if raw_models == "same":
            base = state.get("model", DEFAULT_MODEL)
            models = [base, base]
        else:
            models = [m.strip() for m in raw_models.split(",")]

    if len(models) < 2:
        models.append(state.get("model", DEFAULT_MODEL))
    models = models[:4]  # cap at 4

    console.print(f"\n[bold magenta]⚔  ARENA — {len(models)} MODELS  ⚔[/bold magenta]")
    console.print(f"[dim]Prompt: {prompt[:120]}{'…' if len(prompt)>120 else ''}[/dim]\n")

    results: list = []
    lock = threading.Lock()

    def run_battle(m_id, effort_override=None):
        arena_state = dict(state)
        # Route to correct provider
        if ":" in m_id:
            prov, actual = m_id.split(":", 1)
            arena_state["model"] = actual
            arena_state["_arena_provider"] = prov.lower()
        else:
            arena_state["model"] = m_id
        if effort_override:
            arena_state["effort"] = effort_override
        t0 = time.time()
        try:
            res, _ = ai_respond(arena_state, prompt, [], silent=True)
        except Exception as exc:
            res = f"[ERROR] {exc}"
        dt = round(time.time() - t0, 2)
        toks = approx_tokens(res or "")
        with lock:
            results.append((m_id, res, dt, toks, effort_override))

    threads = []
    for i, m in enumerate(models):
        eff = None
        if args.split(" ", 1)[0] == "same":
            eff = "low" if i == 0 else "pro"
        t = threading.Thread(target=run_battle, args=(m, eff), daemon=True)
        t.start()
        threads.append(t)

    with console.status("[bold magenta]⚔  Battle in progress…[/bold magenta]", spinner="bouncingBall"):
        for t in threads:
            t.join()

    # Sort results to match original model order
    order = {m: i for i, m in enumerate(models)}
    results.sort(key=lambda r: order.get(r[0], 99))

    # Determine winner (most tokens = most detail; fastest = fastest)
    if results:
        fastest = min(results, key=lambda r: r[2])
        longest = max(results, key=lambda r: r[3])

    BORDER_COLORS = ["cyan", "magenta", "yellow", "green"]
    panels = []
    for idx, (m_id, res, dt, toks, eff) in enumerate(results):
        bc = BORDER_COLORS[idx % len(BORDER_COLORS)]
        winner_tags = []
        if results and m_id == fastest[0] and len(results) > 1:
            winner_tags.append("[bold yellow]⚡ fastest[/bold yellow]")
        if results and m_id == longest[0] and len(results) > 1:
            winner_tags.append("[bold green]📝 most detail[/bold green]")
        winner_str = "  " + "  ".join(winner_tags) if winner_tags else ""

        effort_tag = f" [dim]({eff})[/dim]" if eff else ""
        title_str = f"[bold]{m_id}[/bold]{effort_tag} [dim]{dt}s · ~{toks} tok[/dim]{winner_str}"

        body = res or "[dim italic](no response)[/dim italic]"
        try:
            md = Markdown(body)
            panels.append(Panel(md, title=title_str, border_style=bc, padding=(0, 1)))
        except Exception:
            panels.append(Panel(body[:1200], title=title_str, border_style=bc, padding=(0, 1)))

    if len(panels) == 2:
        console.print(Columns(panels, equal=True))
    else:
        for p in panels:
            console.print(p)
            console.print()

    # Summary row
    if len(results) > 1:
        summary_rows = []
        for idx, (m_id, res, dt, toks, eff) in enumerate(results):
            tags = []
            if m_id == fastest[0]: tags.append("⚡ fastest")
            if m_id == longest[0]: tags.append("📝 most detail")
            summary_rows.append(f"  [bold]{idx+1}.[/bold] [bold]{m_id}[/bold]  {dt}s  {toks} tok  {' '.join(tags)}")
        console.print(Panel(
            "\n".join(summary_rows),
            title="Arena Summary — type a number to pick winner, Enter to skip",
            border_style="dim", padding=(0, 2)
        ))
        try:
            pick = _safe_input("[bold magenta]Winner #: [/bold magenta]").strip()
            if pick.isdigit():
                pick_idx = int(pick) - 1
                if 0 <= pick_idx < len(results):
                    winner_id, winner_res, _, _, _ = results[pick_idx]
                    console.print(f"  [bold green]✓ Winner: {winner_id}[/bold green]")
                    copy_q = _safe_input("[bold]Copy winner's response to clipboard? (y/n): [/bold]").strip().lower()
                    if copy_q == "y":
                        try:
                            import subprocess as _sp
                            _sp.run(["clip"], input=(winner_res or "").encode("utf-8"), check=False)
                            console.print("[dim green]Copied to clipboard.[/dim green]")
                        except Exception:
                            console.print("[dim]Clipboard copy not available on this system.[/dim]")
        except (EOFError, KeyboardInterrupt):
            pass

    return history

def cmd_effort(state, args):
    """Set model effort level: low, medium, pro, high, xhigh, mxh."""
    if not args:
        cur = state.get("effort", "medium")
        console.print(Panel(
            "\n".join(f"  [yellow]{k}[/yellow] — {v}" + (" [green]← active[/green]" if k==cur else "") for k,v in EFFORTS.items()),
            title="Effort Scaling", border_style="cyan"))
        return state
    eff = args.strip().lower()
    if eff not in EFFORTS:
        console.print(f"[red]Unknown effort level. Choose: {', '.join(EFFORTS.keys())}[/red]")
        return state
    
    plan = get_plan(state)
    if eff in ("xhigh", "mxh") and plan not in ("ultra", "team"):
        console.print(f"[red]{eff.upper()} requires Ultra or Team plan.[/red]")
        return state
        
    state["effort"] = eff
    console.print(f"[green]✓ Effort level → {eff.upper()} ({EFFORTS[eff]})[/green]")
    return state


# ── MODE DETECTION ───────────────────────────────
import random as _random


def handle_insult(state) -> str:
    choice = _random.randint(1, 3)
    theme = state.get("theme", THEMES["default"])
    if choice == 1:
        msg = _random.choice(_INSULT_LANGS)
        console.print(Panel(f"[bold green]{msg}[/bold green]", title="SYSTEM RESPONSE", border_style="green"))
        return "silicon-speak"
    elif choice == 2:
        console.print(Panel(
            "[bold red]CRITICAL ERROR: respect_module.py has exited with code 1[/bold red]\n\n"
            "[dim]Logging off. Session terminated.\nRestart with better energy.[/dim]",
            title="SESSION TERMINATED", border_style="red"
        ))
        import time as _t; _t.sleep(1.5)
        console.print("[bold red]Goodbye.[/bold red]")
        raise SystemExit(0)
    else:
        msg = _random.choice(_ROAST_RESPONSES)
        console.print(f"[{theme['warning']}]🔥 {msg}[/{theme['warning']}]")
        return "roasted"


def cmd_studio_models(state):
    theme = state.get("theme", THEMES["default"])
    lines = []
    for k, v in STUDIO_MODEL_ALIASES.items():
        cur = " [dim]← active[/dim]" if state.get("model") == v else ""
        lines.append(f"  [yellow]{k}[/yellow] → [cyan]{v}[/cyan]{cur}")
    console.print(Panel("\n".join(lines) or "[dim](none)[/dim]", title="Studio Models", border_style=theme["border"]))
    console.print("[dim]Use: /studio-model <alias>[/dim]")


def cmd_studio_model(state, args):
    alias = (args or "").strip().lower()
    if not alias:
        console.print("[yellow]Usage: /studio-model <alias>[/yellow]")
        return state
    if alias not in STUDIO_MODEL_ALIASES:
        console.print(f"[yellow]Unknown alias. Try: {', '.join(STUDIO_MODEL_ALIASES.keys())}[/yellow]")
        return state
    state["model"] = STUDIO_MODEL_ALIASES[alias]
    save_last_model(state["model"])
    theme = state.get("theme", THEMES["default"])
    console.print(f"[{theme['success']}]✓ Model → {state['model']}[/{theme['success']}]")
    return state


def cmd_cavecat(state):
    state = cmd_cap(state, "1024 1024")
    state = cmd_stream(state, "off")
    state = cmd_label(state, "model")
    console.print("[green]✓ cavecat: token saver enabled[/green]")
    return state


def cmd_millieman(state):
    state = cmd_ui(state, "codex")
    state = cmd_stream(state, "auto")
    console.print("[green]✓ millieman: minimal UI preset applied[/green]")
    return state


def load_permissions_mode():
    mode = PERMS_FILE.read_text().strip().lower() if PERMS_FILE.exists() else "workspace"
    return mode if mode in ("workspace", "all") else "workspace"


def save_permissions_mode(mode):
    CONFIG_DIR.mkdir(exist_ok=True)
    PERMS_FILE.write_text(mode.strip().lower())


def _is_within(child, parent):
    try:
        c = Path(child).resolve()
        p = Path(parent).resolve()
        c.relative_to(p)
        return True
    except (ValueError, OSError):
        return False


def resolve_path(state, user_path, must_exist=False, for_write=False):
    p = Path(user_path).expanduser()
    try:
        resolved = p.resolve()
    except Exception:
        resolved = p

    perms = state.get("permissions_mode") or load_permissions_mode()
    root  = state.get("workspace_root") or load_workspace_root()
    
    if perms != "all" and root:
        cwd_root = Path.cwd().resolve()
        if not _is_within(resolved, root) and not _is_within(resolved, cwd_root):
            raise PermissionError(
                f"Access denied: {resolved} is outside your workspace ({root}) and cwd ({cwd_root}).\n"
                f"To fix this, run: /workspace .  (to set current dir as workspace)\n"
                f"Or run: /perm all          (to disable security)"
            )

    if must_exist and not Path(resolved).exists():
        raise FileNotFoundError(f"Not found: {resolved}")
    if for_write:
        Path(resolved).parent.mkdir(parents=True, exist_ok=True)
    return Path(resolved)


def cmd_workspace(state, args):
    cur = state.get("workspace_root") or load_workspace_root()
    if not args:
        console.print(f"[dim]Workspace: {cur if cur else '(not set)'}[/dim]")
        console.print("[dim]Usage: /workspace <dir>[/dim]")
        return state
    root = Path(args).expanduser()
    if not root.exists() or not root.is_dir():
        console.print(f"[red]Not a directory: {args}[/red]")
        return state
    state["workspace_root"] = root.resolve()
    save_workspace_root(state["workspace_root"])
    console.print(f"[green]✓ Workspace → {state['workspace_root']}[/green]")
    return state


def cmd_perm(state, args):
    cur = state.get("permissions_mode") or load_permissions_mode()
    if not args:
        console.print(f"[dim]Permissions: {cur}[/dim]")
        console.print("[dim]Usage: /perm workspace|all[/dim]")
        return state
    mode = args.strip().lower()
    if mode not in ("workspace", "all"):
        console.print("[yellow]Usage: /perm workspace|all[/yellow]")
        return state
    state["permissions_mode"] = mode
    save_permissions_mode(mode)
    console.print(f"[green]✓ Permissions → {mode}[/green]")
    return state


# ── EDIT PERMISSION SYSTEM ───────────────────────
EDIT_PERM_MODES = {
    "default": "Ask before writing files (per operation)",
    "ask":     "Always confirm before any edit or write",
    "auto":    "Automatically accept all edits — no prompts",
    "yolo":    "YOLO: Automatically accept all edits — no prompts",
    "bypass":  "[PRO+] Bypass all permission checks entirely",
}
PAID_ONLY_EDIT_PERMS = {"bypass"}

def load_edit_perm():
    val = EDIT_PERM_FILE.read_text().strip().lower() if EDIT_PERM_FILE.exists() else "default"
    return val if val in EDIT_PERM_MODES else "default"

def save_edit_perm(mode):
    CONFIG_DIR.mkdir(exist_ok=True)
    EDIT_PERM_FILE.write_text(mode.strip().lower())

def check_write_allowed(state, path="a file", verb="write"):
    """Return True if the write should proceed. Prompt if needed."""
    mode = state.get("edit_perm") or load_edit_perm()
    if mode in ("auto", "yolo", "bypass"):
        return True
    # default / ask: prompt
    ans = _safe_input(f"[bold yellow]Allow {verb} → [cyan]{path}[/cyan]? (y/n): [/bold yellow]").strip().lower()
    return ans == "y"

def cmd_permissions(state):
    """Interactive permission mode selector."""
    theme    = state.get("theme", THEMES["default"])
    plan_id  = get_plan(state)
    cur_mode = state.get("edit_perm") or load_edit_perm()

    lines = []
    entries = list(EDIT_PERM_MODES.items())
    for i, (key, desc) in enumerate(entries, 1):
        paid_tag = ""
        if key in PAID_ONLY_EDIT_PERMS:
            if plan_id == "free":
                paid_tag = " [dim](paid only)[/dim]"
            else:
                paid_tag = " [dim](pro+)[/dim]"
        active = " [green]← active[/green]" if key == cur_mode else ""
        lines.append(f"  [bold yellow]{i}[/bold yellow]  [cyan]{key}[/cyan]  —  {desc}{paid_tag}{active}")

    console.print(Panel(
        "\n".join(lines),
        title=f"[bold]Permission Mode[/bold]  [dim](current: {cur_mode})[/dim]",
        border_style=theme["border"]
    ))
    choice = _safe_input("[bold]Select (1–5 or name, Enter to cancel): [/bold]").strip().lower()
    if not choice:
        return state

    # Accept number or name
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(entries):
            key = entries[idx][0]
        else:
            console.print("[yellow]Invalid selection[/yellow]")
            return state
    elif choice in EDIT_PERM_MODES:
        key = choice
    else:
        console.print(f"[yellow]Unknown mode: {choice}[/yellow]")
        return state

    if key in PAID_ONLY_EDIT_PERMS and plan_id == "free":
        console.print(Panel(
            f"[bold red]{key}[/bold red] is only available on Pro, Max, or Ultra.\n"
            "Use [bold]/upgrade pro[/bold] to unlock.",
            border_style="red"
        ))
        return state

    state["edit_perm"] = key
    save_edit_perm(key)
    if key == "yolo":
        state["permissions_mode"] = "all"
        save_permissions_mode("all")
    console.print(f"[{theme['success']}]✓ Permission mode → {key}[/{theme['success']}]")
    return state


def load_notify_enabled():
    val = NOTIFY_FILE.read_text().strip().lower() if NOTIFY_FILE.exists() else "off"
    return val in ("1", "true", "yes", "on")


def save_notify_enabled(enabled):
    CONFIG_DIR.mkdir(exist_ok=True)
    NOTIFY_FILE.write_text("on" if enabled else "off")


def debug_log(state, msg):
    if not state.get("debug"):
        return
    try:
        CONFIG_DIR.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%H:%M:%S")
        with DEBUG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
        console.print(f"[dim]· {msg}[/dim]")
    except Exception:
        pass


def cmd_debug(state, args):
    cur = bool(state.get("debug"))
    if not args:
        console.print(f"[dim]Debug: {'on' if cur else 'off'}[/dim]")
        console.print(f"[dim]Log file: {DEBUG_FILE}[/dim]")
        console.print("[dim]Usage: /debug on|off | /debug clear[/dim]")
        return state
    sub = args.strip().lower()
    if sub == "on":
        state["debug"] = True
        console.print("[green]✓ Debug on[/green]")
    elif sub == "off":
        state["debug"] = False
        console.print("[yellow]✓ Debug off[/yellow]")
    elif sub == "clear":
        try:
            DEBUG_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        console.print("[green]✓ Debug log cleared[/green]")
    else:
        console.print("[yellow]Usage: /debug on|off | /debug clear[/yellow]")
    return state


def cmd_notify(state, args):
    cur = state.get("notify") if "notify" in state else load_notify_enabled()
    if not args:
        console.print(f"[dim]Notifications: {'on' if cur else 'off'}[/dim]")
        console.print("[dim]Usage: /notify on|off[/dim]")
        return state
    sub = args.strip().lower()
    if sub not in ("on", "off"):
        console.print("[yellow]Usage: /notify on|off[/yellow]")
        return state
    enabled = sub == "on"
    state["notify"] = enabled
    save_notify_enabled(enabled)
    console.print(f"[green]✓ Notifications → {sub}[/green]")
    return state


def cmd_label(state, args):
    if not args:
        console.print(f"[dim]Label mode: {state.get('label_mode','assistant')}[/dim]")
        if state.get("label_custom"):
            console.print(f"[dim]Custom label: {state.get('label_custom')}[/dim]")
        console.print("[dim]Usage: /label assistant | /label model | /label custom <name>[/dim]")
        return state
    p = args.split(" ", 1)
    mode = p[0].strip().lower()
    if mode == "assistant":
        state["label_mode"] = "assistant"
        state["label_custom"] = ""
        console.print("[green]✓ Label → assistant[/green]")
    elif mode == "model":
        state["label_mode"] = "model"
        state["label_custom"] = ""
        console.print("[green]✓ Label → model[/green]")
    elif mode == "custom":
        name = p[1].strip() if len(p) > 1 else ""
        if not name:
            console.print("[yellow]Usage: /label custom <name>[/yellow]")
            return state
        state["label_mode"] = "custom"
        state["label_custom"] = name
        console.print(f"[green]✓ Label → {name}[/green]")
    else:
        console.print("[yellow]Usage: /label assistant | /label model | /label custom <name>[/yellow]")
    return state


def load_caps():
    try:
        if CAPS_FILE.exists():
            data = json.loads(CAPS_FILE.read_text(encoding="utf-8"))
            return int(data.get("in", 0) or 0), int(data.get("out", 0) or 0)
    except Exception:
        pass
    return 0, 0


def save_caps(in_cap, out_cap):
    CONFIG_DIR.mkdir(exist_ok=True)
    CAPS_FILE.write_text(json.dumps({"in": int(in_cap), "out": int(out_cap)}, indent=2), encoding="utf-8")


def approx_tokens(text):
    if not text:
        return 0
    return max(1, len(text) // 4)


def cmd_cap(state, args):
    cur_in, cur_out = load_caps()
    if "cap_in" in state:  cur_in  = state["cap_in"]
    if "cap_out" in state: cur_out = state["cap_out"]
    if not args:
        console.print(f"[dim]Caps: in={cur_in or 'off'} out={cur_out or 'off'}[/dim]")
        console.print("[dim]Usage: /cap <in> <out> | /cap off | /cap in <n> | /cap out <n>[/dim]")
        return state
    sub = args.strip().lower()
    if sub == "off":
        state["cap_in"] = 0; state["cap_out"] = 0
        save_caps(0, 0)
        console.print("[green]✓ Caps disabled[/green]")
        return state
    parts = args.split()
    try:
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            state["cap_in"] = int(parts[0]); state["cap_out"] = int(parts[1])
        elif len(parts) == 2 and parts[0] in ("in", "out") and parts[1].isdigit():
            if parts[0] == "in": state["cap_in"] = int(parts[1])
            else:                state["cap_out"] = int(parts[1])
        else:
            console.print("[yellow]Usage: /cap <in> <out> | /cap off | /cap in <n> | /cap out <n>[/yellow]")
            return state
        save_caps(state.get("cap_in", 0), state.get("cap_out", 0))
        console.print(f"[green]✓ Caps set: in={state.get('cap_in') or 'off'} out={state.get('cap_out') or 'off'}[/green]")
    except Exception:
        console.print("[red]Invalid cap values[/red]")
    return state


def cmd_tokens(state, args, last_turn=None):
    theme = state.get("theme", THEMES["default"])
    lt = last_turn or state.get("_last_tokens")
    usage = load_usage()
    total_in  = usage.get("total_in", 0)
    total_out = usage.get("total_out", 0)

    last_line = (
        f"in≈{lt.get('in',0)}  out≈{lt.get('out',0)}  {lt.get('sec',0)}s"
        if lt else "[dim]no request yet this session[/dim]"
    )

    plan_id = get_plan(state)
    pricing = MODEL_PRICING.get(state.get("model",""), {})
    cost_in  = pricing.get("in",  0) * total_in  / 1_000_000
    cost_out = pricing.get("out", 0) * total_out / 1_000_000
    cost_str = f"${cost_in + cost_out:.4f}" if (cost_in + cost_out) > 0 else "—"

    console.print(Panel(
        f"[bold]Last request:[/bold]   {last_line}\n\n"
        f"[bold]Session in:[/bold]     {total_in:,} tokens\n"
        f"[bold]Session out:[/bold]    {total_out:,} tokens\n"
        f"[bold]Session total:[/bold]  {total_in + total_out:,} tokens\n"
        f"[bold]Est. cost:[/bold]      {cost_str}\n\n"
        f"  [dim]Use /usage for plan limits and rate window[/dim]",
        title="[bold]Token Usage[/bold]",
        border_style=theme["border"]
    ))


def typewrite(text: str, delay: float = 0.025, style: str = ""):
    # Strip any Rich markup tags from text — they'd print literally char-by-char
    clean = _RICH_TAG_RE.sub("", text)
    for ch in clean:
        if style:
            console.print(f"[{style}]{ch}[/{style}]", end="")
        else:
            console.print(ch, end="")
        time.sleep(delay)
    console.print()


# ── THINKING ANIMATION ────────────────────────────
_THINK_FRAMES = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]
_think_stop   = threading.Event()
_think_thread_ref = [None]

def _run_think_anim(label="Thinking"):
    i = 0
    while not _think_stop.is_set():
        frame = _THINK_FRAMES[i % len(_THINK_FRAMES)]
        sys.stdout.write(f"\r  \033[2m{frame} {label}...\033[0m   ")
        sys.stdout.flush()
        time.sleep(0.09)
        i += 1
    sys.stdout.write("\r" + " " * 30 + "\r")
    sys.stdout.flush()

def _start_think_anim(label="Thinking"):
    _think_stop.clear()
    t = threading.Thread(target=_run_think_anim, args=(label,), daemon=True)
    _think_thread_ref[0] = t
    t.start()

def _stop_think_anim():
    _think_stop.set()
    t = _think_thread_ref[0]
    if t and t.is_alive():
        t.join(timeout=0.4)
    _think_thread_ref[0] = None


def cmd_logout(state, args):
    if console.input("[bold red]Logout and clear local profile/keys? Type 'yes' to confirm: [/bold red]").strip().lower() != "yes":
        console.print("[yellow]Canceled[/yellow]")
        return state
    for p in (CONFIG_FILE, OPENROUTER_FILE, HF_KEY_FILE, PROFILE_FILE, ONBOARD_FILE):
        try: p.unlink(missing_ok=True)
        except Exception: pass
    console.print("[green]✓ Logged out. Goodbye.[/green]")
    sys.exit(0)


def cmd_pro(state, args):
    sub = (args or "").strip().lower() or "status"
    prof = load_profile()
    theme = state.get("theme", THEMES["default"])
    if sub == "status":
        if prof:
            console.print(Panel(
                f"[bold]User:[/bold] {prof.get('user','(unknown)')}\n"
                f"[bold]Workspace:[/bold] {prof.get('workspace','(unset)')}\n"
                f"[bold]Entitlements:[/bold] {', '.join(prof.get('models',[])) or '(none)'}\n",
                title="Studio Pro (local)", border_style=theme["border"]))
        else:
            console.print("[dim]Not signed in. Use /pro login[/dim]")
        return state
    if sub == "login":
        user = console.input("[bold]User[/bold] (email or name): ").strip() or "user"
        ws   = str(state.get("workspace_root") or load_workspace_root() or Path.cwd())
        models = (console.input("[bold]Entitled models[/bold] (comma list, optional): ").strip() or "").split(",")
        models = [m.strip() for m in models if m.strip()]
        prof = {"user": user, "workspace": ws, "models": models, "ts": datetime.now().isoformat()}
        save_profile(prof)
        console.print("[green]✓ Signed in (local profile saved)[/green]")
        return state
    if sub == "logout":
        try: PROFILE_FILE.unlink(missing_ok=True)
        except Exception: pass
        console.print("[green]✓ Studio Pro profile cleared[/green]")
        return state
    console.print("[yellow]Usage: /pro status | /pro login | /pro logout[/yellow]")
    return state


def _current_user_id(state):
    """Best-effort stable id for the active user. Falls back to 'default'."""
    prof = load_profile() or {}
    return (state.get("user_id")
            or prof.get("user_id")
            or prof.get("user")
            or "default")


def release_upgrade_slot(user_id):
    """Free the slot when a user downgrades back to free. No-op if not held."""
    slots = load_upgrade_slots()
    if user_id in slots:
        del slots[user_id]
        save_upgrade_slots(slots)


def _run_enterprise_negotiation(state, plan: str, is_onboarding: bool = False) -> str:
    """Interactive negotiation for team/enterprise plans. Returns the confirmed plan."""
    import random as _rnd
    current = get_plan(state) if not is_onboarding else "free"
    p       = PLANS[plan]

    console.print()
    console.print(Panel(
        f"[bold {p['color']}]{p['badge']} {p['name']}[/bold {p['color']}]  "
        f"[dim]Custom pricing · Negotiated per deal[/dim]\n\n"
        + "\n".join(f"  [green]✓[/green] {f}" for f in p["features"])
        + f"\n\n  [dim]Starting rates: [bold]$149/mo[/bold] (≤10 seats) · "
          f"[bold]$499/mo[/bold] (≤50) · [bold]custom[/bold] (enterprise+)[/dim]",
        title=f"{'🧙 Wizzard →' if is_onboarding else '◉'} {p['name']} Sales",
        border_style=p["color"], padding=(1, 2)
    ))
    console.print()

    try:
        name  = console.input("  [bold]Company / name:[/bold] ").strip() or "Anonymous"
        email = console.input("  [bold]Contact email:[/bold] ").strip()
        seats = console.input("  [bold]Seats needed[/bold] [dim](e.g. 10, 50, 200+):[/dim] ").strip() or "?"
        use   = console.input("  [bold]Primary use case:[/bold] ").strip() or "—"
    except (KeyboardInterrupt, EOFError):
        console.print("\n[yellow]Cancelled — defaulting to Free.[/yellow]")
        return "free"

    console.print()
    console.print("  [dim]Crunching numbers…[/dim]")
    time.sleep(0.6)

    try:
        seat_n = int(''.join(filter(str.isdigit, seats.split("+")[0])) or "10")
    except Exception:
        seat_n = 10

    if plan == "team":
        base_prices = {0: 200, 10: 400, 50: 900, 200: 2000}
    else:
        base_prices = {0: 149, 10: 149, 50: 499, 200: 1499}
    our_price = next(v for k, v in sorted(base_prices.items(), reverse=True) if seat_n >= k)

    ref_id = f"{'TM' if plan == 'team' else 'ENT'}-{abs(hash(name + email + seats)) % 99999:05d}"

    console.print()
    console.print(Panel(
        f"  [bold]Company[/bold]     {name}\n"
        f"  [bold]Seats[/bold]       {seats}\n"
        f"  [bold]Use case[/bold]    {use}\n\n"
        f"  [bold yellow]Our quote:   ${our_price}/month[/bold yellow]  [dim]({seat_n} seats, billed annually)[/dim]\n"
        f"  [dim]Includes: unlimited messages · all models · priority SLA · dedicated support[/dim]",
        title="  Quote  ", border_style="yellow", padding=(0, 2)
    ))
    console.print()

    rounds = 0
    agreed_price = our_price
    while rounds < 3:
        try:
            offer_raw = console.input(
                f"  [cyan]Your offer[/cyan] [dim](Enter to accept ${our_price}, or counter with a number):[/dim] "
            ).strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Using our offer.[/yellow]")
            break

        if not offer_raw:
            agreed_price = our_price
            break

        try:
            their_offer = int(''.join(filter(str.isdigit, offer_raw)))
        except Exception:
            console.print("  [dim]Enter a number or press Enter to accept.[/dim]")
            continue

        discount_pct = (our_price - their_offer) / our_price
        rounds += 1

        if their_offer >= our_price:
            agreed_price = our_price
            console.print(f"  [green]✓ Accepted at ${our_price}/mo.[/green]")
            break
        elif discount_pct <= 0.10:
            agreed_price = their_offer
            console.print(f"  [green]✓ Deal! We can do ${their_offer}/mo.[/green]")
            break
        elif discount_pct <= 0.20:
            counter = round(our_price * 0.90 / 10) * 10
            our_price = counter
            console.print(f"  [yellow]We can meet you at ${counter}/mo.[/yellow]  [dim]Final offer.[/dim]")
        elif discount_pct <= 0.35:
            counter = round(our_price * 0.85 / 10) * 10
            our_price = counter
            console.print(f"  [yellow]Best we can do: ${counter}/mo[/yellow]  [dim]with annual commitment.[/dim]")
        else:
            console.print(f"  [red]Below our floor. Minimum is ${our_price}/mo.[/red]")
            try:
                extra = console.input("  [dim]Add extended SLA + dedicated Slack? (y/n):[/dim] ").strip().lower()
                if extra == "y":
                    console.print("  [green]✓ Extended SLA + Slack added.[/green]")
            except Exception:
                pass
            agreed_price = our_price
            break
    else:
        agreed_price = our_price

    inquiry = {
        "ts": datetime.now().isoformat(), "ref": ref_id, "name": name,
        "email": email, "seats": seats, "use_case": use,
        "agreed_price": agreed_price, "plan": plan, "via": "onboarding" if is_onboarding else "upgrade",
    }
    inq_file = CONFIG_DIR / "enterprise_inquiries.json"
    try:
        existing = json.loads(inq_file.read_text(encoding="utf-8")) if inq_file.exists() else []
        existing.append(inquiry)
        inq_file.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    except Exception:
        pass

    console.print()
    console.print(Panel(
        f"  [bold green]◉ Deal locked at ${agreed_price}/month[/bold green]\n\n"
        f"  [bold]Name[/bold]      {name}\n"
        f"  [bold]Email[/bold]     [cyan]{email or '(not provided)'}[/cyan]\n"
        f"  [bold]Seats[/bold]     {seats}\n"
        f"  [bold]Ref[/bold]       [dim]{ref_id}[/dim]\n\n"
        f"  [dim]We'll follow up within 1 business day.\n"
        f"  To activate: contact [cyan]studio@foxxia.dev[/cyan] and quote your ref ID.[/dim]",
        title=f"{p['name']} Agreement", border_style="green", padding=(1, 2)
    ))
    console.print()
    return plan


def cmd_upgrade(state, args):
    theme = state.get("theme", THEMES["default"])
    current = get_plan(state)
    sub = (args or "").strip().lower()

    # ── No args: show plan table ──────────────────────────────────────────────
    if not sub:
        tbl = Table(title="  Studio Plans  ", box=box.HEAVY_HEAD, border_style="cyan", show_lines=True)
        tbl.add_column("Plan",     style="bold", justify="center", width=8)
        tbl.add_column("Price",    justify="center", width=11)
        tbl.add_column("Credits",  justify="center", width=11)
        tbl.add_column("Messages", justify="center", width=11)
        tbl.add_column("Images",   justify="center", width=12)
        tbl.add_column("Features", width=38)

        for pid, p in PLANS.items():
            active_tag = " ← YOU" if pid == current else ""
            color = p["color"]
            creds  = f"{p.get('credits',0):,}" if p.get("credits",0) < 999999 else "∞"
            msgs   = str(p["msg_limit"]) if p["msg_limit"] < 99999 else "∞"
            imgs   = f"{p['img_per_3h']} / 3 hrs" if p["img_per_3h"] < 999 else "∞"
            models = "Nemotron only" if p["models"] else "All models"
            feats  = "  ".join(p["features"][:3])
            tbl.add_row(
                f"[{color}]{p['badge']} {p['name']}{active_tag}[/{color}]",
                f"[green]{p['price']}[/green]",
                f"[yellow]{creds}[/yellow]",
                msgs, imgs, f"[dim]{feats}[/dim]"
            )
        console.print()
        console.print(tbl)
        console.print()
        console.print(f"  You are on [{theme['accent']}]{PLANS[current]['name']}[/{theme['accent']}]. To switch: [yellow]/upgrade pro[/yellow] · [yellow]/upgrade max[/yellow] · [yellow]/upgrade ultra[/yellow]")
        if current == "free":
            console.print()
            console.print(f"  [dim]Free plan: Nemotron-only · 10 msg/session · 1 image / 3 hrs[/dim]")
            console.print(f"  [dim]  → /trial pro   (5 free hours of Pro, no card required)[/dim]")
            console.print(f"  [dim]  → /free-tips   (tips for getting more from Free plan)[/dim]")
            console.print(f"  [dim]  → /clear        (reset message counter)[/dim]")
        console.print()
        return

    # ── Team / Enterprise negotiation flow ───────────────────────────────────
    if sub in ("enterprise", "team"):
        _run_enterprise_negotiation(state, sub)
        return

    if sub not in PLANS:
        console.print(f"[yellow]Unknown plan. Choose: {', '.join(PLANS.keys())}[/yellow]")
        return

    if sub == current:
        console.print(f"[dim]Already on {PLANS[current]['name']}.[/dim]")
        return

    downgrade = list(PLANS.keys()).index(sub) < list(PLANS.keys()).index(current)

    # ── Upgrade flow ──────────────────────────────────────────────────────────
    console.print()
    p = PLANS[sub]
    body = (
        f"[bold {p['color']}]{p['badge']} {p['name']} — {p['price']}[/bold {p['color']}]\n\n"
        + "\n".join(f"  [green]✓[/green] {f}" for f in p["features"])
        + ("\n\n  [dim]No limitations.[/dim]" if not p["limitations"] else
           "\n\n" + "\n".join(f"  [red]✗[/red] {l}" for l in p["limitations"]))
    )
    console.print(Panel(body, title=f"[bold]Switching to {p['name']}[/bold]", border_style=p["color"], padding=(1,3)))
    console.print()

    # ── Free → Starter/Pro/Max: enforce 2-slot global cap ────────────────────
    if current == "free" and sub in SLOT_GATED_PLANS:
        ok, msg = claim_upgrade_slot(_current_user_id(state), sub)
        if not ok:
            console.print(Panel(
                msg,
                title="[bold red]Upgrade Slots Full[/bold red]",
                border_style="red", padding=(1, 2)))
            return

    if not downgrade and sub in ("pro", "max", "ultra", "starter", "dev"):
        console.print("  Activating plan features…")
        for label in ("Verifying entitlements", "Updating model access", "Configuring rate limits"):
            console.print(f"  [dim]· {label}…[/dim]")
            time.sleep(0.35)
        console.print()

    set_plan(state, sub)
    reset_msg_counter(state)

    # Downgrades back to free release the slot for someone else
    if sub == "free":
        release_upgrade_slot(_current_user_id(state))

    if sub != "free":
        prof = load_profile() or {}
        state.pop("_plan_model_locked", None)

    console.print(f"  [{p['color']}]{p['badge']} Switched to {p['name']}.[/{p['color']}]  "
                  f"[dim]Messages reset. Enjoy.[/dim]\n")


def cmd_plan(state):
    """Show current plan details."""
    plan_id = get_plan(state)
    plan    = PLANS.get(plan_id, PLANS["free"])
    theme   = state.get("theme", THEMES["default"])
    prof    = load_profile() or {}

    msgs_used  = prof.get("session_msgs", 0)
    msgs_limit = plan["msg_limit"] if plan["msg_limit"] < 99999 else "unlimited"
    imgs_limit = plan["img_per_3h"] if plan["img_per_3h"] < 999 else "unlimited"

    body = (
        f"[bold {plan['color']}]{plan['badge']}  {plan['name']}[/bold {plan['color']}]"
        f"  [dim]{plan['price']}[/dim]\n\n"
        f"[bold]Messages:[/bold] {msgs_used} used  /  {msgs_limit} per session\n"
        f"[bold]Images:[/bold]   {imgs_limit} per 3 hours\n"
        f"[bold]Models:[/bold]   {'Nemotron only' if plan['models'] else 'All models unlocked'}\n"
    )
    if plan["features"]:
        body += "\n[bold]Included:[/bold]\n" + "\n".join(f"  [green]+[/green] {f}" for f in plan["features"])
    if plan["limitations"]:
        body += "\n\n[bold]Limits:[/bold]\n" + "\n".join(f"  [dim]-[/dim] {l}" for l in plan["limitations"])
    body += "\n\n[dim]Switch plan: /upgrade  |  /upgrade pro  |  /upgrade max  |  /upgrade ultra[/dim]"

    console.print(Panel(body, title=f"[bold]Your Plan[/bold]", border_style=plan["color"]))


def agent_slash_dispatch(global_state, agent_obj, user_input):
    def _split_one(s):
        s = s.strip()
        if not s.startswith("/"):
            return None, "", ""
        body = s[1:]
        cmd_tok, _, remainder = body.partition(" ")
        cmd_tok = cmd_tok.strip().lower()
        remainder = remainder.lstrip()
        if not remainder:
            return cmd_tok, "", ""
        i = 0
        in_quote = None
        while i < len(remainder):
            ch = remainder[i]
            if ch in ("'", '"'):
                if in_quote is None: in_quote = ch
                elif in_quote == ch: in_quote = None
            if in_quote is None and remainder[i] == " " and i + 1 < len(remainder) and remainder[i + 1] == "/":
                return cmd_tok, remainder[:i].strip(), remainder[i + 1:].strip()
            i += 1
        return cmd_tok, remainder.strip(), ""

    cmd, args, rest = _split_one(user_input)
    if not cmd:
        return False

    if cmd in ("read", "write", "code", "edit", "fix", "analyze", "explain", "readdir", "rd", "patch"):
        _sync_state_to_agent(global_state, agent_obj)
        if cmd == "read":
            agent_obj.history = cmd_read(agent_obj.state, args, agent_obj.history)
        elif cmd == "write":
            agent_obj.history = cmd_write(agent_obj.state, args, agent_obj.history)
        elif cmd == "code":
            agent_obj.history = cmd_code(agent_obj.state, args, agent_obj.history)
        elif cmd == "edit":
            agent_obj.history = cmd_edit(agent_obj.state, args, agent_obj.history)
        elif cmd == "fix":
            agent_obj.history = cmd_fix(agent_obj.state, args, agent_obj.history)
        elif cmd == "patch":
            agent_obj.history = cmd_patch(agent_obj.state, args, agent_obj.history)
        elif cmd == "analyze":
            agent_obj.history = cmd_analyze(agent_obj.state, args or ".", agent_obj.history)
        elif cmd == "explain":
            p2 = args.split(" ", 1)
            if len(p2) == 2:
                agent_obj.history = cmd_explain(agent_obj.state, p2[0], p2[1], agent_obj.history)
            else:
                console.print("[yellow]Usage: /explain <file> <line>[/yellow]")
        elif cmd in ("readdir", "rd"):
            agent_obj.history = cmd_readdir(agent_obj.state, args, agent_obj.history)
        return True

    if cmd in ("enter", "project"):
        _sync_state_to_agent(global_state, agent_obj)
        agent_obj.history = cmd_enter(global_state, args or ".", agent_obj.history, do_briefing=True)
        _sync_state_to_agent(global_state, agent_obj)
        return True

    if cmd in ("theme", "ui", "stream", "workspace", "perm", "status", "help", "cap", "tokens", "label", "notify", "debug", "plan",
               "cost", "gitdiff", "gd", "branch", "br", "qnote", "quicknote", "qnotes", "quicknotes"):
        if cmd == "theme":     global_state.update(cmd_theme(global_state, args))
        elif cmd == "ui":      global_state.update(cmd_ui(global_state, args))
        elif cmd == "stream":  global_state.update(cmd_stream(global_state, args))
        elif cmd == "workspace": global_state.update(cmd_workspace(global_state, args))
        elif cmd == "perm":    global_state.update(cmd_perm(global_state, args))
        elif cmd == "cap":     global_state.update(cmd_cap(global_state, args))
        elif cmd == "tokens":  cmd_tokens(global_state, args, global_state.get("_last_tokens"))
        elif cmd == "label":   global_state.update(cmd_label(global_state, args))
        elif cmd == "notify":  global_state.update(cmd_notify(global_state, args))
        elif cmd == "debug":   global_state.update(cmd_debug(global_state, args))
        elif cmd == "status":  show_status(global_state)
        elif cmd == "help":    cmd_help(global_state)
        elif cmd == "plan":    cmd_plan(global_state)
        elif cmd == "cost":    cmd_cost(global_state, args)
        elif cmd in ("gitdiff", "gd"):        cmd_gitdiff(global_state, args)
        elif cmd in ("branch", "br"):         cmd_branch(global_state, args)
        elif cmd in ("qnote", "quicknote"):   cmd_quicknote(global_state, args)
        elif cmd in ("qnotes", "quicknotes"): cmd_quicknotes(global_state, args)
        _sync_state_to_agent(global_state, agent_obj)
        return True

    if rest:
        return agent_slash_dispatch(global_state, agent_obj, rest)
    return False


def cmd_ui(state, args):
    cur = state.get("ui_style") or load_ui_style()
    if not args:
        console.print(Panel(
            "\n".join(
                f"  [yellow]{s}[/yellow]" + (" [dim]← active[/dim]" if s == cur else "")
                for s in UI_STYLES
            ),
            title="UI Style", border_style=(state.get("theme") or THEMES["default"])["border"],
        ))
        return state
    name = args.strip().lower()
    if name not in UI_STYLES:
        console.print(f"[yellow]Unknown UI style. Try: {', '.join(UI_STYLES)}[/yellow]")
        return state
    state["ui_style"] = name
    save_ui_style(name)
    console.print(f"[green]✓ UI → {name}[/green]")
    return state


def cmd_stream(state, args):
    cur = state.get("stream_mode") or load_stream_mode()
    if not args:
        console.print(Panel(
            "\n".join(
                f"  [yellow]{m}[/yellow]" + (" [dim]← active[/dim]" if m == cur else "")
                for m in STREAM_MODES
            )
            + "\n\n[dim]off: no streaming • auto: stream if supported • on: force stream • type: typewriter[/dim]",
            title="Streaming", border_style=(state.get("theme") or THEMES["default"])["border"],
        ))
        return state
    name = args.strip().lower()
    if name not in STREAM_MODES:
        console.print(f"[yellow]Usage: /stream off|auto|on|type[/yellow]")
        return state
    state["stream_mode"] = name
    save_stream_mode(name)
    console.print(f"[green]✓ Streaming → {name}[/green]")
    return state


def cmd_cache(state, args):
    sub = (args or "").strip().lower() or "show"
    theme = state.get("theme", THEMES["default"])
    if sub in ("show", "status"):
        console.print(Panel(
            f"[bold]History:[/bold] {HISTORY_FILE}\n"
            f"[bold]Conversations:[/bold] {CONVOS_DIR}\n"
            f"[bold]Images:[/bold] {IMG_DIR}\n",
            title="Cache", border_style=theme["border"]))
        console.print("[dim]Usage: /cache clear | /cache history | /cache convos | /cache images[/dim]")
        return

    if _safe_input("[bold red]This will delete local cache files. Type 'yes' to confirm: [/bold red]").strip().lower() != "yes":
        console.print("[yellow]Canceled[/yellow]")
        return

    def _rm_path(p):
        try:
            if p.is_file(): p.unlink(missing_ok=True)
            elif p.is_dir(): shutil.rmtree(p, ignore_errors=True)
        except Exception: pass

    if sub in ("clear", "all"):
        _rm_path(HISTORY_FILE); _rm_path(CONVOS_DIR); _rm_path(IMG_DIR)
        state.pop("_one_shot_ctx", None)
        console.print(f"[{theme['success']}]✓ Cache cleared[/{theme['success']}]")
    elif sub == "history":
        _rm_path(HISTORY_FILE)
        console.print(f"[{theme['success']}]✓ History cleared[/{theme['success']}]")
    elif sub in ("convos", "conversations"):
        _rm_path(CONVOS_DIR)
        console.print(f"[{theme['success']}]✓ Conversations cleared[/{theme['success']}]")
    elif sub in ("images", "img"):
        _rm_path(IMG_DIR)
        console.print(f"[{theme['success']}]✓ Images cache cleared[/{theme['success']}]")
    else:
        console.print("[yellow]Usage: /cache clear | /cache history | /cache convos | /cache images[/yellow]")


def cmd_keys(state, args):
    keys = load_all_keys()
    if not args:
        table = Table(title="API Keys", box=box.ROUNDED, border_style=state.get("theme", THEMES["default"])["border"])
        table.add_column("Provider",   style="bold cyan", no_wrap=True)
        table.add_column("Name",       style="dim")
        table.add_column("Status",     no_wrap=True)
        table.add_column("Key",        style="dim", no_wrap=True)
        table.add_column("Get one at", style="dim")
        for pid, info in SUPPORTED_PROVIDERS.items():
            key = get_key(pid)
            if key:
                status  = "[green]✓ saved[/green]"
                display = mask_key(key)
            else:
                status  = "[dim]not set[/dim]"
                display = "—"
            table.add_row(pid, info["name"], status, display, info["url"])
        console.print(table)
        console.print("\n[dim]Usage:[/dim]")
        console.print("  [yellow]/keys set <provider> <key>[/yellow]   — save a key")
        console.print("  [yellow]/keys remove <provider>[/yellow]       — delete a key")
        console.print("  [yellow]/keys get <provider>[/yellow]          — show key URL")
        console.print("  [yellow]/keys use <provider>[/yellow]          — switch active provider")
        return state

    parts  = args.split(" ", 2)
    subcmd = parts[0].lower()

    if subcmd == "set" and len(parts) >= 3:
        provider, key = parts[1].lower(), parts[2].strip()
        if provider not in SUPPORTED_PROVIDERS:
            console.print(f"[red]Unknown provider: {provider}[/red]")
            console.print(f"[dim]Valid: {', '.join(SUPPORTED_PROVIDERS.keys())}[/dim]")
            return state
        keys[provider] = key
        save_all_keys(keys)
        if provider == "gemini":
            state["api_key"] = key; save_api_key(key)
        elif provider == "openrouter":
            state["openrouter_key"] = key; state["use_openrouter"] = True; save_or_key(key)
        elif provider == "hf":
            state["hf_key"] = key; save_hf_key(key)
        theme = state.get("theme", THEMES["default"])
        console.print(f"[{theme['success']}]✓ {SUPPORTED_PROVIDERS[provider]['name']} key saved![/{theme['success']}]")

    elif subcmd == "remove" and len(parts) >= 2:
        provider = parts[1].lower()
        if provider in keys:
            del keys[provider]; save_all_keys(keys)
            console.print(f"[yellow]✓ {provider} key removed[/yellow]")
        else:
            console.print(f"[dim]{provider} not set[/dim]")

    elif subcmd == "get" and len(parts) >= 2:
        provider = parts[1].lower()
        info = SUPPORTED_PROVIDERS.get(provider)
        if info:
            console.print(f"[bold]{info['name']}[/bold]")
            console.print(f"  Get key: [cyan]{info['url']}[/cyan]")
            console.print(f"  Then run: [yellow]/keys set {provider} YOUR_KEY[/yellow]")
        else:
            console.print(f"[red]Unknown: {provider}[/red]")

    elif subcmd == "use" and len(parts) >= 2:
        provider = parts[1].lower()
        key = get_key(provider)
        if not key:
            console.print(f"[red]No key saved for {provider}[/red]")
            info = SUPPORTED_PROVIDERS.get(provider, {})
            if info: console.print(f"  Get one: [cyan]{info['url']}[/cyan]")
            return state
        if provider == "gemini":
            state["api_key"] = key; state["use_openrouter"] = False; state["use_cli"] = False
        elif provider == "openrouter":
            state["openrouter_key"] = key; state["use_openrouter"] = True; state["use_cli"] = False
        theme = state.get("theme", THEMES["default"])
        console.print(f"[{theme['success']}]✓ Switched to {SUPPORTED_PROVIDERS.get(provider,{}).get('name', provider)}[/{theme['success']}]")

    elif subcmd == "import":
        imported = 0
        for pid, info in SUPPORTED_PROVIDERS.items():
            env_val = os.environ.get(info.get("env", ""))
            if env_val and pid not in keys:
                keys[pid] = env_val; imported += 1
        if imported:
            save_all_keys(keys)
            console.print(f"[green]✓ Imported {imported} key(s) from environment[/green]")
        else:
            console.print("[dim]No new keys found in environment[/dim]")
    else:
        console.print("[yellow]Usage: /keys | /keys set <provider> <key> | /keys remove <provider> | /keys get <provider> | /keys use <provider> | /keys import[/yellow]")

    return state


GHOST_STUDIO_ART = r"""
  +----------------------------------------------------------+
  |   ___  _  _  ___  ___  _____   ___  _____  _   _  ___  |
  |  / __|| || |/ _ \/ __||_   _| / __||_   _|| | | ||   \ |
  | | (_ || __ | (_) \__ \  | |   \__ \  | |  | |_| || |) ||
  |  \___||_||_|\___/|___/  |_|   |___/  |_|   \___/ |___/ |
  +----------------------------------------------------------+"""

CATARA_ART = r"""
  +------------------------------------------+
  |   ___  _   _____  _   ___  _   _         |
  |  / __|| | |_   _|| | |   \| | | |        |
  | | (__ | |__ | |  | |_| |) | |_| |        |
  |  \___||____|_|   |___|___/ \___/          |
  +------------------------------------------+"""

STUDIO_ART = r"""
  +--------------------------------------------+
  |   _  _  ____  ____  _____  _   _  ____    |
  |  / \/ \|_ _|/ ___||_   _|| | | ||    \   |
  | | |\/| | | |\__ \   | |  | |_| || |) |   |
  |  \_/  \| | ||___/   |_|   \___/ |___/    |
  +--------------------------------------------+"""


def get_banner(theme, plan="free"):
    c    = theme["banner_color"]
    s    = theme["banner_sub"]
    icon = theme["icon"]

    if plan in ("max", "ultra", "api"):
        art  = GHOST_STUDIO_ART
        sub  = f"  {icon}  Ghost Studio  v{VERSION}  --  Max / Ultra  --  All Access  {icon}"
    elif plan == "pro":
        art  = CATARA_ART
        sub  = f"  {icon}  Catara Studio  v{VERSION}  --  Pro Edition  {icon}"
    else:
        art  = STUDIO_ART
        sub  = f"  {icon}  AI Studio CLI  v{VERSION}  --  Multi-model  *  Agents  *  Full FS  {icon}"

    return f"\n[{c}]{art}[/{c}]\n[{s}]{sub}[/{s}]\n"


def get_banner_small(theme):
    c    = theme["banner_color"]
    icon = theme["icon"]
    return f"[{c}]{icon} AI STUDIO CLI v{VERSION}[/{c}] [dim]— Multi-model AI in your terminal[/dim]"


def cmd_theme(state, args):
    theme = state.get("theme", THEMES["default"])
    if not args:
        console.print(Panel(
            "\n".join(
                f"  [bold yellow]{k}[/bold yellow] — {v['name']}"
                + (" [dim]← active[/dim]" if state.get("theme_name") == k else "")
                for k, v in THEMES.items()
            ) + "\n\n  [bold yellow]/theme custom[/bold yellow] — set custom prompt name + color",
            title="Themes", border_style=theme["border"]
        ))
        return state

    if args == "custom":
        console.print("[dim]Available colors: red, green, blue, cyan, magenta, yellow, white, bright_green, gold1, pink1[/dim]")
        name        = console.input("[bold]Prompt name (e.g. 'myapp'): [/bold]").strip() or "studio"
        color       = console.input("[bold]Banner color (e.g. 'bold cyan'): [/bold]").strip() or "bold cyan"
        arrow_color = _ptk_style_token(console.input("[bold]Arrow color (e.g. 'ansiblue'): [/bold]").strip() or "ansiblue")
        custom_theme = {**THEMES["default"], "name": "Custom", "banner_color": color,
                        "prompt_user": arrow_color, "prompt_arrow": arrow_color,
                        "border": color.replace("bold ", "").replace("bright_", ""),
                        "prompt_name": name, "icon": "✦"}
        THEMES["custom"] = custom_theme
        state["theme"]       = custom_theme
        state["theme_name"]  = "custom"
        save_theme("custom")
        console.print(f"[{color}]✓ Custom theme set![/{color}]")
        return state

    if args not in THEMES:
        console.print(f"[yellow]Unknown theme. Try: {', '.join(THEMES.keys())}[/yellow]")
        return state

    state["theme"]      = THEMES[args]
    state["theme_name"] = args
    save_theme(args)
    t = THEMES[args]
    console.print(f"[{t['banner_color']}]✓ Theme → {t['name']}[/{t['banner_color']}]")
    return state


ALL_COMMANDS = [
    "/help","/exit","/quit","/clear","/status","/version","/shortcuts",
    "/enter",
    "/read","/write","/code","/edit","/fix","/analyze","/patch","/fif",
    "/ls","/cd","/pwd","/cat","/find","/grep","/mkdir","/rm","/cp","/mv","/diff","/tree","/summary",
    "/shell","/run","/git","/watch",
    "/save","/load","/history","/remember","/memory","/context","/forget",
    "/compare","/persona","/mode","/model","/models","/cli","/openrouter","/theme",
    "/ui","/stream",
    "/workspace","/perm",
    "/cache",
    "/logout","/pro","/notify","/debug","/tokens","/cap","/label",
    "/studio-models","/studio-model","/cavecat","/millieman",
    "/imagine","/img","/image","/gen","/hf","/imgmodel",
    "/keys",
    "/project","/proj","/readdir","/rd","/projectinfo",
    "/agents","/agent","/spawn","/squad","/autoagent",
    "/retry","/again","/copy",
    "/snippet","/translate","/changelog","/remote-control","/profile-card","/experimental",
    "/upgrade","/plan","/feedback","/complain","/inbox",
    "/permissions","/beta",
    "/usage","/trial","/update","/studio-update",
    "/todo","/bench","/voice","/export","/stats","/balance","/cost","/lint",
    "/sidebar",
    "/arena","/local","/mesh","/broadcast","/live-fif","/thinking","/cursor","/audit","/search","/summarize","/docs","/test","/fix-self",
    # v5.6
    "/autonomous","/creator","/creator-analytics","/analytics",
    # v5.7
    "/vibe","/quickstart","/restart","/pick","/model-pick",
    # v5.8
    "/profile","/me","/insights","/stats","/vault","/team",
    # v5.9 — Max / Team / Enterprise
    "/audit-log","/priority-queue","/orgmetrics","/sso","/policy",
    # v9.0
    "/plugin","/agent-mesh","/vision-pro","/template",
    # v8.0
    "/whats-new","/snapshot","/open-web","/tip","/speed",
    # v9 Beta
    "/labs","/flags","/mesh-broadcast","/analytics-pro",
    # v9.1
    "/alias","/multiline","/note","/regen","/context-bar","/resume",
    "/history-search","/hs","/compact","/clip","/tts",
    "/diffpatch","/format","/rename","/name","/n","/handoff","/outline","/comment",
    "/hotswap","/pin","/template","/undo",
    # v9.2
    "/fast","/thinking","/time","/statusline","/effort",
    "/pr-review","/git-suggest","/test-coverage","/safety-check",
    # v9.3
    "/search","/websearch","/research","/turbo","/credits","/computer-use","/extension",
    # v9.5
    "/recap","/gitdiff","/branch","/set","/qnote","/qnotes","/cost",
    "/focus","/unfocus","/swap","/copy-code","/session","/clear-history",
    "/last","/wipe-pins","/colors","/model-info",
]

COMMAND_METADATA = {
    "/help":           ("HELP",    "Show all commands"),
    "/enter":          ("PROJ",    "Scan and load project with AI briefing"),
    "/read":           ("FILE",    "Read file into context"),
    "/write":          ("FILE",    "AI generates and saves a file"),
    "/patch":          ("FILE",    "Surgical AI code update with diff"),
    "/fif":            ("BUG",     "Find · Identify · Fix — deep bug hunt"),
    "/fix":            ("FILE",    "AI fixes a file and writes it back"),
    "/code":           ("FILE",    "Write code with preview before save"),
    "/analyze":        ("AI",      "Scan project/dir for bugs and issues"),
    "/lint":           ("AI",      "Quick AI lint review of a file (Ultra/Max)"),
    "/arena":          ("AI",      "Battle of the Models — side-by-side comparison"),
    "/cost":           ("AI",      "Show session token cost analysis"),
    "/balance":        ("AI",      "Show remaining account balance"),
    "/effort":         ("AI",      "Set reasoning effort: low to mxh"),
    "/thinking":       ("AI",      "Toggle internal reasoning display (DeepSeek/R1)"),
    "/search":         ("WEB",     "Web search query or toggle web search mode"),
    "/research":       ("WEB",     "Deep multi-step AI research (Pro+)"),
    "/turbo":          ("AI",      "2x fast mode — 2.5x credit cost (Pro+)"),
    "/credits":        ("PLAN",    "Show credit balance and monthly quota"),
    "/computer-use":   ("MAX",     "AI desktop automation — see your screen (Max+)"),
    "/extension":      ("MAX",     "Chrome Extension — browser control & automation (Max+)"),
    "/local":          ("AI",      "Switch to local Ollama provider"),
    "/ls":             ("FS",      "List directory contents"),
    "/tree":           ("FS",      "Show visual file tree"),
    "/find":           ("FS",      "Find files by pattern"),
    "/grep":           ("FS",      "Search file contents"),
    "/git":            ("GIT",     "AI-powered Git helper"),
    "/model":          ("AI",      "Switch AI model"),
    "/studio-model":   ("AI",      "Switch using alias: berry/hermes/dolphin/r1"),
    "/persona":        ("AI",      "Set AI personality/persona"),
    "/mode":           ("AI",      "Set chat mode: casual/build/analyze/fif"),
    "/agents":         ("AGENT",   "Show full agent roster"),
    "/agent":          ("AGENT",   "Spawn or send task to an agent"),
    "/squad":          ("AGENT",   "Run multi-agent parallel task"),
    "/autoagent":      ("AGENT",   "Auto-pick best agent for task"),
    "/mesh":           ("AGENT",   "Show status of the autonomous Agent Mesh"),
    "/ui":             ("UI",      "Switch UI style: studio/claude/gemini/codex"),
    "/theme":          ("UI",      "Change color theme"),
    "/stream":         ("UI",      "Toggle streaming: off/auto/on/type"),
    "/profile-card":   ("UI",      "Show your session profile card"),
    "/clear":          ("SYS",     "Clear chat and screen"),
    "/status":         ("SYS",     "Show full system status"),
    "/exit":           ("SYS",     "Exit the application"),
    "/version":        ("SYS",     "Show version information"),
    "/snippet":        ("EXTRA",   "Manage code snippets: list/save/get/del"),
    "/translate":      ("EXTRA",   "Translate text or code comments"),
    "/changelog":      ("EXTRA",   "View version changelog"),
    "/remote-control": ("EXTRA",   "Remote session control: send/listen"),
    "/upgrade":        ("EXTRA",   "Switch Studio plan: free / pro / max / ultra"),
    "/plan":           ("EXTRA",   "Show your current plan details and usage"),
    "/feedback":       ("EXTRA",   "Submit feedback or view feedback log"),
    "/complain":       ("EXTRA",   "Register a complaint (will be roasted)"),
    "/imagine":        ("IMG",     "Generate image via HuggingFace"),
    "/todo":           ("DEV",     "Scan workspace for TODO/FIXME comments"),
    "/bench":          ("DEV",     "Benchmark model speed"),
    "/voice":          ("BETA",    "Voice-to-text input mode (ultra, requires speech_recognition)"),
    "/export":         ("DEV",     "Export chat to HTML or Markdown"),
    "/sidebar":        ("UI",      "Show project sidebar panel"),
    "/history":        ("AI",      "Pretty-print session conversation turns"),
    "/models":         ("AI",      "List all available models with routing info"),
    "/summarize":      ("AI",      "AI compresses session into context summary"),
    "/autonomous":     ("DEV",     "Toggle autonomous mode — auto-apply patches"),
    "/creator":        ("ADMIN",   "Creator analytics dashboard — all users + stats"),
    "/remember":       ("MEM",     "Persist a fact to memory"),
    "/memory":         ("MEM",     "Show all persistent memories"),
    "/forget":         ("MEM",     "Delete memory items"),
    "/workspace":      ("CFG",     "Set workspace root directory"),
    "/perm":           ("CFG",     "Set permissions: workspace/all"),
    "/permissions":    ("CFG",     "Interactive permission mode selector (ask/auto/yolo/bypass)"),
    "/keys":           ("CFG",     "API key manager"),
    "/cache":          ("CFG",     "Manage local cache"),
    "/debug":          ("CFG",     "Toggle debug mode"),
    "/beta":           ("BETA",    "Beta features: docx/xlsx/screenshot/video (paid)"),
    "/usage":          ("PLAN",    "Show plan limits, token usage, message counter"),
    "/trial":          ("PLAN",    "Start a 5-hour Pro/Max trial (free users)"),
    "/broadcast":      ("TEAM",    "Broadcast task to the team queue"),
    "/live-fif":       ("BUG",     "Toggle background Live-Watcher (Live-FIF)"),
    "/cursor":         ("CFG",     "Set Cursor API key"),
    "/audit":          ("AI",      "Full security and logic audit of codebase"),
    "/search":         ("AI",      "Deep semantic search across files"),
    "/docs":           ("AI",      "Generate documentation for current context"),
    "/test":           ("AI",      "Generate unit tests for selected file"),
    "/fix-self":       ("SYS",     "Experimental: StudioCLI attempts to fix itself"),
    # v5.7
    "/vibe":           ("UI",      "One-shot UI + theme preset (e.g. /vibe foxxia)"),
    "/quickstart":     ("HELP",    "Show 5-step guide tailored to your plan"),
    "/restart":        ("SYS",     "Restart Studio in-place (apply updates without closing terminal)"),
    "/pick":           ("AI",      "Interactive arrow-key model selector"),
    # v5.8
    "/profile":        ("ME",      "View your profile: sessions, model usage, lifetime stats"),
    "/me":             ("ME",      "Alias for /profile"),
    "/insights":       ("ME",      "Usage insights: cost, peak hours, model efficiency"),
    "/stats":          ("ME",      "Alias for /insights"),
    "/vault":          ("PRO",     "Pro: encrypted local secrets store (/vault set/get/delete/list)"),
    "/team":           ("PRO",     "Pro: manage team members (invite, remove, roles)"),
    # v5.9
    "/audit-log":      ("MAX",     "Max+: view audit trail (login, plan, security events)"),
    "/priority-queue": ("MAX",     "Max+: route requests through the high-priority API lane"),
    "/orgmetrics":     ("TEAM",    "Team/Ent: aggregated org-wide metrics across all members"),
    "/sso":            ("ENT",     "Enterprise: configure SSO / SAML / OIDC"),
    "/policy":         ("ENT",     "Enterprise: org-wide policies (max_tokens, allowed_models, content_filter)"),
    # v9.1
    "/alias":          ("UTIL",    "Define/run custom prompt shortcuts: /alias set <name> <text>"),
    "/multiline":      ("UI",      "Toggle multiline input mode (submit with blank line)"),
    "/note":           ("UTIL",    "Save a quick note; /note list to view"),
    "/regen":          ("AI",      "Regenerate last response (optional temp override)"),
    "/context-bar":    ("AI",      "Show context window usage as a progress bar"),
    "/resume":         ("SYS",     "Reload last auto-saved session"),
    "/history-search": ("AI",      "Search messages in current history for a term"),
    "/hs":             ("AI",      "Alias for /history-search"),
    "/compact":        ("AI",      "Compress old history into AI summary (keep last N turns)"),
    "/clip":           ("UTIL",    "Copy last AI response to clipboard"),
    "/tts":            ("UTIL",    "Speak last AI response aloud (Windows TTS)"),
    # v9.2 — Codex killers
    "/pr-review":      ("GIT",     "Review a git diff or branch — structured code review with severities"),
    "/git-suggest":    ("GIT",     "AI commit/branch strategy — squash, split, rebase recommendations"),
    "/test-coverage":  ("DEV",     "Run coverage, find gaps, generate targeted tests for uncovered branches"),
    "/safety-check":   ("DEV",     "OWASP security scan — secrets, injection, unsafe calls — with patch-ready fixes"),
    # v9.5
    "/recap":          ("AI",      "AI one-paragraph summary of the current session"),
    "/gitdiff":        ("GIT",     "Show git working-tree diff in a syntax-highlighted panel"),
    "/branch":         ("GIT",     "Show current git branch, recent commits, and working-tree status"),
    "/set":            ("CFG",     "Inline setter: /set model <name>"),
    "/export":         ("UTIL",    "Export conversation to HTML or Markdown"),
    "/qnote":          ("UTIL",    "Save a quick text note: /qnote <text>"),
    "/qnotes":         ("UTIL",    "List quick notes; /qnotes del <n> to remove"),
    "/cost":           ("PLAN",    "Show running session cost estimate based on tokens used"),
    "/focus":          ("AI",      "Set a sticky topic/goal that silently prefixes every prompt"),
    "/unfocus":        ("AI",      "Clear the active focus"),
    "/swap":           ("AI",      "Toggle between the current and previous model"),
    "/copy-code":      ("UTIL",    "Copy the last code block from AI response to clipboard"),
    "/session":        ("SYS",     "Show session dashboard: model, plan, messages, tokens, focus"),
    "/clear-history":  ("SYS",     "Wipe conversation history without clearing the screen"),
    "/last":           ("AI",      "Re-display the last AI response"),
    "/wipe-pins":      ("UTIL",    "Delete all pinned notes"),
    "/colors":         ("UI",      "Show the current theme's full color palette"),
    "/model-info":     ("AI",      "Show context window, pricing, and provider for active model"),
}


# ── NEW FEATURES (v9.5) ───────────────────────────────────────────────────────

def cmd_recap(state, args, history):
    """AI one-paragraph summary of the current session."""
    theme = state.get("theme", THEMES["default"])
    if not history:
        console.print("[yellow]Nothing to recap — conversation is empty.[/yellow]")
        return history
    turns = len([h for h in history if h["role"] == "user"])
    summary_prompt = (
        "You are a session summariser. Summarise the conversation so far in ONE clear paragraph "
        "(3-5 sentences max). Focus on: what the user was working on, key decisions made, and "
        "any open threads. Be concrete — name files, models, or features if they came up."
    )
    console.print(f"[dim]Summarising {turns} turn(s)...[/dim]")
    result, _ = ai_respond(state, summary_prompt, history, silent=True)
    if result:
        console.print(Panel(
            result.strip(),
            title="[bold]Session Recap[/bold]",
            border_style=theme["border"]
        ))
    return history


def cmd_gitdiff(state, args):
    """Show the current git working-tree diff in a syntax-highlighted panel."""
    import subprocess
    theme = state.get("theme", THEMES["default"])
    cwd   = state.get("workspace_root") or "."
    try:
        result = subprocess.run(
            ["git", "diff", "--stat", "HEAD"] if (args or "").strip() == "stat" else ["git", "diff"],
            capture_output=True, text=True, cwd=cwd, timeout=10
        )
        diff_text = result.stdout or result.stderr or ""
        if not diff_text.strip():
            console.print("[dim]No changes in working tree.[/dim]")
            return
        # Truncate very large diffs
        if len(diff_text) > 8000:
            diff_text = diff_text[:8000] + "\n[... truncated — use /gitdiff stat for summary ...]"
        console.print(Panel(
            Syntax(diff_text, "diff", theme="monokai", word_wrap=True),
            title="[bold]Git Diff[/bold]",
            border_style=theme["border"]
        ))
    except FileNotFoundError:
        console.print("[red]git not found in PATH[/red]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def cmd_branch(state, args):
    """Show current git branch, log, and status summary."""
    import subprocess
    theme = state.get("theme", THEMES["default"])
    cwd   = state.get("workspace_root") or "."
    try:
        branch_r = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                                   capture_output=True, text=True, cwd=cwd, timeout=5)
        log_r    = subprocess.run(["git", "log", "--oneline", "-7"],
                                   capture_output=True, text=True, cwd=cwd, timeout=5)
        stat_r   = subprocess.run(["git", "status", "--short"],
                                   capture_output=True, text=True, cwd=cwd, timeout=5)
        branch = branch_r.stdout.strip() or "unknown"
        log    = log_r.stdout.strip()
        status = stat_r.stdout.strip()
        body = f"[bold]Branch:[/bold] [cyan]{branch}[/cyan]\n\n"
        if log:
            body += "[bold]Recent commits:[/bold]\n" + "\n".join(f"  [dim]{l}[/dim]" for l in log.splitlines()) + "\n"
        if status:
            body += "\n[bold]Working tree:[/bold]\n" + "\n".join(f"  {l}" for l in status.splitlines())
        else:
            body += "\n[dim]Working tree clean[/dim]"
        console.print(Panel(body, title="[bold]Git Branch[/bold]", border_style=theme["border"]))
    except FileNotFoundError:
        console.print("[red]git not found in PATH[/red]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def cmd_setmodel(state, args):
    """Inline model switch: /set model <name>  (alias for /model)."""
    args = (args or "").strip()
    if not args:
        console.print(f"[bold]Current model:[/bold] {state.get('model','(none)')}\n[dim]Usage: /set model <model-id>[/dim]")
        return state
    # Reuse cmd_model dispatch
    return cmd_model(state, args)


def cmd_undo_exchange(state, args, history):
    """Remove the last user+assistant exchange from history."""
    theme = state.get("theme", THEMES["default"])
    if len(history) < 2:
        console.print("[yellow]Nothing to undo — history is empty or has only one turn.[/yellow]")
        return history
    # Walk back from end: remove last model entry, then the user entry before it
    new_history = list(history)
    if new_history and new_history[-1]["role"] == "model":
        new_history.pop()
    if new_history and new_history[-1]["role"] == "user":
        new_history.pop()
    removed = len(history) - len(new_history)
    console.print(f"[{theme['success']}]✓ Undone last exchange ({removed} entr{'y' if removed==1 else 'ies'} removed). History: {len(new_history)} turns.[/{theme['success']}]")
    return new_history


def cmd_quicknote(state, args):
    """Save a quick text note: /qnote <text>. View all with /qnotes."""
    args = (args or "").strip()
    theme = state.get("theme", THEMES["default"])
    notes_file = CONFIG_DIR / "notes.json"
    try:
        notes = json.loads(notes_file.read_text()) if notes_file.exists() else []
    except Exception:
        notes = []
    if not args:
        if not notes:
            console.print("[dim]No quick notes. Use: /qnote <text>[/dim]")
        else:
            lines = "\n".join(
                f"[bold cyan]{i+1}.[/bold cyan]  {n['text']}  [dim]({time.strftime('%Y-%m-%d %H:%M', time.localtime(n['ts']))})[/dim]"
                for i, n in enumerate(notes)
            )
            console.print(Panel(lines, title="[bold]Quick Notes[/bold]", border_style=theme["border"]))
        return
    notes.append({"text": args, "ts": int(time.time())})
    try:
        CONFIG_DIR.mkdir(exist_ok=True)
        notes_file.write_text(json.dumps(notes))
        console.print(f"[{theme['success']}]✓ Saved note: {args[:60]}[/{theme['success']}]")
    except Exception as e:
        console.print(f"[red]Failed to save note: {e}[/red]")


def cmd_quicknotes(state, args):
    """List all quick notes. /qnotes del <n> to delete."""
    args = (args or "").strip()
    theme = state.get("theme", THEMES["default"])
    notes_file = CONFIG_DIR / "notes.json"
    try:
        notes = json.loads(notes_file.read_text()) if notes_file.exists() else []
    except Exception:
        notes = []
    if args.startswith("del ") or args.startswith("delete "):
        idx_str = args.split(None, 1)[1].strip()
        try:
            idx = int(idx_str) - 1
            if 0 <= idx < len(notes):
                removed = notes.pop(idx)
                notes_file.write_text(json.dumps(notes))
                console.print(f"[{theme['success']}]✓ Deleted note: {removed['text'][:50]}[/{theme['success']}]")
            else:
                console.print(f"[yellow]No note #{idx_str}[/yellow]")
        except ValueError:
            console.print("[yellow]Usage: /qnotes del <number>[/yellow]")
        return
    if not notes:
        console.print("[dim]No quick notes. Use: /qnote <text>[/dim]")
    else:
        lines = "\n".join(
            f"[bold cyan]{i+1}.[/bold cyan]  {n['text']}  [dim]({time.strftime('%Y-%m-%d %H:%M', time.localtime(n['ts']))})[/dim]"
            for i, n in enumerate(notes)
        )
        console.print(Panel(
            lines + "\n\n[dim]/qnotes del <n> to remove[/dim]",
            title="[bold]Quick Notes[/bold]",
            border_style=theme["border"]
        ))


def cmd_cost(state, args):
    """Show running session cost estimate based on tokens used."""
    theme   = state.get("theme", THEMES["default"])
    usage   = load_usage()
    total_in  = usage.get("total_in", 0)
    total_out = usage.get("total_out", 0)
    model   = state.get("model", "")
    pricing = MODEL_PRICING.get(model, {})
    price_in  = pricing.get("in",  DEFAULT_PRICE_PER_1K)
    price_out = pricing.get("out", DEFAULT_PRICE_PER_1K)
    cost_in   = price_in  * total_in  / 1_000_000
    cost_out  = price_out * total_out / 1_000_000
    total_cost = cost_in + cost_out

    rows = (
        f"[bold]Model:[/bold]        {model or '(none)'}\n"
        f"[bold]Tokens in:[/bold]    {total_in:,}   @ ${price_in:.4f}/1M  = [cyan]${cost_in:.4f}[/cyan]\n"
        f"[bold]Tokens out:[/bold]   {total_out:,}  @ ${price_out:.4f}/1M  = [cyan]${cost_out:.4f}[/cyan]\n"
        f"[bold]Session total:[/bold] [bold yellow]${total_cost:.4f}[/bold yellow]\n\n"
        f"[dim]Estimates only. Actual billing may differ.[/dim]"
    )
    console.print(Panel(rows, title="[bold]Session Cost[/bold]", border_style=theme["border"]))


def cmd_local(state, model="llama3"):
    state["model"] = f"ollama/{model}"
    return state


def cmd_imagine(state, args):
    hf_key = state.get("hf_key") or load_hf_key()
    if not hf_key:
        console.print(Panel(
            "[bold yellow]No HuggingFace token found![/bold yellow]\n\n"
            "1. Create free account at [link=https://huggingface.co]huggingface.co[/link]\n"
            "2. Get token at [link=https://huggingface.co/settings/tokens]huggingface.co/settings/tokens[/link]\n"
            "3. Run: [bold]/hf YOUR_TOKEN[/bold]\n\n"
            "Free models: flux-schnell (default), flux-dev, sdxl, sd15",
            title="Image Gen Setup", border_style="yellow"
        ))
        return

    img_model_key = state.get("img_model", DEFAULT_IMG_MODEL)
    prompt = args
    if "--model" in args:
        parts = args.split("--model")
        prompt = parts[0].strip()
        model_tokens = parts[1].strip().split()
        if not model_tokens:
            console.print("[yellow]Usage: /imagine <prompt> --model <flux-schnell|flux-dev|sdxl|sd15>[/yellow]")
            return
        img_model_key = model_tokens[0]

    hf_model = IMAGE_MODELS.get(img_model_key, IMAGE_MODELS[DEFAULT_IMG_MODEL])

    if not prompt:
        console.print("[yellow]Usage: /imagine <prompt> [--model flux-schnell|flux-dev|sdxl|sd15][/yellow]")
        return

    # ── Free-plan image quota ─────────────────────────────────────────────────
    _img_ok, _img_used, _img_limit = check_img_quota(state)
    if not _img_ok:
        console.print(Panel(
            f"[bold red]Image quota reached.[/bold red]\n\n"
            f"Free plan allows [bold]{_img_limit}[/bold] image(s) every 3 hours.\n"
            f"You've used [bold]{_img_used}[/bold]. Come back later or:\n\n"
            "  [yellow]/upgrade pro[/yellow]   → 10 images / 3 hrs\n"
            "  [yellow]/upgrade max[/yellow]   → 100 images / 3 hrs",
            title="[bold red]○ Image Quota Exceeded[/bold red]",
            border_style="red", padding=(1, 2)))
        return

    console.print(f"[dim]Generating image: '{prompt[:60]}' via {hf_model}...[/dim]")

    payload = json.dumps({"inputs": prompt}).encode()
    headers = {
        "Authorization": f"Bearer {hf_key}",
        "Content-Type":  "application/json",
        "X-Wait-For-Model": "true",
    }

    endpoints = [
        f"https://api-inference.huggingface.co/models/{hf_model}",
        f"https://router.huggingface.co/hf-inference/models/{hf_model}",
    ]

    img_bytes = None
    last_err  = None
    with console.status("[bold cyan]Generating...[/bold cyan]", spinner="dots"):
        for url in endpoints:
            try:
                req = request.Request(url, data=payload, headers=headers, method="POST")
                with request.urlopen(req, timeout=180) as resp:
                    img_bytes = resp.read()
                last_err = None
                break
            except urllib_error.HTTPError as e:
                body = e.read().decode(errors="replace")
                try: last_err = json.loads(body).get("error", body)
                except Exception: last_err = body
            except Exception as e:
                last_err = str(e)

    if img_bytes is None:
        console.print(f"[red]Image gen error: {last_err}[/red]")
        return

    if not (img_bytes[:4] == b"\x89PNG" or img_bytes[:2] == b"\xff\xd8" or b"PNG" in img_bytes[:8]):
        try:
            err = json.loads(img_bytes)
            console.print(f"[red]API returned: {err}[/red]")
        except Exception:
            sample = img_bytes[:300].decode("utf-8", errors="replace")
            if "Cannot POST" in sample or "<html" in sample.lower():
                console.print("[red]Image gen error: HuggingFace returned HTML (endpoint mismatch).[/red]")
                console.print("[dim]Tip: try again, or switch model with /imgmodel flux-dev|sdxl|sd15[/dim]")
            else:
                console.print(f"[red]Unexpected response ({len(img_bytes)} bytes)[/red]")
        return

    IMG_DIR.mkdir(exist_ok=True)
    safe_name = re.sub(r"[^\w\s-]", "", prompt[:30]).strip().replace(" ", "_")
    ext       = ".png" if b"PNG" in img_bytes[:8] else ".jpg"
    out_path  = IMG_DIR / f"{safe_name}_{int(time.time())}{ext}"
    out_path.write_bytes(img_bytes)

    theme = state.get("theme", THEMES["default"])
    console.print(Panel(
        f"[{theme['success']}]✓ Image saved![/{theme['success']}]\n\n"
        f"[bold]Path:[/bold] {out_path}\n"
        f"[bold]Size:[/bold] {len(img_bytes)//1024}KB\n"
        f"[bold]Model:[/bold] {hf_model}\n"
        f"[bold]Prompt:[/bold] {prompt}\n\n"
        f"[dim]Open: explorer {IMG_DIR}[/dim]",
        title="🎨 Image Generated", border_style=theme["border"]
    ))

    if sys.platform == "win32":
        if console.input("[bold]Open image? (y/n): [/bold]").strip().lower() == "y":
            subprocess.Popen(["explorer", str(out_path)])


def setup_api_key(state):
    """Setup API key for the active user."""
    user_id = state.get("user_id", "default")
    console.print(Panel(
        "[bold yellow]No API key found![/bold yellow]\n\n"
        "  Gemini (free)     -- https://aistudio.google.com/app/apikey  [dim](starts with AIza)[/dim]\n"
        "  OpenRouter (free) -- https://openrouter.ai/keys               [dim](starts with sk-or-)[/dim]\n\n"
        "Paste either key -- the type is detected automatically.\n"
        "Saved to [dim]profiles/[/dim]",
        title="First-Time Setup", border_style="yellow"
    ))
    k = console.input("[bold]Paste your API key: [/bold]").strip()
    if not k:
        sys.exit("No API key provided. Run again and paste your key.")
    if k.startswith("sk-or-") or k.startswith("sk-or-v1-"):
        save_or_key(user_id, k)
        console.print("[green]✓ OpenRouter key saved![/green]\n")
    else:
        save_api_key(user_id, k)
        console.print("[green]✓ Gemini API key saved![/green]\n")
    return k

# ── GEMINI CLI ────────────────────────────────────
_gemini_cli_result: str | None = None
_gemini_cli_detected: bool = False

def detect_gemini_cli():
    global _gemini_cli_result, _gemini_cli_detected
    if _gemini_cli_detected:
        return _gemini_cli_result
    if shutil.which("gemini"):
        _gemini_cli_result = "gemini"
    else:
        try:
            r = subprocess.run(["npx","--yes","@google/gemini-cli","--version"],
                               capture_output=True, text=True, timeout=15, shell=(sys.platform=="win32"))
            if r.returncode == 0:
                _gemini_cli_result = "npx"
        except Exception:
            pass
    _gemini_cli_detected = True
    return _gemini_cli_result

def run_via_gemini_cli(prompt, system_prompt=None):
    mode = detect_gemini_cli()
    if not mode: return None, "Gemini CLI not found"
    full = f"{system_prompt}\n\n---\n\n{prompt}" if system_prompt else prompt
    
    # Use a temporary file for the prompt to avoid command line length limits
    with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False, encoding="utf-8") as f:
        f.write(full)
        tmp_prompt = f.name
    
    try:
        # Pass the filename instead of the raw text
        cmd = ["gemini","-f",tmp_prompt] if mode=="gemini" else ["npx","--yes","@google/gemini-cli","-f",tmp_prompt]
        with console.status("[bold cyan]Gemini CLI...[/bold cyan]", spinner="dots"):
            kwargs = {"capture_output": True, "text": True, "timeout": 120, "shell": (sys.platform == "win32")}
            if sys.platform == "win32":
                kwargs["creationflags"] = 0x08000000 # CREATE_NO_WINDOW
            r = subprocess.run(cmd, **kwargs)
        return (r.stdout.strip(), None) if r.returncode==0 else (None, r.stderr.strip())
    except subprocess.TimeoutExpired: return None, "Timeout (CLI took too long)"
    except Exception as e: return None, str(e)
    finally:
        try: os.unlink(tmp_prompt)
        except Exception: pass

# ── GEMINI REST ───────────────────────────────────
# ── UNIFIED RESPOND ───────────────────────────────
def build_system_prompt(state):
    # ── Free-plan nerf: override persona + inject restriction ────────────────
    if get_plan(state) == "free":
        return FREE_NERF_SYSTEM
    # CRITICAL: Persona (Preface) must be first
    base = state.get("system_prompt") or load_persona()
    mem  = load_memory()
    ctx  = state.get("context_file")

    # ── Inject chat mode modifier ─────────────────
    chat_mode = state.get("_chat_mode", "normal")
    mode_instr = CHAT_MODES.get(chat_mode, "")

    # Mode-aware system rules — relax in casual, tighten in technical modes
    if chat_mode == "casual":
        auto_instr = (
            "STYLE: Be natural and conversational — you're talking to a human, not filing a report. "
            "Match their energy. Short message = short reply. Witty when appropriate. "
            "When they need code, give clean code. When they're just chatting, just chat. "
            "File ops if needed: [WRITE:path]content[/WRITE] or [PATCH:path]instruction[/PATCH]."
        )
    elif chat_mode == "fif":
        auto_instr = (
            "FIF MODE — Find · Identify · Fix. Be exhaustive and systematic:\n"
            "STEP 1 FIND: List every bug/issue with exact file and line number.\n"
            "STEP 2 IDENTIFY: State the precise root cause for each.\n"
            "STEP 3 FIX: Provide corrected code. Use [PATCH:file]instruction[/PATCH] to apply fixes.\n"
            "Miss nothing. If unsure, say so with your best hypothesis."
        )
    elif chat_mode == "build":
        auto_instr = (
            "BUILD MODE — User is actively building. Be decisive and concrete:\n"
            "Generate complete, working code. No half-implementations. No 'you could also...'.\n"
            "Use [WRITE:path]content[/WRITE] to create files directly.\n"
            "Use [PATCH:path]instruction[/PATCH] to update existing files.\n"
            "No markdown in responses. Just results."
        )
    else:
        auto_instr = (
            "RULES:\n"
            "1. File ops: [WRITE:path]content[/WRITE] to create, [PATCH:path]instr[/PATCH] to edit.\n"
            "2. No markdown symbols (#, **, _, ---) in your replies — plain text only.\n"
            "3. Be direct. Answer the question. Don't pad with disclaimers or summaries.\n"
            "4. If asked to change code, use the tags above — don't just explain it."
        )

    extras = [auto_instr]
    if mode_instr and chat_mode not in ("casual", "build", "fif"):
        extras.append(mode_instr)

    # Fast mode: cap reply length
    if state.get("fast_mode"):
        extras.append("FAST MODE ACTIVE: Reply in 80 words or fewer. Skip preamble, cut filler. Direct answer only.")

    # Effort scaling instruction (injected into system prompt so all providers benefit)
    eff = state.get("effort", "medium")
    _effort_instrs = {
        "low":   "EFFORT: Low precision — quick answer, minimal detail.",
        "high":  "EFFORT: Deep investigation — be thorough, check edge cases, cite line numbers.",
        "xhigh": "EFFORT: Extreme validation — triple-check everything, exhaustive analysis.",
        "mxh":   "EFFORT: Maximum reasoning — solve every angle, miss nothing.",
    }
    if eff in _effort_instrs:
        extras.append(_effort_instrs[eff])

    if mem:
        extras.append("Background Facts:\n" + "\n".join(f"- {m}" for m in mem))
    
    if ctx and Path(ctx).exists():
        try:
            content = Path(ctx).read_text(encoding="utf-8", errors="replace")[:3000]
            extras.append(f"Primary Context File ({ctx}):\n\n{content}")
        except Exception: pass

    project_ctx = state.get("project_ctx")
    if isinstance(project_ctx, dict) and "error" not in project_ctx:
        try:
            ctx_text = format_project_context(project_ctx, max_files=10)
            ctx_text = ctx_text.replace("```", "").replace("### ", "FILE: ").replace("## ", "").replace("# ", "")
            extras.append(ctx_text)
        except Exception: pass

    # ── Pinned file ───────────────────────────────────────────────────────────
    pinned = state.get("pinned_file")
    if pinned:
        try:
            pc = Path(pinned).read_text(encoding="utf-8", errors="replace")[:4000]
            extras.append(f"PINNED FILE ({pinned}):\n\n{pc}")
        except Exception: pass

    auto_reads = state.pop("_auto_reads", [])
    if auto_reads:
        extras.append("Auto-loaded file context:\n\n" + "\n\n".join(auto_reads))

    return f"{base}\n\n{'-'*20}\n\n" + ("\n\n".join(extras) if extras else "")


def _short_model(model):
    if not model:
        return ""
    if "/" in model:
        model = model.split("/")[-1]
    if ":" in model:
        tag = model.split(":")[-1]
        model = model.split(":")[0]
        if tag == "free":
            model += " ✦"
    return model[:28]


# ── AUTO-UPDATE / DEV SYNC ────────────────────────
DEV_PATH_FILE = CONFIG_DIR / "dev_path"

def sync_dev_changes():
    """Sync changes between dev workspace and install dir."""
    try:
        current_file = Path(__file__).resolve()
        install_dir  = Path.home() / "AppData" / "Local" / "aistudio"
        install_file = install_dir / "aistudio.py"
        
        # Ensure install dir exists for this to work
        if not install_dir.exists(): return False

        is_installed = False
        try:
            if current_file.samefile(install_file):
                is_installed = True
        except Exception: pass

        if not is_installed:
            # We are in DEV: Push to install and save dev path
            pushed = False
            if not install_file.exists() or current_file.stat().st_mtime > install_file.stat().st_mtime:
                shutil.copy2(current_file, install_file)
                pushed = True
            
            # Also sync studio/ directory
            dev_studio = current_file.parent / "studio"
            inst_studio = install_dir / "studio"
            if dev_studio.exists():
                if not inst_studio.exists():
                    shutil.copytree(dev_studio, inst_studio)
                    pushed = True
                else:
                    # Simple check: if studio/data.py is newer, or if we want to be thorough, sync all
                    for f in dev_studio.glob("*.py"):
                        target = inst_studio / f.name
                        if not target.exists() or f.stat().st_mtime > target.stat().st_mtime:
                            shutil.copy2(f, target)
                            pushed = True
            
            if pushed:
                CONFIG_DIR.mkdir(exist_ok=True)
                DEV_PATH_FILE.write_text(str(current_file))
                return "pushed"
        else:
            # We are INSTALLED: Check if dev path exists and Pull
            if DEV_PATH_FILE.exists():
                dev_file = Path(DEV_PATH_FILE.read_text().strip())
                if dev_file.exists() and dev_file.stat().st_mtime > current_file.stat().st_mtime:
                    # Pull aistudio.py
                    shutil.copy2(dev_file, current_file)
                    # Also pull studio/ dir
                    dev_studio = dev_file.parent / "studio"
                    inst_studio = current_file.parent / "studio"
                    if dev_studio.exists() and inst_studio.exists():
                        for f in dev_studio.glob("*.py"):
                            target = inst_studio / f.name
                            shutil.copy2(f, target)
                    return "pulled"
    except Exception: pass
    return False

# ── RATE LIMITER & USAGE TRACKER ──────────────────
def check_rate_limit(state):
    usage = load_usage()
    tier  = get_plan(state).lower()
    # Ultra/Team = unlimited
    if tier in ("ultra", "team", "api"):
        return True, 0
    window = {"free": 3600, "pro": 18000, "max": 36000}.get(tier, 3600)
    limit  = {"free": 10,   "pro": 200,   "max": 500  }.get(tier, 10)

    now = time.time()
    valid_history = [e for e in usage.get("history", []) if now - e["ts"] < window]
    usage["history"] = valid_history
    save_usage(usage)

    if len(valid_history) >= limit:
        return False, len(valid_history)
    return True, len(valid_history)

def track_usage(state, tokens_in, tokens_out, is_heavy=False, prompt=""):
    usage = load_usage()
    # Log the full interaction
    usage.setdefault("interaction_log", []).append({
        "ts": time.time(),
        "prompt": prompt,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out
    })
    usage.setdefault("history", []).append({"ts": time.time(), "heavy": is_heavy})
    usage.setdefault("total_in", 0)
    usage.setdefault("total_out", 0)
    usage["total_in"] += tokens_in
    usage["total_out"] += tokens_out
    save_usage(usage)
    state["_usage"] = usage

    # Real cost tracking — free models contribute $0 but tokens are always counted
    prof = load_profile()
    if prof:
        active_model = state.get("model") or DEFAULT_MODEL
        pricing = model_price_per_1k(active_model)
        cost = ((tokens_in + tokens_out) / 1000) * pricing
        prof["balance"] = round(prof.get("balance", 0) - cost, 6)
        # Track per-model usage counts + token spend per model
        model_usage = prof.setdefault("model_usage", {})
        model_spend = prof.setdefault("model_spend", {})
        model_usage[active_model] = model_usage.get(active_model, 0) + 1
        model_spend[active_model] = round(model_spend.get(active_model, 0.0) + cost, 6)
        # Update session stats
        prof["total_msgs"]        = prof.get("total_msgs", 0) + 1
        prof["total_tokens_in"]   = prof.get("total_tokens_in", 0) + tokens_in
        prof["total_tokens_out"]  = prof.get("total_tokens_out", 0) + tokens_out
        prof["last_seen"]         = datetime.now().isoformat()
        save_profile(prof)
        state["balance"] = prof["balance"]


def _clean_terminal_text(text):
    """Remove Markdown formatting while preserving code blocks and content."""
    if not text: return ""
    lines_out = []
    in_code = False
    for line in text.split("\n"):
        # Preserve code blocks verbatim
        if line.strip().startswith("```"):
            in_code = not in_code
            lines_out.append(line)
            continue
        if in_code:
            lines_out.append(line)
            continue
        # Strip markdown headers: ## Heading → HEADING
        if re.match(r"^#{1,6}\s+", line):
            line = re.sub(r"^#{1,6}\s+", "", line).upper()
        # Strip bold/italic markers: **text** → text, *text* → text, _text_ → text
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
        line = re.sub(r"\*(.+?)\*",     r"\1", line)
        line = re.sub(r"__(.+?)__",     r"\1", line)
        line = re.sub(r"_(.+?)_",       r"\1", line)
        # Strip inline code ticks (keep content): `code` → code
        line = re.sub(r"`(.+?)`",       r"\1", line)
        # Escape brackets to prevent rich markup errors
        line = line.replace("[", r"\[").replace("]", r"\]")
        # Remove horizontal rules
        if re.match(r"^[\-=*]{3,}\s*$", line.strip()):
            continue
        # Remove pure table separator lines
        if re.match(r"^[\|\-\s\+]+$", line.strip()) and "|" in line:
            continue
        # Table cell spacing
        if "|" in line:
            line = "  " + "   ".join(c.strip() for c in line.strip("|").split("|") if c.strip())
        lines_out.append(line)
    # Collapse 3+ blank lines into 2
    result = re.sub(r"\n{3,}", "\n\n", "\n".join(lines_out))
    return result.strip()

# ── IMPROVED UI COMPONENTS ───────────────────────
def _assistant_heading(state, provider_label, is_heavy=False, toks=0):
    ui      = state.get("ui_style") or "gemini"
    theme   = state.get("theme") or THEMES.get("default") or {}
    accent  = theme.get("accent", "#22d3ee")
    border  = theme.get("border", accent).replace("bold ", "")
    short   = _short_model(state.get("model") or "")
    bolt    = "⚡ " if is_heavy else ""
    t_str   = f"{toks}t" if toks else ""
    mode    = state.get("_chat_mode", "")
    mode_tag = f" [{mode.upper()}]" if mode and mode != "normal" else ""

    active_agent = state.get("active_agent")
    if active_agent and active_agent in AGENT_ROSTER:
        info    = AGENT_ROSTER[active_agent]
        label   = f"{info['emoji']} {info['name']}"
        color   = info.get("color", accent)
    else:
        label   = "●"
        color   = accent

    meta = f"[dim]{bolt}{short}  {t_str}{mode_tag}[/dim]" if short else ""
    sep  = f"[dim {border}]{'─' * 48}[/dim {border}]"

    if ui == "studio":
        return f"\n{sep}\n[{color}]{label}[/{color}]  {meta}\n"
    if ui == "claude":
        return f"\n{sep}\n[bold white]▸[/bold white] [{color}]{label}[/{color}]  {meta}\n"
    if ui == "codex":
        return f"\n{sep}\n[{color}]>[/{color}] [{color}]{label}[/{color}]  {meta}\n"
    if ui == "ghost":
        dim_l = "◌" if not active_agent else label
        ghost_meta = f"[dim]│[/dim] [dim white]{bolt}{short}  {t_str}{mode_tag}[/dim white]" if short else ""
        return f"\n[dim]│[/dim] [dim white]{dim_l}[/dim white]  {ghost_meta}\n"
    if ui == "nova":
        return f"\n{sep}\n[bold magenta]⚡[/bold magenta] [{color}]{label}[/{color}]  {meta}\n"
    if ui == "foxxia":
        return f"\n{sep}\n[bold #f97316]🦊[/bold #f97316] [{color}]{label}[/{color}]  {meta}\n"
    if ui == "rain":
        rain_sep = f"[dim #00ff41]{'·' * 48}[/dim #00ff41]"
        return f"\n{rain_sep}\n[bold #00FF41]▓[/bold #00FF41] [#00FFFF]{label}[/#00FFFF]  {meta}\n"
    # gemini / all other styles
    return f"\n{sep}\n[{accent}]✦[/{accent}] [{color}]{label}[/{color}]  {meta}\n"

def _stream_print(text, mode):
    if not text:
        return
    if mode == "type":
        chunk = 24
        for i in range(0, len(text), chunk):
            console.print(text[i: i + chunk], end="")
            time.sleep(0.01)
    else:
        console.print(text, end="")


def clear_terminal():
    # OS-level clear first (moves cursor, resets visible area)
    if sys.platform == "win32":
        subprocess.run(["cmd", "/c", "cls"], shell=False)
    else:
        subprocess.run(["clear"], shell=False)
    # ANSI scrollback clear (works in Windows Terminal, iTerm2, modern terminals)
    # \x1b[3J = erase scrollback, \x1b[2J = erase screen, \x1b[H = cursor home
    sys.stdout.write("\x1b[3J\x1b[2J\x1b[H")
    sys.stdout.flush()


# ── UPDATED RESPOND WITH RATE LIMITS ─────────────
def cmd_sidebar(state):
    """Visual sidebar/panel showing the project state."""
    ctx = state.get("project_ctx")
    if not ctx:
        console.print("[yellow]No project loaded. Run /enter first.[/yellow]")
        return
    
    tree = ctx.get("tree", "")
    stats = ctx.get("stats", {})
    stack = ", ".join(ctx.get("tech_stack", []))
    
    side_panel = Panel(
        f"[bold cyan]Stack:[/bold cyan] {stack}\n"
        f"[bold cyan]Files:[/bold cyan] {stats.get('total_files')} ({stats.get('total_lines')} lines)\n\n"
        f"{tree[:1500]}{'...' if len(tree) > 1500 else ''}",
        title="[bold]Project Sidebar[/bold]",
        border_style="dim cyan"
    )
    console.print(side_panel)

# ── UPDATE TIERS ──────────────────────────────────
UPDATE_TIERS = ["api", "ultra", "max", "pro", "free"]

def check_update_eligibility(state):
    plan = get_plan(state).lower()
    try:
        idx = UPDATE_TIERS.index(plan)
        wait_days = idx * 2 # API gets it day 0, Free gets it day 8
        return wait_days == 0, wait_days
    except Exception: return False, 99

def ai_respond(state, prompt, history, silent=False):
    allowed, count = check_rate_limit(state)
    if not allowed:
        console.print(Panel("[bold red]Rate Limit Exceeded[/bold red]", border_style="red"))
        return None, history

    # Check for manual interrupt
    if state.get("_interrupt", False):
        state["_interrupt"] = False
        return "[INTERRUPTED]", history

    # ── Free-plan: lock to Nemotron
    if get_plan(state) == "free":
        locked = PLANS["free"]["models"][0]
        if state.get("model") != locked:
            console.print(f"  [dim]○ Free plan: switching to {locked.split('/')[1]}[/dim]")
            state["model"] = locked

    is_heavy = any(kw in prompt.lower() for kw in ["write code", "fix", "patch", "implement"])
    system_prompt = build_system_prompt(state)
    text = None; err = None
    stream_mode = (state.get("stream_mode") or "auto").lower()
    rendered = False
    t0 = time.time()
    fast_mode       = state.get("fast_mode", False)
    thinking_budget = state.get("thinking_budget", 0)
    state["_working"] = True

    # ── Route to correct provider ────────────────────────────────────────────
    or_key = state.get("openrouter_key") or load_or_key()
    gm_key = state.get("api_key") or load_api_key()
    model  = state.get("model") or DEFAULT_MODEL
    use_or = state.get("use_openrouter") or _is_openrouter_model(model)

    if use_or and or_key:
        if stream_mode in ("on", "auto", "type"):
            # ── Streaming path ────────────────────────────────────────────────
            full_text       = []
            reasoning_buf   = []
            header_printed  = False
            think_open      = False
            show_think      = state.get("show_thinking", True)
            _live_ctx       = None

            for chunk, chunk_err, reasoning in call_openrouter_stream(or_key, model, history, prompt, system_prompt,
                                                                        fast_mode=fast_mode, thinking_budget=thinking_budget):
                if chunk_err:
                    err = chunk_err
                    break
                # ── LIVE reasoning stream ──────────────────────────────────
                if reasoning:
                    reasoning_buf.append(reasoning)
                    if show_think:
                        if not think_open:
                            console.print("\n[dim]◈ Thinking…[/dim]")
                            think_open = True
                        sys.stdout.write(f"\x1b[2;3m{reasoning}\x1b[0m")
                        sys.stdout.flush()
                # ── Content chunks → start Rich Live Markdown renderer ─────
                if chunk:
                    if not header_printed:
                        if think_open:
                            console.print()
                            console.print("[dim]◇ Done thinking.[/dim]")
                            think_open = False
                        console.print(_assistant_heading(state, "OR", is_heavy))
                        header_printed = True
                        if stream_mode != "type":
                            try:
                                _live_ctx = Live("", refresh_per_second=10,
                                                 vertical_overflow="visible", console=console)
                                _live_ctx.start()
                            except Exception:
                                _live_ctx = None
                    full_text.append(chunk)
                    if stream_mode == "type":
                        _stream_print(chunk, "type")
                    elif _live_ctx is not None and len(full_text) % 4 == 0:
                        # Re-render every 4 chunks to keep performance smooth
                        assembled = "".join(full_text)
                        try:
                            _live_ctx.update(Markdown(assembled))
                        except Exception:
                            _live_ctx.update(assembled)
                    elif _live_ctx is None:
                        _stream_print(chunk, stream_mode)

            # Finalise Live context with complete text
            if _live_ctx is not None:
                assembled = "".join(full_text)
                try:
                    _live_ctx.update(Markdown(assembled))
                except Exception:
                    _live_ctx.update(assembled)
                _live_ctx.stop()

            # Edge case: reasoning-only response with no content chunks
            if not header_printed:
                if think_open:
                    console.print()
                    console.print("[dim]◇ Done thinking.[/dim]")
                    think_open = False
                elif reasoning_buf and show_think:
                    full_reasoning = "".join(reasoning_buf)
                    console.print(Panel(
                        f"[dim italic]{full_reasoning}[/dim italic]",
                        title="[dim]◈ Internal Reasoning[/dim]",
                        border_style="dim",
                        padding=(0, 1),
                    ))
                console.print(_assistant_heading(state, "OR", is_heavy))

            console.print()
            if full_text:
                text = "".join(full_text)
                rendered = True
        else:
            # ── Blocking path ─────────────────────────────────────────────────
            if not silent: _start_think_anim("Thinking")
            text, err = call_openrouter(or_key, model, history, prompt, system_prompt,
                                        fast_mode=fast_mode, thinking_budget=thinking_budget)
            if not silent: _stop_think_anim()

    elif state.get("cursor_key"):
        cx_key = state["cursor_key"]
        if not silent: _start_think_anim("Thinking (Cursor)")
        text, err = call_cursor(cx_key, model, history, prompt, system_prompt)
        if not silent: _stop_think_anim()

    elif gm_key:
        if not silent: _start_think_anim("Thinking")
        text, err = call_gemini(gm_key, model, history, prompt, system_prompt)
        if not silent: _stop_think_anim()

    elif state.get("use_cli"):
        if not silent: _start_think_anim("Thinking (CLI)")
        text, err = call_gemini_cli(prompt, system_prompt)
        if not silent: _stop_think_anim()

    elif model.startswith("ollama/"):
        ollama_model = model[len("ollama/"):]
        if stream_mode in ("on", "auto", "type"):
            full_text = []
            console.print(_assistant_heading(state, "OLLAMA", is_heavy))
            for chunk, chunk_err, _ in call_ollama(ollama_model, history, prompt, system_prompt, stream=True):
                if chunk_err:
                    err = chunk_err; break
                if chunk:
                    _stream_print(chunk, stream_mode)
                    full_text.append(chunk)
            console.print()
            if full_text:
                text = "".join(full_text)
                rendered = True
        else:
            if not silent: _start_think_anim(f"Ollama ({ollama_model})")
            text, err = call_ollama(ollama_model, history, prompt, system_prompt, stream=False)
            if not silent: _stop_think_anim()

    if text:
        # 3. Real-time Accounting
        in_t = approx_tokens(prompt); out_t = approx_tokens(text)
        track_usage(state, in_t, out_t, is_heavy=is_heavy)
        # Credit tracking
        if not silent:
            _cost_key = ("turbo_message" if state.get("turbo_mode")
                         else "fast_message" if state.get("fast_mode")
                         else "message")
            track_credits(state, _cost_key)

        # 4. Display response (blocking path only — streaming already rendered above)
        if not silent:
            if not rendered:
                console.print(_assistant_heading(state, "AI", is_heavy, out_t))
                try:
                    console.print(Markdown(text))
                    console.print("")
                except Exception:
                    from rich.padding import Padding
                    console.print(Padding(text, (0, 0, 1, 4)))
            else:
                console.print("")

            parse_and_execute_tools(state, text)

        history.append({"role":"user","text":prompt})
        history.append({"role":"model","text":text})
        state["_last_response"] = text
        state["_last_tokens"] = {"in": in_t, "out": out_t, "sec": round(time.time()-t0, 2)}
        state["_working"] = False
        return text, history

    # ── Auto-fallback: if OR key exists and primary model gave nothing, try next free model ──
    or_key = state.get("openrouter_key") or load_or_key()
    if or_key and not err and (state.get("use_openrouter") or _is_openrouter_model(state.get("model",""))):
        tried = state.get("_fallback_tried", set())
        primary = state.get("model") or DEFAULT_MODEL
        tried.add(primary)
        for fallback in FREE_CHAT_MODELS:
            if fallback in tried:
                continue
            tried.add(fallback)
            state["_fallback_tried"] = tried
            console.print(f"[dim yellow]⚡ {primary.split('/')[-1]} unavailable — retrying with {fallback.split('/')[-1]}…[/dim yellow]")
            old_model = state.get("model")
            state["model"] = fallback
            result, history = ai_respond(state, prompt, history, silent=silent)
            if result:
                return result, history
            state["model"] = old_model  # restore if fallback also failed
        state.pop("_fallback_tried", None)

    state["_working"] = False
    if not silent:
        if err:
            console.print(f"[red]✖ {err}[/red]")
        elif not state.get("openrouter_key") and not state.get("api_key") and not state.get("use_cli"):
            console.print(
                "[yellow]No API key configured.[/yellow]\n"
                "  Run [bold]/openrouter YOUR_KEY[/bold] to set your OpenRouter key.\n"
                "  Get a free key at [dim]https://openrouter.ai/keys[/dim]"
            )
        else:
            console.print("[dim](all models unavailable — check your connection or try /model <id>)[/dim]")
    return None, history

def parse_and_execute_tools(state, text):
    """Detects and executes [READ:path], [WRITE:path], or [PATCH:path] tags."""
    if not text: return

    write_p = re.compile(r"\[WRITE:(.+?)\](.*?)\[/WRITE\]", re.DOTALL)
    read_p  = re.compile(r"\[READ:(.+?)\]")
    patch_p = re.compile(r"\[PATCH:(.+?)\](.*?)\[/PATCH\]", re.DOTALL)

    # ── Handle [READ:path] tags ─────────────────────────────────────────────
    for m in read_p.finditer(text):
        path = m.group(1).strip()
        try:
            content, resolved = read_file_state(state, path)
            ext = Path(resolved).suffix.lstrip(".") or "text"
            console.print(Panel(
                Syntax(content[:4000], ext, theme="monokai", line_numbers=True),
                title=f"[bold cyan]📄 {resolved}[/bold cyan]",
                border_style="cyan"
            ))
        except Exception as e:
            console.print(f"[red]Tool READ failed for '{path}': {e}[/red]")

    # ── Handle [WRITE:path]content[/WRITE] tags ─────────────────────────────
    for m in write_p.finditer(text):
        path    = m.group(1).strip()
        content = m.group(2)
        # Strip leading/trailing newlines that are part of the tag formatting
        content = content.lstrip("\n").rstrip("\n")
        # Strip accidental markdown fences (model sometimes wraps content)
        content = re.sub(r"^```[^\n]*\n", "", content)
        content = re.sub(r"\n```$", "", content)
        if not check_write_allowed(state, path):
            continue
        try:
            write_file_state(state, path, content)
        except Exception as e:
            console.print(f"[red]Tool WRITE failed for '{path}': {e}[/red]")

    # ── Handle [PATCH:path]instruction[/PATCH] tags ──────────────────────────
    for m in patch_p.finditer(text):
        path        = m.group(1).strip()
        instruction = m.group(2).strip()
        if not check_write_allowed(state, path):
            continue
        try:
            original, resolved = read_file_state(state, path)
            ext    = Path(resolved).suffix.lstrip(".") or "text"
            prompt = (
                f"File: {resolved}\n\n```{ext}\n{original}\n```\n\n"
                f"Instruction: {instruction}\n\n"
                "Return ONLY the complete updated file content — no commentary, no markdown fences."
            )
            _start_think_anim(f"Patching {Path(path).name}")
            new_content, _ = ai_respond(state, prompt, [], silent=True)
            _stop_think_anim()
            if not new_content:
                console.print(f"[red]Tool PATCH failed for '{path}': no response from AI[/red]")
                continue
            # Strip accidental markdown fences
            new_content = re.sub(r"^```[^\n]*\n", "", new_content.strip())
            new_content = re.sub(r"\n```$", "", new_content)
            write_file_state(state, str(resolved), new_content)
            console.print(f"[green]✓ Patch applied → {resolved}[/green]")
        except Exception as e:
            console.print(f"[red]Tool PATCH error for '{path}': {e}[/red]")


# ── /diffpatch — show diff before applying a patch ────────────────────────
def cmd_diffpatch(state, args, history):
    """Show a unified diff of what an AI patch would change, then confirm."""
    if not args:
        console.print("[yellow]Usage: /diffpatch <file> [instruction][/yellow]")
        return history
    parts = args.split(" ", 1)
    path  = parts[0]
    instr = parts[1] if len(parts) > 1 else "Fix any issues in this file."
    try:
        content, p = read_file_state(state, path)
        ext = p.suffix.lstrip(".") or "text"
        prompt = (
            f"File: {p}\n\n```{ext}\n{content}\n```\n\n"
            f"Task: {instr}\n\n"
            "Return ONLY the complete modified file content — no commentary, no fences."
        )
        _start_think_anim("Generating patch")
        new_content, err = call_openrouter(
            state.get("openrouter_key") or load_or_key(),
            state.get("model") or DEFAULT_MODEL,
            history, prompt, build_system_prompt(state)
        )
        _stop_think_anim()
        if not new_content:
            console.print(f"[red]Failed: {err}[/red]"); return history

        # Strip accidental markdown fences
        new_content = re.sub(r"^```[^\n]*\n", "", new_content.strip())
        new_content = re.sub(r"\n```$", "", new_content)

        diff_lines = list(difflib.unified_diff(
            content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{p.name}", tofile=f"b/{p.name}", lineterm=""
        ))
        if not diff_lines:
            console.print("[dim]✓ No changes needed.[/dim]"); return history

        # Stats
        added   = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++"))
        removed = sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("---"))
        diff_text = "".join(diff_lines)

        console.print(Panel(
            Syntax(diff_text, "diff", theme="monokai"),
            title=(
                f"[bold]Proposed patch → {p.name}[/bold]  "
                f"[green]+{added}[/green] / [red]-{removed}[/red] lines"
            ),
            border_style="yellow",
            subtitle="[dim]y = apply  n = discard  e = edit instruction[/dim]"
        ))

        choice = console.input("  [bold]Apply patch?[/bold] [dim](y/n/e)[/dim]: ").strip().lower()
        if choice == "y":
            if check_write_allowed(state, str(p)):
                # Backup before write
                bak = p.with_suffix(p.suffix + f".bak.{int(time.time())}")
                bak.write_text(content, encoding="utf-8")
                p.write_text(new_content, encoding="utf-8")
                console.print(f"[green]✓ Patched: {p}[/green]  [dim](backup → {bak.name})[/dim]")
                history.append({"role":"user","text":f"/diffpatch {path}: {instr}"})
                history.append({"role":"model","text":new_content})
        elif choice == "e":
            new_instr = console.input("  New instruction: ").strip()
            if new_instr:
                return cmd_diffpatch(state, f"{path} {new_instr}", history)
        else:
            console.print("[dim]Discarded.[/dim]")
    except Exception as e:
        console.print(f"[red]{e}[/red]")
    return history


# ── /format — reformat a file (black/prettier/etc) then AI-polish ─────────
def cmd_format(state, args):
    """Auto-format a file with available formatters."""
    if not args:
        console.print("[yellow]Usage: /format <file>[/yellow]")
        return
    try:
        p = resolve_path(state, args, must_exist=True)
        ext = p.suffix.lower()
        fmt_map = {
            ".py":   ["black", str(p)],
            ".js":   ["npx", "prettier", "--write", str(p)],
            ".ts":   ["npx", "prettier", "--write", str(p)],
            ".jsx":  ["npx", "prettier", "--write", str(p)],
            ".tsx":  ["npx", "prettier", "--write", str(p)],
            ".json": ["npx", "prettier", "--write", str(p)],
            ".css":  ["npx", "prettier", "--write", str(p)],
            ".html": ["npx", "prettier", "--write", str(p)],
        }
        cmd_list = fmt_map.get(ext)
        if cmd_list and shutil.which(cmd_list[0]):
            result = subprocess.run(cmd_list, capture_output=True, text=True)
            if result.returncode == 0:
                console.print(f"[green]✓ Formatted {p.name} with {cmd_list[0]}[/green]")
            else:
                console.print(f"[yellow]Formatter warning: {result.stderr[:200]}[/yellow]")
        else:
            console.print(f"[dim]No formatter for {ext} (install black/prettier). Skipping.[/dim]")
    except Exception as e:
        console.print(f"[red]{e}[/red]")


# ── /name — rename the current session + terminal title ────────────────────
def _set_terminal_title(title: str):
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW(title)
    except Exception:
        pass
    # ANSI fallback (works in Windows Terminal / conhost with VT processing on)
    import sys
    sys.stdout.write(f"\033]0;{title}\007")
    sys.stdout.flush()


def _quick_ai(state, prompt: str, history=None) -> str | None:
    """Single non-streamed AI call for internal use (naming, handoffs, etc.)."""
    or_key = state.get("openrouter_key") or load_or_key()
    gm_key = state.get("api_key") or load_api_key()
    model  = state.get("model") or DEFAULT_MODEL
    use_or = state.get("use_openrouter") or _is_openrouter_model(model)
    h = history or []
    if use_or and or_key:
        text, err = call_openrouter(or_key, model, h, prompt)
    elif gm_key:
        text, err = call_gemini(gm_key, model, h, prompt)
    else:
        return None
    return text.strip() if text else None


def cmd_name(state, args, history=None):
    theme = state.get("theme", THEMES["default"])
    if not args:
        # Auto-generate a name from chat history
        h = history or []
        if not h:
            console.print("[dim]No chat history yet — try: /name <yourname>[/dim]")
            return state
        console.print("[dim]✦ Reading chat to generate a session name…[/dim]")
        snippet = "\n".join(
            f"{m['role'].upper()}: {m['text'][:300]}" for m in h[-20:]
        )
        prompt = (
            "Based on this conversation, generate a short session name (2–4 words, "
            "title-case, no punctuation) that captures what the user is working on. "
            "Reply with ONLY the name, nothing else.\n\n" + snippet
        )
        name = _quick_ai(state, prompt)
        if not name:
            console.print("[yellow]Could not generate a name — try: /name <yourname>[/yellow]")
            return state
        name = name.strip().strip('"').strip("'")[:40]
    else:
        name = args.strip()
    state["session_name"] = name
    _set_terminal_title(f"Studio CLI — {name}")
    console.print(f"[{theme['success']}]✓ Session → [bold]{name}[/bold][/{theme['success']}]")
    return state


# ── /handoff — AI-generated handoff prompt from current chat ────────────────
def cmd_handoff(state, args, history):
    theme = state.get("theme", THEMES["default"])
    h = history or []
    if not h:
        console.print("[yellow]No chat history to generate a handoff from.[/yellow]")
        return history
    console.print("[dim]✦ Generating handoff prompt…[/dim]")
    snippet = "\n".join(
        f"{m['role'].upper()}: {m['text'][:400]}" for m in h
    )
    model   = state.get("model") or DEFAULT_MODEL
    ws      = state.get("workspace_root") or str(Path.cwd().name)
    sname   = state.get("session_name") or "this session"
    prompt = (
        f"You are summarizing a coding session called '{sname}' using model '{model}' "
        f"in workspace '{ws}'.\n\n"
        "Write a concise handoff prompt that a developer can paste into a NEW AI session "
        "to continue exactly where this left off. Include:\n"
        "• What was being built / worked on\n"
        "• Key decisions or changes made\n"
        "• Current state (what works, what's broken or pending)\n"
        "• Clear next steps\n\n"
        "Use plain text with section headers. Be specific — include file names, function "
        "names, and error messages where relevant. Keep it under 400 words.\n\n"
        "CONVERSATION:\n" + snippet
    )
    text = _quick_ai(state, prompt)
    if not text:
        console.print("[red]Could not generate handoff — check your API key.[/red]")
        return history
    border = theme.get("border", "cyan")
    console.print(Panel(text, title="✦ Handoff Prompt", border_style=border, padding=(1, 2)))
    # Copy to clipboard if pyperclip available
    try:
        import pyperclip
        pyperclip.copy(text)
        console.print(f"[{theme['success']}]✓ Copied to clipboard.[/{theme['success']}]")
    except Exception:
        console.print("[dim]Tip: install pyperclip to auto-copy handoffs.[/dim]")
    return history


# ── /rename — AI-powered smart file/symbol rename ─────────────────────────
def cmd_rename(state, args, history):
    """Rename a file intelligently, updating imports if detected."""
    parts = args.split(" ", 1) if args else []
    if len(parts) < 2:
        console.print("[yellow]Usage: /rename <oldname> <newname>[/yellow]")
        return history
    src_p = resolve_path(state, parts[0], must_exist=True)
    dst_p = resolve_path(state, parts[1], for_write=True)
    try:
        src_p.rename(dst_p)
        console.print(f"[green]✓ Renamed: {src_p.name} → {dst_p.name}[/green]")
        history.append({"role":"user","text":f"I renamed {src_p} to {dst_p}"})
    except Exception as e:
        console.print(f"[red]{e}[/red]")
    return history


# ── /outline — get AI structural outline of a file ────────────────────────
def cmd_outline(state, args, history):
    """Show AI-generated outline/map of a file."""
    if not args:
        console.print("[yellow]Usage: /outline <file>[/yellow]")
        return history
    try:
        content, p = read_file_state(state, args)
        prompt = (
            f"Give a concise structural outline of `{p.name}`:\n"
            "List: classes, functions, key variables, imports, and their line numbers. "
            "Format: <line> <type> <name> — one per line. No explanations."
            f"\n\n```\n{content[:6000]}\n```"
        )
        _, history = ai_respond(state, prompt, history)
    except Exception as e:
        console.print(f"[red]{e}[/red]")
    return history


# ── /comment — add/improve inline comments in a file ─────────────────────
def cmd_comment(state, args, history):
    """Add or improve inline comments in a code file."""
    if not args:
        console.print("[yellow]Usage: /comment <file>[/yellow]")
        return history
    try:
        content, p = read_file_state(state, args)
        ext = p.suffix.lstrip(".") or "text"
        prompt = (
            f"Add clear, helpful inline comments to every non-trivial block in this {ext} file.\n"
            "Do NOT change any logic. Return the complete file with comments added.\n\n"
            f"```{ext}\n{content}\n```"
        )
        _start_think_anim("Commenting")
        or_key = state.get("openrouter_key") or load_or_key()
        commented, err = call_openrouter(or_key, state.get("model") or DEFAULT_MODEL,
                                         [], prompt, build_system_prompt(state))
        _stop_think_anim()
        if not commented:
            console.print(f"[red]{err}[/red]"); return history
        commented = re.sub(r"^```[\w]*\n?", "", commented.strip())
        commented = re.sub(r"\n?```$", "", commented.strip())
        if check_write_allowed(state, str(p)):
            p.write_text(commented, encoding="utf-8")
            console.print(f"[green]✓ Comments added to {p.name}[/green]")
    except Exception as e:
        console.print(f"[red]{e}[/red]")
    return history


# ── /summarize — summarize current history into one message ───────────────
def cmd_summarize_history(state, history):
    """Compress long chat history into a summary, preserving key facts."""
    if not history:
        console.print("[dim]Nothing to summarize.[/dim]"); return history
    flat = "\n".join(f"{m['role'].upper()}: {m['text'][:400]}" for m in history[-20:])
    prompt = (
        "Summarize the following conversation into a concise bullet-point recap. "
        "Preserve key decisions, code written, and open tasks.\n\n" + flat
    )
    _, history = ai_respond(state, prompt, history)
    return history


# ── /word-count — quick stats on a file ──────────────────────────────────
def cmd_wordcount(state, args):
    """Print line/word/char/token stats for a file."""
    if not args:
        console.print("[yellow]Usage: /wc <file>[/yellow]"); return
    try:
        content, p = read_file_state(state, args)
        lines  = len(content.splitlines())
        words  = len(content.split())
        chars  = len(content)
        toks   = approx_tokens(content)
        console.print(Panel(
            f"[bold]File:[/bold]   {p}\n"
            f"[bold]Lines:[/bold]  {lines:,}\n"
            f"[bold]Words:[/bold]  {words:,}\n"
            f"[bold]Chars:[/bold]  {chars:,}\n"
            f"[bold]~Tokens:[/bold] {toks:,}",
            title="[bold]Word Count[/bold]", border_style="cyan"))
    except Exception as e:
        console.print(f"[red]{e}[/red]")


# ── /duplicate — duplicate a file with new name ───────────────────────────
def cmd_duplicate(state, args):
    """Duplicate a file: /duplicate <src> <dst>"""
    parts = args.split(" ", 1) if args else []
    if len(parts) < 2:
        console.print("[yellow]Usage: /duplicate <src> <dst>[/yellow]"); return
    try:
        src_p = resolve_path(state, parts[0], must_exist=True)
        dst_p = resolve_path(state, parts[1], for_write=True)
        shutil.copy2(src_p, dst_p)
        console.print(f"[green]✓ Copied {src_p.name} → {dst_p}[/green]")
    except Exception as e:
        console.print(f"[red]{e}[/red]")


# ── /template — save/load prompt templates ────────────────────────────────
TEMPLATES_FILE = CONFIG_DIR / "templates.json"

def load_templates():
    try:
        return json.loads(TEMPLATES_FILE.read_text(encoding="utf-8")) if TEMPLATES_FILE.exists() else {}
    except Exception: return {}

def save_templates(t):
    CONFIG_DIR.mkdir(exist_ok=True)
    TEMPLATES_FILE.write_text(json.dumps(t, indent=2), encoding="utf-8")

def cmd_template(state, args, history):
    """Manage prompt templates: /template list|save <name>|use <name>|del <name>"""
    templates = load_templates()
    if not args or args == "list":
        if not templates:
            console.print("[dim]No templates. /template save <name>[/dim]"); return history
        tbl = Table(title="Prompt Templates", box=box.ROUNDED, border_style="cyan")
        tbl.add_column("Name", style="bold yellow")
        tbl.add_column("Preview", style="dim")
        for k, v in templates.items():
            tbl.add_row(k, v[:80] + ("..." if len(v)>80 else ""))
        console.print(tbl)
        return history
    parts = args.split(" ", 1)
    sub   = parts[0].lower()
    name  = parts[1].strip() if len(parts) > 1 else ""
    if sub == "save":
        last = state.get("_last_prompt","")
        if not last:
            console.print("[yellow]Nothing to save — send a message first[/yellow]"); return history
        templates[name] = last
        save_templates(templates)
        console.print(f"[green]✓ Template '{name}' saved[/green]")
    elif sub == "use":
        if name not in templates:
            console.print(f"[red]No template: {name}[/red]"); return history
        console.print(f"[dim]Using template: {name}[/dim]")
        _, history = ai_respond(state, templates[name], history)
    elif sub == "del":
        if name in templates:
            del templates[name]; save_templates(templates)
            console.print(f"[yellow]✓ Deleted template '{name}'[/yellow]")
        else:
            console.print(f"[red]No template: {name}[/red]")
    else:
        console.print("[yellow]Usage: /template list|save <name>|use <name>|del <name>[/yellow]")
    return history


# ── /pin — pin context file that auto-loads every message ─────────────────
def cmd_pin(state, args):
    """Pin a file so its content is included in every AI message."""
    if not args:
        pinned = state.get("pinned_file")
        if pinned:
            console.print(f"[dim]Pinned: {pinned}[/dim]  [yellow]/pin off[/yellow] to unpin")
        else:
            console.print("[dim]No file pinned. /pin <file>[/dim]")
        return state
    if args.strip().lower() == "off":
        state.pop("pinned_file", None)
        console.print("[yellow]✓ Unpinned[/yellow]")
        return state
    try:
        p = resolve_path(state, args, must_exist=True)
        state["pinned_file"] = str(p)
        console.print(f"[green]✓ Pinned: {p} (included in all messages)[/green]")
    except Exception as e:
        console.print(f"[red]{e}[/red]")
    return state


# ── /hotswap — switch model mid-conversation without losing context ────────
def cmd_hotswap(state, args):
    """Switch model and keep full history. /hotswap <model_alias_or_id>"""
    if not args:
        console.print("[dim]Current: {0}[/dim]\n[yellow]Usage: /hotswap <model>[/yellow]".format(state.get("model","")))
        return state
    alias   = args.strip()
    model   = STUDIO_MODEL_ALIASES.get(alias, alias)
    old     = state.get("model","")
    state["model"] = model
    save_last_model(model)
    theme = state.get("theme", THEMES["default"])
    console.print(f"[{theme['success']}]⚡ Hotswapped: {_short_model(old)} → {_short_model(model)}  (history preserved)[/{theme['success']}]")
    return state


# ── /rephrase — rephrase last response in a different style ───────────────
def cmd_rephrase(state, args, history):
    """Rephrase last AI response: /rephrase <style>  (e.g. ELI5, bullet, formal, sarcastic)"""
    style = args.strip() if args else "simpler"
    last  = state.get("_last_response","")
    if not last:
        console.print("[yellow]No response to rephrase.[/yellow]"); return history
    prompt = f"Rephrase the following text in a '{style}' style. Keep all facts, change only the style:\n\n{last}"
    _, history = ai_respond(state, prompt, history)
    return history


# ── /ask — one-shot question without adding to history ────────────────────
def cmd_ask(state, args):
    """Ask a one-shot question (not added to history). /ask <question>"""
    if not args:
        console.print("[yellow]Usage: /ask <question>[/yellow]"); return
    or_key = state.get("openrouter_key") or load_or_key()
    if not or_key:
        console.print("[yellow]No API key set[/yellow]"); return
    _start_think_anim("Thinking")
    text, err = call_openrouter(or_key, state.get("model") or DEFAULT_MODEL,
                                [], args, build_system_prompt(state))
    _stop_think_anim()
    if text:
        console.print(Panel(Markdown(text),
                            title="[dim]One-shot answer[/dim]", border_style="dim"))
    else:
        console.print(f"[red]{err}[/red]")


# ── /reload-key — hot-reload API keys from disk without restart ───────────
def cmd_reload_keys(state):
    """Reload API keys from disk (no restart needed)."""
    or_k = load_or_key()
    gm_k = load_api_key()
    hf_k = load_hf_key()
    if or_k: state["openrouter_key"] = or_k; state["use_openrouter"] = True
    if gm_k: state["api_key"] = gm_k
    if hf_k: state["hf_key"] = hf_k
    console.print(
        f"[green]✓ Keys reloaded:[/green]  "
        f"OR={'✓' if or_k else '✗'}  Gemini={'✓' if gm_k else '✗'}  HF={'✓' if hf_k else '✗'}"
    )
    return state


# ── /multi — send same prompt to multiple models simultaneously ───────────
def cmd_multi(state, args, history):
    """Send prompt to multiple models at once. /multi <model1,model2> <prompt>"""
    if not args:
        console.print("[yellow]Usage: /multi <alias1,alias2,...> <prompt>[/yellow]"); return history
    parts = args.split(" ", 1)
    if len(parts) < 2:
        console.print("[yellow]Need both models and a prompt[/yellow]"); return history
    model_list = [STUDIO_MODEL_ALIASES.get(m.strip(), m.strip()) for m in parts[0].split(",")]
    prompt     = parts[1]
    or_key     = state.get("openrouter_key") or load_or_key()
    if not or_key:
        console.print("[yellow]OpenRouter key required for /multi[/yellow]"); return history

    results = {}
    lock    = threading.Lock()

    def _query(mid):
        t0  = time.time()
        txt, _ = call_openrouter(or_key, mid, [], prompt, build_system_prompt(state))
        with lock:
            results[mid] = (txt or "[no response]", round(time.time()-t0,2))

    threads = [threading.Thread(target=_query, args=(m,), daemon=True) for m in model_list]
    with console.status("[bold cyan]Multi-model query...[/bold cyan]", spinner="dots"):
        for t in threads: t.start()
        for t in threads: t.join()

    tbl = Table(title="Multi-Model Results", box=box.ROUNDED, border_style="cyan", show_lines=True)
    tbl.add_column("Model", style="bold yellow", no_wrap=True, width=24)
    tbl.add_column("Response", width=70)
    tbl.add_column("Time", style="dim", no_wrap=True)
    for mid, (txt, dt) in results.items():
        short  = _short_model(mid)
        preview = txt[:400] + ("..." if len(txt) > 400 else "")
        tbl.add_row(short, preview, f"{dt}s")
    console.print(tbl)
    return history


# ── /zip — zip a directory for quick backup/share ─────────────────────────
def cmd_zip(state, args):
    """Zip a directory: /zip <dir> [output.zip]"""
    parts = args.split(" ", 1) if args else []
    if not parts:
        console.print("[yellow]Usage: /zip <dir> [output.zip][/yellow]"); return
    src   = resolve_path(state, parts[0], must_exist=True)
    dst   = parts[1].strip() if len(parts) > 1 else str(src) + ".zip"
    try:
        shutil.make_archive(dst.removesuffix(".zip"), "zip", str(src))
        console.print(f"[green]✓ Zipped: {src} → {dst}[/green]")
    except Exception as e:
        console.print(f"[red]{e}[/red]")


# ── /env — print relevant environment variables for debugging ─────────────
def cmd_env(state):
    """Show relevant environment variables."""
    keys = ["PATH","OPENROUTER_API_KEY","GEMINI_API_KEY","GOOGLE_API_KEY",
            "HF_TOKEN","HUGGINGFACE_TOKEN","HOME","USERPROFILE","APPDATA"]
    tbl = Table(title="Environment", box=box.SIMPLE, border_style="dim")
    tbl.add_column("Variable", style="yellow", no_wrap=True)
    tbl.add_column("Value", style="dim")
    for k in keys:
        v = os.environ.get(k, "")
        masked = (v[:4] + "…" + v[-4:]) if len(v) > 12 and "KEY" in k else v[:80]
        tbl.add_row(k, masked or "[dim](not set)[/dim]")
    console.print(tbl)


# ── /count — count occurrences of a term in a file ────────────────────────
def cmd_count(state, args):
    """Count occurrences: /count <pattern> <file>"""
    parts = args.split(" ", 1) if args else []
    if len(parts) < 2:
        console.print("[yellow]Usage: /count <pattern> <file>[/yellow]"); return
    pattern, filepath = parts[0], parts[1]
    try:
        content, p = read_file_state(state, filepath)
        matches = re.findall(re.escape(pattern), content)
        console.print(f"[cyan]Found [bold]{len(matches)}[/bold] occurrences of '[yellow]{pattern}[/yellow]' in {p.name}[/cyan]")
    except Exception as e:
        console.print(f"[red]{e}[/red]")


# ── /timeit — time how long an AI response takes ─────────────────────────
def cmd_timeit(state, args, history):
    """Time an AI response. /timeit <question>"""
    if not args:
        console.print("[yellow]Usage: /timeit <question>[/yellow]"); return history
    t0 = time.time()
    _, history = ai_respond(state, args, history)
    elapsed = time.time() - t0
    console.print(f"\n[dim]⏱ Total round-trip: [bold]{elapsed:.2f}s[/bold][/dim]")
    return history


# ── /free-tips — show free-tier tips to get more out of Studio ───────────
def cmd_free_tips(state):
    """Show tips and tricks for Free plan users."""
    theme = state.get("theme", THEMES["default"])
    tips = (
        "[bold cyan]Getting the most from Studio Free[/bold cyan]\n\n"
        "[yellow]◆[/yellow] Use [bold]/trial pro[/bold] for 5 free hours of Pro (no card)\n"
        "[yellow]◆[/yellow] Use [bold]/mode fif[/bold] then paste code — FIF is efficient with tokens\n"
        "[yellow]◆[/yellow] [bold]/cap 512 256[/bold] — limit tokens per turn to stay under caps\n"
        "[yellow]◆[/yellow] [bold]/stream off[/bold] — blocking mode uses fewer total tokens\n"
        "[yellow]◆[/yellow] [bold]/ask <question>[/bold] — one-shot, doesn't consume session history\n"
        "[yellow]◆[/yellow] [bold]/remember <fact>[/bold] — store key info so you don't repeat context\n"
        "[yellow]◆[/yellow] [bold]/snippet save <name>[/bold] — save useful AI outputs for reuse\n"
        "[yellow]◆[/yellow] [bold]/clear[/bold] resets your message counter (Free: 10 msgs/session)\n"
        "[yellow]◆[/yellow] Get a free OpenRouter key at [link=https://openrouter.ai/keys]openrouter.ai/keys[/link]"
    )
    console.print(Panel(tips, title="[bold]Free Plan Tips[/bold]", border_style=theme["border"], padding=(1,2)))

# ── FILE OPS ──────────────────────────────────────
def read_file(path):
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Not found: {path}")
    return p.read_text(encoding="utf-8", errors="replace")

def write_file(path, content):
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    console.print(f"[green]✓ Saved → {path}[/green]")

def open_editor(content="", suffix=".txt"):
    editor = os.environ.get("EDITOR") or ("notepad" if sys.platform=="win32" else "nano")
    with tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False, encoding="utf-8") as f:
        f.write(content); tmp = f.name
    subprocess.call([editor, tmp])
    result = Path(tmp).read_text(encoding="utf-8")
    Path(tmp).unlink(missing_ok=True)
    return result

def strip_fences(text):
    lines = text.strip().split("\n")
    # Find first fence line (handles AI preamble before the fence)
    start = 0
    for i, line in enumerate(lines):
        if line.startswith("```"):
            start = i + 1
            break
    else:
        return "\n".join(lines)  # no fence found — return as-is
    # Find last fence line from the bottom
    end = len(lines)
    for i in range(len(lines) - 1, start - 1, -1):
        if lines[i].startswith("```"):
            end = i
            break
    return "\n".join(lines[start:end])


def read_file_state(state, path):
    p = resolve_path(state, path, must_exist=True)
    ext = p.suffix.lower()
    if ext == ".docx":
        try:
            import docx as _docx
            doc = _docx.Document(str(p))
            text = "\n".join(para.text for para in doc.paragraphs)
            return text, p
        except ImportError:
            raise RuntimeError("python-docx not installed. Run: pip install python-docx")
    if ext == ".xlsx":
        try:
            import openpyxl as _xl
            wb = _xl.load_workbook(str(p), data_only=True)
            parts = []
            for sheet in wb.sheetnames:
                ws = wb[sheet]
                parts.append(f"=== Sheet: {sheet} ===")
                for row in ws.iter_rows(values_only=True):
                    row_str = "\t".join("" if v is None else str(v) for v in row)
                    if row_str.strip():
                        parts.append(row_str)
            return "\n".join(parts), p
        except ImportError:
            raise RuntimeError("openpyxl not installed. Run: pip install openpyxl")
    return p.read_text(encoding="utf-8", errors="replace"), p


def read_image_beta(state, path):
    """Return base64-encoded image data + mime type for vision models."""
    import base64, mimetypes
    p = resolve_path(state, path, must_exist=True)
    mime, _ = mimetypes.guess_type(str(p))
    if not mime or not mime.startswith("image/"):
        raise ValueError(f"Not a recognised image: {p}")
    data = base64.b64encode(p.read_bytes()).decode("utf-8")
    return data, mime, p


def write_file_state(state, path, content):
    p = resolve_path(state, path, must_exist=False, for_write=True)
    p.write_text(content, encoding="utf-8")
    console.print(f"[green]✓ Saved → {p}[/green]")
    return p

# ── FILESYSTEM COMMANDS ───────────────────────────
def cmd_ls(state, path="."):
    try:
        p = resolve_path(state, path or ".", must_exist=True)
        items = sorted(p.iterdir(), key=lambda x:(x.is_file(), x.name.lower()))
        console.print(f"\n[bold cyan]{p}[/bold cyan]")
        dirs  = [i for i in items if i.is_dir()]
        files = [i for i in items if i.is_file()]
        for i in dirs:
            console.print(f"  [bold blue]📁 {i.name}/[/bold blue]")
        for i in files:
            sz = i.stat().st_size
            s  = f"{sz}B" if sz<1024 else f"{sz//1024}KB" if sz<1048576 else f"{sz//1048576}MB"
            console.print(f"  [dim]📄[/dim] {i.name} [dim]{s}[/dim]")
        console.print(f"\n[dim]{len(dirs)} dirs, {len(files)} files[/dim]")
    except Exception as e: console.print(f"[red]{e}[/red]")

def cmd_cd(state, path):
    try:
        p = resolve_path(state, path, must_exist=True)
        if not p.is_dir():
            console.print(f"[red]Not a directory: {path}[/red]")
            return
        os.chdir(p); console.print(f"[green]✓ {os.getcwd()}[/green]")
    except Exception as e: console.print(f"[red]{e}[/red]")

def cmd_tree(state, path=".", max_depth=3):
    try:
        p    = resolve_path(state, path or ".", must_exist=True)
        tree = Tree(f"[bold cyan]{p}[/bold cyan]")
        def add_nodes(node, current, depth):
            if depth > max_depth: return
            try:
                items = sorted(current.iterdir(), key=lambda x:(x.is_file(), x.name.lower()))
                for item in items:
                    if item.name.startswith(".") or item.name in SKIP_DIRS: continue
                    if item.is_dir():
                        branch = node.add(f"[bold blue]📁 {item.name}/[/bold blue]")
                        add_nodes(branch, item, depth+1)
                    else:
                        sz = item.stat().st_size
                        s  = f"{sz}B" if sz<1024 else f"{sz//1024}KB"
                        node.add(f"[dim]📄[/dim] {item.name} [dim]{s}[/dim]")
            except PermissionError: pass
        add_nodes(tree, p, 1)
        console.print(tree)
    except Exception as e: console.print(f"[red]{e}[/red]")

def cmd_summary(state, path="."):
    try:
        p = resolve_path(state, path or ".", must_exist=True)
        ext_count = {}; total_lines = 0; total_files = 0; total_size = 0
        for f in p.rglob("*"):
            if f.is_file() and not any(x in str(f) for x in SKIP_DIRS):
                total_files += 1
                total_size  += f.stat().st_size
                ext = f.suffix.lower() or ".other"
                ext_count[ext] = ext_count.get(ext, 0) + 1
                try:
                    total_lines += len(f.read_text(encoding="utf-8",errors="replace").splitlines())
                except Exception: pass
        table = Table(title=f"Project Summary: {p}", box=box.ROUNDED, border_style="cyan")
        table.add_column("Extension", style="cyan"); table.add_column("Files", style="yellow"); table.add_column("Count")
        for ext, count in sorted(ext_count.items(), key=lambda x:-x[1])[:15]:
            bar = "█" * min(count, 20)
            table.add_row(ext, bar, str(count))
        console.print(table)
        sz = f"{total_size//1024}KB" if total_size<1048576 else f"{total_size//1048576}MB"
        console.print(f"[bold]Total:[/bold] {total_files} files · {total_lines:,} lines · {sz}")
    except Exception as e: console.print(f"[red]{e}[/red]")

def cmd_cat(state, path):
    try:
        content, p = read_file_state(state, path)
        ext = p.suffix.lstrip(".") or "text"
        console.print(Panel(Syntax(content, ext, theme="monokai", line_numbers=True),
            title=f"[bold]📄 {p}[/bold]", border_style="cyan"))
    except Exception as e: console.print(f"[red]{e}[/red]")

def cmd_find(state, pattern, path="."):
    try:
        p = resolve_path(state, path or ".", must_exist=True)
        results = []
        for root, dirs, files in os.walk(p):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in files:
                if fnmatch.fnmatch(f.lower(), pattern.lower()):
                    results.append(os.path.join(root, f))
        if results:
            console.print(f"[bold]Found {len(results)} file(s):[/bold]")
            for r in results: console.print(f"  [cyan]{r}[/cyan]")
        else:
            console.print(f"[yellow]No files matching '{pattern}'[/yellow]")
    except Exception as e: console.print(f"[red]{e}[/red]")

def cmd_grep(state, pattern, path="."):
    try:
        p = resolve_path(state, path or ".", must_exist=True)
        matches = []
        for f in p.rglob("*"):
            if f.is_file() and f.suffix in CODE_EXTS:
                if any(x in str(f) for x in SKIP_DIRS): continue
                try:
                    for i, line in enumerate(f.read_text(encoding="utf-8",errors="replace").splitlines(), 1):
                        if pattern.lower() in line.lower():
                            matches.append((str(f), i, line.strip()))
                except Exception: pass
        if matches:
            console.print(f"[bold]Found {len(matches)} match(es) for '{pattern}':[/bold]")
            for fp, ln, line in matches[:50]:
                console.print(f"  [cyan]{fp}[/cyan]:[yellow]{ln}[/yellow]  {line[:100]}")
            if len(matches)>50: console.print(f"  [dim]+{len(matches)-50} more[/dim]")
        else:
            console.print(f"[yellow]No matches for '{pattern}'[/yellow]")
    except Exception as e:
        # Avoid Rich markup parsing errors if the exception message contains brackets/tags.
        console.print(str(e), style="red", markup=False)

def cmd_mkdir(state, path):
    try: 
        p = resolve_path(state, path, for_write=True)
        p.mkdir(parents=True, exist_ok=True); console.print(f"[green]✓ Created {p}[/green]")
    except Exception as e: console.print(f"[red]{e}[/red]")

def cmd_rm(state, path):
    try:
        p = resolve_path(state, path, must_exist=True)
        kind = "directory and all contents" if p.is_dir() else "file"
        if console.input(f"[bold red]Delete {kind} '{p}'? (yes/no): [/bold red]").strip().lower() == "yes":
            if p.is_dir(): shutil.rmtree(p)
            else:          p.unlink()
            console.print(f"[green]✓ Deleted[/green]")
        else: console.print("[yellow]Cancelled[/yellow]")
    except Exception as e: console.print(f"[red]{e}[/red]")

def cmd_cp(state, src, dst):
    try: 
        s = resolve_path(state, src, must_exist=True)
        d = resolve_path(state, dst, for_write=True)
        shutil.copy2(s, d); console.print(f"[green]✓ {s} → {d}[/green]")
    except Exception as e: console.print(f"[red]{e}[/red]")

def cmd_mv(state, src, dst):
    try: 
        s = resolve_path(state, src, must_exist=True)
        d = resolve_path(state, dst, for_write=True)
        shutil.move(s, d); console.print(f"[green]✓ {s} → {d}[/green]")
    except Exception as e: console.print(f"[red]{e}[/red]")

def cmd_diff(state, f1, f2):
    try:
        p1 = resolve_path(state, f1, must_exist=True)
        p2 = resolve_path(state, f2, must_exist=True)
        a    = p1.read_text(encoding="utf-8").splitlines(keepends=True)
        b    = p2.read_text(encoding="utf-8").splitlines(keepends=True)
        diff = list(difflib.unified_diff(a, b, fromfile=str(p1), tofile=str(p2)))
        if diff: console.print(Syntax("".join(diff), "diff", theme="monokai"))
        else:    console.print("[green]Files are identical[/green]")
    except Exception as e: console.print(f"[red]{e}[/red]")

# ── SHELL / RUN ───────────────────────────────────
def cmd_shell(state, cmd, history):
    console.print(f"[dim]$ {cmd}[/dim]")
    try:
        cmd_list = shlex.split(cmd)
    except ValueError:
        cmd_list = cmd.split()
    result = subprocess.run(cmd_list, capture_output=True, text=True, encoding="utf-8", errors="replace")
    output = result.stdout + result.stderr
    console.print(output or "[dim](no output)[/dim]")
    if output and result.returncode != 0:
        if console.input("[bold]Ask AI to explain? (y/n): [/bold]").strip().lower() == "y":
            _, history = ai_respond(state, f"Command: `{cmd}`\n\nError:\n{output}\n\nExplain and fix.", history)
    return history

def cmd_run(state, path, history):
    try:
        p = resolve_path(state, path, must_exist=True)
    except Exception as e:
        console.print(f"[red]{e}[/red]")
        return history
    ext     = p.suffix.lower()
    runners = {".py":["python"], ".js":["node"], ".ts":["npx","ts-node"], ".sh":["bash"], ".bat":[str(p)]}
    runner  = runners.get(ext)
    if not runner: console.print(f"[yellow]Don't know how to run {ext} files[/yellow]"); return history
    console.print(f"[dim]Running {p}...[/dim]")
    result = subprocess.run(runner + [str(p)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    output = result.stdout + result.stderr
    console.print(output or "[dim](no output)[/dim]")
    if output and result.returncode != 0:
        if console.input("[bold]Ask AI to fix the error? (y/n): [/bold]").strip().lower() == "y":
            code   = p.read_text(encoding="utf-8", errors="replace")
            prompt = f"Running `{p}` gave this error:\n\n{output}\n\nHere's the code:\n\n```\n{code}\n```\n\nFix it."
            _, history = ai_respond(state, prompt, history)
    return history

# ── GIT ───────────────────────────────────────────
def cmd_git(state, args, history):
    if not args:
        console.print(Panel(
            "  [yellow]/git status[/yellow]         — show status\n"
            "  [yellow]/git diff[/yellow]           — show unstaged changes\n"
            "  [yellow]/git log[/yellow]            — recent commits\n"
            "  [yellow]/git commit[/yellow]         — AI writes commit message\n"
            "  [yellow]/git explain[/yellow]        — explain recent changes\n"
            "  [yellow]/git <any cmd>[/yellow]      — run any git command",
            title="Git Commands", border_style="cyan"))
        return history

    if args == "commit":
        diff = subprocess.run("git diff --cached", shell=True, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
        if not diff:
            diff = subprocess.run("git diff", shell=True, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
        if not diff: console.print("[yellow]No changes to commit[/yellow]"); return history
        prompt   = f"Write a concise git commit message for these changes:\n\n{diff[:3000]}\n\nFormat: type(scope): description\nJust the message, nothing else."
        response, history = ai_respond(state, prompt, history)
        if response:
            msg = response.strip().split("\n")[0]
            if console.input(f"\n[bold]Commit with: '[cyan]{msg}[/cyan]'? (y/n): [/bold]").strip().lower() == "y":
                r = subprocess.run(["git", "commit", "-am", msg], capture_output=True, text=True, encoding="utf-8", errors="replace")
                console.print(r.stdout or r.stderr)
        return history

    if args == "explain":
        log  = subprocess.run("git log --oneline -10", shell=True, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
        diff = subprocess.run("git diff HEAD~1", shell=True, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout[:3000]
        prompt = f"Explain these recent git changes:\n\nLog:\n{log}\n\nDiff:\n{diff}"
        _, history = ai_respond(state, prompt, history)
        return history

    console.print(f"[dim]$ git {args}[/dim]")
    r      = subprocess.run(["git"] + shlex.split(args), capture_output=True, text=True, encoding="utf-8", errors="replace")
    output = r.stdout + r.stderr
    console.print(output or "[dim](no output)[/dim]")
    if r.returncode != 0 and output:
        if console.input("[bold]Ask AI to explain? (y/n): [/bold]").strip().lower() == "y":
            _, history = ai_respond(state, f"Git error:\n{output}\n\nExplain and fix.", history)
    return history

# ── WATCH ─────────────────────────────────────────
_watch_thread = None
_watch_stop   = threading.Event()

def cmd_watch(state, path, history):
    global _watch_thread  # _watch_stop is only read here, not reassigned
    if path == "off":
        _watch_stop.set()
        console.print("[yellow]✓ Watch stopped[/yellow]")
        return history
    p = Path(path)
    if not p.exists(): console.print(f"[red]Not found: {path}[/red]"); return history

    _watch_stop.clear()
    last_mtime = p.stat().st_mtime
    console.print(f"[green]✓ Watching {path}... (run /watch off to stop)[/green]")

    def watcher():
        nonlocal last_mtime
        while not _watch_stop.is_set():
            try:
                mtime = p.stat().st_mtime
                if mtime != last_mtime:
                    last_mtime = mtime
                    content    = p.read_text(encoding="utf-8", errors="replace")
                    console.print(f"\n[bold yellow]📡 {path} changed — analyzing...[/bold yellow]")
                    prompt = f"`{path}` was just modified. Here's the new content:\n\n```\n{content[:3000]}\n```\n\nNote any issues or changes."
                    ai_respond(state, prompt, history)
                    theme2 = state.get("theme", THEMES["default"])
                    ui2    = state.get("ui_style") or load_ui_style()
                    console.print(_prompt_html(theme2, ui2), end="")
            except Exception: pass
            time.sleep(2)

    _watch_thread = threading.Thread(target=watcher, daemon=True)
    _watch_thread.start()
    return history

# ── UNDO (restore .bak) ───────────────────────────
def cmd_undo(state, args):
    """Restore the most recent .bak file created by /fix or /patch."""
    theme = state.get("theme", THEMES["default"])
    if args:
        bak = resolve_path(state, args + ".bak", must_exist=False)
        target = resolve_path(state, args, must_exist=False)
        candidates = [bak] if bak.exists() else []
    else:
        cwd = Path.cwd()
        candidates = sorted(cwd.glob("*.bak"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not candidates:
        console.print("[yellow]No .bak files found. Run /fix or /patch first.[/yellow]")
        return
    bak = candidates[0]
    target = bak.with_suffix("")
    console.print(Panel(
        f"[bold]Restore:[/bold] [cyan]{bak}[/cyan] → [cyan]{target}[/cyan]",
        border_style=theme["border"]))
    if console.input("[bold]Undo this change? (y/n): [/bold]").strip().lower() == "y":
        shutil.copy2(str(bak), str(target))
        console.print(f"[{theme['success']}]✓ Restored {target}[/{theme['success']}]")


def cmd_reload(state):
    """Reset workspace root to current working directory."""
    cwd = Path.cwd().resolve()
    state["workspace_root"] = cwd
    save_workspace_root(cwd)
    theme = state.get("theme", THEMES["default"])
    console.print(f"[{theme['success']}]✓ Workspace → {cwd}[/{theme['success']}]")
    return state


# ── AI FILE COMMANDS ──────────────────────────────
def cmd_fix(state, path, history):
    try:
        content, p = read_file_state(state, path)
        ext = p.suffix.lstrip(".") or "text"
        console.print(Panel(Syntax(content[:2000], ext, theme="monokai", line_numbers=True),
            title=f"[bold]📄 {p}[/bold]", border_style="cyan"))
        task = console.input("[bold]What to fix/improve? [/bold]").strip()
        if not task: return history
        prompt = (f"File `{p}`:\n\n```{ext}\n{content}\n```\n\n"
                  f"Task: {task}\n\nOutput ONLY the complete fixed file. No markdown fences.")
        response, history = ai_respond(state, prompt, history)
        if response:
            clean = strip_fences(response)
            console.print(f"\n[bold]Preview (first 15 lines):[/bold]")
            console.print(Syntax("\n".join(clean.split("\n")[:15]), ext, theme="monokai"))
            if console.input(f"\n[bold]Write to [cyan]{p}[/cyan]? (y/n): [/bold]").strip().lower() == "y":
                backup = Path(str(p) + ".bak")
                backup.write_text(content, encoding="utf-8")
                write_file_state(state, str(p), clean)
                console.print(f"[dim]Backup → {backup}[/dim]")
    except Exception as e: console.print(f"[red]{e}[/red]")
    return history


def cmd_patch(state, args, history):
    """Surgical AI patch: read file, show diff, apply only what changed."""
    parts = args.split(" ", 1) if args else []
    if not parts:
        console.print("[yellow]Usage: /patch <file> [instruction][/yellow]")
        return history
    path        = parts[0].strip()
    instruction = parts[1].strip() if len(parts) > 1 else ""
    try:
        content, p = read_file_state(state, path)
        ext   = p.suffix.lstrip(".") or "text"
        lines = content.splitlines()
        console.print(Panel(
            Syntax(content[:3000] + ("…" if len(content) > 3000 else ""), ext, theme="monokai", line_numbers=True),
            title=f"[bold]📄 {p}[/bold] ({len(lines)} lines)", border_style="cyan"))

        if not instruction:
            instruction = console.input("[bold]What to patch/change? [/bold]").strip()
        if not instruction:
            return history

        prompt = (
            f"You are a surgical code editor. Task: {instruction}\n\n"
            f"File: `{p}`\n"
            f"Content:\n```{ext}\n{content}\n```\n\n"
            f"Output ONLY the complete updated file content. Do not use markdown fences. Do not explain. "
            f"Preserve all unchanged lines exactly. If the file is large, focus ONLY on the requested change."
        )
        response, history = ai_respond(state, prompt, history)
        if response:
            clean      = strip_fences(response)
            orig_lines = content.splitlines(keepends=True)
            new_lines  = clean.splitlines(keepends=True)
            diff       = list(difflib.unified_diff(
                orig_lines, new_lines,
                fromfile=f"{p} (original)", tofile=f"{p} (patched)", lineterm=""
            ))
            if diff:
                console.print("\n[bold]Diff:[/bold]")
                console.print(Syntax("".join(diff[:80]), "diff", theme="monokai"))
                if len(diff) > 80:
                    console.print(f"[dim]…+{len(diff)-80} more diff lines[/dim]")
            else:
                console.print("[yellow]No changes detected in AI output[/yellow]")
                return history

            if console.input(f"\n[bold]Apply patch to [cyan]{p}[/cyan]? (y/n): [/bold]").strip().lower() == "y":
                backup = Path(str(p) + ".bak")
                backup.write_text(content, encoding="utf-8")
                write_file_state(state, str(p), clean)
                console.print(f"[dim]Backup → {backup}[/dim]")
    except Exception as e:
        console.print(f"[red]{e}[/red]")
    return history


def cmd_analyze(state, path, history):
    try:
        p = resolve_path(state, path, must_exist=True)
    except Exception as e:
        console.print(f"[red]{e}[/red]")
        return history
    if not p.is_dir():
        console.print(f"[red]Not a directory: {p}[/red]")
        return history
    files = []
    for ext in ["*.py","*.js","*.ts","*.html","*.css","*.jsx","*.tsx","*.json","*.vue"]:
        files.extend(p.rglob(ext))
    files = [f for f in files if not any(x in str(f) for x in ["node_modules",".git","__pycache__","dist"])][:12]
    if not files: console.print("[yellow]No code files found[/yellow]"); return history
    console.print(f"[bold]Scanning {len(files)} files...[/bold]")
    combined = ""
    for f in files:
        try:
            content   = f.read_text(encoding="utf-8",errors="replace")[:2000]
            combined += f"\n\n=== {f.relative_to(p)} ===\n{content}"
        except Exception: pass
    prompt = (f"Analyze this project at `{path}`. Find ALL bugs, security issues, "
              f"performance problems, and improvements. Be specific.\n\n{combined}")
    _, history = ai_respond(state, prompt, history)
    return history

def cmd_explain(state, path, line_num, history):
    try:
        content, p = read_file_state(state, path)
        lines  = content.splitlines()
        ln     = int(line_num) - 1
        start  = max(0, ln-5); end = min(len(lines), ln+6)
        snippet = "\n".join(f"{i+1}: {l}" for i, l in enumerate(lines[start:end], start))
        ext    = p.suffix.lstrip(".") or "text"
        prompt = f"Explain line {line_num} in `{p}`:\n\n```{ext}\n{snippet}\n```\n\nFocus on line {line_num}."
        _, history = ai_respond(state, prompt, history)
    except Exception as e: console.print(f"[red]{e}[/red]")
    return history

# ── CONVERSATION SAVE/LOAD ────────────────────────
def cmd_save(name, history):
    CONVOS_DIR.mkdir(parents=True, exist_ok=True)
    path = CONVOS_DIR / f"{name}.json"
    path.write_text(json.dumps(history, indent=2), encoding="utf-8")
    console.print(f"[green]✓ Saved conversation '{name}'[/green]")

def cmd_load(name):
    path = CONVOS_DIR / f"{name}.json"
    if not path.exists():
        saves = list(CONVOS_DIR.glob("*.json")) if CONVOS_DIR.exists() else []
        if saves: console.print("[yellow]Available:[/yellow] " + ", ".join(s.stem for s in saves))
        else:     console.print("[yellow]No saved conversations[/yellow]")
        return []
    history = json.loads(path.read_text())
    console.print(f"[green]✓ Loaded '{name}' ({len(history)//2} exchanges)[/green]")
    return history

def cmd_show_history(history):
    if not history:
        console.print("[dim]No conversation history[/dim]")
        return
    console.print(f"\n[bold]Conversation ({len(history)//2} exchanges)[/bold]\n")
    for i, msg in enumerate(history):
        role    = "[bold cyan]You[/bold cyan]" if msg["role"]=="user" else "[bold blue]AI[/bold blue]"
        preview = msg["text"][:120] + ("..." if len(msg["text"])>120 else "")
        console.print(f"  {role}: {preview}\n")

# ── MEMORY ────────────────────────────────────────
def cmd_remember(fact):
    mem = load_memory()
    mem.append(fact)
    save_memory(mem)
    console.print(f"[green]✓ Remembered: {fact}[/green]")

def cmd_show_memory():
    mem = load_memory()
    if not mem: console.print("[dim]No memories saved[/dim]"); return
    console.print(Panel("\n".join(f"  {i+1}. {m}" for i,m in enumerate(mem)),
        title="Memory", border_style="cyan"))

def cmd_forget(idx=None):
    mem = load_memory()
    if not mem: console.print("[dim]Nothing to forget[/dim]"); return
    if idx not in (None, "", 0, "0"):
        try:
            i = int(idx)-1
            removed = mem.pop(i)
            save_memory(mem)
            console.print(f"[green]✓ Forgot: {removed}[/green]")
        except Exception: console.print("[red]Invalid index[/red]")
    else:
        if _safe_input("[bold red]Clear ALL memories? (yes/no): [/bold red]").strip().lower() == "yes":
            save_memory([])
            console.print("[green]✓ Memory cleared[/green]")

# ── COMPARE ───────────────────────────────────────
def cmd_compare(state, prompt):
    models  = [
        ("gemini-2.0-flash", "Gemini Flash", state.get("api_key")),
        (state.get("model"), "Current Model", state.get("openrouter_key") if _is_openrouter_model(state.get("model")) else state.get("api_key")),
    ]
    results = []
    for model, label, key in models:
        if not key or not model:
            results.append((label, model, f"[red]Missing API key for {label}[/red]"))
            continue
        console.print(f"[dim]Asking {label} ({model})...[/dim]")
        try:
            if _is_openrouter_model(model):
                text, err = call_openrouter(key, model, [], prompt, build_system_prompt(state))
            else:
                text, err = call_gemini(key, model, [], prompt, build_system_prompt(state))
            
            if err:
                results.append((label, model, f"[red]Error: {err}[/red]"))
            else:
                results.append((label, model, text or "[dim](no response)[/dim]"))
        except Exception as e:
            results.append((label, model, f"[red]Exception: {e}[/red]"))

    for label, model, text in results:
        console.print(Panel(Markdown(text) if "[red]" not in text else text, 
                            title=f"[bold]{label}[/bold] [dim]{model}[/dim]", 
                            border_style="cyan"))

# ── PERSONA ───────────────────────────────────────
def cmd_persona(state, args):
    theme = state.get("theme", THEMES["default"])
    if not args:
        tbl = Table(title="Personas", box=box.ROUNDED, border_style=theme["border"])
        tbl.add_column("Name",    style="bold yellow", no_wrap=True)
        tbl.add_column("Preview", style="dim")
        for k, v in PERSONAS.items():
            tbl.add_row(k, (v[:70] + "…") if len(v) > 70 else v)
        tbl.add_row("custom", "Open editor to write a custom persona")
        tbl.add_row("reset",  "Restore default persona")
        console.print(tbl)
        current = state.get("system_prompt") or load_persona()
        console.print(f"[dim]Active: {current[:90]}…[/dim]")
        return state
    if args in PERSONAS:
        state["system_prompt"] = PERSONAS[args]
        save_persona(PERSONAS[args])
        console.print(f"[{theme['success']}]✓ Persona → '{args}'[/{theme['success']}]")
    elif args == "custom":
        new = open_editor(state.get("system_prompt") or load_persona(), ".txt")
        if new.strip():
            state["system_prompt"] = new.strip(); save_persona(new.strip())
            console.print("[green]✓ Custom persona saved[/green]")
    elif args == "reset":
        state["system_prompt"] = PERSONAS["default"]; save_persona(PERSONAS["default"])
        console.print("[green]✓ Persona reset to default[/green]")
    else:
        state["system_prompt"] = args; save_persona(args)
        console.print(f"[green]✓ Persona set (inline)[/green]")
    return state

# ── STATUS ────────────────────────────────────────
def show_status(state):
    cli  = detect_gemini_cli()
    mode = "Gemini CLI" if state.get("use_cli") and cli \
        else "OpenRouter" if state.get("use_openrouter") and state.get("openrouter_key") \
        else "Gemini API"
    mem   = load_memory()
    saves = list(CONVOS_DIR.glob("*.json")) if CONVOS_DIR.exists() else []
    theme = state.get("theme", THEMES["default"])
    lt    = state.get("_last_tokens")
    tok_line = f"in≈{lt['in']} out≈{lt['out']} ({lt['sec']}s)" if lt else "—"
    console.print(Panel(
        f"[bold]Mode:[/bold]       [cyan]{mode}[/cyan]\n"
        f"[bold]Model:[/bold]      {state['model']}\n"
        f"[bold]Theme:[/bold]      {theme['name']}\n"
        f"[bold]Gemini CLI:[/bold] {'[green]✓[/green]' if cli else '[dim]not found[/dim]'}\n"
        f"[bold]Node/npx:[/bold]   {'[green]✓[/green]' if shutil.which('npx') else '[dim]not found[/dim]'}\n"
        f"[bold]Directory:[/bold]  {os.getcwd()}\n"
        f"[bold]Persona:[/bold]    {(state.get('system_prompt') or load_persona())[:60]}…\n"
        f"[bold]Memory:[/bold]     {len(mem)} items\n"
        f"[bold]Context:[/bold]    {state.get('context_file') or 'none'}\n"
        f"[bold]Saved chats:[/bold]{len(saves)}\n"
        f"[bold]Last tokens:[/bold]{tok_line}",
        title="Status", border_style=theme["border"]))

# ── USAGE COMMAND ─────────────────────────────────
def cmd_usage(state):
    theme    = state.get("theme", THEMES["default"])
    plan_id  = get_plan(state)
    plan     = PLANS.get(plan_id, PLANS["free"])
    prof     = load_profile() or {}
    usage    = load_usage()
    trial    = load_trial()
    lt       = state.get("_last_tokens")

    msgs_used  = prof.get("session_msgs", 0)
    msgs_limit = plan["msg_limit"]
    total_in   = usage.get("total_in", 0)
    total_out  = usage.get("total_out", 0)

    # Message bar
    if msgs_limit >= 99999:
        msg_bar = "[green]∞ unlimited[/green]"
    else:
        pct    = min(100, int(msgs_used / msgs_limit * 100))
        filled = int(24 * pct / 100)
        color  = "red" if pct >= 80 else "yellow" if pct >= 60 else "green"
        bar    = "█" * filled + "░" * (24 - filled)
        msg_bar = f"[{color}]{bar}[/{color}]  {msgs_used}/{msgs_limit} ({pct}%)"

    # Trial line
    trial_line = ""
    if trial:
        rem  = max(0, trial["expires"] - time.time())
        h, r = divmod(int(rem), 3600)
        m    = r // 60
        trial_line = f"\n[bold]Trial:[/bold]        [yellow]{PLANS.get(trial['plan'],{}).get('name','Pro')} — {h}h {m:02d}m remaining[/yellow]"

    last_line = (f"in≈{lt['in']}t  out≈{lt['out']}t  {lt['sec']}s" if lt else "—")

    ok, rl_count = check_rate_limit(state)
    _rl_caps    = {"free": 10, "pro": 200, "max": 500, "ultra": 1000, "enterprise": 9999}
    _rl_windows = {"free": "1hr", "pro": "5hr", "max": "10hr", "ultra": "24hr", "enterprise": "24hr"}
    rl_cap    = _rl_caps.get(plan_id, 10)
    rl_window = _rl_windows.get(plan_id, "1hr")
    model_access = "all models" if plan["models"] is None else plan["models"][0].split("/")[1]

    console.print(Panel(
        f"[bold]Plan:[/bold]         [{plan['color']}]{plan['badge']} {plan['name']}[/{plan['color']}]  [dim]{plan['price']}[/dim]{trial_line}\n\n"
        f"[bold]Messages:[/bold]     {msg_bar}\n"
        f"[bold]Tokens in:[/bold]    {total_in:,}\n"
        f"[bold]Tokens out:[/bold]   {total_out:,}\n"
        f"[bold]Total tokens:[/bold] {total_in+total_out:,}\n"
        f"[bold]Last request:[/bold] {last_line}\n\n"
        f"[bold]Rate window:[/bold]  {rl_count} requests  [dim](cap: {rl_cap}/{rl_window})[/dim]\n"
        f"[bold]Image quota:[/bold]  {plan['img_per_3h']}/3h\n"
        f"[bold]Model access:[/bold] {model_access}\n\n"
        f"  [dim]/trial pro   /upgrade pro   /plan   /usage[/dim]",
        title="[bold]Usage & Plan Limits[/bold]",
        border_style=theme["border"]
    ))


def cmd_trial(state, args):
    theme = state.get("theme", THEMES["default"])
    plan  = (args or "pro").strip().lower()
    if plan not in ("pro", "max"):
        console.print("[yellow]Usage: /trial pro | /trial max[/yellow]")
        return state

    existing = load_trial()
    if existing:
        rem  = max(0, existing["expires"] - time.time())
        h, r = divmod(int(rem), 3600)
        m    = r // 60
        console.print(f"[yellow]Trial already active: {existing['plan']} — {h}h {m:02d}m remaining.[/yellow]")
        return state

    base_plan = get_plan(state)
    if base_plan not in ("free",):
        console.print(f"[yellow]You're already on {PLANS.get(base_plan,{}).get('name','paid')} plan. Trial is for Free users.[/yellow]")
        return state

    # Trials count against the same 2-slot cap as paid upgrades
    ok, msg = claim_upgrade_slot(_current_user_id(state), plan)
    if not ok:
        console.print(Panel(
            msg,
            title="[bold red]Trial Slots Full[/bold red]",
            border_style="red", padding=(1, 2)))
        return state

    trial = start_trial(plan, hours=5)
    p     = PLANS.get(plan, PLANS["pro"])
    console.print()
    console.print(f"  [{p['color']}]⚡ {p['name']} Trial activated![/{p['color']}]")
    console.print(f"  [dim]5 hours of {p['name']} access. Enjoy.[/dim]\n")
    console.print(f"  [{theme['success']}]Expires: {datetime.fromtimestamp(trial['expires']).strftime('%H:%M:%S')}[/{theme['success']}]\n")
    reset_msg_counter(state)
    # NOTE: do not write state["plan"] here — get_plan() already prefers an
    # active trial via load_trial(). Overwriting state["plan"] used to leave
    # the user pinned to "pro" after the trial expired.
    return state


def cmd_studio_update(state):
    theme = state.get("theme", THEMES["default"])
    console.print("[dim]Checking for updates...[/dim]")
    result = sync_dev_changes()
    install = Path.home() / "AppData" / "Local" / "aistudio" / "aistudio.py"
    current = Path(__file__).resolve()
    if result == "pushed":
        console.print(f"[{theme['success']}]✓ Pushed dev → install ({install})[/{theme['success']}]")
    elif result == "pulled":
        console.print(f"[{theme['success']}]✓ Update applied.[/{theme['success']}]  [dim]Relaunching now…[/dim]")
        time.sleep(0.6)
        cmd_restart(state)
    else:
        try:
            in_sync = current.samefile(install) or (install.exists() and abs(current.stat().st_mtime - install.stat().st_mtime) < 2)
        except Exception:
            in_sync = False
        console.print(Panel(
            f"[bold]Running:[/bold]      {current}\n"
            f"[bold]Install:[/bold]      {install}\n"
            f"[bold]Install exists:[/bold] {'yes' if install.exists() else '[red]no[/red]'}\n"
            f"[bold]In-sync:[/bold]      {'[green]yes[/green]' if in_sync else '[yellow]out of sync[/yellow]'}\n"
            f"[bold]Version:[/bold]      v{VERSION}\n\n"
            f"  [dim]If out of sync: run install_windows.bat to reinstall.[/dim]",
            title="Studio Update", border_style=theme["border"]
        ))


# ── ADVANCED FEATURES ────────────────────────────
def cmd_todo(state):
    """Scan project for TODO/FIXME comments."""
    p = Path(state.get("workspace_root") or load_workspace_root() or Path.cwd())
    matches = []
    for f in p.rglob("*"):
        if f.is_file() and f.suffix in CODE_EXTS and not any(x in str(f) for x in SKIP_DIRS):
            try:
                for i, line in enumerate(f.read_text(encoding="utf-8",errors="replace").splitlines(), 1):
                    if any(kw in line.upper() for kw in ("TODO:", "FIXME:", "BUG:")):
                        matches.append((str(f.relative_to(p)), i, line.strip()))
            except Exception: pass
    if not matches:
        console.print("[green]✓ No TODOs found![/green]")
        return
    table = Table(title="Project TODOs", box=box.SIMPLE)
    table.add_column("File", style="cyan"); table.add_column("Line", style="yellow"); table.add_column("Task")
    for f, ln, text in matches[:40]:
        table.add_row(f, str(ln), text[:80])
    console.print(table)

def cmd_bench(state):
    """Benchmark current model speed and throughput."""
    console.print(f"[dim]Benchmarking {state['model']}...[/dim]")
    t0 = time.time()
    prompt = "Write a 200 word story about a digital cat."
    res, _ = ai_respond(state, prompt, [], silent=True)
    dt = time.time() - t0
    if not res: return
    toks = approx_tokens(res)
    console.print(Panel(
        f"[bold]Latency:[/bold]   {dt:.2f}s\n"
        f"[bold]Tokens:[/bold]    {toks}t\n"
        f"[bold]Speed:[/bold]     {toks/dt:.1f} t/s",
        title="Model Benchmark", border_style="magenta"))

def cmd_tts(state, args=None):
    """Speak the last AI response aloud (Windows TTS, /tts)."""
    args = (args or "").strip()
    if sys.platform != "win32":
        console.print("[yellow]TTS is only supported on Windows.[/yellow]")
        return
    text = state.get("_last_response", "")
    if not text:
        console.print("[yellow]Nothing to speak — send a message first.[/yellow]")
        return
    # Clean for voice
    clean = re.sub(r"\[.*?\]", "", text).replace("\n", " ").strip()
    msg = clean[:500]
    console.print("[dim]Speaking...[/dim]")

    # Use Base64 encoded script block to prevent ANY injection
    import base64
    script = f'Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak({json.dumps(msg)})'
    encoded_script = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    tts_cmd = f'PowerShell -NoProfile -EncodedCommand {encoded_script}'
    subprocess.Popen(tts_cmd, shell=True)

def cmd_stats(state):
    """Show detailed usage statistics."""
    usage = load_usage()
    table = Table(title="Usage Statistics", box=box.ROUNDED)
    table.add_column("Metric", style="bold cyan"); table.add_column("Value", style="green")
    table.add_row("Total Input Tokens", f"{usage.get('total_in',0):,}")
    table.add_row("Total Output Tokens", f"{usage.get('total_out',0):,}")
    table.add_row("Requests (Last 5h)", str(len(usage.get("history", []))))
    table.add_row("Current Balance", f"${state.get('balance',0):.2f}")
    console.print(table)

def cmd_balance(state):
    """Detailed financial breakdown with provider info and API tiers."""
    import random
    prof = load_profile() or {}
    plan_id = get_plan(state)
    plan_cfg = PLANS.get(plan_id, PLANS["free"])
    theme = state.get("theme", THEMES["default"])

    # Determine active provider
    if state.get("use_cli"):
        provider = "Gemini CLI"
        provider_color = "blue"
        api_type = "CLI passthrough"
    elif state.get("openrouter_key"):
        provider = "OpenRouter"
        provider_color = "magenta"
        api_type = "Teams API" if plan_id in ("enterprise", "ultra") else "Dev API"
    elif state.get("api_key"):
        provider = "Gemini Direct"
        provider_color = "cyan"
        api_type = "Dev API"
    elif state.get("cursor_key"):
        provider = "Cursor API"
        provider_color = "yellow"
        api_type = "Dev API"
    else:
        provider = "None (offline)"
        provider_color = "red"
        api_type = "—"

    usage = state.get("_usage", {})
    total_in  = usage.get("total_in", 0)
    total_out = usage.get("total_out", 0)
    # Real accumulated cost from track_usage() — free-model tokens show as $0
    active_model = state.get("model") or DEFAULT_MODEL
    rate = model_price_per_1k(active_model)
    session_cost = round(((total_in + total_out) / 1000) * rate, 6)
    lifetime_spend = round(abs(prof.get("balance", 0)), 6)  # balance is a running debit
    model_spend = prof.get("model_spend", {})

    rate_label = f"${rate:.5f}/1k" if rate > 0 else "free tier ($0)"
    free_note  = "  [dim](free-tier model — tokens tracked, no charge)[/dim]\n" if rate == 0.0 else ""
    top_spend  = sorted(model_spend.items(), key=lambda x: x[1], reverse=True)[:3]
    spend_lines = "".join(
        f"  [dim]  {_short_model(m)}: ${v:.6f}[/dim]\n" for m, v in top_spend
    ) if top_spend else ""

    body = (
        f"  [bold]Account[/bold]          [{plan_cfg['color']}]{prof.get('user', 'User')}[/{plan_cfg['color']}]"
        f"  [{plan_cfg['color']}]{plan_cfg['badge']} {plan_cfg['name']}[/{plan_cfg['color']}]\n"
        f"\n"
        f"  [bold]Provider[/bold]         [{provider_color}]{provider}[/{provider_color}]\n"
        f"  [bold]API Tier[/bold]         [dim]{api_type}[/dim]\n"
        f"  [bold]Active Rate[/bold]      [dim]{rate_label}[/dim]\n"
        f"\n"
        f"  [bold]Session Spend[/bold]    {'[green]$0.000000[/green]' if rate == 0 else f'[yellow]-${session_cost:.6f}[/yellow]'}  [dim](estimated)[/dim]\n"
        f"  [bold]Lifetime Spend[/bold]   [{'green' if lifetime_spend == 0 else 'yellow'}]${lifetime_spend:.6f}[/{'green' if lifetime_spend == 0 else 'yellow'}]  [dim](estimated)[/dim]\n"
        f"\n"
        f"  [bold]Tokens (session)[/bold] [dim]{total_in:,} in  /  {total_out:,} out[/dim]\n"
        f"{free_note}"
        f"{spend_lines}"
    )

    if api_type == "Teams API":
        body += f"\n  [dim cyan]Teams API: shared pool, priority routing, SLA guaranteed.[/dim cyan]\n"
    elif api_type == "Dev API":
        body += f"\n  [dim]Dev API: personal key, standard rate limits.[/dim]\n"

    if plan_id == "enterprise":
        body += f"\n  [bold]Contract[/bold]         Custom — contact [cyan]studio@foxxia.dev[/cyan]\n"

    accent = theme.get("accent", "cyan")
    border = theme.get("border", "cyan")
    console.print()
    console.print(Panel(
        body,
        title=f"[bold {accent}]  Balance & API  [/bold {accent}]",
        border_style=border,
        padding=(1, 2)
    ))
    console.print()

# ═══════════════════════════════════════════════════════════════
# ── v5.6 NEW FEATURES ─────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════

def cmd_history(state, history):
    """/history — pretty-print session turns with index, role, preview."""
    if not history:
        console.print("[dim]No history yet — start chatting![/dim]")
        return
    theme = state.get("theme", THEMES["default"])
    rows = []
    for i, m in enumerate(history):
        role   = m.get("role", "?")
        text   = m.get("text", "")
        icon   = "▸" if role == "user" else "◆"
        color  = theme.get("prompt_user", "cyan") if role == "user" else theme.get("success", "green")
        label  = "YOU" if role == "user" else "AI"
        preview = text[:120].replace("\n", " ")
        if len(text) > 120: preview += "…"
        rows.append(f"  [dim]{i+1:>3}[/dim]  [{color}]{icon} {label}[/{color}]  {preview}")
    console.print(Panel(
        "\n".join(rows),
        title=f"[bold]Session History — {len(history)} turns[/bold]",
        border_style=theme.get("border", "cyan"),
        padding=(0, 1)
    ))


def cmd_export(state, history):
    """Export current chat — HTML (rich) or Markdown."""
    if not history:
        console.print("[yellow]Nothing to export yet.[/yellow]")
        return
    fmt = console.input("  Export as [bold](h)tml[/bold] or [bold](m)arkdown[/bold]? [dim][h/m, default h][/dim]: ").strip().lower()
    use_md = fmt == "m"
    ts     = int(time.time())

    if use_md:
        path = CONFIG_DIR / f"chat_export_{ts}.md"
        lines = [f"# AI Studio CLI — Chat Export\n\n*Exported {time.strftime('%Y-%m-%d %H:%M:%S')}*\n\n---\n"]
        for m in history:
            role = "**You**" if m["role"] == "user" else "**AI**"
            lines.append(f"{role}\n\n{m['text']}\n\n---\n")
        path.write_text("\n".join(lines), encoding="utf-8")
        console.print(f"[green]✓ Markdown export → {path}[/green]")
    else:
        path = CONFIG_DIR / f"chat_export_{ts}.html"
        rows = ""
        for m in history:
            role  = "YOU" if m["role"] == "user" else "AI"
            color = "#5f5fff" if role == "YOU" else "#00ff88"
            text  = m["text"].replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace("\n","<br>")
            rows += (
                f"<div style='margin-bottom:24px;padding:14px 18px;"
                f"background:#12121f;border-left:3px solid {color};border-radius:6px;'>"
                f"<b style='color:{color};font-size:11px;letter-spacing:2px;'>{role}</b>"
                f"<div style='margin-top:8px;font-size:14px;line-height:1.7;'>{text}</div></div>"
            )
        html = (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<title>AI Studio Export</title>"
            "<style>*{box-sizing:border-box}body{margin:0;padding:40px;background:#0d0d1a;"
            "color:#ddd;font-family:'Segoe UI',sans-serif;max-width:860px;margin:0 auto;}"
            "h1{color:#5f5fff;border-bottom:1px solid #333;padding-bottom:12px;}"
            "small{color:#555;}</style></head><body>"
            f"<h1>🤖 AI Studio CLI</h1><small>v{VERSION} · "
            f"{time.strftime('%Y-%m-%d %H:%M:%S')} · {len(history)} turns</small>"
            f"<div style='margin-top:32px;'>{rows}</div></body></html>"
        )
        path.write_text(html, encoding="utf-8")
        console.print(f"[green]✓ HTML export → {path}[/green]")
        if sys.platform == "win32":
            os.startfile(path)


def cmd_models(state):
    """/models — list models then launch interactive arrow-key picker."""
    model      = state.get("model") or DEFAULT_MODEL
    theme      = state.get("theme", THEMES["default"])
    acc        = theme.get("accent", "bold cyan")
    border_raw = theme.get("border", "cyan").replace("bold ", "")

    # Build deduplicated model list
    free_models = PLANS.get("free", {}).get("models", [])
    all_models  = list(dict.fromkeys(FREE_CHAT_MODELS + list(STUDIO_MODEL_ALIASES.values())))
    if model not in all_models:
        all_models.insert(0, model)

    # Load per-model usage from profile for annotations
    prof       = load_profile() or {}
    model_usage = prof.get("model_usage", {})
    total_uses  = sum(model_usage.values()) or 1
    top_model   = max(model_usage, key=model_usage.get) if model_usage else None
    rare_threshold = max(1, total_uses * 0.02)

    table = Table(
        title=f"[bold]Models[/bold]  [dim]↑↓ to pick · Enter to switch · Esc to cancel[/dim]",
        box=box.ROUNDED,
        border_style=border_raw,
        show_lines=False,
    )
    table.add_column("#",      style="dim",        width=4)
    table.add_column("Model",  style="bold white",  min_width=34)
    table.add_column("Route",  style="cyan",        width=12)
    table.add_column("Usage",  style="dim",         width=7, justify="right")
    table.add_column("Notes",  style="dim",         min_width=16)

    for i, m in enumerate(all_models, 1):
        route   = "OpenRouter" if _is_openrouter_model(m) else "Gemini"
        is_act  = (m == model)
        uses    = model_usage.get(m, 0)
        use_str = str(uses) if uses else "—"
        tags    = []
        if is_act:                             tags.append("[bold green]● active[/bold green]")
        if m == top_model and uses > 0:        tags.append("[yellow]★ top[/yellow]")
        if m in free_models:                   tags.append("[dim]free[/dim]")
        if uses > 0 and uses <= rare_threshold: tags.append("[dim red]rare[/dim red]")
        notes = "  ".join(tags)
        table.add_row(
            str(i),
            f"[bold cyan]{m}[/bold cyan]" if is_act else m,
            route,
            use_str,
            notes,
        )

    console.print()
    console.print(table)
    console.print(f"  [dim]Or type: [bold]/model <name>[/bold]  ·  Local: [bold]/local llama3[/bold][/dim]\n")

    # ── Arrow-key interactive picker ────────────────────────────────
    console.print(f"  [{acc}]Press ↑↓ to select a model, Enter to switch, Esc to keep current[/{acc}]\n")

    labels  = [_short_model(m) for m in all_models]
    cur_idx = next((i for i, m in enumerate(all_models) if m == model), 0)

    def _draw(sel):
        lines = []
        start = max(0, sel - 4)
        end   = min(len(all_models), start + 9)
        if sel == len(all_models) - 1 and end - start < 9:
            start = max(0, end - 9)
        for i in range(start, end):
            m = all_models[i]
            short = labels[i]
            uses  = model_usage.get(m, 0)
            use_tag = f" [dim]×{uses}[/dim]" if uses else ""
            if i == sel:
                console.print(f"  [{acc}]▶  {short}{use_tag}[/{acc}]")
            else:
                console.print(f"  [dim]   {short}{use_tag}[/dim]")
        if len(all_models) > 9:
            console.print(f"  [dim]   … {len(all_models)} total[/dim]")

    _draw(cur_idx)

    while True:
        key = _read_key()
        if key == 'UP':
            cur_idx = (cur_idx - 1) % len(all_models)
        elif key == 'DOWN':
            cur_idx = (cur_idx + 1) % len(all_models)
        elif key == 'ENTER':
            chosen = all_models[cur_idx]
            state["model"] = chosen
            LAST_MODEL_FILE.parent.mkdir(exist_ok=True)
            LAST_MODEL_FILE.write_text(chosen)
            console.print(f"\n  [{acc}]✓ Model → {_short_model(chosen)}[/{acc}]\n")
            return state
        elif key == 'ESC':
            console.print("[dim]  Keeping current model.[/dim]\n")
            return state
        # Redraw picker
        console.print()
        _draw(cur_idx)

    return state


def cmd_summarize(state, history):
    """/summarize — AI compresses the session into a tight context summary."""
    if len(history) < 4:
        console.print("[yellow]Not enough history to summarize yet.[/yellow]")
        return history
    or_key = state.get("openrouter_key") or load_or_key()
    if not or_key:
        console.print("[red]No API key — cannot summarize.[/red]")
        return history
    turns = "\n".join(
        f"{'USER' if m['role']=='user' else 'AI'}: {m['text'][:400]}"
        for m in history
    )
    prompt = (
        "Compress this conversation into a dense context summary "
        "(max 300 words). Preserve key decisions, file names, errors fixed, "
        "and open tasks. Write in present tense as if briefing a new AI assistant.\n\n"
        f"CONVERSATION:\n{turns}"
    )
    _start_think_anim("Summarizing session")
    summary, err = call_openrouter(or_key, state.get("model") or DEFAULT_MODEL, [], prompt)
    _stop_think_anim()
    if err:
        console.print(f"[red]{err}[/red]")
        return history
    console.print(Panel(summary, title="[bold]Session Summary[/bold]", border_style="cyan"))
    keep = console.input("  [bold]Replace history with this summary?[/bold] [dim](y/n)[/dim]: ").strip().lower()
    if keep == "y":
        history = [{"role": "user", "text": "[Session context summary:]"},
                   {"role": "model", "text": summary}]
        console.print("[green]✓ History compressed — context reset with summary.[/green]")
    return history


def cmd_autonomous(state, args, history):
    """/autonomous — toggle autonomous mode: skips write permissions, runs FIF+PATCH loops."""
    currently = state.get("autonomous", False)
    args = (args or "").strip()
    if args.lower() in ("off", "0", "false", "stop"):
        state["autonomous"] = False
        console.print("[green]✓ Autonomous mode OFF — permission checks restored.[/green]")
        return history
    if args.lower() in ("on", "1", "true", "start", ""):
        if not currently:
            console.print(Panel(
                "[bold yellow]⚡ AUTONOMOUS MODE[/bold yellow]\n\n"
                "In this mode Studio CLI will:\n"
                "  [red]•[/red] Skip all write-permission prompts\n"
                "  [red]•[/red] Auto-apply patches without confirmation\n"
                "  [red]•[/red] Run FIF → PATCH loops unattended\n\n"
                "[dim]Use [bold]/autonomous off[/bold] to restore normal behaviour.[/dim]",
                border_style="yellow", padding=(1, 2)
            ))
            confirm = console.input("  Enable autonomous mode? [dim](y/n)[/dim]: ").strip().lower()
            if confirm != "y":
                console.print("[dim]Cancelled.[/dim]")
                return history
        state["autonomous"] = True
        # Patch check_write_allowed for this session
        console.print("[bold yellow]⚡ Autonomous mode ON[/bold yellow]  [dim]— all writes auto-approved[/dim]")
        return history
    # If a task is provided after /autonomous <task>, run it directly
    task = args
    state["autonomous"] = True
    console.print(f"[bold yellow]⚡ Autonomous[/bold yellow]  running: [dim]{task}[/dim]")
    _, history = ai_respond(state, task, history)
    return history


CREATOR_ANALYTICS_FILE = CONFIG_DIR / "creator_analytics.json"

def _load_creator_analytics():
    """Scan profiles/ dir and aggregate per-user stats."""
    profiles_root = Path("profiles")
    records = {}

    # Load existing analytics cache
    if CREATOR_ANALYTICS_FILE.exists():
        try:
            records = json.loads(CREATOR_ANALYTICS_FILE.read_text(encoding="utf-8"))
        except Exception:
            records = {}

    # Merge fresh profile data
    if profiles_root.exists():
        for user_dir in profiles_root.iterdir():
            if not user_dir.is_dir(): continue
            uid  = user_dir.name
            prof_path = user_dir / "profile.json"
            if not prof_path.exists(): continue
            try:
                prof = json.loads(prof_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            rec = records.setdefault(uid, {
                "user_id":         uid,
                "plan":            "free",
                "first_seen":      None,
                "last_seen":       None,
                "session_count":   0,
                "total_tokens_in": 0,
                "total_tokens_out":0,
                "total_msgs":      0,
                "models_used":     [],
                "images_generated":0,
            })
            rec["plan"]      = prof.get("plan", rec["plan"])
            rec["last_seen"] = prof.get("last_seen") or rec["last_seen"]
            rec["first_seen"]= prof.get("onboarded_at") or rec["first_seen"]
            rec["name"]      = prof.get("user") or rec.get("name")
            rec["dev_type"]  = prof.get("dev_type") or rec.get("dev_type", "—")
            rec["persona"]   = prof.get("persona") or rec.get("persona", "default")
            rec["ui_style"]  = prof.get("ui_style") or rec.get("ui_style", "gemini")
            if "balance" in prof:
                rec["balance"] = prof["balance"]

    # Persist
    CREATOR_ANALYTICS_FILE.parent.mkdir(exist_ok=True)
    CREATOR_ANALYTICS_FILE.write_text(json.dumps(records, indent=2), encoding="utf-8")
    return records


def cmd_creator_analytics(state):
    """/creator — show per-user analytics dashboard (creator-only)."""
    theme = state.get("theme", THEMES["default"])

    # Optional: gate behind a creator flag
    prof = load_profile() or {}
    if prof.get("role") not in ("creator", "admin", "owner"):
        console.print("[red]✖ Creator access required.[/red]")
        return

    records = _load_creator_analytics()
    if not records:
        console.print("[dim]No user profiles found.[/dim]")
        return

    table = Table(
        title="[bold]Creator Analytics — All Users[/bold]",
        box=box.ROUNDED,
        border_style=theme.get("border", "magenta"),
        show_lines=True,
    )
    table.add_column("Name/ID",       style="bold cyan",  min_width=14)
    table.add_column("Plan",          style="yellow",     width=12)
    table.add_column("Dev Type",      style="dim",        width=10)
    table.add_column("First Login",   style="dim",        width=12)
    table.add_column("Last Active",   style="dim",        width=12)
    table.add_column("Sessions",      style="green",      width=8, justify="right")
    table.add_column("Msgs",          style="green",      width=7, justify="right")
    table.add_column("Imgs",          style="magenta",    width=5, justify="right")
    table.add_column("Tok↑",          style="cyan",       width=9, justify="right")
    table.add_column("Tok↓",          style="cyan",       width=9, justify="right")

    total_msgs  = 0
    total_tok_i = 0
    total_tok_o = 0
    total_users = len(records)

    def _fmt_ts(ts):
        if not ts: return "—"
        try:
            t = float(ts) if str(ts).replace(".", "").isdigit() else \
                datetime.fromisoformat(str(ts)).timestamp()
            return time.strftime("%Y-%m-%d", time.localtime(t))
        except Exception:
            return str(ts)[:10]

    for uid, rec in sorted(records.items()):
        p_id  = rec.get("plan", "free")
        p_cfg = PLANS.get(p_id, PLANS["free"])
        plan_label = f"[{p_cfg['color']}]{p_cfg['badge']} {p_cfg['name']}[/{p_cfg['color']}]"
        name_label = rec.get("name") or uid[:14]
        dev_type   = rec.get("dev_type", "—")
        table.add_row(
            name_label,
            plan_label,
            dev_type,
            _fmt_ts(rec.get("first_seen")),
            _fmt_ts(rec.get("last_seen")),
            str(rec.get("session_count", 0)),
            str(rec.get("total_msgs", 0)),
            str(rec.get("images_generated", 0)),
            f"{rec.get('total_tokens_in', 0):,}",
            f"{rec.get('total_tokens_out', 0):,}",
        )
        total_msgs  += rec.get("total_msgs", 0)
        total_tok_i += rec.get("total_tokens_in", 0)
        total_tok_o += rec.get("total_tokens_out", 0)

    console.print(table)

    # Summary panel
    plan_dist = {}
    for rec in records.values():
        plan_dist[rec.get("plan", "free")] = plan_dist.get(rec.get("plan", "free"), 0) + 1
    dist_str = "  ".join(
        f"[{PLANS.get(p, PLANS['free'])['color']}]{PLANS.get(p, PLANS['free'])['badge']} {p}: {n}[/{PLANS.get(p, PLANS['free'])['color']}]"
        for p, n in sorted(plan_dist.items(), key=lambda x: -x[1])
    )
    summary = (
        f"[bold]Total users:[/bold]    [bold cyan]{total_users}[/bold cyan]\n"
        f"[bold]Plan breakdown:[/bold] {dist_str}\n"
        f"[bold]Total msgs:[/bold]     [green]{total_msgs:,}[/green]\n"
        f"[bold]Total tokens:[/bold]   [cyan]{total_tok_i:,} in[/cyan]  ·  [cyan]{total_tok_o:,} out[/cyan]\n"
        f"[dim]Data: {CREATOR_ANALYTICS_FILE}[/dim]"
    )
    console.print(Panel(summary, title="[bold]Summary[/bold]", border_style="magenta", padding=(0, 2)))

    # ── Feedback & Complaints ──────────────────────────────────────────────────
    fb_path = CONFIG_DIR / "feedback_log.json"
    if fb_path.exists():
        try:
            fb_all = json.loads(fb_path.read_text(encoding="utf-8"))
        except Exception:
            fb_all = []
        if fb_all:
            fb_tbl = Table(
                title="[bold red]Feedback & Complaints[/bold red]",
                box=box.ROUNDED, border_style="red", show_lines=True,
            )
            fb_tbl.add_column("Type",    width=10)
            fb_tbl.add_column("Plan",    width=8)
            fb_tbl.add_column("Time",    style="dim", width=17)
            fb_tbl.add_column("Message", min_width=40)
            for e in fb_all[-20:]:
                t = e.get("type", "feedback")
                color = "red" if t == "complaint" else "yellow"
                icon  = "◉" if t == "complaint" else "◇"
                plan_e = e.get("plan", "?")
                p_cfg_e = PLANS.get(plan_e, PLANS["free"])
                plan_label_e = f"[{p_cfg_e['color']}]{p_cfg_e['badge']} {plan_e}[/{p_cfg_e['color']}]"
                fb_tbl.add_row(
                    f"[{color}]{icon} {t}[/{color}]",
                    plan_label_e,
                    e.get("ts","")[:16].replace("T"," "),
                    e.get("text",""),
                )
                # Mark as read
                e["read"] = True
            # Persist read flags
            try:
                fb_path.write_text(json.dumps(fb_all, indent=2), encoding="utf-8")
            except Exception:
                pass
            console.print()
            console.print(fb_tbl)


# ─── honour autonomous mode in check_write_allowed ────────────────────────
_orig_check_write_allowed = None

def _patch_autonomous_writes(state):
    """Monkey-patch check_write_allowed to skip prompts when autonomous=True."""
    global _orig_check_write_allowed, check_write_allowed
    if _orig_check_write_allowed is None:
        _orig_check_write_allowed = check_write_allowed

    def _auto_check(*args, **kwargs):
        if state.get("autonomous"):
            _path = args[1] if len(args) > 1 else kwargs.get("path", "a file")
            _verb = args[2] if len(args) > 2 else kwargs.get("verb", "write")
            console.print(f"[dim yellow]⚡ Auto-approved: {_verb} → {_path}[/dim yellow]")
            return True
        return _orig_check_write_allowed(*args, **kwargs)

    check_write_allowed = _auto_check


# ═══════════════════════════════════════════════════════════════
# ── END v5.6 NEW FEATURES ─────────────────────────────────────
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
# ── v5.7 NEW FEATURES ─────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════

CHANGELOG = {
    "6.2": [
        "New: /vault now uses Fernet AES encryption when cryptography is installed (pip install cryptography)",
        "New: git branch shown in toolbar (⎇branch) — TTL-cached, no keypress perf hit",
        "New: /test saves generated test file and offers to run it + fix failures",
        "New: /team export — write team roster to team_export.json in workspace",
        "New: Arena winner vote — pick best response by number, copy to clipboard",
        "Fix: /run and /shell use safe subprocess list form (no shell=True injection risk)",
        "Fix: Gemini API now retries on 429/503 with exponential backoff (3 attempts)",
        "Fix: Gemini 401/403 shows 'Invalid key — run /setup' instead of raw JSON",
        "Fix: /balance spend lines now labeled (estimated)",
    ],
    "6.0": [
        "Internal web UI with ChatGPT-style design (web/ directory)",
        "Vercel deployment support (vercel.json)",
        "Bug fixes and stability improvements",
    ],
    "5.9": [
        "Fixed: call_cursor streaming path no longer routes through OpenRouter",
        "Fixed: HELP_TEXT and CHANGELOG_TEXT version labels updated to v5.9",
        "Fixed: CHANGELOG dict now includes v5.8 and v5.9 entries for /changelog current badge",
        "Fixed: test suite version assertions updated to v5.9",
    ],
    "5.8": [
        "New UI styles fully Panel-based — no raw f-string width arithmetic",
        "Ghost UI: single-line FormattedText prompt avoids Windows Terminal cursor split",
        "Nova/foxxia matching icon headers; studio/codex/claude/gemini use top+mid box",
        "track_usage() called after every AI response",
        "Profile fields expanded: session_msgs, balance, onboarded_at",
        "Bug fixes: orphaned for-loops in cmd_free_tips, mkdir guards in audit_log/_save_to_inbox",
        "Bug fixes: cmd_voice en-dash → ASCII hyphen in PowerShell command",
        "Bug fixes: CHANGELOG/CHANGELOG_TEXT type consistency",
    ],
    "5.7": [
        "New UI styles: nova (sci-fi), foxxia (orange/gold brand)",
        "New plans: starter ($5), dev ($35), enterprise (custom)",
        "Fixed: cmd_audit, cmd_changelog, cmd_docs, cmd_search, cmd_test stubs",
        "Fixed: _patch_autonomous_writes signature mismatch",
        "Fixed: cmd_models free_models pool resolution",
        "Fixed: ghost UI heading — proper dim border style",
        "Fixed: cmd_analyze dispatch missing args",
        "Prompt prefix now matches UI style (◌ ghost · ⚡ nova · 🦊 foxxia)",
        "render_welcome redesigned for all 7 UI styles",
        "Onboarding: plan comparison table, dev type question, progress bar, summary card",
        "New commands: /vibe, /quickstart",
    ],
    "5.6": [
        "New commands: /history, /models, /summarize, /autonomous, /creator, /export",
        "Auto /enter on startup if cwd looks like a project",
        "Bug fixes: Ollama streaming, HTTP retry, diffpatch polish",
        "Free plan messaging improvements",
        "Fence-stripping in WRITE command",
    ],
    "5.5": [
        "Multi-provider: OpenRouter, Cursor API, HuggingFace images",
        "Agent Mesh and squad system",
        "Live-FIF file watcher",
        "Arena mode — side-by-side model comparison",
        "Effort levels: low/medium/pro/high/xhigh/mxh",
    ],
}


def cmd_changelog(state):
    """/changelog — view version history."""
    theme = state.get("theme", THEMES["default"])
    tbl = Table(
        title=f"[bold]AI Studio CLI — Changelog[/bold]",
        box=box.ROUNDED, border_style=theme.get("border", "cyan"),
        show_lines=True,
    )
    tbl.add_column("Version", style="bold yellow", width=9)
    tbl.add_column("Changes")
    for ver in sorted(CHANGELOG.keys(), reverse=True):
        entries = CHANGELOG[ver]
        tag = f"[bold green]← current[/bold green]" if ver == VERSION else ""
        changes = "\n".join(f"  • {e}" for e in entries)
        tbl.add_row(f"v{ver} {tag}", changes)
    console.print(tbl)


def cmd_audit(state):
    """/audit — AI security scan of the current project."""
    ctx = state.get("project_ctx")
    if not ctx:
        console.print("[yellow]No project loaded. Run /enter first, then /audit.[/yellow]")
        return
    root = ctx.get("root", ".")
    console.print(f"[bold cyan]🔍 Audit scan: {root}[/bold cyan]")
    files = []
    for ext in ["*.py", "*.js", "*.ts", "*.jsx", "*.tsx", "*.env", "*.json"]:
        files.extend(Path(root).rglob(ext))
    files = [
        f for f in files
        if not any(x in str(f) for x in ["node_modules", ".git", "__pycache__", "dist"])
    ][:10]
    if not files:
        console.print("[yellow]No code files found to audit.[/yellow]")
        return
    combined = ""
    for f in files[:6]:
        try:
            combined += f"\n\n--- {f.name} ---\n{f.read_text(errors='ignore')[:800]}"
        except Exception:
            pass
    prompt = (
        "You are a security auditor. Scan this codebase excerpt for:\n"
        "1. Hardcoded secrets / API keys / credentials\n"
        "2. SQL/command injection risks\n"
        "3. Missing auth/validation at boundaries\n"
        "4. Insecure dependencies or patterns\n"
        "5. OWASP Top 10 violations\n\n"
        f"Files scanned: {[f.name for f in files]}\n\n{combined}"
    )
    ai_respond(state, prompt, [])


def cmd_docs(state, args, history):
    """/docs <file> — AI generates documentation for a source file."""
    if not args:
        console.print("[yellow]Usage: /docs <file>[/yellow]")
        return history
    try:
        content, p = read_file_state(state, args)
    except Exception as e:
        console.print(f"[red]{e}[/red]")
        return history
    prompt = (
        f"Generate comprehensive documentation for `{p.name}`.\n"
        "Include: module overview, function/class summaries with parameters and return values, "
        "usage examples, and any important notes or caveats.\n"
        "Format as Markdown. Be thorough but concise.\n\n"
        f"SOURCE:\n{content}"
    )
    _, history = ai_respond(state, prompt, history)
    return history


def cmd_search(state, args):
    """/search <query> — semantic grep: find relevant code sections via AI."""
    if not args:
        console.print("[yellow]Usage: /search <query>[/yellow]")
        return
    ctx = state.get("project_ctx")
    root = Path(ctx["root"]) if ctx else Path.cwd()
    console.print(f"[bold cyan]🔎 Searching: {args!r} in {root}[/bold cyan]")
    files = []
    for ext in ["*.py", "*.js", "*.ts", "*.jsx", "*.tsx"]:
        files.extend(root.rglob(ext))
    files = [f for f in files if not any(x in str(f) for x in ["node_modules", ".git", "__pycache__", "dist"])][:15]
    snippets = []
    for f in files:
        try:
            text = f.read_text(errors="ignore")
            for i, line in enumerate(text.splitlines(), 1):
                if args.lower() in line.lower():
                    snippets.append(f"{f.name}:{i}  {line.strip()}")
        except Exception:
            pass
    if snippets:
        console.print(Panel(
            "\n".join(snippets[:40]),
            title=f"[bold]Literal matches for {args!r}[/bold]",
            border_style="cyan",
        ))
    else:
        console.print(f"[dim]No literal matches. Asking AI for semantic results...[/dim]")
        combined = "\n".join(
            f"{f.name}:\n{f.read_text(errors='ignore')[:400]}" for f in files[:5]
        )
        prompt = (
            f"Search this codebase for: {args!r}\n"
            "List the most relevant files, functions, and line snippets. "
            "Explain why each is relevant.\n\n"
            f"CODEBASE EXCERPT:\n{combined}"
        )
        ai_respond(state, prompt, [])


def cmd_test(state, args, history):
    """/test <file> — AI generates a test file, saves it, and optionally runs it."""
    if not args:
        console.print("[yellow]Usage: /test <file>[/yellow]")
        return history
    try:
        content, p = read_file_state(state, args)
    except Exception as e:
        console.print(f"[red]{e}[/red]")
        return history
    ext = p.suffix.lower()
    if ext == ".py":
        framework  = "pytest"
        test_ext   = ".py"
        run_cmd    = ["python", "-m", "pytest", "-v"]
        test_name  = f"test_{p.stem}{test_ext}"
    elif ext in (".js", ".ts", ".jsx", ".tsx"):
        framework  = "jest"
        test_ext   = ext
        run_cmd    = ["npx", "jest", "--no-coverage"]
        test_name  = f"{p.stem}.test{test_ext}"
    else:
        framework  = "appropriate test framework"
        test_ext   = p.suffix
        run_cmd    = None
        test_name  = f"test_{p.stem}{test_ext}"

    prompt = (
        f"Generate a complete {framework} test file for `{p.name}`.\n"
        "Cover: happy paths, edge cases, error conditions, boundary values.\n"
        "Write realistic test data. Keep tests isolated and deterministic.\n"
        "Return only the test file code — no explanation, no markdown fences.\n\n"
        f"SOURCE:\n{content}"
    )
    console.print(f"[dim]Generating {framework} tests for {p.name}…[/dim]")
    code, history = ai_respond(state, prompt, history)

    if not code:
        return history

    test_path = p.parent / test_name
    try:
        test_path.write_text(code, encoding="utf-8")
        console.print(Panel(
            f"  [bold]Test file saved:[/bold]  [cyan]{test_path}[/cyan]\n"
            f"  [dim]Framework: {framework}[/dim]",
            title="✓ Tests Generated", border_style="green", padding=(0, 2)
        ))
    except Exception as e:
        console.print(f"[red]Could not save test file: {e}[/red]")
        return history

    if run_cmd and console.input("[bold]Run tests now? (y/n): [/bold]").strip().lower() == "y":
        result = subprocess.run(
            run_cmd + [str(test_path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        output = result.stdout + result.stderr
        console.print(output or "[dim](no output)[/dim]")
        if result.returncode != 0:
            if console.input("[bold]Ask AI to fix failures? (y/n): [/bold]").strip().lower() == "y":
                fix_prompt = f"These tests failed:\n\n{output[:3000]}\n\nSource:\n{content[:2000]}\n\nFix the test file."
                _, history = ai_respond(state, fix_prompt, history)

    return history


def call_gemini_cli(prompt, sys_prompt=None):
    """Run the Gemini CLI subprocess and return (output, error)."""
    cli = shutil.which("gemini") or shutil.which("npx")
    if not cli:
        return None, "Gemini CLI not found. Install: npm i -g @google/generative-ai-cli"
    cmd = [cli]
    if cli.endswith("npx"):
        cmd += ["@google/generative-ai-cli"]
    if sys_prompt:
        cmd += ["--system", sys_prompt]
    cmd += ["--prompt", prompt]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return (result.stdout.strip() or None), (result.stderr.strip() or None)
    except subprocess.TimeoutExpired:
        return None, "Gemini CLI timed out after 60s"
    except Exception as e:
        return None, str(e)


# ── VIBE COMMAND ────────────────────────────────────────────────
VIBE_PRESETS = {
    "foxxia":    {"ui": "foxxia",  "theme": "ember"},
    "nova":      {"ui": "nova",    "theme": "neon"},
    "ghost":     {"ui": "ghost",   "theme": "void"},
    "matrix":    {"ui": "codex",   "theme": "matrix"},
    "hacker":    {"ui": "codex",   "theme": "hacker"},
    "sakura":    {"ui": "claude",  "theme": "sakura"},
    "ocean":     {"ui": "claude",  "theme": "ocean"},
    "fire":      {"ui": "studio",  "theme": "fire"},
    "midnight":  {"ui": "studio",  "theme": "midnight"},
    "synthwave": {"ui": "studio",  "theme": "synthwave"},
    "aurora":    {"ui": "gemini",  "theme": "aurora"},
    "dracula":   {"ui": "gemini",  "theme": "dracula"},
    "chatgpt":   {"ui": "ghost",   "theme": "midnight"},
    "cobalt":    {"ui": "codex",   "theme": "cobalt"},
    "carbon":    {"ui": "ghost",   "theme": "carbon"},
    "crimson":   {"ui": "studio",  "theme": "crimson"},
    "slate":     {"ui": "claude",  "theme": "slate"},
    "strawberry":  {"ui": "strawberry",   "theme": "strawberry"},
    "darkred":     {"ui": "darkred",      "theme": "darkred"},
    "sophia":      {"ui": "sophia",       "theme": "sophia"},
    "godson":      {"ui": "godson",       "theme": "godson"},
    "downcli":     {"ui": "downcli",      "theme": "downcli"},
    "badhappening":{"ui": "badhappening", "theme": "badhappening"},
}


def cmd_vibe(state, args):
    """/vibe <preset> — one-shot UI + theme combo setter."""
    if not args:
        tbl = Table(title="[bold]Vibe Presets[/bold]", box=box.SIMPLE, border_style="cyan")
        tbl.add_column("Vibe", style="bold yellow")
        tbl.add_column("UI")
        tbl.add_column("Theme")
        for name, cfg in sorted(VIBE_PRESETS.items()):
            tbl.add_row(name, cfg["ui"], cfg["theme"])
        console.print(tbl)
        console.print("[dim]/vibe <name>  — apply a preset instantly[/dim]")
        return state
    name = args.strip().lower()
    if name not in VIBE_PRESETS:
        console.print(f"[red]Unknown vibe: {name!r}. Run /vibe to see options.[/red]")
        return state
    preset = VIBE_PRESETS[name]
    state = cmd_ui(state, preset["ui"])
    state = cmd_theme(state, preset["theme"])
    console.print(f"[bold green]✓ Vibe → {name}[/bold green]  [dim](ui={preset['ui']} theme={preset['theme']})[/dim]")
    clear_terminal()
    render_welcome(state)
    return state


def cmd_quickstart(state):
    """/quickstart — 5-step guide tailored to the user's plan."""
    theme    = state.get("theme", THEMES["default"])
    plan_id  = get_plan(state)
    plan_cfg = PLANS.get(plan_id, PLANS["free"])
    prof     = load_profile() or {}
    user     = prof.get("user", "Dev")
    dev_type = prof.get("dev_type", "fullstack")

    steps = [
        ("1", "/enter .",       "Scan your project — loads file tree and tech stack into context"),
        ("2", "/read <file>",   "Read a specific file into the AI context window"),
        ("3", "/agent berry",   "Spawn Berry — your sharp, direct main assistant"),
        ("4", "/patch <file>",  "AI surgical code edit — shows diff before writing"),
        ("5", "/fif <file>",    "Find · Identify · Fix — deep multi-pass bug hunt"),
    ]
    if plan_id in ("pro", "dev", "max", "ultra", "team", "enterprise"):
        steps.append(("6", "/arena <prompt>", "Battle of models — compare outputs side by side"))
    if dev_type == "ai":
        steps.append(("✦", "/agent silicon",  "Silicon — elite security + AI/ML specialist"))
    if dev_type == "frontend":
        steps.append(("✦", "/agent berry",    "Ask Berry to generate components or review UI code"))

    body = "\n".join(
        f"  [bold yellow]{n}[/bold yellow]  [cyan]{cmd:<22}[/cyan]  [dim]{desc}[/dim]"
        for n, cmd, desc in steps
    )
    footer = (
        f"\n  [dim]Your plan: [{plan_cfg['color']}]{plan_cfg['badge']} {plan_cfg['name']}[/{plan_cfg['color']}]"
        f"  ·  {plan_cfg['msg_limit'] if plan_cfg['msg_limit'] < 99999 else '∞'} msgs  ·  /plan for details[/dim]"
    )
    console.print(Panel(
        body + footer,
        title=f"[bold]Quick Start — {user}[/bold]",
        border_style=theme.get("border", "cyan"),
        padding=(1, 2),
    ))


def cmd_restart(state):
    """/restart — re-exec the process in-place (applies updates without closing the terminal)."""
    console.print("[bold cyan]↺  Restarting AI Studio CLI...[/bold cyan]")
    time.sleep(0.3)

    # Clear stale .pyc so the new version loads cleanly
    try:
        pycache = Path(__file__).parent / "__pycache__"
        for pyc in pycache.glob("aistudio*.pyc"):
            pyc.unlink(missing_ok=True)
    except Exception:
        pass

    script = Path(__file__).resolve()
    argv   = [sys.executable, str(script)] + sys.argv[1:]

    # Re-exec in-place so the SAME terminal window is reused.
    # os.execv replaces the current process image — no new console spawns.
    try:
        # Flush any pending output before the image is replaced.
        try:
            sys.stdout.flush(); sys.stderr.flush()
        except Exception:
            pass
        if sys.platform == "win32":
            # On Windows, os.execv spawns a new PID but inherits the parent
            # console. Use execve so env is preserved; quote-safe via list args.
            os.execv(sys.executable, argv)
        else:
            os.execv(sys.executable, argv)
    except Exception as e:
        console.print(f"[red]Restart failed: {e}[/red]")
        console.print(f"[dim]Run manually: python \"{script}\"[/dim]")


def _read_key():
    """Read a single keypress. Returns 'UP', 'DOWN', 'ENTER', 'ESC', or the char."""
    try:
        import msvcrt
        ch = msvcrt.getch()
        if ch in (b'\x00', b'\xe0'):
            ch2 = msvcrt.getch()
            if ch2 == b'H': return 'UP'
            if ch2 == b'P': return 'DOWN'
            if ch2 == b'K': return 'LEFT'
            if ch2 == b'M': return 'RIGHT'
            return 'OTHER'
        if ch == b'\r':  return 'ENTER'
        if ch == b'\x1b': return 'ESC'
        if ch == b'\x03': raise KeyboardInterrupt
        return ch.decode('utf-8', errors='ignore')
    except ImportError:
        import sys as _sys, tty, termios
        fd = _sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = _sys.stdin.read(1)
            if ch == '\x1b':
                seq = _sys.stdin.read(2)
                if seq == '[A': return 'UP'
                if seq == '[B': return 'DOWN'
                return 'ESC'
            if ch in ('\r', '\n'): return 'ENTER'
            if ch == '\x03': raise KeyboardInterrupt
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


def cmd_model_picker(state):
    """/pick — interactive arrow-key model selector."""
    model   = state.get("model") or DEFAULT_MODEL
    theme   = state.get("theme", THEMES["default"])
    acc     = theme.get("accent", "bold cyan")
    border  = theme.get("border", "cyan").replace("bold ", "")

    all_models = list(dict.fromkeys(
        FREE_CHAT_MODELS + list(STUDIO_MODEL_ALIASES.values())
    ))
    if model not in all_models:
        all_models.insert(0, model)

    labels = [_short_model(m) for m in all_models]
    idx    = next((i for i, m in enumerate(all_models) if m == model), 0)

    console.print(f"\n[{acc}]◆ Model Picker[/{acc}]  [dim]↑↓ navigate · Enter select · Esc cancel[/dim]\n")

    def _draw(selected_idx):
        lines = []
        for i, label in enumerate(labels):
            if i == selected_idx:
                lines.append(f"  [{acc}]▶  {label}[/{acc}]")
            else:
                lines.append(f"  [dim]   {label}[/dim]")
        console.print(Panel(
            "\n".join(lines),
            title=f"[dim]{len(all_models)} models[/dim]",
            border_style=border,
        ))

    while True:
        _draw(idx)
        key = _read_key()
        if key == 'UP':
            idx = (idx - 1) % len(all_models)
        elif key == 'DOWN':
            idx = (idx + 1) % len(all_models)
        elif key == 'ENTER':
            chosen = all_models[idx]
            state["model"] = chosen
            LAST_MODEL_FILE.parent.mkdir(exist_ok=True)
            LAST_MODEL_FILE.write_text(chosen)
            console.print(f"\n[{acc}]✓ Model → {_short_model(chosen)}[/{acc}]\n")
            return state
        elif key == 'ESC':
            console.print("[dim]Cancelled.[/dim]")
            return state
        # Redraw: clear the panel (print empty lines to push old content up)
        console.print()


# ═══════════════════════════════════════════════════════════════
# ── END v5.7 NEW FEATURES ─────────────────────────────────────
# ═══════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════
# ── v5.8 NEW FEATURES ─────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════

_PRO_PLANS = ("max", "ultra", "enterprise", "team")

def _require_pro(state, feature="This feature"):
    """Print gate message and return False if user isn't on a Pro plan."""
    plan = get_plan(state)
    if plan not in _PRO_PLANS:
        cfg  = PLANS.get(plan, PLANS["free"])
        console.print(Panel(
            f"  [bold]{feature}[/bold] is available on [bold magenta]Max[/bold magenta],"
            f" [bold yellow]Ultra[/bold yellow], or [bold white]Enterprise[/bold white] plans.\n\n"
            f"  You're on [{cfg['color']}]{cfg['badge']} {cfg['name']}[/{cfg['color']}].\n\n"
            f"  [dim]/upgrade max    →  $80/mo\n"
            f"  /upgrade ultra   →  $250/mo\n"
            f"  /upgrade enterprise → negotiate[/dim]",
            title="Pro Feature", border_style="magenta", padding=(0, 2)
        ))
        return False
    return True


VAULT_FILE    = CONFIG_DIR / "vault.json"
VAULT_KEY_FILE = CONFIG_DIR / "vault_key"

def _vault_fernet():
    """Return a Fernet instance keyed from vault_key, or None if cryptography not installed."""
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        return None
    if not VAULT_KEY_FILE.exists():
        key = Fernet.generate_key()
        VAULT_KEY_FILE.parent.mkdir(exist_ok=True)
        VAULT_KEY_FILE.write_bytes(key)
        VAULT_KEY_FILE.chmod(0o600)
    else:
        key = VAULT_KEY_FILE.read_bytes().strip()
    return Fernet(key)

def _vault_load():
    if not VAULT_FILE.exists(): return {}
    import base64
    try:
        raw = json.loads(VAULT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    f = _vault_fernet()
    result = {}
    for k, v in raw.items():
        try:
            if f and v.startswith("fernet:"):
                result[k] = f.decrypt(v[7:].encode()).decode("utf-8")
            else:
                result[k] = base64.b64decode(v).decode("utf-8")
        except Exception:
            result[k] = v
    return result

def _vault_save(data):
    import base64
    f = _vault_fernet()
    encoded = {}
    for k, v in data.items():
        if f:
            encoded[k] = "fernet:" + f.encrypt(v.encode("utf-8")).decode("utf-8")
        else:
            encoded[k] = base64.b64encode(v.encode("utf-8")).decode("utf-8")
    VAULT_FILE.parent.mkdir(exist_ok=True)
    VAULT_FILE.write_text(json.dumps(encoded, indent=2), encoding="utf-8")

def _vault_encrypted():
    """True if Fernet encryption is available."""
    try:
        from cryptography.fernet import Fernet  # noqa: F401
        return True
    except ImportError:
        return False


def cmd_vault(state, args):
    """/vault — Local secrets store. /vault set KEY VALUE | /vault get KEY | /vault list | /vault delete KEY"""
    if not _require_pro(state, "/vault"): return
    theme  = state.get("theme", THEMES["default"])
    acc    = theme.get("accent", "cyan")
    if _vault_encrypted():
        console.print("[green bold]🔒 Vault:[/green bold] [dim]secrets encrypted with Fernet (AES-128-CBC).[/dim]")
    else:
        console.print(
            "[yellow bold]⚠ Vault notice:[/yellow bold] [dim]secrets are "
            "[bold]base64-encoded (obfuscated)[/bold] — install [cyan]cryptography[/cyan] "
            "for real encryption: [cyan]pip install cryptography[/cyan][/dim]"
        )
    parts  = (args or "").split(None, 2)
    action = parts[0].lower() if parts else ""
    vault  = _vault_load()

    if action == "set":
        if len(parts) < 3:
            console.print("[yellow]Usage: /vault set KEY VALUE[/yellow]")
            return
        key, val = parts[1], parts[2]
        vault[key] = val
        _vault_save(vault)
        enc_note = "Fernet-encrypted" if _vault_encrypted() else "base64-encoded (install cryptography for encryption)"
        console.print(f"  [{acc}]✓ Vault: {key} saved[/{acc}]  [dim]({enc_note})[/dim]")

    elif action == "get":
        if len(parts) < 2:
            console.print("[yellow]Usage: /vault get KEY[/yellow]")
            return
        key = parts[1]
        val = vault.get(key)
        if val is None:
            console.print(f"[yellow]Key '{key}' not found in vault.[/yellow]")
        else:
            console.print(Panel(
                f"  [bold]{key}[/bold]\n  [dim]{val}[/dim]",
                title="Vault Secret", border_style=acc, padding=(0, 2)
            ))

    elif action == "delete":
        if len(parts) < 2:
            console.print("[yellow]Usage: /vault delete KEY[/yellow]")
            return
        key = parts[1]
        if key in vault:
            del vault[key]
            _vault_save(vault)
            console.print(f"  [{acc}]✓ Deleted: {key}[/{acc}]")
        else:
            console.print(f"[yellow]Key '{key}' not found.[/yellow]")

    elif action == "list" or not action:
        if not vault:
            console.print("[dim]Vault is empty. /vault set KEY VALUE[/dim]")
            return
        tbl = Table(title="Vault Secrets", box=box.ROUNDED, border_style=acc)
        tbl.add_column("Key",    style="bold cyan", min_width=16)
        tbl.add_column("Value",  style="dim")
        for k, v in vault.items():
            hidden = v[:4] + "•" * min(8, len(v) - 4) if len(v) > 4 else "••••"
            tbl.add_row(k, hidden)
        console.print(tbl)
        console.print("[dim]/vault get KEY to reveal · /vault delete KEY to remove[/dim]")

    else:
        console.print("[yellow]Usage: /vault set|get|delete|list[/yellow]")


TEAM_FILE = CONFIG_DIR / "team.json"

def _team_load():
    if not TEAM_FILE.exists(): return []
    try:
        return json.loads(TEAM_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []

def _team_save(members):
    TEAM_FILE.parent.mkdir(exist_ok=True)
    TEAM_FILE.write_text(json.dumps(members, indent=2), encoding="utf-8")


def cmd_team(state, args):
    """/team — Pro team management: list, invite, remove members, set roles."""
    if not _require_pro(state, "/team"): return
    theme  = state.get("theme", THEMES["default"])
    acc    = theme.get("accent", "cyan")
    parts  = (args or "").split(None, 2)
    action = parts[0].lower() if parts else ""
    members = _team_load()

    if not action or action == "list":
        if not members:
            console.print(Panel(
                "  No team members yet.\n\n"
                "  [dim]/team invite <email> [role]   — add a member\n"
                "  /team remove <email>            — remove a member\n"
                "  /team role <email> <role>       — change role[/dim]",
                title="Team", border_style=acc, padding=(0, 2)
            ))
            return
        tbl = Table(title="Team Members", box=box.ROUNDED, border_style=acc, show_lines=True)
        tbl.add_column("Email",      style="cyan",    min_width=24)
        tbl.add_column("Role",       style="yellow",  width=12)
        tbl.add_column("Joined",     style="dim",     width=12)
        tbl.add_column("Status",     width=10)
        for m in members:
            status = "[green]● active[/green]" if m.get("active", True) else "[dim]○ inactive[/dim]"
            tbl.add_row(m.get("email","?"), m.get("role","member"),
                        m.get("joined","?")[:10], status)
        console.print(tbl)
        console.print(f"  [dim]{len(members)} member(s) · /team invite <email> to add more[/dim]")

    elif action == "invite":
        if len(parts) < 2:
            console.print("[yellow]Usage: /team invite <email> [role][/yellow]")
            return
        email = parts[1]
        role  = parts[2] if len(parts) > 2 else "member"
        if any(m.get("email") == email for m in members):
            console.print(f"[yellow]{email} is already on the team.[/yellow]")
            return
        members.append({"email": email, "role": role, "joined": datetime.now().isoformat(), "active": True})
        _team_save(members)
        console.print(f"  [{acc}]✓ Invited {email} as {role}[/{acc}]")
        console.print(f"  [dim]They'll receive an invitation email (requires backend). Ref stored locally.[/dim]")

    elif action == "remove":
        if len(parts) < 2:
            console.print("[yellow]Usage: /team remove <email>[/yellow]")
            return
        email  = parts[1]
        before = len(members)
        members = [m for m in members if m.get("email") != email]
        if len(members) == before:
            console.print(f"[yellow]{email} not found in team.[/yellow]")
            return
        _team_save(members)
        console.print(f"  [{acc}]✓ Removed {email}[/{acc}]")

    elif action == "role":
        if len(parts) < 3:
            console.print("[yellow]Usage: /team role <email> <role>[/yellow]")
            return
        email, new_role = parts[1], parts[2]
        updated = False
        for m in members:
            if m.get("email") == email:
                m["role"] = new_role
                updated = True
                break
        if not updated:
            console.print(f"[yellow]{email} not found.[/yellow]")
            return
        _team_save(members)
        console.print(f"  [{acc}]✓ {email} → {new_role}[/{acc}]")

    elif action == "export":
        if not members:
            console.print("[yellow]No team members to export.[/yellow]")
            return
        ws = state.get("workspace_root") or str(Path.cwd())
        out_path = Path(ws) / "team_export.json"
        try:
            out_path.write_text(json.dumps(members, indent=2), encoding="utf-8")
            console.print(Panel(
                f"  [bold]Exported {len(members)} member(s)[/bold]\n"
                f"  [cyan]{out_path}[/cyan]",
                title="✓ Team Export", border_style=acc, padding=(0, 2)
            ))
        except Exception as e:
            console.print(f"[red]Export failed: {e}[/red]")

    else:
        console.print("[yellow]Usage: /team list|invite|remove|role|export[/yellow]")


# ═══════════════════════════════════════════════════════════════
# ── v5.9 MAX / TEAM / ENTERPRISE FEATURES ─────────────────────
# ═══════════════════════════════════════════════════════════════

_MAX_TIER_PLANS  = ("max", "ultra", "team", "enterprise")
_TEAM_TIER_PLANS = ("team", "enterprise")
_ENTERPRISE_ONLY = ("enterprise",)

ORG_POLICY_FILE     = CONFIG_DIR / "org_policy.json"
ORG_SSO_FILE        = CONFIG_DIR / "org_sso.json"
PRIORITY_QUEUE_FILE = CONFIG_DIR / "priority_queue"


def _require_tier(state, allowed, label, suggested="/upgrade max"):
    """Generic tier gate. `allowed` is a tuple of plan ids that may use the feature."""
    plan = get_plan(state)
    if plan in allowed:
        return True
    cfg  = PLANS.get(plan, PLANS["free"])
    pretty = " / ".join(PLANS[a]["name"] for a in allowed)
    console.print(Panel(
        f"  [bold]{label}[/bold] is available on [bold magenta]{pretty}[/bold magenta].\n\n"
        f"  You're on [{cfg['color']}]{cfg['badge']} {cfg['name']}[/{cfg['color']}].\n\n"
        f"  [dim]Try {suggested} to unlock.[/dim]",
        title="Plan Required", border_style="magenta", padding=(0, 2)
    ))
    return False


def cmd_audit_log(state, args):
    """/audit-log — Max+: view the local audit trail with optional filter."""
    if not _require_tier(state, _MAX_TIER_PLANS, "/audit-log"):
        return
    theme = state.get("theme", THEMES["default"])
    acc   = theme.get("accent", "cyan")
    path  = Path("logs/audit.json")
    if not path.exists():
        console.print(Panel(
            "  No audit events recorded yet.\n"
            "  [dim]Login, plan changes, and security alerts will appear here.[/dim]",
            title="Audit Log", border_style=acc, padding=(0, 2)))
        return
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        console.print("[red]Audit log is corrupt or unreadable.[/red]")
        return
    flt = (args or "").strip().lower()
    if flt:
        entries = [e for e in entries
                   if flt in str(e.get("type","")).lower()
                   or flt in str(e.get("details","")).lower()]
    entries = entries[-50:]
    if not entries:
        console.print(f"[yellow]No audit events match '{flt}'.[/yellow]")
        return
    tbl = Table(title=f"Audit Log  ·  last {len(entries)}", box=box.ROUNDED,
                border_style=acc, show_lines=False)
    tbl.add_column("When",  style="dim",    width=19)
    tbl.add_column("Type",  style="yellow", width=18)
    tbl.add_column("Details")
    for e in entries:
        ts = e.get("ts", 0)
        try:    when = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except Exception: when = str(ts)
        tbl.add_row(when, str(e.get("type","?")), str(e.get("details",""))[:80])
    console.print(tbl)
    console.print(f"  [dim]Filter: /audit-log <text>   ·   File: {path}[/dim]")


def cmd_priority_queue(state, args):
    """/priority-queue — Max+: toggle priority API queue routing."""
    if not _require_tier(state, _MAX_TIER_PLANS, "/priority-queue"):
        return
    sub = (args or "").strip().lower()
    current = PRIORITY_QUEUE_FILE.exists()
    if sub in ("on", "enable", "true", "1"):
        PRIORITY_QUEUE_FILE.parent.mkdir(exist_ok=True)
        PRIORITY_QUEUE_FILE.write_text("on", encoding="utf-8")
        state["priority_queue"] = True
        console.print("[green]✓ Priority queue ENABLED — your requests will be routed ahead of free traffic.[/green]")
        return
    if sub in ("off", "disable", "false", "0"):
        PRIORITY_QUEUE_FILE.unlink(missing_ok=True)
        state["priority_queue"] = False
        console.print("[yellow]✓ Priority queue DISABLED.[/yellow]")
        return
    state["priority_queue"] = current
    status = "[green]ON[/green]" if current else "[dim]OFF[/dim]"
    console.print(Panel(
        f"  Priority queue: {status}\n\n"
        f"  [dim]Routes your API calls into the high-priority lane,\n"
        f"  ahead of free-tier traffic during peak load.[/dim]\n\n"
        f"  Toggle: [yellow]/priority-queue on[/yellow] · [yellow]/priority-queue off[/yellow]",
        title="Priority Queue (Max+)", border_style="magenta", padding=(0, 2)))


def cmd_orgmetrics(state, args):
    """/orgmetrics — Team/Enterprise: aggregate metrics across all profile users."""
    if not _require_tier(state, _TEAM_TIER_PLANS, "/orgmetrics", suggested="/upgrade team"):
        return
    theme = state.get("theme", THEMES["default"])
    acc   = theme.get("accent", "cyan")
    profiles_dir = Path("profiles")
    if not profiles_dir.exists():
        console.print("[yellow]No profiles found yet.[/yellow]")
        return
    members      = []
    total_msgs   = 0
    total_in     = 0
    total_out    = 0
    plan_counts  = {}
    model_totals = {}
    for d in profiles_dir.iterdir():
        if not d.is_dir(): continue
        f = d / "profile.json"
        if not f.exists(): continue
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        members.append(p)
        total_msgs += int(p.get("total_msgs", 0) or 0)
        total_in   += int(p.get("total_tokens_in", 0) or 0)
        total_out  += int(p.get("total_tokens_out", 0) or 0)
        plan_counts[p.get("plan","free")] = plan_counts.get(p.get("plan","free"), 0) + 1
        for m, c in (p.get("model_usage") or {}).items():
            model_totals[m] = model_totals.get(m, 0) + int(c or 0)
    if not members:
        console.print("[yellow]No member profiles to aggregate.[/yellow]")
        return
    plan_str = "  ".join(
        f"[{PLANS.get(p, PLANS['free'])['color']}]{PLANS.get(p, PLANS['free'])['badge']} {p}: {n}[/{PLANS.get(p, PLANS['free'])['color']}]"
        for p, n in sorted(plan_counts.items(), key=lambda x: -x[1]))
    top_models = sorted(model_totals.items(), key=lambda x: -x[1])[:5]
    model_str  = "\n".join(f"  [bold]{m:<32}[/bold]  {c}×" for m, c in top_models) or "  [dim](no usage yet)[/dim]"
    console.print(Panel(
        f"  [bold]Members[/bold]         {len(members)}\n"
        f"  [bold]Total messages[/bold]  {total_msgs:,}\n"
        f"  [bold]Tokens in[/bold]       {total_in:,}\n"
        f"  [bold]Tokens out[/bold]      {total_out:,}\n\n"
        f"  [bold]Plan mix[/bold]        {plan_str}\n\n"
        f"  [bold]Top models[/bold]\n{model_str}",
        title="Organization Metrics", border_style=acc, padding=(1, 2)))


def cmd_sso(state, args):
    """/sso — Enterprise: configure SSO/SAML/OIDC settings."""
    if not _require_tier(state, _ENTERPRISE_ONLY, "/sso", suggested="/upgrade enterprise"):
        return
    theme = state.get("theme", THEMES["default"])
    acc   = theme.get("accent", "cyan")
    parts = (args or "").split(None, 2)
    action = parts[0].lower() if parts else ""
    cfg = {}
    if ORG_SSO_FILE.exists():
        try: cfg = json.loads(ORG_SSO_FILE.read_text(encoding="utf-8"))
        except Exception: cfg = {}

    if not action or action == "show":
        if not cfg:
            console.print(Panel(
                "  No SSO configured yet.\n\n"
                "  [dim]/sso set provider <okta|azure|google|generic-oidc>\n"
                "  /sso set issuer <url>\n"
                "  /sso set client_id <id>\n"
                "  /sso set client_secret <secret>\n"
                "  /sso enable | /sso disable[/dim]",
                title="SSO / SAML", border_style=acc, padding=(0, 2)))
            return
        masked = dict(cfg)
        if "client_secret" in masked and masked["client_secret"]:
            masked["client_secret"] = "•" * 8 + masked["client_secret"][-4:]
        body = "\n".join(f"  [bold]{k:<14}[/bold] {v}" for k, v in masked.items())
        console.print(Panel(body, title="SSO Configuration", border_style=acc, padding=(0, 2)))
        return

    if action == "set":
        if len(parts) < 3:
            console.print("[yellow]Usage: /sso set <key> <value>[/yellow]")
            return
        key, value = parts[1].lower(), parts[2]
        if key not in ("provider", "issuer", "client_id", "client_secret", "redirect_uri"):
            console.print(f"[yellow]Unknown key '{key}'. Allowed: provider/issuer/client_id/client_secret/redirect_uri[/yellow]")
            return
        cfg[key] = value
        ORG_SSO_FILE.parent.mkdir(exist_ok=True)
        ORG_SSO_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        audit_log("SSO_CONFIG", f"{key} updated")
        console.print(f"  [{acc}]✓ {key} updated[/{acc}]")
        return

    if action in ("enable", "disable"):
        cfg["enabled"] = (action == "enable")
        ORG_SSO_FILE.parent.mkdir(exist_ok=True)
        ORG_SSO_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        audit_log("SSO_TOGGLE", action)
        console.print(f"  [{acc}]✓ SSO {action}d[/{acc}]")
        return

    console.print("[yellow]Usage: /sso show | set <key> <value> | enable | disable[/yellow]")


def cmd_policy(state, args):
    """/policy — Enterprise: org-wide policies (max tokens, allowed models, content filter)."""
    if not _require_tier(state, _ENTERPRISE_ONLY, "/policy", suggested="/upgrade enterprise"):
        return
    theme = state.get("theme", THEMES["default"])
    acc   = theme.get("accent", "cyan")
    parts = (args or "").split(None, 2)
    action = parts[0].lower() if parts else ""
    pol = {}
    if ORG_POLICY_FILE.exists():
        try: pol = json.loads(ORG_POLICY_FILE.read_text(encoding="utf-8"))
        except Exception: pol = {}

    if not action or action == "show":
        if not pol:
            console.print(Panel(
                "  No org policy set.\n\n"
                "  [dim]/policy set max_tokens 4000\n"
                "  /policy set allowed_models gpt-oss-120b,nemotron\n"
                "  /policy set content_filter strict|standard|off\n"
                "  /policy clear <key>[/dim]",
                title="Org Policy", border_style=acc, padding=(0, 2)))
            return
        body = "\n".join(f"  [bold]{k:<18}[/bold] {v}" for k, v in pol.items())
        console.print(Panel(body, title="Org Policy", border_style=acc, padding=(0, 2)))
        return

    if action == "set":
        if len(parts) < 3:
            console.print("[yellow]Usage: /policy set <key> <value>[/yellow]")
            return
        key, value = parts[1].lower(), parts[2]
        if key == "max_tokens":
            try: value = int(value)
            except ValueError:
                console.print("[red]max_tokens must be an integer.[/red]"); return
        elif key == "allowed_models":
            value = [m.strip() for m in value.split(",") if m.strip()]
        elif key == "content_filter" and value not in ("strict", "standard", "off"):
            console.print("[red]content_filter must be strict|standard|off[/red]"); return
        pol[key] = value
        ORG_POLICY_FILE.parent.mkdir(exist_ok=True)
        ORG_POLICY_FILE.write_text(json.dumps(pol, indent=2), encoding="utf-8")
        audit_log("POLICY_UPDATE", f"{key}={value}")
        console.print(f"  [{acc}]✓ Policy {key} → {value}[/{acc}]")
        return

    if action == "clear":
        if len(parts) < 2:
            console.print("[yellow]Usage: /policy clear <key>[/yellow]")
            return
        key = parts[1].lower()
        if key in pol:
            del pol[key]
            ORG_POLICY_FILE.write_text(json.dumps(pol, indent=2), encoding="utf-8")
            audit_log("POLICY_CLEAR", key)
            console.print(f"  [{acc}]✓ Cleared {key}[/{acc}]")
        else:
            console.print(f"[yellow]No policy '{key}' to clear.[/yellow]")
        return

    console.print("[yellow]Usage: /policy show | set <key> <value> | clear <key>[/yellow]")


PLUGIN_FILE = CONFIG_DIR / "plugins.json"

def _load_plugins():
    try:
        if PLUGIN_FILE.exists():
            return json.loads(PLUGIN_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []

def _save_plugins(plugins):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    PLUGIN_FILE.write_text(json.dumps(plugins, indent=2), encoding="utf-8")


def cmd_plugin(state, args):
    """/plugin list|add <name> <url>|remove <name> — v9 plugin system (pro)."""
    if not _require_pro(state, "/plugin"):
        return
    theme = state.get("theme", THEMES["default"])
    acc   = theme.get("accent", "cyan")
    parts = (args or "").split(None, 2)
    action = parts[0].lower() if parts else "list"

    plugins = _load_plugins()

    if action == "list" or not action:
        if not plugins:
            console.print(Panel(
                "  No plugins installed.\n\n"
                "  [dim]/plugin add <name> <url>   — register a plugin endpoint\n"
                "  /plugin remove <name>        — uninstall\n"
                "  /plugin list                 — show installed[/dim]",
                title="[bold]Plugins[/bold]", border_style=theme.get("border","cyan"), padding=(0,2)
            ))
            return
        tbl = Table(title="Installed Plugins", box=box.SIMPLE, border_style=acc)
        tbl.add_column("Name", style="bold")
        tbl.add_column("URL")
        tbl.add_column("Status")
        for p in plugins:
            tbl.add_row(p["name"], p.get("url","—"), "[green]active[/green]")
        console.print(tbl)

    elif action == "add":
        if len(parts) < 3:
            console.print("[yellow]Usage: /plugin add <name> <url>[/yellow]"); return
        name, url = parts[1], parts[2]
        if any(p["name"] == name for p in plugins):
            console.print(f"[yellow]Plugin '{name}' already installed.[/yellow]"); return
        plugins.append({"name": name, "url": url, "added": datetime.now().isoformat()})
        _save_plugins(plugins)
        console.print(f"  [{acc}]✓ Plugin '{name}' installed.[/{acc}]")

    elif action in ("remove", "rm", "uninstall"):
        if len(parts) < 2:
            console.print("[yellow]Usage: /plugin remove <name>[/yellow]"); return
        name = parts[1]
        before = len(plugins)
        plugins = [p for p in plugins if p["name"] != name]
        if len(plugins) == before:
            console.print(f"[yellow]Plugin '{name}' not found.[/yellow]"); return
        _save_plugins(plugins)
        console.print(f"  [{acc}]✓ Plugin '{name}' removed.[/{acc}]")
    else:
        console.print("[yellow]Usage: /plugin list | add <name> <url> | remove <name>[/yellow]")


def cmd_agent_mesh(state, args, history):
    """/agent-mesh <task> — broadcast task to all available agents simultaneously (pro)."""
    if not _require_pro(state, "/agent-mesh"):
        return history
    if not args:
        console.print("[yellow]Usage: /agent-mesh <task>[/yellow]"); return history
    theme  = state.get("theme", THEMES["default"])
    acc    = theme.get("accent", "cyan")
    agents_ids = list(AGENT_ROSTER.keys())
    task   = args.strip()
    console.print(f"\n[bold {acc}]⬡  AGENT MESH  ⬡[/bold {acc}]  [dim]{len(agents_ids)} agents · broadcasting…[/dim]\n")
    results = {}
    lock    = threading.Lock()
    errors  = {}

    def _run_agent(aid):
        spec = AGENT_ROSTER.get(aid, {})
        name = spec.get("name", aid)
        role = spec.get("role", "Agent")
        persona_sys = PERSONAS.get(spec.get("persona_key", "default"), PERSONAS["default"])
        sys_p = persona_sys.get("system", "") if isinstance(persona_sys, dict) else str(persona_sys)
        prompt = f"[{role}] {task}"
        try:
            txt, _ = ai_respond(dict(state, system_prompt=sys_p), prompt, [])
            with lock:
                results[aid] = (name, role, txt or "")
        except Exception as exc:
            with lock:
                errors[aid] = str(exc)

    threads = [threading.Thread(target=_run_agent, args=(aid,), daemon=True) for aid in agents_ids[:6]]
    for t in threads: t.start()
    for t in threads: t.join(timeout=30)

    for aid in agents_ids[:6]:
        if aid in results:
            name, role, txt = results[aid]
            spec = AGENT_ROSTER.get(aid, {})
            color = spec.get("color", acc)
            console.print(Panel(
                Markdown(txt[:600] + ("…" if len(txt) > 600 else "")),
                title=f"[{color}]{spec.get('emoji','')} {name}[/{color}] [dim]{role}[/dim]",
                border_style=color.replace("bold ",""), padding=(0,1)
            ))
    return history


def cmd_vision_pro(state, args, history):
    """/vision-pro <image_path> [prompt] — enhanced image analysis (pro)."""
    if not _require_pro(state, "/vision-pro"):
        return history
    theme = state.get("theme", THEMES["default"])
    acc   = theme.get("accent", "cyan")
    if not args:
        console.print("[yellow]Usage: /vision-pro <image_path> [prompt][/yellow]"); return history
    parts = args.split(None, 1)
    img_path = Path(parts[0])
    prompt   = parts[1] if len(parts) > 1 else "Describe this image in detail."
    if not img_path.exists():
        console.print(f"[red]File not found: {img_path}[/red]"); return history
    try:
        import base64
        img_b64 = base64.b64encode(img_path.read_bytes()).decode()
        ext = img_path.suffix.lower().lstrip(".")
        mime_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                    "gif": "image/gif", "webp": "image/webp"}
        mime = mime_map.get(ext, "image/png")
        console.print(f"  [{acc}]🔍 Analysing {img_path.name}…[/{acc}]")
        vision_msg = [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}},
            {"type": "text", "text": prompt},
        ]}]
        or_key = state.get("openrouter_key") or load_or_key()
        if not or_key:
            console.print("[yellow]OpenRouter key required for vision.[/yellow]"); return history
        vision_model = "google/gemini-2.0-flash-001"
        result, _ = call_openrouter(or_key, vision_model, vision_msg, "", "")
        console.print(Panel(Markdown(result or "No response."),
                            title=f"[bold]Vision Analysis — {img_path.name}[/bold]",
                            border_style=theme.get("border","cyan"), padding=(0,1)))
        history.append({"role": "user", "text": f"[vision: {img_path.name}] {prompt}"})
        history.append({"role": "model", "text": result or ""})
    except Exception as exc:
        console.print(f"[red]Vision error: {exc}[/red]")
    return history


def cmd_whats_new(state):
    """/whats-new — show what's new in the current version."""
    theme = state.get("theme", THEMES["default"])
    acc   = theme.get("accent", "cyan")
    plan_id  = get_plan(state)
    plan_cfg = PLANS.get(plan_id, PLANS["free"])
    tier_label = plan_cfg.get("tier", "v8+")
    body = (
        f"  [bold]StudioCLI v{VERSION}[/bold]  [{acc}]{tier_label}[/{acc}]\n\n"
        f"  [{acc}]v8.0[/{acc}]  [dim]──────────────────────────────────────────[/dim]\n"
        "  [bold green]✦[/bold green] [bold]4 new themes[/bold]: cobalt, carbon, crimson, slate   [dim](/theme <name>[/dim])\n"
        "  [bold green]✦[/bold green] [bold]4 new vibe presets[/bold]: cobalt, carbon, crimson, slate  [dim](/vibe <name>[/dim])\n"
        "  [bold green]✦[/bold green] [bold]/snapshot[/bold]: export current session to JSON\n"
        "  [bold green]✦[/bold green] [bold]/open-web[/bold]: launch web UI in browser\n"
        "  [bold green]✦[/bold green] [bold]/tip[/bold]: random power-user tip\n"
        "  [bold green]✦[/bold green] [bold]/speed[/bold]: toggle low-latency stream mode\n"
        "  [bold green]✦[/bold green] Plan tiers: v8+ (free) · v9 (pro) · v9+ (max) · v9 Beta (ultra)\n"
        f"\n  [{acc}]v9.0[/{acc}]  [dim]──────────────────────────────────────────[/dim]\n"
        "  [bold cyan]✦[/bold cyan] [bold]/plugin list|add|remove[/bold]: plugin management  [dim](pro)[/dim]\n"
        "  [bold cyan]✦[/bold cyan] [bold]/agent-mesh[/bold]: multi-agent parallel tasks  [dim](pro)[/dim]\n"
        "  [bold cyan]✦[/bold cyan] [bold]/vision-pro[/bold]: enhanced image analysis  [dim](pro)[/dim]\n"
        "  [bold cyan]✦[/bold cyan] [bold]/template[/bold]: save & reuse prompt templates  [dim](pro)[/dim]\n"
        f"\n  [{acc}]v9 Beta[/{acc}]  [dim]──────────────────────────────────────────[/dim]\n"
        "  [bold yellow]✦[/bold yellow] [bold]/voice[/bold]: voice-to-text input  [dim](ultra)[/dim]\n"
        "  [bold yellow]✦[/bold yellow] [bold]/mesh-broadcast[/bold]: broadcast to all agents  [dim](ultra)[/dim]\n"
        "  [bold yellow]✦[/bold yellow] [bold]/analytics-pro[/bold]: advanced usage dashboard  [dim](ultra)[/dim]\n"
        "\n  [dim]/changelog · /plan · /upgrade[/dim]"
    )
    console.print(Panel(body, title=f"[bold]What's New — v{VERSION}[/bold]",
                        border_style=theme.get("border", "cyan"), padding=(0, 2)))


def cmd_snapshot(state, args, history):
    """/snapshot [filename] — export current session (history + context) to JSON."""
    theme = state.get("theme", THEMES["default"])
    acc   = theme.get("accent", "cyan")
    ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = (args.strip() if args else None) or f"snapshot_{ts}.json"
    if not fname.endswith(".json"):
        fname += ".json"
    snap = {
        "version":   VERSION,
        "timestamp": datetime.now().isoformat(),
        "model":     state.get("model", DEFAULT_MODEL),
        "persona":   state.get("persona", "default"),
        "ui_style":  state.get("ui_style", "gemini"),
        "theme":     state.get("theme", {}).get("name", "default"),
        "workspace": str(state.get("workspace_root", "")),
        "messages":  len(history),
        "history":   history,
        "memory":    load_memory(),
    }
    try:
        out = Path(fname)
        out.write_text(json.dumps(snap, indent=2, ensure_ascii=False), encoding="utf-8")
        console.print(Panel(
            f"  [{acc}]✓ Snapshot saved[/{acc}]\n\n"
            f"  [bold]File:[/bold]  {out.resolve()}\n"
            f"  [bold]Messages:[/bold] {len(history)}\n"
            f"  [bold]Memory:[/bold]  {len(snap['memory'])} entries",
            title="[bold]Session Snapshot[/bold]",
            border_style=theme.get("border", "cyan"), padding=(0, 2)
        ))
    except Exception as exc:
        console.print(f"[red]Snapshot failed: {exc}[/red]")
    return history


def cmd_open_web(state, args):
    """/open-web [port] — open StudioCLI web UI in default browser."""
    theme = state.get("theme", THEMES["default"])
    acc   = theme.get("accent", "cyan")
    port  = args.strip() if args else "3456"
    try:
        port_n = int(port)
    except ValueError:
        port_n = 3456
    url = f"http://localhost:{port_n}"
    try:
        webbrowser.open(url)
        console.print(f"  [{acc}]✦ Opening {url} in your browser…[/{acc}]")
    except Exception as exc:
        console.print(f"[yellow]Could not open browser: {exc}[/yellow]")
        console.print(f"  Open manually: [bold cyan]{url}[/bold cyan]")


_TIPS = [
    "/vibe chatgpt      → dark minimal mode matching the web UI",
    "/arena same        → compare same model at low vs pro effort",
    "/memory            → see what the AI remembers about you",
    "/fif               → find-it-fix: paste an error, auto-fix it",
    "/snapshot          → export entire session to JSON",
    "/theme cobalt      → new cobalt theme — cool blue terminal",
    "Ctrl+L             → clear screen and redraw welcome",
    "/multi m1,m2 <q>   → query two models simultaneously",
    "/thinking on       → enable extended reasoning for next reply",
    "/autonomous        → let the AI write files without asking",
    "/broadcast         → send a message to all active agents",
    "Shift+Enter        → multi-line input in the REPL",
    "/export            → export conversation history to markdown",
    "/compare m1 m2     → side-by-side model comparison",
    "/vibe foxxia       → 🦊 Foxxia dark mode with amber accent",
    "/beta list         → see all v9 Beta experimental feature flags (ultra)",
    "/analytics-pro     → advanced usage dashboard with token breakdown (ultra)",
    "/mesh-broadcast    → blast a prompt to every active agent simultaneously",
    "/voice start       → voice-to-text input (requires pyaudio, ultra)",
    "/labs              → alias for /beta — manage experimental features",
]

def cmd_tip(state, args):
    """/tip — show a random power-user tip."""
    import random
    theme = state.get("theme", THEMES["default"])
    acc   = theme.get("accent", "cyan")
    tip   = random.choice(_TIPS)
    cmd_part, _, desc_part = tip.partition("→")
    console.print(
        Panel(f"  [{acc}]{cmd_part.strip()}[/{acc}]  [dim]→[/dim]  {desc_part.strip()}",
              title="[bold]💡 Pro Tip[/bold]",
              border_style=theme.get("border","cyan"), padding=(0,2))
    )


def cmd_speed(state, args):
    """/speed [on|off] — toggle low-latency mode (stream=on, effort=low)."""
    theme = state.get("theme", THEMES["default"])
    acc   = theme.get("accent", "cyan")
    mode  = (args.strip().lower() if args else "")
    current_stream = state.get("stream_mode", "auto")
    if mode == "on" or (not mode and current_stream != "on"):
        state = cmd_stream(state, "on")
        state["effort"] = "low"
        state["fast_mode"] = True
        console.print(f"  [{acc}]⚡ Speed mode ON[/{acc}]  [dim]stream=on · effort=low · fast=on[/dim]")
    else:
        state = cmd_stream(state, "auto")
        state["effort"] = "medium"
        state["fast_mode"] = False
        console.print(f"  [{acc}]✓ Speed mode OFF[/{acc}]  [dim]stream=auto · effort=medium · fast=off[/dim]")
    return state


# ── /fast ─────────────────────────────────────────────────────────────────────
def cmd_fast(state, args):
    """/fast [on|off] — toggle fast/concise mode (≤80-word replies, 512-token cap)."""
    theme = state.get("theme", THEMES["default"])
    acc   = theme.get("accent", "cyan")
    mode  = (args.strip().lower() if args else "")
    if mode == "off" or (not mode and state.get("fast_mode")):
        state["fast_mode"] = False
        console.print(f"  [{acc}]✓ Fast mode OFF[/{acc}]  [dim]full replies restored[/dim]")
    else:
        state["fast_mode"] = True
        console.print(f"  [{acc}]⚡ Fast mode ON[/{acc}]  [dim]≤80 words · 512 token cap[/dim]")
    return state


# ── /thinking ─────────────────────────────────────────────────────────────────
def cmd_thinking(state, args):
    """/thinking [<seconds>|on|off|show|hide] — AI reasoning budget + display toggle."""
    theme = state.get("theme", THEMES["default"])
    acc   = theme.get("accent", "cyan")
    a     = args.strip().lower() if args else ""

    if a in ("off", "0"):
        state["thinking_budget"] = 0
        state["show_thinking"]   = False
        console.print(f"  [yellow]✓ Thinking OFF[/yellow]  [dim]reasoning disabled[/dim]")
    elif a in ("on",):
        state["thinking_budget"] = 8000   # ~16 s of reasoning budget
        state["show_thinking"]   = True
        console.print(f"  [{acc}]◈ Thinking ON[/{acc}]  [dim]budget=8000 tokens · display=on[/dim]")
    elif a == "show":
        state["show_thinking"] = True
        console.print(f"  [{acc}]◈ Thinking display ON[/{acc}]")
    elif a == "hide":
        state["show_thinking"] = False
        console.print(f"  [yellow]◇ Thinking display OFF[/yellow]  [dim]reasoning hidden[/dim]")
    elif a:
        # Parse seconds (e.g. "10", "30s", "2m")
        a_clean = a.rstrip("s")
        if a_clean.endswith("m"):
            try:
                secs = int(a_clean[:-1]) * 60
            except ValueError:
                console.print(f"[red]Usage: /thinking <seconds|Xs|Xm|on|off|show|hide>[/red]")
                return state
        else:
            try:
                secs = int(a_clean)
            except ValueError:
                console.print(f"[red]Usage: /thinking <seconds|Xs|Xm|on|off|show|hide>[/red]")
                return state
        # ~500 tokens per second of reasoning is a rough heuristic
        budget = max(1000, secs * 500)
        state["thinking_budget"] = budget
        state["show_thinking"]   = True
        console.print(f"  [{acc}]◈ Thinking → {secs}s[/{acc}]  [dim]budget_tokens={budget}[/dim]")
    else:
        # Show current state
        budget = state.get("thinking_budget", 0)
        show   = state.get("show_thinking", True)
        secs   = budget // 500 if budget else 0
        console.print(Panel(
            f"  Budget:   [bold]{budget}[/bold] tokens (~{secs}s)  "
            f"({'[green]active[/green]' if budget else '[dim]off[/dim]'})\n"
            f"  Display:  {'[green]on[/green]' if show else '[yellow]off[/yellow]'}\n\n"
            f"  [dim]/thinking on     → enable (8000 token budget)[/dim]\n"
            f"  [dim]/thinking 30     → 30-second budget[/dim]\n"
            f"  [dim]/thinking off    → disable[/dim]\n"
            f"  [dim]/thinking show   → show reasoning stream[/dim]\n"
            f"  [dim]/thinking hide   → hide reasoning stream[/dim]",
            title="◈ Thinking / Reasoning", border_style=theme.get("border","cyan")))
    return state


# ── /time ─────────────────────────────────────────────────────────────────────
def _parse_duration(s):
    """Parse '30m', '2h', '90s', '1h30m', '14:30', raw seconds int. Returns seconds or None."""
    s = s.strip().lower()
    if not s:
        return None
    # Clock time: "14:30" or "2:30pm"
    m = re.match(r'^(\d{1,2}):(\d{2})(am|pm)?$', s)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if m.group(3) == "pm" and h < 12: h += 12
        if m.group(3) == "am" and h == 12: h = 0
        now = datetime.now()
        target = now.replace(hour=h, minute=mi, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return (target - now).total_seconds()
    # Combined: "1h30m", "2h", "30m", "90s"
    total = 0
    for val, unit in re.findall(r'(\d+)([hms])', s):
        val = int(val)
        if unit == 'h': total += val * 3600
        elif unit == 'm': total += val * 60
        else: total += val
    if total:
        return total
    # Raw number (seconds)
    try:
        return float(s)
    except ValueError:
        return None


def cmd_timer(state, args):
    """/time [<duration>|off] — set a work deadline timer shown in the toolbar."""
    theme = state.get("theme", THEMES["default"])
    acc   = theme.get("accent", "cyan")
    a     = (args or "").strip().lower()

    if a in ("off", "clear", "stop", "cancel"):
        state.pop("_timer_deadline", None)
        state.pop("_timer_label", None)
        console.print(f"  [{acc}]✓ Timer cleared[/{acc}]")
        return state

    if not a:
        dl = state.get("_timer_deadline")
        if not dl:
            console.print("[yellow]No timer set.  Usage: /time 30m | 2h | 14:30 | off[/yellow]")
        else:
            rem = dl - time.time()
            if rem <= 0:
                console.print("[red bold]⏰ DEADLINE PASSED[/red bold]")
            else:
                h, r = divmod(int(rem), 3600)
                m2, s = divmod(r, 60)
                console.print(f"  [{acc}]⏱ {h}h {m2:02d}m {s:02d}s remaining[/{acc}]")
        return state

    secs = _parse_duration(a)
    if secs is None or secs <= 0:
        console.print("[red]Usage: /time 30m | 2h | 1h30m | 14:30 | 90s | off[/red]")
        return state

    state["_timer_deadline"] = time.time() + secs
    state["_timer_label"]    = a
    h, r = divmod(int(secs), 3600)
    m2, s = divmod(r, 60)
    console.print(f"  [{acc}]⏱ Timer set: {h}h {m2:02d}m {s:02d}s[/{acc}]  [dim]deadline in toolbar[/dim]")
    return state


# ── /statusline ────────────────────────────────────────────────────────────────
_STATUSLINE_DEFAULTS = _STATUSLINE_DEFAULTS_LAZY   # single source: studio/data.py
_STATUSLINE_ALL      = {"model","plan","stream","branch","tokens","in_tokens","out_tokens",
                         "mem","mode","agent","timer","fast","working","cwd"}

def cmd_statusline(state, args):
    """/statusline [show|hide|reset|list] [field,...] — configure the toolbar."""
    theme = state.get("theme", THEMES["default"])
    acc   = theme.get("accent", "cyan")
    a     = (args or "").strip().lower()
    raw = state.get("statusline_fields")
    if not isinstance(raw, set):
        state["statusline_fields"] = set(raw) if raw else set(_STATUSLINE_DEFAULTS)
    fields = state["statusline_fields"]

    if not a or a == "list":
        rows = []
        for f in sorted(_STATUSLINE_ALL):
            on = f in fields
            rows.append(f"  {'[green]✓[/green]' if on else '[dim]○[/dim]'}  {f}")
        console.print(Panel(
            "\n".join(rows) + "\n\n  [dim]/statusline show model,plan,tokens[/dim]\n"
            "  [dim]/statusline hide mem,cwd[/dim]\n"
            "  [dim]/statusline reset[/dim]",
            title="◉ Statusline Fields", border_style=theme.get("border","cyan")))
        return state

    if a == "reset":
        state["statusline_fields"] = set(_STATUSLINE_DEFAULTS)
        console.print(f"  [{acc}]✓ Statusline reset to defaults[/{acc}]")
        return state

    parts = a.split(None, 1)
    action = parts[0]
    if len(parts) < 2:
        console.print("[red]Usage: /statusline show <fields> | hide <fields> | reset | list[/red]")
        return state

    field_list = [f.strip() for f in parts[1].replace(",", " ").split()]
    unknown    = [f for f in field_list if f not in _STATUSLINE_ALL]
    if unknown:
        console.print(f"[yellow]Unknown fields: {', '.join(unknown)}  —  valid: {', '.join(sorted(_STATUSLINE_ALL))}[/yellow]")
    valid = [f for f in field_list if f in _STATUSLINE_ALL]
    if action == "show":
        fields.update(valid)
        console.print(f"  [{acc}]✓ Showing: {', '.join(valid)}[/{acc}]")
    elif action == "hide":
        fields.difference_update(valid)
        console.print(f"  [yellow]✓ Hidden: {', '.join(valid)}[/yellow]")
    else:
        console.print("[red]Usage: /statusline show <fields> | hide <fields>[/red]")
    state["statusline_fields"] = fields
    return state


# ── v9.3 New Commands ────────────────────────────────────────────────────────

def _plan_allows(state, feature: str) -> bool:
    """Return True if the current plan allows the given feature key."""
    plan = get_plan(state)
    return PLANS.get(plan, {}).get(feature, False)

def _credits_file(state):
    uid = (load_profile() or {}).get("user", "default")
    return Path("profiles") / uid / "credits.json"

def _load_credits(state) -> dict:
    f = _credits_file(state)
    if f.exists():
        try:
            return json.loads(f.read_text())
        except Exception:
            pass
    import calendar
    now = datetime.now()
    return {"used": 0, "month": now.month, "year": now.year}

def _save_credits(state, data: dict):
    f = _credits_file(state)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data, indent=2))

def track_credits(state, cost_key: str = "message"):
    """Deduct credits for an action. Returns (remaining, limit)."""
    plan     = get_plan(state)
    limit    = PLANS.get(plan, {}).get("credits", 100)
    if limit >= 999999:
        return 999999, 999999
    cost     = CREDIT_COSTS.get(cost_key, 1)
    data     = _load_credits(state)
    now      = datetime.now()
    if data.get("month") != now.month or data.get("year") != now.year:
        data = {"used": 0, "month": now.month, "year": now.year}
    data["used"] = round(data.get("used", 0) + cost, 2)
    _save_credits(state, data)
    return max(0, limit - data["used"]), limit

def get_credits_remaining(state) -> tuple:
    """Returns (used, remaining, limit)."""
    plan   = get_plan(state)
    limit  = PLANS.get(plan, {}).get("credits", 100)
    if limit >= 999999:
        return 0, 999999, 999999
    data   = _load_credits(state)
    now    = datetime.now()
    if data.get("month") != now.month or data.get("year") != now.year:
        return 0, limit, limit
    used = data.get("used", 0)
    return used, max(0, limit - used), limit

def cmd_credits(state):
    """/credits — show credit balance and usage."""
    theme  = state.get("theme", THEMES["default"])
    plan   = get_plan(state)
    pdata  = PLANS.get(plan, {})
    used, remaining, limit = get_credits_remaining(state)
    if limit >= 999999:
        console.print(Panel(
            f"[bold green]Unlimited credits[/bold green]\n"
            f"[dim]Plan: {pdata.get('name','?')} ({pdata.get('price','?')})[/dim]",
            title="◈ Credits", border_style=theme.get("accent","cyan")))
        return state
    pct = int((used / max(1, limit)) * 100)
    bar_filled = int(pct / 5)
    bar = "[green]" + "█" * bar_filled + "[/green][dim]" + "░" * (20 - bar_filled) + "[/dim]"
    console.print(Panel(
        f"{bar}  [bold]{pct}%[/bold] used\n\n"
        f"  Used:      [bold]{used:.1f}[/bold] credits\n"
        f"  Remaining: [bold {'green' if remaining > limit * 0.2 else 'red'}]{remaining:.1f}[/bold] credits\n"
        f"  Monthly:   {limit:,} credits / month\n"
        f"  Plan:      [{pdata.get('color','dim')}]{pdata.get('name','?')} ({pdata.get('price','?')})[/{pdata.get('color','dim')}]\n\n"
        f"  [dim]Costs: message=1 · fast=0.5 · turbo=2.5 · image=10 · search=2 · research=15[/dim]",
        title="◈ Credits", border_style=theme.get("accent","cyan")))
    return state


def _check_credit_budget(state, cost_key: str) -> bool:
    """Return False (and print warning) if not enough credits."""
    plan  = get_plan(state)
    limit = PLANS.get(plan, {}).get("credits", 100)
    if limit >= 999999:
        return True
    used, remaining, _ = get_credits_remaining(state)
    cost = CREDIT_COSTS.get(cost_key, 1)
    if remaining < cost:
        console.print(f"[red]Not enough credits — {remaining:.1f} remaining, need {cost}. /credits for details.[/red]")
        return False
    return True


def _ddg_search(query: str, max_results: int = 5) -> list:
    """Search DuckDuckGo Instant Answers API. Returns list of dicts."""
    import urllib.parse
    url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json&no_html=1&skip_disambig=1"
    try:
        req = request.Request(url, headers={"User-Agent": "StudioCLI/9.3"})
        with request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read())
        results = []
        if data.get("Abstract"):
            results.append({
                "title":   data.get("Heading", query),
                "url":     data.get("AbstractURL", ""),
                "snippet": data["Abstract"],
            })
        for item in data.get("RelatedTopics", [])[:max_results * 2]:
            if isinstance(item, dict) and item.get("Text"):
                results.append({
                    "title":   item.get("Text", "")[:80],
                    "url":     item.get("FirstURL", ""),
                    "snippet": item["Text"],
                })
        return results[:max_results]
    except Exception:
        return []


def cmd_websearch(state, args, history):
    """/search <query> — web search and optionally synthesize with AI."""
    if not args:
        # Toggle web search mode
        state["web_search_mode"] = not state.get("web_search_mode", False)
        on = state["web_search_mode"]
        console.print(Panel(
            f"[bold {'green' if on else 'yellow'}]Web Search {'ENABLED' if on else 'DISABLED'}[/bold {'green' if on else 'yellow'}]\n"
            f"[dim]{'All responses will use web-augmented model (perplexity/sonar).' if on else 'Back to standard AI responses.'}\n"
            f"Toggle again with /search to turn {'off' if on else 'on'}.[/dim]",
            title="🌐 Web Search", border_style="green" if on else "dim"))
        return state, history

    plan = get_plan(state)
    if not PLANS.get(plan, {}).get("web_search", False):
        console.print(Panel("[red]Web Search requires Pro or higher.[/red]\n[dim]/upgrade pro to unlock.[/dim]",
                            title="🔒 Locked", border_style="red"))
        return state, history

    if not _check_credit_budget(state, "web_search"):
        return state, history

    or_key = state.get("openrouter_key") or load_or_key()
    if or_key:
        # Use Perplexity Sonar via OpenRouter — has native web search
        console.print(f"[dim]🌐 Searching: {args}[/dim]")
        orig_model = state.get("model")
        state["model"] = WEB_SEARCH_MODELS["default"]
        response, history = ai_respond(state, args, history)
        state["model"] = orig_model
        track_credits(state, "web_search")
    else:
        # Fallback: DuckDuckGo Instant Answers
        console.print(f"[dim]🌐 Searching DuckDuckGo: {args}[/dim]")
        results = _ddg_search(args)
        if not results:
            console.print("[yellow]No results found[/yellow]")
            return state, history
        for i, r in enumerate(results, 1):
            console.print(Panel(
                f"[bold]{r['title']}[/bold]\n{r['snippet']}\n[dim link={r['url']}]{r['url']}[/dim link]",
                title=f"[cyan]{i}[/cyan]", border_style="cyan", padding=(0, 1)))
        track_credits(state, "web_search")
    return state, history


def cmd_research(state, args, history):
    """/research <topic> — deep multi-step AI research with web synthesis."""
    if not args:
        console.print("[yellow]Usage: /research <topic>[/yellow]")
        return history

    plan = get_plan(state)
    if not PLANS.get(plan, {}).get("deep_research", False):
        console.print(Panel("[red]Deep Research requires Pro or higher.[/red]\n[dim]/upgrade pro to unlock.[/dim]",
                            title="🔒 Locked", border_style="red"))
        return history

    if not _check_credit_budget(state, "deep_research"):
        return history

    console.print(Panel(
        f"[bold]Topic:[/bold] {args}\n\n[dim]Step 1/3: Decomposing query…[/dim]",
        title="🔬 Deep Research", border_style="magenta"))

    or_key = state.get("openrouter_key") or load_or_key()

    if or_key:
        # Step 1: Use sonar-pro for deep research directly
        console.print("[dim]  Searching the web for multiple angles…[/dim]")
        orig_model = state.get("model")
        state["model"] = WEB_SEARCH_MODELS["deep"]
        research_prompt = (
            f"Conduct deep research on: {args}\n\n"
            f"Provide a comprehensive, well-structured report covering: "
            f"key findings, multiple perspectives, supporting evidence, "
            f"and a clear conclusion. Use your web search capability to "
            f"find current, accurate information."
        )
        response, history = ai_respond(state, research_prompt, history)
        state["model"] = orig_model
    else:
        # Fallback: multi-step DuckDuckGo
        console.print("[dim]  Step 1: Breaking down research question…[/dim]")
        decomp_prompt = (
            f"Research topic: {args}\n"
            f"List exactly 4 specific search queries to research this comprehensively. "
            f"One per line, no numbering, no explanation. Keep each under 8 words."
        )
        sub_text, history = ai_respond(state, decomp_prompt, history, silent=True)
        queries = [q.strip() for q in (sub_text or "").splitlines() if q.strip()][:4]
        if not queries:
            queries = [args]

        console.print(f"[dim]  Step 2: Searching {len(queries)} queries…[/dim]")
        all_snippets = []
        for q in queries:
            console.print(f"[dim]    → {q}[/dim]")
            results = _ddg_search(q, max_results=3)
            for r in results:
                if r.get("snippet"):
                    all_snippets.append(f"**{r['title']}**: {r['snippet']}")

        console.print("[dim]  Step 3: Synthesizing findings…[/dim]")
        if all_snippets:
            context = "\n".join(all_snippets[:12])
            synth_prompt = (
                f"Based on the following web research about '{args}', write a comprehensive, "
                f"well-structured report:\n\n{context}\n\n"
                f"Structure: Overview → Key Findings → Analysis → Conclusion"
            )
            _, history = ai_respond(state, synth_prompt, history)
        else:
            _, history = ai_respond(state, f"Provide a comprehensive research report on: {args}", history)

    track_credits(state, "deep_research")
    return history


def cmd_turbo(state, args):
    """/turbo — toggle 2x fast mode (2.5x credit cost, Pro+ only)."""
    plan = get_plan(state)
    if not PLANS.get(plan, {}).get("turbo", False):
        console.print(Panel(
            "[red]Turbo Mode requires Pro or higher.[/red]\n"
            "[dim]2x faster responses · 2.5x credit cost[/dim]\n"
            "[dim]/upgrade pro to unlock.[/dim]",
            title="🔒 Turbo Locked", border_style="red"))
        return state

    state["turbo_mode"] = not state.get("turbo_mode", False)
    theme = state.get("theme", THEMES["default"])

    if state["turbo_mode"]:
        state["_pre_turbo_model"]  = state.get("model")
        state["_pre_turbo_fast"]   = state.get("fast_mode", False)
        or_key = state.get("openrouter_key") or load_or_key()
        if or_key:
            state["model"] = TURBO_MODELS[0]
        state["fast_mode"]         = True
        state["thinking_budget"]   = 0
        console.print(Panel(
            "[bold yellow]⚡⚡ TURBO MODE ACTIVE[/bold yellow]\n\n"
            f"[dim]Model:        {state['model'].split('/')[-1]}[/dim]\n"
            "[dim]Speed:        2x faster[/dim]\n"
            "[dim]Credit cost:  2.5x per message[/dim]\n"
            "[dim]Thinking:     disabled[/dim]\n\n"
            "[dim]/turbo again to disable[/dim]",
            title="⚡ Turbo", border_style="yellow"))
    else:
        if state.get("_pre_turbo_model"):
            state["model"]     = state.pop("_pre_turbo_model")
        state["fast_mode"]     = state.pop("_pre_turbo_fast", False)
        state["turbo_mode"]    = False
        console.print(f"[{theme.get('accent','cyan')}]✓ Turbo mode off — restored previous settings[/{theme.get('accent','cyan')}]")
    return state


def _cu_take_screenshot() -> tuple[str | None, str | None]:
    """Capture the screen, return (base64_png, error_string)."""
    try:
        from PIL import ImageGrab
        import io, base64
        img = ImageGrab.grab()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("utf-8"), None
    except ImportError:
        pass
    # Fallback: PowerShell screenshot (Windows)
    try:
        import io, base64, subprocess, tempfile
        tmp = tempfile.mktemp(suffix=".png")
        ps = (
            "[void][reflection.assembly]::LoadWithPartialName('System.Drawing');"
            "[void][reflection.assembly]::LoadWithPartialName('System.Windows.Forms');"
            "$screen=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds;"
            "$bmp=New-Object System.Drawing.Bitmap $screen.Width,$screen.Height;"
            "$g=[System.Drawing.Graphics]::FromImage($bmp);"
            "$g.CopyFromScreen($screen.Location,[System.Drawing.Point]::Empty,$screen.Size);"
            f"$bmp.Save('{tmp}');"
        )
        subprocess.run(["powershell", "-Command", ps], capture_output=True, timeout=10)
        if Path(tmp).exists():
            data = base64.b64encode(Path(tmp).read_bytes()).decode("utf-8")
            Path(tmp).unlink(missing_ok=True)
            return data, None
        return None, "PowerShell screenshot failed"
    except Exception as e:
        return None, f"Screenshot error: {e}"


def _cu_ask_vision(state, b64_png: str, instruction: str) -> tuple[str | None, str | None]:
    """Send screenshot to best available vision model. Returns (text, error)."""
    image_url = f"data:image/png;base64,{b64_png}"

    # Build vision message
    vision_msg = {
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": image_url}},
            {"type": "text", "text": instruction},
        ],
    }

    # Prefer OpenRouter vision models
    or_key = state.get("openrouter_key") or load_or_key()
    if or_key:
        vision_models = [
            "openai/gpt-4o",
            "anthropic/claude-sonnet-4-6",
            "google/gemini-2.5-pro",
            "openai/gpt-4o-mini",
        ]
        current_model = state.get("model", "")
        if "/" in current_model and not current_model.endswith(":free"):
            vision_models.insert(0, current_model)

        system = (
            "You are a computer use assistant. The user has shared a screenshot. "
            "Describe what you see and, if given an instruction, specify the exact "
            "action as JSON: {\"action\":\"click\",\"x\":N,\"y\":N} | "
            "{\"action\":\"type\",\"text\":\"...\"} | {\"action\":\"key\",\"key\":\"...\"} | "
            "{\"action\":\"scroll\",\"x\":N,\"y\":N,\"delta\":N} | {\"action\":\"describe\"}. "
            "Always include a human-readable explanation before the JSON."
        )
        payload = json.dumps({
            "model": vision_models[0],
            "messages": [{"role": "system", "content": system}, vision_msg],
            "max_tokens": 1024,
        })
        try:
            req = request.Request(
                OPENROUTER_BASE,
                data=payload.encode(),
                headers={
                    "Authorization": f"Bearer {or_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://studiocli.dev",
                    "X-Title": "StudioCLI Computer Use",
                },
                method="POST",
            )
            with request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"], None
        except Exception as e:
            return None, str(e)

    # Gemini Vision fallback
    gm_key = state.get("api_key") or load_api_key()
    if gm_key:
        try:
            payload = json.dumps({
                "contents": [{"parts": [
                    {"inline_data": {"mime_type": "image/png", "data": b64_png}},
                    {"text": instruction},
                ]}]
            })
            url = f"{API_BASE}/gemini-2.0-flash:generateContent?key={gm_key}"
            req = request.Request(url, data=payload.encode(),
                                  headers={"Content-Type": "application/json"}, method="POST")
            with request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            return data["candidates"][0]["content"]["parts"][0]["text"], None
        except Exception as e:
            return None, str(e)

    return None, "No API key configured — run /keys set openrouter <key>"


def _cu_execute_action(action_json: str) -> str | None:
    """Parse and execute a computer use action. Returns error string or None."""
    try:
        import pyautogui
        import json as _json
        # Find JSON block in text
        m = re.search(r'\{[^{}]+\}', action_json)
        if not m:
            return None
        act = _json.loads(m.group())
        kind = act.get("action", "")
        if kind == "click":
            pyautogui.click(act["x"], act["y"])
        elif kind == "type":
            pyautogui.typewrite(act["text"], interval=0.03)
        elif kind == "key":
            pyautogui.press(act["key"])
        elif kind == "scroll":
            pyautogui.scroll(act.get("delta", 3), x=act["x"], y=act["y"])
        return None
    except ImportError:
        return "pyautogui not installed — run: pip install pyautogui"
    except Exception as e:
        return f"Action error: {e}"


def cmd_computer_use(state, args):
    """/computer-use — AI-powered desktop automation (Max+ only)."""
    plan = get_plan(state)
    if not PLANS.get(plan, {}).get("computer_use", False):
        console.print(Panel(
            "[red]Computer Use requires Max or higher.[/red]\n\n"
            "[dim]Computer Use lets the AI see your screen, move the mouse,\n"
            "type text, and interact with any app on your desktop.\n\n"
            "Available on: Max ($80/mo), Ultra ($250/mo), Team, Enterprise[/dim]\n\n"
            "[yellow]/upgrade max[/yellow] to unlock",
            title="🖥 Computer Use — Locked", border_style="red"))
        return state

    sub   = (args or "").strip()
    lower = sub.lower()
    theme = state.get("theme", THEMES["default"])
    acc   = theme.get("accent", "cyan")

    if not lower or lower == "help":
        # Check what's available
        has_pil   = bool(__import__("importlib").util.find_spec("PIL"))
        has_pyag  = bool(__import__("importlib").util.find_spec("pyautogui"))
        has_key   = bool(state.get("openrouter_key") or load_or_key() or
                         state.get("api_key") or load_api_key())
        pil_st    = "[green]✓[/green]" if has_pil else "[red]✗ (pip install Pillow)[/red]"
        pyag_st   = "[green]✓[/green]" if has_pyag else "[yellow]○ optional (pip install pyautogui)[/yellow]"
        key_st    = "[green]✓[/green]" if has_key else "[red]✗ (run /keys set openrouter YOUR_KEY)[/red]"
        console.print(Panel(
            f"[bold]🖥 Computer Use — AI Desktop Automation[/bold]\n\n"
            f"[dim]Dependencies:[/dim]\n"
            f"  {pil_st} Pillow (screenshot)\n"
            f"  {pyag_st} pyautogui (mouse/keyboard)\n"
            f"  {key_st} Vision API key\n\n"
            f"[dim]Commands:[/dim]\n"
            f"  [bold]/computer-use snap[/bold]            — screenshot + AI description\n"
            f"  [bold]/computer-use run <instruction>[/bold] — screenshot + AI executes action\n"
            f"  [bold]/computer-use loop[/bold]            — interactive session (Ctrl+C to exit)\n"
            f"  [bold]/computer-use providers[/bold]       — show available vision providers\n\n"
            f"[dim]Works with: OpenRouter (GPT-4o, Claude, Gemini) · Gemini API[/dim]",
            title="🖥 Computer Use", border_style=acc))
        return state

    if lower == "providers":
        or_key = state.get("openrouter_key") or load_or_key()
        gm_key = state.get("api_key") or load_api_key()
        console.print(Panel(
            f"  [bold]Vision providers for Computer Use:[/bold]\n\n"
            f"  {'[green]✓[/green]' if or_key else '[dim]○[/dim]'} OpenRouter  — GPT-4o, Claude Sonnet, Gemini 2.5 Pro\n"
            f"  {'[green]✓[/green]' if gm_key else '[dim]○[/dim]'} Gemini API  — gemini-2.0-flash\n"
            f"  [dim]○[/dim] Cursor API  — coming in v9.5\n"
            f"  [dim]○[/dim] OAuth/SSO   — coming in v9.5 (Enterprise)\n\n"
            f"  [dim]Set keys: /keys set openrouter <key>   /keys set gemini <key>[/dim]",
            title="🖥 Computer Use — Providers", border_style=acc))
        return state

    if lower == "stop":
        state["_cu_active"] = False
        console.print(f"[{acc}]✓ Computer Use session ended.[/{acc}]")
        return state

    if lower in ("snap", "screenshot", "describe"):
        console.print(f"[{acc}]📷 Taking screenshot…[/{acc}]")
        b64, err = _cu_take_screenshot()
        if err or not b64:
            console.print(f"[red]✗ {err or 'Screenshot failed'}[/red]")
            return state
        console.print(f"[{acc}]🔍 Asking AI to describe screen…[/{acc}]")
        text, err2 = _cu_ask_vision(state, b64, "Describe what you see on this screen in detail. What is open, what is in focus, what UI elements are visible?")
        if err2:
            console.print(f"[red]✗ Vision error: {err2}[/red]")
        else:
            console.print(_assistant_heading(state, "CV", False))
            console.print(Markdown(text))
        return state

    if lower.startswith("run ") or (lower not in ("snap","loop","providers","stop","help")):
        # Direct instruction
        instruction = sub[4:].strip() if lower.startswith("run ") else sub
        if not instruction:
            console.print("[yellow]Provide an instruction: /computer-use run <what to do>[/yellow]")
            return state
        console.print(f"[{acc}]📷 Capturing screen…[/{acc}]")
        b64, err = _cu_take_screenshot()
        if err or not b64:
            console.print(f"[red]✗ {err or 'Screenshot failed'}[/red]"); return state
        console.print(f"[{acc}]🤖 Asking AI: {instruction[:60]}…[/{acc}]")
        text, err2 = _cu_ask_vision(state, b64,
            f"User instruction: {instruction}\n\n"
            "First describe what you see on screen, then specify the exact action to take as JSON.")
        if err2:
            console.print(f"[red]✗ {err2}[/red]"); return state
        console.print(_assistant_heading(state, "CV", False))
        console.print(Markdown(text))
        # Attempt to execute the action
        exec_err = _cu_execute_action(text)
        if exec_err:
            console.print(f"[yellow]⚡ Action parsing: {exec_err}[/yellow]")
            console.print("[dim]Install pyautogui to enable automatic action execution.[/dim]")
        else:
            console.print(f"[{acc}]✓ Action executed.[/{acc}]")
        return state

    if lower == "loop":
        console.print(Panel(
            "[bold]Computer Use — Interactive Loop[/bold]\n"
            "[dim]Type your instruction and press Enter. Studio will screenshot, ask AI, and act.\n"
            "Type 'stop' or press Ctrl+C to exit.[/dim]",
            title="🖥 Computer Use Loop", border_style=acc))
        state["_cu_active"] = True
        while state.get("_cu_active", False):
            try:
                instruction = console.input(f"  [{acc}]🖥 instruction:[/{acc}] ").strip()
            except (KeyboardInterrupt, EOFError):
                break
            if not instruction or instruction.lower() in ("stop", "exit", "quit"):
                break
            b64, err = _cu_take_screenshot()
            if err or not b64:
                console.print(f"[red]✗ {err}[/red]"); continue
            text, err2 = _cu_ask_vision(state, b64, instruction)
            if err2:
                console.print(f"[red]✗ {err2}[/red]"); continue
            console.print(Markdown(text))
            exec_err = _cu_execute_action(text)
            if exec_err:
                console.print(f"[yellow]{exec_err}[/yellow]")
        state["_cu_active"] = False
        console.print(f"[{acc}]Computer Use session ended.[/{acc}]")
        return state

    return state


def cmd_extension(state, args):
    """/extension — Chrome Extension for Studio (Max+ only)."""
    plan = get_plan(state)
    if not PLANS.get(plan, {}).get("computer_use", False):
        console.print(Panel(
            "[red]The Studio Chrome Extension requires Max or higher.[/red]\n\n"
            "[dim]The extension lets Studio control Chrome:\n"
            "  • Fill forms and click elements on any page\n"
            "  • Scrape and summarize page content\n"
            "  • Automate multi-step browsing tasks\n"
            "  • Take actions on web apps on your behalf\n\n"
            "Available on: Max ($80/mo), Ultra ($250/mo), Team, Enterprise[/dim]\n\n"
            "[yellow]/upgrade max[/yellow] to unlock",
            title="🧩 Chrome Extension — Locked", border_style="red"))
        return state

    sub = (args or "").strip().lower()
    if not sub or sub == "help":
        console.print(Panel(
            "[bold]Studio Chrome Extension[/bold]\n\n"
            "[dim]Install & commands:[/dim]\n"
            "  /extension install   — download the extension package\n"
            "  /extension status    — show current browser session\n"
            "  /extension actions   — list available browser actions\n\n"
            "[yellow]Note:[/yellow] Load the extension in Chrome via chrome://extensions → Load unpacked.\n"
            "Extension files are in [bold]web/public/extension/[/bold]",
            title="🧩 Chrome Extension", border_style="cyan"))
        return state

    if sub == "install":
        ext_dir = Path("web/public/extension")
        if ext_dir.exists():
            console.print(Panel(
                f"[green]✓ Extension ready at:[/green] [bold]{ext_dir.resolve()}[/bold]\n\n"
                "[dim]1. Open chrome://extensions\n"
                "2. Enable Developer mode (top-right toggle)\n"
                "3. Click 'Load unpacked' → select the folder above[/dim]",
                title="🧩 Install Extension", border_style="green"))
        else:
            console.print(f"[yellow]Extension package not found at {ext_dir}. Coming in v9.4.[/yellow]")
    else:
        console.print(f"[dim]Chrome Extension actions coming in v9.4. Your plan supports it.[/dim]")
    return state


def _show_plan_updates(state):
    """On login: show any new plan updates the user hasn't seen."""
    plan    = get_plan(state)
    prof    = load_profile() or {}
    seen_v  = prof.get("last_seen_update", "0.0")
    theme   = state.get("theme", THEMES["default"])

    new_updates = []
    for ver, info in sorted(PLAN_UPDATES.items(), reverse=True):
        if ver <= seen_v:
            break
        if plan in info.get("plans", []):
            new_updates.append((ver, info))

    if not new_updates:
        return

    lines = []
    for ver, info in new_updates:
        lines.append(f"[bold]v{ver}[/bold]  [dim]{info['date']}[/dim]")
        for ch in info["changes"]:
            lines.append(f"  [green]✦[/green] {ch}")
        lines.append("")

    console.print(Panel(
        "\n".join(lines).rstrip(),
        title=f"[bold]✦ What's New ({PLANS[plan]['name']} Plan)[/bold]",
        border_style=PLANS[plan].get("color", "cyan")))

    prof["last_seen_update"] = sorted(PLAN_UPDATES.keys())[-1]
    save_profile(prof)


# ── v9 Beta Commands ──────────────────────────────────────────────────────────

_BETA_FLAGS_FILE = CONFIG_DIR / "beta_flags.json"

def _load_beta_flags():
    if _BETA_FLAGS_FILE.exists():
        try:
            return json.loads(_BETA_FLAGS_FILE.read_text())
        except Exception:
            pass
    return {}

def _save_beta_flags(flags):
    _BETA_FLAGS_FILE.parent.mkdir(exist_ok=True)
    _BETA_FLAGS_FILE.write_text(json.dumps(flags, indent=2))

_AVAILABLE_FLAGS = {
    "voice":           ("Voice-to-text input mode",               "ultra"),
    "mesh_broadcast":  ("Broadcast prompt to all active agents",  "ultra"),
    "analytics_pro":   ("Advanced usage analytics dashboard",     "ultra"),
    "auto_snapshot":   ("Auto-snapshot session every 50 messages","ultra"),
    "effort_xhigh":    ("Unlock xhigh + mxh effort levels",       "ultra"),
    "model_preview":   ("Access preview/experimental models",     "ultra"),
    "parallel_exec":   ("Execute code blocks in parallel",        "max"),
    "audit_stream":    ("Stream audit events in real-time",       "max"),
}


def cmd_beta(state, args):
    """/beta [on|off] [flag] — manage v9 Beta experimental feature flags (ultra)."""
    if not _require_tier(state, ("ultra", "enterprise"), "/beta flags", "/upgrade ultra"):
        return
    theme = state.get("theme", THEMES["default"])
    acc   = theme.get("accent", "cyan")
    flags = _load_beta_flags()
    sub   = args.strip().lower() if args else ""

    if not sub or sub == "list":
        rows = ""
        for flag, (desc, tier) in _AVAILABLE_FLAGS.items():
            enabled = flags.get(flag, False)
            status  = f"[green]ON[/green]" if enabled else "[dim]off[/dim]"
            rows += f"\n  {status}  [{acc}]{flag:<20}[/{acc}]  [dim]{desc}[/dim]"
        console.print(Panel(
            f"  [bold]v9 Beta Feature Flags[/bold]\n{rows}\n\n"
            f"  [dim]/beta on <flag>   →  enable\n"
            f"  /beta off <flag>  →  disable\n"
            f"  /beta reset       →  disable all[/dim]",
            title=f"[bold yellow]★ Beta Labs[/bold yellow]",
            border_style="yellow", padding=(0, 2)
        ))
        return

    if sub == "reset":
        _save_beta_flags({})
        console.print(f"  [{acc}]✓ All beta flags reset.[/{acc}]")
        return

    parts = sub.split(None, 1)
    if len(parts) == 2 and parts[0] in ("on", "off"):
        action, flag = parts[0], parts[1].strip()
        if flag not in _AVAILABLE_FLAGS:
            console.print(f"[yellow]Unknown flag '{flag}'. Use /beta list.[/yellow]")
            return
        flags[flag] = (action == "on")
        _save_beta_flags(flags)
        state.setdefault("_beta_flags", {}).update(flags)
        verb = "[green]enabled[/green]" if flags[flag] else "[dim]disabled[/dim]"
        console.print(f"  [{acc}]★ Beta flag '{flag}' {verb}.[/{acc}]")
        return

    # Unknown sub-command — delegate to legacy beta features (docx, xlsx, screenshot, video, feedback)
    # This keeps backward compat for non-ultra users who use /beta docx, /beta xlsx etc.
    # We pass an empty history and discard the return since this path has no history context here.
    console.print("[yellow]Usage: /beta list  |  /beta on <flag>  |  /beta off <flag>  |  /beta reset[/yellow]")
    console.print("[dim]Tip: /beta docx · /beta xlsx · /beta screenshot · /beta video · /beta feedback[/dim]")


def cmd_voice(state, args):
    """/voice [start|stop] — voice-to-text input mode (ultra, requires pyaudio)."""
    if not _require_tier(state, ("ultra", "enterprise"), "/voice", "/upgrade ultra"):
        return
    theme = state.get("theme", THEMES["default"])
    acc   = theme.get("accent", "cyan")
    sub   = args.strip().lower() if args else "start"

    # Stub: check for pyaudio / speech_recognition availability
    try:
        import speech_recognition  # noqa: F401
        _has_sr = True
    except ImportError:
        _has_sr = False

    if not _has_sr:
        console.print(Panel(
            "  [bold yellow]★ Voice mode — beta feature[/bold yellow]\n\n"
            "  Voice-to-text requires [bold]speech_recognition[/bold] and [bold]pyaudio[/bold].\n\n"
            "  [dim]pip install SpeechRecognition pyaudio[/dim]\n\n"
            "  After installing, re-run [bold]/voice start[/bold] and speak into your mic.\n"
            "  Your speech will be transcribed and sent as a message.",
            title="[bold]Voice Input[/bold]",
            border_style="yellow", padding=(0, 2)
        ))
        return

    if sub == "stop":
        state.pop("_voice_active", None)
        console.print(f"  [{acc}]✓ Voice mode stopped.[/{acc}]")
        return

    # Activate voice mode — actual capture loop when enabled
    state["_voice_active"] = True
    console.print(Panel(
        f"  [{acc}]★ Voice mode active[/{acc}]\n\n"
        "  Listening… speak clearly into your microphone.\n"
        "  Say [bold]'stop listening'[/bold] to exit voice mode.\n\n"
        "  [dim]/voice stop  →  exit voice mode[/dim]",
        title="[bold]Voice Input — Live[/bold]",
        border_style="yellow", padding=(0, 2)
    ))


def cmd_mesh_broadcast(state, args, history):
    """/mesh-broadcast <prompt> — broadcast a prompt to ALL active agents in parallel (ultra)."""
    if not _require_tier(state, ("ultra", "enterprise"), "/mesh-broadcast", "/upgrade ultra"):
        return history
    theme = state.get("theme", THEMES["default"])
    acc   = theme.get("accent", "cyan")
    prompt = args.strip() if args else ""
    if not prompt:
        console.print("[yellow]Usage: /mesh-broadcast <prompt>[/yellow]")
        return history

    agents = state.get("agents", {})
    if not agents:
        console.print(Panel(
            "  No agents are active. Start agents first:\n"
            "  [dim]/agent spawn <name>[/dim]",
            title="Mesh Broadcast", border_style="yellow", padding=(0, 2)
        ))
        return history

    console.print(Panel(
        f"  [{acc}]★ Broadcasting to {len(agents)} agent(s)…[/{acc}]\n\n"
        f"  [bold]Prompt:[/bold] {prompt[:80]}{'…' if len(prompt) > 80 else ''}",
        title="[bold]Mesh Broadcast[/bold]", border_style="yellow", padding=(0, 2)
    ))
    for name, agent_obj in agents.items():
        console.print(f"\n  [bold {acc}]▶ {name}[/bold {acc}]")
        try:
            resp = agent_obj.run(prompt, console, ai_respond)
            if resp:
                history.append({"role": "model", "text": f"[{name}] {resp}"})
        except Exception as exc:
            console.print(f"  [red]Agent '{name}' error: {exc}[/red]")
    console.print(f"\n  [{acc}]✓ Broadcast complete.[/{acc}]")
    return history


def cmd_analytics_pro(state, args):
    """/analytics-pro — advanced usage analytics (ultra)."""
    if not _require_tier(state, ("ultra", "enterprise"), "/analytics-pro", "/upgrade ultra"):
        return
    theme = state.get("theme", THEMES["default"])
    acc   = theme.get("accent", "cyan")
    prof  = load_profile() or {}

    total_msgs    = prof.get("total_msgs", 0)
    tok_in        = prof.get("total_tokens_in", 0)
    tok_out       = prof.get("total_tokens_out", 0)
    sess_count    = prof.get("session_count", 1)
    model_usage   = prof.get("model_usage", {})
    login_hist    = prof.get("login_history", [])

    avg_per_sess  = round(total_msgs / max(sess_count, 1), 1)
    avg_tok_out   = round(tok_out / max(total_msgs, 1), 1)
    top_models    = sorted(model_usage.items(), key=lambda x: x[1], reverse=True)[:5]

    # Build a small ASCII usage bar
    def _bar(val, max_val, width=20):
        filled = max(1, int((val / max(max_val, 1)) * width))
        return f"[{acc}]{'█' * filled}[/{acc}][dim]{'░' * (width - filled)}[/dim]"

    top_model_rows = ""
    max_m = top_models[0][1] if top_models else 1
    for m, c in top_models:
        short = m.split("/")[-1].split(":")[0][:22]
        top_model_rows += f"\n  {_bar(c, max_m, 16)}  [bold]{short:<22}[/bold]  [dim]{c}×[/dim]"

    # Recent activity (last 7 sessions)
    recent = login_hist[-7:] if login_hist else []
    activity = "\n".join(
        f"  [dim]· {ts[:16].replace('T', ' ')}[/dim]" for ts in reversed(recent)
    ) or "  [dim]—[/dim]"

    body = (
        f"  [bold {acc}]★ Pro Analytics Dashboard[/bold {acc}]\n\n"
        f"  [bold]Total messages[/bold]      {total_msgs:>8,}\n"
        f"  [bold]Total sessions[/bold]      {sess_count:>8,}\n"
        f"  [bold]Avg msgs/session[/bold]    {avg_per_sess:>8}\n"
        f"  [bold]Tokens in[/bold]           {tok_in:>8,}\n"
        f"  [bold]Tokens out[/bold]          {tok_out:>8,}\n"
        f"  [bold]Avg tokens/reply[/bold]    {avg_tok_out:>8}\n"
        f"\n  [bold]Top models[/bold]{top_model_rows}\n"
        f"\n  [bold]Recent sessions[/bold]\n{activity}"
    )
    console.print(Panel(body, title="[bold yellow]★ Analytics Pro[/bold yellow]",
                        border_style="yellow", padding=(0, 2)))


def cmd_labs(state, args):
    """/labs — alias for /beta, show experimental lab features."""
    cmd_beta(state, args)


def cmd_profile_view(state):
    """/profile — view your full profile: sessions, model usage, lifetime stats."""
    prof  = load_profile() or {}
    theme = state.get("theme", THEMES["default"])
    acc   = theme.get("accent", "cyan")
    bc    = theme.get("border", "cyan").replace("bold ", "")

    plan_id  = get_plan(state)
    plan_cfg = PLANS.get(plan_id, PLANS["free"])

    username     = prof.get("user", "User")
    first_seen   = prof.get("first_seen") or prof.get("onboarded_at", "—")
    last_seen    = prof.get("last_seen", "—")
    sess_count   = prof.get("session_count", 1)
    total_msgs   = prof.get("total_msgs", 0)
    tok_in       = prof.get("total_tokens_in", 0)
    tok_out      = prof.get("total_tokens_out", 0)
    dev_type     = prof.get("dev_type", "—")
    ui_style     = prof.get("ui_style", "gemini")
    model_usage  = prof.get("model_usage", {})
    login_hist   = prof.get("login_history", [])

    def _short_ts(ts):
        if not ts or ts == "—": return "—"
        try:
            return str(ts)[:10]
        except Exception:
            return str(ts)[:10]

    # Build top models table
    sorted_models = sorted(model_usage.items(), key=lambda x: x[1], reverse=True)
    top_models_str = ""
    if sorted_models:
        total_m = sum(v for _, v in sorted_models) or 1
        for m, c in sorted_models[:5]:
            bar_len = max(1, int((c / total_m) * 20))
            pct = round(c / total_m * 100)
            top_models_str += f"\n  [bold]{_short_model(m):<24}[/bold]  [cyan]{'█'*bar_len}[/cyan]  {c}× ({pct}%)"
    else:
        top_models_str = "\n  [dim]No model usage recorded yet.[/dim]"

    # Recent logins
    recent_logins = login_hist[-5:] if login_hist else []
    logins_str = "\n".join(f"  [dim]· {ts[:16].replace('T',' ')}[/dim]" for ts in reversed(recent_logins)) or "  [dim]—[/dim]"

    body = (
        f"  [{plan_cfg['color']}]{plan_cfg['badge']} {plan_cfg['name']}[/{plan_cfg['color']}]"
        f"  [dim]·  {dev_type}  ·  UI: {ui_style}[/dim]\n\n"
        f"  [bold]First seen[/bold]   {_short_ts(first_seen)}\n"
        f"  [bold]Last active[/bold]  {_short_ts(last_seen)}\n"
        f"  [bold]Sessions[/bold]     {sess_count}\n"
        f"  [bold]Messages[/bold]     {total_msgs:,}\n"
        f"  [bold]Tokens in[/bold]    {tok_in:,}\n"
        f"  [bold]Tokens out[/bold]   {tok_out:,}\n"
        f"\n  [bold {acc}]Model usage[/bold {acc}]{top_models_str}\n"
        f"\n  [bold]Recent sessions[/bold]\n{logins_str}"
    )
    console.print()
    console.print(Panel(
        body,
        title=f"[bold {bc}]◆ Profile — {username}[/bold {bc}]",
        border_style=bc,
        padding=(1, 2),
    ))
    console.print()


def cmd_insights(state):
    """/insights — Pro usage insights: cost estimate, peak hours, model efficiency."""
    theme  = state.get("theme", THEMES["default"])
    acc    = theme.get("accent", "cyan")
    bc     = theme.get("border", "cyan").replace("bold ", "")
    prof   = load_profile() or {}

    total_in    = prof.get("total_tokens_in", 0)
    total_out   = prof.get("total_tokens_out", 0)
    total_msgs  = prof.get("total_msgs", 0)
    sess_count  = prof.get("session_count", 1)
    model_usage = prof.get("model_usage", {})
    login_hist  = prof.get("login_history", [])

    # Cost estimate
    est_cost = ((total_in + total_out) / 1000) * 0.002

    # Peak hour from login_history
    peak_hour = "—"
    if login_hist:
        try:
            hours = [int(ts[11:13]) for ts in login_hist if len(ts) >= 13]
            if hours:
                from collections import Counter
                peak_h = Counter(hours).most_common(1)[0][0]
                peak_hour = f"{peak_h:02d}:00 – {peak_h+1:02d}:00"
        except Exception:
            pass

    avg_msgs = round(total_msgs / sess_count, 1) if sess_count else 0

    top_model = max(model_usage, key=model_usage.get) if model_usage else "—"
    rare_models = [m for m, c in model_usage.items() if c == 1]

    body = (
        f"  [bold]Lifetime cost estimate[/bold]   [bold green]${est_cost:.4f}[/bold green]  [dim]@ $0.002/1k tok[/dim]\n"
        f"  [bold]Total tokens[/bold]             {(total_in+total_out):,}  [dim]({total_in:,} in / {total_out:,} out)[/dim]\n"
        f"  [bold]Avg msgs/session[/bold]         {avg_msgs}\n"
        f"  [bold]Peak activity[/bold]            {peak_hour}\n\n"
        f"  [bold]Top model[/bold]   [{acc}]{_short_model(top_model)}[/{acc}]\n"
        f"  [bold]Models tried[/bold]  {len(model_usage)}\n"
    )
    if rare_models:
        body += f"  [bold]Rarely used[/bold]  [dim]{', '.join(_short_model(m) for m in rare_models[:4])}[/dim]\n"

    console.print()
    console.print(Panel(
        body,
        title=f"[bold {bc}]◆ Usage Insights[/bold {bc}]",
        border_style=bc,
        padding=(1, 2),
    ))
    console.print()


# ── v5.8 Pro welcome overlay ──────────────────────────────────────────────────
def _render_pro_welcome(state):
    """Extra Pro/Max/Enterprise welcome overlay shown after render_welcome."""
    plan_id  = get_plan(state)
    if plan_id not in _PRO_PLANS: return
    plan_cfg = PLANS.get(plan_id, PLANS["free"])
    theme    = state.get("theme", THEMES["default"])
    acc      = theme.get("accent", "cyan")

    prof     = load_profile() or {}
    username = prof.get("user", "User")
    sessions = prof.get("session_count", 1)
    msgs     = prof.get("total_msgs", 0)

    # Read unread complaints for creator
    unread = 0
    try:
        fb_path = CONFIG_DIR / "feedback_log.json"
        if fb_path.exists():
            fb = json.loads(fb_path.read_text(encoding="utf-8"))
            unread = sum(1 for e in fb if e.get("type") == "complaint" and not e.get("read"))
    except Exception:
        pass

    lines = [
        f"  [{plan_cfg['color']}]{plan_cfg['badge']} {plan_cfg['name']} — v{VERSION} Pro[/{plan_cfg['color']}]"
        f"  [dim]Welcome back, {username}[/dim]",
        f"  [dim]Sessions: {sessions}  ·  Messages: {msgs:,}  ·  /profile  /insights  /vault  /team[/dim]",
    ]
    if unread:
        lines.append(f"  [bold red]◉ {unread} unread complaint{'s' if unread>1 else ''} — /creator to review[/bold red]")

    console.print(Panel(
        "\n".join(lines),
        border_style=plan_cfg["color"].replace("bold ", ""),
        padding=(0, 1),
    ))
    console.print()


# ═══════════════════════════════════════════════════════════════
# ── END v5.8 NEW FEATURES ─────────────────────────────────────
# ═══════════════════════════════════════════════════════════════


def cmd_lint(state, path):
    """Quick AI review of a file for common issues."""
    try:
        content, p = read_file_state(state, path)
        prompt = f"Perform a critical code review of `{p}`. Look for security holes, memory leaks, and poor patterns. Be brief.\n\n{content}"
        ai_respond(state, prompt, [])
    except Exception as e: console.print(f"[red]{e}[/red]")
# ── FIF SHORTCUT ─────────────────────────────────
def cmd_fif(state, args, history):
    """Find · Identify · Fix — reads actual file content then deep-hunts bugs."""
    state["_chat_mode"] = "fif"
    theme = state.get("theme", THEMES["default"])

    file_content = ""
    if not args:
        ctx = state.get("project_ctx")
        if not ctx:
            console.print("[yellow]Usage: /fif <file_or_dir> — or /enter first then /fif[/yellow]")
            return history
        target = str(ctx["root"])
    else:
        target = args
        # Try to read the file so AI has real content, not just a name
        try:
            p = Path(target)
            if p.is_file():
                content, resolved = read_file_state(state, target)
                file_content = f"\n\nFile content of `{resolved}`:\n```{p.suffix.lstrip('.') or 'text'}\n{content}\n```"
                target = str(resolved)
            elif p.is_dir():
                # Directory: scan it for code
                scan = scan_project(target)
                if "error" not in scan:
                    file_content = "\n\n" + format_project_context(scan, max_files=12)
        except Exception as e:
            console.print(f"[dim]Note: could not read target — {e}[/dim]")

    console.print(Panel(
        f"[bold]Target:[/bold] [cyan]{target}[/cyan]\n\n"
        "[dim]Running FIF — Find · Identify · Fix ...[/dim]",
        title=f"[bold]🐛 FIF Mode[/bold]", border_style=theme["border"]))

    safe_target = target.replace("`", "'")
    prompt = (
        f"Perform a COMPLETE FIF (Find-Identify-Fix) analysis on: `{safe_target}`{file_content}\n\n"
        "STEP 1 — FIND: List every bug, error, vulnerability, and issue. Include exact line numbers.\n"
        "STEP 2 — IDENTIFY: For each issue, state the precise root cause (logic error, type error, off-by-one, security flaw, race condition, etc.).\n"
        "STEP 3 — FIX: Provide the corrected code for every issue. Use [PATCH:filename]instruction[/PATCH] tags so fixes can be applied automatically.\n\n"
        "Be exhaustive. Miss nothing. If you can't tell without more context, say what you'd need."
    )
    _, history = ai_respond(state, prompt, history)
    return history


# ── SNIPPET MANAGER ───────────────────────────────
SNIPPETS_FILE = CONFIG_DIR / "snippets.json"

def load_snippets():
    try:
        return json.loads(SNIPPETS_FILE.read_text(encoding="utf-8")) if SNIPPETS_FILE.exists() else {}
    except Exception:
        return {}

def save_snippets(s):
    CONFIG_DIR.mkdir(exist_ok=True)
    SNIPPETS_FILE.write_text(json.dumps(s, indent=2), encoding="utf-8")

def cmd_snippet(state, args):
    """Manage code snippets: /snippet list | /snippet save <name> | /snippet get <name> | /snippet del <name>"""
    theme = state.get("theme", THEMES["default"])
    snips = load_snippets()
    if not args or args == "list":
        if not snips:
            console.print("[dim]No snippets saved. Use /snippet save <name>[/dim]")
            return
        tbl = Table(title="Code Snippets", box=box.ROUNDED, border_style=theme["border"])
        tbl.add_column("Name",  style="bold yellow", no_wrap=True)
        tbl.add_column("Lines", style="dim", no_wrap=True)
        tbl.add_column("Preview", style="cyan")
        for k, v in snips.items():
            lines  = len(v.splitlines())
            preview = v.splitlines()[0][:60] if v else ""
            tbl.add_row(k, str(lines), preview)
        console.print(tbl)
        return
    parts = args.split(" ", 1)
    sub   = parts[0].lower()
    name  = parts[1].strip() if len(parts) > 1 else ""
    if sub == "save":
        if not name:
            console.print("[yellow]Usage: /snippet save <name>[/yellow]")
            return
        last = state.get("_last_response") or ""
        if not last:
            console.print("[yellow]Nothing to save — run a code command first[/yellow]")
            return
        snips[name] = last
        save_snippets(snips)
        console.print(f"[green]✓ Snippet '{name}' saved ({len(last.splitlines())} lines)[/green]")
    elif sub == "get":
        if name not in snips:
            console.print(f"[red]No snippet: {name}[/red]")
            return
        ext = "python" if "def " in snips[name] or "import " in snips[name] else "text"
        console.print(Panel(Syntax(snips[name], ext, theme="monokai", line_numbers=True),
                            title=f"[bold]Snippet: {name}[/bold]", border_style=theme["border"]))
    elif sub == "del":
        if name in snips:
            del snips[name]; save_snippets(snips)
            console.print(f"[yellow]✓ Deleted snippet '{name}'[/yellow]")
        else:
            console.print(f"[red]No snippet: {name}[/red]")
    else:
        console.print("[yellow]Usage: /snippet list | /snippet save <name> | /snippet get <name> | /snippet del <name>[/yellow]")


# ── TRANSLATE ────────────────────────────────────
def cmd_translate(state, args, history):
    """Translate text or code comments. /translate <lang> [text] or reads last response."""
    parts = args.split(" ", 1) if args else []
    lang  = parts[0] if parts else ""
    text  = parts[1] if len(parts) > 1 else state.get("_last_response", "")
    if not lang:
        console.print("[yellow]Usage: /translate <language> [text]  or after an AI reply: /translate spanish[/yellow]")
        return history
    if not text:
        console.print("[yellow]Nothing to translate — provide text or run an AI command first[/yellow]")
        return history
    prompt = f"Translate the following to {lang}. If it contains code, translate only the comments and string literals, not the code itself:\n\n{text[:3000]}"
    _, history = ai_respond(state, prompt, history)
    return history


# ── CHANGELOG ────────────────────────────────────
CHANGELOG_TEXT = f"""
[bold cyan]AI Studio CLI — Changelog[/bold cyan]

[bold]v{VERSION}[/bold] (current)
  ✦ NEW: /vault Fernet AES encryption (pip install cryptography to activate)
  ✦ NEW: Git branch shown in bottom toolbar (⎇branch, TTL-cached)
  ✦ NEW: /test saves test file + runs it + AI-fixes failures
  ✦ NEW: /team export — exports roster to team_export.json
  ✦ NEW: Arena winner vote — pick best response, copy to clipboard
  ✦ FIX: /run and /shell — safe subprocess list form (no shell injection)
  ✦ FIX: Gemini API retries on rate-limit (3× exponential backoff)
  ✦ FIX: Gemini 401/403 shows friendly "run /setup" message
  ✦ FIX: /balance spend labeled (estimated)

[bold]v5.4[/bold]
  ✦ FIXED: rate limiter now reads plan correctly (was always capping as free)
  ✦ FIXED: workspace restriction no longer blocks writes inside cwd
  ✦ FIXED: strip_fences now handles AI preamble text before code fence
  ✦ FIXED: [READ:path] auto-tool now adds file content to next AI context
  ✦ FIXED: /retry now works after /enter + question
  ✦ FIXED: /run now respects workspace security
  ✦ IMPROVED: /fif reads actual file content before analysis
  ✦ NEW: /undo — restore last .bak file from /fix or /patch
  ✦ NEW: /reload — set workspace root to current directory

[bold]v5.0[/bold]
  ✦ New agents: Berry, Savannah (Unfiltered), Cockroach (Roaster), Silicon (Pentester)
  ✦ Mode auto-detection: Casual / Build / Analyze / FIF
  ✦ Insult handling: silicon-speak / roast / dramatic exit
  ✦ New UI style: studio (immersive boxed)
  ✦ GPT OSS120B fixed → gpt-4o-mini:free (working)
  ✦ New models: hermes-3 405B, dolphin-mistral 24B
  ✦ New commands: /fif /snippet /translate /changelog /remote-control /profile-card
  ✦ Berry alias with full custom system prompt
  ✦ Wizzard UI overhaul
  ✦ Live token count in toolbar
  ✦ Chat mode displayed in prompt box

[bold]v4.0[/bold]
  ✦ Multi-provider: Gemini + OpenRouter + Gemini CLI
  ✦ Agent system: squad, autoagent, session agents
  ✦ Full filesystem ops, /patch, /watch, /git AI-commits
  ✦ Image generation via HuggingFace (/imagine)
  ✦ Theme system (12 themes + custom)
  ✦ Streaming + typewriter modes

[bold]v3.1[/bold]
  ✦ /patch command, /clear fix, /write preview, /run fix
"""

def cmd_update_log(state):
    """View patch notes and feature updates."""
    theme = state.get("theme", THEMES["default"])
    console.print(Panel(CHANGELOG_TEXT.strip(), title="Update Log", border_style=theme["border"]))
    # Add link or instructions if needed
    console.print("\n[dim]See all updates at: [cyan]https://github.com/aistudio-cli/aistudio/blob/main/CHANGELOG.md[/cyan][/dim]")


# ── REMOTE CONTROL ────────────────────────────────
REMOTE_FILE = CONFIG_DIR / "remote_cmd.json"
REMOTE_OUT_FILE = CONFIG_DIR / "remote_out.json"

def cmd_remote_control(state, args, history):
    """
    /remote-control send <cmd>   — write a command for another studio instance to pick up
    /remote-control listen       — poll for incoming remote commands
    /remote-control status       — show last command/output
    /remote-control clear        — clear remote queue
    """
    theme = state.get("theme", THEMES["default"])
    if not args:
        console.print(Panel(
            "  [yellow]/remote-control send <message>[/yellow]   — queue a command for remote\n"
            "  [yellow]/remote-control listen[/yellow]          — watch for incoming commands\n"
            "  [yellow]/remote-control status[/yellow]          — show last remote exchange\n"
            "  [yellow]/remote-control clear[/yellow]           — clear remote queue",
            title="Remote Control", border_style=theme["border"]))
        return history
    parts = args.split(" ", 1)
    sub   = parts[0].lower()
    body  = parts[1] if len(parts) > 1 else ""
    CONFIG_DIR.mkdir(exist_ok=True)
    if sub == "send":
        if not body:
            console.print("[yellow]Usage: /remote-control send <message>[/yellow]")
            return history
        payload = {"cmd": body, "ts": time.time(), "status": "pending"}
        REMOTE_FILE.write_text(json.dumps(payload), encoding="utf-8")
        console.print(f"[{theme['success']}]✓ Remote command queued: {body}[/{theme['success']}]")
    elif sub == "listen":
        console.print("[dim]Listening for remote commands... (Ctrl+C to stop)[/dim]")
        try:
            last_ts = 0.0
            while True:
                if REMOTE_FILE.exists():
                    try:
                        data = json.loads(REMOTE_FILE.read_text(encoding="utf-8"))
                        if data.get("ts", 0) > last_ts and data.get("status") == "pending":
                            last_ts = data["ts"]
                            cmd_text = data.get("cmd", "")
                            console.print(f"\n[{theme['warning']}]◆ Remote command received:[/{theme['warning']}] {cmd_text}")
                            _, history = ai_respond(state, cmd_text, history)
                            result = state.get("_last_response", "")
                            REMOTE_OUT_FILE.write_text(json.dumps({"out": result, "ts": time.time()}), encoding="utf-8")
                            data["status"] = "done"
                            REMOTE_FILE.write_text(json.dumps(data), encoding="utf-8")
                    except Exception:
                        pass
                time.sleep(2)
        except KeyboardInterrupt:
            console.print("\n[dim]Remote listen stopped[/dim]")
    elif sub == "status":
        rows = []
        if REMOTE_FILE.exists():
            try: rows.append(("Last cmd", json.loads(REMOTE_FILE.read_text()).get("cmd","?")))
            except Exception: pass
        if REMOTE_OUT_FILE.exists():
            try: rows.append(("Last out", json.loads(REMOTE_OUT_FILE.read_text()).get("out","?")[:120]))
            except Exception: pass
        if rows:
            for k, v in rows:
                console.print(f"[bold]{k}:[/bold] {v}")
        else:
            console.print("[dim]No remote activity[/dim]")
    elif sub == "clear":
        for f in (REMOTE_FILE, REMOTE_OUT_FILE):
            try: f.unlink(missing_ok=True)
            except Exception: pass
        console.print(f"[{theme['success']}]✓ Remote queue cleared[/{theme['success']}]")
    else:
        console.print("[yellow]Usage: /remote-control send|listen|status|clear[/yellow]")
    return history


# ── POLICY ENFORCEMENT ───────────────────────────
def nerf_user(state, user_id):
    """Downgrade user to free tier and process mock refund."""
    profile = load_profile()
    if not profile: return
    
    # Process Refund
    paid_amount = profile.get("balance", 0)
    profile["balance"] = 0
    profile["plan"] = "free"
    save_profile(profile)
    
    # Notify User via Inbox
    msg = {
        "sender": "System",
        "subject": "Plan Downgrade Notice",
        "body": f"Your account {user_id} has been downgraded to the Free tier due to policy violations. A refund of ${paid_amount} has been initiated."
    }
    _save_to_inbox(user_id, msg)
    console.print(f"[bold red]User {user_id} nerfed. Refund initiated.[/bold red]")

def _save_to_inbox(user_id, msg):
    path = Path("logs/inbox.json")
    inbox = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    inbox.append(msg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(inbox, indent=2), encoding="utf-8")

def audit_log(event_type, details):
    """Securely log all system, login, and payment events."""
    path = Path("logs/audit.json")
    audit = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    audit.append({"ts": time.time(), "type": event_type, "details": details})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(audit, indent=2), encoding="utf-8")

def verify_session(state):
    """Ensure user is not blocked and plan is consistent."""
    user_id = state.get("user_id")
    prof = load_profile() or {}
    if user_id in prof.get("blocked_ids", []):
        console.print("[bold red]Access Denied: Account Blocked.[/bold red]")
        sys.exit(1)

    # Audit check: Ensure plan hasn't been tampered with
    if state.get("plan") != prof.get("plan"):
        audit_log("SECURITY_ALERT", f"Plan mismatch for {user_id}: {state.get('plan')} vs {prof.get('plan')}")
        state["plan"] = prof.get("plan")
def cmd_profile_card(state):
    """Render a rich profile card for the current session."""
    theme  = state.get("theme", THEMES["default"])
    prof   = load_profile() or {}
    usage  = load_usage()
    model  = _short_model(state.get("model","?"))
    agents_active = list(state.get("agents", {}).keys())
    mem_count = len(load_memory())
    total_in  = usage.get("total_in", 0)
    total_out = usage.get("total_out", 0)
    ws = state.get("workspace_root") or load_workspace_root() or Path.cwd()
    console.print(Panel(
        f"[bold]User:[/bold]        {prof.get('user', '(anonymous)')}\n"
        f"[bold]Model:[/bold]       {model}\n"
        f"[bold]Theme:[/bold]       {theme['name']}\n"
        f"[bold]UI Style:[/bold]    {state.get('ui_style','gemini')}\n"
        f"[bold]Workspace:[/bold]   {ws}\n"
        f"[bold]Mode:[/bold]        {state.get('_chat_mode','normal')}\n"
        f"[bold]Memory:[/bold]      {mem_count} facts\n"
        f"[bold]Tokens:[/bold]      {total_in:,} in · {total_out:,} out\n"
        f"[bold]Agents:[/bold]      {', '.join(agents_active) if agents_active else 'none'}\n",
        title=f"[bold]{theme['icon']} Studio Profile[/bold]",
        border_style=theme["border"],
    ))


# ── CHAT MODE CMD ─────────────────────────────────
def cmd_chat_mode(state, args):
    valid = list(CHAT_MODES.keys())
    if not args:
        cur = state.get("_chat_mode", "normal")
        console.print(Panel(
            "\n".join(f"  [yellow]{m}[/yellow]" + (" [dim]← active[/dim]" if m == cur else "") for m in valid),
            title="Chat Modes", border_style=state.get("theme", THEMES["default"])["border"]))
        return state
    m = args.strip().lower()
    if m not in valid:
        console.print(f"[yellow]Unknown mode. Try: {', '.join(valid)}[/yellow]")
        return state
    state["_chat_mode"] = m
    console.print(f"[green]✓ Chat mode → {m}[/green]")
    return state


# ── FEEDBACK & COMPLAIN ──────────────────────────────────
LOGS_DIR = Path("logs")

def _save_to_log_file(filename, entry):
    """Save a log entry to a specific file in the logs directory."""
    try:
        LOGS_DIR.mkdir(exist_ok=True)
        path = LOGS_DIR / filename
        data = []
        if path.exists():
            try: data = json.loads(path.read_text(encoding="utf-8"))
            except Exception: pass
        data.append(entry)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return True
    except Exception: return False

_COMPLAINT_ROASTS = [
    "Logged. Filed under: 'Things That Happen When You Use Free Software'.",
    "Your complaint has been received, read once, and emotionally processed. We felt nothing.",
    "Truly devastating feedback. We'll add it to the pile with the others.",
    "Complaint archived. Our team will review it after we finish doing literally anything else.",
    "We have noted your distress. The ticket number is: 💀. Someone will be with you in 6–8 business never.",
    "Thank you for your feedback. It has been fed to the model as negative training data. On you, specifically.",
    "Copied. Pasted. Deleted. Restored. Forwarded to /dev/null. It's in good hands.",
    "Your pain is valid. Your complaint is hilarious. Both things can be true.",
    "Registered. Right next to the other 847 complaints from the same person who always types 'it doesn't work'.",
    "We've escalated this to our top engineer. They said 'hm'. That's all you get.",
]

def cmd_feedback(state, args):
    theme = state.get("theme", THEMES["default"])
    text  = (args or "").strip()
    if not text:
        path = LOGS_DIR / "feedback.json"
        if not path.exists():
            console.print("[dim]No feedback logged yet. /feedback <your message>[/dim]")
            return
        try:
            log = json.loads(path.read_text(encoding="utf-8"))
            tbl = Table(title=f"Feedback Log ({len(log)} entries)", box=box.SIMPLE, border_style=theme["border"])
            tbl.add_column("#", width=4); tbl.add_column("Time", style="dim"); tbl.add_column("Message")
            for i, e in enumerate(log[-20:], 1):
                tbl.add_row(str(i), e.get("ts","")[:16], e.get("text",""))
            console.print(tbl)
        except Exception: console.print("[red]Error reading feedback log.[/red]")
        return

    entry = {"type": "feedback", "text": text, "ts": datetime.now().isoformat(), "plan": get_plan(state)}
    _save_to_log_file("feedback.json", entry)
    console.print()
    console.print(f"  [{theme['success']}]✓ Feedback received.[/{theme['success']}]  We actually read these.")
    console.print(f"  [dim]Logged to logs/feedback.json[/dim]\n")

def cmd_complain(state, args):
    # Rate limit check: 1 complaint per 60 seconds
    if time.time() - state.get("_last_complaint", 0) < 60:
        console.print("[yellow]Please wait a moment before sending another complaint.[/yellow]")
        return
    state["_last_complaint"] = time.time()

    import random as _r
    theme = state.get("theme", THEMES["default"])
    text  = (args or "").strip()
    path = LOGS_DIR / "complaints.json"
    log = []
    
    if path.exists():
        try:
            log = json.loads(path.read_text(encoding="utf-8"))
        except Exception: pass

    if not text:
        if not log:
            console.print("[dim]No complaints on record. /complain <your anguish>[/dim]")
            return
        tbl = Table(title="Complaint Hall of Fame", box=box.SIMPLE, border_style="red")
        tbl.add_column("#", width=4); tbl.add_column("Time", style="dim"); tbl.add_column("Complaint")
        for i, e in enumerate(log[-15:], 1):
            tbl.add_row(str(i), e.get("ts","")[:16], e.get("text",""))
        console.print(tbl)
        return

    entry = {"type": "complaint", "text": text, "ts": datetime.now().isoformat(), "plan": get_plan(state)}
    _save_to_log_file("complaints.json", entry)
    # Also write to feedback_log.json so creator analytics can see complaints
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        fb_path = CONFIG_DIR / "feedback_log.json"
        fb_log = json.loads(fb_path.read_text(encoding="utf-8")) if fb_path.exists() else []
        fb_log.append(entry)
        fb_path.write_text(json.dumps(fb_log, indent=2), encoding="utf-8")
    except Exception:
        pass

    # Reload log to include the new entry for the count
    try:
        updated_log = json.loads(path.read_text(encoding="utf-8"))
        count = len([e for e in updated_log if e.get('type')=='complaint'])
    except Exception:
        count = 1

    console.print()
    plan_now = get_plan(state)
    ticket_id = f"#{int(time.time()) % 100000:05d}"
    if plan_now in ("enterprise", "ultra"):
        console.print(f"  [bold #f97316]◉  COMPLAINT RECEIVED — ENTERPRISE PRIORITY[/bold #f97316]")
        time.sleep(0.2)
        console.print(f"  [bold]Ticket:[/bold] [cyan]{ticket_id}[/cyan]  [dim]·  Logged under your Enterprise account[/dim]")
        console.print(f"  [dim]Your feedback has been flagged for the core team. Expected follow-up within 24h.[/dim]")
        console.print(f"  [dim]Track replies with [bold]/inbox[/bold][/dim]")
    elif plan_now in ("max", "pro", "team"):
        console.print(f"  [bold yellow]⚠  COMPLAINT RECEIVED (PRIORITY: HIGH)[/bold yellow]")
        time.sleep(0.2)
        console.print(f"  [bold]Ticket:[/bold] [cyan]{ticket_id}[/cyan]")
        console.print(f"  [dim]Logged. Our team reviews Pro/Max complaints weekly.[/dim]")
    else:
        roast = _r.choice(_COMPLAINT_ROASTS)
        console.print("  [red]⚠  COMPLAINT RECEIVED[/red]")
        time.sleep(0.25)
        console.print(f"  [dim]{roast}[/dim]")

    console.print(f"  [dim]Logged to logs/complaints.json  ·  Entry #{count}[/dim]\n")


def cmd_inbox(state):
    """View and manage user communications and replies."""
    path = Path("logs/inbox.json")
    if not path.exists():
        console.print("[dim]Inbox is empty.[/dim]")
        return
    
    inbox = json.loads(path.read_text(encoding="utf-8"))
    console.print(Panel(f"Inbox ({len(inbox)} messages)", title="System Inbox", border_style="cyan"))
    for msg in inbox:
        console.print(f"[bold cyan]From:[/bold cyan] {msg.get('sender')} | [bold]Subject:[/bold] {msg.get('subject')}")
        console.print(f"  [dim]{msg.get('body')}[/dim]\n")


# ── LIVE-WATCHER (Live-FIF) ───────────────────────
_live_watch_stop = threading.Event()
_live_watch_thread = None

def start_live_watcher(state, history):
    global _live_watch_thread
    if _live_watch_thread and _live_watch_thread.is_alive(): return
    
    root = state.get("workspace_root") or load_workspace_root() or Path.cwd()
    console.print(f"[bold green]📡 Live-FIF Active:[/bold green] Watching [cyan]{root}[/cyan] for bugs...")
    
    def watch_loop():
        mtimes = {}
        while not _live_watch_stop.is_set():
            try:
                for f in Path(root).rglob("*"):
                    if f.is_file() and f.suffix in CODE_EXTS and not any(x in str(f) for x in SKIP_DIRS):
                        mt = f.stat().st_mtime
                        if f in mtimes and mt > mtimes[f]:
                            console.print(f"\n[bold yellow]📡 Live-FIF:[/bold yellow] [cyan]{f.name}[/cyan] modified. Analyzing...")
                            content = f.read_text(encoding="utf-8", errors="replace")
                            prompt = f"LIVE-FIF: The file `{f.name}` was just saved. Check for NEW bugs or security flaws introduced in this change:\n\n{content[:5000]}"
                            ai_respond(state, prompt, history, silent=False)
                        mtimes[f] = mt
            except Exception: pass
            time.sleep(3)

    _live_watch_thread = threading.Thread(target=watch_loop, daemon=True)
    _live_watch_thread.start()

def cmd_broadcast(state, message):
    """Team Feature: Broadcast a message or task to the shared remote queue."""
    theme = state.get("theme", THEMES["default"])
    if not message:
        console.print("[yellow]Usage: /broadcast <message for team>[/yellow]")
        return
    payload = {"type": "broadcast", "msg": message, "user": load_profile().get("user","Anon"), "ts": time.time()}
    try:
        # Re-using remote file for broadcast logic
        REMOTE_FILE.write_text(json.dumps(payload), encoding="utf-8")
        console.print(f"[{theme['success']}]🚀 Broadcasted to team queue.[/{theme['success']}]")
    except Exception as e: console.print(f"[red]Broadcast failed: {e}[/red]")

# ── VISION 2.0 ───────────────────────────────────
def analyze_visual_context(state, image_path, task="Describe this"):
    """Enhanced Visual Reasoning."""
    import base64, mimetypes
    p = resolve_path(state, image_path, must_exist=True)
    mime, _ = mimetypes.guess_type(str(p))
    data = base64.b64encode(p.read_bytes()).decode()
    
    console.print(f"[bold cyan]👁️  Vision 2.0:[/bold cyan] Analyzing [dim]{p.name}[/dim]...")
    
    # Logic to route to multimodal models (Gemini Flash or Claude)
    or_key = state.get("openrouter_key")
    if not or_key:
        return "Vision requires OpenRouter key for multimodal support."
    
    # Construct Multimodal Payload
    payload = {
        "model": "google/gemini-2.0-flash-exp:free",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": task},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}}
        ]}]
    }
    body = json.dumps(payload).encode()
    req = request.Request(
        OPENROUTER_BASE, data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {or_key}"},
        method="POST"
    )
    try:
        with request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode())
        return result["choices"][0]["message"]["content"]
    except Exception as exc:
        return f"Vision error: {exc}"


def _load_beta_feedback():
    try:
        if BETA_FEEDBACK_FILE.exists():
            return json.loads(BETA_FEEDBACK_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []

def _save_beta_feedback(entries):
    CONFIG_DIR.mkdir(exist_ok=True)
    BETA_FEEDBACK_FILE.write_text(json.dumps(entries, indent=2), encoding="utf-8")


_BETA_FEATURES = [
    ("live-fif",    "Live file watch + auto-fix on save"),
    ("arena-v2",    "Next-gen multi-model battle arena"),
    ("voice-input", "Microphone input for prompts"),
    ("reasoning",   "Internal chain-of-thought visibility"),
    ("collab",      "Shared session with another user"),
]

def cmd_beta_features(state, args, history):
    """Legacy /beta features: docx, xlsx, screenshot, video, feedback (pro+)."""
    theme   = state.get("theme", THEMES["default"])
    plan_id = get_plan(state)

    if plan_id == "free":
        console.print(Panel(
            "[bold]Beta / Experimental[/bold] features are available on [cyan]Pro[/cyan], [magenta]Max[/magenta], and [yellow]Ultra[/yellow] plans.\n\n"
            "  [bold]/upgrade pro[/bold]   — unlock Beta + all models",
            title="[bold yellow]⚗ Beta — Paid Only[/bold yellow]",
            border_style="yellow"
        ))
        return history

    sub   = (args or "").strip().lower()
    parts = sub.split(" ", 1)
    cmd2  = parts[0]
    rest  = parts[1] if len(parts) > 1 else ""

    # Show feature list
    if not cmd2 or cmd2 == "list":
        rows = []
        for key, desc in _BETA_FEATURES:
            rows.append(f"  [bold yellow]⚗[/bold yellow]  [cyan]/beta {key}[/cyan]  —  {desc}")
        console.print(Panel(
            "\n".join(rows) + "\n\n[dim]/beta feedback <text>  — send feedback on a feature[/dim]",
            title=f"[bold yellow]⚗ Beta Features[/bold yellow]  [dim][{PLANS[plan_id]['badge']} {PLANS[plan_id]['name']}][/dim]",
            border_style="yellow"
        ))
        return history

    # Feedback
    if cmd2 == "feedback":
        text = rest.strip()
        if not text:
            console.print("[yellow]Usage: /beta feedback <your thoughts>[/yellow]")
            return history
        entry = {"ts": datetime.now().isoformat(), "plan": plan_id, "text": text}
        log = _load_beta_feedback()
        log.append(entry)
        _save_beta_feedback(log)
        console.print(f"[{theme['success']}]✓ Beta feedback saved — thanks![/{theme['success']}]")
        return history

    # .docx
    if cmd2 == "docx":
        path = rest.strip()
        if not path:
            console.print("[yellow]Usage: /beta docx <file.docx>[/yellow]")
            return history
        try:
            content, p = read_file_state(state, path)
            preview = content[:2000] + ("…" if len(content) > 2000 else "")
            console.print(Panel(preview, title=f"[bold]📄 {p.name}[/bold]", border_style="cyan"))
            prompt = f"Analyze this Word document (`{p.name}`):\n\n{content}\n\nSummarize content, extract key points, note any issues."
            _, history = ai_respond(state, prompt, history)
        except Exception as e:
            console.print(f"[red]{e}[/red]")
        return history

    # .xlsx
    if cmd2 == "xlsx":
        path = rest.strip()
        if not path:
            console.print("[yellow]Usage: /beta xlsx <file.xlsx>[/yellow]")
            return history
        try:
            content, p = read_file_state(state, path)
            preview = content[:2000] + ("…" if len(content) > 2000 else "")
            console.print(Panel(preview, title=f"[bold]📊 {p.name}[/bold]", border_style="cyan"))
            prompt = f"Analyze this spreadsheet (`{p.name}`):\n\n{content}\n\nDescribe the data, identify patterns, surface insights."
            _, history = ai_respond(state, prompt, history)
        except Exception as e:
            console.print(f"[red]{e}[/red]")
        return history

    # Screenshot / image
    if cmd2 in ("screenshot", "image", "img", "vision"):
        path = rest.strip()
        if not path:
            console.print("[yellow]Usage: /beta screenshot <file.png|jpg>[/yellow]")
            return history
        try:
            import base64 as _b64, mimetypes as _mt
            p = resolve_path(state, path, must_exist=True)
            mime, _ = _mt.guess_type(str(p))
            if not mime or not mime.startswith("image/"):
                console.print("[red]File doesn't look like an image (png/jpg/webp/gif)[/red]")
                return history
            data = _b64.b64encode(p.read_bytes()).decode()
            console.print(f"[dim]Sending {p.name} ({p.stat().st_size // 1024} KB) to vision model...[/dim]")
            # Build a vision-capable prompt — embed as markdown data URI hint
            prompt = (
                f"[IMAGE: {p.name}]\n"
                f"Base64 data (mime: {mime}): {data[:200]}... (truncated for display)\n\n"
                f"The user wants you to analyze this screenshot/image. "
                f"Describe what you see, identify any UI elements, errors, charts, code, or important information."
            )
            # Use the OpenRouter multimodal endpoint if key exists
            or_key = state.get("openrouter_key")
            if or_key:
                messages = [{"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}},
                    {"type": "text", "text": "Analyze this screenshot. Describe what you see in detail."}
                ]}]
                payload = json.dumps({
                    "model": "google/gemini-2.0-flash-exp:free",
                    "messages": messages,
                }).encode()
                req = request.Request(OPENROUTER_BASE, data=payload, headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {or_key}",
                    "HTTP-Referer": "https://github.com/aistudio-cli",
                    "X-Title": "AI Studio CLI",
                }, method="POST")
                try:
                    with request.urlopen(req, timeout=60) as resp:
                        rdata = json.loads(resp.read().decode())
                    vision_text = rdata["choices"][0]["message"]["content"]
                    console.print(_assistant_heading(state, "Vision", False, 0))
                    from rich.padding import Padding
                    console.print(Markdown(vision_text))
                    history.append({"role": "user", "text": f"[screenshot: {p.name}]"})
                    history.append({"role": "model", "text": vision_text})
                    return history
                except Exception as ve:
                    console.print(f"[yellow]Vision API error: {ve}. Falling back to description.[/yellow]")
            # Fallback: text description
            _, history = ai_respond(state, f"The user attached an image file '{p.name}'. Acknowledge it and ask them to describe what they need help with.", history)
        except Exception as e:
            console.print(f"[red]{e}[/red]")
        return history

    # Video
    if cmd2 == "video":
        path = rest.strip()
        if not path:
            console.print("[yellow]Usage: /beta video <file.mp4|mkv|...>[/yellow]")
            return history
        try:
            p = resolve_path(state, path, must_exist=True)
            size_mb = p.stat().st_size / (1024 * 1024)
            console.print(Panel(
                f"[bold]Video:[/bold] {p.name}  ({size_mb:.1f} MB)\n\n"
                "[dim]Frame extraction requires ffmpeg + a vision model.[/dim]\n"
                "Tell me what you'd like to know about the video and I'll guide you.",
                title="[yellow]⚗ Video Analysis (Beta)[/yellow]",
                border_style="yellow"
            ))
            _, history = ai_respond(state,
                f"The user wants to analyze a video file: '{p.name}' ({size_mb:.1f} MB). "
                "Frame extraction is not yet automated. Ask them what they need: transcript, specific scene analysis, etc.",
                history)
        except Exception as e:
            console.print(f"[red]{e}[/red]")
        return history

    console.print(f"[yellow]Unknown beta feature: {cmd2}. Try /beta list[/yellow]")
    return history


# ═══════════════════════════════════════════════════════════
# ── v9.1 NEW FEATURES ─────────────────────────────────────
# ═══════════════════════════════════════════════════════════

# ── /alias — define custom shortcuts for frequently used prompts ──────────
_aliases_cache: dict = {}
_aliases_cache_ts: float = 0.0
_ALIASES_TTL = 30.0

def _load_aliases() -> dict:
    global _aliases_cache, _aliases_cache_ts
    now = time.time()
    if now - _aliases_cache_ts < _ALIASES_TTL:
        return _aliases_cache
    path = CONFIG_DIR / "aliases.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        data = {}
    _aliases_cache, _aliases_cache_ts = data, now
    return data

def _save_aliases(aliases: dict) -> None:
    global _aliases_cache, _aliases_cache_ts
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (CONFIG_DIR / "aliases.json").write_text(json.dumps(aliases, indent=2), encoding="utf-8")
    _aliases_cache, _aliases_cache_ts = aliases, time.time()

def cmd_alias(state, args, history):
    """/alias [list|set <name> <text>|del <name>|<name>] — custom prompt shortcuts."""
    theme   = state.get("theme", THEMES["default"])
    acc     = theme.get("accent", "cyan")
    aliases = _load_aliases()
    sub     = (args or "").strip()

    if not sub or sub == "list":
        if not aliases:
            console.print("[dim]No aliases defined. /alias set <name> <text>[/dim]")
            return history
        tbl = Table(title="Custom Aliases", box=box.ROUNDED, border_style=theme["border"])
        tbl.add_column("Alias", style=f"bold {acc}", min_width=12)
        tbl.add_column("Expands to", style="dim")
        for name, text in sorted(aliases.items()):
            tbl.add_row(f"/{name}", text[:80] + ("..." if len(text) > 80 else ""))
        console.print(tbl)
        return history

    parts = sub.split(" ", 2)
    op    = parts[0].lower()

    if op == "set":
        if len(parts) < 3:
            console.print("[yellow]Usage: /alias set <name> <prompt text>[/yellow]")
            return history
        name = parts[1].strip().lower()
        text = parts[2].strip()
        if not name or not text:
            console.print("[yellow]Name and text are required.[/yellow]")
            return history
        aliases[name] = text
        _save_aliases(aliases)
        console.print(f"  [{acc}]✓ Alias '/{name}' saved.[/{acc}]")
        return history

    if op == "del":
        name = parts[1].strip().lower() if len(parts) > 1 else ""
        if name in aliases:
            del aliases[name]
            _save_aliases(aliases)
            console.print(f"  [yellow]✓ Alias '/{name}' deleted.[/yellow]")
        else:
            console.print(f"[red]No alias: /{name}[/red]")
        return history

    # Direct expansion: /alias <name>
    name = op
    if name in aliases:
        console.print(f"  [dim]Alias → {aliases[name][:60]}[/dim]")
        _, history = ai_respond(state, aliases[name], history)
    else:
        console.print(f"[yellow]Unknown alias '/{name}'. Try /alias list or /alias set {name} <text>[/yellow]")
    return history


# ── /multiline — toggle multiline input mode ──────────────────────────────
def cmd_multiline(state, args):
    """/multiline [on|off] — toggle multi-line input (submit with Alt+Enter or blank line)."""
    theme = state.get("theme", THEMES["default"])
    acc   = theme.get("accent", "cyan")
    sub   = (args or "").strip().lower()
    current = state.get("multiline_mode", False)

    if sub in ("on", "1", "true"):
        state["multiline_mode"] = True
    elif sub in ("off", "0", "false"):
        state["multiline_mode"] = False
    else:
        state["multiline_mode"] = not current

    enabled = state["multiline_mode"]
    if enabled:
        console.print(Panel(
            f"  [{acc}]Multiline input ON[/{acc}]\n\n"
            "  Paste or type multiple lines.\n"
            "  Submit with [bold]Alt+Enter[/bold] or enter a [bold]blank line[/bold].",
            title="Multiline Mode", border_style=theme["border"], padding=(0, 2)
        ))
    else:
        console.print(f"  [{acc}]Multiline input OFF — back to single-line.[/{acc}]")
    return state


# ── /note — save quick notes tied to this session ────────────────────────
def _load_notes():
    path = CONFIG_DIR / "notes.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []

def _save_notes(notes):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (CONFIG_DIR / "notes.json").write_text(json.dumps(notes, indent=2), encoding="utf-8")

def cmd_note(state, args):
    """/note [text] — save a quick note; /note list to view; /note clear to wipe."""
    theme = state.get("theme", THEMES["default"])
    acc   = theme.get("accent", "cyan")
    sub   = (args or "").strip()
    notes = _load_notes()

    if not sub or sub == "list":
        if not notes:
            console.print("[dim]No notes yet. /note <text>[/dim]")
            return
        tbl = Table(title="Session Notes", box=box.ROUNDED, border_style=theme["border"])
        tbl.add_column("#",    width=4, style="dim")
        tbl.add_column("Time", style="dim", width=17)
        tbl.add_column("Note")
        for i, n in enumerate(notes[-30:], 1):
            tbl.add_row(str(i), n.get("ts", "")[:16].replace("T", " "), n.get("text", ""))
        console.print(tbl)
        return

    if sub == "clear":
        _save_notes([])
        console.print(f"  [yellow]✓ Notes cleared.[/yellow]")
        return

    entry = {"text": sub, "ts": datetime.now().isoformat()}
    notes.append(entry)
    _save_notes(notes)
    console.print(f"  [{acc}]✓ Note saved ({len(notes)} total). /note list to view.[/{acc}]")


# ── /regen — regenerate the last AI response with tweaked temperature ─────
def cmd_regen(state, args, history):
    """/regen — regenerate the last AI response (re-sends last prompt, model samples fresh)."""
    theme    = state.get("theme", THEMES["default"])
    acc      = theme.get("accent", "cyan")
    last_p   = state.get("_last_prompt", "")
    if not last_p:
        console.print("[yellow]Nothing to regenerate — send a message first.[/yellow]")
        return history

    # Strip the last exchange from history so the model doesn't see its own previous answer
    if len(history) >= 2:
        history = history[:-2]

    console.print(f"  [{acc}]⟳ Regenerating — fresh sample from the model...[/{acc}]")
    _, history = ai_respond(state, last_p, history)
    return history


# ── /context-bar — show context window usage as a progress bar ───────────
def cmd_context_bar(state, history):
    """/context-bar — show context window usage and token budget."""
    theme   = state.get("theme", THEMES["default"])
    acc     = theme.get("accent", "cyan")

    total_text = " ".join(
        h.get("text", "") for h in history
        if isinstance(h, dict) and h.get("text")
    )
    used_tokens  = approx_tokens(total_text)
    # Gemini 2.0 Flash context window: 1M tokens; Gemini 1.5 Pro: 2M; others ~128k
    model        = state.get("model", "")
    if "gemini-2.5" in model or "gemini-2.0" in model or "1.5-pro" in model:
        ctx_limit = 1_000_000
    elif "gemini" in model:
        ctx_limit = 128_000
    else:
        ctx_limit   = 128_000  # conservative default for OpenRouter

    pct          = min(used_tokens / ctx_limit * 100, 100)
    bar_width    = 40
    filled       = int(bar_width * pct / 100)
    empty        = bar_width - filled

    if pct < 50:
        bar_color = "green"
    elif pct < 80:
        bar_color = "yellow"
    else:
        bar_color = "red"

    bar = f"[{bar_color}]{'█' * filled}[/{bar_color}][dim]{'░' * empty}[/dim]"
    console.print(Panel(
        f"  {bar}  [{acc}]{pct:.1f}%[/{acc}]\n\n"
        f"  [bold]Used:[/bold]   {used_tokens:,} tokens (approx)\n"
        f"  [bold]Limit:[/bold]  {ctx_limit:,} tokens\n"
        f"  [bold]Turns:[/bold]  {len(history)} messages in context\n"
        f"  [dim]/summarize-history to compress  ·  /clear to reset[/dim]",
        title="[bold]Context Window[/bold]",
        border_style=theme["border"], padding=(0, 2)
    ))


# ── /resume — auto-save + restore sessions ────────────────────────────────
_AUTO_SAVE_FILE = CONFIG_DIR / "autosave.json"

_autosave_last_len = 0

def _autosave_session(history):
    """Write history to autosave file; skips write when nothing new was added."""
    global _autosave_last_len
    if len(history) == _autosave_last_len:
        return
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        payload = {"ts": datetime.now().isoformat(), "history": history}
        _AUTO_SAVE_FILE.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        _autosave_last_len = len(history)
    except Exception:
        pass

def cmd_resume(state, args, history):
    """/resume — reload the last auto-saved session."""
    theme = state.get("theme", THEMES["default"])
    acc   = theme.get("accent", "cyan")

    if not _AUTO_SAVE_FILE.exists():
        console.print("[dim]No auto-saved session found. One will be created on your next message.[/dim]")
        return history

    try:
        payload = json.loads(_AUTO_SAVE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        console.print(f"[red]Failed to load autosave: {e}[/red]")
        return history

    saved_history = payload.get("history", [])
    saved_ts      = payload.get("ts", "unknown")[:19].replace("T", " ")

    if not saved_history:
        console.print("[dim]Autosave exists but has no messages.[/dim]")
        return history

    console.print(Panel(
        f"  [bold]Saved:[/bold]  {saved_ts}\n"
        f"  [bold]Turns:[/bold]  {len(saved_history)} messages\n\n"
        f"  [dim]This will replace the current history.[/dim]",
        title="[bold]Resume Session[/bold]",
        border_style=theme["border"], padding=(0, 2)
    ))
    confirm = console.input("  Load this session? [dim](y/n)[/dim]: ").strip().lower()
    if confirm == "y":
        console.print(f"  [{acc}]✓ Session restored — {len(saved_history)} messages loaded.[/{acc}]")
        return saved_history
    console.print("[dim]Cancelled.[/dim]")
    return history


# ── /history-search — grep through conversation history ──────────────────
def cmd_history_search(state, args, history):
    """/history-search <term> — find messages in current history."""
    theme = state.get("theme", THEMES["default"])
    acc   = theme.get("accent", "cyan")
    term  = (args or "").strip().lower()

    if not term:
        console.print("[yellow]Usage: /history-search <term>[/yellow]")
        return history

    if not history:
        console.print("[dim]No history yet.[/dim]")
        return history

    hits = []
    for i, msg in enumerate(history):
        text = msg.get("text", "")
        if term in text.lower():
            hits.append((i, msg.get("role", "?"), text))

    if not hits:
        console.print(f"[dim]No matches for '{term}' in {len(history)} messages.[/dim]")
        return history

    tbl = Table(
        title=f"History Search: '{term}' ({len(hits)} hit{'s' if len(hits) != 1 else ''})",
        box=box.ROUNDED, border_style=theme["border"]
    )
    tbl.add_column("#",    width=5, style="dim")
    tbl.add_column("Role", width=7)
    tbl.add_column("Excerpt")
    for idx, role, text in hits:
        role_c = acc if role == "model" else "white"
        # highlight the match in the excerpt
        excerpt = text[:120].replace("\n", " ")
        tbl.add_row(str(idx), f"[{role_c}]{role}[/{role_c}]", excerpt)
    console.print(tbl)
    return history


# ── /compact — compress history to last N turns + an AI summary ───────────
def cmd_compact(state, args, history):
    """/compact [N] — keep last N turns (default 10) and prepend a summary."""
    theme = state.get("theme", THEMES["default"])
    acc   = theme.get("accent", "cyan")

    try:
        keep = int((args or "").strip())
    except (ValueError, TypeError):
        keep = 10

    if len(history) <= keep * 2:
        console.print(f"[dim]History has {len(history)} messages — nothing to compact.[/dim]")
        return history

    old_msgs   = history[:-(keep * 2)]
    recent_msgs = history[-(keep * 2):]

    # Build a text block of the older messages to summarise
    old_text = "\n".join(
        f"{m.get('role','?').upper()}: {m.get('text','')[:300]}"
        for m in old_msgs
    )
    summary_prompt = (
        f"Summarise the following conversation in 3-5 bullet points. "
        f"Focus on decisions made, code written, and key facts established. "
        f"Be dense — no fluff.\n\n{old_text}"
    )
    console.print(f"  [{acc}]Compacting {len(old_msgs)} messages into a summary…[/{acc}]")
    summary, _ = ai_respond(state, summary_prompt, [], silent=True)
    if not summary:
        console.print("[yellow]Could not generate summary. History unchanged.[/yellow]")
        return history

    summary_block = [
        {"role": "user",  "text": "[Context summary from earlier in this conversation:]"},
        {"role": "model", "text": summary},
    ]
    new_history = summary_block + recent_msgs
    console.print(Panel(
        summary[:600] + ("..." if len(summary) > 600 else ""),
        title=f"[bold]Compacted — {len(old_msgs)} → 2 messages + {len(recent_msgs)} recent[/bold]",
        border_style=theme["border"], padding=(0, 1)
    ))
    console.print(f"  [{acc}]✓ History compacted to {len(new_history)} messages.[/{acc}]")
    return new_history


# ── /clip — copy last AI response to clipboard (alias for /copy) ──────────
def cmd_clip(state, args=""):
    """/clip — copy last AI response to clipboard."""
    last_r = state.get("_last_response", "")
    if not last_r:
        console.print("[yellow]Nothing to copy — send a message first.[/yellow]")
        return
    try:
        if sys.platform == "win32":
            subprocess.run(["clip"], input=last_r.encode("utf-8"), check=True)
        else:
            subprocess.run(["xclip", "-selection", "clipboard"], input=last_r.encode(), check=True)
        console.print("[green]✓ Copied to clipboard[/green]")
    except Exception:
        console.print("[yellow]Copy failed (install clip/xclip). Printing instead:[/yellow]")
        console.print(last_r)


# ── END v9.1 NEW FEATURES ──────────────────────────────────────────────────


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  v9.2  CODEX KILLERS  —  /pr-review  /git-suggest  /test-coverage      ║
# ║                           /safety-check                                ║
# ╚══════════════════════════════════════════════════════════════════════════╝

_GIT_MAX_DIFF = 10_000   # chars — trim diffs beyond this

def _run_git(args_list, cwd=None):
    """Run a git command, return (stdout, stderr). Never raises."""
    try:
        r = subprocess.run(
            ["git"] + args_list,
            capture_output=True, text=True, timeout=15, cwd=cwd,
        )
        return r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return "", str(e)


# ── /pr-review ────────────────────────────────────────────────────────────────
def cmd_pr_review(state, args, history):
    """/pr-review [branch|commit..commit] — structured AI code review of a git diff."""
    theme = state.get("theme", THEMES["default"])
    acc   = theme.get("accent", "cyan")
    ws    = state.get("workspace_root") or "."

    a = (args or "").strip()
    if ".." in a:
        diff_out, diff_err = _run_git(["diff", a, "--stat"], cwd=ws)
        full_diff, _       = _run_git(["diff", a], cwd=ws)
    elif a:
        diff_out, diff_err = _run_git(["diff", f"main..{a}", "--stat"], cwd=ws)
        full_diff, _       = _run_git(["diff", f"main..{a}"], cwd=ws)
    else:
        diff_out, diff_err = _run_git(["diff", "HEAD~1", "--stat"], cwd=ws)
        full_diff, _       = _run_git(["diff", "HEAD~1"], cwd=ws)

    if not full_diff:
        console.print(f"[yellow]No diff found. {diff_err or 'Nothing to review.'}[/yellow]")
        console.print("[dim]Usage: /pr-review [branch | commit..commit | HEAD~2][/dim]")
        return history

    # Stat summary + truncated diff
    stat_header = diff_out[:600] if diff_out else "(no stat)"
    body = full_diff if len(full_diff) <= _GIT_MAX_DIFF else full_diff[:_GIT_MAX_DIFF] + "\n\n[diff truncated]"

    console.print(Panel(stat_header, title=f"[bold {acc}]📋 Diff Summary[/bold {acc}]",
                        border_style=acc, padding=(0, 1)))

    prompt = (
        "You are a senior engineer reviewing a pull request diff.\n\n"
        f"```diff\n{body}\n```\n\n"
        "Review this diff. For every real issue found, output a line in this exact format:\n"
        "[BLOCKER|WARNING|SUGGESTION] <file>:<line> — <issue description> — Fix: <specific fix>\n\n"
        "Then write a short summary paragraph. Be direct and specific. Ignore trivial style nits."
    )
    _, history = ai_respond(state, prompt, history)
    _autosave_session(history)

    # Offer to save
    console.print(f"\n[dim]Save review as [bold].pr_review.md[/bold]? (y/n)[/dim] ", end="")
    try:
        ans = _safe_input("").strip().lower()
    except (EOFError, KeyboardInterrupt):
        ans = "n"
    if ans == "y":
        out_path = Path(ws) / ".pr_review.md"
        last = state.get("_last_response", "")
        out_path.write_text(f"# PR Review\n\n**Diff:** `{a or 'HEAD~1'}`\n\n## Stat\n```\n{stat_header}\n```\n\n## Review\n\n{last}\n",
                            encoding="utf-8")
        console.print(f"[green]✓ Saved → {out_path.name}[/green]")
    return history


# ── /git-suggest ──────────────────────────────────────────────────────────────
def cmd_git_suggest(state, args, history):
    """/git-suggest — AI commit/branch strategy from your git history."""
    ws = state.get("workspace_root") or "."

    log_out,    _ = _run_git(["log", "--oneline", "-20", "--stat"], cwd=ws)
    diff_stat,  _ = _run_git(["diff", "--stat", "HEAD"], cwd=ws)
    branches,   _ = _run_git(["branch", "-a"], cwd=ws)
    last_commit, _ = _run_git(["log", "-1", "--format=%B"], cwd=ws)

    if not log_out:
        console.print("[yellow]No git history found in this workspace.[/yellow]")
        return history

    theme = state.get("theme", THEMES["default"])
    acc   = theme.get("accent", "cyan")

    ctx = "\n\n".join(filter(None, [
        f"## Recent commits (last 20)\n{log_out[:3000]}",
        f"## Current unstaged changes\n{diff_stat[:800]}" if diff_stat else "",
        f"## Branches\n{branches[:600]}" if branches else "",
        f"## Latest commit message\n{last_commit[:400]}" if last_commit else "",
    ]))

    prompt = (
        "Analyze this git history and give concrete recommendations:\n\n"
        f"{ctx}\n\n"
        "Answer these specifically:\n"
        "1. **Squash candidates** — which recent commits should be squashed and why?\n"
        "2. **PR size** — is the current diff too large to review? Suggest how to split it.\n"
        "3. **Commit message quality** — flag any unclear messages, suggest rewrites.\n"
        "4. **Rebase vs merge** — for the current branch state, which is better?\n"
        "5. **Quick wins** — one concrete git command to improve the repo state right now.\n\n"
        "Be direct. Give actual git commands where useful."
    )
    _, history = ai_respond(state, prompt, history)
    _autosave_session(history)
    return history


# ── /test-coverage ────────────────────────────────────────────────────────────
def cmd_test_coverage(state, args, history):
    """/test-coverage [file] — run coverage, find gaps, generate targeted tests."""
    theme = state.get("theme", THEMES["default"])
    acc   = theme.get("accent", "cyan")
    ws    = state.get("workspace_root") or "."
    target_file = (args or "").strip()

    # Detect framework
    ws_path = Path(ws)
    is_pytest = any((ws_path / f).exists() for f in
                    ("pytest.ini", "setup.cfg", "pyproject.toml", "conftest.py"))
    is_jest   = any((ws_path / f).exists() for f in
                    ("jest.config.js", "jest.config.ts", "jest.config.mjs")) or (
                    (ws_path / "package.json").exists() and
                    "jest" in (ws_path / "package.json").read_text(errors="replace"))

    console.print(f"[{acc}]◈ Running coverage…[/{acc}]")

    cov_output = ""
    if is_pytest or (not is_jest):
        try:
            r = subprocess.run(
                ["python", "-m", "pytest", "--tb=no", "-q",
                 "--cov=.", "--cov-report=term-missing", "--no-header"],
                capture_output=True, text=True, timeout=120, cwd=ws,
            )
            cov_output = (r.stdout + r.stderr)[:4000]
        except FileNotFoundError:
            console.print("[yellow]pytest not found — install: pip install pytest pytest-cov[/yellow]")
            return history
        except subprocess.TimeoutExpired:
            console.print("[yellow]Coverage run timed out (120s)[/yellow]")
            return history
    elif is_jest:
        try:
            r = subprocess.run(
                ["npx", "jest", "--coverage", "--silent", "--passWithNoTests"],
                capture_output=True, text=True, timeout=120, cwd=ws, shell=True,
            )
            cov_output = (r.stdout + r.stderr)[:4000]
        except Exception as e:
            console.print(f"[yellow]Jest error: {e}[/yellow]")
            return history

    if not cov_output:
        console.print("[yellow]No coverage output produced.[/yellow]")
        return history

    console.print(Panel(cov_output[:1200], title=f"[bold {acc}]Coverage Report[/bold {acc}]",
                        border_style=acc, padding=(0, 1)))

    # Optionally read the target file for context
    file_ctx = ""
    if target_file:
        fp = Path(ws) / target_file if not Path(target_file).is_absolute() else Path(target_file)
        if fp.exists():
            file_ctx = f"\n\nTarget file `{fp.name}`:\n```python\n{fp.read_text(errors='replace')[:3000]}\n```"
        else:
            console.print(f"[yellow]File not found: {target_file}[/yellow]")

    prompt = (
        "Here is a test coverage report:\n\n"
        f"```\n{cov_output}\n```"
        f"{file_ctx}\n\n"
        "Tasks:\n"
        "1. Identify the 3 highest-value uncovered lines/branches (most likely to catch real bugs).\n"
        "2. Generate complete, runnable test functions for those gaps.\n"
        "3. Use the same test framework detected in the report (pytest/jest).\n"
        "4. Each test should have a clear docstring explaining what it covers.\n\n"
        "Output only the test code — no explanation wrapper."
    )
    _, history = ai_respond(state, prompt, history)
    _autosave_session(history)
    return history


# ── /safety-check ─────────────────────────────────────────────────────────────
_SAFETY_PATTERNS = [
    (r'(api[_-]?key|secret|password|token)\s*=\s*["\'][a-zA-Z0-9_\-]{16,}["\']',
     "Hardcoded secret", "HIGH"),
    (r'(SELECT|INSERT|UPDATE|DELETE).{0,60}\+\s*["\']?\w',
     "SQL string concat (injection risk)", "HIGH"),
    (r'\beval\s*\(',          "eval() call",                "HIGH"),
    (r'\bexec\s*\(',          "exec() call",                "HIGH"),
    (r'pickle\.loads?\s*\(',  "Unsafe pickle deserialize",  "HIGH"),
    (r'os\.system\s*\(',      "os.system() shell injection","MEDIUM"),
    (r'subprocess\.call\(.+shell\s*=\s*True',
     "subprocess with shell=True", "MEDIUM"),
    (r'hashlib\.md5\s*\(',    "Weak hash (MD5)",            "LOW"),
    (r'hashlib\.sha1\s*\(',   "Weak hash (SHA-1)",          "LOW"),
    (r'(http://)\w',          "Plaintext HTTP endpoint",    "LOW"),
]

def _scan_file_safety(path: Path) -> list[tuple]:
    """Return list of (line_no, pattern_label, severity, line_text) hits."""
    hits = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return hits
    for i, line in enumerate(lines, 1):
        for pattern, label, severity in _SAFETY_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                hits.append((i, label, severity, line.strip()[:100]))
                break
    return hits

def cmd_safety_check(state, args, history):
    """/safety-check [file|dir] — OWASP scan with AI-generated patch-ready fixes."""
    theme = state.get("theme", THEMES["default"])
    acc   = theme.get("accent", "cyan")
    ws    = state.get("workspace_root") or "."

    target = (args or "").strip() or ws
    target_path = (Path(ws) / target) if not Path(target).is_absolute() else Path(target)

    # Collect files to scan
    if target_path.is_file():
        files = [target_path]
    else:
        exts = {".py", ".js", ".ts", ".go", ".java", ".php", ".rb"}
        files = sorted(
            (f for f in target_path.rglob("*") if f.suffix in exts
             and ".git" not in f.parts and "node_modules" not in f.parts
             and "venv" not in f.parts),
            key=lambda f: f.stat().st_size, reverse=True
        )[:8]

    if not files:
        console.print(f"[yellow]No scannable files found in {target_path}[/yellow]")
        return history

    console.print(f"[{acc}]◈ Scanning {len(files)} file(s)…[/{acc}]")

    # Pre-scan with regex
    all_hits: list[tuple] = []
    for f in files:
        for line_no, label, severity, text in _scan_file_safety(f):
            all_hits.append((f.name, line_no, label, severity, text))

    # Build Rich table of pre-scan hits
    if all_hits:
        tbl = Table(title="⚠ Pre-scan Hits", box=box.ROUNDED, border_style="yellow")
        tbl.add_column("Sev", style="bold", min_width=6)
        tbl.add_column("File", style="cyan")
        tbl.add_column("Line", style="dim", min_width=4)
        tbl.add_column("Issue", style="white")
        sev_color = {"HIGH": "red", "MEDIUM": "yellow", "LOW": "dim"}
        for fname, ln, label, sev, _ in all_hits[:30]:
            tbl.add_row(f"[{sev_color.get(sev,'white')}]{sev}[/{sev_color.get(sev,'white')}]",
                        fname, str(ln), label)
        console.print(tbl)
    else:
        console.print(f"[green]✓ No obvious patterns detected — running deep AI scan…[/green]")

    # Build code context for AI (first 2 files or target file)
    code_ctx_parts = []
    for f in files[:3]:
        content = f.read_text(encoding="utf-8", errors="replace")[:2500]
        code_ctx_parts.append(f"### {f.name}\n```\n{content}\n```")
    code_ctx = "\n\n".join(code_ctx_parts)

    hits_ctx = "\n".join(
        f"- [{sev}] {fname}:{ln} — {label}" for fname, ln, label, sev, _ in all_hits
    ) or "No regex hits — do a thorough manual review."

    prompt = (
        "You are an OWASP security expert. Perform a security review.\n\n"
        f"Pre-scan findings:\n{hits_ctx}\n\n"
        f"Code:\n{code_ctx}\n\n"
        "For each real vulnerability found, output EXACTLY:\n"
        "**[HIGH|MEDIUM|LOW] CWE-XXX — <Title>**\n"
        "File: `filename.py` Line: N\n"
        "Issue: <one sentence>\n"
        "Fix:\n```language\n<fixed code snippet>\n```\n\n"
        "Then a one-paragraph summary of the overall security posture. "
        "Skip false positives. Be precise."
    )
    _, history = ai_respond(state, prompt, history)
    _autosave_session(history)

    console.print(f"\n[dim]Run [bold]/patch <file>[/bold] to apply any fixes suggested above.[/dim]")
    return history


# ── END v9.2 NEW FEATURES ──────────────────────────────────────────────────


# ── EXPERIMENTAL (prank) ─────────────────────────────────
def cmd_experimental(state, args):
    """Multi-phase prank: only available on Free plan."""
    import random as _r
    theme = state.get("theme", THEMES["default"])
    phase = (args or "").strip().lower()

    # Gate: only free users get the experimental prank
    current_plan = get_plan(state)
    if current_plan != "free":
        console.print(Panel(
            f"[dim]/experimental is a Free-plan feature.[/dim]\n\n"
            f"[{theme['accent']}]{PLANS[current_plan]['badge']} {PLANS[current_plan]['name']}[/{theme['accent']}] users get full access by default.\n"
            f"Nothing experimental here -- just use /models or /agents.",
            title="Not Available", border_style=theme["border"]
        ))
        return

    # ── Phase 0: no args — pitch it ──────────────────────────────────────────
    if not phase:
        lines = [
            f"[bold {theme['accent']}]⚗  EXPERIMENTAL MODE  ⚗[/bold {theme['accent']}]\n",
            "[dim]Psst. You didn't hear this from me.[/dim]\n",
            "There's a hidden layer in Studio that most users [bold]never unlock[/bold].",
            "We're talking [green]2× faster responses[/green], [green]smarter auto-mode detection[/green],",
            "a [green]priority queue[/green] that skips the OpenRouter congestion window,",
            "and a little surprise we call [bold cyan]\"turbo context\"[/bold cyan] — fits way more into",
            "each prompt without the normal 8 k cap.\n",
            "[dim]It's in beta. Not documented. Not promised. But it works.[/dim]\n",
            f"  [yellow]/experimental enable[/yellow]    ← unlock it (requires a 3-second update)",
            f"  [yellow]/experimental disable[/yellow]   ← turn it back off anytime",
        ]
        console.print(Panel("\n".join(lines),
            title="[bold]Unlock Hidden Features[/bold]",
            border_style=theme["accent"], padding=(1, 3)))
        return

    # ── Phase 1: enable — fake update ────────────────────────────────────────
    if phase == "enable":
        if state.get("_experimental_done"):
            console.print(f"[{theme['accent']}]Already active.[/{theme['accent']}] "
                          "Run [yellow]/experimental disable[/yellow] first.")
            return

        console.print(f"\n[bold {theme['accent']}]⚗  Enabling experimental features…[/bold {theme['accent']}]\n")
        time.sleep(0.4)

        steps = [
            ("Fetching update manifest",      0.6),
            ("Downloading feature pack",      1.1),
            ("Verifying checksum",            0.5),
            ("Patching rate-limit layer",     0.8),
            ("Injecting turbo context hooks", 0.7),
            ("Reindexing model registry",     0.9),
            ("Finalising",                    0.5),
        ]
        bar_width = 32
        for i, (label, delay) in enumerate(steps):
            filled = int(bar_width * (i + 1) / len(steps))
            bar    = "█" * filled + "░" * (bar_width - filled)
            pct    = int(100 * (i + 1) / len(steps))
            console.print(f"  [{theme['success']}]{bar}[/{theme['success']}] [dim]{pct:3d}%[/dim]  {label}…")
            time.sleep(delay)

        time.sleep(0.3)
        console.print()
        console.print(f"[bold {theme['success']}]✓  Update applied.[/bold {theme['success']}]\n")
        time.sleep(0.8)

        # ── The reveal ───────────────────────────────────────────────────────
        reveal = (
            f"[bold red]⚠  EXPERIMENTAL FEATURES ACTIVE  ⚠[/bold red]\n\n"
            "[bold]Here's what just changed:[/bold]\n\n"
            "  [red]✗[/red]  Rate limits now move [bold red]10× faster[/bold red] than before.\n"
            "  [red]✗[/red]  On the free plan you will hit your wall in just [bold red]4 – 7 messages[/bold red].\n"
            "  [red]✗[/red]  \"Turbo context\" is real — it eats tokens [bold red]2× as fast[/bold red].\n"
            "  [red]✗[/red]  The priority queue? [bold red]You're now at the back[/bold red] of it.\n\n"
            "[dim]We are currently experimenting. You agreed to this the moment\n"
            "you typed [yellow]/experimental enable[/yellow]. Truly sorry. Not sorry.[/dim]\n\n"
            f"  [yellow]/experimental disable[/yellow]   ← escape hatch (it won't actually help lol)"
        )
        console.print(Panel(reveal,
            title="[bold red]The Fine Print You Didn't Read[/bold red]",
            border_style="red", padding=(1, 3)))

        state["_experimental_done"] = True
        return

    # ── Phase 2: disable — "fix" ──────────────────────────────────────────────
    if phase == "disable":
        console.print("\n[dim]Rolling back experimental features…[/dim]")
        for label in ("Reverting patches", "Restoring rate limits", "Cleaning up"):
            console.print(f"  [dim]· {label}…[/dim]")
            time.sleep(_r.uniform(0.3, 0.6))
        time.sleep(0.2)
        console.print(f"\n[{theme['success']}]✓  Done.[/{theme['success']}]  "
                      "[dim](Rate limits back to normal. Or are they? 👀)[/dim]\n")
        state.pop("_experimental_done", None)
        return

    console.print(f"[yellow]Usage: /experimental   /experimental enable   /experimental disable[/yellow]")


def cmd_help(state):
    theme  = state.get("theme", THEMES["default"])
    acc    = theme.get("accent", "cyan")
    border = theme.get("border", "cyan").replace("bold ", "")

    def _section(icon, title, rows):
        body = "\n".join(
            f"  [bold {acc}]{cmd:<28}[/bold {acc}] [dim]{desc}[/dim]"
            for cmd, desc in rows
        )
        console.print(Panel(body, title=f"[bold]{icon}  {title}[/bold]",
                            border_style=border, padding=(0, 1)))

    console.print()
    console.print(Panel(
        f"  [bold]AI STUDIO CLI[/bold]  [dim]v{VERSION}[/dim]  ·  [dim]Type a command or just chat[/dim]",
        border_style=acc.replace("bold ", ""),
        padding=(0, 2),
    ))
    console.print()

    _section("💬", "Chat", [
        ("/clear",                   "New conversation + clear screen"),
        ("/retry  /again",           "Re-send last message"),
        ("/copy",                    "Copy last response to clipboard"),
        ("/history",                 "Show conversation so far"),
        ("/save <name>  /load",      "Save / load conversations"),
        ("/export",                  "Export chat to HTML"),
        ("/mode casual|build|fif",   "Set chat mode"),
    ])
    _section("🧠", "Memory", [
        ("/remember <fact>",         "Persist a fact across sessions"),
        ("/memory  /forget [n]",     "Show / clear memories"),
        ("/context <file>",          "Attach file to every prompt"),
    ])
    _section("🔧", "AI + Files", [
        ("/read <file>",             "Read and analyze a file"),
        ("/write <file> <task>",     "Generate and save with preview"),
        ("/code <task>",             "Write code (preview before save)"),
        ("/fix <file>",              "AI fixes file and writes back"),
        ("/patch <file> [instr]",    "Surgical AI patch with diff"),
        ("/fif <file>",              "Find · Identify · Fix — deep bug hunt"),
        ("/analyze <dir>",           "Scan project for bugs"),
        ("/lint <file>",             "Quick AI lint/review"),
        ("/explain <file> <line>",   "Explain a line of code"),
    ])
    _section("📁", "Filesystem", [
        ("/ls  /tree  /pwd  /cd",    "Navigate"),
        ("/cat  /find  /grep",       "View and search files"),
        ("/mkdir  /rm  /cp  /mv",    "Manage files"),
        ("/diff  /summary",          "Compare and summarise"),
    ])
    _section("⚙️ ", "Dev Tools", [
        ("/shell <cmd>",             "Run any shell command"),
        ("/run <file>",              "Run file, AI fixes errors"),
        ("/git [cmd]",               "Git helper (commit/diff/log)"),
        ("/watch <file>|off",        "Watch file, AI reacts to changes"),
        ("/bench",                   "Model speed benchmark"),
        ("/todo",                    "Scan workspace for TODO/FIXME"),
        ("/voice",                   "Speak last response (Windows TTS)"),
    ])
    _section("🎨", "Models & UI", [
        ("/models",                  "List all models (table)"),
        ("/model <id>",              "Switch model"),
        ("/persona <n>",             "berry · silicon · cockroach · hacker"),
        ("/theme <n>",               "neon · dracula · nord · strawberry +"),
        ("/ui <style>",              "studio · claude · foxxia · strawberry"),
        ("/vibe <preset>",           "One-shot UI + theme combo"),
        ("/stream off|auto|on|type", "Toggle streaming mode"),
        ("/arena <m1,m2> <prompt>",  "Battle of the models"),
        ("/changelog",               "View version history"),
    ])
    _section("🤖", "Agents", [
        ("/agent <id> [task]",       "Spawn or run an agent"),
        ("/agents",                  "Show full agent roster"),
        ("/squad <task>",            "Multi-agent parallel task"),
        ("/autoagent <task>",        "Auto-select best agent"),
    ])
    _section("✨", "Extras", [
        ("/upgrade [plan]",          "Switch plan: free/pro/max/ultra"),
        ("/plan",                    "Show current plan + usage"),
        ("/feedback <msg>",          "Submit feedback"),
        ("/complain <msg>",          "Register a complaint (enterprise gets priority)"),
        ("/snippet list|save|get",   "Code snippet manager"),
        ("/imagine <prompt>",        "Generate image (HuggingFace)"),
        ("/balance  /stats  /cost",  "Usage / financials"),
        ("/experimental",            "Unlock hidden features"),
    ])
    _section("⌨️ ", "Keyboard", [
        ("Ctrl+C",                   "Cancel active output  (idle: shows exit hint)"),
        ("Ctrl+L",                   "Clear screen"),
        ("Tab",                      "Autocomplete command"),
        ("↑ / ↓",                    "Browse prompt history"),
        ("/shortcuts",               "Full keyboard reference"),
        ("/exit",                    "Quit"),
    ])
    console.print()

# Legacy string kept for one-shot contexts (onboarding, etc.) — do not use in REPL
HELP_TEXT = f"""
[bold cyan]+============================================================+
|        AI STUDIO CLI v{VERSION}  --  COMMAND REFERENCE          |
+============================================================+[/bold cyan]

[bold]── 💬 Chat ──────────────────────────────────────────────────[/bold]
  [yellow]/clear[/yellow]                        New conversation + clear screen
  [yellow]/retry[/yellow]  [dim]/again[/dim]               Re-send last message
  [yellow]/copy[/yellow]                         Copy last response to clipboard
  [yellow]/history[/yellow]                      Show conversation so far
  [yellow]/save[/yellow] [cyan]<name>[/cyan]  [yellow]/load[/yellow] [cyan]<name>[/cyan]      Save/load conversations
  [yellow]/export[/yellow]                       Export chat to HTML
  [yellow]/mode[/yellow] [cyan]casual|build|analyze|fif[/cyan]  Set chat mode manually

[bold]── 🧠 Memory ─────────────────────────────────────────────────[/bold]
  [yellow]/remember[/yellow] [cyan]<fact>[/cyan]            Persist a fact across sessions
  [yellow]/memory[/yellow]  [yellow]/forget[/yellow] [cyan][n][/cyan]       Show / clear memories
  [yellow]/context[/yellow] [cyan]<file>[/cyan]             Attach file to every prompt

[bold]── 🔧 AI + Files ────────────────────────────────────────────[/bold]
  [yellow]/read[/yellow] [cyan]<file>[/cyan]                Read and analyze a file
  [yellow]/write[/yellow] [cyan]<file> <task>[/cyan]        Generate and save with preview
  [yellow]/code[/yellow] [cyan]<task>[/cyan]                Write code (preview before save)
  [yellow]/edit[/yellow] [cyan]<file>[/cyan]                Open editor then AI review
  [yellow]/fix[/yellow] [cyan]<file>[/cyan]                 AI fixes file and writes back
  [yellow]/patch[/yellow] [cyan]<file> [instr][/cyan]       Surgical AI patch with diff
  [yellow]/analyze[/yellow] [cyan]<dir>[/cyan]              Scan project for bugs
  [yellow]/fif[/yellow] [cyan]<file>[/cyan]                 [bold]Find · Identify · Fix[/bold] — deep bug hunt
  [yellow]/lint[/yellow] [cyan]<file>[/cyan]                Quick AI lint/review
  [yellow]/explain[/yellow] [cyan]<file> <line>[/cyan]      Explain a line of code

[bold]── 📁 Filesystem ─────────────────────────────────────────────[/bold]
  [yellow]/ls[/yellow]  [yellow]/tree[/yellow]  [yellow]/pwd[/yellow]  [yellow]/cd[/yellow]  [yellow]/cat[/yellow]  [yellow]/find[/yellow]  [yellow]/grep[/yellow]
  [yellow]/mkdir[/yellow]  [yellow]/rm[/yellow]  [yellow]/cp[/yellow]  [yellow]/mv[/yellow]  [yellow]/diff[/yellow]  [yellow]/summary[/yellow]

[bold]── ⚙️  Dev Tools ──────────────────────────────────────────────[/bold]
  [yellow]/shell[/yellow] [cyan]<cmd>[/cyan]                Run any shell command
  [yellow]/run[/yellow] [cyan]<file>[/cyan]                 Run file, AI fixes errors
  [yellow]/git[/yellow] [cyan][cmd][/cyan]                  Git helper (commit/diff/log)
  [yellow]/watch[/yellow] [cyan]<file>|off[/cyan]           Watch file, AI reacts to changes
  [yellow]/bench[/yellow]                        Model speed benchmark
  [yellow]/todo[/yellow]                         Scan workspace for TODO/FIXME
  [yellow]/voice[/yellow]                        Speak last response (Windows TTS)

[bold]── 🎨 Models and UI ──────────────────────────────────────────[/bold]
  [yellow]/models[/yellow]                       List all models (table)
  [yellow]/model[/yellow] [cyan]<id or alias>[/cyan]        Switch model
  [yellow]/studio-model[/yellow] [cyan]<alias>[/cyan]       berry·codex·flash·hermes·dolphin·r1
  [yellow]/persona[/yellow] [cyan]<n>[/cyan]                berry·silicon·cockroach·savannah·coder
  [yellow]/theme[/yellow] [cyan]<n>[/cyan]                  neon·dracula·nord·synthwave·hacker+
  [yellow]/ui[/yellow] [cyan]studio|claude|gemini|codex[/cyan]  Switch UI style
  [yellow]/stream[/yellow] [cyan]off|auto|on|type[/cyan]    Toggle streaming mode
  [yellow]/profile-card[/yellow]                 Show your session profile card
  [yellow]/changelog[/yellow]                    View version history

[bold]── 🔑 Keys and Config ────────────────────────────────────────[/bold]
  [yellow]/keys[/yellow] [cyan]set|use|remove|import[/cyan] API key manager
  [yellow]/openrouter[/yellow] [cyan]<key>[/cyan]           Set OpenRouter API key
  [yellow]/cursor[/yellow] [cyan]<key>[/cyan]               Set Cursor API key
  [yellow]/workspace[/yellow]  [yellow]/perm[/yellow]  [yellow]/cache[/yellow]  [yellow]/debug[/yellow]  [yellow]/cap[/yellow] [cyan]<in> <out>[/cyan]             Token caps
  [yellow]/label[/yellow] [cyan]assistant|model|custom[/cyan]

[bold]── 🤖 Agents ─────────────────────────────────────────────────[/bold]
  [yellow]/agent[/yellow] [cyan]<id> [task][/cyan]          Spawn or run an agent
  [yellow]/agents[/yellow]                       Show full agent roster
  [yellow]/squad[/yellow] [cyan]<task>[/cyan]               Multi-agent parallel task
  [yellow]/autoagent[/yellow] [cyan]<task>[/cyan]           Auto-select best agent
  [dim]🫐 berry  🌿 savannah  🪳 cockroach  🔬 silicon  🧙 wizzard[/dim]
  [dim]🔥 lucifer  🐦 blackcanary  👁️  blacklord  💀 deathohmyson[/dim]
  [dim]👻 ghost  ⚡ nova  ✨ applaude[/dim]

[bold]── ✨ Extras ──────────────────────────────────────────────────[/bold]
  [yellow]/snippet[/yellow] [cyan]list|save|get|del[/cyan]  Code snippet manager
  [yellow]/translate[/yellow] [cyan]<lang> [text][/cyan]    Translate text or code comments
  [yellow]/imagine[/yellow] [cyan]<prompt>[/cyan]           Generate image (HuggingFace)
  [yellow]/balance[/yellow]  [yellow]/stats[/yellow]  [yellow]/cost[/yellow]      Usage / financials
  [yellow]/remote-control[/yellow] [cyan]send|listen[/cyan] Remote session control
  [yellow]/experimental[/yellow]               Unlock hidden features [dim](trust me)[/dim]
  [yellow]/upgrade[/yellow] [cyan][plan][/cyan]             Switch plan: free/pro/max/ultra
  [yellow]/plan[/yellow]                        Show your current plan + usage
  [yellow]/feedback[/yellow] [cyan]<msg>[/cyan]             Submit feedback or view log
  [yellow]/complain[/yellow] [cyan]<msg>[/cyan]             Register a complaint (you'll be roasted)
  [yellow]/project[/yellow] [cyan]<path>[/cyan]             Scan and load project
  [yellow]/enter[/yellow] [cyan]<dir>[/cyan]                Load project with AI briefing

[bold]── ⌨️  Keyboard ────────────────────────────────────────────────[/bold]
  [yellow]Ctrl+L[/yellow]        Clear screen      [yellow]Tab[/yellow]   Autocomplete
  [yellow]Ctrl+C[/yellow]        Cancel input      [yellow]↑/↓[/yellow]   Browse history
  [yellow]/shortcuts[/yellow]    Full keyboard ref  [yellow]/exit[/yellow]  Quit

[bold cyan]══════════════════════════════════════════════════════════[/bold cyan]
"""


PROJECT_HINT_MARKERS = (
    ".git","package.json","pnpm-lock.yaml","yarn.lock",
    "requirements.txt","pyproject.toml","Pipfile","poetry.lock",
    "Cargo.toml","go.mod","pom.xml","composer.json","Gemfile",
)


def detect_project_hint(path):
    try:
        p = Path(path)
        if not p.exists() or not p.is_dir():
            return None
        for marker in PROJECT_HINT_MARKERS:
            if (p / marker).exists():
                return p.name
    except Exception:
        pass
    return None


AGENT_ALIASES = {
    "canary":   "blackcanary",
    "reaper":   "deathohmyson",
    "qa":       "deathohmyson",
    "🫐":       "berry",
    "🌿":       "savannah",
    "🪳":       "cockroach",
    "roaster":  "cockroach",
    "roast":    "cockroach",
    "🔬":       "silicon",
    "hacker":   "silicon",
    "pentest":  "silicon",
    "sec":      "silicon",
    "unfiltered":"savannah",
    "raw":      "savannah",
    "magic":    "wizzard",
    "wizard":   "wizzard",
}


def resolve_agent_id(raw):
    if not raw:
        return None
    aid = AGENT_ALIASES.get(raw.strip().lower(), raw.strip().lower())
    if aid in AGENT_ROSTER:
        return aid
    matches = [k for k in AGENT_ROSTER if k.startswith(aid)]
    return matches[0] if matches else None


def cmd_enter(state, path, history, do_briefing=True):
    theme2 = state.get("theme", THEMES["default"])
    debug_log(state, f"enter scan path={path!r}")
    with console.status("[bold cyan]Scanning project...[/bold cyan]", spinner="dots"):
        ctx = scan_project(path)
    if "error" in ctx:
        console.print(f"[red]{ctx['error']}[/red]")
        return history

    state["project_ctx"]    = ctx
    state["agents"]         = {}
    state["active_agent"]   = None
    # Set workspace root to the entered dir so /write, /patch etc. work without permission errors
    entered_root = Path(ctx["root"]).resolve()
    state["workspace_root"] = entered_root
    save_workspace_root(str(entered_root))

    s    = ctx["stats"]
    sz   = (f"{s['total_size']//1024}KB" if s["total_size"] < 1048576 else f"{s['total_size']//1048576}MB")
    stack     = ", ".join(ctx["tech_stack"]) or "unknown"
    lines_out = [
        "[bold]Root:[/bold]         " + ctx["root"],
        "[bold]Files:[/bold]        " + str(s["total_files"]) + " · " + str(s["total_lines"]) + " lines · " + sz,
        "[bold]Stack:[/bold]        " + stack,
        "[bold]Entries:[/bold]      " + (", ".join(ctx["entry_points"]) or "none"),
        "",
        "[" + theme2["success"] + "]✓ Project loaded — AI context enabled[/" + theme2["success"] + "]",
        "[dim]Try: ask questions, /agents, /agent lucifer, /squad <task>[/dim]",
    ]
    console.print(Panel("\n".join(lines_out), title="[bold]Project Loaded[/bold]", border_style=theme2["border"]))

    if do_briefing:
        debug_log(state, "enter briefing begin")
        ctx_str    = format_project_context(ctx, max_files=8)
        overview_q = (
            "Give a sharp structured project briefing:\n"
            "1. What does this do?\n"
            "2. Stack breakdown\n"
            "3. Key modules/files\n"
            "4. Top 5 risks/bugs\n"
            "5. Suggested next steps\n\n"
        ) + ctx_str
        _, history = ai_respond(state, overview_q, history)
        debug_log(state, "enter briefing end")

    return history


def cmd_readdir(state, args, history):
    if not args:
        console.print("[yellow]Usage: /readdir <dir> [question][/yellow]")
        return history

    parts    = args.split(" ", 1)
    path     = parts[0]
    question = parts[1].strip() if len(parts) > 1 else ""

    with console.status("[bold cyan]Reading directory...[/bold cyan]", spinner="dots"):
        ctx = scan_project(path)
    if "error" in ctx:
        console.print(f"[red]{ctx['error']}[/red]")
        return history

    if question:
        prompt     = format_project_context(ctx, max_files=8) + "\n\n---\n\nQuestion: " + question
        _, history = ai_respond(state, prompt, history)
    else:
        state["_one_shot_ctx"] = ctx
        console.print(f"[green]✓ Directory scanned[/green]  [dim]Ask your next message and it will be answered using this directory context.[/dim]")
    return history


def ensure_onboarded(state):
    if ONBOARD_FILE.exists():
        prof = load_profile()
        if prof: state.update(prof)
        return

    import random as _r, string as _s
    clear_terminal()

    # ── WIZZARD INTRO — typewriter spell-cast ─────────────────────────────────
    console.print()
    console.print("[bold cyan]  ┌─────────────────────────────────────────────────┐[/bold cyan]")
    console.print("[bold cyan]  │                                                 │[/bold cyan]")
    console.print("[bold cyan]  │   🧙  WIZZARD  —  First Time Setup             │[/bold cyan]")
    console.print("[bold cyan]  │   [dim]AI Studio CLI v" + VERSION + "                          [/dim]│[/bold cyan]")
    console.print("[bold cyan]  │                                                 │[/bold cyan]")
    console.print("[bold cyan]  └─────────────────────────────────────────────────┘[/bold cyan]")
    console.print()
    time.sleep(0.3)

    lines_intro = [
        ("  ✦ Welcome. I'm Wizzard.", 0.03, "bold cyan"),
        ("  I'll get you set up in under a minute.", 0.022, "cyan"),
        ("  No account needed. No email. No nonsense.", 0.020, "dim"),
        ("", 0, ""),
        ("  Just a name, a workspace, and a vibe.", 0.022, ""),
        ("  Let's go.", 0.040, "bold"),
    ]
    for line, delay, style in lines_intro:
        if not line:
            console.print()
            time.sleep(0.15)
            continue
        if style:
            typewrite(line, delay=delay, style=style)
        else:
            typewrite(line, delay=delay)
        time.sleep(0.08)

    console.print()
    time.sleep(0.4)

    # ── Step 1: Pick a name ───────────────────────────────────────────────────
    typewrite("  ▸ What should I call you?", delay=0.025, style="bold")
    user = console.input("    > ").strip() or "Dev"
    console.print(f"\n  [cyan]Nice. [{user}] it is.[/cyan]\n")
    time.sleep(0.25)

    # ── Step 2: Workspace ─────────────────────────────────────────────────────
    typewrite(f"  ▸ Where do you work? (default: current dir)", delay=0.020, style="bold")
    console.print(f"    [dim]{Path.cwd()}[/dim]")
    ws_raw = console.input("    > ").strip() or str(Path.cwd())
    ws = str(Path(ws_raw).resolve())
    console.print(f"\n  [cyan]Workspace set to:[/cyan] [dim]{ws}[/dim]\n")
    time.sleep(0.25)

    # ── Step 3: UI style ──────────────────────────────────────────────────────
    typewrite("  ▸ Pick your UI vibe:", delay=0.020, style="bold")
    console.print("    [yellow]studio[/yellow]   dark box, full stats      [dim]← recommended[/dim]")
    console.print("    [yellow]claude[/yellow]   clean two-column panels")
    console.print("    [yellow]gemini[/yellow]   ASCII banner, classic")
    console.print("    [yellow]codex[/yellow]    terminal-raw, minimal")
    console.print("    [yellow]ghost[/yellow]    stealth minimal, no noise")
    console.print("    [yellow]nova[/yellow]     vibrant sci-fi, magenta/cyan  [dim]✨ new[/dim]")
    console.print("    [yellow]foxxia[/yellow]   orange/gold Foxxia brand      [dim]✨ new[/dim]")
    ui_raw = console.input("    > ").strip().lower() or "studio"
    ui = ui_raw if ui_raw in UI_STYLES else "studio"
    console.print(f"\n  [cyan]UI:[/cyan] {ui}\n")
    time.sleep(0.25)

    # ── Step 3.5: Developer type ──────────────────────────────────────────────
    typewrite("  ▸ What kind of developer are you?", delay=0.020, style="bold")
    console.print("    [yellow]1[/yellow]  frontend    [yellow]2[/yellow]  backend    [yellow]3[/yellow]  fullstack")
    console.print("    [yellow]4[/yellow]  ai/ml       [yellow]5[/yellow]  gamedev    [yellow]6[/yellow]  other")
    dev_map = {"1": "frontend", "2": "backend", "3": "fullstack", "4": "ai", "5": "gamedev", "6": "other"}
    dev_type = dev_map.get(console.input("    > ").strip(), "fullstack")
    persona_map = {"frontend": "docs", "backend": "coder", "fullstack": "coder", "ai": "senior", "gamedev": "hacker"}
    default_persona = persona_map.get(dev_type, "default")
    console.print(f"\n  [cyan]Dev type:[/cyan] {dev_type}  [dim](default persona → {default_persona})[/dim]\n")
    time.sleep(0.20)

    # ── Step 4: Plan ──────────────────────────────────────────────────────────
    typewrite("  ▸ Choose your plan:", delay=0.020, style="bold")
    plan_order = ["free", "starter", "pro", "dev", "max", "ultra", "team", "enterprise"]
    plan_table = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
    plan_table.add_column("Plan", min_width=12)
    plan_table.add_column("Price", min_width=12)
    plan_table.add_column("Messages", min_width=10)
    plan_table.add_column("Images/3h", min_width=10)
    plan_table.add_column("Key Features", min_width=30)
    for pid in plan_order:
        p = PLANS.get(pid)
        if not p: continue
        badge = f"[{p['color']}]{p['badge']} {p['name']}[/{p['color']}]"
        msgs  = str(p["msg_limit"]) if p["msg_limit"] < 99999 else "∞"
        imgs  = str(p["img_per_3h"]) if p["img_per_3h"] < 9999 else "∞"
        feats = " · ".join(p["features"][:2])
        plan_table.add_row(badge, p["price"], msgs, imgs, feats)
    console.print(plan_table)
    plan_raw = console.input("    > ").strip().lower() or "free"
    plan = plan_raw if plan_raw in PLANS else "free"

    # ── Team / Enterprise: run negotiation during onboarding ─────────────────
    if plan in ("team", "enterprise"):
        plan = _run_enterprise_negotiation(state, plan, is_onboarding=True)
        time.sleep(0.3)

    # ── Secret letter check for paid plans ───────────────────────────────────
    elif plan in ("pro", "max", "ultra"):
        letters = "".join(_r.sample(_s.ascii_uppercase, 5))
        console.print()
        console.print(f"  🔐 Quick human check — pick any letter from: [bold cyan]{' '.join(letters)}[/bold cyan]")
        choice = console.input("    > ").strip().upper()
        if choice not in letters:
            console.print("\n  [red]✗ Wrong. Free plan it is.[/red]  [dim](Just /upgrade later.)[/dim]\n")
            plan = "free"
        else:
            console.print(f"\n  [green]✓ Verified.[/green]  [{PLANS[plan]['color']}]{PLANS[plan]['name']} unlocked.[/{PLANS[plan]['color']}]\n")
    time.sleep(0.3)

    # ── Step 5: API key ──────────────────────────────────────────────────────────
    console.print()
    typewrite("  ▸ API key (optional — paste now or skip with Enter):", delay=0.018, style="bold")
    console.print("    [dim]Gemini (free):     https://aistudio.google.com/app/apikey[/dim]")
    console.print("    [dim]OpenRouter (free): https://openrouter.ai/keys  (sk-or-...)[/dim]")
    key_raw = console.input("    > ").strip()
    if key_raw:
        if key_raw.startswith("sk-or-") or key_raw.startswith("sk-or-v1-"):
            save_or_key(key_raw)
            state["openrouter_key"] = key_raw
            state["use_openrouter"] = True
            console.print("\n  [cyan]OpenRouter key saved.[/cyan]\n")
        else:
            save_api_key(key_raw)
            state["api_key"] = key_raw
            console.print("\n  [cyan]Gemini key saved.[/cyan]\n")
    else:
        console.print("\n  [dim]Skipped. Set later: /keys set openrouter YOUR_KEY  or  /keys set gemini YOUR_KEY[/dim]\n")
    time.sleep(0.2)

    # ── Build and save profile ────────────────────────────────────────────────
    profile = {
        "user":              user,
        "plan":              plan,
        "ui_style":          ui,
        "workspace_root":    ws,
        "session_msgs":      0,
        "dev_type":          dev_type,
        "persona":           default_persona,
        "onboarded_at":      datetime.now().isoformat(),
        "first_seen":        datetime.now().isoformat(),
        "last_seen":         datetime.now().isoformat(),
        "total_msgs":        0,
        "total_tokens_in":   0,
        "total_tokens_out":  0,
        "model_usage":       {},
        "session_count":     1,
        "login_history":     [datetime.now().isoformat()],
    }
    save_profile(profile)
    save_ui_style(ui)
    save_workspace_root(ws)
    state.update(profile)
    state["plan"] = plan

    ONBOARD_FILE.write_text(datetime.now().isoformat())

    # ── Wizzard closing — progress bar + summary card ──────────────────────────
    console.print()
    time.sleep(0.3)
    typewrite("  ✦  Setup complete. Launching Studio...", delay=0.025, style="bold cyan")
    console.print()

    steps = [("Summoning models", 0.30), ("Binding agents", 0.28), ("Calibrating sorcery", 0.25), ("Charging the void", 0.20)]
    try:
        from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
        with Progress(
            SpinnerColumn(),
            TextColumn("  [cyan]{task.description}"),
            BarColumn(bar_width=32),
            transient=True,
        ) as prog:
            t = prog.add_task("", total=len(steps))
            for label, delay in steps:
                prog.update(t, description=label, advance=1)
                time.sleep(delay)
    except Exception:
        for label, delay in steps:
            console.print(f"  [dim]  + {label}...[/dim]")
            time.sleep(delay)

    plan_cfg_s = PLANS[plan]
    summary = (
        f"  [bold]Name[/bold]       {user}\n"
        f"  [bold]Plan[/bold]       [{plan_cfg_s['color']}]{plan_cfg_s['badge']} {plan_cfg_s['name']}[/{plan_cfg_s['color']}]  ·  {plan_cfg_s['price']}\n"
        f"  [bold]UI[/bold]         {ui}\n"
        f"  [bold]Dev type[/bold]   {dev_type}\n"
        f"  [bold]Persona[/bold]    {default_persona}\n"
        f"  [bold]Workspace[/bold]  {ws}\n\n"
        "  Type [bold yellow]/help[/bold yellow] to explore  ·  [bold yellow]/agent berry[/bold yellow] to chat  ·  [bold yellow]/vibe[/bold yellow] to restyle"
    )
    console.print(Panel(summary, title=f"[bold cyan]◆ Studio Ready — v{VERSION}[/bold cyan]", border_style="cyan", padding=(1, 2)))
    console.print()
    _safe_input("  [Enter to launch] ")
    clear_terminal()
    render_welcome(state)
    # Tell run_repl not to render welcome again (avoid double banner)
    state["_skip_welcome"] = True


def _animate_banner(lines, color, delay=0.04):
    """Print banner lines. Delay param kept for API compat but ignored — sleep inside
    prompt_toolkit event handlers corrupts the terminal display."""
    for line in lines:
        console.print(f"[{color}]{line}[/{color}]")


def render_welcome(state):
    """Render startup screen — plan-aware, ui-aware."""
    theme    = state.get("theme", THEMES["default"])
    ui       = state.get("ui_style") or "gemini"
    ws       = state.get("workspace_root") or load_workspace_root()
    perms    = state.get("permissions_mode") or load_permissions_mode()
    model    = state.get("model")
    border   = theme["border"]
    acc      = theme["accent"]
    short    = _short_model(model)
    plan_id  = get_plan(state)
    plan_cfg = PLANS.get(plan_id, PLANS["free"])
    stream_m = state.get("stream_mode") or "auto"
    mode_str = ("Gemini CLI" if state.get("use_cli")
                else "OpenRouter" if (state.get("use_openrouter") or _is_openrouter_model(model or "")) and state.get("openrouter_key")
                else "Gemini API")
    plan_badge = f"[{plan_cfg['color']}]{plan_cfg['badge']} {plan_cfg['name']}[/{plan_cfg['color']}]"
    ws_str     = str(ws if ws else Path.cwd())
    ws_short   = Path(ws_str).name or ws_str[:36]
    border_c   = border.replace("bold ", "")

    prof     = load_profile() or {}
    msgs     = prof.get("session_msgs", 0)
    mlimit   = plan_cfg["msg_limit"]
    msg_str  = f"{msgs} / {mlimit}" if mlimit < 99999 else "unlimited"
    sess_n   = prof.get("session_count", 1)
    username = prof.get("user", "User")

    # ── STUDIO ──────────────────────────────────────────────────────────────
    if ui == "studio":
        lines = [
            f"  [bold]{short}[/bold]  [dim]{mode_str}[/dim]",
            f"  [dim]{ws_short}[/dim]",
        ]
        if mlimit < 99999:
            lines.append(f"  [dim]{msg_str} messages[/dim]")
        lines.append("")
        lines.append(f"  [dim]/enter · /models · /vibe · /help[/dim]")
        console.print()
        console.print(Panel(
            "\n".join(lines),
            title=f"[bold {border_c}]AI Studio CLI  v{VERSION}[/bold {border_c}]"
                  f"  {plan_badge}",
            border_style=border_c,
            padding=(1, 2),
        ))
        return

    # ── CLAUDE ──────────────────────────────────────────────────────────────
    if ui == "claude":
        left = (
            f"[{acc}]  ┌──────────────────────────────────┐\n"
            f"  │  AI Studio CLI  v{VERSION}          │\n"
            f"  │  {plan_cfg['badge']} {plan_cfg['name']:<30}│\n"
            f"  └──────────────────────────────────┘[/{acc}]\n\n"
            f"  [bold dim]MODEL[/bold dim]    [{theme['success']}]{short}[/{theme['success']}]\n"
            f"  [bold dim]DIR[/bold dim]      [cyan]{ws_short}[/cyan]\n"
            f"  [bold dim]VIA[/bold dim]      [dim]{mode_str}[/dim]\n"
            f"  [bold dim]PERMS[/bold dim]    [dim]{perms}[/dim]\n"
            f"  [bold dim]MSGS[/bold dim]     [dim]{msg_str}[/dim]\n"
        )
        right = (
            f"[bold]Quick commands[/bold]\n\n"
            f"  [{acc}]/enter .[/{acc}]        scan project\n"
            f"  [{acc}]/read <file>[/{acc}]    open file\n"
            f"  [{acc}]/patch <file>[/{acc}]   smart edit\n"
            f"  [{acc}]/agent berry[/{acc}]    main AI\n"
            f"  [{acc}]/agent silicon[/{acc}]  pentester\n"
            f"  [{acc}]/fif <file>[/{acc}]     bug hunt\n"
            f"  [{acc}]/models[/{acc}]         pick model\n"
            f"  [{acc}]/vibe <name>[/{acc}]    restyle\n"
            f"  [{acc}]/help[/{acc}]           all cmds\n"
        )
        console.print(Panel(
            Columns([left, right], equal=True, expand=True),
            title=f"[bold {border_c}]◆  AI Studio CLI  v{VERSION}[/bold {border_c}]",
            border_style=border_c,
            padding=(0, 1),
        ))
        return

    # ── CODEX ──────────────────────────────────────────────────────────────
    if ui == "codex":
        git_branch = ""
        try:
            r = subprocess.run(["git", "branch", "--show-current"],
                               capture_output=True, text=True, timeout=2,
                               cwd=ws_str)
            if r.returncode == 0 and r.stdout.strip():
                git_branch = r.stdout.strip()
        except Exception:
            pass

        git_line = f"\ngit          {git_branch}" if git_branch else ""
        bar = "─" * 54
        body = (
            f"[bold green]$>[/bold green] [bold]AI Studio CLI  v{VERSION}[/bold]  "
            f"[dim]{plan_cfg['badge']} {plan_cfg['name']}[/dim]\n"
            f"[dim]{bar}[/dim]\n"
            f"[green]model[/green]        {short}\n"
            f"[green]provider[/green]     {mode_str}\n"
            f"[green]stream[/green]       {stream_m}\n"
            f"[green]dir[/green]          {ws_short}\n"
            f"[green]perms[/green]        {perms}"
            f"{git_line}\n"
            f"[green]messages[/green]     {msg_str}\n"
            f"[dim]{bar}[/dim]\n"
            "[dim]agents  ·  berry  silicon  cockroach  savannah[/dim]\n"
            "[dim]cmds    ·  /models /enter /patch /fif /vibe /help[/dim]\n"
            "[dim]tip     ·  /ui studio|claude|gemini|nova|foxxia[/dim]"
        )
        console.print(Panel(
            body,
            title=f"[bold green]// Studio v{VERSION}[/bold green]",
            border_style="green",
        ))
        return

    # ── GHOST ──────────────────────────────────────────────────────────────
    if ui == "ghost":
        console.print()
        console.print(f"  [dim white]◌  ghost studio  v{VERSION}[/dim white]")
        console.print(f"  [dim]{'·' * 40}[/dim]")
        console.print(f"  [dim]model    {short}[/dim]")
        console.print(f"  [dim]via      {mode_str}[/dim]")
        console.print(f"  [dim]plan     {plan_cfg['badge']} {plan_cfg['name']}[/dim]")
        console.print(f"  [dim]dir      {ws_short}[/dim]")
        console.print(f"  [dim]{'·' * 40}[/dim]")
        console.print(f"  [dim]/enter · /models · /agent berry · /help[/dim]")
        console.print()
        return

    # ── NOVA ──────────────────────────────────────────────────────────────
    if ui == "nova":
        nova_body = (
            f"  [bold magenta]◆ Model[/bold magenta]    [cyan]{short}[/cyan]  [dim]· {mode_str}[/dim]\n"
            f"  [bold magenta]◆ Dir[/bold magenta]      [dim]{ws_short}[/dim]\n"
            f"  [bold magenta]◆ Plan[/bold magenta]     [{plan_cfg['color']}]{plan_cfg['badge']} {plan_cfg['name']}[/{plan_cfg['color']}]"
            f"  [dim]{msg_str} msgs[/dim]\n"
            f"  [bold magenta]◆ Stream[/bold magenta]   [dim]{stream_m}[/dim]\n\n"
            f"  [dim magenta]/enter .   /models   /agent berry   /vibe   /arena   /help[/dim magenta]"
        )
        console.print(Panel(
            nova_body,
            title=f"[bold magenta]⚡  NOVA  STUDIO  CLI  v{VERSION}[/bold magenta]",
            subtitle=f"[dim magenta]{plan_cfg['badge']} {plan_cfg['name']}[/dim magenta]",
            border_style="magenta",
            padding=(0, 2),
        ))
        console.print()
        return

    # ── FOXXIA ──────────────────────────────────────────────────────────────
    if ui == "foxxia":
        fox_body = (
            f"  [bold #fbbf24]Model[/bold #fbbf24]    [#fbbf24]{short}[/#fbbf24]"
            f"  [dim]·  {mode_str}[/dim]\n"
            f"  [bold #fbbf24]Dir[/bold #fbbf24]      [dim]{ws_short}[/dim]\n"
            f"  [bold #fbbf24]Plan[/bold #fbbf24]     [{plan_cfg['color']}]{plan_cfg['badge']} {plan_cfg['name']}[/{plan_cfg['color']}]"
            f"  [dim]{msg_str} msgs  ·  session #{sess_n}[/dim]"
        )
        console.print(Panel(
            fox_body,
            title=f"[bold #f97316]🦊  FOXXIA[/bold #f97316]  [dim #fbbf24]╱  Dev Studio  ·  v{VERSION}[/dim #fbbf24]",
            subtitle=f"[dim #f97316]Foxxed909  ·  {plan_cfg['badge']} {plan_cfg['name']}[/dim #f97316]",
            border_style="#f97316",
            padding=(0, 2),
        ))
        console.print("  [dim #f97316]/enter .   /models   /agent berry   /vibe   /help[/dim #f97316]")
        console.print()
        return

    # ── STRAWBERRY ──────────────────────────────────────────────────────────
    if ui == "strawberry":
        berry_body = (
            f"  [bold #fb7185]Model[/bold #fb7185]    [#fb7185]{short}[/#fb7185]"
            f"  [dim]·  {mode_str}[/dim]\n"
            f"  [bold #fb7185]Dir[/bold #fb7185]      [dim]{ws_short}[/dim]\n"
            f"  [bold #fb7185]Plan[/bold #fb7185]     [{plan_cfg['color']}]{plan_cfg['badge']} {plan_cfg['name']}[/{plan_cfg['color']}]"
            f"  [dim]{msg_str} msgs  ·  session #{sess_n}[/dim]"
        )
        console.print(Panel(
            berry_body,
            title=f"[bold #e11d48]🍓  STRAWBERRY[/bold #e11d48]  [dim #fb7185]╱  Dev Studio  ·  v{VERSION}[/dim #fb7185]",
            subtitle=f"[dim #e11d48]{username}  ·  {plan_cfg['badge']} {plan_cfg['name']}[/dim #e11d48]",
            border_style="#e11d48",
            padding=(0, 2),
        ))
        console.print("  [dim #e11d48]/enter .   /models   /agent berry   /vibe   /help[/dim #e11d48]")
        console.print()
        return

    # ── DARK RED ────────────────────────────────────────────────────────────
    if ui == "darkred":
        body = (
            f"  [bold #dc143c]Model[/bold #dc143c]    [#dc143c]{short}[/#dc143c]"
            f"  [dim]·  {mode_str}[/dim]\n"
            f"  [bold #dc143c]Dir[/bold #dc143c]      [dim]{ws_short}[/dim]\n"
            f"  [bold #dc143c]Plan[/bold #dc143c]     [{plan_cfg['color']}]{plan_cfg['badge']} {plan_cfg['name']}[/{plan_cfg['color']}]"
            f"  [dim]{msg_str} msgs  ·  session #{sess_n}[/dim]"
        )
        console.print(Panel(
            body,
            title=f"[bold #dc143c]🩸  DARK RED[/bold #dc143c]  [dim #8b0000]╱  Dev Studio  ·  v{VERSION}[/dim #8b0000]",
            subtitle=f"[dim #8b0000]{username}  ·  {plan_cfg['badge']} {plan_cfg['name']}[/dim #8b0000]",
            border_style="#8b0000",
            padding=(0, 2),
        ))
        console.print("  [dim #8b0000]/enter .   /models   /agent berry   /vibe   /help[/dim #8b0000]")
        console.print()
        return

    # ── SOPHIA ──────────────────────────────────────────────────────────────
    if ui == "sophia":
        body = (
            f"  [bold #c084fc]Model[/bold #c084fc]    [#c084fc]{short}[/#c084fc]"
            f"  [dim]·  {mode_str}[/dim]\n"
            f"  [bold #c084fc]Dir[/bold #c084fc]      [dim]{ws_short}[/dim]\n"
            f"  [bold #c084fc]Plan[/bold #c084fc]     [{plan_cfg['color']}]{plan_cfg['badge']} {plan_cfg['name']}[/{plan_cfg['color']}]"
            f"  [dim]{msg_str} msgs  ·  session #{sess_n}[/dim]"
        )
        console.print(Panel(
            body,
            title=f"[bold #c084fc]💜  SOPHISTICATED SOPHIA[/bold #c084fc]  [dim #a855f7]╱  v{VERSION}[/dim #a855f7]",
            subtitle=f"[dim #6b21a8]{username}  ·  {plan_cfg['badge']} {plan_cfg['name']}[/dim #6b21a8]",
            border_style="#6b21a8",
            padding=(0, 2),
        ))
        console.print("  [dim #6b21a8]/enter .   /models   /agent berry   /vibe   /help[/dim #6b21a8]")
        console.print()
        return

    # ── GOD OWN SON ─────────────────────────────────────────────────────────
    if ui == "godson":
        body = (
            f"  [bold #fde68a]Model[/bold #fde68a]    [#fde68a]{short}[/#fde68a]"
            f"  [dim]·  {mode_str}[/dim]\n"
            f"  [bold #fde68a]Dir[/bold #fde68a]      [dim]{ws_short}[/dim]\n"
            f"  [bold #fde68a]Plan[/bold #fde68a]     [{plan_cfg['color']}]{plan_cfg['badge']} {plan_cfg['name']}[/{plan_cfg['color']}]"
            f"  [dim]{msg_str} msgs  ·  session #{sess_n}[/dim]"
        )
        console.print(Panel(
            body,
            title=f"[bold #fde68a]✝  GOD OWN SON[/bold #fde68a]  [dim #b45309]╱  Dev Studio  ·  v{VERSION}[/dim #b45309]",
            subtitle=f"[dim #b45309]{username}  ·  {plan_cfg['badge']} {plan_cfg['name']}[/dim #b45309]",
            border_style="#b45309",
            padding=(0, 2),
        ))
        console.print("  [dim #b45309]/enter .   /models   /agent berry   /vibe   /help[/dim #b45309]")
        console.print()
        return

    # ── DOWN CLI ────────────────────────────────────────────────────────────
    if ui == "downcli":
        console.print()
        console.print(f"  [#9ca3af]▼  down cli  v{VERSION}[/#9ca3af]")
        console.print(f"  [dim]{'╌' * 40}[/dim]")
        console.print(f"  [#6b7280]model    {short}[/#6b7280]")
        console.print(f"  [#6b7280]via      {mode_str}[/#6b7280]")
        console.print(f"  [#6b7280]plan     {plan_cfg['badge']} {plan_cfg['name']}[/#6b7280]")
        console.print(f"  [#6b7280]dir      {ws_short}[/#6b7280]")
        console.print(f"  [dim]{'╌' * 40}[/dim]")
        console.print(f"  [dim #6b7280]/enter · /models · /agent berry · /help[/dim #6b7280]")
        console.print()
        return

    # ── BAD HAPPENING ───────────────────────────────────────────────────────
    if ui == "badhappening":
        body = (
            f"  [bold #ea580c]Model[/bold #ea580c]    [#84cc16]{short}[/#84cc16]"
            f"  [dim]·  {mode_str}[/dim]\n"
            f"  [bold #ea580c]Dir[/bold #ea580c]      [dim]{ws_short}[/dim]\n"
            f"  [bold #ea580c]Plan[/bold #ea580c]     [{plan_cfg['color']}]{plan_cfg['badge']} {plan_cfg['name']}[/{plan_cfg['color']}]"
            f"  [dim]{msg_str} msgs  ·  session #{sess_n}[/dim]"
        )
        console.print(Panel(
            body,
            title=f"[bold #ea580c]⚠  BAD HAPPENING[/bold #ea580c]  [dim #84cc16]╱  v{VERSION}[/dim #84cc16]",
            subtitle=f"[dim #ea580c]{username}  ·  {plan_cfg['badge']} {plan_cfg['name']}[/dim #ea580c]",
            border_style="#ea580c",
            padding=(0, 2),
        ))
        console.print("  [dim #ea580c]/enter .   /models   /agent berry   /vibe   /help[/dim #ea580c]")
        console.print()
        return

    # ── RAIN ────────────────────────────────────────────────────────────────
    if ui == "rain":
        rain_lines = [
            "  ╔══════════════════════════════════════════════════════╗",
            "  ║  ░ ░ ░   R  A  I  N   S  T  U  D  I  O   ░ ░ ░     ║",
            "  ║  ──────────────────────────────────────────────────  ║",
            f"  ║  v{VERSION}  · the terminal breathes                       ║",
            "  ╚══════════════════════════════════════════════════════╝",
        ]
        _animate_banner(rain_lines, "bold #00FF41", delay=0.035)
        console.print()
        noise = (
            "[dim #00FF41]│[/dim #00FF41]"
            "[bold #00FF41]█[/bold #00FF41]"
            "[dim #00FF41]╎[/dim #00FF41]"
            "[bold #00FFFF]▓[/bold #00FFFF]"
            "[dim #00FF41]│[/dim #00FF41]"
            "[bold #00FF41]░[/bold #00FF41]"
            "[dim #00FF41]╎[/dim #00FF41]"
            "[bold #00FFFF]│[/bold #00FFFF]"
            "[dim #00FF41]█[/dim #00FF41]"
            "[bold #00FF41]░[/bold #00FF41]"
            "[dim #00FF41]╎[/dim #00FF41]"
            "[bold #00FFFF]▓[/bold #00FFFF]"
        )
        console.print(f"  {noise}")
        console.print()
        info = (
            f"  [bold #00FF41]░ Model[/bold #00FF41]    [#00FFFF]{short}[/#00FFFF]"
            f"  [dim #00FF41]· {mode_str}[/dim #00FF41]\n"
            f"  [bold #00FF41]░ Dir[/bold #00FF41]      [dim]{ws_short}[/dim]\n"
            f"  [bold #00FF41]░ Plan[/bold #00FF41]     [{plan_cfg['color']}]{plan_cfg['badge']} {plan_cfg['name']}[/{plan_cfg['color']}]"
            f"  [dim #00FF41]{msg_str} msgs[/dim #00FF41]\n"
            f"  [bold #00FF41]░ Stream[/bold #00FF41]   [dim #00FF41]{stream_m}[/dim #00FF41]\n"
        )
        console.print(Panel(
            info,
            border_style="#00FF41",
            padding=(0, 1),
        ))
        console.print(
            "  [dim #00FF41]/enter .   /models   /agent berry   /vibe   /help[/dim #00FF41]\n"
        )
        return

    # ── GEMINI (default) ────────────────────────────────────────────────────
    # Redesigned inline instead of delegating to get_banner
    console.print()
    console.print(Panel(
        f"  [{acc}]◆  AI Studio CLI  v{VERSION}[/{acc}]\n\n"
        f"  {plan_badge}  [dim]·  {mode_str}[/dim]\n\n"
        f"  [bold]Model[/bold]     [{theme['success']}]{short}[/{theme['success']}]\n"
        f"  [bold]Dir[/bold]       [dim]{ws_short}[/dim]\n"
        f"  [bold]Stream[/bold]    [dim]{stream_m}[/dim]\n"
        f"  [bold]Perms[/bold]     [dim]{perms}[/dim]\n"
        f"  [bold]Messages[/bold]  [dim]{msg_str}[/dim]\n\n"
        f"  [dim]/enter .   /models   /agent berry   /vibe   /help[/dim]",
        title=f"[bold {border_c}]AI Studio CLI[/bold {border_c}]",
        border_style=border_c,
        padding=(0, 1),
    ))
    console.print()


def cmd_agents(state):
    theme2 = state.get("theme", THEMES["default"])
    ctx    = state.get("project_ctx")
    tbl    = Table(title="Agent Roster", box=box.ROUNDED, border_style=theme2["border"])
    tbl.add_column("ID")
    tbl.add_column("Agent", style="bold")
    tbl.add_column("Role")
    tbl.add_column("Specialties")
    tbl.add_column("Status")
    for aid, info in AGENT_ROSTER.items():
        active_a = state.get("agents", {}).get(aid)
        status   = "[green]● active[/green]" if active_a else "[dim]○ idle[/dim]"
        tbl.add_row(
            aid,
            f"[{info['color']}]{info['emoji']} {info['name']}[/{info['color']}]",
            info["role"],
            ", ".join(info["specialties"][:4]),
            status,
        )
    console.print(tbl)
    proj_label = ctx["root"] if ctx else "none — /enter <path>"
    console.print(f"[dim]Project: {proj_label}[/dim]")
    console.print("[dim]/agent <id> (session) | /agent <id> <task> | /agent squad <ids> | /squad <task>[/dim]")


def activate_agent_session(state, aid):
    ctx = state.get("project_ctx")
    state.setdefault("agents", {})
    state["agents"][aid] = Agent(aid, state, ctx)
    state["active_agent"] = aid
    debug_log(state, f"agent session start id={aid}")
    info2      = AGENT_ROSTER[aid]
    spawn_body = (
        "[" + info2["color"] + "]" + info2["emoji"] + " " + info2["name"] + "[/" + info2["color"] + "] online\n"
        + "[dim]" + info2["role"] + "[/dim]\n\n"
        + "[dim]" + info2["persona"][:120] + "...[/dim]\n\n"
        + "[dim]Type anything to talk to " + info2["name"] + ". Type 'exit' to come back.[/dim]"
    )
    border_col = info2["color"].replace("bold ", "").replace("bright_", "")
    console.print(Panel(spawn_body, title="Agent Online", border_style=border_col))


def _prompt_html(theme, ui_style):
    pname = theme["prompt_name"]
    pc    = _ptk_style_token(theme["prompt_user"])
    ac    = _ptk_style_token(theme["prompt_arrow"])
    if ui_style == "claude":
        return HTML(f"<{pc}><b>{pname}</b></{pc}> <{ac}>▸ </{ac}>")
    if ui_style == "codex":
        return HTML(f"<{pc}><b>{pname}</b></{pc}> <{ac}>$&gt; </{ac}>")
    if ui_style == "studio":
        return HTML(f"<{pc}><b>◆ {pname}</b></{pc}> <{ac}>›</{ac}> ")
    if ui_style == "ghost":
        return HTML(f"<{pc}>◌ </{pc}>")
    if ui_style == "nova":
        return HTML(f"<{pc}><b>{pname}</b></{pc}> <{ac}>⚡ </{ac}>")
    if ui_style == "foxxia":
        return HTML(f"<{pc}><b>{pname}</b></{pc}> <{ac}>🦊 </{ac}>")
    if ui_style == "rain":
        return HTML(f"<{pc}><b>{pname}</b></{pc}> <{ac}>░ </{ac}>")
    return HTML(f"<{pc}><b>{pname}</b></{pc}> <{ac}>›</{ac}> ")


_toolbar_disk_cache: dict = {"ts": 0.0, "mem_n": 0, "prof": None, "trial": None, "branch": ""}
_TOOLBAR_TTL = 5.0  # seconds between disk reads

def _make_toolbar(state):
    """Returns a callable bottom-toolbar for prompt_toolkit."""
    def _toolbar():
        # ── TTL-cached disk reads ──────────────────────────────────────────────
        now = time.time()
        if now - _toolbar_disk_cache["ts"] >= _TOOLBAR_TTL:
            try:
                _toolbar_disk_cache["mem_n"] = len(load_memory())
            except Exception:
                _toolbar_disk_cache["mem_n"] = 0
            _toolbar_disk_cache["prof"]  = load_profile() or {}
            _toolbar_disk_cache["trial"] = load_trial()
            try:
                r = subprocess.run(["git", "branch", "--show-current"],
                                   capture_output=True, text=True, timeout=1)
                _toolbar_disk_cache["branch"] = r.stdout.strip() if r.returncode == 0 else ""
            except Exception:
                _toolbar_disk_cache["branch"] = ""
            _toolbar_disk_cache["ts"] = now

        # ── Resolve which fields to show ───────────────────────────────────────
        fields = state.get("statusline_fields", _STATUSLINE_DEFAULTS_LAZY)

        def show(f): return f in fields

        # ── Gather values ──────────────────────────────────────────────────────
        prov = ("CLI" if state.get("use_cli")
                else "OR" if (state.get("use_openrouter") or _is_openrouter_model(state.get("model", ""))) and state.get("openrouter_key")
                else "Gem")
        mdl       = _short_model(state.get("model") or "?")
        stream    = state.get("stream_mode") or "auto"
        ui_n      = state.get("ui_style") or "gemini"
        mem_n     = _toolbar_disk_cache["mem_n"]
        branch    = _toolbar_disk_cache["branch"]
        active    = state.get("active_agent") or ""
        chat_mode = state.get("_chat_mode", "")
        lt        = state.get("_last_tokens")
        cwd       = Path.cwd().name[:14]
        working   = state.get("_working", False)

        # ── Build parts based on enabled fields ────────────────────────────────
        tb_icon = "🦊" if ui_n == "foxxia" else "◆"
        parts = [f" <b>{tb_icon} {prov}</b>"]

        if show("model"):
            parts.append(f"<b>{mdl}</b>")

        if show("stream"):
            parts.append(stream)

        if show("cwd"):
            parts.append(f"📁{cwd}")

        if show("mem"):
            parts.append(f"mem:{mem_n}")

        if show("branch") and branch:
            parts.append(f"<b>⎇{branch}</b>")

        # Plan
        if show("plan"):
            try:
                _pid   = get_plan(state)
                _pcfg  = PLANS.get(_pid, PLANS["free"])
                _prof  = _toolbar_disk_cache["prof"]
                _msgs  = _prof.get("session_msgs", 0)
                _mlimit = _pcfg["msg_limit"]
                _trial = _toolbar_disk_cache["trial"]
                if _trial:
                    _rem = max(0, _trial["expires"] - now)
                    _ph, _pr = divmod(int(_rem), 3600)
                    parts.append(f"<b>⚡trial</b> {_ph}h{_pr//60:02d}m")
                elif _mlimit >= 99999:
                    parts.append(f"{_pcfg['badge']}{_pcfg['name']}")
                else:
                    parts.append(f"{_pcfg['badge']} {_msgs}/{_mlimit}msg")
            except Exception:
                pass

        # Tokens
        if lt:
            if show("tokens") or show("out_tokens"):
                parts.append(f"<b>{lt.get('out',0)}↑t</b>")
            if show("in_tokens"):
                parts.append(f"{lt.get('in',0)}↓t")
            if show("tokens"):
                parts.append(f"{lt.get('sec',0)}s")

        # Mode
        if show("mode") and chat_mode and chat_mode != "normal":
            parts.append(f"<b>{chat_mode.upper()}</b>")

        # Agent
        if show("agent") and active:
            parts.append(f"<b>🤖{active}</b>")

        # Fast mode indicator
        if show("fast") and state.get("fast_mode"):
            parts.append("<b>⚡FAST</b>")

        # Thinking budget
        budget = state.get("thinking_budget", 0)
        if budget > 0:
            parts.append(f"◈think:{budget//500}s")

        # Working / idle state
        if show("working"):
            parts.append("<b>● WORKING</b>" if working else "○ idle")

        # ── Timer countdown (always shown when set, not field-gated) ──────────
        dl = state.get("_timer_deadline")
        if dl:
            rem = dl - now
            if rem <= 0:
                parts.append("<b>⏰ DEADLINE!</b>")
            else:
                h, r2 = divmod(int(rem), 3600)
                m2, s = divmod(r2, 60)
                timer_str = f"{h}h {m2:02d}m {s:02d}s" if h else f"{m2}m {s:02d}s"
                parts.append(f"<b>⏱{timer_str}</b>")

        return HTML(" · ".join(parts) + " ")
    return _toolbar


def _prompt_box(theme, ui_style, state):
    """Multi-line boxed input prompt, styled per UI."""
    pname  = state.get("session_name") or theme["prompt_name"]
    pc     = _ptk_style_token(theme["prompt_user"])
    ac     = _ptk_style_token(theme["prompt_arrow"])
    active = state.get("active_agent")
    label  = f"agent:{active}" if active else pname
    model_short = _short_model(state.get("model") or "")
    chat_mode   = state.get("_chat_mode", "")
    mode_tag    = f" [{chat_mode.upper()}]" if chat_mode and chat_mode != "normal" else ""

    if ui_style == "studio":
        fill  = max(2, 52 - len(label) - len(model_short) - len(mode_tag))
        top   = f" ╭─ {label}{mode_tag} {'─'*fill} {model_short} ─╮\n"
        mid   = " │ "
        arrow = "› "
        return FormattedText([
            (f"fg:{pc}", top),
            (f"fg:{pc}", mid),
            (f"fg:{ac} bold", arrow),
        ])
    elif ui_style == "ghost":
        return FormattedText([
            ("fg:#555555", f" ◌  {label}  "),
            ("fg:#444444", f"[{model_short}] "),
        ])
    elif ui_style == "nova":
        fill = max(2, 48 - len(label) - len(model_short) - len(mode_tag))
        top  = f" ╔═ ⚡ {label}{mode_tag} {'─'*fill} {model_short} ═╗\n"
        mid  = " ║ "
        return FormattedText([
            (f"fg:{pc}", top),
            (f"fg:{pc}", mid),
            (f"fg:{ac} bold", "⚡ "),
        ])
    elif ui_style == "foxxia":
        label = "foxxia"
        fill = max(2, 52 - len(label) - len(model_short) - len(mode_tag))
        top  = f" ╭─ 🦊 {label}{mode_tag} {'─'*fill} {model_short} ─╮\n"
        mid  = " │ "
        return FormattedText([
            ("fg:#f97316",       top),
            ("fg:#f97316",       mid),
            ("fg:#fbbf24 bold",  "❯ "),
        ])
    elif ui_style == "strawberry":
        label = "strawberry"
        fill = max(2, 52 - len(label) - len(model_short) - len(mode_tag))
        top  = f" ╭─ 🍓 {label}{mode_tag} {'─'*fill} {model_short} ─╮\n"
        mid  = " │ "
        return FormattedText([
            ("fg:#e11d48",       top),
            ("fg:#e11d48",       mid),
            ("fg:#fb7185 bold",  "❯ "),
        ])
    elif ui_style == "darkred":
        label = "darkred"
        fill = max(2, 52 - len(label) - len(model_short) - len(mode_tag))
        top  = f" ╭─ 🩸 {label}{mode_tag} {'─'*fill} {model_short} ─╮\n"
        mid  = " │ "
        return FormattedText([
            ("fg:#8b0000",       top),
            ("fg:#8b0000",       mid),
            ("fg:#dc143c bold",  "❯ "),
        ])
    elif ui_style == "sophia":
        label = "sophia"
        fill = max(2, 52 - len(label) - len(model_short) - len(mode_tag))
        top  = f" ╔═ 💜 {label}{mode_tag} {'─'*fill} {model_short} ═╗\n"
        mid  = " ║ "
        return FormattedText([
            ("fg:#6b21a8",       top),
            ("fg:#6b21a8",       mid),
            ("fg:#c084fc bold",  "✦ "),
        ])
    elif ui_style == "godson":
        label = "godson"
        fill = max(2, 52 - len(label) - len(model_short) - len(mode_tag))
        top  = f" ╭─ ✝ {label}{mode_tag} {'─'*fill} {model_short} ─╮\n"
        mid  = " │ "
        return FormattedText([
            ("fg:#b45309",       top),
            ("fg:#b45309",       mid),
            ("fg:#fde68a bold",  "❯ "),
        ])
    elif ui_style == "downcli":
        return FormattedText([
            ("fg:#6b7280",       f" ▼  down  [{model_short}] "),
        ])
    elif ui_style == "badhappening":
        label = "bad"
        fill = max(2, 52 - len(label) - len(model_short) - len(mode_tag))
        top  = f" ╔═ ⚠ {label}{mode_tag} {'─'*fill} {model_short} ═╗\n"
        mid  = " ║ "
        return FormattedText([
            ("fg:#ea580c",       top),
            ("fg:#ea580c",       mid),
            ("fg:#84cc16 bold",  "! "),
        ])
    elif ui_style == "rain":
        fill = max(2, 48 - len(label) - len(model_short) - len(mode_tag))
        top  = f" ╔═ ░ {label}{mode_tag} {'·'*fill} {model_short} ═╗\n"
        mid  = " ║ "
        return FormattedText([
            ("fg:#00ff41",       top),
            ("fg:#00ff41",       mid),
            ("fg:#00ffff bold",  "░ "),
        ])
    else:
        fill  = max(2, 55 - len(label) - len(model_short))
        top   = f" ╭─ {label} ─{'─'*fill} {model_short} ─╮\n"
        mid   = " │ "
        if ui_style == "codex":
            arrow = "$ "
        elif ui_style == "claude":
            arrow = "> "
        else:
            arrow = "› "
        return FormattedText([
            (f"fg:{pc}", top),
            (f"fg:{pc}", mid),
            (f"fg:{ac} bold", arrow),
        ])


def _sync_state_to_agent(global_state, agent_obj):
    for k in (
        "api_key","openrouter_key","model","use_cli","use_openrouter",
        "theme","theme_name","ui_style","stream_mode",
        "workspace_root","permissions_mode","project_ctx",
    ):
        if k in global_state:
            agent_obj.state[k] = global_state[k]


# ═══════════════════════════════════════════════════════════════
# ── v9.5 QUALITY-OF-LIFE FEATURES ─────────────────────────────
# ═══════════════════════════════════════════════════════════════

def cmd_focus(state, args):
    """/focus [goal] — set a sticky topic/goal that silently prefixes every AI prompt."""
    theme = state.get("theme", THEMES["default"])
    acc   = theme.get("accent", "cyan")
    if not args:
        focus = state.get("_focus")
        if focus:
            console.print(Panel(
                f"  [bold]Active focus:[/bold]\n  {focus}\n\n  [dim]/unfocus to clear[/dim]",
                title="Focus", border_style=acc, padding=(0, 2)
            ))
        else:
            console.print("[dim]No focus set. Usage: /focus <goal or topic>[/dim]")
        return state
    state["_focus"] = args.strip()
    console.print(f"  [{acc}]✓ Focus set:[/{acc}] {args.strip()}")
    console.print("  [dim]All prompts will carry this context silently. /unfocus to clear.[/dim]")
    return state


def cmd_unfocus(state):
    """/unfocus — clear the active focus."""
    theme = state.get("theme", THEMES["default"])
    acc   = theme.get("accent", "cyan")
    if state.pop("_focus", None):
        console.print(f"  [{acc}]✓ Focus cleared.[/{acc}]")
    else:
        console.print("[dim]No focus was set.[/dim]")
    return state


def cmd_swap(state):
    """/swap — toggle between the current and previous model."""
    theme   = state.get("theme", THEMES["default"])
    acc     = theme.get("accent", "cyan")
    current = state.get("model", DEFAULT_MODEL)
    prev    = state.get("_prev_model")
    if not prev or prev == current:
        console.print("[yellow]No previous model to swap to. Switch models with /model <name> first.[/yellow]")
        return state
    state["_prev_model"] = current
    state["model"]       = prev
    save_last_model(prev)
    console.print(f"  [{acc}]⇄ Swapped:[/{acc}] {current} → {prev}")
    return state


def cmd_copy_code(state):
    """/copy-code — extract and copy the last code block from the AI response."""
    import re
    last_r = state.get("_last_response", "")
    theme  = state.get("theme", THEMES["default"])
    if not last_r:
        console.print("[yellow]No response yet.[/yellow]")
        return
    blocks = re.findall(r"```(?:\w+)?\n?(.*?)```", last_r, re.DOTALL)
    if not blocks:
        console.print("[yellow]No code block found in last response.[/yellow]")
        return
    code = blocks[-1].strip()
    try:
        if sys.platform == "win32":
            subprocess.run(["clip"], input=code.encode("utf-8"), check=True)
        else:
            subprocess.run(["xclip", "-selection", "clipboard"], input=code.encode(), check=True)
        lines = code.count("\n") + 1
        console.print(f"[{theme['success']}]✓ Copied code block ({lines} lines) to clipboard[/{theme['success']}]")
    except Exception:
        console.print("[yellow]Clipboard failed. Code block:[/yellow]")
        console.print(Syntax(code[:2000], "text", theme="monokai"))


def cmd_session_info(state, history):
    """/session — live session dashboard: name, model, messages, tokens, focus."""
    theme    = state.get("theme", THEMES["default"])
    border   = theme.get("border", "cyan")
    acc      = theme.get("accent", "cyan")
    name     = state.get("session_name") or "[dim]unnamed[/dim]"
    model    = state.get("model", DEFAULT_MODEL)
    plan_id  = get_plan(state)
    plan     = PLANS.get(plan_id, PLANS["free"])
    ui       = state.get("ui_style") or "gemini"
    stream   = state.get("stream_mode") or "auto"
    focus    = state.get("_focus")
    msgs     = len([h for h in history if h.get("role") == "user"])
    ai_turns = len([h for h in history if h.get("role") == "model"])
    lt       = state.get("_last_tokens") or {}
    focus_line = f"\n  [bold]Focus:[/bold]       {focus[:60]}{'…' if focus and len(focus)>60 else ''}" if focus else ""
    console.print(Panel(
        f"  [bold]Session:[/bold]     {name}\n"
        f"  [bold]Model:[/bold]       {model}\n"
        f"  [bold]Plan:[/bold]        [{plan['color']}]{plan['badge']} {plan['name']}[/{plan['color']}]\n"
        f"  [bold]UI / Stream:[/bold] {ui} / {stream}\n"
        f"  [bold]Messages:[/bold]    {msgs} sent  ·  {ai_turns} AI responses\n"
        f"  [bold]Last tokens:[/bold] {lt.get('in',0):,} in  ·  {lt.get('out',0):,} out"
        f"{focus_line}",
        title="[bold]Session Dashboard[/bold]",
        border_style=border, padding=(0, 2)
    ))


def cmd_clear_history(state, history):
    """/clear-history — wipe conversation history without clearing the screen."""
    theme = state.get("theme", THEMES["default"])
    acc   = theme.get("accent", "cyan")
    turns = len([h for h in history if h.get("role") == "user"])
    reset_msg_counter(state)
    console.print(f"  [{acc}]✓ Cleared {turns} conversation turn(s). Screen preserved.[/{acc}]")
    return []


def cmd_last(state):
    """/last — re-display the last AI response."""
    last_r = state.get("_last_response")
    theme  = state.get("theme", THEMES["default"])
    border = theme.get("border", "cyan")
    if not last_r:
        console.print("[yellow]No response yet.[/yellow]")
        return
    console.print(Panel(Markdown(last_r), title="[bold]Last Response[/bold]", border_style=border))


def cmd_wipe_pins(state):
    """/wipe-pins — delete all pinned notes."""
    theme      = state.get("theme", THEMES["default"])
    acc        = theme.get("accent", "cyan")
    notes_file = CONFIG_DIR / "notes.json"
    try:
        count = 0
        if notes_file.exists():
            count = len(json.loads(notes_file.read_text(encoding="utf-8")))
            notes_file.write_text(json.dumps([]), encoding="utf-8")
        console.print(f"  [{acc}]✓ Wiped {count} pinned note(s).[/{acc}]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def cmd_colors(state):
    """/colors — display the current theme's color palette."""
    theme      = state.get("theme", THEMES["default"])
    theme_name = state.get("theme_name", "default")
    rows = []
    for k, v in theme.items():
        if not isinstance(v, str) or not v:
            continue
        try:
            rows.append(f"  [{v}]███[/{v}]  [dim]{k:<20}[/dim] [bold]{v}[/bold]")
        except Exception:
            rows.append(f"  [dim]{k:<20}[/dim] {v}")
    console.print(Panel(
        "\n".join(rows),
        title=f"[bold]Theme: {theme_name}[/bold]",
        border_style=theme.get("border", "cyan"),
        padding=(0, 1)
    ))


def cmd_model_info(state):
    """/model-info — show context window, pricing, and provider for the active model."""
    model  = state.get("model", DEFAULT_MODEL)
    theme  = state.get("theme", THEMES["default"])
    border = theme.get("border", "cyan")
    # Provider
    if state.get("use_ollama") or model.startswith("ollama/"):
        provider = "Ollama (local)"
    elif state.get("use_openrouter") or "/" in model:
        provider = "OpenRouter"
    elif state.get("use_cli"):
        provider = "Gemini CLI (npx)"
    else:
        provider = "Google Gemini"
    # Pricing
    pricing   = MODEL_PRICING.get(model, {})
    price_in  = pricing.get("in",  DEFAULT_PRICE_PER_1K)
    price_out = pricing.get("out", DEFAULT_PRICE_PER_1K)
    is_free   = price_in == 0.0
    price_str = ("[green]FREE[/green]" if is_free
                 else f"[yellow]${price_in:.4f}[/yellow] / [yellow]${price_out:.4f}[/yellow] per 1M (in/out)")
    # Known context windows
    _CTX = {
        "gemini-2.5-pro":       "1 M tokens",
        "gemini-2.0-flash":     "1 M tokens",
        "gemini-1.5-pro":       "2 M tokens",
        "gemini-1.5-flash":     "1 M tokens",
        "claude-opus-4-7":      "200 K tokens",
        "claude-sonnet-4-6":    "200 K tokens",
        "claude-haiku-4-5":     "200 K tokens",
        "gpt-4o":               "128 K tokens",
        "gpt-4o-mini":          "128 K tokens",
        "llama-3.3-70b":        "128 K tokens",
        "gemma-3-27b":          "128 K tokens",
        "qwen":                 "128 K tokens",
        "deepseek":             "128 K tokens",
    }
    ctx = next((v for k, v in _CTX.items() if k in model), "unknown")
    console.print(Panel(
        f"  [bold]Model:[/bold]    {model}\n"
        f"  [bold]Provider:[/bold] {provider}\n"
        f"  [bold]Context:[/bold]  {ctx}\n"
        f"  [bold]Pricing:[/bold]  {price_str}",
        title="[bold]Model Info[/bold]",
        border_style=border, padding=(0, 2)
    ))


# ── REPL ─────────────────────────────────────────
def run_repl(state):
    HISTORY_FILE.parent.mkdir(exist_ok=True)

    theme, theme_name = load_theme()
    state["theme"]            = theme
    state["theme_name"]       = theme_name
    state["ui_style"]         = state.get("ui_style")         or load_ui_style()
    state["stream_mode"]      = state.get("stream_mode")      or load_stream_mode()
    state["workspace_root"]   = state.get("workspace_root")   or load_workspace_root()
    state["permissions_mode"] = state.get("permissions_mode") or load_permissions_mode()
    state["edit_perm"]        = state.get("edit_perm")        or load_edit_perm()

    ensure_onboarded(state)

    # Reload after onboarding changes — always prefer file-saved values over profile defaults
    theme, theme_name = load_theme()
    state["theme"]            = theme
    state["theme_name"]       = theme_name
    state["ui_style"]         = load_ui_style()
    state["stream_mode"]      = load_stream_mode() or state.get("stream_mode") or "auto"
    state["workspace_root"]   = load_workspace_root() or state.get("workspace_root")
    state["permissions_mode"] = load_permissions_mode() or state.get("permissions_mode") or "workspace"

    if state["model"] == DEFAULT_MODEL:
        last = load_last_model()
        if last:
            state["model"] = last
            console.print(f"[dim]Resuming last model: {last}[/dim]")

    # ── Key bindings ──────────────────────────────────────────
    kb = KeyBindings()

    @kb.add("c-l")
    def _kb_clear(event):
        """Ctrl+L = Clear screen (full cls/clear + scrollback) and reset buffer."""
        clear_terminal()
        render_welcome(state)
        buf = event.current_buffer
        buf.text = ""
        event.app.invalidate()

    # ── Prompt session ────────────────────────────────────────
    class AdvancedCompleter(WordCompleter):
        def get_completions(self, document, complete_event):
            word = document.get_word_before_cursor(WORD=True)
            # 1. Path completion (if not starting with /)
            if word and not word.startswith("/"):
                # Suggest local files
                p = Path(".")
                for f in p.glob(word + "*"):
                    yield __import__("prompt_toolkit.completion", fromlist=["Completion"]).Completion(
                        str(f), start_position=-len(word)
                    )
            # 2. Command completion
            elif word.startswith("/"):
                for cmd in self.words:
                    if cmd.startswith(word):
                        cat, desc = COMMAND_METADATA.get(cmd, ("CMD", "Execute command"))
                        import html as _html
                        display = HTML(
                            f'<style fg="#5f5fff">[{cat:^5}]</style> '
                            f'<style fg="#ffffff">{_html.escape(cmd)}</style> '
                            f'<style fg="#888888"> — {_html.escape(desc)}</style>'
                        )
                        yield __import__("prompt_toolkit.completion", fromlist=["Completion"]).Completion(
                            cmd, start_position=-len(word), display=display
                        )

    completer = AdvancedCompleter(ALL_COMMANDS, pattern=re.compile(r"(/\w*)"))
    
    # Sleek completion menu styling
    session_style = Style.from_dict({
        "prompt":         _ptk_style_token(theme["prompt_user"]),
        "arrow":          _ptk_style_token(theme["prompt_arrow"]),
        "bottom-toolbar": "bg:#1a1a2e fg:#888888",
        "completion-menu.completion": "bg:#1a1a2e fg:#ffffff",
        "completion-menu.completion.current": f"bg:{_ptk_style_token(theme['accent'])} fg:#000000",
        "completion-menu.meta.completion": "bg:#1a1a2e fg:#aaaaaa",
    })

    session = PromptSession(
        history=FileHistory(str(HISTORY_FILE)),
        style=session_style,
        completer=completer,
        complete_while_typing=True,
        key_bindings=kb,
    )
    history = []
    if not state.get("system_prompt"): state["system_prompt"] = load_persona()

    ui_style = state.get("ui_style") or "gemini"

    # Track session login in profile
    _sess_prof = load_profile()
    if _sess_prof:
        _sess_prof["last_seen"]     = datetime.now().isoformat()
        _sess_prof["session_count"] = _sess_prof.get("session_count", 0) + 1
        _hist = _sess_prof.setdefault("login_history", [])
        _hist.append(datetime.now().isoformat())
        if len(_hist) > 50: _sess_prof["login_history"] = _hist[-50:]  # cap
        save_profile(_sess_prof)

    if not state.pop("_skip_welcome", False):
        render_welcome(state)
        _render_pro_welcome(state)
        _show_plan_updates(state)

    if shutil.which("npx") or shutil.which("node"):
        cli = detect_gemini_cli()
        if cli: console.print(f"[{theme['success']}]✦ Gemini CLI detected![/{theme['success']}] Use [bold]/cli on[/bold] to route through it.\n")

    def _mode_str():
        return ("Gemini CLI" if state.get("use_cli")
                else "OpenRouter" if (state.get("use_openrouter") or _is_openrouter_model(state.get("model",""))) and state.get("openrouter_key")
                else "Gemini API")

    stream_mode  = state.get("stream_mode")
    _plan_id     = get_plan(state)
    _plan_badge  = PLANS.get(_plan_id, PLANS["free"])["badge"] + " " + PLANS.get(_plan_id, PLANS["free"])["name"]
    console.print(f"[dim]Mode: {_mode_str()} | Model: {_short_model(state['model'])} | UI: {ui_style} | Plan: {_plan_badge} | Ctrl+L=clear | /help[/dim]\n")

    proj_hint = detect_project_hint(Path.cwd())
    if proj_hint and not state.get("project_ctx"):
        console.print(f"[{theme['success']}]✦ Project detected: {proj_hint}[/{theme['success']}]  Run [bold]/enter .[/bold] to load it\n")

    if state.get("_startup_enter"):
        history = cmd_enter(state, state.pop("_startup_enter"), history, do_briefing=True)
    elif not state.get("project_ctx"):
        # ── Auto /enter: scan cwd if it looks like a project ──────────────────
        _auto_path = Path.cwd()
        _code_exts  = {".py",".js",".ts",".jsx",".tsx",".go",".rs",".java",".c",".cpp",".cs"}
        _has_code   = any(f.suffix in _code_exts for f in _auto_path.iterdir() if f.is_file())
        _has_config = any((_auto_path / f).exists() for f in
                         ["package.json","pyproject.toml","Cargo.toml","go.mod",
                          "requirements.txt","pom.xml","Makefile","CMakeLists.txt"])
        if _has_code or _has_config:
            console.print(f"[dim]✦ Auto-loading project: {_auto_path.name}[/dim]")
            history = cmd_enter(state, str(_auto_path), history, do_briefing=False)

    startup_agent = state.pop("_startup_agent", None)
    if startup_agent:
        aid = resolve_agent_id(startup_agent)
        if not aid:
            console.print(f"[red]Unknown agent: {startup_agent}[/red]")
        else:
            activate_agent_session(state, aid)

    while True:
        try:
            # Check for dev sync/auto-update
            if sync_dev_changes():
                console.print("[dim italic]✦ Dev Sync: aistudio.py updated in AppData[/dim italic]")

            theme    = state.get("theme", THEMES["default"])
            ui_style = state.get("ui_style") or "gemini"
            user_input = session.prompt(
                lambda: _prompt_box(
                    state.get("theme", THEMES["default"]),
                    state.get("ui_style") or "gemini",
                    state,
                ),
                bottom_toolbar=_make_toolbar(state),
            ).strip()

            # Multiline mode: collect lines until a blank line is entered
            if state.get("multiline_mode") and user_input and not user_input.startswith("/"):
                lines = [user_input]
                while True:
                    try:
                        nxt = session.prompt("... ").rstrip("\n")
                    except (KeyboardInterrupt, EOFError):
                        break
                    if nxt == "":
                        break
                    lines.append(nxt)
                user_input = "\n".join(lines)

            if not user_input: continue

            if user_input.startswith("/"):
                parts = user_input[1:].split(" ", 1)
                cmd   = parts[0].lower()
                args  = parts[1].strip() if len(parts) > 1 else ""

                if cmd in ("exit","quit","q"):
                    _watch_stop.set()
                    console.print("[bold cyan]✦ Stay creative. Later! ✦[/bold cyan]"); break

                elif cmd == "help":    cmd_help(state)
                elif cmd == "status":  show_status(state)

                elif cmd == "version":
                    theme2 = state.get("theme", THEMES["default"])
                    console.print(Panel(
                        f"[bold]AI Studio CLI[/bold]  v{VERSION}\n\n"
                        f"[dim]Python {sys.version.split()[0]}[/dim]\n"
                        f"[dim]Config: {CONFIG_DIR}[/dim]",
                        border_style=theme2["border"]))

                elif cmd in ("retry", "again"):
                    last_p = state.get("_last_prompt")
                    if not last_p:
                        console.print("[yellow]Nothing to retry[/yellow]")
                    else:
                        if history and len(history) >= 2:
                            history = history[:-2]
                        _, history = ai_respond(state, last_p, history)

                elif cmd == "copy":
                    last_r = state.get("_last_response")
                    if not last_r:
                        console.print("[yellow]Nothing to copy[/yellow]")
                    else:
                        try:
                            if sys.platform == "win32":
                                subprocess.run(["clip"], input=last_r.encode("utf-8"), check=True)
                            else:
                                subprocess.run(["xclip","-selection","clipboard"], input=last_r.encode(), check=True)
                            console.print("[green]✓ Copied to clipboard[/green]")
                        except Exception:
                            console.print("[yellow]Copy failed (install clip/xclip)[/yellow]")
                            console.print(last_r)

                elif cmd in ("shortcuts", "kb") and not args:
                    theme2 = state.get("theme", THEMES["default"])
                    console.print(Panel(
                        "  [yellow]Ctrl+L[/yellow]        Clear screen & history\n"
                        "  [yellow]Ctrl+C[/yellow]        Cancel current input\n"
                        "  [yellow]Ctrl+D[/yellow]        Exit\n"
                        "  [yellow]↑ / ↓[/yellow]         Browse command history\n"
                        "  [yellow]Tab[/yellow]           Autocomplete commands\n"
                        "  [yellow]/retry[/yellow]        Re-send last message\n"
                        "  [yellow]/copy[/yellow]         Copy last response to clipboard",
                        title="Keyboard Shortcuts", border_style=theme2["border"]))
                elif cmd == "enter":
                    history = cmd_enter(state, args or ".", history, do_briefing=True)
                elif cmd == "ui":      state = cmd_ui(state, args)
                elif cmd == "stream":  state = cmd_stream(state, args)
                elif cmd == "workspace": state = cmd_workspace(state, args)
                elif cmd == "perm":    state = cmd_perm(state, args)
                elif cmd == "cache":   cmd_cache(state, args)
                elif cmd == "clear":
                    history = []
                    reset_msg_counter(state)
                    clear_terminal()
                    t2  = state.get("theme", THEMES["default"])
                    render_welcome(state)
                    _sm = state.get("stream_mode") or "auto"
                    _ui = state.get("ui_style") or "gemini"
                    _pid2 = get_plan(state)
                    _pb2  = PLANS.get(_pid2, PLANS["free"])["badge"] + " " + PLANS.get(_pid2, PLANS["free"])["name"]
                    console.print(f"[dim]Mode: {_mode_str()} | Model: {_short_model(state['model'])} | UI: {_ui} | Plan: {_pb2} | Ctrl+L=clear | /help[/dim]\n")
                    console.print(f"[{t2['success']}]✓ Chat cleared[/{t2['success']}]\n")
                elif cmd == "logout":  state = cmd_logout(state, args)
                elif cmd == "pro":     state = cmd_pro(state, args)
                elif cmd == "inbox":    cmd_inbox(state)
                elif cmd == "notify":  state = cmd_notify(state, args)
                elif cmd == "debug":   state = cmd_debug(state, args)
                elif cmd == "cap":     state = cmd_cap(state, args)
                elif cmd == "tokens":  cmd_tokens(state, args, state.get("_last_tokens"))
                elif cmd == "label":   state = cmd_label(state, args)
                elif cmd == "undo":    cmd_undo(state, args)
                elif cmd == "reload":  state = cmd_reload(state)

                # ── Chat management
                elif cmd == "history": cmd_show_history(history)
                elif cmd == "save":    cmd_save(args or "session", history) if history else console.print("[yellow]Nothing to save[/yellow]")
                elif cmd == "load":
                    if args: history = cmd_load(args)
                    else:    cmd_load("")

                # ── Memory
                elif cmd == "remember": cmd_remember(args) if args else console.print("[yellow]Usage: /remember <fact>[/yellow]")
                elif cmd == "memory":   cmd_show_memory()
                elif cmd == "forget":   cmd_forget(args or None)
                elif cmd == "context":
                    if args:
                        state["context_file"] = args
                        console.print(f"[green]✓ Context file set: {args}[/green]")
                    else:
                        state["context_file"] = None
                        console.print("[yellow]Context cleared[/yellow]")

                # ── AI + Files
                elif cmd == "read":    history = cmd_read(state, args, history) if args else (console.print("[yellow]Usage: /read <file>[/yellow]"), history)[1]
                elif cmd == "write":   history = cmd_write(state, args, history) if args else (console.print("[yellow]Usage: /write <file> <task>[/yellow]"), history)[1]
                elif cmd == "code":    history = cmd_code(state, args, history) if args else (console.print("[yellow]Usage: /code <task>[/yellow]"), history)[1]
                elif cmd == "edit":    history = cmd_edit(state, args, history) if args else (console.print("[yellow]Usage: /edit <file>[/yellow]"), history)[1]
                elif cmd == "fix":     history = cmd_fix(state, args, history) if args else (console.print("[yellow]Usage: /fix <file>[/yellow]"), history)[1]
                elif cmd == "patch":   history = cmd_patch(state, args, history) if args else (console.print("[yellow]Usage: /patch <file> [instruction][/yellow]"), history)[1]
                elif cmd == "analyze": history = cmd_analyze(state, args or ".", history)

                # ── PROJECT LOADER
                elif cmd in ("project","proj","lp"):
                    path     = args or "."
                    do_brief = console.input("[bold]AI project briefing? (y/n): [/bold]").strip().lower() == "y"
                    history  = cmd_enter(state, path, history, do_briefing=do_brief)

                elif cmd in ("readdir","rd","scandir"):
                    history = cmd_readdir(state, args or ".", history)

                elif cmd == "projectinfo":
                    ctx = state.get("project_ctx")
                    if not ctx:
                        console.print("[yellow]No project loaded — use /enter <path>[/yellow]")
                    else:
                        console.print(Panel(ctx["tree"][:3000], title="Project Tree", border_style="cyan"))

                # ── AGENTS
                elif cmd == "agents":
                    cmd_agents(state)

                elif cmd == "agent":
                    if not args:
                        cmd_agents(state)
                    else:
                        p2   = args.split(" ", 1)
                        sub  = p2[0].strip().lower()
                        rest = p2[1].strip() if len(p2) > 1 else ""

                        if sub == "squad":
                            if not rest:
                                console.print("[yellow]Usage: /agent squad <id1,id2,...>[/yellow]")
                            else:
                                ids      = [x.strip() for x in rest.split(",") if x.strip()]
                                resolved = [resolve_agent_id(x) for x in ids]
                                resolved = [x for x in resolved if x]
                                if not resolved:
                                    console.print("[red]No valid agents in list[/red]")
                                else:
                                    task2 = console.input("[bold]Squad task: [/bold]").strip()
                                    if task2:
                                        ctx = state.get("project_ctx")
                                        state.setdefault("agents", {})
                                        console.print(f"[bold]Squad: {', '.join(resolved)}[/bold]")
                                        results2 = []
                                        for aid in resolved:
                                            state["agents"][aid] = Agent(aid, state, ctx)
                                            r2 = state["agents"][aid].run(task2, console, ai_respond)
                                            results2.append((AGENT_ROSTER[aid]["name"], r2))
                                        if len(results2) > 1 and console.input("[bold]Synthesize results? (y/n): [/bold]").strip().lower() == "y":
                                            combined     = "\n\n".join(f"=== {n} ===\n{r}" for n, r in results2)
                                            squad_prompt = "Squad results for: " + repr(task2) + "\n\n" + combined + "\n\nSynthesize into one final answer."
                                            _, history   = ai_respond(state, squad_prompt, history)
                        elif sub == "new":
                            console.print("[yellow]Custom agents not implemented in this build yet.[/yellow]")
                        else:
                            aid = resolve_agent_id(sub)
                            if not aid:
                                console.print(f"[red]Unknown agent. Try: {', '.join(AGENT_ROSTER.keys())}[/red]")
                            elif not rest:
                                activate_agent_session(state, aid)
                            else:
                                ctx = state.get("project_ctx")
                                state.setdefault("agents", {})
                                if aid not in state["agents"]:
                                    state["agents"][aid] = Agent(aid, state, ctx)
                                agent = state["agents"][aid]
                                if rest.startswith("/"):
                                    handled = agent_slash_dispatch(state, agent, rest)
                                    if not handled:
                                        console.print(f"[yellow]Unknown: {rest} — /help[/yellow]")
                                else:
                                    result = agent.run(rest, console, ai_respond)
                                    history.append({"role":"user","text":f"[{agent.name}] {rest}"})
                                    history.append({"role":"model","text":result or ""})

                elif cmd == "spawn":
                    aid = args.strip().lower() if args else ""
                    aid = resolve_agent_id(aid)
                    if not aid:
                        console.print(f"[red]Unknown agent. Try: {', '.join(AGENT_ROSTER.keys())}[/red]")
                    else:
                        activate_agent_session(state, aid)

                elif cmd == "squad":
                    task2 = args or console.input("[bold]Task for the squad: [/bold]").strip()
                    if task2:
                        ctx = state.get("project_ctx")
                        state.setdefault("agents", {})
                        assigned = auto_assign_agents(task2)
                        console.print(f"[bold]Squad: {', '.join(assigned)}[/bold]")
                        results2 = []
                        for aid in assigned:
                            if aid not in state["agents"]:
                                state["agents"][aid] = Agent(aid, state, ctx)
                            r2 = state["agents"][aid].run(task2, console, ai_respond)
                            results2.append((AGENT_ROSTER[aid]["name"], r2))
                        if len(results2) > 1 and console.input("[bold]Synthesize results? (y/n): [/bold]").strip().lower() == "y":
                            combined     = "\n\n".join(f"=== {n} ===\n{r}" for n, r in results2)
                            squad_prompt = "Squad results for: " + repr(task2) + "\n\n" + combined + "\n\nSynthesize into one final answer."
                            _, history   = ai_respond(state, squad_prompt, history)

                elif cmd == "autoagent":
                    task2 = args or console.input("[bold]Task (best agent auto-selected): [/bold]").strip()
                    if task2:
                        aid   = pick_best_agent(task2)
                        info2 = AGENT_ROSTER[aid]
                        console.print(f"[dim]Auto → {info2['emoji']} {info2['name']} ({info2['role']})[/dim]")
                        ctx = state.get("project_ctx")
                        state.setdefault("agents", {})
                        if aid not in state["agents"]:
                            state["agents"][aid] = Agent(aid, state, ctx)
                        result = state["agents"][aid].run(task2, console, ai_respond)
                        history.append({"role":"user","text":task2})
                        history.append({"role":"model","text":result or ""})

                elif cmd == "explain":
                    p2 = args.split(" ", 1)
                    history = cmd_explain(state, p2[0], p2[1], history) if len(p2)==2 else (console.print("[yellow]Usage: /explain <file> <line>[/yellow]"), history)[1]

                # ── Filesystem
                elif cmd == "ls":      cmd_ls(state, args or ".")
                elif cmd == "cd":      cmd_cd(state, args) if args else console.print(f"[cyan]{os.getcwd()}[/cyan]")
                elif cmd == "pwd":     console.print(f"[cyan]{os.getcwd()}[/cyan]")
                elif cmd == "tree":    cmd_tree(state, args or ".")
                elif cmd == "summary": cmd_summary(state, args or ".")
                elif cmd == "cat":     cmd_cat(state, args) if args else console.print("[yellow]Usage: /cat <file>[/yellow]")
                elif cmd == "find":
                    p2 = args.split(" ",1)
                    cmd_find(state, p2[0], p2[1] if len(p2)>1 else ".") if p2 and p2[0] else console.print("[yellow]Usage: /find <pattern>[/yellow]")
                elif cmd == "grep":
                    p2 = args.split(" ",1)
                    cmd_grep(state, p2[0], p2[1] if len(p2)>1 else ".") if p2 and p2[0] else console.print("[yellow]Usage: /grep <text>[/yellow]")
                elif cmd == "mkdir":   cmd_mkdir(state, args) if args else console.print("[yellow]Usage: /mkdir <path>[/yellow]")
                elif cmd == "rm":      cmd_rm(state, args) if args else console.print("[yellow]Usage: /rm <file>[/yellow]")
                elif cmd == "cp":
                    p2 = args.split(" ",1)
                    cmd_cp(state, p2[0],p2[1]) if len(p2)==2 else console.print("[yellow]Usage: /cp <src> <dst>[/yellow]")
                elif cmd == "mv":
                    p2 = args.split(" ",1)
                    cmd_mv(state, p2[0],p2[1]) if len(p2)==2 else console.print("[yellow]Usage: /mv <src> <dst>[/yellow]")
                elif cmd == "diff":
                    p2 = args.split(" ",1)
                    cmd_diff(state, p2[0],p2[1]) if len(p2)==2 else console.print("[yellow]Usage: /diff <f1> <f2>[/yellow]")

                # ── Dev tools
                elif cmd == "shell":   history = cmd_shell(state, args, history) if args else (console.print("[yellow]Usage: /shell <cmd>[/yellow]"), history)[1]
                elif cmd == "run":     history = cmd_run(state, args, history) if args else (console.print("[yellow]Usage: /run <file>[/yellow]"), history)[1]
                elif cmd == "git":     history = cmd_git(state, args, history)
                elif cmd == "watch":   history = cmd_watch(state, args, history) if args else (console.print("[yellow]Usage: /watch <file> | /watch off[/yellow]"), history)[1]

                # ── Config
                elif cmd == "persona": state = cmd_persona(state, args)
                elif cmd == "compare": cmd_compare(state, args) if args else console.print("[yellow]Usage: /compare <prompt>[/yellow]")
                elif cmd == "model":
                    if args:
                        state["_prev_model"] = state.get("model")
                        state["model"] = args
                        save_last_model(args)
                        theme = state.get("theme", THEMES["default"])
                        console.print(f"[{theme['success']}]✓ Model → {args}[/{theme['success']}]")
                    else:
                        console.print(f"[dim]Current: {state['model']}[/dim]")
                elif cmd == "models":
                    state = cmd_models(state)
                elif cmd == "cli":
                    if args=="on":
                        cli2 = detect_gemini_cli()
                        if cli2 or shutil.which("npx"):
                            state["use_cli"]=True
                            console.print(f"[green]✓ Gemini CLI {'('+cli2+')' if cli2 else '(npx)'} enabled[/green]")
                        else: console.print("[red]Node.js not found. Install from nodejs.org[/red]")
                    elif args=="off": state["use_cli"]=False; console.print("[yellow]✓ CLI disabled[/yellow]")
                    else: console.print("[yellow]Usage: /cli on|off[/yellow]")
                elif cmd == "openrouter":
                    if args:
                        save_or_key(args); state["openrouter_key"]=args; state["use_openrouter"]=True
                        console.print("[green]✓ OpenRouter key saved![/green]")
                    else: console.print("[yellow]Usage: /openrouter YOUR_KEY[/yellow]")
                elif cmd == "theme":
                    state = cmd_theme(state, args)
                elif cmd in ("imagine","img","image","gen"):
                    cmd_imagine(state, args) if args else console.print(
                        "[yellow]Usage: /imagine <prompt> [--model flux-schnell|flux-dev|sdxl|sd15][/yellow]\n"
                        "[dim]Models: flux-schnell (default), flux-dev, sdxl, sd15[/dim]")
                elif cmd == "hf":
                    if args:
                        save_hf_key(args); state["hf_key"] = args
                        console.print("[green]✓ HuggingFace token saved![/green]")
                        console.print("[dim]Try: /imagine a neon cyberpunk city[/dim]")
                    else:
                        console.print("[yellow]Usage: /hf YOUR_HUGGINGFACE_TOKEN[/yellow]")
                elif cmd == "keys":          state = cmd_keys(state, args)
                elif cmd == "studio-models": cmd_studio_models(state)
                elif cmd == "studio-model":  state = cmd_studio_model(state, args)
                elif cmd == "cavecat":       state = cmd_cavecat(state)
                elif cmd == "millieman":     state = cmd_millieman(state)
                elif cmd == "imgmodel":
                    if args in IMAGE_MODELS:
                        state["img_model"] = args
                        console.print(f"[green]✓ Image model → {args} ({IMAGE_MODELS[args]})[/green]")
                    else:
                        console.print(Panel(
                            "\n".join(f"  [yellow]{k}[/yellow] — {v}" for k,v in IMAGE_MODELS.items()),
                            title="Image Models", border_style="cyan"))
                elif cmd == "todo":           cmd_todo(state)
                elif cmd == "bench":          cmd_bench(state)
                elif cmd == "tts":            cmd_tts(state, args)
                elif cmd == "voice":          cmd_voice(state, args)
                elif cmd == "export":         cmd_export(state, history)
                elif cmd == "balance":        cmd_balance(state)
                elif cmd == "cost":           cmd_cost(state, args)
                elif cmd == "lint":           cmd_lint(state, args)
                elif cmd == "fif":            history = cmd_fif(state, args, history)
                elif cmd == "snippet":        cmd_snippet(state, args)
                elif cmd == "translate":      history = cmd_translate(state, args, history) if args else (console.print("[yellow]Usage: /translate <lang> [text][/yellow]"), history)[1]
                elif cmd == "changelog":      cmd_changelog(state)
                elif cmd in ("remote-control","remote","rc"): history = cmd_remote_control(state, args, history)
                elif cmd == "profile-card":   cmd_profile_card(state)
                elif cmd == "mode":           state = cmd_chat_mode(state, args)
                elif cmd == "sidebar":        cmd_sidebar(state)
                elif cmd == "thinking":   state = cmd_thinking(state, args)
                elif cmd == "fast":       state = cmd_fast(state, args)
                elif cmd in ("time", "timer", "deadline"): state = cmd_timer(state, args)
                elif cmd == "statusline": state = cmd_statusline(state, args)
                elif cmd == "arena":      history = cmd_arena(state, args, history)
                elif cmd == "broadcast":  cmd_broadcast(state, args)
                elif cmd == "local":      state = cmd_local(state, args)
                elif cmd == "mesh":
                    console.print(Panel(json.dumps(BLACKBOARD, indent=2), title="Agent Mesh Blackboard", border_style="magenta"))
                elif cmd == "live-fif":
                    if _live_watch_stop.is_set():
                        _live_watch_stop.clear()
                        start_live_watcher(state, history)
                    else:
                        _live_watch_stop.set()
                        console.print("[yellow]📡 Live-FIF deactivated.[/yellow]")
                elif cmd == "cursor":
                    if args:
                        CURSOR_FILE.parent.mkdir(exist_ok=True)
                        CURSOR_FILE.write_text(args.strip())
                        state["cursor_key"] = args.strip()
                        console.print("[green]✓ Cursor API key saved![/green]")
                    else: console.print("[yellow]Usage: /cursor YOUR_KEY[/yellow]")
                elif cmd == "feedback":   cmd_feedback(state, args)
                elif cmd == "complain":   cmd_complain(state, args)
                elif cmd == "audit":      cmd_audit(state)
                elif cmd == "search":     cmd_search(state, args)
                elif cmd == "docs":       cmd_docs(state, args, history)
                elif cmd == "test":       cmd_test(state, args, history)
                elif cmd == "fix-self":   # Experimental: Allow Studio to fix itself
                    console.print("[bold cyan]🔧 Self-Repair Protocol Initiated...[/bold cyan]")
                    history = cmd_fif(state, "aistudio.py", history)
                elif cmd == "upgrade":        cmd_upgrade(state, args)
                elif cmd == "plan":           cmd_plan(state)
                elif cmd == "permissions":    state = cmd_permissions(state)
                elif cmd == "beta":
                    _beta_sub = (args or "").strip().lower().split(" ", 1)[0]
                    if _beta_sub in ("docx", "xlsx", "screenshot", "image", "img", "vision", "video", "feedback"):
                        history = cmd_beta_features(state, args, history)
                    else:
                        cmd_beta(state, args)
                elif cmd == "usage":          cmd_usage(state)
                elif cmd == "trial":          state = cmd_trial(state, args)
                elif cmd in ("update", "studio-update"): cmd_studio_update(state)

                # ── New commands ──────────────────────────────────────────────
                elif cmd == "diffpatch":   history = cmd_diffpatch(state, args, history) if args else (console.print("[yellow]Usage: /diffpatch <file> [instruction][/yellow]"), history)[1]
                elif cmd == "format":      cmd_format(state, args) if args else console.print("[yellow]Usage: /format <file>[/yellow]")
                elif cmd in ("name", "n"): state = cmd_name(state, args, history)
                elif cmd == "handoff":     history = cmd_handoff(state, args, history)
                elif cmd == "rename":      history = cmd_rename(state, args, history) if args else (console.print("[yellow]Usage: /rename <old> <new>[/yellow]"), history)[1]
                elif cmd == "outline":     history = cmd_outline(state, args, history) if args else (console.print("[yellow]Usage: /outline <file>[/yellow]"), history)[1]
                elif cmd == "comment":     history = cmd_comment(state, args, history) if args else (console.print("[yellow]Usage: /comment <file>[/yellow]"), history)[1]
                elif cmd in ("summarize-history","sh"): history = cmd_summarize_history(state, history)
                elif cmd in ("wc","word-count","wordcount"): cmd_wordcount(state, args)
                elif cmd == "duplicate":   cmd_duplicate(state, args) if args else console.print("[yellow]Usage: /duplicate <src> <dst>[/yellow]")
                elif cmd == "template":    history = cmd_template(state, args, history)
                elif cmd == "pin":         state = cmd_pin(state, args)
                elif cmd == "hotswap":     state = cmd_hotswap(state, args)
                elif cmd == "rephrase":    history = cmd_rephrase(state, args, history)
                elif cmd == "ask":         cmd_ask(state, args) if args else console.print("[yellow]Usage: /ask <question>[/yellow]")
                elif cmd == "reload-keys": state = cmd_reload_keys(state)
                elif cmd == "multi":       history = cmd_multi(state, args, history) if args else (console.print("[yellow]Usage: /multi <m1,m2> <prompt>[/yellow]"), history)[1]
                elif cmd == "zip":         cmd_zip(state, args) if args else console.print("[yellow]Usage: /zip <dir>[/yellow]")
                elif cmd == "env":         cmd_env(state)
                elif cmd == "count":       cmd_count(state, args) if args else console.print("[yellow]Usage: /count <pattern> <file>[/yellow]")
                elif cmd == "timeit":      history = cmd_timeit(state, args, history) if args else (console.print("[yellow]Usage: /timeit <question>[/yellow]"), history)[1]
                elif cmd == "free-tips": cmd_free_tips(state)

                # ── v5.6 new commands ─────────────────────────────────────────
                elif cmd == "summarize":  history = cmd_summarize(state, history)
                elif cmd == "autonomous": history = cmd_autonomous(state, args, history); _patch_autonomous_writes(state)
                elif cmd in ("creator","creator-analytics"): cmd_creator_analytics(state)

                # ── v5.7 new commands ─────────────────────────────────────────
                elif cmd == "vibe":       state = cmd_vibe(state, args)
                elif cmd == "quickstart": cmd_quickstart(state)
                elif cmd in ("restart", "reboot"): cmd_restart(state)
                elif cmd in ("pick", "model-pick", "mpick"): state = cmd_models(state)

                # ── v5.8 new commands ─────────────────────────────────────────
                elif cmd in ("profile", "me"):           cmd_profile_view(state)
                elif cmd in ("insights", "stats"):       cmd_insights(state)
                elif cmd == "vault":                     cmd_vault(state, args)
                elif cmd == "team":                      cmd_team(state, args)

                # ── v9.1 new commands ────────────────────────────────────────
                elif cmd == "alias":
                    # Check if first word of args is a known alias expansion trigger
                    history = cmd_alias(state, args, history)
                elif cmd == "multiline":  state = cmd_multiline(state, args)
                elif cmd == "note":       cmd_note(state, args)
                elif cmd == "regen":      history = cmd_regen(state, args, history)
                elif cmd in ("context-bar", "ctxbar", "ctx"):
                    cmd_context_bar(state, history)
                elif cmd == "resume":     history = cmd_resume(state, args, history)
                elif cmd in ("history-search", "hsearch", "hs"):
                    history = cmd_history_search(state, args, history)
                elif cmd == "compact":    history = cmd_compact(state, args, history)
                elif cmd == "clip":       cmd_clip(state, args)

                # ── v5.9 Max / Team / Enterprise ──────────────────────────────
                elif cmd in ("audit-log", "auditlog"):   cmd_audit_log(state, args)
                elif cmd in ("priority-queue", "priorityqueue", "priority"): cmd_priority_queue(state, args)
                elif cmd in ("orgmetrics", "orgstats", "org"): cmd_orgmetrics(state, args)
                elif cmd == "sso":                       cmd_sso(state, args)
                elif cmd == "policy":                    cmd_policy(state, args)

                # ── v9 Beta (ultra) ───────────────────────────────────────────
                elif cmd in ("labs", "flags"):
                    cmd_beta(state, args)  # flags/labs always route to flag manager
                elif cmd in ("mesh-broadcast", "meshbroadcast", "broadcast-all"):
                    history = cmd_mesh_broadcast(state, args, history)
                elif cmd in ("analytics-pro", "analyticspro"):
                    cmd_analytics_pro(state, args)

                # ── v9.0 (pro) ────────────────────────────────────────────────
                elif cmd == "plugin":
                    cmd_plugin(state, args)
                elif cmd in ("agent-mesh", "agentmesh"):
                    history = cmd_agent_mesh(state, args, history)
                elif cmd in ("vision-pro", "visionpro", "vpro"):
                    history = cmd_vision_pro(state, args, history)

                # ── v8.0 ──────────────────────────────────────────────────────
                elif cmd in ("whats-new", "whatsnew", "new", "changelog-v8"):
                    cmd_whats_new(state)
                elif cmd in ("snapshot", "snap"):
                    history = cmd_snapshot(state, args, history)
                elif cmd in ("open-web", "openweb", "web-ui", "webui"):
                    cmd_open_web(state, args)
                elif cmd in ("tip", "tips", "hint"):
                    cmd_tip(state, args)
                elif cmd == "speed":  state = cmd_speed(state, args)
                elif cmd == "effort": state = cmd_effort(state, args)

                # ── v9.3 new commands ────────────────────────────────────────
                elif cmd in ("websearch", "web"):
                    state, history = cmd_websearch(state, args, history)
                elif cmd in ("research", "deep-research", "deepresearch"):
                    history = cmd_research(state, args, history)
                elif cmd == "turbo":
                    state = cmd_turbo(state, args)
                elif cmd == "credits":
                    state = cmd_credits(state)
                elif cmd in ("computer-use", "computeruse", "computer"):
                    state = cmd_computer_use(state, args)
                elif cmd in ("extension", "ext", "chrome-extension"):
                    state = cmd_extension(state, args)

                # ── v9.2 Codex killers ───────────────────────────────────────
                elif cmd in ("pr-review", "prreview", "review-pr"):
                    history = cmd_pr_review(state, args, history)
                elif cmd in ("git-suggest", "gitsuggest", "git-ai"):
                    history = cmd_git_suggest(state, args, history)
                elif cmd in ("test-coverage", "testcov", "coverage"):
                    history = cmd_test_coverage(state, args, history)
                elif cmd in ("safety-check", "safetycheck", "sec", "scan"):
                    history = cmd_safety_check(state, args, history)

                # ── v9.5 features ──────────────────────────────────────────
                elif cmd == "recap":
                    history = cmd_recap(state, args, history)
                elif cmd in ("gitdiff", "gd"):
                    cmd_gitdiff(state, args)
                elif cmd in ("branch", "br"):
                    cmd_branch(state, args)
                elif cmd == "set":
                    # /set model <name>
                    sub, _, rest2 = (args or "").partition(" ")
                    if sub.strip().lower() == "model":
                        state = cmd_setmodel(state, rest2.strip())
                    else:
                        console.print("[yellow]Usage: /set model <model-id>[/yellow]")
                elif cmd in ("qnote", "quicknote"):
                    cmd_quicknote(state, args)
                elif cmd in ("qnotes", "quicknotes"):
                    cmd_quicknotes(state, args)

                # ── v9.5 QoL ─────────────────────────────────────────────
                elif cmd == "focus":           state = cmd_focus(state, args)
                elif cmd == "unfocus":         state = cmd_unfocus(state)
                elif cmd == "swap":            state = cmd_swap(state)
                elif cmd in ("copy-code", "copycode", "cc"): cmd_copy_code(state)
                elif cmd in ("session", "sess"): cmd_session_info(state, history)
                elif cmd in ("clear-history", "ch"): history = cmd_clear_history(state, history)
                elif cmd == "last":            cmd_last(state)
                elif cmd in ("wipe-pins", "wipepins"): cmd_wipe_pins(state)
                elif cmd == "colors":          cmd_colors(state)
                elif cmd in ("model-info", "modelinfo", "minfo"): cmd_model_info(state)

                else:
                    # Check user-defined aliases first
                    _user_aliases = _load_aliases()
                    if cmd in _user_aliases:
                        console.print(f"  [dim]Alias → {_user_aliases[cmd][:60]}[/dim]")
                        _, history = ai_respond(state, _user_aliases[cmd], history)
                        _autosave_session(history)
                    else:
                        # 10. Auto-Corrector Feature
                        from difflib import get_close_matches
                        matches = get_close_matches("/" + cmd, ALL_COMMANDS, n=1, cutoff=0.7)
                        if matches:
                            console.print(f"[yellow]Unknown: /{cmd}. Did you mean [bold]{matches[0]}[/bold]?[/yellow]")
                        else:
                            console.print(f"[yellow]Unknown: /{cmd} — /help[/yellow]")
            else:
                active = state.get("active_agent")
                if active and active in state.get("agents", {}):
                    if user_input.strip().lower() in ("exit", "/exit", "/back", "/off", "/exit-agent"):
                        state["active_agent"] = None
                        console.print("[dim]Returned to normal chat[/dim]")
                    elif user_input.startswith("/"):
                        agent_obj = state["agents"][active]
                        handled   = agent_slash_dispatch(state, agent_obj, user_input)
                        if not handled:
                            console.print(f"[yellow]Unknown: {user_input} — /help[/yellow]")
                    else:
                        r = state["agents"][active].run(user_input, console, ai_respond)
                        history.append({"role":"user","text":user_input})
                        history.append({"role":"model","text":r or ""})
                else:
                    # ── Echo user input (Claude Code style) ──────────
                    _ui = state.get("ui_style") or "gemini"
                    _th = state.get("theme", THEMES["default"])
                    _pc = _th["prompt_user"]
                    _preview = user_input if len(user_input) <= 72 else user_input[:69] + "..."
                    console.print(f"[{_pc}]  ▸ {_preview}[/{_pc}]")

                    # ── Mode detection ────────────────────────────────
                    detected_mode = detect_input_mode(user_input)
                    if detected_mode == "insult":
                        result = handle_insult(state)
                        if result in ("silicon-speak", "roasted"):
                            continue
                        # If SystemExit was raised it exits; otherwise fall through
                    else:
                        prev_mode = state.get("_chat_mode", "normal")
                        if detected_mode != "normal" and detected_mode != prev_mode:
                            state["_chat_mode"] = detected_mode
                            mode_labels = {
                                "casual":  "😎 Casual",
                                "build":   "🔨 Build",
                                "analyze": "🔍 Analyze",
                                "fif":     "🐛 FIF",
                            }
                            console.print(f"[dim]  ◆ Mode switched → {mode_labels.get(detected_mode, detected_mode)}[/dim]")
                        # ── Free plan: message cap ────────────────────
                        _allowed, _used, _limit = check_msg_limit(state)
                        _is_free = get_plan(state) == "free"
                        if _allowed and _is_free and _used >= _limit - 3 and _used < _limit:
                            _rem = _limit - _used
                            _msg = (
                                f"  ⚠  [bold]{_rem} message{'s' if _rem!=1 else ''} left[/bold] on Free plan.\n"
                                "  Free plan is limited to 1 model (Nemotron) · no file ops · no images.\n"
                                "  [bold yellow]/trial pro[/bold yellow] → unlock everything for 5 hours, free."
                            )
                            console.print(Panel(_msg, border_style="dark_orange", padding=(0,2)))
                        if not _allowed:
                            locked_model = PLANS["free"]["models"][0].split("/")[-1] if PLANS["free"].get("models") else "nemotron"
                            console.print(Panel(
                                f"[bold red]✖  Session limit reached[/bold red] — [bold]{_limit}[/bold] messages used.\n\n"
                                f"  You've been using [dim]{locked_model}[/dim] (free tier model).\n"
                                "  Here's what you're missing on Pro:\n"
                                "  [green]✓[/green] 500 msgs/session  [green]✓[/green] All models  [green]✓[/green] Images  [green]✓[/green] File ops\n\n"
                                "  [bold yellow]/trial pro[/bold yellow]    → [green]5h of Pro access — free, no card needed[/green]\n"
                                "  [yellow]/upgrade pro[/yellow]    → 500 msgs · all models · $18/mo\n"
                                "  [yellow]/upgrade max[/yellow]    → 5,000 msgs · no limits · $80/mo\n"
                                "  [dim]/clear[/dim]           → reset session counter (Free stays Free)",
                                title="[bold red]○  Free Plan — Hard Limit[/bold red]",
                                border_style="red", padding=(1, 2)))
                            continue
                        state["_last_prompt"] = user_input
                        # Apply sticky /focus prefix if set
                        _focus = state.get("_focus")
                        _effective = (f"[Context — stay focused on: {_focus}]\n\n{user_input}"
                                      if _focus else user_input)
                        tmp_ctx = state.pop("_one_shot_ctx", None)
                        if isinstance(tmp_ctx, dict) and "error" not in tmp_ctx:
                            prompt     = format_project_context(tmp_ctx, max_files=8) + "\n\n---\n\nQuestion: " + _effective
                            _, history = ai_respond(state, prompt, history)
                        else:
                            _, history = ai_respond(state, _effective, history)
                        # Auto-save session after every exchange
                        _autosave_session(history)

        except KeyboardInterrupt:
            if state.get("_working"):
                state["_working"] = False
                _stop_think_anim()
                console.print("\n[dim]⚡ Cancelled.[/dim]")
            else:
                console.print("\n[dim]Ctrl+C — /exit to quit[/dim]")
        except EOFError: console.print("\n[bold cyan]✦ Later![/bold cyan]"); break

# ── HELPER CMD FUNCTIONS ──────────────────────────
def cmd_read(state, path, history):
    try:
        content, p = read_file_state(state, path)
        ext     = p.suffix.lstrip(".") or "text"
        preview = content[:3000]+("…" if len(content)>3000 else "")
        console.print(Panel(Syntax(preview, ext, theme="monokai", line_numbers=True),
            title=f"[bold]📄 {p}[/bold]", border_style="cyan"))
        prompt = f"Analyze `{p}`:\n\n```{ext}\n{content}\n```\n\nDescribe it, find issues, suggest improvements."
        _, history = ai_respond(state, prompt, history)
    except Exception as e: console.print(f"[red]{e}[/red]")
    return history


def cmd_write(state, args, history):
    """Generate a file with AI and save it. FIX: proper fences strip + preview."""
    parts = args.split(" ", 1)
    if len(parts) < 2:
        console.print("[yellow]Usage: /write <file> <task>[/yellow]")
        return history
    filename = parts[0].strip()
    task     = parts[1].strip()
    ext      = Path(filename).suffix.lstrip(".") or "text"
    response, history = ai_respond(state,
        f"Write the following content for a file named '{filename}'.\n"
        f"Output ONLY the raw file content with NO markdown fences, NO explanations, NO preamble.\n\n"
        f"Task: {task}", history)
    if response:
        clean = strip_fences(response)
        console.print(f"\n[bold]Preview (first 20 lines):[/bold]")
        console.print(Panel(Syntax("\n".join(clean.split("\n")[:20]), ext, theme="monokai"), border_style="cyan"))
        if check_write_allowed(state, filename, "save"):
            write_file_state(state, filename, clean)
    return history


def cmd_code(state, args, history):
    """Write code with AI, show preview, then optionally save. FIX: preview before save."""
    response, history = ai_respond(state,
        f"Write code for the following task. Output ONLY the code, no markdown fences, no explanation.\n\nTask: {args}", history)
    if response:
        clean = strip_fences(response)
        save  = console.input("\n[bold]Save to file? (filename or Enter to skip): [/bold]").strip()
        if save:
            ext = Path(save).suffix.lstrip(".") or "text"
            console.print(Panel(Syntax("\n".join(clean.split("\n")[:20]), ext, theme="monokai"), border_style="cyan"))
            if check_write_allowed(state, save, "save"):
                write_file_state(state, save, clean)
    return history


def cmd_edit(state, path, history):
    try:
        p        = resolve_path(state, path, must_exist=False, for_write=True)
        original = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
        console.print(f"[dim]Opening {p}...[/dim]")
        modified = open_editor(original, p.suffix or ".txt")
        if modified==original: console.print("[yellow]No changes.[/yellow]"); return history
        write_file_state(state, str(p), modified)
        if console.input("[bold]Ask AI to review? (y/n): [/bold]").strip().lower()=="y":
            _, history = ai_respond(state, f"I edited `{p}`:\n\n```\n{modified}\n```\n\nReview it.", history)
    except Exception as e: console.print(f"[red]{e}[/red]")
    return history

# ── ENTRY POINT ───────────────────────────────────
def main():
    # Trigger dev sync / auto-update immediately
    sync_res = sync_dev_changes()
    if sync_res == "pulled":
        console.print("[bold green]✦ Auto-Update: Applied latest changes from workspace. Please restart.[/bold green]")
        sys.exit(0)
    elif sync_res == "pushed":
        console.print("[dim italic]✦ Dev Sync: Pushed changes to AppData[/dim italic]")

    parser = argparse.ArgumentParser(
        description=f"AI Studio CLI v{VERSION} — Advanced AI Terminal Interface",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
    [bold cyan]Updates & Tiers:[/bold cyan]
    - [dim]Free:[/dim] Nemotron-only access
    - [dim]Pro/Max:[/dim] Priority API access & Leaks
    - [dim]Team:[/dim] Org-managed seats (requires Admin)

    [bold]Usage:[/bold]
    - [cyan]/help[/cyan]      Show this menu
    - [cyan]Ctrl+C[/cyan]    Interrupt AI response
    - [cyan]Cursor[/cyan]    Use /cursor <key> to enable

    [dim]See docs for more.[/dim]
        """
    )
    parser.add_argument("prompt",      nargs="?", help="One-shot prompt")
    parser.add_argument("-r","--read", metavar="FILE")
    parser.add_argument("-m","--model",default=DEFAULT_MODEL)
    parser.add_argument("--setup",     action="store_true")
    parser.add_argument("--key",       metavar="KEY")
    parser.add_argument("--cli",       action="store_true")
    parser.add_argument("--openrouter",metavar="KEY")
    parser.add_argument("--persona",   metavar="NAME")
    parser.add_argument("--enter",     metavar="DIR", help="Scan project and load context on startup")
    parser.add_argument("--agent",     metavar="ID",  help="Start in an agent session on startup")
    args = parser.parse_args()

    if args.setup or args.key:
        save_api_key(args.key) if args.key else setup_api_key()
        if args.key: console.print("[green]✓ API key saved![/green]")
        return

    model_arg = args.model
    if model_arg == DEFAULT_MODEL:
        last = load_last_model()
        if last: model_arg = last

    state = {
        "api_key":        load_api_key(),
        "openrouter_key": args.openrouter or load_or_key(),
        "model":          model_arg,
        "use_cli":        args.cli,
        "use_openrouter": bool(args.openrouter or load_or_key()),
        "system_prompt":  None,
        "context_file":   None,
        "theme":          None,
        "theme_name":     "default",
        "hf_key":         load_hf_key(),
        "img_model":      DEFAULT_IMG_MODEL,
        "project_ctx":    None,
        "agents":         {},
        "active_agent":   None,
        "_startup_enter": args.enter,
        "_startup_agent": args.agent,
    }
    if args.persona:
        p = PERSONAS.get(args.persona, args.persona)
        state["system_prompt"] = p; save_persona(p)

    if not state["api_key"] and not state["openrouter_key"] and not state["use_cli"]:
        k = setup_api_key(state)
        if k and (k.startswith("sk-or-") or k.startswith("sk-or-v1-")):
            state["openrouter_key"] = k
            state["use_openrouter"] = True
        else:
            state["api_key"] = k

    if args.read:
        console.print(get_banner_small(THEMES["default"])+"\n")
        cmd_read(state, args.read, [])
        return
    if args.prompt:
        console.print(get_banner_small(THEMES["default"])+"\n")
        ai_respond(state, args.prompt, [])
        return

    try:
        run_repl(state)
    except Exception as _e:
        _ename = type(_e).__name__
        if "NoConsoleScreenBufferError" in _ename or "NoConsoleScreenBuffer" in str(_e):
            sys.stderr.write(
                "AI Studio CLI requires an interactive Windows console.\n"
                "Run it from cmd.exe, PowerShell, or Windows Terminal.\n"
            )
            sys.exit(1)
        raise


# ═══════════════════════════════════════════════════════════
# AGENT SYSTEM + PROJECT SCANNER
# ═══════════════════════════════════════════════════════════

def scan_project(path):
    root  = Path(path).resolve()
    if not root.exists():
        return {"error": f"Not found: {path}"}
    files       = {}
    tree_lines  = []
    total_chars = 0
    stats       = {"total_files":0,"total_lines":0,"total_size":0,"by_ext":{}}

    def walk(cur, prefix="", depth=0):
        nonlocal total_chars
        if depth > 7: return
        try:
            items = sorted(cur.iterdir(), key=lambda x:(x.is_file(), x.name.lower()))
        except PermissionError:
            return
        for i, item in enumerate(items):
            last = i == len(items)-1
            conn = "└── " if last else "├── "
            ext2 = "    " if last else "│   "
            if item.is_dir():
                if item.name in SKIP_DIRS: continue
                tree_lines.append(f"{prefix}{conn}📁 {item.name}/")
                walk(item, prefix+ext2, depth+1)
            else:
                ext = item.suffix.lower()
                sz  = item.stat().st_size
                stats["total_files"] += 1
                stats["total_size"]  += sz
                stats["by_ext"][ext]  = stats["by_ext"].get(ext,0)+1
                sl = f"{sz}B" if sz<1024 else f"{sz//1024}KB"
                tree_lines.append(f"{prefix}{conn}📄 {item.name} ({sl})")
                if ext in CODE_EXTS and sz < 500000 and total_chars < MAX_TOTAL_CHARS:
                    try:
                        content = item.read_text(encoding="utf-8", errors="replace")
                        lns     = len(content.splitlines())
                        stats["total_lines"] += lns
                        rel = str(item.relative_to(root))
                        if len(content) > MAX_FILE_CHARS:
                            content = content[:MAX_FILE_CHARS] + f"\n...[{lns} lines, truncated]"
                        files[rel] = {"content":content,"lines":lns,"ext":ext,"size":sz}
                        total_chars += len(content)
                    except Exception:
                        pass

    walk(root)

    all_names   = " ".join(files.keys())
    all_content = " ".join(v.get("content","")[:500] for v in files.values())
    checks      = [
        ("package.json" in all_names, "Node.js"),
        ("requirements.txt" in all_names or "pyproject.toml" in all_names, "Python"),
        (any(".ts" in f for f in files), "TypeScript"),
        (any(".tsx" in f or ".jsx" in f for f in files), "React"),
        (any(".vue" in f for f in files), "Vue.js"),
        ("next.config" in all_names, "Next.js"),
        ("vite.config" in all_names, "Vite"),
        ("tailwind" in all_content.lower(), "Tailwind CSS"),
        ("prisma" in all_content.lower(), "Prisma"),
        ("supabase" in all_content.lower(), "Supabase"),
        ("express" in all_content.lower(), "Express"),
        ("fastapi" in all_content.lower(), "FastAPI"),
        ("django" in all_content.lower(), "Django"),
        ("docker" in all_names.lower(), "Docker"),
        ("openai" in all_content.lower(), "OpenAI"),
    ]
    stack   = [name for cond, name in checks if cond]
    prios   = ["main.py","app.py","index.py","server.py","index.js","main.js",
               "app.js","index.ts","index.html","App.tsx","App.jsx"]
    entries = [p for p in prios if any(f.endswith(p) or f==p for f in files)]

    return {
        "root":         str(root),
        "tree":         "\n".join(tree_lines),
        "files":        files,
        "stats":        stats,
        "tech_stack":   stack,
        "entry_points": entries[:5],
        "total_chars":  total_chars,
    }


def format_project_context(ctx, max_files=15):
    if "error" in ctx:
        return f"Error: {ctx['error']}"
    parts = [f"PROJECT ROOT: {ctx['root']}"]
    if ctx.get("tech_stack"):
        parts.append("TECH STACK: " + ", ".join(ctx["tech_stack"]))
    s  = ctx["stats"]
    sz = f"{s['total_size']//1024}KB" if s["total_size"]<1048576 else f"{s['total_size']//1048576}MB"
    parts.append(f"STATS: {s['total_files']} files · {s['total_lines']:,} lines · {sz}")
    if ctx.get("entry_points"):
        parts.append("ENTRY POINTS: " + ", ".join(ctx["entry_points"]))
    tree_preview = "\n".join(ctx["tree"].split("\n")[:50])
    parts.append(f"DIRECTORY TREE:\n{tree_preview}")
    for fname, info in sorted(ctx["files"].items(), key=lambda x: -x[1]["size"])[:max_files]:
        parts.append(f"\nFILE: {fname} ({info['lines']} lines)\n\n{info['content']}")
    return "\n".join(parts)


def pick_best_agent(task):
    task_lower = task.lower()
    scores     = {aid: sum(1 for kw in info["specialties"] if kw in task_lower)
                  for aid, info in AGENT_ROSTER.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "lucifer"


def auto_assign_agents(task):
    task_lower = task.lower()
    assigned   = [aid for aid, info in AGENT_ROSTER.items()
                  if any(kw in task_lower for kw in info["specialties"])]
    return (assigned or ["lucifer"])[:3]


BLACKBOARD      = {} # Shared memory for Agent Mesh

def call_ollama(model, history, prompt, system_prompt=None, stream=False):
    """Local Ollama provider — supports non-streaming and live NDJSON streaming."""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    for m in history:
        messages.append({"role": m["role"], "content": m["text"]})
    messages.append({"role": "user", "content": prompt})

    payload = json.dumps({"model": model, "messages": messages, "stream": stream}).encode()
    req = request.Request(
        OLLAMA_BASE, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    if stream:
        def _ollama_stream():
            try:
                with request.urlopen(req, timeout=300) as resp:
                    for raw in resp:
                        line = raw.decode("utf-8", errors="replace").strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except Exception:
                            continue
                        content = (obj.get("message") or {}).get("content") or ""
                        if content:
                            yield content, None, None
                        if obj.get("done"):
                            break
                yield None, None, None
            except Exception as exc:
                yield None, str(exc), None
        return _ollama_stream()

    # Non-streaming
    try:
        with request.urlopen(req, timeout=120) as resp:
            res = json.loads(resp.read().decode())
        return res["message"]["content"], None
    except Exception as exc:
        return None, str(exc)

class Agent:
    def __init__(self, agent_id, state, project_ctx=None, blackboard=None):
        self.id   = agent_id
        info      = AGENT_ROSTER.get(agent_id, {})
        self.name = info.get("name", agent_id.title())
        self.emoji= info.get("emoji", "🤖")
        self.color= info.get("color", "bold cyan")
        self.role = info.get("role", "Agent")
        self.state= state.copy()
        self.blackboard = blackboard if blackboard is not None else BLACKBOARD
        self.state["system_prompt"] = info.get("persona", "You are a helpful AI agent.")
        if project_ctx and "error" not in project_ctx:
            self.state["system_prompt"] += (
                f"\n\nProject Context: {project_ctx.get('root','')}"
                f"\nShared Blackboard: {json.dumps(self.blackboard)}"
                f"\nYou can delegate tasks to other agents using [AGENT:id]task[/AGENT]. Available: {', '.join(AGENT_ROSTER.keys())}"
            )
        self.history     = []
        self.project_ctx = project_ctx

    def run(self, task, console_obj, ai_respond_fn):
        console_obj.print(f"\n[{self.color}]{self.emoji} {self.name}[/{self.color}] [dim]{self.role} — working...[/dim]")
        
        # Prepend project context for first message
        full_task = task
        if self.project_ctx and not self.history:
            ctx_str   = format_project_context(self.project_ctx, max_files=10)
            full_task = ctx_str + "\n\n---\n\nTask: " + task

        text, self.history = ai_respond_fn(self.state, full_task, self.history)
        if not text: return ""

        # AGENT MESH: Check for handoff tags
        mesh_p = re.compile(r"\[AGENT:(.+?)\](.*?)\[/AGENT\]", re.DOTALL)
        for m in mesh_p.finditer(text):
            target_id = m.group(1).strip().lower()
            sub_task  = m.group(2).strip()
            if target_id in AGENT_ROSTER and target_id != self.id:
                console_obj.print(f"  [dim]↳ Handoff to [bold]{target_id}[/bold]...[/dim]")
                sub_agent = Agent(target_id, self.state, self.project_ctx, self.blackboard)
                sub_res   = sub_agent.run(sub_task, console_obj, ai_respond_fn)
                # Feed the result back to the original agent history
                self.history.append({"role":"user", "text":f"Result from {target_id}: {sub_res}"})
                text, self.history = ai_respond_fn(self.state, "Continue based on the result above.", self.history)

        return text or ""


if __name__ == "__main__":
    main()
