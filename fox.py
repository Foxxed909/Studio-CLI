#!/usr/bin/env python3
"""
🦊 FOX CLI — Premium AI terminal for Studio Max users.
Version 1.0.0 · Requires Studio Max / Ultra / Enterprise / Team plan.
"""

# ── Imports ───────────────────────────────────────────────────────────────────
import json
import os
import re
import sys
import time
import subprocess
import threading
import csv
import io
from datetime import datetime
from pathlib import Path
from urllib import request as urllib_request
from urllib import error as urllib_error

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.syntax import Syntax
    from rich.columns import Columns
    from rich.markdown import Markdown
    from rich import box
except ImportError:
    print("FOX requires 'rich'. Install: pip install rich prompt_toolkit")
    sys.exit(1)

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.completion import WordCompleter, Completion
    from prompt_toolkit.styles import Style
    from prompt_toolkit.formatted_text import FormattedText, HTML
    from prompt_toolkit.filters import Condition
except ImportError:
    print("FOX requires 'prompt_toolkit'. Install: pip install rich prompt_toolkit")
    sys.exit(1)

# ── Version & constants ────────────────────────────────────────────────────────
VERSION          = "1.0.0"
OPENROUTER_BASE  = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
DEFAULT_FOX_MODEL = "google/gemini-2.5-flash"

# ── Config paths ──────────────────────────────────────────────────────────────
FOX_CONFIG_DIR   = Path.home() / ".fox"
FOX_HISTORY_FILE = FOX_CONFIG_DIR / "history"
FOX_THEME_FILE   = FOX_CONFIG_DIR / "theme"
FOX_SESSION_FILE = FOX_CONFIG_DIR / "session.json"
FOX_ONBOARD_FILE = FOX_CONFIG_DIR / "onboarded"
FOX_QUEUE_FILE   = FOX_CONFIG_DIR / "queue.json"
FOX_MEMORY_FILE  = FOX_CONFIG_DIR / "memory.json"

# Shared with StudioCLI — read only (never corrupt StudioCLI state)
PROFILES_DIR     = Path("profiles")

console = Console()

# ── Plans ─────────────────────────────────────────────────────────────────────
_FOX_ALLOWED = ("max", "ultra", "enterprise", "team", "dev")

PLANS = {
    "free":       {"name": "Free",       "color": "dim",          "badge": "○",  "tier": "v8+"},
    "starter":    {"name": "Starter",    "color": "green",        "badge": "◇",  "tier": "v8+"},
    "pro":        {"name": "Pro",        "color": "cyan",         "badge": "◆",  "tier": "v9"},
    "dev":        {"name": "Dev",        "color": "bold cyan",    "badge": "⬡",  "tier": "v9+"},
    "max":        {"name": "Max",        "color": "magenta",      "badge": "◈",  "tier": "v9+"},
    "ultra":      {"name": "Ultra",      "color": "bold yellow",  "badge": "★",  "tier": "v9 Beta"},
    "team":       {"name": "Team",       "color": "bold green",   "badge": "👥", "tier": "v9+"},
    "enterprise": {"name": "Enterprise", "color": "bold white",   "badge": "◉",  "tier": "∞"},
}

# ── Cost table ($/1k tokens: input, output) ───────────────────────────────────
COST_TABLE: dict[str, tuple[float, float]] = {
    "nvidia/nemotron-3-super-120b-a12b:free":        (0.0,       0.0),
    "openai/gpt-oss-120b:free":                      (0.0,       0.0),
    "meta-llama/llama-3.3-70b-instruct:free":        (0.0,       0.0),
    "meta-llama/llama-3.2-3b-instruct:free":         (0.0,       0.0),
    "google/gemma-3-27b-it:free":                    (0.0,       0.0),
    "qwen/qwen3-coder:free":                         (0.0,       0.0),
    "google/gemini-2.5-flash":                       (0.000075,  0.0003),
    "google/gemini-2.5-pro":                         (0.00125,   0.005),
    "openai/gpt-4o":                                 (0.0025,    0.010),
    "openai/gpt-4o-mini":                            (0.00015,   0.0006),
    "anthropic/claude-sonnet-4-5":                   (0.003,     0.015),
    "anthropic/claude-opus-4-5":                     (0.015,     0.075),
    "anthropic/claude-haiku-4-5":                    (0.0008,    0.004),
    "mistralai/mistral-large":                       (0.002,     0.006),
    "qwen/qwen-2.5-72b-instruct":                    (0.0004,    0.0004),
    "meta-llama/llama-3.1-405b-instruct":            (0.00027,   0.00027),
}
_DEFAULT_COST = (0.001, 0.001)

# ── Themes ────────────────────────────────────────────────────────────────────
THEMES: dict[str, dict] = {
    "fox": {
        "name":         "Fox",
        "banner_color": "bold yellow",
        "accent":       "bold yellow",
        "prompt_user":  "ansiyellow",
        "prompt_arrow": "ansiyellow",
        "border":       "yellow",
        "success":      "bright_yellow",
        "error":        "bold red",
        "warning":      "yellow",
        "dim":          "dim",
        "banner_sub":   "bold yellow",
        "icon":         "🦊",
        "prompt_name":  "fox",
        "cost_color":   "yellow",
    },
    "noir": {
        "name":         "Noir",
        "banner_color": "bold white",
        "accent":       "bold white",
        "prompt_user":  "ansiwhite",
        "prompt_arrow": "ansiwhite",
        "border":       "white",
        "success":      "bright_white",
        "error":        "bold red",
        "warning":      "bold yellow",
        "dim":          "dim",
        "banner_sub":   "white",
        "icon":         "◈",
        "prompt_name":  "fox",
        "cost_color":   "white",
    },
    "ember": {
        "name":         "Ember",
        "banner_color": "bold red",
        "accent":       "bold orange3",
        "prompt_user":  "ansired",
        "prompt_arrow": "ansibrightred",
        "border":       "orange3",
        "success":      "bright_yellow",
        "error":        "bold red",
        "warning":      "yellow",
        "dim":          "dim",
        "banner_sub":   "orange3",
        "icon":         "🔥",
        "prompt_name":  "fox",
        "cost_color":   "orange3",
    },
}

# ── Model aliases ─────────────────────────────────────────────────────────────
FOX_MODEL_ALIASES: dict[str, str] = {
    "fast":    "google/gemini-2.5-flash",
    "flash":   "google/gemini-2.5-flash",
    "smart":   "anthropic/claude-sonnet-4-5",
    "sonnet":  "anthropic/claude-sonnet-4-5",
    "pro":     "anthropic/claude-sonnet-4-5",
    "opus":    "anthropic/claude-opus-4-5",
    "haiku":   "anthropic/claude-haiku-4-5",
    "cheap":   "meta-llama/llama-3.3-70b-instruct:free",
    "free":    "meta-llama/llama-3.3-70b-instruct:free",
    "llama":   "meta-llama/llama-3.3-70b-instruct:free",
    "gemini":  "google/gemini-2.5-pro",
    "gpt4":    "openai/gpt-4o",
    "gpt":     "openai/gpt-4o",
    "mini":    "openai/gpt-4o-mini",
    "mistral": "mistralai/mistral-large",
    "qwen":    "qwen/qwen-2.5-72b-instruct",
}

FOX_MODELS_LIST = [
    {"id": "google/gemini-2.5-flash",                 "alias": "fast",    "badge": "⚡ FAST"},
    {"id": "meta-llama/llama-3.3-70b-instruct:free",  "alias": "free",    "badge": "○ FREE"},
    {"id": "openai/gpt-4o",                           "alias": "gpt4",    "badge": "◆ PRO"},
    {"id": "openai/gpt-4o-mini",                      "alias": "mini",    "badge": "◆ PRO"},
    {"id": "anthropic/claude-sonnet-4-5",             "alias": "smart",   "badge": "◆ PRO"},
    {"id": "anthropic/claude-opus-4-5",               "alias": "opus",    "badge": "★ MAX"},
    {"id": "anthropic/claude-haiku-4-5",              "alias": "haiku",   "badge": "⚡ FAST"},
    {"id": "google/gemini-2.5-pro",                   "alias": "gemini",  "badge": "◆ PRO"},
    {"id": "mistralai/mistral-large",                 "alias": "mistral", "badge": "◆ PRO"},
    {"id": "qwen/qwen-2.5-72b-instruct",              "alias": "qwen",    "badge": "◆ PRO"},
]

# ── Agent roster ──────────────────────────────────────────────────────────────
FOX_AGENTS: dict[str, dict] = {
    "default":    {
        "name": "Fox",
        "icon": "🦊",
        "desc": "Sharp, direct, cost-aware",
        "system": "You are FOX — a premium AI assistant inside FOX CLI. Direct, precise, cost-aware. Write complete production-quality code. Never pad responses. When asked for code, produce the full file. When asked to fix bugs, find all of them. Be efficient.",
    },
    "coder":      {
        "name": "Coder",
        "icon": "⌨",
        "desc": "Elite software engineer",
        "system": "You are an elite software engineer inside FOX CLI. Write clean, idiomatic, production-ready code. No explanations unless asked. No markdown fences around files — output raw code. Fix all linting issues. Add types everywhere.",
    },
    "debugger":   {
        "name": "Debugger",
        "icon": "🔬",
        "desc": "Root-cause analyst",
        "system": "You are a debugging specialist inside FOX CLI. When given code or an error, identify the root cause — not just the symptom. List every bug with: exact line number, root cause, fix with corrected code snippet. Use forensic precision.",
    },
    "architect":  {
        "name": "Architect",
        "icon": "🎯",
        "desc": "Systems design expert",
        "system": "You are a senior software architect inside FOX CLI. Think in systems, tradeoffs, and long-term maintainability. Give brutally honest architectural feedback. Call out bad patterns. Recommend proven solutions. Be concise.",
    },
    "reviewer":   {
        "name": "Reviewer",
        "icon": "🔍",
        "desc": "Code review specialist",
        "system": "You are a senior code reviewer inside FOX CLI. Review code for: correctness, security vulnerabilities, performance issues, readability, and test coverage. Be specific — cite line numbers. End every review with a VERDICT: SHIP IT / NEEDS WORK / CRITICAL.",
    },
    "writer":     {
        "name": "Writer",
        "icon": "📝",
        "desc": "Technical documentation",
        "system": "You are a technical writer inside FOX CLI. Produce clear, accurate, well-structured documentation. Use proper headings. Write docstrings in the style of the language. Generate README files, API docs, and inline comments with precision.",
    },
    "security":   {
        "name": "Security",
        "icon": "🔒",
        "desc": "Security & vulnerability analysis",
        "system": "You are a security engineer inside FOX CLI. Analyze code for security vulnerabilities: injection, XSS, auth bypass, insecure defaults, exposed secrets, OWASP Top 10. Cite CVEs where applicable. Provide specific fixes alongside every finding.",
    },
}

# ── Profile I/O (shared with StudioCLI) ──────────────────────────────────────
def load_profile(user_id: str = "default") -> dict | None:
    path = PROFILES_DIR / user_id / "profile.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None

def save_profile(profile: dict, user_id: str = "default") -> None:
    path = PROFILES_DIR / user_id / "profile.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, indent=2), encoding="utf-8")

def load_or_key(user_id: str = "default") -> str | None:
    k = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("STUDIO_OR_KEY")
    if k:
        return k
    path = PROFILES_DIR / user_id / "openrouter_key"
    if path.exists():
        raw = path.read_text().strip()
        try:
            return json.loads(raw).get("key") or raw
        except Exception:
            return raw if raw.startswith("sk-or-") else None
    return None

def save_or_key(key: str, user_id: str = "default") -> None:
    path = PROFILES_DIR / user_id / "openrouter_key"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key.strip())

def load_fox_session() -> dict:
    if FOX_SESSION_FILE.exists():
        try:
            return json.loads(FOX_SESSION_FILE.read_text())
        except Exception:
            pass
    return {}

def save_fox_session(data: dict) -> None:
    FOX_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    FOX_SESSION_FILE.write_text(json.dumps(data, indent=2))

def load_fox_memory() -> list:
    if FOX_MEMORY_FILE.exists():
        try:
            return json.loads(FOX_MEMORY_FILE.read_text())
        except Exception:
            pass
    return []

def save_fox_memory(mem: list) -> None:
    FOX_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    FOX_MEMORY_FILE.write_text(json.dumps(mem, indent=2))

# ── Plan gate ─────────────────────────────────────────────────────────────────
def get_profile_plan(user_id: str = "default") -> str:
    prof = load_profile(user_id)
    if prof:
        return prof.get("plan", "free")
    return "free"

def check_fox_access() -> tuple[bool, str]:
    plan = get_profile_plan()
    return plan in _FOX_ALLOWED, plan

# ── Auto-context detection ────────────────────────────────────────────────────
_CTX_MARKERS = (
    ".git", "package.json", "pyproject.toml", "Cargo.toml",
    "go.mod", "requirements.txt", "Pipfile", "pom.xml",
    "composer.json", "Makefile", "CMakeLists.txt", "deno.json",
)
_CODE_EXTS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs",
    ".java", ".c", ".cpp", ".h", ".cs", ".rb", ".php",
    ".toml", ".yaml", ".yml", ".json", ".sh", ".md",
}
_SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", "dist", "build",
    ".next", "venv", ".venv", "env", ".cache", "tmp", ".mypy_cache",
}
_MAX_CTX_CHARS = 10_000

def detect_project_context(path: Path) -> dict | None:
    if not any((path / m).exists() for m in _CTX_MARKERS):
        return None
    ctx: dict = {"root": str(path), "tech_stack": [], "files": {}, "total_chars": 0, "git_branch": None}
    stack_markers = [
        ("package.json", "Node.js"), ("pyproject.toml", "Python"), ("requirements.txt", "Python"),
        ("Cargo.toml", "Rust"), ("go.mod", "Go"), ("pom.xml", "Java"),
        ("composer.json", "PHP"), ("Makefile", "C/C++"),
    ]
    for marker, label in stack_markers:
        if (path / marker).exists() and label not in ctx["tech_stack"]:
            ctx["tech_stack"].append(label)
    for f in sorted(path.iterdir()):
        if ctx["total_chars"] >= _MAX_CTX_CHARS:
            break
        if f.is_file() and f.suffix in _CODE_EXTS and not f.name.startswith("."):
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
                if len(content) > 3000:
                    content = content[:3000] + "\n...[truncated]"
                ctx["files"][f.name] = content
                ctx["total_chars"] += len(content)
            except Exception:
                pass
    try:
        r = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, timeout=2, cwd=str(path)
        )
        if r.returncode == 0:
            ctx["git_branch"] = r.stdout.strip()
    except Exception:
        pass
    return ctx

def format_context_summary(ctx: dict) -> str:
    parts = [f"PROJECT ROOT: {ctx['root']}"]
    if ctx.get("tech_stack"):
        parts.append("STACK: " + ", ".join(ctx["tech_stack"]))
    if ctx.get("git_branch"):
        parts.append(f"GIT BRANCH: {ctx['git_branch']}")
    if ctx.get("files"):
        parts.append(f"FILES LOADED: {len(ctx['files'])}")
        for name, content in list(ctx["files"].items())[:8]:
            parts.append(f"\n--- {name} ---\n{content[:600]}")
    return "\n".join(parts)

# ── Streaming + API ───────────────────────────────────────────────────────────
def call_openrouter_stream(api_key: str, model: str, messages: list):
    """Yield (chunk, error, reasoning) tuples via SSE streaming."""
    payload = json.dumps({
        "model":    model,
        "messages": messages,
        "stream":   True,
        "max_tokens": 4096,
    }).encode()
    req = urllib_request.Request(
        OPENROUTER_BASE,
        data=payload,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer":  "https://github.com/foxxed909/studio-cli",
            "X-Title":       "FOX CLI",
        },
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=300) as resp:
            buf = ""
            for raw in resp:
                buf += raw.decode("utf-8", errors="replace")
                lines = buf.split("\n")
                buf = lines.pop()
                for line in lines:
                    trimmed = line.strip()
                    if not trimmed or not trimmed.startswith("data:"):
                        continue
                    data = trimmed[5:].strip()
                    if data == "[DONE]":
                        return
                    try:
                        obj = json.loads(data)
                    except Exception:
                        continue
                    choice    = (obj.get("choices") or [{}])[0]
                    delta     = choice.get("delta") or {}
                    content   = delta.get("content")
                    reasoning = delta.get("reasoning") or delta.get("reasoning_content")
                    if reasoning:
                        yield None, None, reasoning
                    if content:
                        yield content, None, None
    except urllib_error.HTTPError as exc:
        try:
            body = exc.read().decode()
            msg  = json.loads(body).get("error", {}).get("message") or body
        except Exception:
            msg = str(exc)
        yield None, msg, None
    except Exception as exc:
        yield None, str(exc), None

def call_openrouter_blocking(api_key: str, model: str, messages: list) -> str | None:
    """Non-streaming call — returns full response text (used by /arena)."""
    payload = json.dumps({
        "model":    model,
        "messages": messages,
        "stream":   False,
        "max_tokens": 4096,
    }).encode()
    req = urllib_request.Request(
        OPENROUTER_BASE,
        data=payload,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer":  "https://github.com/foxxed909/studio-cli",
            "X-Title":       "FOX CLI",
        },
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode())
            return body.get("choices", [{}])[0].get("message", {}).get("content")
    except Exception:
        return None

# ── Cost engine ───────────────────────────────────────────────────────────────
def estimate_cost(model_id: str, tokens_in: int, tokens_out: int) -> float:
    if model_id.endswith(":free"):
        return 0.0
    rates = COST_TABLE.get(model_id, _DEFAULT_COST)
    return (tokens_in * rates[0] + tokens_out * rates[1]) / 1000

def approx_tokens(text: str) -> int:
    return max(1, len(text) // 4) if text else 0

def print_cost_footer(state: dict, tokens_in: int, tokens_out: int, elapsed: float) -> None:
    model    = state.get("model", "")
    cost     = estimate_cost(model, tokens_in, tokens_out)
    theme    = state.get("theme", THEMES["fox"])
    cc       = theme.get("cost_color", "yellow")
    free_tag = " [dim](free)[/dim]" if cost == 0.0 else ""
    cost_str = "free" if cost == 0.0 else f"${cost:.6f}"
    console.print(
        f"[dim]  ·  {tokens_in:,} in  {tokens_out:,} out  "
        f"[{cc}]{cost_str}[/{cc}]{free_tag}  {elapsed:.1f}s[/dim]"
    )
    state["_session_cost"]      = state.get("_session_cost", 0.0) + cost
    state["_session_tokens_in"]  = state.get("_session_tokens_in", 0)  + tokens_in
    state["_session_tokens_out"] = state.get("_session_tokens_out", 0) + tokens_out
    state["_session_msgs"]       = state.get("_session_msgs", 0) + 1
    state["_last_tokens"] = {"in": tokens_in, "out": tokens_out, "sec": elapsed, "cost": cost, "model": model}

# ── System prompt builder ─────────────────────────────────────────────────────
FOX_DEFAULT_SYSTEM = (
    "You are FOX — a premium AI assistant inside FOX CLI, a high-performance terminal tool "
    "for professional developers. You are direct, precise, and cost-aware. "
    "Write complete, production-quality code. Never pad responses with unnecessary preamble. "
    "When asked for code, produce the full file. When asked to fix bugs, find all of them. "
    "The user sees token costs in real-time — be efficient, not verbose."
)

def build_system_prompt(state: dict) -> str:
    base = state.get("system_prompt") or FOX_DEFAULT_SYSTEM
    parts = [base]
    if state.get("auto_ctx"):
        summary = format_context_summary(state["auto_ctx"])
        parts.append(f"\nPROJECT CONTEXT:\n{summary}")
    mem = load_fox_memory()
    if mem:
        mem_lines = "\n".join(f"- {m['text']}" for m in mem[-10:])
        parts.append(f"\nUSER MEMORY:\n{mem_lines}")
    return "\n\n".join(parts)

# ── AI core ───────────────────────────────────────────────────────────────────
def fox_respond(
    state: dict,
    prompt: str,
    history: list,
    silent: bool = False,
    system_override: str | None = None,
) -> tuple[str | None, list]:
    """Main AI call. Always streams. Always shows cost footer. Returns (text, history)."""
    or_key = state.get("openrouter_key") or load_or_key()
    if not or_key:
        console.print(Panel(
            "  No OpenRouter key configured.\n\n"
            "  [dim]Set via environment:[/dim]  [yellow]export OPENROUTER_API_KEY=sk-or-...[/yellow]\n"
            "  [dim]Or re-run onboarding:[/dim]  [yellow]fox --setup[/yellow]",
            title="[bold red]No API Key[/bold red]", border_style="red", padding=(0, 2)
        ))
        return None, history

    model   = state.get("model", DEFAULT_FOX_MODEL)
    system  = system_override or build_system_prompt(state)
    theme   = state.get("theme", THEMES["fox"])
    acc     = theme["accent"]
    icon    = theme["icon"]

    messages: list[dict] = [{"role": "system", "content": system}]
    for m in history:
        messages.append({
            "role":    "assistant" if m["role"] == "model" else m["role"],
            "content": m["text"],
        })
    messages.append({"role": "user", "content": prompt})

    t0           = time.time()
    full_text:   list[str] = []
    reasoning_buf: list[str] = []
    think_open   = False
    first_chunk  = True
    err: str | None = None
    is_think_mode = state.get("_think_mode", False)

    for chunk, chunk_err, reasoning in call_openrouter_stream(or_key, model, messages):
        if chunk_err:
            err = chunk_err
            break
        if reasoning and is_think_mode:
            if not think_open:
                console.print("\n[dim yellow]◈ Reasoning…[/dim yellow]")
                think_open = True
            sys.stdout.write(f"\x1b[2;3m{reasoning}\x1b[0m")
            sys.stdout.flush()
            reasoning_buf.append(reasoning)
        if chunk:
            if first_chunk:
                if think_open:
                    console.print("\n[dim]◇ Done thinking.[/dim]")
                    think_open = False
                if not silent:
                    short_model = model.split("/")[-1].split(":")[0]
                    console.print(f"\n[{acc}]{icon}[/{acc}] [bold]FOX[/bold]  [dim]{short_model}[/dim]\n")
                first_chunk = False
            if not silent:
                console.print(chunk, end="")
            full_text.append(chunk)

    elapsed = round(time.time() - t0, 2)
    text    = "".join(full_text) if full_text else None

    if not silent:
        console.print()
        if err:
            console.print(f"\n[red]Error: {err}[/red]")
        elif text:
            ctx_tokens = sum(approx_tokens(m.get("content", "")) for m in messages[:-1])
            tokens_in  = approx_tokens(prompt) + ctx_tokens
            tokens_out = approx_tokens(text)
            print_cost_footer(state, tokens_in, tokens_out, elapsed)

    if text:
        history.append({"role": "user",  "text": prompt})
        history.append({"role": "model", "text": text})
        state["_last_response"] = text

    return text, history

# ── Onboarding ────────────────────────────────────────────────────────────────
def ping_openrouter_key(key: str) -> bool:
    req = urllib_request.Request(
        OPENROUTER_MODELS_URL,
        headers={"Authorization": f"Bearer {key}"},
        method="GET",
    )
    try:
        with urllib_request.urlopen(req, timeout=8) as resp:
            return resp.status == 200
    except Exception:
        return False

def run_onboarding() -> bool:
    """Run first-time setup. Returns True if completed successfully."""
    console.print(Panel(
        f"\n  [bold yellow]🦊 FOX CLI[/bold yellow]  [dim]v{VERSION}[/dim]\n\n"
        "  [bold]Premium AI terminal for serious builders.[/bold]\n\n"
        "  [dim]Requires Studio Max, Ultra, Enterprise, or Team plan.[/dim]",
        border_style="yellow",
        padding=(0, 2),
    ))

    existing = load_profile()
    if existing:
        plan = existing.get("plan", "free")
        if plan in _FOX_ALLOWED:
            existing["fox_user"] = True
            save_profile(existing)
            FOX_ONBOARD_FILE.parent.mkdir(parents=True, exist_ok=True)
            FOX_ONBOARD_FILE.write_text(datetime.now().isoformat())
            console.print(f"  [dim green]✓ Studio profile detected — [{PLANS[plan]['color']}]{PLANS[plan]['name']}[/{PLANS[plan]['color']}] plan. FOX enabled.[/dim green]\n")
            return True
        else:
            console.print(Panel(
                f"  Your Studio plan is [bold]{existing.get('plan', 'free').title()}[/bold].\n\n"
                "  FOX CLI requires [bold magenta]Max[/bold magenta], [bold yellow]Ultra[/bold yellow], "
                "[bold green]Team[/bold green], or [bold white]Enterprise[/bold white].\n\n"
                "  [dim]Upgrade in Studio CLI:[/dim]  [yellow]python aistudio.py → /upgrade max[/yellow]",
                title="[bold red]FOX — Upgrade Required[/bold red]",
                border_style="red", padding=(0, 2),
            ))
            return False

    # Full first-run onboarding
    console.print("\n  [dim]No Studio profile found. Let's set up FOX.[/dim]\n")
    try:
        user = console.input("  [bold yellow]Your name:[/bold yellow] ").strip() or "Dev"
        console.print(
            "\n  [dim]Get a free OpenRouter key at:[/dim] [cyan underline]https://openrouter.ai/keys[/cyan underline]"
        )
        or_key = console.input("  [bold yellow]OpenRouter API key (sk-or-...):[/bold yellow] ").strip()
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Setup cancelled.[/dim]")
        return False

    if or_key:
        console.print("  [dim]Validating key…[/dim]", end="")
        valid = ping_openrouter_key(or_key)
        if valid:
            console.print(" [green]✓ Valid[/green]")
            save_or_key(or_key)
        else:
            console.print(" [yellow]⚠ Could not validate (key saved anyway — check later)[/yellow]")
            save_or_key(or_key)

    profile = {
        "user":          user,
        "plan":          "max",
        "fox_user":      True,
        "onboarded_at":  datetime.now().isoformat(),
        "first_seen":    datetime.now().isoformat(),
        "last_seen":     datetime.now().isoformat(),
        "session_msgs":  0,
        "total_msgs":    0,
        "session_count": 1,
        "login_history": [datetime.now().isoformat()],
    }
    save_profile(profile)
    FOX_ONBOARD_FILE.parent.mkdir(parents=True, exist_ok=True)
    FOX_ONBOARD_FILE.write_text(datetime.now().isoformat())
    console.print(f"\n  [bold yellow]🦊 FOX ready, {user}.[/bold yellow]  [dim]/help to explore[/dim]\n")
    return True

# ── Banner & welcome ──────────────────────────────────────────────────────────
_FOX_ASCII = r"""
 ███████╗ ██████╗ ██╗  ██╗
 ██╔════╝██╔═══██╗╚██╗██╔╝
 █████╗  ██║   ██║ ╚███╔╝
 ██╔══╝  ██║   ██║ ██╔██╗
 ██║     ╚██████╔╝██╔╝ ██╗
 ╚═╝      ╚═════╝ ╚═╝  ╚═╝"""

def clear_terminal():
    os.system("cls" if sys.platform == "win32" else "clear")

def render_welcome(state: dict) -> None:
    theme   = state.get("theme", THEMES["fox"])
    bc      = theme["banner_color"]
    acc     = theme["accent"]
    icon    = theme["icon"]
    plan_id = get_profile_plan()
    plan    = PLANS.get(plan_id, PLANS["free"])
    model   = state.get("model", DEFAULT_FOX_MODEL)
    short_m = model.split("/")[-1].split(":")[0]

    # Cost per 1k for current model
    rates = COST_TABLE.get(model, _DEFAULT_COST)
    if model.endswith(":free"):
        cost_str = "free"
    else:
        cost_str = f"${(rates[0]+rates[1])/2*1000:.4f}/1k"

    # Git branch
    branch = ""
    try:
        r = subprocess.run(["git","branch","--show-current"], capture_output=True, text=True, timeout=1)
        if r.returncode == 0 and r.stdout.strip():
            branch = f"  ·  ⎇ [dim]{r.stdout.strip()}[/dim]"
    except Exception:
        pass

    agent_id = state.get("active_agent") or "default"
    agent    = FOX_AGENTS.get(agent_id, FOX_AGENTS["default"])

    body = (
        f"[{bc}]{_FOX_ASCII}[/{bc}]\n\n"
        f"  [bold]v{VERSION}[/bold]  ·  "
        f"[{plan['color']}]{plan['badge']} {plan['name']}[/{plan['color']}]  ·  "
        f"[{acc}]{icon} {agent['name']}[/{acc}]  ·  "
        f"[dim]{short_m}  {cost_str}[/dim]{branch}\n\n"
        f"  [dim]/think  /code  /fix  /commit  /cost  /help[/dim]"
    )
    console.print(Panel(body, border_style=theme["border"], padding=(0, 2)))

# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_think(state: dict, args: str, history: list) -> list:
    """/think <prompt> — AI with visible reasoning + cost footer."""
    if not args:
        console.print("[yellow]Usage: /think <your question>[/yellow]")
        return history
    state["_think_mode"] = True
    _, history = fox_respond(state, args, history)
    state["_think_mode"] = False
    return history


def _strip_fences(text: str) -> str:
    lines = text.strip().split("\n")
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)


def cmd_code(state: dict, args: str, history: list) -> list:
    """/code <instruction> — AI writes code; optionally saves to file."""
    if not args:
        console.print("[yellow]Usage: /code <instruction>[/yellow]")
        return history
    override = (
        "You are an elite coder. Write complete, production-ready code only. "
        "No explanations. No markdown fences. Output the full file contents directly. "
        "If the task is small, still output the complete file."
    )
    text, history = fox_respond(state, args, history, system_override=override)
    if not text:
        return history
    theme = state.get("theme", THEMES["fox"])
    acc   = theme["accent"]
    try:
        save_path = console.input(f"\n  [{acc}]Save to file?[/{acc}] [dim](filename or Enter to skip):[/dim] ").strip()
        if save_path:
            Path(save_path).write_text(_strip_fences(text), encoding="utf-8")
            console.print(f"  [green]✓ Saved to {save_path}[/green]")
    except (KeyboardInterrupt, EOFError):
        pass
    return history


def cmd_fix(state: dict, args: str, history: list) -> list:
    """/fix <file> — find-identify-fix deep bug hunt on a file."""
    if not args:
        console.print("[yellow]Usage: /fix <file>[/yellow]")
        return history
    path = Path(args.strip())
    if not path.exists():
        console.print(f"[red]File not found: {path}[/red]")
        return history
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        console.print(f"[red]Cannot read {path}: {exc}[/red]")
        return history
    theme = state.get("theme", THEMES["fox"])
    ext   = path.suffix.lstrip(".")
    console.print(Panel(
        Syntax(content[:3000], ext or "text", theme="monokai", line_numbers=True),
        title=f"[dim]{path}[/dim]", border_style=theme["border"], padding=(0, 1)
    ))
    prompt = (
        f"File: {path}\n\n```{ext}\n{content}\n```\n\n"
        "Task: Find · Identify · Fix — scan this file completely.\n"
        "For each issue: state the exact line number, root cause, severity (LOW/MEDIUM/HIGH/CRITICAL), "
        "and provide corrected code. Use headers: ## BUGS, ## SECURITY, ## PERFORMANCE, ## FIXED CODE."
    )
    _, history = fox_respond(state, prompt, history)
    return history


def cmd_commit(state: dict, history: list) -> list:
    """/commit — AI writes a commit message and runs git commit."""
    diff = ""
    try:
        r = subprocess.run("git diff --cached", shell=True, capture_output=True, text=True, timeout=10)
        diff = r.stdout.strip()
        if not diff:
            r = subprocess.run("git diff", shell=True, capture_output=True, text=True, timeout=10)
            diff = r.stdout.strip()
    except Exception as exc:
        console.print(f"[red]git error: {exc}[/red]")
        return history
    if not diff:
        console.print("[yellow]No staged or unstaged changes found.[/yellow]")
        return history
    prompt = (
        f"Git diff:\n```diff\n{diff[:4000]}\n```\n\n"
        "Write a conventional commit message. Format: type(scope): description\n"
        "Types: feat, fix, refactor, docs, style, test, chore\n"
        "Return ONLY the commit message — one line, no explanation."
    )
    override = "You write concise, precise git commit messages. Return ONLY the message, nothing else."
    text, history = fox_respond(state, prompt, history, system_override=override)
    if not text:
        return history
    msg = text.strip().split("\n")[0].strip("`").strip()
    theme = state.get("theme", THEMES["fox"])
    acc   = theme["accent"]
    console.print(Panel(
        f"  [bold]Commit message:[/bold]\n\n  [{acc}]{msg}[/{acc}]",
        border_style=theme["border"], padding=(0, 2)
    ))
    try:
        confirm = console.input(f"\n  [{acc}]Commit? (y/n):[/{acc}] ").strip().lower()
        if confirm == "y":
            r = subprocess.run(["git", "commit", "-am", msg], capture_output=True, text=True)
            if r.returncode == 0:
                console.print("[green]✓ Committed.[/green]")
            else:
                console.print(f"[red]Commit failed: {r.stderr.strip()}[/red]")
    except (KeyboardInterrupt, EOFError):
        pass
    return history


def cmd_cost(state: dict) -> None:
    """/cost — show session spend summary."""
    theme = state.get("theme", THEMES["fox"])
    acc   = theme["accent"]
    cc    = theme["cost_color"]
    total_cost = state.get("_session_cost", 0.0)
    tok_in     = state.get("_session_tokens_in", 0)
    tok_out    = state.get("_session_tokens_out", 0)
    msgs       = state.get("_session_msgs", 0)
    last       = state.get("_last_tokens") or {}

    t = Table(box=box.SIMPLE_HEAVY, border_style="dim", pad_edge=False)
    t.add_column("Metric",  style="dim", no_wrap=True)
    t.add_column("Value",   style=acc)

    if last:
        t.add_row("Last response — model",  last.get("model","—").split("/")[-1].split(":")[0])
        t.add_row("Last response — tokens", f"{last.get('in',0):,} in  {last.get('out',0):,} out")
        t.add_row("Last response — cost",   f"[{cc}]${last.get('cost',0):.6f}[/{cc}]")
        t.add_row("Last response — time",   f"{last.get('sec',0):.1f}s")
        t.add_row("", "")

    t.add_row("Session messages",    str(msgs))
    t.add_row("Session tokens in",   f"{tok_in:,}")
    t.add_row("Session tokens out",  f"{tok_out:,}")
    t.add_row("Session total cost",  f"[bold {cc}]${total_cost:.6f}[/bold {cc}]")
    if msgs > 0:
        t.add_row("Avg cost / message", f"${total_cost/msgs:.6f}")

    console.print(Panel(t, title="[bold]💰 Cost Dashboard[/bold]", border_style=theme["border"], padding=(0, 2)))


def cmd_model(state: dict, args: str) -> None:
    """/model [alias|id|fast|smart|cheap] — switch AI model."""
    theme = state.get("theme", THEMES["fox"])
    acc   = theme["accent"]
    if not args:
        t = Table(box=box.SIMPLE_HEAVY, border_style="dim", pad_edge=False)
        t.add_column("Alias",   style=acc, no_wrap=True)
        t.add_column("Model",   style="dim")
        t.add_column("Input",   style="dim", justify="right")
        t.add_column("Output",  style="dim", justify="right")
        t.add_column("Badge",   style="bold")
        for m in FOX_MODELS_LIST:
            rates = COST_TABLE.get(m["id"], _DEFAULT_COST)
            if m["id"].endswith(":free"):
                inp_str = "free"
                out_str = "free"
            else:
                inp_str = f"${rates[0]*1000:.4f}/1k"
                out_str = f"${rates[1]*1000:.4f}/1k"
            current = " ◄" if m["id"] == state.get("model") else ""
            t.add_row(m["alias"], m["id"].split("/")[-1].split(":")[0]+current, inp_str, out_str, m["badge"])
        console.print(Panel(t, title="[bold]Available Models[/bold]", border_style=theme["border"], padding=(0, 2)))
        return

    resolved = FOX_MODEL_ALIASES.get(args.lower(), args)
    state["model"] = resolved
    short = resolved.split("/")[-1].split(":")[0]
    rates = COST_TABLE.get(resolved, _DEFAULT_COST)
    cost_str = "free" if resolved.endswith(":free") else f"${rates[0]*1000:.4f}/${rates[1]*1000:.4f} per 1k"
    console.print(f"  [{acc}]✓ Model → {short}[/{acc}]  [dim]{cost_str}[/dim]")
    sess = load_fox_session()
    sess["model"] = resolved
    save_fox_session(sess)


def cmd_agent(state: dict, args: str) -> None:
    """/agent [name] — switch active persona."""
    theme = state.get("theme", THEMES["fox"])
    acc   = theme["accent"]
    if not args:
        current = state.get("active_agent") or "default"
        t = Table(box=box.SIMPLE_HEAVY, border_style="dim", pad_edge=False)
        t.add_column("Name",  style=acc, no_wrap=True)
        t.add_column("Icon",  justify="center")
        t.add_column("Description", style="dim")
        for name, info in FOX_AGENTS.items():
            mark = " ◄" if name == current else ""
            t.add_row(name+mark, info["icon"], info["desc"])
        console.print(Panel(t, title="[bold]FOX Agents[/bold]", border_style=theme["border"], padding=(0, 2)))
        return
    name = args.strip().lower()
    if name not in FOX_AGENTS:
        console.print(f"[yellow]Unknown agent '{name}'. Use /agent to list.[/yellow]")
        return
    state["active_agent"] = name
    state["system_prompt"] = FOX_AGENTS[name]["system"]
    info = FOX_AGENTS[name]
    console.print(f"  [{acc}]✓ Agent → {info['icon']} {info['name']}[/{acc}]  [dim]{info['desc']}[/dim]")


def cmd_context(state: dict, args: str, history: list) -> list:
    """/context [refresh|off] — show or manage project context."""
    theme = state.get("theme", THEMES["fox"])
    acc   = theme["accent"]
    sub   = args.strip().lower()
    if sub == "off":
        state.pop("auto_ctx", None)
        console.print(f"  [{acc}]✓ Context cleared.[/{acc}]")
        return history
    if sub == "refresh":
        ctx = detect_project_context(Path.cwd())
        if ctx:
            state["auto_ctx"] = ctx
            console.print(f"  [{acc}]✓ Context refreshed — {len(ctx['files'])} files loaded.[/{acc}]")
        else:
            console.print("  [dim]No project markers found in current directory.[/dim]")
        return history
    ctx = state.get("auto_ctx")
    if not ctx:
        console.print(Panel(
            "  No project context loaded.\n\n"
            "  [dim]/context refresh  →  detect project in cwd\n"
            "  /context off        →  clear context[/dim]",
            title="[bold]Project Context[/bold]", border_style=theme["border"], padding=(0, 2)
        ))
        return history
    ctx_tokens = approx_tokens(format_context_summary(ctx))
    rates = COST_TABLE.get(state.get("model",""), _DEFAULT_COST)
    cost_per_msg = (ctx_tokens * rates[0]) / 1000
    console.print(Panel(
        f"  [bold]Root:[/bold]  {ctx['root']}\n"
        f"  [bold]Stack:[/bold] {', '.join(ctx['tech_stack']) or 'unknown'}\n"
        f"  [bold]Branch:[/bold] {ctx.get('git_branch') or '—'}\n"
        f"  [bold]Files:[/bold] {len(ctx['files'])} loaded  ({ctx['total_chars']:,} chars)\n\n"
        f"  [dim]~{ctx_tokens:,} tokens injected per message  ·  ${cost_per_msg:.6f} extra/msg[/dim]\n\n"
        f"  [dim]/context refresh  →  reload  ·  /context off  →  clear[/dim]",
        title="[bold]Project Context[/bold]", border_style=theme["border"], padding=(0, 2)
    ))
    return history


def cmd_memory(state: dict, args: str) -> None:
    """/memory [add <fact>|clear|list] — manage persistent memory."""
    theme = state.get("theme", THEMES["fox"])
    acc   = theme["accent"]
    mem   = load_fox_memory()
    sub   = args.strip() if args else ""
    if sub.startswith("add "):
        fact = sub[4:].strip()
        if fact:
            mem.append({"text": fact, "ts": datetime.now().isoformat()})
            save_fox_memory(mem)
            console.print(f"  [{acc}]✓ Remembered: {fact}[/{acc}]")
        return
    if sub == "clear":
        save_fox_memory([])
        console.print(f"  [{acc}]✓ Memory cleared.[/{acc}]")
        return
    if not mem:
        console.print("[dim]No memories stored. Use /memory add <fact>[/dim]")
        return
    rows = "\n".join(f"  [dim]·[/dim] {m['text']}" for m in mem[-20:])
    console.print(Panel(rows, title=f"[bold]Memory ({len(mem)} entries)[/bold]",
                        border_style=theme["border"], padding=(0, 2)))


def cmd_clear(state: dict) -> list:
    """/clear — clear conversation and reset session cost."""
    state["_session_cost"]      = 0.0
    state["_session_tokens_in"]  = 0
    state["_session_tokens_out"] = 0
    state["_session_msgs"]       = 0
    state["_last_tokens"]        = None
    clear_terminal()
    render_welcome(state)
    return []


_HELP_CORE = """\
  [bold yellow]/think[/bold yellow]  [dim]<prompt>[/dim]       AI with reasoning + cost footer
  [bold yellow]/code[/bold yellow]   [dim]<instruction>[/dim]  Write code → save to file
  [bold yellow]/fix[/bold yellow]    [dim]<file>[/dim]          Find · Identify · Fix bugs in file
  [bold yellow]/commit[/bold yellow]                  AI commit message → git commit
  [bold yellow]/cost[/bold yellow]                    Session spend dashboard
  [bold yellow]/model[/bold yellow]  [dim][alias][/dim]        Switch model (fast/smart/cheap/opus…)
  [bold yellow]/agent[/bold yellow]  [dim][name][/dim]         Switch persona (coder/debugger/architect…)
  [bold yellow]/context[/bold yellow] [dim][refresh|off][/dim] Project context management
  [bold yellow]/clear[/bold yellow]                   Clear history + reset cost
  [bold yellow]/help[/bold yellow]   [dim][--all][/dim]        This help · --all for all commands"""

_HELP_ADVANCED = """\
  [bold yellow]/arena[/bold yellow]   [dim]<prompt>[/dim]    Compare 2 models side-by-side
  [bold yellow]/export[/bold yellow]  [dim][md|json|csv][/dim]  Export conversation
  [bold yellow]/queue[/bold yellow]   [dim]<task>[/dim]      Queue a background task
  [bold yellow]/share[/bold yellow]               Copy conversation to clipboard
  [bold yellow]/memory[/bold yellow]  [dim][add|list|clear][/dim] Persistent memory
  [bold yellow]/theme[/bold yellow]   [dim][fox|noir|ember][/dim] Switch theme
  [bold yellow]/voice[/bold yellow]               Voice input (coming v1.2)
  [bold yellow]/status[/bold yellow]              Show session info
  [bold yellow]/exit[/bold yellow]                Exit FOX"""


def cmd_help(state: dict, args: str) -> None:
    """/help [--all] — show commands."""
    theme = state.get("theme", THEMES["fox"])
    show_all = "--all" in args
    if show_all:
        body = _HELP_CORE + "\n\n  [dim]── Advanced ──────────────────────────────────────────────────────[/dim]\n\n" + _HELP_ADVANCED
    else:
        body = _HELP_CORE + "\n\n  [dim]/help --all  →  show advanced commands[/dim]"
    console.print(Panel(body, title=f"[bold yellow]🦊 FOX CLI v{VERSION}[/bold yellow]",
                        border_style=theme["border"], padding=(0, 2)))


def cmd_arena(state: dict, args: str, history: list) -> list:
    """/arena <prompt> — compare 2 models side-by-side."""
    if not args:
        console.print("[yellow]Usage: /arena <prompt>[/yellow]")
        return history
    or_key = state.get("openrouter_key") or load_or_key()
    if not or_key:
        console.print("[red]No API key configured.[/red]")
        return history
    theme  = state.get("theme", THEMES["fox"])
    acc    = theme["accent"]
    model1 = state.get("model", DEFAULT_FOX_MODEL)
    system = build_system_prompt(state)
    messages = [{"role": "system", "content": system}]
    for m in history:
        messages.append({"role": "assistant" if m["role"]=="model" else m["role"], "content": m["text"]})
    messages.append({"role": "user", "content": args})

    # Pick a second model automatically
    all_ids = [m["id"] for m in FOX_MODELS_LIST]
    model2  = next((m for m in all_ids if m != model1), "google/gemini-2.5-flash")
    console.print(f"\n  [{acc}]⚔ Arena[/{acc}]  [dim]{model1.split('/')[-1].split(':')[0]} vs {model2.split('/')[-1].split(':')[0]}[/dim]\n")

    results: dict[str, str | None] = {model1: None, model2: None}
    errors: dict[str, str | None]  = {model1: None, model2: None}

    def _run(m: str):
        r = call_openrouter_blocking(or_key, m, messages)
        results[m] = r

    t1 = threading.Thread(target=_run, args=(model1,))
    t2 = threading.Thread(target=_run, args=(model2,))
    t1.start(); t2.start()
    t1.join(); t2.join()

    r1 = results[model1] or "[dim](no response)[/dim]"
    r2 = results[model2] or "[dim](no response)[/dim]"
    short1 = model1.split("/")[-1].split(":")[0]
    short2 = model2.split("/")[-1].split(":")[0]

    p1 = Panel(Markdown(r1), title=f"[{acc}]{short1}[/{acc}]", border_style=theme["border"], padding=(0, 1))
    p2 = Panel(Markdown(r2), title=f"[{acc}]{short2}[/{acc}]", border_style=theme["border"], padding=(0, 1))
    console.print(Columns([p1, p2]))

    # Cost summary
    t1_in  = approx_tokens(args); t1_out = approx_tokens(r1)
    t2_in  = approx_tokens(args); t2_out = approx_tokens(r2)
    c1 = estimate_cost(model1, t1_in, t1_out)
    c2 = estimate_cost(model2, t2_in, t2_out)
    console.print(f"  [dim]Cost: {short1} ${c1:.6f}  ·  {short2} ${c2:.6f}[/dim]")
    return history


def cmd_export(state: dict, history: list, args: str) -> None:
    """/export [md|json|csv] — export conversation."""
    fmt   = args.strip().lower() if args else "md"
    theme = state.get("theme", THEMES["fox"])
    acc   = theme["accent"]
    ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = FOX_CONFIG_DIR / f"fox_export_{ts}.{fmt}"
    FOX_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if fmt == "json":
        fname.write_text(json.dumps({
            "version": VERSION,
            "exported": datetime.now().isoformat(),
            "model": state.get("model"),
            "history": history,
        }, indent=2))
    elif fmt == "csv":
        buf = io.StringIO()
        w   = csv.writer(buf)
        w.writerow(["role", "text", "chars"])
        for m in history:
            w.writerow([m["role"], m["text"], len(m["text"])])
        fname.write_text(buf.getvalue())
    else:
        # Markdown (default)
        lines = [f"# FOX CLI Export — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"]
        lines.append(f"**Model:** {state.get('model','?')}  \n")
        for m in history:
            role = "**You**" if m["role"] == "user" else "**FOX**"
            lines.append(f"\n{role}\n\n{m['text']}\n\n---")
        fname.write_text("\n".join(lines))

    console.print(f"  [{acc}]✓ Exported ({fmt}) → {fname}[/{acc}]")


def cmd_queue(state: dict, args: str) -> None:
    """/queue <task> — save a task to the background queue."""
    theme = state.get("theme", THEMES["fox"])
    acc   = theme["accent"]
    task  = args.strip()
    if not task:
        # Show queue
        q = []
        if FOX_QUEUE_FILE.exists():
            try:
                q = json.loads(FOX_QUEUE_FILE.read_text())
            except Exception:
                pass
        if not q:
            console.print("[dim]Queue is empty. Use /queue <task> to add.[/dim]")
            return
        rows = "\n".join(f"  [dim]{i+1}.[/dim] {item['task']}  [dim]({item['ts'][:16]})[/dim]"
                         for i, item in enumerate(q))
        console.print(Panel(rows, title=f"[bold]Background Queue ({len(q)} tasks)[/bold]",
                            border_style=theme["border"], padding=(0, 2)))
        return

    q = []
    if FOX_QUEUE_FILE.exists():
        try:
            q = json.loads(FOX_QUEUE_FILE.read_text())
        except Exception:
            pass
    q.append({"task": task, "ts": datetime.now().isoformat(), "status": "pending"})
    FOX_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    FOX_QUEUE_FILE.write_text(json.dumps(q, indent=2))
    console.print(Panel(
        f"  [{acc}]✓ Task queued:[/{acc}] {task}\n\n"
        f"  [dim]Queue file:[/dim] {FOX_QUEUE_FILE}\n"
        f"  [dim]Run /queue to view  ·  Background processing in FOX v1.1[/dim]",
        title="[bold yellow]🦊 Queue[/bold yellow]", border_style="yellow", padding=(0, 2)
    ))


def cmd_share(state: dict, history: list) -> None:
    """/share — copy conversation to clipboard as markdown."""
    if not history:
        console.print("[dim]Nothing to share yet.[/dim]")
        return
    theme = state.get("theme", THEMES["fox"])
    acc   = theme["accent"]
    lines = [f"# FOX CLI — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"]
    for m in history:
        role = "**You**" if m["role"] == "user" else "**FOX**"
        lines.append(f"\n{role}\n\n{m['text']}\n")
    md = "\n".join(lines)
    try:
        if sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=md.encode(), check=True)
        elif sys.platform == "win32":
            subprocess.run(["clip"], input=md.encode("utf-16"), check=True)
        else:
            subprocess.run(["xclip", "-selection", "clipboard"], input=md.encode(), check=True)
        console.print(f"  [{acc}]✓ Copied to clipboard ({len(md):,} chars, ~{approx_tokens(md):,} tokens)[/{acc}]")
    except Exception as exc:
        console.print(f"[yellow]Clipboard failed ({exc}). Printing instead:[/yellow]")
        console.print(md[:2000])


def cmd_theme(state: dict, args: str) -> None:
    """/theme [fox|noir|ember] — switch terminal theme."""
    acc = state.get("theme", THEMES["fox"])["accent"]
    if not args:
        console.print(f"  Available themes: [bold yellow]fox[/bold yellow]  noir  ember  [dim](current: {state['theme']['name']})[/dim]")
        return
    name = args.strip().lower()
    if name not in THEMES:
        console.print(f"[yellow]Unknown theme '{name}'. Available: {', '.join(THEMES)}[/yellow]")
        return
    state["theme"] = THEMES[name]
    FOX_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    FOX_THEME_FILE.write_text(name)
    console.print(f"  [{acc}]✓ Theme → {THEMES[name]['name']} {THEMES[name]['icon']}[/{acc}]")


def cmd_status(state: dict) -> None:
    """/status — show session info."""
    theme    = state.get("theme", THEMES["fox"])
    acc      = theme["accent"]
    plan_id  = get_profile_plan()
    plan     = PLANS.get(plan_id, PLANS["free"])
    model    = state.get("model", DEFAULT_FOX_MODEL)
    agent_id = state.get("active_agent") or "default"
    agent    = FOX_AGENTS.get(agent_id, FOX_AGENTS["default"])
    ctx      = state.get("auto_ctx")
    console.print(Panel(
        f"  [bold]Plan:[/bold]  [{plan['color']}]{plan['badge']} {plan['name']}[/{plan['color']}]\n"
        f"  [bold]Model:[/bold] {model.split('/')[-1].split(':')[0]}\n"
        f"  [bold]Agent:[/bold] {agent['icon']} {agent['name']}  [dim]{agent['desc']}[/dim]\n"
        f"  [bold]Theme:[/bold] {theme['name']}\n"
        f"  [bold]Context:[/bold] {'✓ ' + str(len(ctx['files'])) + ' files' if ctx else 'none'}\n"
        f"  [bold]Session cost:[/bold] ${state.get('_session_cost', 0.0):.6f}  "
        f"[dim]({state.get('_session_msgs', 0)} messages)[/dim]",
        title="[bold]FOX Status[/bold]", border_style=theme["border"], padding=(0, 2)
    ))


def cmd_voice(state: dict) -> None:
    """/voice — voice input (requires pyaudio — coming v1.2)."""
    try:
        import speech_recognition  # noqa: F401
        console.print("[dim yellow]🦊 speech_recognition detected — full voice mode in FOX v1.2[/dim yellow]")
    except ImportError:
        console.print(Panel(
            "  [bold yellow]🦊 Voice input — coming in FOX v1.2[/bold yellow]\n\n"
            "  [bold]Requirements:[/bold]\n"
            "  [dim]pip install SpeechRecognition pyaudio[/dim]\n\n"
            "  FOX will transcribe speech from your default microphone\n"
            "  and send it as a chat message.",
            title="[bold]Voice Input[/bold]", border_style="yellow", padding=(0, 2)
        ))

# ── REPL helpers ──────────────────────────────────────────────────────────────
_FOX_COMMANDS = [
    "/think", "/code", "/fix", "/commit", "/cost",
    "/model", "/agent", "/context", "/clear", "/help",
    "/arena", "/export", "/queue", "/share", "/memory",
    "/theme", "/status", "/voice", "/exit", "/quit",
]

def _load_fox_theme() -> dict:
    if FOX_THEME_FILE.exists():
        name = FOX_THEME_FILE.read_text().strip()
        if name in THEMES:
            return THEMES[name]
    return THEMES["fox"]

def _build_completer() -> WordCompleter:
    return WordCompleter(_FOX_COMMANDS, pattern=re.compile(r"(/\w*)"))

def _build_style(theme: dict) -> Style:
    pc = theme["prompt_user"].replace("ansi", "").replace("bold ", "")
    return Style.from_dict({
        "prompt":                             pc,
        "completion-menu.completion":         "bg:#1a1a10 fg:#ffffff",
        "completion-menu.completion.current": "bg:yellow fg:#000000",
        "completion-menu.meta.completion":    "bg:#1a1a10 fg:#aaaaaa",
        "bottom-toolbar":                     "bg:#1a1a10 fg:#665500",
    })

def _make_toolbar(state: dict):
    _cache = {"ts": 0.0, "branch": ""}
    def _toolbar():
        model   = state.get("model", DEFAULT_FOX_MODEL).split("/")[-1].split(":")[0][:18]
        cost    = state.get("_session_cost", 0.0)
        msgs    = state.get("_session_msgs", 0)
        now     = time.time()
        if now - _cache["ts"] > 5.0:
            try:
                r = subprocess.run(["git","branch","--show-current"],
                                   capture_output=True, text=True, timeout=1)
                _cache["branch"] = r.stdout.strip() if r.returncode == 0 else ""
            except Exception:
                _cache["branch"] = ""
            _cache["ts"] = now
        b_part = f" · <b>⎇{_cache['branch']}</b>" if _cache["branch"] else ""
        return HTML(f' 🦊 <b>FOX</b> · <b>{model}</b> · {msgs} msgs · ${cost:.4f}{b_part} ')
    return _toolbar

def _fox_prompt(state: dict) -> FormattedText:
    theme = state.get("theme", THEMES["fox"])
    pc    = theme["prompt_user"]
    icon  = theme["icon"]
    agent = state.get("active_agent") or "default"
    label = FOX_AGENTS.get(agent, FOX_AGENTS["default"])["name"]
    return FormattedText([
        (f"class:prompt", f" {icon} {label} "),
        ("", " › "),
    ])

# ── Main REPL ─────────────────────────────────────────────────────────────────
def run_repl() -> None:
    FOX_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    sess    = load_fox_session()
    or_key  = load_or_key()
    theme   = _load_fox_theme()

    state: dict = {
        "openrouter_key":        or_key,
        "model":                 sess.get("model") or DEFAULT_FOX_MODEL,
        "theme":                 theme,
        "active_agent":          sess.get("active_agent"),
        "system_prompt":         None,
        "auto_ctx":              None,
        "_session_cost":         0.0,
        "_session_tokens_in":    0,
        "_session_tokens_out":   0,
        "_session_msgs":         0,
        "_last_tokens":          None,
        "_last_response":        None,
        "_think_mode":           False,
    }

    # Restore agent system prompt
    if state["active_agent"] and state["active_agent"] in FOX_AGENTS:
        state["system_prompt"] = FOX_AGENTS[state["active_agent"]]["system"]

    # Auto-context
    ctx = detect_project_context(Path.cwd())
    if ctx:
        state["auto_ctx"] = ctx
        stack  = ", ".join(ctx["tech_stack"]) or "unknown"
        branch = f" · ⎇ {ctx['git_branch']}" if ctx.get("git_branch") else ""
        console.print(f"[dim yellow]🦊 context:[/dim yellow] [dim]{Path.cwd().name}{branch} · {stack} · {len(ctx['files'])} files[/dim]")

    # Key bindings
    kb = KeyBindings()

    @kb.add("c-l")
    def _kb_clear(event):
        clear_terminal()
        render_welcome(state)
        event.current_buffer.text = ""
        event.app.invalidate()

    @kb.add("c-k")
    def _kb_cost(event):
        console.print()
        cmd_cost(state)

    session = PromptSession(
        history=FileHistory(str(FOX_HISTORY_FILE)),
        style=_build_style(theme),
        completer=_build_completer(),
        complete_while_typing=True,
        key_bindings=kb,
        bottom_toolbar=_make_toolbar(state),
    )

    render_welcome(state)
    history: list = []

    while True:
        try:
            user_input = session.prompt(lambda: _fox_prompt(state)).strip()
        except KeyboardInterrupt:
            console.print("\n[dim yellow]Ctrl+C — type /exit to quit[/dim yellow]")
            continue
        except EOFError:
            console.print("[bold yellow]🦊 FOX out.[/bold yellow]")
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            parts = user_input[1:].split(" ", 1)
            cmd   = parts[0].lower().strip()
            args  = parts[1].strip() if len(parts) > 1 else ""

            if cmd in ("exit", "quit", "q"):
                console.print("[bold yellow]🦊 FOX out.[/bold yellow]")
                # Save session
                sess["model"]        = state.get("model")
                sess["active_agent"] = state.get("active_agent")
                save_fox_session(sess)
                break
            elif cmd == "think":    history = cmd_think(state, args, history)
            elif cmd == "code":     history = cmd_code(state, args, history)
            elif cmd == "fix":      history = cmd_fix(state, args, history) if args else (console.print("[yellow]Usage: /fix <file>[/yellow]"), history)[1]
            elif cmd == "commit":   history = cmd_commit(state, history)
            elif cmd == "cost":     cmd_cost(state)
            elif cmd == "model":    cmd_model(state, args)
            elif cmd == "agent":    cmd_agent(state, args)
            elif cmd == "context":  history = cmd_context(state, args, history)
            elif cmd == "memory":   cmd_memory(state, args)
            elif cmd == "clear":    history = cmd_clear(state)
            elif cmd == "help":     cmd_help(state, args)
            elif cmd == "arena":    history = cmd_arena(state, args, history)
            elif cmd == "export":   cmd_export(state, history, args)
            elif cmd == "queue":    cmd_queue(state, args)
            elif cmd == "share":    cmd_share(state, history)
            elif cmd == "theme":    cmd_theme(state, args)
            elif cmd == "status":   cmd_status(state)
            elif cmd == "voice":    cmd_voice(state)
            else:
                # Fuzzy match
                import difflib
                matches = difflib.get_close_matches("/" + cmd, _FOX_COMMANDS, n=1, cutoff=0.6)
                if matches:
                    console.print(f"[dim]Unknown /{cmd}. Did you mean [bold]{matches[0]}[/bold]?[/dim]")
                else:
                    console.print(f"[dim]Unknown /{cmd} — /help[/dim]")
        else:
            # Plain text → AI chat
            _, history = fox_respond(state, user_input, history)

# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="🦊 FOX CLI — Premium AI terminal (Studio Max+)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--setup",   action="store_true", help="Run onboarding / setup")
    parser.add_argument("--version", action="store_true", help="Show version and exit")
    parser.add_argument("--theme",   choices=list(THEMES.keys()), help="Override theme")
    parser.add_argument("prompt",    nargs="?", help="One-shot prompt (non-interactive)")
    args = parser.parse_args()

    if args.version:
        print(f"FOX CLI v{VERSION}")
        return

    FOX_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if args.setup or not FOX_ONBOARD_FILE.exists() or not load_profile():
        ok = run_onboarding()
        if not ok:
            sys.exit(1)
        if not args.setup:
            run_repl()
        return

    # Plan gate — runs every launch
    allowed, plan = check_fox_access()
    if not allowed:
        plan_info = PLANS.get(plan, {})
        console.print(Panel(
            f"  [bold red]FOX requires Max, Ultra, Enterprise, or Team plan.[/bold red]\n\n"
            f"  Your plan: [bold]{plan_info.get('name', plan)}[/bold]\n\n"
            f"  [dim]Upgrade in Studio CLI:[/dim]  [yellow]python aistudio.py → /upgrade max[/yellow]",
            title="[bold yellow]🦊 FOX — Upgrade Required[/bold yellow]",
            border_style="yellow", padding=(1, 2),
        ))
        sys.exit(0)

    if args.theme:
        _t = THEMES.get(args.theme, THEMES["fox"])
    else:
        _t = _load_fox_theme()

    # One-shot mode
    if args.prompt:
        or_key = load_or_key()
        if not or_key:
            print("No OpenRouter key. Run: fox --setup")
            sys.exit(1)
        state = {"model": DEFAULT_FOX_MODEL, "theme": _t, "openrouter_key": or_key,
                 "_session_cost": 0.0, "_session_tokens_in": 0, "_session_tokens_out": 0,
                 "_session_msgs": 0, "_think_mode": False, "_last_tokens": None,
                 "_last_response": None, "active_agent": None, "system_prompt": None}
        ctx = detect_project_context(Path.cwd())
        if ctx:
            state["auto_ctx"] = ctx
        fox_respond(state, args.prompt, [])
        return

    run_repl()


if __name__ == "__main__":
    main()
