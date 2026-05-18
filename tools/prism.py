#!/usr/bin/env python3
"""
💎 PRISM CLI — Multi-model AI router. One prompt, many perspectives.
Route · Compare · Synthesize · Decide.
"""

import argparse
import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib import request as urllib_req
from urllib import error as urllib_err

VERSION = "1.0.0"

BOLD  = "\033[1m"
DIM   = "\033[2m"
CYN   = "\033[36m"
MAG   = "\033[35m"
YEL   = "\033[33m"
GRN   = "\033[32m"
RED   = "\033[31m"
BLU   = "\033[34m"
WHT   = "\033[37m"
RESET = "\033[0m"

OR_BASE = "https://openrouter.ai/api/v1/chat/completions"
PRISM_RESULTS_DIR = Path.home() / ".prism" / "results"

PRISM_MODELS = {
    "flash":   {"id": "google/gemini-2.5-flash",                  "color": BLU,  "label": "Gemini Flash",    "cost": (0.000075, 0.0003)},
    "sonnet":  {"id": "anthropic/claude-sonnet-4-5",              "color": MAG,  "label": "Claude Sonnet",   "cost": (0.003, 0.015)},
    "gpt4":    {"id": "openai/gpt-4o",                            "color": GRN,  "label": "GPT-4o",          "cost": (0.0025, 0.010)},
    "mini":    {"id": "openai/gpt-4o-mini",                       "color": CYN,  "label": "GPT-4o Mini",     "cost": (0.00015, 0.0006)},
    "llama":   {"id": "meta-llama/llama-3.3-70b-instruct:free",   "color": YEL,  "label": "Llama 3.3 70B",   "cost": (0.0, 0.0)},
    "mistral": {"id": "mistralai/mistral-large",                  "color": RED,  "label": "Mistral Large",   "cost": (0.002, 0.006)},
    "gemini":  {"id": "google/gemini-2.5-pro",                    "color": BLU,  "label": "Gemini Pro",      "cost": (0.00125, 0.005)},
    "haiku":   {"id": "anthropic/claude-haiku-4-5",               "color": MAG,  "label": "Claude Haiku",    "cost": (0.0008, 0.004)},
}

PRISM_PRESETS = {
    "fast":     ["flash", "mini", "haiku"],
    "deep":     ["sonnet", "gemini", "gpt4"],
    "free":     ["llama", "flash"],
    "all":      list(PRISM_MODELS.keys()),
    "balanced": ["flash", "sonnet", "llama"],
    "code":     ["sonnet", "gpt4", "gemini"],
}


def load_key() -> str | None:
    k = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("STUDIO_OR_KEY")
    if k:
        return k
    for p in [
        Path("profiles") / "default" / "openrouter_key",
        Path.home() / ".aistudio" / "openrouter_key",
        Path.home() / ".fox" / "openrouter_key",
    ]:
        if p.exists():
            raw = p.read_text().strip()
            try:
                return json.loads(raw).get("key") or raw
            except Exception:
                return raw if raw.startswith("sk-or-") else None
    return None


def call_model(key: str, model_id: str, prompt: str, system: str = "Be concise and precise.") -> tuple[str | None, float, str | None]:
    """Returns (response_text, elapsed_seconds, error)."""
    payload = json.dumps({
        "model":      model_id,
        "messages":   [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "stream":     False,
        "max_tokens": 2048,
    }).encode()
    req = urllib_req.Request(
        OR_BASE, data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}", "X-Title": "PRISM CLI"},
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib_req.urlopen(req, timeout=90) as resp:
            text = json.loads(resp.read())["choices"][0]["message"]["content"]
            return text, round(time.time() - t0, 2), None
    except Exception as exc:
        return None, round(time.time() - t0, 2), str(exc)


def estimate_cost(model_key: str, tok_in: int, tok_out: int) -> float:
    rates = PRISM_MODELS.get(model_key, {}).get("cost", (0.001, 0.001))
    mid = PRISM_MODELS.get(model_key, {}).get("id", "")
    if mid.endswith(":free"):
        return 0.0
    return (tok_in * rates[0] + tok_out * rates[1]) / 1000


def approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def divider(w: int = 72) -> str:
    return f"{DIM}{'─' * w}{RESET}"


def print_header() -> None:
    print(f"\n{BOLD}{MAG}💎 PRISM{RESET}  {DIM}v{VERSION} — Multi-model AI router{RESET}\n")


def print_model_result(alias: str, info: dict, text: str | None, elapsed: float, error: str | None) -> None:
    color = info["color"]
    label = info["label"]
    cost  = estimate_cost(alias, approx_tokens("prompt"), approx_tokens(text or ""))
    cost_str = "free" if cost == 0.0 else f"${cost:.6f}"
    print(f"\n{BOLD}{color}▶ {label}{RESET}  {DIM}{elapsed:.1f}s · {cost_str}{RESET}")
    print(divider())
    if error:
        print(f"  {RED}Error: {error}{RESET}")
    elif text:
        # Indent each line slightly
        for line in text.split("\n"):
            print(f"  {line}")
    print()


def cmd_route(prompt: str, models: list[str], system: str = "Be concise and precise.") -> None:
    """Run prompt against multiple models in parallel."""
    key = load_key()
    if not key:
        print(f"{RED}No API key. Set OPENROUTER_API_KEY{RESET}")
        sys.exit(1)

    print_header()
    print(f"  {DIM}Routing to: {', '.join(m.upper() for m in models)}{RESET}")
    print(f"  {DIM}Prompt:     {prompt[:80]}{'…' if len(prompt) > 80 else ''}{RESET}\n")

    results: dict[str, tuple] = {}
    lock = threading.Lock()

    def _run(alias: str):
        info = PRISM_MODELS[alias]
        text, elapsed, err = call_model(key, info["id"], prompt, system)
        with lock:
            results[alias] = (text, elapsed, err)

    print(f"  {DIM}⟳ Querying {len(models)} model(s) in parallel…{RESET}\n")
    threads = [threading.Thread(target=_run, args=(m,)) for m in models]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    total_cost = 0.0
    for alias in models:
        info = PRISM_MODELS[alias]
        text, elapsed, err = results.get(alias, (None, 0, "No result"))
        print_model_result(alias, info, text, elapsed, err)
        total_cost += estimate_cost(alias, approx_tokens(prompt), approx_tokens(text or ""))

    print(divider())
    print(f"  {DIM}Total cost: ${total_cost:.6f}  ·  {len(models)} models{RESET}\n")

    # Save results
    PRISM_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = {
        "prompt":    prompt,
        "models":    models,
        "timestamp": datetime.now().isoformat(),
        "results":   {
            alias: {"text": results.get(alias, (None,))[0], "elapsed": results.get(alias, (None, 0))[1]}
            for alias in models
        },
    }
    (PRISM_RESULTS_DIR / f"prism_{ts}.json").write_text(json.dumps(out, indent=2))


def cmd_synthesize(prompt: str, models: list[str]) -> None:
    """Run prompt on multiple models, then synthesize responses into one answer."""
    key = load_key()
    if not key:
        print(f"{RED}No API key.{RESET}")
        sys.exit(1)

    print_header()
    print(f"  {DIM}Step 1: Gathering responses from {len(models)} models…{RESET}\n")

    results: dict[str, str] = {}
    lock = threading.Lock()

    def _run(alias: str):
        info = PRISM_MODELS[alias]
        text, _, err = call_model(key, info["id"], prompt)
        with lock:
            results[alias] = text or f"[Error: {err}]"

    threads = [threading.Thread(target=_run, args=(m,)) for m in models]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for alias in models:
        info = PRISM_MODELS[alias]
        print(f"  {info['color']}{BOLD}{info['label']}{RESET}  {DIM}✓{RESET}")

    # Build synthesis prompt
    synth_parts = [f"Multiple AI models answered this question: '{prompt}'\n\nTheir responses:"]
    for alias in models:
        synth_parts.append(f"\n## {PRISM_MODELS[alias]['label']}\n{results[alias][:1000]}")
    synth_parts.append(
        "\n\nSynthesize these responses into ONE definitive answer:\n"
        "1. Where they agree → state the consensus clearly\n"
        "2. Where they differ → note the key differences\n"
        "3. Your synthesis → the best combined answer\n"
        "Be concise. Use the strongest insights from each."
    )

    print(f"\n  {DIM}Step 2: Synthesizing with Claude Sonnet…{RESET}\n")
    synth_model = PRISM_MODELS.get("sonnet") or PRISM_MODELS.get("flash")
    synth_id    = synth_model["id"]  # type: ignore
    text, elapsed, err = call_model(key, synth_id, "\n".join(synth_parts),
                                    "You are an expert synthesizer. Combine multiple AI responses into one definitive answer.")
    print(f"{BOLD}{MAG}💎 SYNTHESIS{RESET}  {DIM}{elapsed:.1f}s{RESET}")
    print(divider())
    if err:
        print(f"{RED}{err}{RESET}")
    else:
        for line in (text or "").split("\n"):
            print(f"  {line}")
    print()


def cmd_vote(prompt: str, models: list[str]) -> None:
    """Run a yes/no or A/B question and tally votes."""
    key = load_key()
    if not key:
        print(f"{RED}No API key.{RESET}")
        sys.exit(1)

    print_header()
    print(f"  {DIM}Vote prompt: {prompt[:80]}{RESET}\n")

    vote_system = (
        "Answer this question with ONLY one of: YES, NO, A, B, or NEITHER. "
        "Then in 15 words or fewer, explain why. Format: ANSWER: <choice>  REASON: <why>"
    )

    results: dict[str, tuple] = {}
    lock = threading.Lock()

    def _run(alias: str):
        info = PRISM_MODELS[alias]
        text, elapsed, err = call_model(key, info["id"], prompt, vote_system)
        with lock:
            results[alias] = (text, elapsed, err)

    threads = [threading.Thread(target=_run, args=(m,)) for m in models]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    votes: dict[str, int] = {}
    print(f"  {'Model':<20}  {'Vote':<8}  Reason\n  {divider(60)}")
    for alias in models:
        info = PRISM_MODELS[alias]
        text, _, err = results.get(alias, (None, 0, "Error"))
        vote = "ERROR"
        reason = err or "No response"
        if text:
            import re
            m = re.search(r"ANSWER:\s*(\w+)", text, re.IGNORECASE)
            r = re.search(r"REASON:\s*(.+)", text, re.IGNORECASE)
            vote   = m.group(1).upper() if m else text.split()[0][:8]
            reason = r.group(1).strip() if r else text[:60]
        votes[vote] = votes.get(vote, 0) + 1
        color = info["color"]
        print(f"  {color}{BOLD}{info['label']:<20}{RESET}  {BOLD}{vote:<8}{RESET}  {DIM}{reason[:50]}{RESET}")

    print(f"\n  {divider()}")
    winner = max(votes, key=lambda k: votes[k]) if votes else "N/A"
    print(f"  {BOLD}Result: {GRN}{winner}{RESET}  {DIM}({votes.get(winner,0)}/{len(models)} votes){RESET}\n")


def cmd_benchmark(prompt: str, models: list[str]) -> None:
    """Benchmark speed and cost across models."""
    key = load_key()
    if not key:
        print(f"{RED}No API key.{RESET}")
        sys.exit(1)

    print_header()
    print(f"  {DIM}Benchmarking {len(models)} models…{RESET}\n")

    results: dict[str, tuple] = {}
    lock = threading.Lock()

    def _run(alias: str):
        info = PRISM_MODELS[alias]
        t, elapsed, err = call_model(key, info["id"], prompt)
        with lock:
            results[alias] = (t, elapsed, err)

    threads = [threading.Thread(target=_run, args=(m,)) for m in models]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    print(f"  {'Model':<22}  {'Speed':>8}  {'Tokens':>8}  {'Cost':>12}  {'Quality'}")
    print(f"  {divider(72)}")
    ranked = sorted(results.items(), key=lambda x: x[1][1])
    for alias, (text, elapsed, err) in ranked:
        info = PRISM_MODELS[alias]
        tok_out = approx_tokens(text or "")
        cost = estimate_cost(alias, approx_tokens(prompt), tok_out)
        cost_str = "free" if cost == 0.0 else f"${cost:.6f}"
        quality = "✓" if text and not err else "✗"
        color = info["color"]
        tok_s = round(tok_out / max(elapsed, 0.1))
        print(f"  {color}{BOLD}{info['label']:<22}{RESET}  {elapsed:>6.1f}s  {tok_s:>5}t/s  {cost_str:>12}  {quality}")
    print()


def cmd_models() -> None:
    """List available models and presets."""
    print_header()
    print(f"  {BOLD}Models:{RESET}\n")
    for alias, info in PRISM_MODELS.items():
        mid = info["id"].split("/")[-1].split(":")[0]
        rates = info.get("cost", (0, 0))
        cost_str = "free" if info["id"].endswith(":free") else f"${rates[0]*1000:.4f}/${rates[1]*1000:.4f} per 1k"
        print(f"  {info['color']}{BOLD}{alias:<12}{RESET}  {mid:<28}  {DIM}{cost_str}{RESET}")

    print(f"\n  {BOLD}Presets:{RESET}\n")
    for preset, models in PRISM_PRESETS.items():
        print(f"  {MAG}{BOLD}{preset:<12}{RESET}  {DIM}{', '.join(models)}{RESET}")
    print()


# ── Main ──────────────────────────────────────────────────────────────────────

def _resolve_models(spec: str) -> list[str]:
    """Resolve a model spec (preset name or comma-separated aliases) to a list."""
    if spec in PRISM_PRESETS:
        return PRISM_PRESETS[spec]
    parts = [p.strip() for p in spec.split(",")]
    valid = []
    for p in parts:
        if p in PRISM_MODELS:
            valid.append(p)
        else:
            print(f"  {YEL}Warning: unknown model '{p}' — skipped.{RESET}")
    return valid or list(PRISM_PRESETS["fast"])


def main():
    parser = argparse.ArgumentParser(
        prog="prism",
        description=f"💎 PRISM CLI v{VERSION} — Multi-model AI router",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  prism route      "<prompt>" [--models fast|balanced|all|m1,m2]
  prism synth      "<prompt>" [--models deep|balanced]
  prism vote       "<question>" [--models balanced]
  prism bench      "<prompt>" [--models all]
  prism models              List all models and presets

Model presets: fast · deep · free · all · balanced · code
Model aliases: flash · sonnet · gpt4 · mini · llama · mistral · gemini · haiku

Examples:
  prism route "What is the best way to handle auth in 2025?"
  prism route "Explain async/await" --models sonnet,flash,llama
  prism synth "Design a rate limiter" --models deep
  prism vote "Should I use TypeScript for this project?"
  prism bench "Write hello world" --models all
""",
    )
    parser.add_argument("command", nargs="?", help="route|synth|vote|bench|models")
    parser.add_argument("prompt",  nargs="?", help="The prompt to send")
    parser.add_argument("--models", "-m", default="balanced", help="Model preset or comma-separated aliases")
    parser.add_argument("--version", action="store_true")
    parsed = parser.parse_args()

    if parsed.version:
        print(f"PRISM CLI v{VERSION}")
        return

    if not parsed.command or parsed.command == "models":
        cmd_models()
        return

    cmd    = parsed.command.lower()
    prompt = parsed.prompt
    models = _resolve_models(parsed.models)

    if not prompt:
        print(f"{RED}Usage: prism {cmd} \"<prompt>\" [--models <preset>]{RESET}")
        sys.exit(1)

    if cmd in ("route", "r"):
        cmd_route(prompt, models)
    elif cmd in ("synth", "synthesize", "s"):
        cmd_synthesize(prompt, models)
    elif cmd in ("vote", "v"):
        cmd_vote(prompt, models)
    elif cmd in ("bench", "benchmark", "b"):
        cmd_benchmark(prompt, models)
    else:
        print(f"{RED}Unknown command '{cmd}'. Try: route, synth, vote, bench, models{RESET}")
        sys.exit(1)


if __name__ == "__main__":
    main()
