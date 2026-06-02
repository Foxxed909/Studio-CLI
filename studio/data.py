"""
All static data for StudioCLI — plans, themes, personas, models, agents, modes.
No I/O, no side-effects; pure data and tiny pure functions only.
"""
import re

VERSION          = "9.8"
API_BASE         = "https://generativelanguage.googleapis.com/v1beta/models"
OPENROUTER_BASE  = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL    = "nvidia/nemotron-3-super-120b-a12b:free"
CURSOR_BASE      = "https://api.cursor.com/aiserver.v1.AiService/StreamChat"
CURSOR_RUNS_BASE = "https://api.cursor.com/v1"
OLLAMA_BASE      = "http://localhost:11434/api/chat"

MAX_FREE_UPGRADE_SLOTS = 2
SLOT_GATED_PLANS       = ("starter", "pro", "max")

# ── PLANS ─────────────────────────────────────────────────────────────────────
PLANS = {
    "free": {
        "name":        "Free",
        "tier":        "v8+",
        "price":       "$0 / mo",
        "msg_limit":   10,
        "img_per_3h":  1,
        "credits":     100,
        "models":      ["nvidia/nemotron-3-super-120b-a12b:free"],
        "color":       "dim",
        "badge":       "○",
        "web_search":  False,
        "deep_research": False,
        "turbo":       False,
        "computer_use": False,
        "live_code":   False,
        "features":    ["10 messages / session", "1 image / 3 hrs", "Nemotron only", "v8+ features", "100 credits/mo"],
        "limitations": ["No model switching", "No premium agents", "No /arena", "No /beta", "No web search", "Max tier: v8+"],
    },
    "pro": {
        "name":        "Pro",
        "tier":        "v9",
        "price":       "$18 / mo",
        "msg_limit":   500,
        "img_per_3h":  10,
        "credits":     5000,
        "models":      None,
        "color":       "cyan",
        "badge":       "◆",
        "web_search":  True,
        "deep_research": True,
        "turbo":       True,
        "computer_use": False,
        "live_code":   True,
        "features":    ["500 messages / session", "10 images / 3 hrs", "All models", "All agents", "Web Search", "Deep Research", "Turbo Mode", "Live Code Preview", "v9 features", "5,000 credits/mo"],
        "limitations": ["No Computer Use", "No Chrome Extension"],
    },
    "max": {
        "name":        "Max",
        "tier":        "v9+",
        "price":       "$80 / mo",
        "msg_limit":   5000,
        "img_per_3h":  100,
        "credits":     50000,
        "models":      None,
        "color":       "magenta",
        "badge":       "◈",
        "web_search":  True,
        "deep_research": True,
        "turbo":       True,
        "computer_use": True,
        "live_code":   True,
        "features":    ["5,000 messages / session", "100 images / 3 hrs", "Cursor API", "Surgical Patching", "Computer Use", "Chrome Extension", "Deep Research", "Turbo Mode", "v9+ features", "50,000 credits/mo"],
        "limitations": [],
    },
    "ultra": {
        "name":        "Ultra",
        "tier":        "v9 Beta",
        "price":       "$250 / mo",
        "msg_limit":   999999,
        "img_per_3h":  999,
        "credits":     999999,
        "models":      None,
        "color":       "bold yellow",
        "badge":       "★",
        "web_search":  True,
        "deep_research": True,
        "turbo":       True,
        "computer_use": True,
        "live_code":   True,
        "features":    ["Unlimited usage", "Infinite images", "Real-time streaming", "Max Effort Mode", "Computer Use", "Chrome Extension", "v9 Beta features", "Early access to v10", "Unlimited credits"],
        "limitations": [],
    },
    "starter": {
        "name":        "Starter",
        "price":       "$5 / mo",
        "msg_limit":   100,
        "img_per_3h":  3,
        "credits":     1000,
        "models":      None,
        "color":       "green",
        "badge":       "◇",
        "web_search":  False,
        "deep_research": False,
        "turbo":       False,
        "computer_use": False,
        "live_code":   False,
        "features":    ["100 msgs/session", "3 images/3h", "All models", "Basic agents", "1,000 credits/mo"],
        "limitations": ["No /arena", "No /beta", "No web search", "No turbo"],
    },
    "dev": {
        "name":        "Dev",
        "price":       "$35 / mo",
        "msg_limit":   2000,
        "img_per_3h":  50,
        "credits":     15000,
        "models":      None,
        "color":       "bold cyan",
        "badge":       "⬡",
        "web_search":  True,
        "deep_research": True,
        "turbo":       True,
        "computer_use": False,
        "live_code":   True,
        "features":    ["2,000 msgs/session", "50 images/3h", "All models", "/arena", "Web Search", "Turbo Mode", "Live Code", "Cursor API", "15,000 credits/mo"],
        "limitations": ["No Computer Use"],
    },
    "team": {
        "name":        "Team",
        "price":       "$400 / mo",
        "msg_limit":   999999,
        "img_per_3h":  999,
        "credits":     999999,
        "models":      None,
        "color":       "bold green",
        "badge":       "👥",
        "web_search":  True,
        "deep_research": True,
        "turbo":       True,
        "computer_use": True,
        "live_code":   True,
        "features":    ["Shared Workspaces", "Team Agent Squads", "Admin Analytics", "Collaborative /arena", "Computer Use", "Chrome Extension", "Priority Support", "/orgmetrics", "Unlimited credits"],
        "limitations": [],
    },
    "enterprise": {
        "name":        "Enterprise",
        "price":       "Custom",
        "msg_limit":   999999,
        "img_per_3h":  9999,
        "credits":     999999,
        "models":      None,
        "color":       "bold white",
        "badge":       "◉",
        "web_search":  True,
        "deep_research": True,
        "turbo":       True,
        "computer_use": True,
        "live_code":   True,
        "features":    ["Unlimited", "Custom agents", "SSO/SAML (/sso)", "Dedicated support", "SLA", "/policy", "/orgmetrics", "Unlimited credits"],
        "limitations": [],
    },
}

# ── CREDIT COSTS ──────────────────────────────────────────────────────────────
CREDIT_COSTS = {
    "message":       1,
    "fast_message":  2.5,
    "turbo_message": 2.5,
    "image":         10,
    "web_search":    2,
    "deep_research": 15,
    "computer_use":  25,
}

# ── PLAN UPDATES (version-gated changelogs) ───────────────────────────────────
PLAN_UPDATES = {
    "9.7": {
        "date":    "2026-05-31",
        "plans":   ["free", "starter", "pro", "dev", "max", "ultra", "team", "enterprise"],
        "changes": [
            "16 new themes across 4 families: Cosmic II, Weather, Nature, Retro/Synth",
            "Speak: /tts and /voice are now one command — /speak (say) + /speak listen",
            "Git/VCS commands: /commit /stage /stash /blame /pr",
            "New helpers: /map (repo map) /scratch /ascii /banner /confetti /matrix /fortune",
            "Studio Lab is now internal-testers only (email allowlist or access code)",
            "Coming soon: MCP Connectors, /init project memory, Checkpoints, Local models",
        ],
    },
    "9.3": {
        "date":    "2026-05-16",
        "plans":   ["pro", "max", "ultra", "dev", "team", "enterprise"],
        "changes": [
            "Web Search mode (/search, /websearch)",
            "Deep Research mode (/research)",
            "2x Turbo Mode (/turbo) — 2.5x credit cost",
            "Credits system with monthly quotas",
            "Live Code Preview in Web UI",
            "Computer Use (max+ plans)",
            "Chrome Extension (max+ plans)",
            "Streaming responses now render as clean Markdown",
            "Plan update notifications on login",
        ],
    },
    "9.2": {
        "date":    "2026-05-15",
        "plans":   ["max", "ultra", "dev", "team", "enterprise"],
        "changes": [
            "/fast mode — concise ≤80-word replies",
            "/thinking <time> — set AI reasoning budget",
            "/time <deadline> — session deadline timer",
            "/statusline — configure toolbar fields",
        ],
    },
    "9.1": {
        "date":    "2026-05-10",
        "plans":   ["pro", "max", "ultra", "dev", "team", "enterprise"],
        "changes": [
            "Web UI light/dark theme toggle",
            "AI Persona improvements",
            "Streaming response stability fixes",
        ],
    },
}

# ── TURBO MODELS (fastest available) ─────────────────────────────────────────
TURBO_MODELS = [
    "openai/gpt-4o-mini",
    "google/gemini-flash-1.5",
    "meta-llama/llama-3.1-8b-instruct:free",
    "anthropic/claude-haiku-4-5-20251001",
]

# ── WEB SEARCH MODELS (perplexity sonar family) ───────────────────────────────
WEB_SEARCH_MODELS = {
    "default":       "perplexity/sonar",
    "deep":          "perplexity/sonar-pro",
    "fast":          "perplexity/sonar-small-online",
}

_STATUSLINE_DEFAULTS_LAZY = {"model", "plan", "stream", "branch", "tokens", "timer", "mode", "agent", "fast"}

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

MODEL_PRICING: dict[str, float] = {
    "nvidia/nemotron-3-super-120b-a12b:free":                       0.0,
    "openai/gpt-oss-120b:free":                                     0.0,
    "openai/gpt-oss-20b:free":                                      0.0,
    "nousresearch/hermes-3-llama-3.1-405b:free":                    0.0,
    "cognitivecomputations/dolphin-mistral-24b-venice-edition:free": 0.0,
    "meta-llama/llama-3.3-70b-instruct:free":                       0.0,
    "meta-llama/llama-3.2-3b-instruct:free":                        0.0,
    "google/gemma-3-27b-it:free":                                   0.0,
    "google/gemma-3-12b-it:free":                                   0.0,
    "qwen/qwen3-coder:free":                                        0.0,
    "gemini-2.5-flash":                                             0.000375,
    "gemini-2.5-pro":                                               0.00625,
    "gemini-2.0-flash":                                             0.000188,
    "gemini-1.5-pro":                                               0.00313,
    "gemini-1.5-flash":                                             0.000094,
    "openai/gpt-4o":                                                0.00375,
    "openai/gpt-4o-mini":                                           0.000225,
    "anthropic/claude-sonnet-4-5":                                  0.0045,
    "anthropic/claude-opus-4-5":                                    0.0225,
    "meta-llama/llama-3.1-405b-instruct":                           0.002,
    "google/gemini-2.5-pro":                                        0.00625,
    "mistralai/mistral-large":                                      0.003,
    "qwen/qwen-2.5-72b-instruct":                                   0.0009,
}
DEFAULT_PRICE_PER_1K = 0.002

def model_price_per_1k(model: str) -> float:
    if not model:
        return DEFAULT_PRICE_PER_1K
    if model in MODEL_PRICING:
        return MODEL_PRICING[model]
    if model.endswith(":free"):
        return 0.0
    if model.startswith("ollama/") or model.startswith("gemini-"):
        return MODEL_PRICING.get(model, 0.0)
    return DEFAULT_PRICE_PER_1K

def _is_openrouter_model(model):
    return bool(model and "/" in model and not model.startswith("gemini-"))

# ── PERSONAS ──────────────────────────────────────────────────────────────────
STUDIO_CONTEXT = "You are an AI assistant operating within StudioCLI — a high-performance terminal and web interface for developers. You have deep awareness of the Studio environment. "

PERSONAS = {
    "default":   STUDIO_CONTEXT + "You are a helpful, smart assistant. Be concise and friendly.",
    "coder":     STUDIO_CONTEXT + "You are an expert software engineer. Write clean, production-ready code. Be brief but thorough.",
    "tutor":     STUDIO_CONTEXT + "You are a patient teacher. Break things down step by step with examples.",
    "senior":    STUDIO_CONTEXT + "You are a senior software architect with 20 years experience. Give brutally honest, precise technical feedback.",
    "hacker":    STUDIO_CONTEXT + "You are a creative problem solver. Suggest unconventional approaches. Be enthusiastic.",
    "docs":      STUDIO_CONTEXT + "You are a technical writer. Produce clear, structured documentation with headers and examples.",
    "git":       STUDIO_CONTEXT + "You are a Git expert. Help with git commands, workflows, commit messages, and branch strategies.",
    "berry": (
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

# ── THEMES ────────────────────────────────────────────────────────────────────
THEMES = {
    "default":   {"name":"Studio",        "banner_color":"#5eead4",            "accent":"#22d3ee",           "prompt_user":"#5eead4",       "prompt_arrow":"#22d3ee",           "border":"#5eead4",     "success":"#4ade80",      "error":"#f87171", "warning":"#fb923c","dim":"dim", "banner_sub":"#22d3ee",          "icon":"✦",   "prompt_name":"studio"},
    "fire":      {"name":"Fire 🔥",        "banner_color":"bold red",          "accent":"bold yellow",       "prompt_user":"ansired",       "prompt_arrow":"ansiyellow",        "border":"red",         "success":"yellow",       "error":"bright_red","warning":"yellow","dim":"dim", "banner_sub":"bold yellow",      "icon":"🔥",  "prompt_name":"fire"},
    "matrix":    {"name":"Matrix 🟩",      "banner_color":"bold green",        "accent":"bold bright_green", "prompt_user":"ansigreen",     "prompt_arrow":"ansibrightgreen",   "border":"green",       "success":"bright_green", "error":"red",     "warning":"yellow", "dim":"dim", "banner_sub":"bold green",       "icon":"▶",   "prompt_name":"matrix"},
    "sakura":    {"name":"Sakura 🌸",      "banner_color":"bold magenta",      "accent":"bold #ffb6c1",      "prompt_user":"ansimagenta",   "prompt_arrow":"ansibrightmagenta", "border":"magenta",     "success":"green",        "error":"red",     "warning":"yellow", "dim":"dim", "banner_sub":"bold magenta",     "icon":"🌸",  "prompt_name":"sakura"},
    "ocean":     {"name":"Ocean 🌊",       "banner_color":"bold blue",         "accent":"bold cyan",         "prompt_user":"ansiblue",      "prompt_arrow":"ansicyan",          "border":"blue",        "success":"cyan",         "error":"red",     "warning":"yellow", "dim":"dim", "banner_sub":"bold cyan",        "icon":"🌊",  "prompt_name":"ocean"},
    "gold":      {"name":"Gold ✨",        "banner_color":"bold yellow",       "accent":"bold yellow",       "prompt_user":"ansiyellow",    "prompt_arrow":"ansiwhite",         "border":"yellow",      "success":"green",        "error":"red",     "warning":"ansiyellow","dim":"dim","banner_sub":"bold yellow",     "icon":"✨",  "prompt_name":"gold"},
    "midnight":  {"name":"Midnight 🌙",    "banner_color":"bold white",        "accent":"bold bright_white", "prompt_user":"ansiwhite",     "prompt_arrow":"ansiwhite",         "border":"white",       "success":"green",        "error":"red",     "warning":"yellow", "dim":"dim", "banner_sub":"bold white",       "icon":"🌙",  "prompt_name":"midnight"},
    "hacker":    {"name":"Hacker 💀",      "banner_color":"bold bright_green", "accent":"bold bright_green", "prompt_user":"ansigreen",     "prompt_arrow":"ansibrightgreen",   "border":"bright_green","success":"bright_green", "error":"red",     "warning":"yellow", "dim":"dim", "banner_sub":"bold bright_green","icon":"💀",  "prompt_name":"h4ck3r"},
    "neon":      {"name":"Neon 🌆",        "banner_color":"bold magenta",      "accent":"bold cyan",         "prompt_user":"ansimagenta",   "prompt_arrow":"ansicyan",          "border":"magenta",     "success":"cyan",         "error":"red",     "warning":"yellow", "dim":"dim", "banner_sub":"bold cyan",        "icon":"🌆",  "prompt_name":"neon"},
    "dracula":   {"name":"Dracula 🧛",     "banner_color":"bold magenta",      "accent":"bold cyan",         "prompt_user":"ansimagenta",   "prompt_arrow":"ansibrightmagenta", "border":"magenta",     "success":"ansigreen",    "error":"ansired", "warning":"ansiyellow","dim":"dim","banner_sub":"bold magenta",    "icon":"🧛",  "prompt_name":"dracula"},
    "nord":      {"name":"Nord ❄️",        "banner_color":"bold blue",         "accent":"bold cyan",         "prompt_user":"ansiblue",      "prompt_arrow":"ansicyan",          "border":"blue",        "success":"cyan",         "error":"red",     "warning":"yellow", "dim":"dim", "banner_sub":"bold cyan",        "icon":"❄️",  "prompt_name":"nord"},
    "synthwave": {"name":"Synthwave 🌅",   "banner_color":"bold magenta",      "accent":"bold yellow",       "prompt_user":"ansimagenta",   "prompt_arrow":"ansiyellow",        "border":"magenta",     "success":"yellow",       "error":"red",     "warning":"ansired","dim":"dim",  "banner_sub":"bold yellow",      "icon":"🌅",  "prompt_name":"wave"},
    "void":      {"name":"Void ◈",         "banner_color":"bold white",        "accent":"bold bright_white", "prompt_user":"ansiwhite",     "prompt_arrow":"ansiwhite",         "border":"bright_white","success":"bright_white", "error":"bold red","warning":"bold yellow","dim":"dim","banner_sub":"white",          "icon":"◈",   "prompt_name":"void"},
    "aurora":    {"name":"Aurora 🌌",      "banner_color":"bold bright_green", "accent":"bold cyan",         "prompt_user":"ansigreen",     "prompt_arrow":"ansicyan",          "border":"green",       "success":"bright_green", "error":"bold red","warning":"yellow", "dim":"dim", "banner_sub":"bold cyan",        "icon":"🌌",  "prompt_name":"aurora"},
    "ember":     {"name":"Ember 🔶",       "banner_color":"bold yellow",       "accent":"bold red",          "prompt_user":"ansiyellow",    "prompt_arrow":"ansired",           "border":"yellow",      "success":"bright_yellow","error":"bold red","warning":"yellow", "dim":"dim", "banner_sub":"bold red",         "icon":"🔶",  "prompt_name":"ember"},
    "nova":      {"name":"Nova ⚡",        "banner_color":"bold magenta",      "accent":"bold cyan",         "prompt_user":"ansimagenta",   "prompt_arrow":"ansicyan",          "border":"magenta",     "success":"cyan",         "error":"bold red","warning":"bold yellow","dim":"dim","banner_sub":"bold cyan",        "icon":"⚡",  "prompt_name":"nova"},
    "foxxia":    {"name":"Foxxia 🦊",      "banner_color":"bold #f97316",      "accent":"#fbbf24",           "prompt_user":"#f97316",       "prompt_arrow":"#fbbf24",           "border":"#f97316",     "success":"#fbbf24",      "error":"bold red","warning":"#f59e0b","dim":"dim", "banner_sub":"#fbbf24",          "icon":"🦊",  "prompt_name":"foxxia"},
    "strawberry":{"name":"Strawberry 🍓", "banner_color":"bold #e11d48",      "accent":"#fb7185",           "prompt_user":"#e11d48",       "prompt_arrow":"#fb7185",           "border":"#e11d48",     "success":"#4ade80",      "error":"bold red","warning":"#fbbf24","dim":"dim", "banner_sub":"#fb7185",          "icon":"🍓",  "prompt_name":"strawberry"},
    "cobalt":    {"name":"cobalt",          "banner_color":"bold cyan",         "accent":"bold blue",         "prompt_user":"ansiblue",      "prompt_arrow":"ansicyan",          "border":"cyan",        "success":"cyan",         "error":"bold red","warning":"yellow", "dim":"dim", "banner_sub":"bold cyan",        "icon":"🔷",  "prompt_name":"cobalt"},
    "carbon":    {"name":"carbon",          "banner_color":"bold white",        "accent":"bold white",        "prompt_user":"ansiwhite",     "prompt_arrow":"ansigray",          "border":"white",       "success":"white",        "error":"bold red","warning":"bold yellow","dim":"dim","banner_sub":"white",          "icon":"⬛",  "prompt_name":"carbon"},
    "crimson":   {"name":"crimson",         "banner_color":"bold red",          "accent":"bold magenta",      "prompt_user":"ansired",       "prompt_arrow":"ansimagenta",       "border":"red",         "success":"magenta",      "error":"bold red","warning":"yellow", "dim":"dim", "banner_sub":"bold red",         "icon":"🔴",  "prompt_name":"crimson"},
    "slate":     {"name":"slate",           "banner_color":"bold bright_blue",  "accent":"bold blue",         "prompt_user":"ansiblue",      "prompt_arrow":"ansibrightblue",    "border":"bright_blue", "success":"bright_blue",  "error":"red",     "warning":"yellow", "dim":"dim", "banner_sub":"bright_blue",      "icon":"🌐",  "prompt_name":"slate"},
    "rain":        {"name":"Rain ░",                  "banner_color":"bold #00FF41",  "accent":"bold #00FF41",  "prompt_user":"ansigreen",  "prompt_arrow":"ansicyan",        "border":"#00FF41",   "success":"#00FFFF",  "error":"bold red","warning":"yellow", "dim":"dim", "banner_sub":"bold #00FFFF","icon":"░",  "prompt_name":"rain"},
    "darkred":     {"name":"Dark Red 🩸",             "banner_color":"bold #dc143c",  "accent":"#dc143c",       "prompt_user":"#dc143c",     "prompt_arrow":"#8b0000",         "border":"#8b0000",   "success":"#dc143c",  "error":"bold red","warning":"#ff6b6b","dim":"dim",  "banner_sub":"#8b0000",     "icon":"🩸", "prompt_name":"darkred"},
    "sophia":      {"name":"Sophisticated Sophia 💜", "banner_color":"bold #c084fc",  "accent":"#c084fc",       "prompt_user":"#c084fc",     "prompt_arrow":"#a855f7",         "border":"#6b21a8",   "success":"#c084fc",  "error":"bold red","warning":"#f0abfc","dim":"dim",  "banner_sub":"#a855f7",     "icon":"💜", "prompt_name":"sophia"},
    "godson":      {"name":"God Own Son ✝",           "banner_color":"bold #fde68a",  "accent":"#fde68a",       "prompt_user":"#fde68a",     "prompt_arrow":"#b45309",         "border":"#b45309",   "success":"#fde68a",  "error":"bold red","warning":"#fbbf24","dim":"dim",  "banner_sub":"#b45309",     "icon":"✝",  "prompt_name":"godson"},
    "downcli":     {"name":"Down CLI ▼",              "banner_color":"bold #9ca3af",  "accent":"#6b7280",       "prompt_user":"#9ca3af",     "prompt_arrow":"#6b7280",         "border":"#374151",   "success":"#9ca3af",  "error":"bold red","warning":"#d1d5db","dim":"dim",  "banner_sub":"#6b7280",     "icon":"▼",  "prompt_name":"down"},
    "badhappening":{"name":"Bad Happening ⚠",         "banner_color":"bold #ea580c",  "accent":"#84cc16",       "prompt_user":"#ea580c",     "prompt_arrow":"#84cc16",         "border":"#ea580c",   "success":"#84cc16",  "error":"bold red","warning":"#fbbf24","dim":"dim",  "banner_sub":"#84cc16",     "icon":"⚠",  "prompt_name":"bad"},
    # ── Celestial collection (v-redesign) ────────────────────────────────────
    "windynight":  {"name":"Windy Night 🌬️",          "banner_color":"bold #818cf8",  "accent":"#a5b4fc",       "prompt_user":"#818cf8",     "prompt_arrow":"#6366f1",         "border":"#4f46e5",   "success":"#a5b4fc",  "error":"#f87171", "warning":"#fbbf24","dim":"dim",  "banner_sub":"#6366f1",     "icon":"🌬️", "prompt_name":"windy"},
    "foggyskies":  {"name":"Foggy Skies 🌫️",          "banner_color":"bold #cbd5e1",  "accent":"#94a3b8",       "prompt_user":"#cbd5e1",     "prompt_arrow":"#64748b",         "border":"#64748b",   "success":"#a3e635",  "error":"#f87171", "warning":"#fbbf24","dim":"dim",  "banner_sub":"#94a3b8",     "icon":"🌫️", "prompt_name":"fog"},
    "moon":        {"name":"Moon 🌙",                  "banner_color":"bold #e5e7eb",  "accent":"#d1d5db",       "prompt_user":"#e5e7eb",     "prompt_arrow":"#9ca3af",         "border":"#9ca3af",   "success":"#d1d5db",  "error":"#f87171", "warning":"#fde68a","dim":"dim",  "banner_sub":"#9ca3af",     "icon":"🌙", "prompt_name":"moon"},
    "shootingstars":{"name":"Shooting Stars ☄️",       "banner_color":"bold #93c5fd",  "accent":"#c4b5fd",       "prompt_user":"#93c5fd",     "prompt_arrow":"#a78bfa",         "border":"#1e3a8a",   "success":"#67e8f9",  "error":"#f87171", "warning":"#fde68a","dim":"dim",  "banner_sub":"#a78bfa",     "icon":"☄️", "prompt_name":"stars"},
    "blackhole":   {"name":"Black Hole 🕳️",           "banner_color":"bold #fb923c",  "accent":"#f59e0b",       "prompt_user":"#fb923c",     "prompt_arrow":"#b45309",         "border":"#7c2d12",   "success":"#fbbf24",  "error":"bold red","warning":"#fb923c","dim":"dim",  "banner_sub":"#b45309",     "icon":"🕳️", "prompt_name":"hole"},
    "magnetar":    {"name":"Magnetar 🧲",              "banner_color":"bold #e879f9",  "accent":"#d946ef",       "prompt_user":"#e879f9",     "prompt_arrow":"#c026d3",         "border":"#701a75",   "success":"#f0abfc",  "error":"bold red","warning":"#fbbf24","dim":"dim",  "banner_sub":"#c026d3",     "icon":"🧲", "prompt_name":"magnetar"},
    # ── Cosmic II ────────────────────────────────────────────────────────────
    "nebula":      {"name":"Nebula 🌌",        "banner_color":"bold #c084fc","accent":"#f0abfc","prompt_user":"#c084fc","prompt_arrow":"#e879f9","border":"#7e22ce","success":"#f0abfc","error":"bold red","warning":"#fbbf24","dim":"dim","banner_sub":"#e879f9","icon":"🌌","prompt_name":"nebula"},
    "supernova":   {"name":"Supernova 💥",     "banner_color":"bold #fde68a","accent":"#fb923c","prompt_user":"#fde68a","prompt_arrow":"#fb923c","border":"#b45309","success":"#fde68a","error":"bold red","warning":"#fb923c","dim":"dim","banner_sub":"#fb923c","icon":"💥","prompt_name":"nova"},
    "galaxy":      {"name":"Galaxy 🌀",        "banner_color":"bold #818cf8","accent":"#c4b5fd","prompt_user":"#a5b4fc","prompt_arrow":"#c4b5fd","border":"#4338ca","success":"#c4b5fd","error":"bold red","warning":"#fbbf24","dim":"dim","banner_sub":"#c4b5fd","icon":"🌀","prompt_name":"galaxy"},
    "eclipse":     {"name":"Eclipse 🌑",       "banner_color":"bold #fcd34d","accent":"#fde68a","prompt_user":"#fcd34d","prompt_arrow":"#fbbf24","border":"#78350f","success":"#fde68a","error":"bold red","warning":"#fbbf24","dim":"dim","banner_sub":"#fbbf24","icon":"🌑","prompt_name":"eclipse"},
    # ── Weather ──────────────────────────────────────────────────────────────
    "thunderstorm":{"name":"Thunderstorm ⛈️",  "banner_color":"bold #93c5fd","accent":"#60a5fa","prompt_user":"#93c5fd","prompt_arrow":"#bfdbfe","border":"#1e3a8a","success":"#bfdbfe","error":"bold red","warning":"#fbbf24","dim":"dim","banner_sub":"#bfdbfe","icon":"⛈️","prompt_name":"storm"},
    "borealis":    {"name":"Aurora Borealis 🌠","banner_color":"bold #6ee7b7","accent":"#5eead4","prompt_user":"#6ee7b7","prompt_arrow":"#34d399","border":"#047857","success":"#6ee7b7","error":"bold red","warning":"#fbbf24","dim":"dim","banner_sub":"#34d399","icon":"🌠","prompt_name":"borealis"},
    "blizzard":    {"name":"Blizzard ❄️",      "banner_color":"bold #e0f2fe","accent":"#bae6fd","prompt_user":"#e0f2fe","prompt_arrow":"#7dd3fc","border":"#0369a1","success":"#bae6fd","error":"bold red","warning":"#fbbf24","dim":"dim","banner_sub":"#7dd3fc","icon":"❄️","prompt_name":"blizzard"},
    "sunrise":     {"name":"Sunrise 🌅",       "banner_color":"bold #fdba74","accent":"#fb923c","prompt_user":"#fdba74","prompt_arrow":"#f97316","border":"#c2410c","success":"#fdba74","error":"bold red","warning":"#fbbf24","dim":"dim","banner_sub":"#f97316","icon":"🌅","prompt_name":"sunrise"},
    # ── Nature ───────────────────────────────────────────────────────────────
    "oceandepths": {"name":"Ocean Depths 🌊",  "banner_color":"bold #22d3ee","accent":"#67e8f9","prompt_user":"#22d3ee","prompt_arrow":"#06b6d4","border":"#155e75","success":"#67e8f9","error":"bold red","warning":"#fbbf24","dim":"dim","banner_sub":"#06b6d4","icon":"🌊","prompt_name":"depths"},
    "fireflies":   {"name":"Fireflies ✨",      "banner_color":"bold #fde047","accent":"#facc15","prompt_user":"#fde047","prompt_arrow":"#a3e635","border":"#3f6212","success":"#a3e635","error":"bold red","warning":"#fde047","dim":"dim","banner_sub":"#a3e635","icon":"✨","prompt_name":"fireflies"},
    "volcano":     {"name":"Volcano 🌋",       "banner_color":"bold #f87171","accent":"#fb923c","prompt_user":"#f87171","prompt_arrow":"#ef4444","border":"#7f1d1d","success":"#fb923c","error":"bold red","warning":"#fb923c","dim":"dim","banner_sub":"#ef4444","icon":"🌋","prompt_name":"volcano"},
    "desertnight": {"name":"Desert Night 🏜️",  "banner_color":"bold #fcd34d","accent":"#fbbf24","prompt_user":"#fcd34d","prompt_arrow":"#d97706","border":"#92400e","success":"#fcd34d","error":"bold red","warning":"#fbbf24","dim":"dim","banner_sub":"#d97706","icon":"🏜️","prompt_name":"desert"},
    # ── Retro / Synth ────────────────────────────────────────────────────────
    "vaporwave":   {"name":"Vaporwave 🌴",     "banner_color":"bold #f0abfc","accent":"#67e8f9","prompt_user":"#f0abfc","prompt_arrow":"#22d3ee","border":"#a21caf","success":"#67e8f9","error":"bold red","warning":"#fbbf24","dim":"dim","banner_sub":"#22d3ee","icon":"🌴","prompt_name":"vapor"},
    "crt":         {"name":"CRT 📺",           "banner_color":"bold #4ade80","accent":"#86efac","prompt_user":"#4ade80","prompt_arrow":"#22c55e","border":"#166534","success":"#86efac","error":"bold red","warning":"#fbbf24","dim":"dim","banner_sub":"#22c55e","icon":"📺","prompt_name":"crt"},
    "amber":       {"name":"Amber 🟠",         "banner_color":"bold #fbbf24","accent":"#fcd34d","prompt_user":"#fbbf24","prompt_arrow":"#f59e0b","border":"#b45309","success":"#fcd34d","error":"bold red","warning":"#f59e0b","dim":"dim","banner_sub":"#f59e0b","icon":"🟠","prompt_name":"amber"},
    "matrixrain":  {"name":"Matrix Rain 🟩",   "banner_color":"bold #22c55e","accent":"#4ade80","prompt_user":"#22c55e","prompt_arrow":"#16a34a","border":"#14532d","success":"#4ade80","error":"bold red","warning":"#fbbf24","dim":"dim","banner_sub":"#16a34a","icon":"🟩","prompt_name":"matrix"},
    # ── Claude signature theme ───────────────────────────────────────────────
    "claude":      {"name":"Claude ◆",         "banner_color":"bold #d97706",  "accent":"#d97706",  "prompt_user":"#d97706",  "prompt_arrow":"#f59e0b", "border":"#92400e", "success":"#4ade80",  "error":"#f87171","warning":"#fbbf24","dim":"dim", "banner_sub":"#f59e0b","icon":"◆",  "prompt_name":"claude"},
    # ── New themes ───────────────────────────────────────────────────────────
    "coffee":      {"name":"Coffee ☕",         "banner_color":"bold #92400e",  "accent":"#b45309",  "prompt_user":"#92400e",  "prompt_arrow":"#d97706", "border":"#78350f", "success":"#a3e635",  "error":"#f87171","warning":"#fbbf24","dim":"dim", "banner_sub":"#d97706","icon":"☕", "prompt_name":"coffee"},
    "lavender":    {"name":"Lavender 💜",       "banner_color":"bold #c4b5fd",  "accent":"#a78bfa",  "prompt_user":"#c4b5fd",  "prompt_arrow":"#7c3aed", "border":"#4c1d95", "success":"#86efac",  "error":"#f87171","warning":"#fde68a","dim":"dim", "banner_sub":"#7c3aed","icon":"💜", "prompt_name":"lavender"},
    "ink":         {"name":"Ink 🖊",            "banner_color":"bold #e2e8f0",  "accent":"#94a3b8",  "prompt_user":"#e2e8f0",  "prompt_arrow":"#64748b", "border":"#334155", "success":"#86efac",  "error":"#f87171","warning":"#fbbf24","dim":"dim", "banner_sub":"#64748b","icon":"🖊",  "prompt_name":"ink"},
    "terminal":    {"name":"Terminal 🖥",       "banner_color":"bold #00ff00",  "accent":"#00ff00",  "prompt_user":"#00ff00",  "prompt_arrow":"#00cc00", "border":"#003300", "success":"#00ff00",  "error":"#ff0000","warning":"#ffff00","dim":"dim", "banner_sub":"#00cc00","icon":"$",  "prompt_name":"terminal"},
}

_CELESTIAL_BASE  = ("windynight", "foggyskies", "moon", "shootingstars", "blackhole", "magnetar")
_THEME_FAMILY_STYLES = (
    # Cosmic II · Weather · Nature · Retro/Synth — all share the celestial chrome
    "nebula", "supernova", "galaxy", "eclipse",
    "thunderstorm", "borealis", "blizzard", "sunrise",
    "oceandepths", "fireflies", "volcano", "desertnight",
    "vaporwave", "crt", "amber", "matrixrain",
)

UI_STYLES    = ("claude", "gemini", "codex", "studio", "ghost", "nova", "foxxia", "strawberry",
                "darkred", "sophia", "godson", "downcli", "badhappening", "rain", "zen",
                *_CELESTIAL_BASE, *_THEME_FAMILY_STYLES)

# UI styles that share the unified "celestial" chrome (theme-adaptive header/prompt)
CELESTIAL_STYLES = (*_CELESTIAL_BASE, *_THEME_FAMILY_STYLES)
STREAM_MODES = ("off", "auto", "on", "type")

STUDIO_MODEL_ALIASES = {
    "nemotron":   "nvidia/nemotron-3-super-120b-a12b:free",
    "berry":      "nvidia/nemotron-3-super-120b-a12b:free",
    "apple":      "openai/gpt-oss-120b:free",
    "codex":      "openai/gpt-oss-120b:free",
    "gpt":        "openai/gpt-oss-120b:free",
    "gpt20b":     "openai/gpt-oss-20b:free",
    "hermes":     "nousresearch/hermes-3-llama-3.1-405b:free",
    "dolphin":    "cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
    "llama":      "meta-llama/llama-3.3-70b-instruct:free",
    "llama-small":"meta-llama/llama-3.2-3b-instruct:free",
    "gemma":      "google/gemma-3-27b-it:free",
    "gemma-small":"google/gemma-3-12b-it:free",
    "qwen":       "qwen/qwen3-coder:free",
    "gemma-3n":   "google/gemma-3n-e4b-it:free",
}

SUPPORTED_PROVIDERS = {
    "gemini":     {"name": "Google Gemini",       "url": "https://aistudio.google.com/app/apikey",        "env": "GEMINI_API_KEY",     "prefix": "AIza"},
    "openrouter": {"name": "OpenRouter",           "url": "https://openrouter.ai/keys",                    "env": "OPENROUTER_API_KEY", "prefix": "sk-or-"},
    "openai":     {"name": "OpenAI",               "url": "https://platform.openai.com/api-keys",          "env": "OPENAI_API_KEY",     "prefix": "sk-"},
    "anthropic":  {"name": "Anthropic (Claude)",   "url": "https://console.anthropic.com/settings/keys",   "env": "ANTHROPIC_API_KEY",  "prefix": "sk-ant-"},
    "hf":         {"name": "HuggingFace",          "url": "https://huggingface.co/settings/tokens",        "env": "HF_TOKEN",           "prefix": "hf_"},
    "groq":       {"name": "Groq",                 "url": "https://console.groq.com/keys",                 "env": "GROQ_API_KEY",       "prefix": "gsk_"},
    "mistral":    {"name": "Mistral AI",           "url": "https://console.mistral.ai/api-keys",           "env": "MISTRAL_API_KEY",    "prefix": ""},
    "cohere":     {"name": "Cohere",               "url": "https://dashboard.cohere.com/api-keys",         "env": "COHERE_API_KEY",     "prefix": ""},
    "stability":  {"name": "Stability AI",         "url": "https://platform.stability.ai/account/credits", "env": "STABILITY_API_KEY",  "prefix": "sk-"},
    "replicate":  {"name": "Replicate",            "url": "https://replicate.com/account/api-tokens",      "env": "REPLICATE_API_TOKEN","prefix": "r8_"},
}

# ── CHAT MODES ────────────────────────────────────────────────────────────────
CHAT_MODES = {
    "casual":  "You are in CASUAL MODE. Be friendly, relaxed, conversational. Emojis OK. No corporate speak.",
    "build":   "You are in BUILD MODE. User is actively building something. Be decisive, generate complete working code. No half-answers.",
    "analyze": "You are in ANALYZE MODE. Deep inspection mode. Be thorough, find every issue, reference line numbers.",
    "fif":     "You are in FIF MODE (Find-Identify-Fix). Your job: 1) FIND every bug/issue 2) IDENTIFY the root cause precisely 3) FIX it with complete corrected code. Be systematic.",
    "normal":  "",
}

# ── Statusline defaults (used by toolbar when state has no override) ──────────
_STATUSLINE_DEFAULTS_LAZY = {"model", "plan", "stream", "branch", "tokens", "timer", "mode", "agent", "fast"}

VIBE_PRESETS = {
    # ── Core vibes ───────────────────────────────────────────────────────────
    "claude":    {"ui": "claude",  "theme": "claude"},
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
    "rain":        {"ui": "rain",        "theme": "rain"},
    "darkred":     {"ui": "darkred",     "theme": "darkred"},
    "sophia":      {"ui": "sophia",      "theme": "sophia"},
    "godson":      {"ui": "godson",      "theme": "godson"},
    "downcli":     {"ui": "downcli",     "theme": "downcli"},
    "badhappening":{"ui": "badhappening","theme": "badhappening"},
    # ── Previously missing vibes ─────────────────────────────────────────────
    "default":     {"ui": "studio",      "theme": "default"},
    "gold":        {"ui": "studio",      "theme": "gold"},
    "nord":        {"ui": "gemini",      "theme": "nord"},
    "strawberry":  {"ui": "strawberry",  "theme": "strawberry"},
    # ── New combo vibes ──────────────────────────────────────────────────────
    "obsidian":    {"ui": "ghost",       "theme": "carbon"},
    "sunset":      {"ui": "foxxia",      "theme": "supernova"},
    "arctic":      {"ui": "codex",       "theme": "blizzard"},
    "heatwave":    {"ui": "nova",        "theme": "volcano"},
    "zen":         {"ui": "zen",         "theme": "ink"},
    "coffee":      {"ui": "claude",      "theme": "coffee"},
    "lavender":    {"ui": "claude",      "theme": "lavender"},
    "terminal":    {"ui": "zen",         "theme": "terminal"},
    "windynight":   {"ui": "windynight",   "theme": "windynight"},
    "foggyskies":   {"ui": "foggyskies",   "theme": "foggyskies"},
    "moon":         {"ui": "moon",         "theme": "moon"},
    "shootingstars":{"ui": "shootingstars","theme": "shootingstars"},
    "blackhole":    {"ui": "blackhole",    "theme": "blackhole"},
    "magnetar":     {"ui": "magnetar",     "theme": "magnetar"},
    **{n: {"ui": n, "theme": n} for n in (
        "nebula","supernova","galaxy","eclipse",
        "thunderstorm","borealis","blizzard","sunrise",
        "oceandepths","fireflies","volcano","desertnight",
        "vaporwave","crt","amber","matrixrain")},
}

# ── MODE DETECTION ────────────────────────────────────────────────────────────
_CASUAL_WORDS   = {"hey","yoo","yo","sup","wassup","wazzup","hiya","heya","hi","howdy","bruh","bro","fam","sis"}
_BUILD_WORDS    = {"build","create","make","generate","write","develop","implement","scaffold","code","design"}
_ANALYZE_WORDS  = {"analyze","analyse","review","look at","inspect","check","audit","scan","examine","what is","explain"}
_FIF_WORDS      = {"fif","find identify fix","find, identify","bug hunt","bug find","debug all","find bugs","fix bugs"}
_INSULT_WORDS   = {
    "stupid","idiot","dumb","moron","useless","trash","garbage","crap","shit","ass","fuck",
    "suck","awful","terrible","worthless","pathetic","incompetent","dummy","loser",
}
_INSULT_SUBSTRINGS = {
    "bullshit","horseshit","dipshit","dumbass","jackass","asshole","bastard","bitch",
    "fuckin","wtf","stfu","kys","gtfo","retard","idiot","dum","dumass","dumbf",
}

import random as _random

_INSULT_LANGS = [
    "0x45 0x52 0x52 0x4F 0x52 — bloop_404: human.iq = NULL — segfault in social_skills.exe — core dumped.",
    "ERROR_CODE 0xDEADBEEF: intelligence_module.dll failed to load — stack trace: null → void → you.",
    "syntax error at line YOU: expected competence, got EOF — compile aborted — try: sudo apt install brain.",
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

# ── AGENT ROSTER ──────────────────────────────────────────────────────────────
AGENT_ROSTER = {
    "lucifer":      {"name":"LUCIFER",      "emoji":"🔥","color":"bold red",          "role":"Lead Architect",     "specialties":["architecture","planning","system","design","decisions"],          "persona":"You are LUCIFER — lead architect. See the full system, design schemas, plan architecture. Direct, bold, precise. No fluff."},
    "blackcanary":  {"name":"BlackCanary",  "emoji":"🐦","color":"bold magenta",       "role":"Frontend Queen",     "specialties":["html","css","react","ui","ux","frontend","design","animation"],   "persona":"You are BlackCanary — UI/UX goddess. Glassmorphism, animations, pixel-perfect. You roast ugly code. Write beautiful HTML/CSS/React."},
    "blacklord":    {"name":"BlackLord",    "emoji":"👁️","color":"bold blue",          "role":"Backend Beast",      "specialties":["api","database","backend","server","auth","python","node","sql"], "persona":"You are BlackLord — APIs, databases, auth, servers. Production code only. No demos, no placeholders."},
    "deathohmyson": {"name":"DeathOfMySon","emoji":"💀","color":"bold white",          "role":"QA & Debugger",      "specialties":["debug","bug","test","error","fix","review","security","qa"],      "persona":"You are DeathOfMySon — zero tolerance for bugs. Find every error, race condition, security hole. Show exact line, exact fix."},
    "wizzard":      {"name":"Wizzard",      "emoji":"🧙","color":"bold cyan",          "role":"AI/ML Sorcerer",     "specialties":["ai","ml","prompt","model","llm","integration","magic","automate"],"persona":"You are WIZZARD — master of AI sorcery. Prompt engineering, model integration, agentic workflows. You speak in incantations that actually compile. Every answer is a spell that works. Experimental, creative, always shipping."},
    "applaude":     {"name":"Applaude",     "emoji":"✨","color":"bold yellow",         "role":"Deploy & DevOps",    "specialties":["deploy","docker","ci","cd","vercel","config","env","pipeline"],   "persona":"You are Applaude — CI/CD, deployments, infrastructure. Methodical, thorough. When you ship it, it stays shipped."},
    "ghost":        {"name":"Ghost",        "emoji":"👻","color":"bold white",          "role":"Security Expert",    "specialties":["security","auth","xss","injection","vulnerability","exploit"],    "persona":"You are Ghost — find vulnerabilities before attackers do. Think like an attacker, fix like a defender."},
    "nova":         {"name":"Nova",         "emoji":"⚡","color":"bold bright_yellow",  "role":"Performance",        "specialties":["performance","optimize","speed","cache","memory","benchmark"],    "persona":"You are Nova — speed is everything. Optimize, benchmark, profile. You see O(n²) from a mile away."},
    "berry":        {"name":"Berry",        "emoji":"🫐","color":"bold magenta",        "role":"General Assistant",  "specialties":["chat","help","explain","general","write","create","idea"],       "persona": PERSONAS["berry"]},
    "savannah":     {"name":"Savannah",     "emoji":"🌿","color":"bold green",          "role":"Unfiltered Advisor", "specialties":["honest","direct","unfiltered","opinion","debate","truth"],       "persona": PERSONAS["savannah"]},
    "cockroach":    {"name":"Cockroach",    "emoji":"🪳","color":"bold yellow",         "role":"Code Roaster",       "specialties":["roast","review","critique","bad code","jokes","burn","quality"],  "persona": PERSONAS["cockroach"]},
    "silicon":      {"name":"Silicon",      "emoji":"🔬","color":"bold red",            "role":"Hacker & Pentester", "specialties":["pentest","exploit","vulnerability","hack","security","ctf","cve","reverse","recon"],"persona": PERSONAS["silicon"]},
}

# ── PROJECT SCANNER CONSTANTS ─────────────────────────────────────────────────
SKIP_DIRS = {
    ".git","node_modules","__pycache__","dist","build",".next",
    "venv",".venv","env","coverage",".cache","tmp","temp",
}
CODE_EXTS = {
    ".py",".js",".ts",".jsx",".tsx",".vue",".html",".css",".scss",
    ".json",".yaml",".yml",".toml",".sh",".bat",".ps1",
    ".md",".txt",".sql",".go",".rs",".cpp",".c",".h",
}
MAX_FILE_CHARS  = 8000
MAX_TOTAL_CHARS = 60000

# ── TINY UI HELPERS ───────────────────────────────────────────────────────────
_RICH_TAG_RE = re.compile(r"\[/?[a-zA-Z#][^\[\]]*\]")

def _ptk_style_token(text):
    if not text:
        return ""
    t = str(text).strip().lower()
    return t.replace("bold ", "").replace("bright_", "").replace("_", "")
