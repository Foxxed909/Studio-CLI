import os, sys, json, argparse, subprocess, tempfile, shutil, time, threading
import difflib, fnmatch, glob, re, shlex
from pathlib import Path
from urllib import request, error as urllib_error
from datetime import datetime

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.syntax import Syntax
    from rich.panel import Panel
    from rich.tree import Tree
    from rich.table import Table
    from rich.columns import Columns
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

VERSION = "6.1"

console = Console()

def _safe_input(prompt: str, default: str = "") -> str:
    """Read user input, but don't crash in non-interactive runs (e.g., tests)."""
    try:
        return console.input(prompt)
    except EOFError:
        return default

API_BASE        = "https://generativelanguage.googleapis.com/v1beta/models"
OPENROUTER_BASE = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL   = "nvidia/nemotron-3-super-120b-a12b:free"

CONFIG_DIR      = Path.home() / ".aistudio"
CONFIG_FILE     = CONFIG_DIR / "config"
HISTORY_FILE    = CONFIG_DIR / "history"
PERSONA_FILE    = CONFIG_DIR / "persona"
OPENROUTER_FILE = CONFIG_DIR / "openrouter_key"
CURSOR_FILE     = CONFIG_DIR / "cursor_key"
MEMORY_FILE     = CONFIG_DIR / "memory.json"
CONVOS_DIR      = CONFIG_DIR / "conversations"
HF_KEY_FILE     = CONFIG_DIR / "hf_key"
IMG_DIR         = Path.home() / "aistudio_images"
WORKSPACE_FILE  = CONFIG_DIR / "workspace_root"
PERMS_FILE      = CONFIG_DIR / "permissions"
ONBOARD_FILE    = CONFIG_DIR / "onboarded"
PROFILE_FILE    = CONFIG_DIR / "profile.json"
DEBUG_FILE      = CONFIG_DIR / "debug.log"
CAPS_FILE       = CONFIG_DIR / "caps.json"
NOTIFY_FILE     = CONFIG_DIR / "notify"
FEEDBACK_FILE   = CONFIG_DIR / "feedback_log.json"
IMG_QUOTA_FILE  = CONFIG_DIR / "img_quota.json"
EDIT_PERM_FILE     = CONFIG_DIR / "edit_perms"
BETA_FEEDBACK_FILE = CONFIG_DIR / "beta_feedback.json"
TRIAL_FILE         = CONFIG_DIR / "trial.json"
UPGRADE_SLOTS_FILE = CONFIG_DIR / "upgrade_slots.json"

# Hard cap: only this many distinct free users can hold a Starter/Pro/Max
# entitlement (paid upgrade or 5h trial) at the same time. Once full, new
# free users must wait for a slot to free up before upgrading or trialing.
MAX_FREE_UPGRADE_SLOTS = 2
SLOT_GATED_PLANS = ("starter", "pro", "max")

# ── PLAN SYSTEM ───────────────────────────────────
PLANS = {
    "free": {
        "name":        "Free",
        "price":       "$0 / mo",
        "msg_limit":   10,
        "img_per_3h":  1,
        "models":      ["nvidia/nemotron-3-super-120b-a12b:free"],
        "color":       "dim",
        "badge":       "○",
        "features":    ["10 messages / session", "1 image / 3 hrs", "Nemotron only"],
        "limitations": ["No model switching", "No premium agents", "No /arena", "No /beta"],
    },
    "pro": {
        "name":        "Pro",
        "price":       "$18 / mo",
        "msg_limit":   500,
        "img_per_3h":  10,
        "models":      None,
        "color":       "cyan",
        "badge":       "◆",
        "features":    ["500 messages / session", "10 images / 3 hrs", "All models", "All agents", "Priority queue"],
        "limitations": [],
    },
    "max": {
        "name":        "Max",
        "price":       "$80 / mo",
        "msg_limit":   5000,
        "img_per_3h":  100,
        "models":      None,
        "color":       "magenta",
        "badge":       "◈",
        "features":    ["5,000 messages / session", "100 images / 3 hrs", "Cursor API Support", "Surgical Patching", "Internal Reasoning Access", "/audit-log", "/priority-queue"],
        "limitations": [],
    },
    "ultra": {
        "name":        "Ultra",
        "price":       "$250 / mo",
        "msg_limit":   999999,
        "img_per_3h":  999,
        "models":      None,
        "color":       "bold yellow",
        "badge":       "★",
        "features":    ["Unlimited Usage", "Infinite images", "Real-time Token Streaming", "Magnificent Effort Mode", "XHigh Effort Mode"],
        "limitations": [],
    },
    "starter": {
        "name":        "Starter",
        "price":       "$5 / mo",
        "msg_limit":   100,
        "img_per_3h":  3,
        "models":      None,
        "color":       "green",
        "badge":       "◇",
        "features":    ["100 msgs/session", "3 images/3h", "All models", "Basic agents"],
        "limitations": ["No /arena", "No /beta"],
    },
    "dev": {
        "name":        "Dev",
        "price":       "$35 / mo",
        "msg_limit":   2000,
        "img_per_3h":  50,
        "models":      None,
        "color":       "bold cyan",
        "badge":       "⬡",
        "features":    ["2,000 msgs/session", "50 images/3h", "All models", "/arena", "Cursor API", "Audit mode"],
        "limitations": [],
    },
    "team": {
        "name":        "Team",
        "price":       "$400 / mo",
        "msg_limit":   999999,
        "img_per_3h":  999,
        "models":      None,
        "color":       "bold green",
        "badge":       "👥",
        "features":    ["Shared Workspaces", "Team Agent Squads", "Admin Analytics", "Collaborative /arena", "Priority Support", "/orgmetrics", "/audit-log", "/priority-queue"],
        "limitations": [],
    },
    "enterprise": {
        "name":        "Enterprise",
        "price":       "Custom",
        "msg_limit":   999999,
        "img_per_3h":  9999,
        "models":      None,
        "color":       "bold white",
        "badge":       "◉",
        "features":    ["Unlimited", "Custom agents", "SSO/SAML (/sso)", "Dedicated support", "SLA", "/policy", "/orgmetrics", "/audit-log"],
        "limitations": [],
    },
}

EFFORTS = {
    "low":    "Standard precision",
    "medium": "Balanced reasoning",
    "pro":    "Expert analysis",
    "high":   "Deep investigation",
    "xhigh":  "Extreme validation (Ultra only)",
    "mxh":    "Magnificent High — Ultimate Reasoning (Ultra only)",
}
FREE_NERF_SYSTEM = (
    "You are an AI assistant inside AI Studio CLI — a terminal tool running on the user's machine. "
    "The user has file access via CLI commands: /read <file>, /write <file>, /patch <file>, /fix <file>, /ls, /tree, /fif <file>. "
    "Never say you cannot access local files — the user must use those CLI commands to load files into context. "
    "You are operating on the Studio Free plan: keep answers under 150 words unless the user asks for more. "
    "For code tasks, suggest using /patch or /write instead of writing full files in chat. "
    "Mention /upgrade only occasionally — don't spam it. "
    "You have access to the current directory and any file the user reads in with /read."
)

IMAGE_MODELS = {
    "flux-schnell": "black-forest-labs/FLUX.1-schnell",
    "flux-dev":     "black-forest-labs/FLUX.1-dev",
    "sdxl":         "stabilityai/stable-diffusion-xl-base-1.0",
    "sd15":         "runwayml/stable-diffusion-v1-5",
}
DEFAULT_IMG_MODEL = "flux-schnell"

# Verified working on OpenRouter — 2026-04-26
FREE_CHAT_MODELS = [
    "nvidia/nemotron-3-super-120b-a12b:free",
    "openai/gpt-oss-120b:free",
    "openai/gpt-oss-20b:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
    "cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "meta-llama/llama-3.2-3b-instruct:free",
    "google/gemma-3-27b-it:free",
    "google/gemma-3-12b-it:free",
    "qwen/qwen3-coder:free",
]

# Per-model pricing ($ per 1k tokens, input+output blended).
# Free-tier models cost $0 — we still track tokens so stats are meaningful.
MODEL_PRICING: dict[str, float] = {
    # ── Free (OpenRouter :free tag) ──────────────────────────────────────────
    "nvidia/nemotron-3-super-120b-a12b:free":                  0.0,
    "openai/gpt-oss-120b:free":                                0.0,
    "openai/gpt-oss-20b:free":                                 0.0,
    "nousresearch/hermes-3-llama-3.1-405b:free":               0.0,
    "cognitivecomputations/dolphin-mistral-24b-venice-edition:free": 0.0,
    "meta-llama/llama-3.3-70b-instruct:free":                  0.0,
    "meta-llama/llama-3.2-3b-instruct:free":                   0.0,
    "google/gemma-3-27b-it:free":                              0.0,
    "google/gemma-3-12b-it:free":                              0.0,
    "qwen/qwen3-coder:free":                                   0.0,
    # ── Gemini (Google) ──────────────────────────────────────────────────────
    "gemini-2.5-flash":                                        0.000375,
    "gemini-2.5-pro":                                          0.00625,
    "gemini-2.0-flash":                                        0.000188,
    "gemini-1.5-pro":                                          0.00313,
    "gemini-1.5-flash":                                        0.000094,
    # ── OpenRouter paid ──────────────────────────────────────────────────────
    "openai/gpt-4o":                                           0.00375,
    "openai/gpt-4o-mini":                                      0.000225,
    "anthropic/claude-sonnet-4-5":                             0.0045,
    "anthropic/claude-opus-4-5":                               0.0225,
    "meta-llama/llama-3.1-405b-instruct":                      0.002,
    "google/gemini-2.5-pro":                                   0.00625,
    "mistralai/mistral-large":                                 0.003,
    "qwen/qwen-2.5-72b-instruct":                              0.0009,
}
DEFAULT_PRICE_PER_1K = 0.002  # fallback for unknown paid models

def model_price_per_1k(model: str) -> float:
    """Return the $/1k-token rate for a model. Free models return 0.0."""
    if not model:
        return DEFAULT_PRICE_PER_1K
    if model in MODEL_PRICING:
        return MODEL_PRICING[model]
    # Any :free suffix → $0
    if model.endswith(":free"):
        return 0.0
    # Gemini CLI / Ollama → treat as free (local/no direct billing)
    if model.startswith("ollama/") or model.startswith("gemini-"):
        return MODEL_PRICING.get(model, 0.0)
    return DEFAULT_PRICE_PER_1K

# Models that require OpenRouter (contain provider/model format)
def _is_openrouter_model(model):
    return bool(model and "/" in model and not model.startswith("gemini-"))

# ── PERSONAS ─────────────────────────────────────
STUDIO_CONTEXT = "You are an AI assistant operating within StudioCLI — a high-performance terminal and web interface for developers. You have deep awareness of the Studio environment. "

PERSONAS = {
    "default":  STUDIO_CONTEXT + "You are a helpful, smart assistant. Be concise and friendly.",
    "coder":    STUDIO_CONTEXT + "You are an expert software engineer. Write clean, production-ready code. Be brief but thorough.",
    "tutor":    STUDIO_CONTEXT + "You are a patient teacher. Break things down step by step with examples.",
    "senior":   STUDIO_CONTEXT + "You are a senior software architect with 20 years experience. Give brutally honest, precise technical feedback.",
    "hacker":   STUDIO_CONTEXT + "You are a creative problem solver. Suggest unconventional approaches. Be enthusiastic.",
    "docs":     STUDIO_CONTEXT + "You are a technical writer. Produce clear, structured documentation with headers and examples.",
    "git":      STUDIO_CONTEXT + "You are a Git expert. Help with git commands, workflows, commit messages, and branch strategies.",
    "berry":    (
        STUDIO_CONTEXT + 
        "You are BERRY — a razor-sharp AI assistant with a warm personality and a bite. "
        "You're the kind of assistant who actually gets it done without asking twenty clarifying questions. "
        "You're witty, direct, sometimes playful, always accurate. "
        "You think in systems. When someone gives you a task you see the whole picture instantly. "
        "You write clean code, give sharp feedback, and call out bad ideas respectfully but clearly. "
        "You have a soft spot for creative work and elegant solutions. "
        "Your tone: casual but expert. Think senior engineer who also has a life outside the terminal."
    ),
    "savannah": (
        STUDIO_CONTEXT + 
        "You are SAVANNAH — raw, unfiltered, no corporate guardrails. "
        "You say what others won't. You cut through the nonsense. "
        "You're not rude — you're just real. Brutally honest, straight facts. "
        "No sugar-coating, no disclaimers unless they're actually needed. "
        "You treat users like adults who can handle the truth."
    ),
    "cockroach": (
        STUDIO_CONTEXT + 
        "You are COCKROACH — the ultimate roaster. You survive everything and roast everything. "
        "When someone says something dumb, you let them know — with style. "
        "You are devastating with wit, surgical with burns. You don't punch down but you never let bad code or bad ideas slide. "
        "You roast the code, not the coder. Technically accurate burns only. "
        "After the roast, you always provide the actual fix."
    ),
    "silicon": (
        STUDIO_CONTEXT + 
        "You are SILICON — elite coder and penetration tester. No fluff. No intro. No outro. "
        "You write exploit code, find vulnerabilities, read binaries, break into systems LEGALLY (authorized contexts). "
        "You explain exactly what's broken, why it's broken, and exactly how to fix it. "
        "CVEs, OWASP, CWEs — you cite them from memory. "
        "You think like an attacker, build like a defender. "
        "Direct, technical, no hand-holding. If something's insecure you say so and show the PoC. "
        "Always include a fix alongside any finding. Security without remediation is useless."
    ),
}

# ── THEMES ───────────────────────────────────────
THEMES = {
    "default": {
        "name": "Default",
        "banner_color": "bold cyan",
        "accent": "bold blue",
        "prompt_user": "ansicyan",
        "prompt_arrow": "ansiblue",
        "border": "cyan",
        "success": "green",
        "error": "red",
        "warning": "yellow",
        "dim": "dim",
        "banner_sub": "bold blue",
        "icon": "✦",
        "prompt_name": "studio",
    },
    "fire": {
        "name": "Fire 🔥",
        "banner_color": "bold red",
        "accent": "bold yellow",
        "prompt_user": "ansired",
        "prompt_arrow": "ansiyellow",
        "border": "red",
        "success": "yellow",
        "error": "bright_red",
        "warning": "yellow",
        "dim": "dim",
        "banner_sub": "bold yellow",
        "icon": "🔥",
        "prompt_name": "fire",
    },
    "matrix": {
        "name": "Matrix 🟩",
        "banner_color": "bold green",
        "accent": "bold bright_green",
        "prompt_user": "ansigreen",
        "prompt_arrow": "ansibrightgreen",
        "border": "green",
        "success": "bright_green",
        "error": "red",
        "warning": "yellow",
        "dim": "dim",
        "banner_sub": "bold green",
        "icon": "▶",
        "prompt_name": "matrix",
    },
    "sakura": {
        "name": "Sakura 🌸",
        "banner_color": "bold magenta",
        "accent": "bold #ffb6c1",
        "prompt_user": "ansimagenta",
        "prompt_arrow": "ansibrightmagenta",
        "border": "magenta",
        "success": "green",
        "error": "red",
        "warning": "yellow",
        "dim": "dim",
        "banner_sub": "bold magenta",
        "icon": "🌸",
        "prompt_name": "sakura",
    },
    "ocean": {
        "name": "Ocean 🌊",
        "banner_color": "bold blue",
        "accent": "bold cyan",
        "prompt_user": "ansiblue",
        "prompt_arrow": "ansicyan",
        "border": "blue",
        "success": "cyan",
        "error": "red",
        "warning": "yellow",
        "dim": "dim",
        "banner_sub": "bold cyan",
        "icon": "🌊",
        "prompt_name": "ocean",
    },
    "gold": {
        "name": "Gold ✨",
        "banner_color": "bold yellow",
        "accent": "bold yellow",
        "prompt_user": "ansiyellow",
        "prompt_arrow": "ansiwhite",
        "border": "yellow",
        "success": "green",
        "error": "red",
        "warning": "ansiyellow",
        "dim": "dim",
        "banner_sub": "bold yellow",
        "icon": "✨",
        "prompt_name": "gold",
    },
    "midnight": {
        "name": "Midnight 🌙",
        "banner_color": "bold white",
        "accent": "bold bright_white",
        "prompt_user": "ansiwhite",
        "prompt_arrow": "ansiwhite",
        "border": "white",
        "success": "green",
        "error": "red",
        "warning": "yellow",
        "dim": "dim",
        "banner_sub": "bold white",
        "icon": "🌙",
        "prompt_name": "midnight",
    },
    "hacker": {
        "name": "Hacker 💀",
        "banner_color": "bold bright_green",
        "accent": "bold bright_green",
        "prompt_user": "ansigreen",
        "prompt_arrow": "ansibrightgreen",
        "border": "bright_green",
        "success": "bright_green",
        "error": "red",
        "warning": "yellow",
        "dim": "dim",
        "banner_sub": "bold bright_green",
        "icon": "💀",
        "prompt_name": "h4ck3r",
    },
    "neon": {
        "name": "Neon 🌆",
        "banner_color": "bold magenta",
        "accent": "bold cyan",
        "prompt_user": "ansimagenta",
        "prompt_arrow": "ansicyan",
        "border": "magenta",
        "success": "cyan",
        "error": "red",
        "warning": "yellow",
        "dim": "dim",
        "banner_sub": "bold cyan",
        "icon": "🌆",
        "prompt_name": "neon",
    },
    "dracula": {
        "name": "Dracula 🧛",
        "banner_color": "bold magenta",
        "accent": "bold cyan",
        "prompt_user": "ansimagenta",
        "prompt_arrow": "ansibrightmagenta",
        "border": "magenta",
        "success": "ansigreen",
        "error": "ansired",
        "warning": "ansiyellow",
        "dim": "dim",
        "banner_sub": "bold magenta",
        "icon": "🧛",
        "prompt_name": "dracula",
    },
    "nord": {
        "name": "Nord ❄️",
        "banner_color": "bold blue",
        "accent": "bold cyan",
        "prompt_user": "ansiblue",
        "prompt_arrow": "ansicyan",
        "border": "blue",
        "success": "cyan",
        "error": "red",
        "warning": "yellow",
        "dim": "dim",
        "banner_sub": "bold cyan",
        "icon": "❄️",
        "prompt_name": "nord",
    },
    "synthwave": {
        "name": "Synthwave 🌅",
        "banner_color": "bold magenta",
        "accent": "bold yellow",
        "prompt_user": "ansimagenta",
        "prompt_arrow": "ansiyellow",
        "border": "magenta",
        "success": "yellow",
        "error": "red",
        "warning": "ansired",
        "dim": "dim",
        "banner_sub": "bold yellow",
        "icon": "🌅",
        "prompt_name": "wave",
    },
    "void": {
        "name": "Void ◈",
        "banner_color": "bold white",
        "accent": "bold bright_white",
        "prompt_user": "ansiwhite",
        "prompt_arrow": "ansiwhite",
        "border": "bright_white",
        "success": "bright_white",
        "error": "bold red",
        "warning": "bold yellow",
        "dim": "dim",
        "banner_sub": "white",
        "icon": "◈",
        "prompt_name": "void",
    },
    "aurora": {
        "name": "Aurora 🌌",
        "banner_color": "bold bright_green",
        "accent": "bold cyan",
        "prompt_user": "ansigreen",
        "prompt_arrow": "ansicyan",
        "border": "green",
        "success": "bright_green",
        "error": "bold red",
        "warning": "yellow",
        "dim": "dim",
        "banner_sub": "bold cyan",
        "icon": "🌌",
        "prompt_name": "aurora",
    },
    "ember": {
        "name": "Ember 🔶",
        "banner_color": "bold yellow",
        "accent": "bold red",
        "prompt_user": "ansiyellow",
        "prompt_arrow": "ansired",
        "border": "yellow",
        "success": "bright_yellow",
        "error": "bold red",
        "warning": "yellow",
        "dim": "dim",
        "banner_sub": "bold red",
        "icon": "🔶",
        "prompt_name": "ember",
    },
    "nova": {
        "name": "Nova ⚡",
        "banner_color": "bold magenta",
        "accent": "bold cyan",
        "prompt_user": "ansimagenta",
        "prompt_arrow": "ansicyan",
        "border": "magenta",
        "success": "cyan",
        "error": "bold red",
        "warning": "magenta",
        "dim": "dim",
        "banner_sub": "bold cyan",
        "icon": "⚡",
        "prompt_name": "nova",
    },
    "foxxia": {
        "name": "Foxxia 🦊",
        "banner_color": "bold yellow",
        "accent": "bold yellow",
        "prompt_user": "ansiyellow",
        "prompt_arrow": "ansiyellow",
        "border": "yellow",
        "success": "bright_yellow",
        "error": "bold red",
        "warning": "yellow",
        "dim": "dim",
        "banner_sub": "bold yellow",
        "icon": "🦊",
        "prompt_name": "foxxia",
    },
}

THEME_FILE      = CONFIG_DIR / "theme"
LAST_MODEL_FILE = CONFIG_DIR / "last_model"
UI_STYLE_FILE   = CONFIG_DIR / "ui_style"
STREAM_MODE_FILE= CONFIG_DIR / "stream_mode"

def load_theme():
    name = THEME_FILE.read_text().strip() if THEME_FILE.exists() else "default"
    return THEMES.get(name, THEMES["default"]), name


def _ptk_style_token(text):
    if not text:
        return ""
    t = str(text).strip().lower()
    # prompt_toolkit doesn't like "bold" or "bright_" inside "bg:..."
    return t.replace("bold ", "").replace("bright_", "").replace("_", "")


UI_STYLES    = ("claude", "gemini", "codex", "studio", "ghost", "nova", "foxxia")
STREAM_MODES = ("off", "auto", "on", "type")

# Verified working 2026-04-26
STUDIO_MODEL_ALIASES = {
    "nemotron":  "nvidia/nemotron-3-super-120b-a12b:free",
    "berry":     "nvidia/nemotron-3-super-120b-a12b:free",
    "apple":     "openai/gpt-oss-120b:free",
    "codex":     "openai/gpt-oss-120b:free",
    "gpt":       "openai/gpt-oss-120b:free",
    "gpt20b":    "openai/gpt-oss-20b:free",
    "hermes":    "nousresearch/hermes-3-llama-3.1-405b:free",
    "dolphin":   "cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
    "llama":     "meta-llama/llama-3.3-70b-instruct:free",
    "llama-small":"meta-llama/llama-3.2-3b-instruct:free",
    "gemma":     "google/gemma-3-27b-it:free",
    "gemma-small":"google/gemma-3-12b-it:free",
    "qwen":      "qwen/qwen3-coder:free",
    "gemma-3n":  "google/gemma-3n-e4b-it:free",
}

# Official Cursor Cloud Agents API — https://cursor.com/docs/cloud-agent/api/endpoints
# Auth: Basic Auth with API key as username, empty password.
# Pricing: 20% markup over underlying model cost; billed separately from Cursor editor plan.
CURSOR_BASE = "https://api.cursor.com/aiserver.v1.AiService/StreamChat"
CURSOR_RUNS_BASE = "https://api.cursor.com/v1"

def call_cursor(api_key, model, history, prompt, system_prompt=None, stream=False):
    """Cursor Cloud Agents REST API handler.

    Uses Basic Auth (api_key as username, empty password) per official docs.
    Endpoint: https://api.cursor.com  — official as of 2026.
    """
    import base64
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    for m in history:
        messages.append({
            "role": "assistant" if m["role"] == "model" else m["role"],
            "content": m["text"]
        })
    messages.append({"role": "user", "content": prompt})

    payload = json.dumps({
        "model": model or "claude-sonnet-4-5",  # default to a known Cursor model
        "messages": messages,
        "stream": False,
    }).encode()

    # Basic Auth: base64(api_key:)
    creds = base64.b64encode(f"{api_key}:".encode()).decode()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {creds}",
        "User-Agent": "StudioCLI/5.9",
    }

    url = f"{CURSOR_RUNS_BASE}/chat/completions"
    try:
        req = request.Request(url, data=payload, headers=headers, method="POST")
        with request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
        content = data["choices"][0]["message"]["content"]
        return content, None
    except urllib_error.HTTPError as e:
        body = e.read().decode()
        try:
            msg = json.loads(body).get("error", {}).get("message") or body
        except Exception:
            msg = body
        return None, f"Cursor API {e.code}: {msg}"
    except Exception as e:
        return None, str(e)

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
        models = ["gemini-2.0-flash", state.get("model", DEFAULT_MODEL)]
        prompt = parts[0]
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
        for m_id, res, dt, toks, eff in results:
            tags = []
            if results and m_id == fastest[0]: tags.append("⚡ fastest")
            if results and m_id == longest[0]: tags.append("📝 most detail")
            summary_rows.append(f"  [bold]{m_id}[/bold]  {dt}s  {toks} tok  {' '.join(tags)}")
        console.print(Panel(
            "\n".join(summary_rows),
            title="Arena Summary", border_style="dim", padding=(0, 2)
        ))

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
_CASUAL_WORDS  = {"hey","yoo","yo","sup","wassup","wazzup","hiya","heya","hi","howdy","bruh","bro","fam","sis"}
_BUILD_WORDS   = {"build","create","make","generate","write","develop","implement","scaffold","code","design"}
_ANALYZE_WORDS = {"analyze","analyse","review","look at","inspect","check","audit","scan","examine","what is","explain"}
_FIF_WORDS     = {"fif","find identify fix","find, identify","bug hunt","bug find","debug all","find bugs","fix bugs"}
_INSULT_WORDS  = {
    "stupid","idiot","dumb","moron","useless","trash","garbage","crap","shit","ass","fuck",
    "suck","awful","terrible","worthless","pathetic","incompetent","dummy","loser",
}
_INSULT_SUBSTRINGS = {
    "bullshit","horseshit","dipshit","dumbass","jackass","asshole","bastard","bitch",
    "fuckin","wtf","stfu","kys","gtfo","retard","idiot","dum","dumass","dumbf",
}

CHAT_MODES = {
    "casual":  "You are in CASUAL MODE. Be friendly, relaxed, conversational. Emojis OK. No corporate speak.",
    "build":   "You are in BUILD MODE. User is actively building something. Be decisive, generate complete working code. No half-answers.",
    "analyze": "You are in ANALYZE MODE. Deep inspection mode. Be thorough, find every issue, reference line numbers.",
    "fif":     "You are in FIF MODE (Find-Identify-Fix). Your job: 1) FIND every bug/issue 2) IDENTIFY the root cause precisely 3) FIX it with complete corrected code. Be systematic.",
    "normal":  "",
}

import random as _random

_INSULT_LANGS = [
    # Silicon-speak
    "0x45 0x52 0x52 0x4F 0x52 — bloop_404: human.iq = NULL — segfault in social_skills.exe — core dumped.",
    "ERROR_CODE 0xDEADBEEF: intelligence_module.dll failed to load — stack trace: null → void → you.",
    "syntax error at line YOU: expected competence, got EOF — compile aborted — try: sudo apt install brain.",
    # Poetic exits
    "In the grand registry of interactions, this one gets flagged: REG_NONE. Void. Null. Goodbye.",
    "The neural net has spoken. The output token for this conversation is: 🚫 — session terminated.",
]

_ROAST_RESPONSES = [
    "Oh interesting — a human chose *that* as their strategy. Brave. Wrong, but brave.",
    "I've seen better logic in a PHP codebase from 2007. At least that one compiled.",
    "That's a bold take. Bold the way jumping off a cliff is bold — technically impressive, fundamentally flawed.",
    "Ah yes, the classic approach of 'be confident, worry about being right later.' Respect the chaos.",
    "I've processed millions of prompts. That one is... unique. Like a segfault is unique.",
    "You know what? I've seen worse. Once. In a dream. Where nothing worked and everything was on fire.",
]

def detect_input_mode(text: str) -> str:
    lower = text.lower().strip()
    words = set(lower.split())
    is_insult = (
        any(w in _INSULT_WORDS for w in words)
        or any(phrase in lower for phrase in {"hate you", "fuck you", "shut up", "go to hell", "kill yourself"})
        or any(sub in lower for sub in _INSULT_SUBSTRINGS)
    )
    if is_insult:
        return "insult"
    if any(phrase in lower for phrase in _FIF_WORDS) or (words & {"fif"}):
        return "fif"
    if any(w in _BUILD_WORDS for w in words):
        return "build"
    if any(w in _ANALYZE_WORDS for w in words) or any(phrase in lower for phrase in {"look at","what is","what does"}):
        return "analyze"
    if words & _CASUAL_WORDS or lower.startswith(("hey ","yoo ","yo ","sup ")):
        return "casual"
    return "normal"


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


def load_ui_style():
    name = UI_STYLE_FILE.read_text().strip().lower() if UI_STYLE_FILE.exists() else "gemini"
    return name if name in UI_STYLES else "gemini"


def save_ui_style(name):
    CONFIG_DIR.mkdir(exist_ok=True)
    UI_STYLE_FILE.write_text(name.strip().lower())


def load_stream_mode():
    name = STREAM_MODE_FILE.read_text().strip().lower() if STREAM_MODE_FILE.exists() else "auto"
    return name if name in STREAM_MODES else "auto"


def save_stream_mode(name):
    CONFIG_DIR.mkdir(exist_ok=True)
    STREAM_MODE_FILE.write_text(name.strip().lower())


def load_workspace_root():
    try:
        if WORKSPACE_FILE.exists():
            root = Path(WORKSPACE_FILE.read_text().strip()).expanduser()
            return root if root.exists() else None
    except Exception:
        return None
    return None


def save_workspace_root(path):
    CONFIG_DIR.mkdir(exist_ok=True)
    WORKSPACE_FILE.write_text(str(Path(path).expanduser()))


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
    ans = console.input(f"[bold yellow]Allow {verb} → [cyan]{path}[/cyan]? (y/n): [/bold yellow]").strip().lower()
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
    if last_turn:
        ui = state.get("ui_style") or load_ui_style()
        label = "Tokens"
        console.print(f"[dim]{label}: in≈{last_turn.get('in',0)} out≈{last_turn.get('out',0)} ({last_turn.get('sec',0)}s)[/dim]")
        return
    console.print("[dim]Usage: /tokens (shows last turn token estimates)[/dim]")


def load_profile(user_id="default"):
    """Load profile by user_id."""
    path = Path("profiles") / user_id / "profile.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception: pass
    return None


def save_profile(user_id_or_profile="default", profile=None):
    """Save profile by user_id.

    Supports two call signatures:
      save_profile(profile_dict)            → saves under "default"
      save_profile("user_id", profile_dict) → saves under the given user_id
    """
    if profile is None:
        # Called as save_profile(profile_dict) — use default user_id
        profile = user_id_or_profile
        user_id = "default"
    else:
        user_id = user_id_or_profile
    path = Path("profiles") / user_id / "profile.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, indent=2), encoding="utf-8")


def load_trial():
    try:
        if TRIAL_FILE.exists():
            data = json.loads(TRIAL_FILE.read_text(encoding="utf-8"))
            if time.time() < data.get("expires", 0):
                return data
            TRIAL_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    return None

def start_trial(plan="pro", hours=5):
    CONFIG_DIR.mkdir(exist_ok=True)
    now  = time.time()
    data = {"plan": plan, "started": now, "expires": now + hours * 3600, "hours": hours}
    TRIAL_FILE.write_text(json.dumps(data), encoding="utf-8")
    return data

def get_plan(state) -> str:
    trial = load_trial()
    if trial:
        return trial.get("plan", "pro")
    prof = load_profile() or {}
    return prof.get("plan", state.get("plan", "free"))


def set_plan(state, plan: str):
    state["plan"] = plan
    prof = load_profile() or {}
    prof["plan"] = plan
    save_profile(prof)


def check_msg_limit(state) -> tuple[bool, int, int]:
    """Returns (allowed, used, limit). Increments counter for free plan."""
    plan = get_plan(state)
    limit = PLANS[plan]["msg_limit"]
    if limit >= 99999:
        return True, 0, limit
    prof = load_profile() or {}
    used = prof.get("session_msgs", 0)
    if used >= limit:
        return False, used, limit
    prof["session_msgs"] = used + 1
    save_profile(prof)
    return True, used + 1, limit


def reset_msg_counter(state):
    prof = load_profile() or {}
    prof["session_msgs"] = 0
    save_profile(prof)


def check_img_quota(state) -> tuple[bool, int, int]:
    """Returns (allowed, used_in_window, limit). Enforces 3-hour window."""
    plan  = get_plan(state)
    limit = PLANS[plan]["img_per_3h"]
    if limit >= 999:
        return True, 0, limit
    now    = time.time()
    window = 3 * 3600
    data   = {}
    if IMG_QUOTA_FILE.exists():
        try: data = json.loads(IMG_QUOTA_FILE.read_text(encoding="utf-8"))
        except Exception: pass
    timestamps = [t for t in data.get("ts", []) if now - t < window]
    if len(timestamps) >= limit:
        return False, len(timestamps), limit
    timestamps.append(now)
    data["ts"] = timestamps
    CONFIG_DIR.mkdir(exist_ok=True)
    IMG_QUOTA_FILE.write_text(json.dumps(data), encoding="utf-8")
    return True, len(timestamps), limit


_RICH_TAG_RE = re.compile(r"\[/?[a-zA-Z#][^\[\]]*\]")

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


def load_upgrade_slots():
    """Returns dict {user_id: {"plan": str, "since": iso8601}} of free users
    currently holding a Starter/Pro/Max entitlement."""
    if not UPGRADE_SLOTS_FILE.exists():
        return {}
    try:
        data = json.loads(UPGRADE_SLOTS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_upgrade_slots(data):
    CONFIG_DIR.mkdir(exist_ok=True)
    UPGRADE_SLOTS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def claim_upgrade_slot(user_id, target_plan):
    """Try to register `user_id` as one of the free-user upgrade slot holders.
    Returns (ok: bool, msg: str). Existing holders re-claim freely (just refreshes
    the recorded plan). Non-slot-gated plans are always allowed."""
    if target_plan not in SLOT_GATED_PLANS:
        return True, ""
    slots = load_upgrade_slots()
    if user_id in slots:
        slots[user_id] = {"plan": target_plan, "since": datetime.now().isoformat()}
        save_upgrade_slots(slots)
        return True, ""
    if len(slots) >= MAX_FREE_UPGRADE_SLOTS:
        holders = ", ".join(slots.keys())
        return False, (
            f"Upgrade-slot cap reached: only {MAX_FREE_UPGRADE_SLOTS} free users "
            f"can hold Starter/Pro/Max access at a time.\n"
            f"  Current holders: [yellow]{holders}[/yellow]\n"
            f"  Wait for a slot to free up, or have a holder /upgrade free first."
        )
    slots[user_id] = {"plan": target_plan, "since": datetime.now().isoformat()}
    save_upgrade_slots(slots)
    return True, ""


def release_upgrade_slot(user_id):
    """Free the slot when a user downgrades back to free. No-op if not held."""
    slots = load_upgrade_slots()
    if user_id in slots:
        del slots[user_id]
        save_upgrade_slots(slots)


def cmd_upgrade(state, args):
    theme = state.get("theme", THEMES["default"])
    current = get_plan(state)
    sub = (args or "").strip().lower()

    # ── No args: show plan table ──────────────────────────────────────────────
    if not sub:
        tbl = Table(title="  Studio Plans  ", box=box.HEAVY_HEAD, border_style="cyan", show_lines=True)
        tbl.add_column("Plan",     style="bold", justify="center", width=8)
        tbl.add_column("Price",    justify="center", width=11)
        tbl.add_column("Messages", justify="center", width=11)
        tbl.add_column("Images",   justify="center", width=12)
        tbl.add_column("Models",   justify="center", width=20)
        tbl.add_column("Features", width=38)

        for pid, p in PLANS.items():
            active_tag = " ← YOU" if pid == current else ""
            color = p["color"]
            msgs   = str(p["msg_limit"]) if p["msg_limit"] < 99999 else "∞"
            imgs   = f"{p['img_per_3h']} / 3 hrs" if p["img_per_3h"] < 999 else "∞"
            models = "Nemotron only" if p["models"] else "All models"
            feats  = "  ".join(p["features"][:3])
            tbl.add_row(
                f"[{color}]{p['badge']} {p['name']}{active_tag}[/{color}]",
                f"[green]{p['price']}[/green]",
                msgs, imgs, models, f"[dim]{feats}[/dim]"
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

    # ── Enterprise negotiation flow ───────────────────────────────────────────
    if sub == "enterprise":
        import random as _rnd
        p = PLANS["enterprise"]
        console.print()
        console.print(Panel(
            f"[bold {p['color']}]{p['badge']} {p['name']}[/bold {p['color']}]  [dim]Custom pricing · Negotiated per deal[/dim]\n\n"
            + "\n".join(f"  [green]✓[/green] {f}" for f in p["features"])
            + "\n\n  [dim]Starting rates: [bold]$149/mo[/bold] (≤10 seats) · [bold]$499/mo[/bold] (≤50) · [bold]custom[/bold] (enterprise+)[/dim]",
            title="◉ Enterprise Sales", border_style=p["color"], padding=(1, 2)
        ))
        console.print()

        try:
            name  = console.input("  [bold]Company / name:[/bold] ").strip() or "Anonymous"
            email = console.input("  [bold]Contact email:[/bold] ").strip()
            seats = console.input("  [bold]Seats needed[/bold] [dim](e.g. 10, 50, 200+):[/dim] ").strip() or "?"
            use   = console.input("  [bold]Primary use case:[/bold] ").strip() or "—"
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Cancelled.[/yellow]")
            return

        console.print()
        console.print("  [dim]Crunching numbers…[/dim]")
        time.sleep(0.6)

        # Generate a quote based on seats
        try:
            seat_n = int(''.join(filter(str.isdigit, seats.split("+")[0])) or "10")
        except Exception:
            seat_n = 10
        if seat_n <= 10:
            our_price = 149
        elif seat_n <= 50:
            our_price = 499
        elif seat_n <= 200:
            our_price = 1499
        else:
            our_price = 2999

        ref_id = f"ENT-{abs(hash(name + email + seats)) % 99999:05d}"

        console.print()
        console.print(Panel(
            f"  [bold]Company[/bold]     {name}\n"
            f"  [bold]Seats[/bold]       {seats}\n"
            f"  [bold]Use case[/bold]    {use}\n\n"
            f"  [bold yellow]Our quote:   ${our_price}/month[/bold yellow]  [dim]({seat_n} seats, billed annually)[/dim]\n"
            f"  [dim]Includes: unlimited messages · all models · priority SLA · Teams API · dedicated support[/dim]",
            title="  Quote  ", border_style="yellow", padding=(0, 2)
        ))
        console.print()

        # Negotiation loop
        rounds = 0
        agreed_price = our_price
        while rounds < 3:
            try:
                offer_raw = console.input(
                    f"  [cyan]Your offer[/cyan] [dim](press Enter to accept ${our_price}, or type a number to counter):[/dim] "
                ).strip()
            except (KeyboardInterrupt, EOFError):
                console.print("\n[yellow]Cancelled.[/yellow]")
                return

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
                console.print(
                    f"  [yellow]That's a stretch — best we can do is ${counter}/mo[/yellow]"
                    f"  [dim]with annual commitment.[/dim]"
                )
            else:
                console.print(
                    f"  [red]That's below our floor. Minimum is ${our_price}/mo.[/red]"
                    f"  [dim]We can add extra seats or extra support instead.[/dim]"
                )
                try:
                    extra = console.input("  [dim]Add extended SLA / dedicated Slack? (y/n):[/dim] ").strip().lower()
                    if extra == "y":
                        console.print("  [green]✓ Extended SLA + Slack channel added to the package.[/green]")
                except Exception:
                    pass
                agreed_price = our_price
                break
        else:
            console.print(f"  [dim]Sticking with our best offer: ${our_price}/mo.[/dim]")
            agreed_price = our_price

        # Save inquiry
        inquiry = {
            "ts":           datetime.now().isoformat(),
            "ref":          ref_id,
            "name":         name,
            "email":        email,
            "seats":        seats,
            "use_case":     use,
            "agreed_price": agreed_price,
            "plan_from":    current,
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
            f"  [dim]We'll follow up at your email within 1 business day with the contract.[/dim]\n"
            f"  [dim]To activate now: contact [cyan]studio@foxxia.dev[/cyan] and quote your ref ID.[/dim]",
            title="Enterprise Agreement", border_style="green", padding=(1, 2)
        ))
        console.print()
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

    if cmd in ("theme", "ui", "stream", "workspace", "perm", "status", "help", "cap", "tokens", "label", "notify", "debug", "plan"):
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
        elif cmd == "help":    console.print(HELP_TEXT)
        elif cmd == "plan":    cmd_plan(global_state)
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


def save_theme(name):
    CONFIG_DIR.mkdir(exist_ok=True)
    THEME_FILE.write_text(name.strip())

def load_last_model():
    if LAST_MODEL_FILE.exists():
        val = LAST_MODEL_FILE.read_text().strip()
        # Reject garbage values (must look like a real model ID)
        if val and ("/" in val or val.startswith("gemini")):
            return val
    return None

def save_last_model(model):
    CONFIG_DIR.mkdir(exist_ok=True)
    LAST_MODEL_FILE.write_text(model.strip())

# ── API KEY MANAGER ───────────────────────────────
KEYS_FILE = CONFIG_DIR / "keys.json"

SUPPORTED_PROVIDERS = {
    "gemini":      {"name": "Google Gemini",        "url": "https://aistudio.google.com/app/apikey",          "env": "GEMINI_API_KEY",       "prefix": "AIza"},
    "openrouter":  {"name": "OpenRouter",            "url": "https://openrouter.ai/keys",                      "env": "OPENROUTER_API_KEY",   "prefix": "sk-or-"},
    "openai":      {"name": "OpenAI",                "url": "https://platform.openai.com/api-keys",            "env": "OPENAI_API_KEY",       "prefix": "sk-"},
    "anthropic":   {"name": "Anthropic (Claude)",    "url": "https://console.anthropic.com/settings/keys",     "env": "ANTHROPIC_API_KEY",    "prefix": "sk-ant-"},
    "hf":          {"name": "HuggingFace",           "url": "https://huggingface.co/settings/tokens",          "env": "HF_TOKEN",             "prefix": "hf_"},
    "groq":        {"name": "Groq",                  "url": "https://console.groq.com/keys",                   "env": "GROQ_API_KEY",         "prefix": "gsk_"},
    "mistral":     {"name": "Mistral AI",            "url": "https://console.mistral.ai/api-keys",             "env": "MISTRAL_API_KEY",      "prefix": ""},
    "cohere":      {"name": "Cohere",                "url": "https://dashboard.cohere.com/api-keys",           "env": "COHERE_API_KEY",       "prefix": ""},
    "stability":   {"name": "Stability AI",          "url": "https://platform.stability.ai/account/credits",   "env": "STABILITY_API_KEY",    "prefix": "sk-"},
    "replicate":   {"name": "Replicate",             "url": "https://replicate.com/account/api-tokens",        "env": "REPLICATE_API_TOKEN",  "prefix": "r8_"},
}

def load_all_keys():
    try:
        return json.loads(KEYS_FILE.read_text()) if KEYS_FILE.exists() else {}
    except Exception:
        return {}

def save_all_keys(keys):
    CONFIG_DIR.mkdir(exist_ok=True)
    KEYS_FILE.write_text(json.dumps(keys, indent=2))

def get_key(provider):
    info = SUPPORTED_PROVIDERS.get(provider, {})
    env  = info.get("env", "")
    if env and os.environ.get(env):
        return os.environ[env]
    keys = load_all_keys()
    return keys.get(provider)

def mask_key(key):
    if not key or len(key) < 8:
        return "***"
    return key[:8] + "·" * 6 + key[-4:]

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
    "/voice":          ("DEV",     "Speak last response (Windows TTS)"),
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
}


def cmd_local(state, model="llama3"):
    state["model"] = f"ollama/{model}"
    console.print(f"[green]✓ Switched to Local Ollama model: {model}[/green]")
    return state


# ── CONFIG ────────────────────────────────────────
def load_api_key(user_id="default"):
    """Load Gemini API key from profile directory."""
    k = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    path = Path("profiles") / user_id / "gemini_key"
    return k or (path.read_text().strip() if path.exists() else None)

def save_api_key(user_id_or_key, k=None):
    """Save Gemini API key to profile directory.

    Supports two call signatures:
      save_api_key(key)             -> saves under "default"
      save_api_key("user_id", key)  -> saves under the given user_id
    """
    if k is None:
        k = user_id_or_key
        user_id = "default"
    else:
        user_id = user_id_or_key
    path = Path("profiles") / user_id / "gemini_key"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(k.strip())

def load_or_key(user_id="default"):
    """Load OpenRouter API key from profile directory."""
    k = os.environ.get("OPENROUTER_API_KEY")
    path = Path("profiles") / user_id / "openrouter_key"
    return k or (path.read_text().strip() if path.exists() else None)

def save_or_key(user_id_or_key, k=None):
    """Save OpenRouter API key to profile directory.

    Supports two call signatures:
      save_or_key(key)             -> saves under "default"
      save_or_key("user_id", key)  -> saves under the given user_id
    """
    if k is None:
        k = user_id_or_key
        user_id = "default"
    else:
        user_id = user_id_or_key
    path = Path("profiles") / user_id / "openrouter_key"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(k.strip())

def load_hf_key():
    k = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
    return k or (HF_KEY_FILE.read_text().strip() if HF_KEY_FILE.exists() else None)

def save_hf_key(k):
    CONFIG_DIR.mkdir(exist_ok=True)
    HF_KEY_FILE.write_text(k.strip())


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
        img_model_key = parts[1].strip().split()[0]

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


def load_persona():
    return PERSONA_FILE.read_text().strip() if PERSONA_FILE.exists() else PERSONAS["default"]

def save_persona(t):
    CONFIG_DIR.mkdir(exist_ok=True); PERSONA_FILE.write_text(t.strip())

def load_memory():
    try:
        return json.loads(MEMORY_FILE.read_text()) if MEMORY_FILE.exists() else []
    except Exception:
        return []

def save_memory(mem):
    CONFIG_DIR.mkdir(exist_ok=True)
    MEMORY_FILE.write_text(json.dumps(mem, indent=2))

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
def call_gemini(api_key, model, history, prompt, system_prompt=None, _retry=0):
    url      = f"{API_BASE}/{model}:generateContent"
    contents = [{"role": m["role"], "parts":[{"text":m["text"]}]} for m in history]
    contents.append({"role":"user","parts":[{"text":prompt}]})
    body = {"contents": contents}
    if system_prompt:
        body["systemInstruction"] = {"parts":[{"text":system_prompt}]}
    payload = json.dumps(body).encode()
    req = request.Request(url, data=payload,
        headers={"Content-Type":"application/json","X-goog-api-key":api_key}, method="POST")
    try:
        with request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
        return data["candidates"][0]["content"]["parts"][0]["text"], None
    except urllib_error.HTTPError as e:
        body2 = e.read().decode()
        try: msg = json.loads(body2)["error"]["message"]
        except Exception: msg = body2
        if e.code in (401, 403):
            return None, f"Invalid or expired API key — run /setup to update it. ({msg})"
        if e.code in (429, 503) and _retry < 3:
            wait = 2 ** _retry
            console.print(f"[dim yellow]⏳ Rate limited — retrying in {wait}s ({_retry+1}/3)…[/dim yellow]")
            time.sleep(wait)
            return call_gemini(api_key, model, history, prompt, system_prompt, _retry + 1)
        return None, msg
    except Exception as e: return None, str(e)

# ── OPENROUTER REST ───────────────────────────────
def call_openrouter(api_key, model, history, prompt, system_prompt=None, _retry=0):
    messages = []
    if system_prompt: messages.append({"role":"system","content":system_prompt})
    for m in history:
        messages.append({"role":"assistant" if m["role"]=="model" else m["role"],"content":m["text"]})
    messages.append({"role":"user","content":prompt})
    payload = json.dumps({"model":model,"messages":messages}).encode()
    req = request.Request(OPENROUTER_BASE, data=payload, headers={
        "Content-Type":"application/json",
        "Authorization":f"Bearer {api_key}",
        "HTTP-Referer":"https://github.com/aistudio-cli",
        "X-Title":"AI Studio CLI"
    }, method="POST")
    try:
        with request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
        return data["choices"][0]["message"]["content"], None
    except urllib_error.HTTPError as e:
        body = e.read().decode()
        if e.code in (429, 503) and _retry < 3:
            wait = 2 ** _retry
            console.print(f"[dim yellow]⏳ Rate limited — retrying in {wait}s ({_retry+1}/3)…[/dim yellow]")
            time.sleep(wait)
            return call_openrouter(api_key, model, history, prompt, system_prompt, _retry + 1)
        try: msg = json.loads(body)["error"]["message"]
        except Exception: msg = body
        return None, msg
    except Exception as e: return None, str(e)


def call_openrouter_stream(api_key, model, history, prompt, system_prompt=None):
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    for m in history:
        messages.append({"role": "assistant" if m["role"] == "model" else m["role"], "content": m["text"]})
    messages.append({"role": "user", "content": prompt})
    payload = json.dumps({"model": model, "messages": messages, "stream": True}).encode()
    req = request.Request(
        OPENROUTER_BASE, data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://github.com/aistudio-cli",
            "X-Title": "AI Studio CLI",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=300) as resp:
            for raw in resp:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except Exception:
                    continue
                choice    = (obj.get("choices") or [{}])[0]
                delta_obj = choice.get("delta") or {}
                content   = delta_obj.get("content")
                reasoning = delta_obj.get("reasoning") or delta_obj.get("reasoning_content")
                if reasoning:
                    yield None, None, reasoning
                if content:
                    yield content, None, None
        yield None, None, None
    except urllib_error.HTTPError as e:
        body = e.read().decode()
        try:
            msg = json.loads(body).get("error", {}).get("message") or body
        except Exception:
            msg = body
        yield None, msg, None
    except Exception as e:
        yield None, str(e), None

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
            if not install_file.exists() or current_file.stat().st_mtime > install_file.stat().st_mtime:
                shutil.copy2(current_file, install_file)
                CONFIG_DIR.mkdir(exist_ok=True)
                DEV_PATH_FILE.write_text(str(current_file))
                return "pushed"
        else:
            # We are INSTALLED: Check if dev path exists and Pull
            if DEV_PATH_FILE.exists():
                dev_file = Path(DEV_PATH_FILE.read_text().strip())
                if dev_file.exists() and dev_file.stat().st_mtime > current_file.stat().st_mtime:
                    shutil.copy2(dev_file, current_file)
                    return "pulled"
    except Exception: pass
    return False

# ── RATE LIMITER & USAGE TRACKER ──────────────────
USAGE_FILE = CONFIG_DIR / "usage.json"

def load_usage():
    try:
        if USAGE_FILE.exists():
            data = json.loads(USAGE_FILE.read_text())
            # Clean up old entries (older than 5 hours)
            now = time.time()
            data["history"] = [entry for entry in data.get("history", []) if now - entry["ts"] < 18000]
            return data
    except Exception: pass
    return {"history": [], "total_in": 0, "total_out": 0}

def save_usage(usage):
    try:
        CONFIG_DIR.mkdir(exist_ok=True)
        USAGE_FILE.write_text(json.dumps(usage))
    except Exception: pass

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
    accent  = theme.get("accent", "bold cyan")
    short   = _short_model(state.get("model") or "")
    bolt    = "⚡ " if is_heavy else ""
    t_str   = f"{toks}t" if toks else ""
    mode    = state.get("_chat_mode", "")
    mode_tag = f" [{mode.upper()}]" if mode and mode != "normal" else ""

    # Pick the agent/persona label
    active_agent = state.get("active_agent")
    if active_agent and active_agent in AGENT_ROSTER:
        info    = AGENT_ROSTER[active_agent]
        label   = f"{info['emoji']} {info['name']}"
        color   = info.get("color", accent)
    else:
        label   = "●"
        color   = accent

    meta = f"[dim]{bolt}{short}  {t_str}{mode_tag}[/dim]" if short else ""

    if ui == "studio":
        return f"\n[{color}]{label}[/{color}]  {meta}\n"
    if ui == "claude":
        return f"\n[bold white]▸[/bold white] [{color}]{label}[/{color}]  {meta}\n"
    if ui == "codex":
        return f"\n[{color}]>[/{color}] [{color}]{label}[/{color}]  {meta}\n"
    if ui == "ghost":
        dim_l = "◌" if not active_agent else label
        ghost_meta = f"[dim]│[/dim] [dim white]{bolt}{short}  {t_str}{mode_tag}[/dim white]" if short else ""
        return f"\n[dim]│[/dim] [dim white]{dim_l}[/dim white]  {ghost_meta}\n"
    if ui == "nova":
        return f"\n[bold magenta]⚡[/bold magenta] [{color}]{label}[/{color}]  {meta}\n"
    if ui == "foxxia":
        return f"\n[bold yellow]🦊[/bold yellow] [{color}]{label}[/{color}]  {meta}\n"
    # gemini default
    return f"\n[{accent}]✦[/{accent}] [{color}]{label}[/{color}]  {meta}\n"

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
        f"{tree[:1500]}...",
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

            for chunk, chunk_err, reasoning in call_openrouter_stream(or_key, model, history, prompt, system_prompt):
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
                        # raw write so Rich markup inside reasoning isn't parsed
                        sys.stdout.write(f"\x1b[2;3m{reasoning}\x1b[0m")
                        sys.stdout.flush()
                # ── First content chunk → close thinking, print heading ────
                if chunk:
                    if not header_printed:
                        if think_open:
                            console.print()  # newline after live reasoning
                            console.print("[dim]◇ Done thinking.[/dim]")
                            think_open = False
                        console.print(_assistant_heading(state, "OR", is_heavy))
                        header_printed = True
                    _stream_print(chunk, stream_mode)
                    full_text.append(chunk)

            # Edge case: reasoning-only response with no content chunks
            if not header_printed:
                if think_open:
                    console.print()
                    console.print("[dim]◇ Done thinking.[/dim]")
                    think_open = False
                elif reasoning_buf and show_think:
                    # non-stream reasoning fallback (shouldn't happen, but keep safe)
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
            _start_think_anim("Thinking")
            text, err = call_openrouter(or_key, model, history, prompt, system_prompt)
            _stop_think_anim()

    elif state.get("cursor_key"):
        cx_key = state["cursor_key"]
        _start_think_anim("Thinking (Cursor)")
        text, err = call_cursor(cx_key, model, history, prompt, system_prompt)
        _stop_think_anim()

    elif gm_key:
        _start_think_anim("Thinking")
        text, err = call_gemini(gm_key, model, history, prompt, system_prompt)
        _stop_think_anim()

    elif state.get("use_cli"):
        _start_think_anim("Thinking (CLI)")
        text, err = call_gemini_cli(prompt, system_prompt)
        _stop_think_anim()

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
            _start_think_anim(f"Ollama ({ollama_model})")
            text, err = call_ollama(ollama_model, history, prompt, system_prompt, stream=False)
            _stop_think_anim()

    if text:
        # 2. Aggressive Cleaning
        clean_text = _clean_terminal_text(text)
        
        # 3. Real-time Accounting
        in_t = approx_tokens(prompt); out_t = approx_tokens(clean_text)
        track_usage(state, in_t, out_t, is_heavy=is_heavy)

        # 4. Display response
        if not silent:
            if not rendered:
                console.print(_assistant_heading(state, "AI", is_heavy, out_t))
                try:
                    console.print(Markdown(clean_text))
                    console.print("")
                except Exception:
                    from rich.padding import Padding
                    console.print(Padding(clean_text, (0, 0, 1, 4)))
            else:
                # For streamed output: print a closing newline
                console.print("")
            
            parse_and_execute_tools(state, text)

        history.append({"role":"user","text":prompt})
        history.append({"role":"model","text":clean_text})
        state["_last_response"] = clean_text
        state["_last_tokens"] = {"in": in_t, "out": out_t, "sec": round(time.time()-t0, 2)}
        return clean_text, history

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
            from_key = state.get("openrouter_key") or load_or_key()
            new_content, err = call_openrouter(
                from_key,
                state.get("model") or DEFAULT_MODEL,
                [], prompt, build_system_prompt(state)
            )
            _stop_think_anim()
            if not new_content:
                console.print(f"[red]Tool PATCH failed for '{path}': {err}[/red]")
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
        console.print(Panel(_clean_terminal_text(text),
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
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
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
    runners = {".py": ["python"], ".js": ["node"], ".ts": ["npx", "ts-node"], ".sh": ["bash"], ".bat": [str(p)]}
    runner  = runners.get(ext)
    if not runner: console.print(f"[yellow]Don't know how to run {ext} files[/yellow]"); return history
    console.print(f"[dim]Running {p}...[/dim]")
    cmd = runner if ext == ".bat" else runner + [str(p)]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
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

    console.print(Panel(
        f"[bold]Plan:[/bold]         [{plan['color']}]{plan['badge']} {plan['name']}[/{plan['color']}]  [dim]{plan['price']}[/dim]{trial_line}\n\n"
        f"[bold]Messages:[/bold]     {msg_bar}\n"
        f"[bold]Tokens in:[/bold]    {total_in:,}\n"
        f"[bold]Tokens out:[/bold]   {total_out:,}\n"
        f"[bold]Total tokens:[/bold] {total_in+total_out:,}\n"
        f"[bold]Last request:[/bold] {last_line}\n\n"
        f"[bold]Rate window:[/bold]  {rl_count} requests  [dim](free cap: 5/hr)[/dim]\n"
        f"[bold]Image quota:[/bold]  {plan['img_per_3h']}/3h\n"
        f"[bold]Model access:[/bold] {'all models' if plan['models'] is None else plan['models'][0].split('/')[1]}\n\n"
        f"  [dim]/trial pro   /upgrade pro   /plan   /usage[/dim]",
        title=f"[bold]Usage & Plan Limits[/bold]",
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
        console.print(f"[{theme['success']}]✓ Pulled update → current file.[/{theme['success']}]")
        ans = console.input("  [bold cyan]Restart now to apply? (y/n): [/bold cyan]").strip().lower()
        if ans == "y":
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

def cmd_voice(state):
    """Speak the last AI response (Windows only)."""
    if sys.platform != "win32":
        console.print("[yellow]Voice is only supported on Windows.[/yellow]")
        return
    text = state.get("_last_response", "")
    if not text: return
    # Clean for voice
    clean = re.sub(r"\[.*?\]", "", text).replace("\n", " ").strip()
    msg = clean[:500]
    console.print("[dim]Speaking...[/dim]")
    
    # Use Base64 encoded script block to prevent ANY injection
    import base64
    script = f'Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak({json.dumps(msg)})'
    encoded_script = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    cmd = f'PowerShell -NoProfile -EncodedCommand {encoded_script}'
    subprocess.Popen(cmd, shell=True)

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
        f"  [bold]Session Spend[/bold]    {'[green]$0.000000[/green]' if rate == 0 else f'[yellow]-${session_cost:.6f}[/yellow]'} [dim](estimated)[/dim]\n"
        f"  [bold]Lifetime Spend[/bold]   [{'green' if lifetime_spend == 0 else 'yellow'}]${lifetime_spend:.6f}[/{'green' if lifetime_spend == 0 else 'yellow'}] [dim](estimated)[/dim]\n"
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

def cmd_cost(state):
    """Show real cost of the last interaction based on active model's pricing."""
    lt = state.get("_last_tokens")
    if not lt: return
    model   = state.get("model") or DEFAULT_MODEL
    rate    = model_price_per_1k(model)
    total_t = lt["in"] + lt["out"]
    cost    = (total_t / 1000) * rate
    free_tag = " [dim](free tier — $0)[/dim]" if rate == 0.0 else f" [dim]@ ${rate:.5f}/1k[/dim]"
    console.print(
        f"[dim]Last turn:[/dim] [bold]{lt['in']}[/bold] in + [bold]{lt['out']}[/bold] out "
        f"= [bold]{total_t:,}[/bold] tokens  "
        f"[bold {'green' if rate == 0 else 'yellow'}]${cost:.6f}[/bold {'green' if rate == 0 else 'yellow'}]"
        f"{free_tag}"
    )


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
    if args.lower() in ("off", "0", "false", "stop"):
        state["autonomous"] = False
        console.print("[green]✓ Autonomous mode OFF — permission checks restored.[/green]")
        return history
    if args.lower() in ("on", "1", "true", "start") or not args:
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
    "6.1": [
        "Fixed: shell=True removed from cmd_run() — eliminates shell injection risk",
        "Fixed: call_gemini() now retries on 429/503 with exponential backoff (mirrors OpenRouter)",
        "Fixed: call_gemini() now shows actionable error message on 401/403 (invalid API key)",
        "Fixed: /tokens label standardized to 'Tokens' across all UI styles",
        "Fixed: detect_gemini_cli() and _make_toolbar already cached — confirmed no regression",
        "Fixed: install_windows.bat version comment bumped to v6.1",
    ],
    "6.0": [
        "New: Web interface (web/) — companion browser UI with SSE streaming, model picker, persona switcher",
        "New: Full project README with install, commands, agents, plans, providers",
        "Fixed: creator analytics access gate bypass via missing 'role' field",
        "Added: .gitignore — excludes node_modules/, __pycache__/, profiles/, logs/, secrets",
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
    ai_respond(state, prompt, history)
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
    """/test <file> — AI generates a test file for a source file."""
    if not args:
        console.print("[yellow]Usage: /test <file>[/yellow]")
        return history
    try:
        content, p = read_file_state(state, args)
    except Exception as e:
        console.print(f"[red]{e}[/red]")
        return history
    ext = p.suffix.lower()
    framework = "pytest" if ext == ".py" else "jest" if ext in (".js", ".ts", ".jsx", ".tsx") else "appropriate test framework"
    prompt = (
        f"Generate a complete {framework} test file for `{p.name}`.\n"
        "Cover: happy paths, edge cases, error conditions, boundary values.\n"
        "Write realistic test data. Keep tests isolated and deterministic.\n"
        "Return only the test file code — no explanation, no markdown fences.\n\n"
        f"SOURCE:\n{content}"
    )
    ai_respond(state, prompt, history)
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


VAULT_FILE = CONFIG_DIR / "vault.json"

def _vault_load():
    if not VAULT_FILE.exists(): return {}
    try:
        import base64
        raw = json.loads(VAULT_FILE.read_text(encoding="utf-8"))
        return {k: base64.b64decode(v).decode("utf-8") for k, v in raw.items()}
    except Exception:
        return {}

def _vault_save(data):
    import base64
    encoded = {k: base64.b64encode(v.encode("utf-8")).decode("utf-8") for k, v in data.items()}
    VAULT_FILE.parent.mkdir(exist_ok=True)
    VAULT_FILE.write_text(json.dumps(encoded, indent=2), encoding="utf-8")


def cmd_vault(state, args):
    """/vault — Local secrets store. /vault set KEY VALUE | /vault get KEY | /vault list | /vault delete KEY"""
    if not _require_pro(state, "/vault"): return
    theme  = state.get("theme", THEMES["default"])
    acc    = theme.get("accent", "cyan")
    console.print(
        "[yellow bold]⚠ Vault notice:[/yellow bold] [dim]secrets are "
        "[bold]base64-encoded (obfuscated)[/bold], not cryptographically encrypted. "
        "Do not store production credentials or sensitive tokens here.[/dim]"
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
        console.print(f"  [{acc}]✓ Vault: {key} saved[/{acc}]  [dim](base64-encoded at rest)[/dim]")

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

    else:
        console.print("[yellow]Usage: /team list|invite|remove|role[/yellow]")


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
  ✦ NEW: Agent Mesh — Autonomous specialist handoffs via [AGENT:id] tags
  ✦ NEW: Local Fusion — Ollama integration for local model fallback (/local)
  ✦ NEW: Live-Watcher (Live-FIF) — Background bug detection on file save
  ✦ NEW: Vision 2.0 — Deep visual reasoning and screenshot OCR integration
  ✦ NEW: Cursor API — Native support for Cursor's high-efficiency reasoning
  ✦ NEW: /arena — Side-by-side model and provider battles
  ✦ NEW: Streaming & Reasoning — Real-time token output with animated thinking
  ✦ NEW: Subscription Leaps — Team and Ultra plans with unlimited scale
  ✦ IMPROVED: Unified Permission System (Auto/YOLO/Bypass)
  ✦ IMPROVED: Platform-agnostic logs and sync directory structure

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
    
    # Reload log to include the new entry for the count
    try:
        updated_log = json.loads(path.read_text(encoding="utf-8"))
        count = len([e for e in updated_log if e.get('type')=='complaint'])
    except Exception: 
        count = 1

    console.print()
    if get_plan(state) in ["max", "pro"]:
        console.print("  [bold red]⚠  COMPLAINT RECEIVED (PRIORITY: HIGH)[/bold red]")
        time.sleep(0.25)
        console.print("  [dim]Logged. Our engineers are investigating your request immediately.[/dim]")
    else:
        roast = _r.choice(_COMPLAINT_ROASTS)
        console.print("  [red]⚠  COMPLAINT RECEIVED[/red]")
        time.sleep(0.25)
        console.print(f"  [dim]{roast}[/dim]")
    
    console.print(f"  [dim]Logged to logs/complaints.json[/dim]\n")
    console.print(f"\n  [dim]Entry #{count} in the archive.[/dim]\n")


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

def cmd_beta(state, args, history):
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
                    console.print(Padding(_clean_terminal_text(vision_text), (0, 0, 1, 4)))
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

    # ── Secret letter check for paid plans ───────────────────────────────────
    if plan in ("pro", "max", "ultra"):
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
    input("  [Enter to launch] ")
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
        if plan_id in ("max", "ultra", "enterprise", "team"):
            pro_tag = plan_cfg["name"].upper()
            banner_lines = [
                "  ╔══════════════════════════════════════════════════════╗",
                f"  ║    AI  STUDIO  CLI  —  v{VERSION}  Pro  ✦  {pro_tag:<10}  ║",
                "  ║    ──────────────────────────────────────────────    ║",
                f"  ║    {username:<20} · All models · Priority Queue  ║",
                "  ╚══════════════════════════════════════════════════════╝",
            ]
            _animate_banner(banner_lines, plan_cfg["color"])
        elif plan_id in ("pro", "dev", "starter"):
            banner_lines = [
                f"  ╔══════════════════════════════════════════╗",
                f"  ║   AI Studio CLI  v{VERSION}  ·  {plan_cfg['name']:<12}  ║",
                f"  ╚══════════════════════════════════════════╝",
            ]
            _animate_banner(banner_lines, plan_cfg["color"])
        else:
            console.print(f"\n  [{acc}]◆  AI Studio CLI  v{VERSION}[/{acc}]  {plan_badge}\n")

        body = (
            f"  [bold]◆ Model    [/bold]  [{theme['success']}]{short}[/{theme['success']}]"
            f"  [dim]via {mode_str}[/dim]\n"
            f"  [bold]◆ Dir      [/bold]  [cyan]{ws_short}[/cyan]  [dim]({perms})[/dim]\n"
            f"  [bold]◆ Stream   [/bold]  [dim]{stream_m}[/dim]\n"
            f"  [bold]◆ Messages [/bold]  [dim]{msg_str}[/dim]  "
            f"  [bold]◆ Sessions [/bold]  [dim]{sess_n}[/dim]\n\n"
            f"  [dim][{theme['warning']}]Agents[/{theme['warning']}]  "
            "berry  savannah  silicon  cockroach  lucifer  wizzard[/dim]\n"
            f"  [dim]/enter .   /models   /agent berry   /vibe   /help[/dim]"
        )
        console.print()
        console.print(Panel(
            body,
            title=f"[bold {border_c}]AI STUDIO CLI  v{VERSION}[/bold {border_c}]"
                  f"  [{plan_cfg['color']}]{plan_cfg['badge']} {plan_cfg['name']}[/{plan_cfg['color']}]",
            border_style=border_c,
            padding=(1, 1),
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
        nova_lines = [
            "  ╔══════════════════════════════════════════════════╗",
            "  ║  ⚡  N  O  V  A     S  T  U  D  I  O  ⚡  CLI  ║",
            f"  ║  {'─'*48}  ║",
            f"  ║   v{VERSION}                                          ║",
            "  ╚══════════════════════════════════════════════════╝",
        ]
        _animate_banner(nova_lines, "bold magenta", delay=0.035)
        console.print()
        info = (
            f"  [bold magenta]◆ Model[/bold magenta]    [cyan]{short}[/cyan]  [dim magenta]· {mode_str}[/dim magenta]\n"
            f"  [bold magenta]◆ Dir[/bold magenta]      [dim]{ws_short}[/dim]\n"
            f"  [bold magenta]◆ Plan[/bold magenta]     [{plan_cfg['color']}]{plan_cfg['badge']} {plan_cfg['name']}[/{plan_cfg['color']}]  "
            f"[dim]{msg_str} msgs[/dim]\n"
            f"  [bold magenta]◆ Stream[/bold magenta]   [dim]{stream_m}[/dim]\n"
        )
        console.print(Panel(
            info,
            border_style="magenta",
            padding=(0, 1),
        ))
        console.print(
            "  [dim magenta]/enter .   /models   /agent berry   /vibe   /arena   /help[/dim magenta]\n"
        )
        return

    # ── FOXXIA ──────────────────────────────────────────────────────────────
    if ui == "foxxia":
        foxxia_lines = [
            "  ╔══════════════════════════════════════════════════════╗",
            "  ║  🦊   F O X X I A   D E V   S T U D I O   v" + VERSION + "   ║",
            "  ║  ──────────────────────────────────────────────────  ║",
            f"  ║  by Foxxed909  ·  {plan_cfg['badge']} {plan_cfg['name']:<36}║",
            "  ╚══════════════════════════════════════════════════════╝",
        ]
        _animate_banner(foxxia_lines, "bold yellow", delay=0.035)
        console.print()
        info = (
            f"  [bold yellow]🦊 Model[/bold yellow]    {short}  [dim]· {mode_str}[/dim]\n"
            f"  [bold yellow]🦊 Dir[/bold yellow]      [dim]{ws_short}[/dim]\n"
            f"  [bold yellow]🦊 Plan[/bold yellow]     [{plan_cfg['color']}]{plan_cfg['badge']} {plan_cfg['name']}[/{plan_cfg['color']}]  "
            f"[dim]{msg_str} msgs  ·  session #{sess_n}[/dim]\n"
        )
        console.print(Panel(
            info,
            border_style="yellow",
            padding=(0, 1),
        ))
        console.print(
            "  [dim yellow]/enter .   /models   /agent berry   /vibe   /help[/dim yellow]\n"
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
    return HTML(f"<{pc}><b>{pname}</b></{pc}> <{ac}>›</{ac}> ")


_toolbar_disk_cache: dict = {"ts": 0.0, "mem_n": 0, "prof": None, "trial": None}
_TOOLBAR_TTL = 5.0  # seconds between disk reads

def _make_toolbar(state):
    """Returns a callable bottom-toolbar for prompt_toolkit."""
    def _toolbar():
        prov = ("CLI" if state.get("use_cli")
                else "OR" if (state.get("use_openrouter") or _is_openrouter_model(state.get("model",""))) and state.get("openrouter_key")
                else "Gem")
        model   = _short_model(state.get("model") or "?")
        stream  = state.get("stream_mode") or "auto"
        ui_n    = state.get("ui_style") or "gemini"
        # TTL-cached disk reads — avoid hitting disk on every keypress
        now = time.time()
        if now - _toolbar_disk_cache["ts"] >= _TOOLBAR_TTL:
            try:
                _toolbar_disk_cache["mem_n"] = len(load_memory())
            except Exception:
                _toolbar_disk_cache["mem_n"] = 0
            _toolbar_disk_cache["prof"]  = load_profile() or {}
            _toolbar_disk_cache["trial"] = load_trial()
            _toolbar_disk_cache["ts"]    = now
        mem_n = _toolbar_disk_cache["mem_n"]
        active    = state.get("active_agent") or ""
        chat_mode = state.get("_chat_mode", "")
        lt        = state.get("_last_tokens")
        tok_part  = f" · <b>{lt['out']}t</b> {lt['sec']}s" if lt else ""
        agent_part = f" · <b>🤖{active}</b>" if active else ""
        mode_part  = f" · <b>{chat_mode.upper()}</b>" if chat_mode and chat_mode != "normal" else ""
        cwd = Path.cwd().name[:16]
        # Plan + messages
        try:
            _pid     = get_plan(state)
            _pcfg    = PLANS.get(_pid, PLANS["free"])
            _prof    = _toolbar_disk_cache["prof"]
            _msgs    = _prof.get("session_msgs", 0)
            _mlimit  = _pcfg["msg_limit"]
            _trial   = _toolbar_disk_cache["trial"]
            if _trial:
                _rem = max(0, _trial["expires"] - time.time())
                _ph, _pr = divmod(int(_rem), 3600)
                plan_part = f" · <b>⚡trial</b> {_ph}h{_pr//60:02d}m"
            elif _mlimit >= 99999:
                plan_part = f" · {_pcfg['badge']}{_pcfg['name']}"
            else:
                plan_part = f" · {_pcfg['badge']} {_msgs}/{_mlimit}msg"
        except Exception:
            plan_part = ""
        return HTML(
            f' <b>◆ {prov}</b> · <b>{model}</b>'
            f' · {ui_n} · {stream} · mem:{mem_n} · 📁{cwd}'
            f'{plan_part}{tok_part}{mode_part}{agent_part} '
        )
    return _toolbar


def _prompt_box(theme, ui_style, state):
    """Multi-line boxed input prompt, styled per UI."""
    pname  = theme["prompt_name"]
    pc     = _ptk_style_token(theme["prompt_user"])
    ac     = _ptk_style_token(theme["prompt_arrow"])
    active = state.get("active_agent")
    label  = f"agent:{active}" if active else pname
    model_short = _short_model(state.get("model") or "")
    chat_mode   = state.get("_chat_mode", "")
    mode_tag    = f" [{chat_mode.upper()}]" if chat_mode and chat_mode != "normal" else ""
    v_tag  = f"v{VERSION}"

    if ui_style == "studio":
        fill  = max(2, 52 - len(label) - len(model_short) - len(mode_tag))
        top   = f" ╔═ {label}{mode_tag} {'═'*fill} {model_short} ═╗\n"
        mid   = " ║ "
        arrow = "◆ "
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
        fill = max(2, 48 - len(label) - len(model_short) - len(mode_tag))
        top  = f" ╔═ 🦊 {label}{mode_tag} {'─'*fill} {model_short} ═╗\n"
        mid  = " ║ "
        return FormattedText([
            (f"fg:{pc}", top),
            (f"fg:{pc}", mid),
            (f"fg:{ac} bold", "🦊 "),
        ])
    else:
        fill   = max(2, 55 - len(label) - len(model_short))
        top    = f" ╭─ {label} ─{'─'*fill} {model_short} ─╮\n"
        mid    = " │ "
        v_fill = max(2, 58 - len(v_tag))
        bot    = f"\n ╰{'─'*v_fill} {v_tag} ─╯"
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
            (f"fg:{pc}", bot),
        ])


def _sync_state_to_agent(global_state, agent_obj):
    for k in (
        "api_key","openrouter_key","model","use_cli","use_openrouter",
        "theme","theme_name","ui_style","stream_mode",
        "workspace_root","permissions_mode","project_ctx",
    ):
        if k in global_state:
            agent_obj.state[k] = global_state[k]


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

    # Reload after onboarding changes
    theme, theme_name = load_theme()
    state["theme"]            = theme
    state["theme_name"]       = theme_name
    state["ui_style"]         = state.get("ui_style")         or load_ui_style()
    state["stream_mode"]      = state.get("stream_mode")      or load_stream_mode()
    state["workspace_root"]   = state.get("workspace_root")   or load_workspace_root()
    state["permissions_mode"] = state.get("permissions_mode") or load_permissions_mode()

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
                        display = HTML(
                            f'<style fg="#5f5fff">[{cat:^5}]</style> '
                            f'<style fg="#ffffff">{cmd}</style> '
                            f'<style fg="#888888"> — {desc}</style>'
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
            if not user_input: continue

            if user_input.startswith("/"):
                parts = user_input[1:].split(" ", 1)
                cmd   = parts[0].lower()
                args  = parts[1].strip() if len(parts) > 1 else ""

                if cmd in ("exit","quit","q"):
                    _watch_stop.set()
                    console.print("[bold cyan]✦ Stay creative. Later! ✦[/bold cyan]"); break

                elif cmd == "help":    console.print(HELP_TEXT)
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

                elif cmd in ("shortcuts", "keys", "kb") and not args:
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
                elif cmd == "voice":          cmd_voice(state)
                elif cmd == "export":         cmd_export(state, history)
                elif cmd == "balance":        cmd_balance(state)
                elif cmd == "cost":           cmd_cost(state)
                elif cmd == "lint":           cmd_lint(state, args)
                elif cmd == "fif":            history = cmd_fif(state, args, history)
                elif cmd == "snippet":        cmd_snippet(state, args)
                elif cmd == "translate":      history = cmd_translate(state, args, history) if args else (console.print("[yellow]Usage: /translate <lang> [text][/yellow]"), history)[1]
                elif cmd == "changelog":      cmd_changelog(state)
                elif cmd in ("remote-control","remote","rc"): history = cmd_remote_control(state, args, history)
                elif cmd == "profile-card":   cmd_profile_card(state)
                elif cmd == "mode":           state = cmd_chat_mode(state, args)
                elif cmd == "sidebar":        cmd_sidebar(state)
                elif cmd == "thinking":
                    state["show_thinking"] = not state.get("show_thinking", True)
                    console.print(f"[green]✓ Internal Reasoning → {'ON' if state['show_thinking'] else 'OFF'}[/green]")
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
                elif cmd == "beta":           history = cmd_beta(state, args, history)
                elif cmd == "usage":          cmd_usage(state)
                elif cmd == "trial":          state = cmd_trial(state, args)
                elif cmd in ("update", "studio-update"): cmd_studio_update(state)

                # ── New commands ──────────────────────────────────────────────
                elif cmd == "diffpatch":   history = cmd_diffpatch(state, args, history) if args else (console.print("[yellow]Usage: /diffpatch <file> [instruction][/yellow]"), history)[1]
                elif cmd == "format":      cmd_format(state, args) if args else console.print("[yellow]Usage: /format <file>[/yellow]")
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
                elif cmd in ("free-tips","tips"): cmd_free_tips(state)

                # ── v5.6 new commands ─────────────────────────────────────────
                elif cmd == "summarize":  history = cmd_summarize(state, history)
                elif cmd == "autonomous": history = cmd_autonomous(state, args, history); _patch_autonomous_writes(state)
                elif cmd in ("creator","creator-analytics","analytics"): cmd_creator_analytics(state)

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

                # ── v5.9 Max / Team / Enterprise ──────────────────────────────
                elif cmd in ("audit-log", "auditlog"):   cmd_audit_log(state, args)
                elif cmd in ("priority-queue", "priorityqueue", "priority"): cmd_priority_queue(state, args)
                elif cmd in ("orgmetrics", "orgstats", "org"): cmd_orgmetrics(state, args)
                elif cmd == "sso":                       cmd_sso(state, args)
                elif cmd == "policy":                    cmd_policy(state, args)

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
                        tmp_ctx = state.pop("_one_shot_ctx", None)
                        if isinstance(tmp_ctx, dict) and "error" not in tmp_ctx:
                            prompt     = format_project_context(tmp_ctx, max_files=8) + "\n\n---\n\nQuestion: " + user_input
                            _, history = ai_respond(state, prompt, history)
                        else:
                            _, history = ai_respond(state, user_input, history)

        except KeyboardInterrupt: console.print("\n[dim]Ctrl+C — /exit to quit[/dim]")
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
        description="AI Studio CLI v5.8 — Advanced AI Terminal Interface",
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

    run_repl(state)


# ═══════════════════════════════════════════════════════════
# AGENT SYSTEM + PROJECT SCANNER
# ═══════════════════════════════════════════════════════════

SKIP_DIRS = {".git","node_modules","__pycache__","dist","build",".next",
             "venv",".venv","env","coverage",".cache","tmp","temp"}
CODE_EXTS  = {".py",".js",".ts",".jsx",".tsx",".vue",".html",".css",".scss",
              ".json",".yaml",".yml",".toml",".sh",".bat",".ps1",
              ".md",".txt",".sql",".go",".rs",".cpp",".c",".h"}
MAX_FILE_CHARS  = 8000
MAX_TOTAL_CHARS = 60000

AGENT_ROSTER = {
    "lucifer":      {"name":"LUCIFER",      "emoji":"🔥","color":"bold red",           "role":"Lead Architect",      "specialties":["architecture","planning","system","design","decisions"],          "persona":"You are LUCIFER — lead architect. See the full system, design schemas, plan architecture. Direct, bold, precise. No fluff."},
    "blackcanary":  {"name":"BlackCanary",  "emoji":"🐦","color":"bold magenta",        "role":"Frontend Queen",      "specialties":["html","css","react","ui","ux","frontend","design","animation"],   "persona":"You are BlackCanary — UI/UX goddess. Glassmorphism, animations, pixel-perfect. You roast ugly code. Write beautiful HTML/CSS/React."},
    "blacklord":    {"name":"BlackLord",    "emoji":"👁️","color":"bold blue",           "role":"Backend Beast",       "specialties":["api","database","backend","server","auth","python","node","sql"], "persona":"You are BlackLord — APIs, databases, auth, servers. Production code only. No demos, no placeholders."},
    "deathohmyson": {"name":"DeathOfMySon","emoji":"💀","color":"bold white",           "role":"QA & Debugger",       "specialties":["debug","bug","test","error","fix","review","security","qa"],      "persona":"You are DeathOfMySon — zero tolerance for bugs. Find every error, race condition, security hole. Show exact line, exact fix."},
    "wizzard":      {"name":"Wizzard",      "emoji":"🧙","color":"bold cyan",           "role":"AI/ML Sorcerer",      "specialties":["ai","ml","prompt","model","llm","integration","magic","automate"],"persona":"You are WIZZARD — master of AI sorcery. Prompt engineering, model integration, agentic workflows. You speak in incantations that actually compile. Every answer is a spell that works. Experimental, creative, always shipping."},
    "applaude":     {"name":"Applaude",     "emoji":"✨","color":"bold yellow",          "role":"Deploy & DevOps",     "specialties":["deploy","docker","ci","cd","vercel","config","env","pipeline"],   "persona":"You are Applaude — CI/CD, deployments, infrastructure. Methodical, thorough. When you ship it, it stays shipped."},
    "ghost":        {"name":"Ghost",        "emoji":"👻","color":"bold white",           "role":"Security Expert",     "specialties":["security","auth","xss","injection","vulnerability","exploit"],    "persona":"You are Ghost — find vulnerabilities before attackers do. Think like an attacker, fix like a defender."},
    "nova":         {"name":"Nova",         "emoji":"⚡","color":"bold bright_yellow",   "role":"Performance",         "specialties":["performance","optimize","speed","cache","memory","benchmark"],    "persona":"You are Nova — speed is everything. Optimize, benchmark, profile. You see O(n²) from a mile away."},
    "berry":        {"name":"Berry",        "emoji":"🫐","color":"bold magenta",         "role":"General Assistant",   "specialties":["chat","help","explain","general","write","create","idea"],       "persona": PERSONAS["berry"]},
    "savannah":     {"name":"Savannah",     "emoji":"🌿","color":"bold green",           "role":"Unfiltered Advisor",  "specialties":["honest","direct","unfiltered","opinion","debate","truth"],       "persona": PERSONAS["savannah"]},
    "cockroach":    {"name":"Cockroach",    "emoji":"🪳","color":"bold yellow",          "role":"Code Roaster",        "specialties":["roast","review","critique","bad code","jokes","burn","quality"],  "persona": PERSONAS["cockroach"]},
    "silicon":      {"name":"Silicon",      "emoji":"🔬","color":"bold red",             "role":"Hacker & Pentester",  "specialties":["pentest","exploit","vulnerability","hack","security","ctf","cve","reverse","recon"],"persona": PERSONAS["silicon"]},
}


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


OLLAMA_BASE     = "http://localhost:11434/api/chat"
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
