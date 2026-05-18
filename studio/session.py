"""
Persistence helpers — load/save profile, API keys, theme, workspace, trial, usage.
All I/O is scoped to ~/.aistudio/ and the local profiles/ directory.
"""
import json
import os
import time
from pathlib import Path
from datetime import datetime

from studio.paths import (
    CONFIG_DIR, HF_KEY_FILE, TRIAL_FILE, IMG_QUOTA_FILE,
    UPGRADE_SLOTS_FILE, THEME_FILE, LAST_MODEL_FILE,
    UI_STYLE_FILE, STREAM_MODE_FILE, KEYS_FILE, USAGE_FILE,
    PERSONA_FILE, WORKSPACE_FILE, MEMORY_FILE,
)
from studio.data import THEMES, SUPPORTED_PROVIDERS


# ── PROFILE ───────────────────────────────────────────────────────────────────
def load_profile(user_id="default"):
    path = Path("profiles") / user_id / "profile.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def save_profile(user_id_or_profile="default", profile=None):
    if profile is None:
        profile = user_id_or_profile
        user_id = "default"
    else:
        user_id = user_id_or_profile
    path = Path("profiles") / user_id / "profile.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, indent=2), encoding="utf-8")


# ── API KEYS ──────────────────────────────────────────────────────────────────
def load_api_key(user_id="default"):
    k = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    path = Path("profiles") / user_id / "gemini_key"
    return k or (path.read_text().strip() if path.exists() else None)


def save_api_key(user_id_or_key, k=None):
    if k is None:
        k = user_id_or_key
        user_id = "default"
    else:
        user_id = user_id_or_key
    path = Path("profiles") / user_id / "gemini_key"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(k.strip())


def load_or_key(user_id="default"):
    k = os.environ.get("OPENROUTER_API_KEY")
    path = Path("profiles") / user_id / "openrouter_key"
    return k or (path.read_text().strip() if path.exists() else None)


def save_or_key(user_id_or_key, k=None):
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


# ── THEME / UI / STREAM ───────────────────────────────────────────────────────
def load_theme():
    name = THEME_FILE.read_text().strip() if THEME_FILE.exists() else "default"
    return THEMES.get(name, THEMES["default"]), name


def save_theme(name):
    CONFIG_DIR.mkdir(exist_ok=True)
    THEME_FILE.write_text(name.strip())


def load_last_model():
    if LAST_MODEL_FILE.exists():
        val = LAST_MODEL_FILE.read_text().strip()
        if val and ("/" in val or val.startswith("gemini")):
            return val
    return None


def save_last_model(model):
    CONFIG_DIR.mkdir(exist_ok=True)
    LAST_MODEL_FILE.write_text(model.strip())


def load_ui_style():
    if UI_STYLE_FILE.exists():
        val = UI_STYLE_FILE.read_text().strip()
        if val:
            return val
    return None


def save_ui_style(style):
    CONFIG_DIR.mkdir(exist_ok=True)
    UI_STYLE_FILE.write_text(style.strip())


def load_stream_mode():
    if STREAM_MODE_FILE.exists():
        val = STREAM_MODE_FILE.read_text().strip()
        if val:
            return val
    return "auto"


def save_stream_mode(mode):
    CONFIG_DIR.mkdir(exist_ok=True)
    STREAM_MODE_FILE.write_text(mode.strip())


# ── PERSONA / WORKSPACE / MEMORY ──────────────────────────────────────────────
def load_persona():
    return PERSONA_FILE.read_text(encoding="utf-8").strip() if PERSONA_FILE.exists() else ""


def save_persona(text):
    CONFIG_DIR.mkdir(exist_ok=True)
    PERSONA_FILE.write_text(text.strip(), encoding="utf-8")


def load_workspace_root():
    if WORKSPACE_FILE.exists():
        val = WORKSPACE_FILE.read_text().strip()
        if val:
            return val
    return None


def save_workspace_root(path_str):
    CONFIG_DIR.mkdir(exist_ok=True)
    WORKSPACE_FILE.write_text(str(path_str).strip())


def load_memory():
    try:
        if MEMORY_FILE.exists():
            data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


def save_memory(mem: list):
    CONFIG_DIR.mkdir(exist_ok=True)
    MEMORY_FILE.write_text(json.dumps(mem, indent=2), encoding="utf-8")


# ── TRIAL ─────────────────────────────────────────────────────────────────────
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


# ── PLAN / QUOTA ──────────────────────────────────────────────────────────────
def get_plan(state) -> str:
    trial = load_trial()
    if trial:
        return trial.get("plan", "pro")
    prof = load_profile() or {}
    return prof.get("plan", state.get("plan", "free"))


def set_plan(state, plan: str):
    from studio.data import PLANS
    state["plan"] = plan
    prof = load_profile() or {}
    prof["plan"] = plan
    save_profile(prof)


def check_msg_limit(state) -> tuple[bool, int, int]:
    from studio.data import PLANS
    plan  = get_plan(state)
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
    from studio.data import PLANS
    plan   = get_plan(state)
    limit  = PLANS[plan]["img_per_3h"]
    if limit >= 999:
        return True, 0, limit
    now    = time.time()
    window = 3 * 3600
    data   = {}
    if IMG_QUOTA_FILE.exists():
        try:
            data = json.loads(IMG_QUOTA_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    timestamps = [t for t in data.get("ts", []) if now - t < window]
    if len(timestamps) >= limit:
        return False, len(timestamps), limit
    timestamps.append(now)
    data["ts"] = timestamps
    CONFIG_DIR.mkdir(exist_ok=True)
    IMG_QUOTA_FILE.write_text(json.dumps(data), encoding="utf-8")
    return True, len(timestamps), limit


# ── UPGRADE SLOTS ─────────────────────────────────────────────────────────────
def load_upgrade_slots():
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
    from studio.data import SLOT_GATED_PLANS, MAX_FREE_UPGRADE_SLOTS
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


# ── USAGE TRACKING ────────────────────────────────────────────────────────────
def load_usage():
    try:
        if USAGE_FILE.exists():
            data = json.loads(USAGE_FILE.read_text())
            now = time.time()
            data["history"] = [e for e in data.get("history", []) if now - e["ts"] < 18000]
            return data
    except Exception:
        pass
    return {"history": [], "total_in": 0, "total_out": 0}


def save_usage(usage):
    try:
        CONFIG_DIR.mkdir(exist_ok=True)
        USAGE_FILE.write_text(json.dumps(usage))
    except Exception:
        pass
