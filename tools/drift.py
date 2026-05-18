#!/usr/bin/env python3
"""
DRIFT — Git Workflow CLI
Brand: DRIFT · 🌊 · Bold blue/cyan · "Ride the git wave"
"""

import sys
import os
import json
import re
import subprocess
import urllib.request
import urllib.error
from datetime import datetime

VERSION = "1.0"

CYAN   = "\033[36m"
BLUE   = "\033[34m"
GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

BRAND   = f"{BOLD}{CYAN}🌊 DRIFT{RESET}"
TAGLINE = f"{DIM}Ride the git wave{RESET}"

# ---------------------------------------------------------------------------
# Key loading
# ---------------------------------------------------------------------------

def load_api_key():
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if key:
        return key
    key_path = os.path.join("profiles", "default", "openrouter_key")
    try:
        with open(key_path) as f:
            return f.read().strip()
    except FileNotFoundError:
        pass
    return ""

# ---------------------------------------------------------------------------
# AI helper
# ---------------------------------------------------------------------------

def ask_ai(prompt: str, api_key: str) -> str:
    if not api_key:
        return f"{YELLOW}[AI unavailable — set OPENROUTER_API_KEY]{RESET}"

    payload = json.dumps({
        "model": "google/gemini-2.5-flash",
        "messages": [{"role": "user", "content": prompt}],
    }).encode()

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/StudioCLI/drift",
            "X-Title": "DRIFT CLI",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"{RED}[AI error: {e}]{RESET}"

# ---------------------------------------------------------------------------
# Shell helper
# ---------------------------------------------------------------------------

def run(cmd: str, check=False) -> tuple[int, str, str]:
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()

def run_out(cmd: str) -> str:
    _, out, _ = run(cmd)
    return out

# ---------------------------------------------------------------------------
# cmd: status
# ---------------------------------------------------------------------------

def cmd_status(args):
    api_key = load_api_key()

    print(f"\n{BRAND}  {TAGLINE}")
    print(f"{DIM}{'─'*50}{RESET}")
    print(f"{BOLD}Git Status{RESET}")
    print()

    git_status = run_out("git status")
    git_log    = run_out("git log --oneline -5")
    git_diff   = run_out("git diff --stat")

    print(f"{BOLD}{CYAN}Status:{RESET}")
    print(git_status)
    print()

    if git_log:
        print(f"{BOLD}{CYAN}Recent commits:{RESET}")
        print(git_log)
        print()

    if git_diff:
        print(f"{BOLD}{CYAN}Diff stat:{RESET}")
        print(git_diff)
        print()

    prompt = (
        f"Review this git state and tell me: what's happening here, any concerns, "
        f"what should I do next? Keep it brief.\n\n"
        f"git status:\n{git_status}\n\n"
        f"Recent log:\n{git_log}\n\n"
        f"Diff stat:\n{git_diff}"
    )
    print(f"{BOLD}{CYAN}🤖 AI Commentary:{RESET}")
    print(ask_ai(prompt, api_key))
    print()

# ---------------------------------------------------------------------------
# cmd: commit
# ---------------------------------------------------------------------------

def cmd_commit(args):
    do_push = "--push" in args
    api_key = load_api_key()

    print(f"\n{BRAND}  {TAGLINE}")
    print(f"{DIM}{'─'*50}{RESET}")
    print(f"{BOLD}Smart Commit{RESET}")
    print()

    diff = run_out("git diff --cached")
    if not diff.strip():
        print(f"{YELLOW}Nothing staged. Checking unstaged diff...{RESET}")
        diff = run_out("git diff")

    if not diff.strip():
        print(f"{YELLOW}No changes to commit.{RESET}")
        return

    print(f"{DIM}Analyzing diff...{RESET}")
    prompt = (
        f"Generate a conventional commit message for this diff. "
        f"Use format: type(scope): description\\n\\nOptional body.\n\n"
        f"Diff:\n{diff[:3000]}\n\n"
        f"Return ONLY the commit message, no extra explanation."
    )
    msg = ask_ai(prompt, api_key)
    # strip possible markdown fences
    msg = msg.strip().strip("`").strip()

    print(f"\n{BOLD}{CYAN}Proposed commit message:{RESET}")
    print(f"{DIM}{'─'*40}{RESET}")
    print(msg)
    print(f"{DIM}{'─'*40}{RESET}")
    print()

    answer = input(f"{YELLOW}Use this message? [Y/n/e(dit)]: {RESET}").strip().lower()
    if answer == "n":
        print(f"{DIM}Commit aborted.{RESET}")
        return
    if answer == "e":
        custom = input("Enter your commit message: ").strip()
        if custom:
            msg = custom

    code, out, err = run(f'git commit -m {json.dumps(msg)}')
    if code == 0:
        print(f"{GREEN}✓ Committed:{RESET} {msg.splitlines()[0]}")
    else:
        print(f"{RED}Commit failed: {err}{RESET}")
        return

    if do_push:
        print(f"{DIM}Pushing...{RESET}")
        code, out, err = run("git push")
        if code == 0:
            print(f"{GREEN}✓ Pushed{RESET}")
            if out:
                print(out)
        else:
            print(f"{RED}Push failed: {err}{RESET}")
    print()

# ---------------------------------------------------------------------------
# cmd: pr
# ---------------------------------------------------------------------------

def cmd_pr(args):
    if not args:
        print(f"{RED}Usage: drift pr <title>{RESET}")
        sys.exit(1)

    title = " ".join(args)
    api_key = load_api_key()

    print(f"\n{BRAND}  {TAGLINE}")
    print(f"{DIM}{'─'*50}{RESET}")
    print(f"{BOLD}PR Description Generator{RESET}")
    print()

    # try main, fall back to master
    code, commits, _ = run("git log main..HEAD --oneline")
    if code != 0 or not commits.strip():
        _, commits, _ = run("git log master..HEAD --oneline")

    _, diff_stat, _ = run("git diff main..HEAD --stat")
    if not diff_stat.strip():
        _, diff_stat, _ = run("git diff master..HEAD --stat")

    print(f"{BOLD}{CYAN}Commits:{RESET}")
    print(commits or f"{DIM}(none found){RESET}")
    print()

    prompt = (
        f"Write a comprehensive PR description with the following sections:\n"
        f"## Summary (3 bullet points)\n"
        f"## Changes (what changed and why)\n"
        f"## Testing (what to test)\n\n"
        f"PR Title: {title}\n"
        f"Commits:\n{commits}\n\n"
        f"Diff stat:\n{diff_stat}"
    )
    description = ask_ai(prompt, api_key)

    print(f"{BOLD}{CYAN}Generated PR Description:{RESET}")
    print()
    print(description)
    print()

    # try clipboard
    copied = False
    try:
        import subprocess as _sp
        for clipcmd in (["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"], ["pbcopy"]):
            try:
                proc = _sp.Popen(clipcmd, stdin=_sp.PIPE, stderr=_sp.DEVNULL)
                proc.communicate(description.encode())
                if proc.returncode == 0:
                    copied = True
                    break
            except FileNotFoundError:
                continue
    except Exception:
        pass

    if copied:
        print(f"{GREEN}✓ Copied to clipboard{RESET}")
    else:
        print(f"{DIM}(clipboard not available){RESET}")
    print()

# ---------------------------------------------------------------------------
# cmd: review
# ---------------------------------------------------------------------------

def cmd_review(args):
    branch = args[0] if args else None
    api_key = load_api_key()

    print(f"\n{BRAND}  {TAGLINE}")
    print(f"{DIM}{'─'*50}{RESET}")
    print(f"{BOLD}AI Code Review{RESET}")
    print()

    if branch:
        diff = run_out(f"git diff {branch}..HEAD")
        label = f"{branch}..HEAD"
    else:
        code, diff, _ = run("git diff main..HEAD")
        label = "main..HEAD"
        if code != 0 or not diff.strip():
            _, diff, _ = run("git diff master..HEAD")
            label = "master..HEAD"

    if not diff.strip():
        print(f"{YELLOW}No diff found for {label}.{RESET}")
        return

    size = len(diff)
    print(f"{DIM}Diff size: {size} chars ({label}){RESET}")
    print()

    prompt = (
        f"Review this branch diff. Focus on: bugs, security issues, performance problems, "
        f"code quality. Format your response exactly as:\n\n"
        f"SUMMARY\n<brief overview>\n\n"
        f"ISSUES\n<numbered list of issues, or 'None found'>\n\n"
        f"VERDICT: APPROVE or REQUEST_CHANGES\n\n"
        f"Diff:\n{diff[:4000]}"
    )
    review = ask_ai(prompt, api_key)

    # colourize sections
    verdict_color = GREEN if "APPROVE" in review.upper() else RED
    lines = review.splitlines()
    for line in lines:
        if line.startswith("SUMMARY"):
            print(f"{BOLD}{CYAN}{line}{RESET}")
        elif line.startswith("ISSUES"):
            print(f"{BOLD}{YELLOW}{line}{RESET}")
        elif line.startswith("VERDICT"):
            print(f"{BOLD}{verdict_color}{line}{RESET}")
        else:
            print(line)
    print()

# ---------------------------------------------------------------------------
# cmd: changelog
# ---------------------------------------------------------------------------

def cmd_changelog(args):
    since = None
    i = 0
    while i < len(args):
        if args[i] == "--since" and i + 1 < len(args):
            since = args[i + 1]; i += 2
        else:
            i += 1

    api_key = load_api_key()

    print(f"\n{BRAND}  {TAGLINE}")
    print(f"{DIM}{'─'*50}{RESET}")
    print(f"{BOLD}Changelog Generator{RESET}")
    print()

    if since:
        code, commits, err = run(f"git log --oneline --since={since}")
        if code != 0 or not commits.strip():
            _, commits, _ = run(f"git log --oneline {since}..HEAD")
        label = f"since {since}"
    else:
        commits = run_out("git log --oneline -20")
        label = "last 20 commits"

    print(f"{DIM}Using: {label}{RESET}")
    print(commits[:1000] if commits else f"{YELLOW}No commits found{RESET}")
    print()

    if not commits.strip():
        return

    prompt = (
        f"Convert these git commits into a user-facing CHANGELOG entry. "
        f"Group by: Features, Bug Fixes, Breaking Changes, Internal. "
        f"Use markdown format. Be concise and user-friendly.\n\n"
        f"Commits:\n{commits}"
    )
    changelog = ask_ai(prompt, api_key)

    print(f"{BOLD}{CYAN}Generated Changelog:{RESET}")
    print()
    print(changelog)
    print()

    answer = input(f"{YELLOW}Append to CHANGELOG.md? [y/N]: {RESET}").strip().lower()
    if answer == "y":
        ts = datetime.now().strftime("%Y-%m-%d")
        entry = f"\n## [{ts}]\n\n{changelog}\n"
        mode = "a" if os.path.exists("CHANGELOG.md") else "w"
        with open("CHANGELOG.md", mode) as f:
            f.write(entry)
        print(f"{GREEN}✓ Appended to CHANGELOG.md{RESET}")
    print()

# ---------------------------------------------------------------------------
# cmd: hotfix
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text.strip())
    text = re.sub(r"-+", "-", text)
    return text[:40].rstrip("-")

def cmd_hotfix(args):
    if not args:
        print(f"{RED}Usage: drift hotfix <description>{RESET}")
        sys.exit(1)

    description = " ".join(args)
    api_key = load_api_key()

    print(f"\n{BRAND}  {TAGLINE}")
    print(f"{DIM}{'─'*50}{RESET}")
    print(f"{BOLD}Hotfix Planner:{RESET} {description}")
    print()

    prompt = (
        f"Create a hotfix plan for: {description}\n\n"
        f"Include exactly:\n"
        f"1) Root cause hypothesis\n"
        f"2) Files most likely affected\n"
        f"3) 3-step fix approach\n"
        f"4) How to test the fix\n"
        f"5) Rollback plan\n\n"
        f"Be specific and actionable."
    )
    plan = ask_ai(prompt, api_key)

    print(f"{BOLD}{CYAN}Hotfix Plan:{RESET}")
    print()
    print(plan)
    print()

    slug = _slugify(description)
    branch_name = f"hotfix/{slug}"
    answer = input(f"{YELLOW}Create hotfix branch '{branch_name}'? [y/N]: {RESET}").strip().lower()
    if answer == "y":
        code, out, err = run(f"git checkout -b {branch_name}")
        if code == 0:
            print(f"{GREEN}✓ Created and switched to branch: {branch_name}{RESET}")
        else:
            print(f"{RED}Failed to create branch: {err}{RESET}")
    print()

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

def print_help():
    print(f"""
{BRAND}  {TAGLINE}  v{VERSION}

{BOLD}Usage:{RESET}
  drift <command> [args]

{BOLD}{CYAN}Commands:{RESET}
  {BOLD}status{RESET}
         AI-enhanced git status with commentary

  {BOLD}commit{RESET} [--push]
         Generate a smart conventional commit message; optionally push

  {BOLD}pr{RESET} <title>
         Generate a PR description from your branch's commits

  {BOLD}review{RESET} [branch]
         AI code review of branch diff with APPROVE/REQUEST_CHANGES verdict

  {BOLD}changelog{RESET} [--since <tag|date>]
         Generate a user-facing CHANGELOG from git history

  {BOLD}hotfix{RESET} <description>
         Structured hotfix planning + optional branch creation

{BOLD}Examples:{RESET}
  drift status
  drift commit --push
  drift pr "Add user authentication"
  drift review feature/login
  drift changelog --since v1.2.0
  drift hotfix "login fails for OAuth users"

{BOLD}Config:{RESET}
  Set OPENROUTER_API_KEY env var, or place key in profiles/default/openrouter_key
""")

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

COMMANDS = {
    "status":    cmd_status,
    "commit":    cmd_commit,
    "pr":        cmd_pr,
    "review":    cmd_review,
    "changelog": cmd_changelog,
    "hotfix":    cmd_hotfix,
}

def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help", "help"):
        print_help()
        sys.exit(0)

    cmd = argv[0].lower()
    rest = argv[1:]

    if cmd not in COMMANDS:
        print(f"{RED}Unknown command: {cmd}{RESET}")
        print_help()
        sys.exit(1)

    COMMANDS[cmd](rest)

if __name__ == "__main__":
    main()
