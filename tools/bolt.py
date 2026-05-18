#!/usr/bin/env python3
"""
⚡ BOLT CLI — AI-powered task runner and automation engine.
Fast. Minimal. No nonsense.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib import request as urllib_req
from urllib import error as urllib_err

VERSION = "1.0.0"

# ANSI
BOLD  = "\033[1m"
DIM   = "\033[2m"
YEL   = "\033[33m"
CYN   = "\033[36m"
GRN   = "\033[32m"
RED   = "\033[31m"
MAG   = "\033[35m"
RESET = "\033[0m"
LIGHTNING = "⚡"

BOLT_TASKS_FILE = Path.home() / ".bolt" / "tasks.json"
BOLT_HISTORY_FILE = Path.home() / ".bolt" / "history.json"

OR_BASE = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "google/gemini-2.5-flash"


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


def ask_ai(prompt: str, system: str = "You are an expert programmer and DevOps engineer. Be concise and precise.") -> str:
    key = load_key()
    if not key:
        return f"{RED}[No API key — set OPENROUTER_API_KEY]{RESET}"
    payload = json.dumps({
        "model":      DEFAULT_MODEL,
        "messages":   [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "stream":     False,
        "max_tokens": 2048,
    }).encode()
    req = urllib_req.Request(
        OR_BASE, data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}", "X-Title": "BOLT CLI"},
        method="POST",
    )
    try:
        with urllib_req.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())["choices"][0]["message"]["content"]
    except Exception as exc:
        return f"{RED}[Error: {exc}]{RESET}"


def header(title: str) -> None:
    w = min(os.get_terminal_size().columns, 72) if hasattr(os, "get_terminal_size") else 72
    print(f"\n{BOLD}{YEL}{LIGHTNING} BOLT  {DIM}v{VERSION}{RESET}  {DIM}{title}{RESET}")
    print(f"{DIM}{'─' * w}{RESET}\n")


def load_tasks() -> dict:
    if BOLT_TASKS_FILE.exists():
        try:
            return json.loads(BOLT_TASKS_FILE.read_text())
        except Exception:
            pass
    return {}


def save_tasks(tasks: dict) -> None:
    BOLT_TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    BOLT_TASKS_FILE.write_text(json.dumps(tasks, indent=2))


def add_to_history(task_name: str, result: str) -> None:
    BOLT_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    hist = []
    if BOLT_HISTORY_FILE.exists():
        try:
            hist = json.loads(BOLT_HISTORY_FILE.read_text())
        except Exception:
            pass
    from datetime import datetime
    hist.append({"task": task_name, "result": result[:500], "ts": datetime.now().isoformat()})
    BOLT_HISTORY_FILE.write_text(json.dumps(hist[-100:], indent=2))


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_run(task_desc: str) -> None:
    """Run a natural language task via AI → shell commands."""
    header("Task Runner")
    print(f"  {DIM}Task:{RESET} {task_desc}\n")
    prompt = (
        f"Task: {task_desc}\n\n"
        "Generate shell commands to complete this task. Rules:\n"
        "1. Output ONLY a numbered list of shell commands (no explanation)\n"
        "2. Prefix dangerous commands with [CONFIRM]\n"
        "3. Use cross-platform commands where possible\n"
        "4. Each command on its own line, numbered: 1. <cmd>"
    )
    result = ask_ai(prompt, "You are a DevOps expert. Output only shell commands, numbered list.")
    print(result)
    print()
    confirm = input(f"  {YEL}Execute these commands? (y/n):{RESET} ").strip().lower()
    if confirm == "y":
        lines = [l.strip() for l in result.splitlines() if l.strip() and not l.strip().startswith("#")]
        cmds  = []
        for l in lines:
            import re
            m = re.match(r"^\d+\.\s+(?:\[CONFIRM\]\s*)?(.+)$", l)
            if m:
                cmds.append(m.group(1))
        for cmd in cmds:
            if "[CONFIRM]" in result:
                ok = input(f"  {RED}Confirm: {cmd}{RESET}  (y/n): ").strip().lower()
                if ok != "y":
                    print(f"  {DIM}Skipped.{RESET}")
                    continue
            print(f"  {CYN}$ {cmd}{RESET}")
            r = subprocess.run(cmd, shell=True)
            if r.returncode != 0:
                print(f"  {RED}Exit code {r.returncode}{RESET}")
        add_to_history(task_desc, "executed")


def cmd_explain(cmd_str: str) -> None:
    """Explain what a shell command does in plain English."""
    header("Command Explainer")
    result = ask_ai(
        f"Explain exactly what this shell command does, step by step:\n\n```\n{cmd_str}\n```\n\n"
        "Format: one short paragraph overview, then bullet points for each part of the command.",
        "You are a shell expert. Explain commands clearly to developers of all levels."
    )
    print(result)


def cmd_fix_error(error: str) -> None:
    """Diagnose a shell error and suggest a fix."""
    header("Error Fixer")
    result = ask_ai(
        f"I got this error:\n\n```\n{error}\n```\n\n"
        "1. What caused this error? (2 sentences)\n"
        "2. How to fix it? (exact commands)\n"
        "3. How to prevent it? (1 sentence)",
        "You are a systems expert. Diagnose errors precisely."
    )
    print(result)


def cmd_generate(script_desc: str) -> None:
    """Generate a shell script from a description."""
    header("Script Generator")
    result = ask_ai(
        f"Write a complete, production-ready bash script that: {script_desc}\n\n"
        "Requirements:\n"
        "- Add a shebang line\n"
        "- Add set -euo pipefail\n"
        "- Add helpful comments\n"
        "- Handle errors gracefully\n"
        "- Output only the script, no explanation",
        "You are an expert bash programmer. Write clean, robust scripts."
    )
    print(f"{GRN}{result}{RESET}\n")
    save_path = input("  Save to file? (filename or Enter to skip): ").strip()
    if save_path:
        Path(save_path).write_text(result)
        os.chmod(save_path, 0o755)
        print(f"  {GRN}✓ Saved to {save_path}{RESET}")


def cmd_alias(name: str, command: str = "") -> None:
    """Save and run named task aliases."""
    header("Task Aliases")
    tasks = load_tasks()
    if not command:
        if name == "list":
            if not tasks:
                print("  No aliases saved. Use: bolt alias <name> <command>")
                return
            for n, c in tasks.items():
                print(f"  {YEL}{n:<20}{RESET}  {DIM}{c}{RESET}")
            return
        if name in tasks:
            print(f"  {CYN}$ {tasks[name]}{RESET}")
            subprocess.run(tasks[name], shell=True)
            add_to_history(name, "ran alias")
        else:
            print(f"  {RED}Unknown alias '{name}'.{RESET}  Run: bolt alias list")
        return
    tasks[name] = command
    save_tasks(tasks)
    print(f"  {GRN}✓ Alias saved: {YEL}{name}{RESET}  →  {DIM}{command}{RESET}")


def cmd_history() -> None:
    """Show recent Bolt task history."""
    header("History")
    if not BOLT_HISTORY_FILE.exists():
        print("  No history yet.")
        return
    try:
        hist = json.loads(BOLT_HISTORY_FILE.read_text())
    except Exception:
        print("  History file corrupted.")
        return
    for item in reversed(hist[-20:]):
        ts = item.get("ts", "")[:16].replace("T", " ")
        print(f"  {DIM}{ts}{RESET}  {YEL}{item['task'][:60]}{RESET}")


def cmd_cron(desc: str) -> None:
    """Generate a cron expression from a natural language schedule."""
    header("Cron Generator")
    result = ask_ai(
        f"Convert this schedule to a cron expression: '{desc}'\n\n"
        "Return:\n"
        "1. The cron expression (5 fields)\n"
        "2. A plain English description of when it runs\n"
        "3. How to add it to crontab (exact command)\n"
        "4. An example crontab entry (including a sample command)",
        "You are a cron expert. Be precise."
    )
    print(result)


def cmd_docker(action: str) -> None:
    """AI Docker helper — generate Dockerfiles, docker-compose, etc."""
    header(f"Docker — {action}")
    prompts = {
        "dockerfile": "Generate a production-ready Dockerfile for a Python application. Include: multi-stage build, non-root user, .dockerignore hints, health check. Scan the current directory if context is provided.",
        "compose":    "Generate a docker-compose.yml for a typical web application with: app service, postgres database, redis cache. Include volumes, environment variables, health checks.",
        "clean":      "Generate shell commands to clean up Docker: remove stopped containers, dangling images, unused volumes, unused networks. Show commands with explanations.",
    }
    prompt_text = prompts.get(action, f"Help me with Docker: {action}")
    result = ask_ai(prompt_text, "You are a Docker and container expert.")
    print(result)
    save_path = input("\n  Save to file? (filename or Enter to skip): ").strip()
    if save_path:
        Path(save_path).write_text(result)
        print(f"  {GRN}✓ Saved to {save_path}{RESET}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="bolt",
        description=f"{LIGHTNING} BOLT CLI v{VERSION} — AI-powered task runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  bolt run    "<task>"          Natural language → shell commands
  bolt explain "<command>"      Explain what a command does
  bolt fix    "<error>"         Diagnose and fix a shell error
  bolt gen    "<description>"   Generate a bash script
  bolt alias  <name> [cmd]      Save/run named task aliases
  bolt alias  list              List all aliases
  bolt history                  Show recent tasks
  bolt cron   "<schedule>"      Convert to cron expression
  bolt docker <dockerfile|compose|clean>  Docker helpers
""",
    )
    parser.add_argument("command", nargs="?", help="Command to run")
    parser.add_argument("args",    nargs="*", help="Arguments")
    parser.add_argument("--version", action="store_true")
    parsed = parser.parse_args()

    if parsed.version:
        print(f"BOLT CLI v{VERSION}")
        return

    if not parsed.command:
        parser.print_help()
        return

    cmd  = parsed.command.lower()
    rest = " ".join(parsed.args) if parsed.args else ""

    if cmd == "run":
        if not rest:
            print(f"{RED}Usage: bolt run \"<task>\"{RESET}")
            return
        cmd_run(rest)
    elif cmd == "explain":
        if not rest:
            print(f"{RED}Usage: bolt explain \"<command>\"{RESET}")
            return
        cmd_explain(rest)
    elif cmd in ("fix", "error"):
        if not rest:
            print(f"{RED}Usage: bolt fix \"<error message>\"{RESET}")
            return
        cmd_fix_error(rest)
    elif cmd in ("gen", "generate", "script"):
        if not rest:
            print(f"{RED}Usage: bolt gen \"<description>\"{RESET}")
            return
        cmd_generate(rest)
    elif cmd == "alias":
        name = parsed.args[0] if parsed.args else "list"
        value = " ".join(parsed.args[1:]) if len(parsed.args) > 1 else ""
        cmd_alias(name, value)
    elif cmd == "history":
        cmd_history()
    elif cmd == "cron":
        if not rest:
            print(f"{RED}Usage: bolt cron \"every day at 3am\"{RESET}")
            return
        cmd_cron(rest)
    elif cmd == "docker":
        action = parsed.args[0] if parsed.args else "help"
        cmd_docker(action)
    else:
        # Unknown command — try to run it as a task
        print(f"  {DIM}Unknown command '{cmd}'. Running as task…{RESET}\n")
        cmd_run(f"{cmd} {rest}".strip())


if __name__ == "__main__":
    main()
