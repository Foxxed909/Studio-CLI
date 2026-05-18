#!/usr/bin/env python3
"""fox-git — AI-powered git assistant.

Usage:
  python tools/fox-git.py commit            AI generates & applies commit message
  python tools/fox-git.py explain           AI explains the last commit
  python tools/fox-git.py branch <desc>     AI suggests a branch name
  python tools/fox-git.py pr               AI drafts a PR description
"""

import sys
import os
import json
import urllib.request
import urllib.error
import subprocess
import argparse

# ---------------------------------------------------------------------------
# ANSI colours
# ---------------------------------------------------------------------------
RESET   = "\033[0m"
BOLD    = "\033[1m"
RED     = "\033[31m"
YELLOW  = "\033[33m"
GREEN   = "\033[32m"
CYAN    = "\033[36m"
MAGENTA = "\033[35m"
DIM     = "\033[2m"

def c(color, text):
    return f"{color}{text}{RESET}"

def header(title):
    print(f"\n{CYAN}{BOLD}{'─' * 55}{RESET}")
    print(f"{CYAN}{BOLD}  {title}{RESET}")
    print(f"{CYAN}{BOLD}{'─' * 55}{RESET}\n")

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
def call_openrouter(api_key, system, user_message):
    payload = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
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
            "X-Title":       "fox-git",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        print(c(RED, f"HTTP {e.code}: {body}"), file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(c(RED, f"Network error: {e.reason}"), file=sys.stderr)
        sys.exit(1)

    choices = data.get("choices", [])
    if not choices:
        print(c(RED, f"Empty response: {data}"), file=sys.stderr)
        sys.exit(1)
    return choices[0]["message"]["content"].strip()

# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------
def run_git(*args, check=True):
    result = subprocess.run(["git"] + list(args), capture_output=True, text=True)
    if check and result.returncode != 0:
        print(c(RED, f"git error: {result.stderr.strip()}"), file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()

def run_cmd(cmd, check=True):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(c(RED, f"Command error: {result.stderr.strip()}"), file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()

# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------
def cmd_commit(api_key):
    """Generate a commit message from staged diff and run git commit."""
    diff = run_git("diff", "--cached")
    if not diff.strip():
        print(c(YELLOW, "No staged changes. Use `git add` first."))
        sys.exit(0)

    print(c(DIM, "Generating commit message…"))
    system = (
        "You are a git expert. Return ONLY the commit message string, nothing else — "
        "no quotes, no explanation. Use conventional commits format: type(scope): description. "
        "Types: feat, fix, docs, style, refactor, test, chore. Keep it under 72 characters."
    )
    msg = call_openrouter(api_key, system, f"Write a commit message for:\n\n{diff}")

    header("Suggested Commit Message")
    print(c(GREEN, msg))
    print()

    confirm = input(f"{BOLD}Use this message? [Y/n/e(dit)]: {RESET}").strip().lower()
    if confirm in ("n", "no"):
        print(c(YELLOW, "Aborted."))
        sys.exit(0)
    if confirm in ("e", "edit"):
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tf:
            tf.write(msg)
            tf_path = tf.name
        editor = os.environ.get("EDITOR", "nano")
        subprocess.run([editor, tf_path])
        with open(tf_path) as f:
            msg = f.read().strip()
        os.unlink(tf_path)

    result = subprocess.run(["git", "commit", "-m", msg], capture_output=False)
    sys.exit(result.returncode)


def cmd_explain(api_key):
    """Explain the last commit in plain English."""
    log_msg  = run_git("log", "-1", "--format=%B")
    show_out = run_git("show", "HEAD", "--stat")
    combined = f"Commit message:\n{log_msg}\n\nChanged files:\n{show_out}"

    print(c(DIM, "Explaining last commit…"))
    system = "You are a helpful engineering communicator. Explain what this commit does in plain English, suitable for a non-technical stakeholder. Keep it concise — 2-4 sentences."
    explanation = call_openrouter(api_key, system, combined)

    header("Last Commit Explained")
    print(explanation)
    print()


def cmd_branch(api_key, description):
    """Suggest a branch name from a feature description."""
    print(c(DIM, "Generating branch name…"))
    system = (
        "You are a git expert. Return ONLY a branch name string, nothing else. "
        "Format: type/short-kebab-description (e.g. feat/user-auth, fix/login-crash). "
        "Keep it under 50 characters, lowercase, hyphens only, no spaces."
    )
    branch_name = call_openrouter(api_key, system, f"Suggest a branch name for: {description}")
    # Sanitize: strip quotes, whitespace, newlines
    branch_name = branch_name.strip().strip('"').strip("'").split("\n")[0].strip()

    header("Suggested Branch Name")
    print(c(GREEN, branch_name))
    print()

    confirm = input(f"{BOLD}Create this branch? [Y/n]: {RESET}").strip().lower()
    if confirm in ("n", "no"):
        print(c(YELLOW, "Branch not created."))
        return

    result = subprocess.run(["git", "checkout", "-b", branch_name], capture_output=False)
    if result.returncode == 0:
        print(c(GREEN, f"Switched to new branch '{branch_name}'"))
    sys.exit(result.returncode)


def cmd_pr(api_key):
    """Draft a PR description from commits ahead of main/master."""
    # Try main first, then master
    for base in ("main", "master"):
        result = subprocess.run(
            ["git", "log", f"{base}..HEAD", "--oneline"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            commits = result.stdout.strip()
            break
    else:
        print(c(RED, "Could not find main or master branch to compare against."), file=sys.stderr)
        sys.exit(1)

    if not commits:
        print(c(YELLOW, "No commits ahead of main/master."))
        sys.exit(0)

    # Also get the diff stat for context
    diff_stat = run_git("diff", f"{base}...HEAD", "--stat", check=False)
    combined = f"Commits:\n{commits}\n\nChanged files:\n{diff_stat}"

    print(c(DIM, "Drafting PR description…"))
    system = (
        "You are a senior engineer writing a pull request description. "
        "Return a well-structured PR body with these sections: "
        "## Summary (2-3 bullet points), ## What changed (brief technical detail), "
        "## Test plan (checklist). Be concise and professional."
    )
    pr_body = call_openrouter(api_key, system, combined)

    header("PR Description Draft")
    print(pr_body)
    print()

    print(c(DIM, "(Copy the text above into your PR description)"))

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="fox-git — AI-powered git assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", metavar="command")

    subparsers.add_parser("commit",  help="AI generates commit message from staged diff")
    subparsers.add_parser("explain", help="AI explains the last commit in plain English")
    branch_p = subparsers.add_parser("branch",  help="AI suggests a branch name from description")
    branch_p.add_argument("description", nargs="+", help="Description of the feature or fix")
    subparsers.add_parser("pr",      help="AI drafts a PR description from commits ahead of main")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(2)

    print(c(CYAN, f"\n{BOLD}fox-git{RESET}{CYAN}  powered by {MODEL}{RESET}"))

    api_key = load_api_key()
    if not api_key:
        print(c(RED, "No API key found. Set OPENROUTER_API_KEY or create profiles/default/openrouter_key"), file=sys.stderr)
        sys.exit(1)

    if args.command == "commit":
        cmd_commit(api_key)
    elif args.command == "explain":
        cmd_explain(api_key)
    elif args.command == "branch":
        description = " ".join(args.description)
        cmd_branch(api_key, description)
    elif args.command == "pr":
        cmd_pr(api_key)


if __name__ == "__main__":
    main()
