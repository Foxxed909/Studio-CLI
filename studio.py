#!/usr/bin/env python3
"""
🎯 STUDIO TOOLS — Unified launcher for all StudioCLI tools.
Run any tool from one place.
"""

import sys
import os
import subprocess
from pathlib import Path

TOOLS_DIR = Path(__file__).parent / "tools"
FOX_CLI   = Path(__file__).parent / "fox.py"

BOLD  = "\033[1m"
DIM   = "\033[2m"
YEL   = "\033[33m"
CYN   = "\033[36m"
GRN   = "\033[32m"
MAG   = "\033[35m"
WHT   = "\033[37m"
RESET = "\033[0m"

TOOLS = {
    "fox":      {"file": str(FOX_CLI),                    "icon": "🦊", "desc": "Premium AI REPL (Max plan)",               "brand": YEL},
    "bedrock":  {"file": str(TOOLS_DIR / "bedrock.py"),   "icon": "🪨", "desc": "Architecture analysis & scaffolding",      "brand": WHT},
    "orange":   {"file": str(TOOLS_DIR / "orange.py"),    "icon": "🍊", "desc": "Data processing & pipeline automation",    "brand": YEL},
    "bolt":     {"file": str(TOOLS_DIR / "bolt.py"),      "icon": "⚡", "desc": "AI-powered task runner & shell helper",    "brand": YEL},
    "prism":    {"file": str(TOOLS_DIR / "prism.py"),     "icon": "💎", "desc": "Multi-model router & comparator",          "brand": MAG},
    "nexus":    {"file": str(TOOLS_DIR / "nexus.py"),     "icon": "🔌", "desc": "API testing & documentation",              "brand": CYN},
    "drift":    {"file": str(TOOLS_DIR / "drift.py"),     "icon": "🌊", "desc": "Git workflow assistant",                   "brand": CYN},
    "pulse":    {"file": str(TOOLS_DIR / "pulse.py"),     "icon": "💓", "desc": "Endpoint monitoring & alerting",           "brand": GRN},
    "review":   {"file": str(TOOLS_DIR / "fox-review.py"),"icon": "🔍", "desc": "AI code review with SHIP IT verdict",      "brand": CYN},
    "git":      {"file": str(TOOLS_DIR / "fox-git.py"),   "icon": "🌿", "desc": "Git commit/explain/branch/PR assistant",   "brand": GRN},
}

def print_header():
    print(f"""
{BOLD}{YEL}  ╔═══════════════════════════════════╗
  ║  🎯  STUDIO TOOLS  Launcher       ║
  ╚═══════════════════════════════════╝{RESET}
  {DIM}Run any StudioCLI tool from one place{RESET}
""")

def print_menu():
    print_header()
    print(f"  {'TOOL':<12}  {'DESCRIPTION'}")
    print(f"  {DIM}{'─'*11}  {'─'*44}{RESET}")
    for name, info in TOOLS.items():
        color = info["brand"]
        exists = "  " if Path(info["file"]).exists() else f" {DIM}(missing){RESET}"
        print(f"  {color}{BOLD}{info['icon']} {name:<10}{RESET}  {DIM}{info['desc']}{RESET}{exists}")
    print(f"""
  {DIM}Usage:{RESET}
    python studio.py <tool> [args...]
    python studio.py fox
    python studio.py bedrock scan .
    python studio.py prism route "What is WASM?" --models balanced
    python studio.py pulse watch https://myapp.com -i 60
""")

def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print_menu()
        return

    tool_name = sys.argv[1].lower()
    rest = sys.argv[2:]

    if tool_name not in TOOLS:
        # Try prefix match
        matches = [k for k in TOOLS if k.startswith(tool_name)]
        if len(matches) == 1:
            tool_name = matches[0]
        else:
            print(f"\n  {YEL}Unknown tool: {tool_name}{RESET}")
            print(f"  Available: {', '.join(TOOLS.keys())}\n")
            sys.exit(1)

    info = TOOLS[tool_name]
    tool_file = Path(info["file"])

    if not tool_file.exists():
        print(f"\n  {YEL}Tool file not found: {tool_file}{RESET}\n")
        sys.exit(1)

    cmd = [sys.executable, str(tool_file)] + rest
    os.execv(sys.executable, cmd)

if __name__ == "__main__":
    main()
