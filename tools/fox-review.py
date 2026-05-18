#!/usr/bin/env python3
"""fox-review — AI-powered code review CLI.

Usage:
  python tools/fox-review.py <file>          Review a single file
  python tools/fox-review.py --diff          Review current git diff
  python tools/fox-review.py --pr <branch>   Review diff vs a branch
"""

import sys
import os
import json
import urllib.request
import urllib.error
import subprocess
import argparse

# ---------------------------------------------------------------------------
# ANSI colours (no rich dependency)
# ---------------------------------------------------------------------------
RESET   = "\033[0m"
BOLD    = "\033[1m"
RED     = "\033[31m"
YELLOW  = "\033[33m"
GREEN   = "\033[32m"
CYAN    = "\033[36m"
MAGENTA = "\033[35m"
WHITE   = "\033[97m"
DIM     = "\033[2m"

def c(color, text):
    return f"{color}{text}{RESET}"

def banner(label, color=CYAN):
    width = 60
    bar = "─" * width
    print(f"\n{color}{BOLD}┌{bar}┐{RESET}")
    print(f"{color}{BOLD}│  {label:<{width - 2}}│{RESET}")
    print(f"{color}{BOLD}└{bar}┘{RESET}")

# ---------------------------------------------------------------------------
# API key
# ---------------------------------------------------------------------------
MODEL = "google/gemini-2.5-flash"

def load_api_key():
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if key:
        return key
    key_file = os.path.join(os.getcwd(), "profiles", "default", "openrouter_key")
    try:
        with open(key_file) as f:
            return f.read().strip()
    except FileNotFoundError:
        return None

# ---------------------------------------------------------------------------
# OpenRouter call
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "You are a senior software engineer doing a rigorous code review. "
    "Analyze the code and respond with these exact sections:\n"
    "SUMMARY\nBUGS\nSECURITY\nSUGGESTIONS\nVERDICT (must be exactly one of: SHIP IT / NEEDS WORK / CRITICAL)\n"
    "Be specific — cite line numbers and exact issues."
)

def call_openrouter(api_key, user_message):
    payload = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
    }).encode()

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer":  "https://github.com/StudioCLI",
            "X-Title":       "fox-review",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        print(c(RED, f"HTTP {e.code}: {body}"), file=sys.stderr)
        sys.exit(2)
    except urllib.error.URLError as e:
        print(c(RED, f"Network error: {e.reason}"), file=sys.stderr)
        sys.exit(2)

    choices = data.get("choices", [])
    if not choices:
        print(c(RED, f"Empty response: {data}"), file=sys.stderr)
        sys.exit(2)
    return choices[0]["message"]["content"]

# ---------------------------------------------------------------------------
# Input collection
# ---------------------------------------------------------------------------
def get_file_content(path):
    try:
        with open(path) as f:
            return f.read()
    except (OSError, IOError) as e:
        print(c(RED, f"Cannot read file: {e}"), file=sys.stderr)
        sys.exit(2)

def run_git(*args):
    result = subprocess.run(["git"] + list(args), capture_output=True, text=True)
    if result.returncode != 0:
        print(c(RED, f"git error: {result.stderr.strip()}"), file=sys.stderr)
        sys.exit(2)
    return result.stdout

def get_diff():
    return run_git("diff")

def get_pr_diff(branch):
    return run_git("diff", f"{branch}...HEAD")

# ---------------------------------------------------------------------------
# Output rendering
# ---------------------------------------------------------------------------
SECTION_COLORS = {
    "SUMMARY":     CYAN,
    "BUGS":        RED,
    "SECURITY":    MAGENTA,
    "SUGGESTIONS": YELLOW,
    "VERDICT":     GREEN,
}

VERDICT_COLOR = {
    "SHIP IT":    (GREEN,  0),
    "NEEDS WORK": (YELLOW, 1),
    "CRITICAL":   (RED,    2),
}

def parse_and_print(review_text):
    """Print sections with color and return exit code based on verdict."""
    sections = {}
    current = None
    lines_buf = []

    for line in review_text.splitlines():
        stripped = line.strip()
        matched = None
        for key in SECTION_COLORS:
            if stripped.upper().startswith(key):
                matched = key
                break
        if matched:
            if current:
                sections[current] = "\n".join(lines_buf).strip()
            current = matched
            lines_buf = []
            # Keep any content on the same line as the header
            rest = stripped[len(matched):].lstrip(": ").strip()
            if rest:
                lines_buf.append(rest)
        elif current:
            lines_buf.append(line)

    if current:
        sections[current] = "\n".join(lines_buf).strip()

    for section, color in SECTION_COLORS.items():
        banner(section, color)
        content = sections.get(section, "(not found)")
        print(content)

    # Determine exit code from verdict
    verdict_text = sections.get("VERDICT", "").upper()
    for label, (color, code) in VERDICT_COLOR.items():
        if label in verdict_text:
            print(f"\n{BOLD}{color}  VERDICT: {label}  {RESET}\n")
            return code

    # Default if we couldn't parse verdict
    print(c(YELLOW, "\n  VERDICT: NEEDS WORK (could not parse verdict)  \n"))
    return 1

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="fox-review — AI-powered code review",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("file", nargs="?", help="File to review")
    group.add_argument("--diff", action="store_true", help="Review current git diff")
    group.add_argument("--pr", metavar="BRANCH", help="Review diff vs branch")
    args = parser.parse_args()

    api_key = load_api_key()
    if not api_key:
        print(c(RED, "No API key found. Set OPENROUTER_API_KEY or create profiles/default/openrouter_key"), file=sys.stderr)
        sys.exit(2)

    print(c(CYAN, f"\n{BOLD}fox-review{RESET}{CYAN}  powered by {MODEL}{RESET}"))

    if args.diff:
        diff = get_diff()
        if not diff.strip():
            print(c(YELLOW, "No changes in working tree."))
            sys.exit(0)
        prompt = f"Review this git diff:\n\n{diff}"
        label = "git diff"
    elif args.pr:
        diff = get_pr_diff(args.pr)
        if not diff.strip():
            print(c(YELLOW, f"No diff between HEAD and {args.pr}."))
            sys.exit(0)
        prompt = f"Review this PR diff (comparing HEAD to {args.pr}):\n\n{diff}"
        label = f"PR vs {args.pr}"
    elif args.file:
        content = get_file_content(args.file)
        prompt = f"Review this file ({args.file}):\n\n{content}"
        label = args.file
    else:
        parser.print_help()
        sys.exit(2)

    print(c(DIM, f"Reviewing: {label} …"))

    review = call_openrouter(api_key, prompt)
    exit_code = parse_and_print(review)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
