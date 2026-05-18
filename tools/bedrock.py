#!/usr/bin/env python3
"""
BEDROCK CLI — Foundation-first AI engineering
Standalone tool for infrastructure, architecture analysis, and project scaffolding.
"""

VERSION = "1.0"

import argparse
import json
import os
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

# ── ANSI color constants ──────────────────────────────────────────────────────
RED    = "\033[31m"
YELLOW = "\033[33m"
GREEN  = "\033[32m"
CYAN   = "\033[36m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"
WHITE  = "\033[97m"
GRAY   = "\033[90m"

# ── Brand constants ───────────────────────────────────────────────────────────
ICON    = "🪨"
NAME    = "BEDROCK"
TAG     = "Foundation-first AI engineering"
PROMPT  = f"{ICON} bedrock ›"
MODEL   = "google/gemini-2.5-flash"

# ── Directories to skip during tree walks ────────────────────────────────────
SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", "dist", "build",
    ".venv", "venv", "env", ".env", ".idea", ".vscode",
    "coverage", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "target",  # Rust/Java
}

# ── Language extension map ────────────────────────────────────────────────────
EXT_LANG = {
    ".py":    "Python",
    ".js":    "JavaScript",
    ".ts":    "TypeScript",
    ".tsx":   "TypeScript/React",
    ".jsx":   "JavaScript/React",
    ".rs":    "Rust",
    ".go":    "Go",
    ".java":  "Java",
    ".c":     "C",
    ".cpp":   "C++",
    ".h":     "C/C++ Header",
    ".cs":    "C#",
    ".rb":    "Ruby",
    ".php":   "PHP",
    ".swift": "Swift",
    ".kt":    "Kotlin",
    ".sh":    "Shell",
    ".bash":  "Bash",
    ".zsh":   "Zsh",
    ".html":  "HTML",
    ".css":   "CSS",
    ".scss":  "SCSS",
    ".sql":   "SQL",
    ".md":    "Markdown",
    ".yaml":  "YAML",
    ".yml":   "YAML",
    ".toml":  "TOML",
    ".json":  "JSON",
}

# ── Framework / config fingerprints ──────────────────────────────────────────
FRAMEWORK_HINTS = {
    "package.json":        "Node.js",
    "next.config.js":      "Next.js",
    "next.config.ts":      "Next.js",
    "vite.config.ts":      "Vite",
    "vite.config.js":      "Vite",
    "angular.json":        "Angular",
    "vue.config.js":       "Vue",
    "nuxt.config.js":      "Nuxt",
    "svelte.config.js":    "SvelteKit",
    "requirements.txt":    "Python project",
    "pyproject.toml":      "Python (pyproject)",
    "setup.py":            "Python (setup.py)",
    "setup.cfg":           "Python (setup.cfg)",
    "Cargo.toml":          "Rust (Cargo)",
    "go.mod":              "Go modules",
    "pom.xml":             "Java (Maven)",
    "build.gradle":        "Java/Kotlin (Gradle)",
    "Gemfile":             "Ruby (Bundler)",
    "composer.json":       "PHP (Composer)",
    "docker-compose.yml":  "Docker Compose",
    "docker-compose.yaml": "Docker Compose",
    "Dockerfile":          "Docker",
    ".github":             "GitHub Actions",
    "terraform":           "Terraform",
    "k8s":                 "Kubernetes",
    "helm":                "Helm",
}

ENTRY_POINTS = {
    "main.py", "app.py", "server.py", "index.py", "cli.py",
    "index.js", "app.js", "server.js", "index.ts", "app.ts",
    "main.rs", "main.go", "Main.java",
}

TEST_DIR_NAMES = {"tests", "test", "__tests__", "spec", "specs"}


# ─────────────────────────────────────────────────────────────────────────────
# Key loading
# ─────────────────────────────────────────────────────────────────────────────

def load_key_from_profile() -> str:
    """Try to read OpenRouter key from the default profile file."""
    key_file = Path("profiles/default/openrouter_key")
    if key_file.exists():
        return key_file.read_text().strip()
    return ""


def get_api_key() -> str:
    return os.environ.get("OPENROUTER_API_KEY", "") or load_key_from_profile()


# ─────────────────────────────────────────────────────────────────────────────
# API helper
# ─────────────────────────────────────────────────────────────────────────────

def ask_ai(prompt: str, system: str = "You are a senior software architect.") -> str:
    """Blocking OpenRouter call. Returns response text or error string."""
    key = get_api_key()
    if not key:
        return (
            f"{RED}[ERROR]{RESET} No OpenRouter key found.\n"
            "Set OPENROUTER_API_KEY env var or write key to profiles/default/openrouter_key"
        )
    payload = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
        "stream": False,
        "max_tokens": 2048,
    }).encode()
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "X-Title": "BEDROCK CLI",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())["choices"][0]["message"]["content"]
    except Exception as e:
        return f"{RED}[ERROR]{RESET} {e}"


# ─────────────────────────────────────────────────────────────────────────────
# Shared utilities
# ─────────────────────────────────────────────────────────────────────────────

def print_header(title: str) -> None:
    """Print a branded BEDROCK header."""
    width = 60
    border = f"{BOLD}{WHITE}{'─' * width}{RESET}"
    print()
    print(border)
    print(f"  {ICON}  {BOLD}{WHITE}{NAME}{RESET}  {GRAY}{TAG}{RESET}")
    print(f"  {CYAN}{title}{RESET}")
    print(border)
    print()


def print_section(header: str, content: str) -> None:
    """Print a colored section block."""
    print(f"\n{BOLD}{CYAN}{'━' * 4} {header} {'━' * (50 - len(header))}{RESET}")
    print(content)


def colorize_ai_output(text: str) -> str:
    """
    Apply basic ANSI coloring to common section headers in AI output.
    Lines that look like ALL-CAPS headings or markdown ## headings get colored.
    """
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        # Markdown bold headers: **Title** or ## Title
        if stripped.startswith("##"):
            lines.append(f"{BOLD}{CYAN}{line}{RESET}")
        elif stripped.startswith("**") and stripped.endswith("**") and len(stripped) > 4:
            lines.append(f"{BOLD}{WHITE}{line}{RESET}")
        elif stripped.isupper() and len(stripped) > 3 and stripped.replace(" ", "").isalpha():
            lines.append(f"{BOLD}{YELLOW}{line}{RESET}")
        elif stripped.startswith("- ") or stripped.startswith("* "):
            lines.append(f"{GREEN}{line}{RESET}")
        elif stripped.startswith("```") or stripped.endswith("```"):
            lines.append(f"{DIM}{line}{RESET}")
        else:
            lines.append(line)
    return "\n".join(lines)


def walk_tree(root: Path):
    """Yield all files under root, skipping SKIP_DIRS."""
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skip dirs in-place
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fname in filenames:
            yield Path(dirpath) / fname


def count_lines(path: Path) -> int:
    """Return number of lines in a file, gracefully ignoring decode errors."""
    try:
        return sum(1 for _ in path.open("rb"))
    except Exception:
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# Command: scan
# ─────────────────────────────────────────────────────────────────────────────

def cmd_scan(path_str: str) -> None:
    root = Path(path_str).resolve()
    if not root.exists():
        print(f"{RED}[ERROR]{RESET} Path not found: {root}")
        sys.exit(1)
    if not root.is_dir():
        print(f"{RED}[ERROR]{RESET} Not a directory: {root}")
        sys.exit(1)

    print_header(f"Scanning: {root}")
    print(f"{DIM}Walking directory tree...{RESET}", flush=True)

    ext_counts: dict[str, int]   = defaultdict(int)
    ext_loc:    dict[str, int]   = defaultdict(int)
    frameworks: list[str]         = []
    entry_points: list[str]       = []
    test_dirs: list[str]          = []
    config_files: list[str]       = []
    total_files = 0

    # Collect framework hints from top-level names
    top_entries = set(p.name for p in root.iterdir())
    for hint, label in FRAMEWORK_HINTS.items():
        if hint in top_entries and label not in frameworks:
            frameworks.append(label)

    for fpath in walk_tree(root):
        total_files += 1
        ext = fpath.suffix.lower()
        if ext in EXT_LANG:
            ext_counts[ext] += 1
            ext_loc[ext] += count_lines(fpath)

        # Entry points
        if fpath.name in ENTRY_POINTS:
            rel = str(fpath.relative_to(root))
            if rel not in entry_points:
                entry_points.append(rel)

        # Test dirs (record unique parent names)
        if fpath.parent.name in TEST_DIR_NAMES:
            rel_dir = str(fpath.parent.relative_to(root))
            if rel_dir not in test_dirs:
                test_dirs.append(rel_dir)

        # Config / infra files
        if fpath.name in {
            "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
            ".env.example", ".env.sample", "nginx.conf", "Makefile",
            "Justfile", "Taskfile.yml", "Taskfile.yaml",
        }:
            config_files.append(str(fpath.relative_to(root)))

    # Build summary for display
    total_loc = sum(ext_loc.values())
    lang_lines = sorted(
        [(EXT_LANG.get(e, e), ext_counts[e], ext_loc[e]) for e in ext_counts],
        key=lambda x: x[2], reverse=True
    )

    # Print local report
    print(f"\n{BOLD}Files scanned:{RESET} {total_files}")
    print(f"{BOLD}Total LOC:{RESET}    {total_loc:,}")
    print()

    print(f"{BOLD}{CYAN}Languages detected:{RESET}")
    for lang, count, loc in lang_lines[:12]:
        bar_len = min(30, int(loc / max(total_loc, 1) * 30))
        bar = "█" * bar_len
        print(f"  {GREEN}{lang:<22}{RESET} {count:>4} files  {loc:>7,} LOC  {DIM}{bar}{RESET}")

    if frameworks:
        print(f"\n{BOLD}{CYAN}Frameworks / tooling:{RESET}")
        for f in frameworks:
            print(f"  {YELLOW}◆ {f}{RESET}")

    if entry_points:
        print(f"\n{BOLD}{CYAN}Entry points:{RESET}")
        for ep in entry_points[:10]:
            print(f"  {GREEN}▶ {ep}{RESET}")

    if test_dirs:
        print(f"\n{BOLD}{CYAN}Test directories:{RESET}")
        for td in test_dirs[:6]:
            print(f"  {CYAN}✓ {td}{RESET}")

    if config_files:
        print(f"\n{BOLD}{CYAN}Infrastructure / config:{RESET}")
        for cf in config_files[:10]:
            print(f"  {DIM}⚙ {cf}{RESET}")

    # Build AI prompt
    lang_summary = ", ".join(f"{l} ({loc:,} LOC)" for l, _, loc in lang_lines[:8])
    framework_summary = ", ".join(frameworks) if frameworks else "None detected"
    entry_summary = ", ".join(entry_points[:5]) if entry_points else "None detected"

    ai_prompt = (
        f"Project: {root.name}\n"
        f"Total files: {total_files}\n"
        f"Total LOC: {total_loc:,}\n"
        f"Languages: {lang_summary}\n"
        f"Frameworks/tooling: {framework_summary}\n"
        f"Entry points: {entry_summary}\n"
        f"Test directories: {', '.join(test_dirs[:4]) if test_dirs else 'None found'}\n"
        f"Config/infra files: {', '.join(config_files[:6]) if config_files else 'None found'}\n\n"
        "Analyze this project structure and produce:\n"
        "1) ARCHITECTURE OVERVIEW\n"
        "2) DEPENDENCIES assessment\n"
        "3) TECHNICAL DEBT risks\n"
        "4) SCALABILITY concerns\n"
        "5) TOP 3 RECOMMENDATIONS\n"
        "Be specific and concise."
    )

    print(f"\n{DIM}Sending to AI for architecture analysis...{RESET}", flush=True)
    result = ask_ai(ai_prompt)

    print_section("AI ARCHITECTURE ANALYSIS", colorize_ai_output(result))
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Command: scaffold
# ─────────────────────────────────────────────────────────────────────────────

SCAFFOLD_TYPES = {"api", "cli", "web", "bot", "worker"}

SCAFFOLD_DESCRIPTIONS = {
    "api":    "a REST API server (Python FastAPI or Node.js Express)",
    "cli":    "a Python CLI tool with argparse and rich output",
    "web":    "a static website (HTML/CSS/JS, no framework)",
    "bot":    "a Discord bot (Python discord.py)",
    "worker": "a background job worker (Python with queue/cron support)",
}


def cmd_scaffold(proj_type: str, name: str) -> None:
    proj_type = proj_type.lower()
    if proj_type not in SCAFFOLD_TYPES:
        print(f"{RED}[ERROR]{RESET} Unknown scaffold type: {proj_type!r}")
        print(f"  Valid types: {', '.join(sorted(SCAFFOLD_TYPES))}")
        sys.exit(1)

    print_header(f"Scaffolding {proj_type.upper()}: {name}")

    description = SCAFFOLD_DESCRIPTIONS[proj_type]
    ai_prompt = (
        f"Generate a project scaffold for {description}.\n"
        f"Project name: {name}\n\n"
        "Respond with:\n"
        "1. FILE STRUCTURE: A tree of files/directories to create (using ASCII tree format, e.g. └── ├──)\n"
        "2. MAIN FILE CONTENT: Full content of the main entry file (the most important file)\n"
        "   Mark the start with: === MAIN FILE: <filename> ===\n"
        "   Mark the end with:   === END MAIN FILE ===\n"
        "3. SETUP INSTRUCTIONS: 2-3 sentences on how to run it.\n"
        "Keep it practical and production-ready but minimal."
    )

    print(f"{DIM}Generating scaffold blueprint...{RESET}", flush=True)
    result = ask_ai(ai_prompt)

    # Split out main file content if present
    main_file_name = None
    main_file_content = None
    display_result = result

    if "=== MAIN FILE:" in result and "=== END MAIN FILE ===" in result:
        before, rest = result.split("=== MAIN FILE:", 1)
        header_line, body = rest.split("\n", 1)
        main_file_name = header_line.strip().rstrip("===").strip()
        content_and_after = body.split("=== END MAIN FILE ===", 1)
        main_file_content = content_and_after[0].strip()
        after = content_and_after[1] if len(content_and_after) > 1 else ""
        display_result = before + after

    print_section("FILE STRUCTURE", colorize_ai_output(display_result))

    if main_file_name and main_file_content:
        print(f"\n{BOLD}{CYAN}Main file: {main_file_name}{RESET}")
        print(f"{DIM}{'─' * 60}{RESET}")
        print(main_file_content)
        print(f"{DIM}{'─' * 60}{RESET}")

    # Offer to create files
    print()
    answer = input(f"{BOLD}{WHITE}Generate these files under ./{name}/? (y/n):{RESET} ").strip().lower()
    if answer != "y":
        print(f"{DIM}Aborted. No files created.{RESET}")
        return

    # Parse the tree from result and create directories/placeholder files
    base = Path(name)
    if base.exists():
        print(f"{YELLOW}[WARN]{RESET} Directory '{name}' already exists. Files will be added inside it.")
    base.mkdir(parents=True, exist_ok=True)

    # Create the main file if we have its content
    created = []
    if main_file_name and main_file_content:
        target = base / main_file_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(main_file_content)
        created.append(str(target))

    # Parse file paths from the tree text
    for line in display_result.splitlines():
        # Look for lines that contain a filename pattern (extension or known names)
        stripped = line.strip().lstrip("│├└─ ")
        if not stripped:
            continue
        # Skip comment lines
        if stripped.startswith("#") or stripped.startswith("//"):
            continue
        # Heuristic: contains a dot extension or is a known dir name
        if ("." in stripped and not stripped.startswith(".") and " " not in stripped.split(".")[-1]):
            # Looks like a file
            rel_path = stripped.split()[0]  # Take first token only
            # Skip if it's the main file already created
            if main_file_name and rel_path.endswith(main_file_name):
                continue
            fpath = base / rel_path
            if not fpath.exists():
                fpath.parent.mkdir(parents=True, exist_ok=True)
                fpath.write_text(f"# {rel_path}\n# Generated by BEDROCK CLI\n")
                created.append(str(fpath))

    print(f"\n{GREEN}Created {len(created)} file(s) under ./{name}/{RESET}")
    for c in created:
        print(f"  {DIM}+ {c}{RESET}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Command: review
# ─────────────────────────────────────────────────────────────────────────────

def detect_language(path: Path) -> str:
    return EXT_LANG.get(path.suffix.lower(), "Unknown")


def cmd_review(file_str: str) -> None:
    fpath = Path(file_str).resolve()
    if not fpath.exists():
        print(f"{RED}[ERROR]{RESET} File not found: {fpath}")
        sys.exit(1)
    if not fpath.is_file():
        print(f"{RED}[ERROR]{RESET} Not a file: {fpath}")
        sys.exit(1)

    lang = detect_language(fpath)
    print_header(f"Architecture Review: {fpath.name}  [{lang}]")

    try:
        source = fpath.read_text(errors="replace")
    except Exception as e:
        print(f"{RED}[ERROR]{RESET} Could not read file: {e}")
        sys.exit(1)

    loc = source.count("\n") + 1
    print(f"{DIM}File: {fpath}  |  Language: {lang}  |  Lines: {loc:,}{RESET}\n")

    if loc > 2000:
        print(f"{YELLOW}[WARN]{RESET} File is large ({loc} lines). Analysis may be truncated.")

    ai_prompt = (
        f"File: {fpath.name}\n"
        f"Language: {lang}\n"
        f"Lines: {loc}\n\n"
        f"```{lang.lower()}\n{source[:8000]}\n```\n\n"
        "Review this file for:\n"
        "- Separation of concerns\n"
        "- SOLID principles adherence\n"
        "- Coupling and cohesion\n"
        "- Naming conventions\n"
        "- Maintainability\n\n"
        "Give specific, line-level feedback where relevant. "
        "Format each concern as: [SEVERITY] Line X: description. "
        "Severity levels: CRITICAL, WARNING, INFO, GOOD."
    )

    print(f"{DIM}Sending file to AI for review...{RESET}", flush=True)
    result = ask_ai(ai_prompt)
    print_section("ARCHITECTURE REVIEW", colorize_severity(result))
    print()


def colorize_severity(text: str) -> str:
    """Color CRITICAL/WARNING/INFO/GOOD prefixes in review output."""
    lines = []
    for line in text.splitlines():
        if "[CRITICAL]" in line:
            lines.append(f"{RED}{line}{RESET}")
        elif "[WARNING]" in line:
            lines.append(f"{YELLOW}{line}{RESET}")
        elif "[INFO]" in line:
            lines.append(f"{CYAN}{line}{RESET}")
        elif "[GOOD]" in line:
            lines.append(f"{GREEN}{line}{RESET}")
        elif line.startswith("##") or line.startswith("**"):
            lines.append(f"{BOLD}{WHITE}{line}{RESET}")
        elif line.startswith("- ") or line.startswith("* "):
            lines.append(f"{DIM}{line}{RESET}")
        else:
            lines.append(line)
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Command: diagram
# ─────────────────────────────────────────────────────────────────────────────

def extract_python_imports(source: str, module_name: str) -> list[str]:
    """Extract imported module names from Python source."""
    imports = []
    for line in source.splitlines():
        line = line.strip()
        if line.startswith("import "):
            parts = line[7:].split(",")
            for p in parts:
                imports.append(p.strip().split(" as ")[0].strip().split(".")[0])
        elif line.startswith("from "):
            parts = line.split()
            if len(parts) >= 2:
                imports.append(parts[1].split(".")[0])
    return imports


def extract_js_imports(source: str) -> list[str]:
    """Extract imported module names from JS/TS source."""
    imports = []
    for line in source.splitlines():
        line = line.strip()
        # import ... from '...'
        if line.startswith("import ") and "from " in line:
            mod = line.split("from ")[-1].strip().strip("'\"`;")
            imports.append(mod)
        # require('...')
        elif "require(" in line:
            start = line.find("require(") + 8
            end = line.find(")", start)
            if end > start:
                mod = line[start:end].strip("'\"` ")
                imports.append(mod)
    return imports


def sanitize_node(name: str) -> str:
    """Make a Mermaid-safe node name."""
    return name.replace("-", "_").replace(".", "_").replace("/", "_").replace("@", "")


def cmd_diagram(path_str: str) -> None:
    root = Path(path_str).resolve()
    if not root.exists():
        print(f"{RED}[ERROR]{RESET} Path not found: {root}")
        sys.exit(1)

    print_header(f"Dependency Diagram: {root.name}")
    print(f"{DIM}Scanning imports...{RESET}", flush=True)

    edges: set[tuple[str, str]] = set()
    nodes: set[str] = set()
    local_modules: set[str] = set()

    # First pass: collect local module names
    for fpath in walk_tree(root):
        ext = fpath.suffix.lower()
        if ext == ".py":
            rel = fpath.relative_to(root)
            mod_name = str(rel).replace(os.sep, ".").removesuffix(".py")
            local_modules.add(mod_name.split(".")[-1])
            local_modules.add(fpath.stem)
        elif ext in {".js", ".ts", ".tsx", ".jsx"}:
            local_modules.add(fpath.stem)

    # Second pass: build edges
    for fpath in walk_tree(root):
        ext = fpath.suffix.lower()
        try:
            source = fpath.read_text(errors="replace")
        except Exception:
            continue

        rel = str(fpath.relative_to(root))
        src_node = sanitize_node(fpath.stem)
        nodes.add(src_node)

        if ext == ".py":
            raw_imports = extract_python_imports(source, fpath.stem)
        elif ext in {".js", ".ts", ".tsx", ".jsx"}:
            raw_imports = extract_js_imports(source)
        else:
            continue

        for imp in raw_imports:
            # Only include local dependencies (skip stdlib / node_modules)
            clean = sanitize_node(imp.lstrip(".").split("/")[-1])
            if not clean:
                continue
            # Check if it looks like a local import
            is_relative = imp.startswith(".")
            is_local = imp in local_modules or fpath.stem in local_modules
            if is_relative or clean in {sanitize_node(m) for m in local_modules}:
                if clean != src_node:
                    edges.add((src_node, clean))
                    nodes.add(clean)

    # Build Mermaid output
    lines = ["graph TD"]
    for src, dst in sorted(edges):
        lines.append(f"    {src} --> {dst}")

    if not edges:
        lines.append("    %% No local import edges detected")
        lines.append("    NOTE[No inter-module dependencies found]")

    diagram = "\n".join(lines)

    # Save to file
    out_file = Path("bedrock_diagram.mmd")
    out_file.write_text(diagram)

    print(f"\n{BOLD}{CYAN}Mermaid Dependency Graph:{RESET}")
    print(f"{DIM}{'─' * 60}{RESET}")
    print(diagram)
    print(f"{DIM}{'─' * 60}{RESET}")
    print(f"\n{GREEN}Saved to:{RESET} {out_file.resolve()}")
    print(f"{DIM}View at: https://mermaid.live/{RESET}")

    node_count = len(nodes)
    edge_count = len(edges)
    print(f"\n{DIM}Nodes: {node_count}  |  Edges: {edge_count}{RESET}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Command: deps
# ─────────────────────────────────────────────────────────────────────────────

DEP_FILES = [
    "package.json",
    "requirements.txt",
    "pyproject.toml",
    "Cargo.toml",
    "Gemfile",
    "composer.json",
    "go.mod",
]


def parse_package_json(content: str) -> dict[str, list[str]]:
    try:
        data = json.loads(content)
        deps = list(data.get("dependencies", {}).keys())
        dev_deps = list(data.get("devDependencies", {}).keys())
        return {"dependencies": deps, "devDependencies": dev_deps}
    except Exception:
        return {}


def parse_requirements_txt(content: str) -> list[str]:
    lines = []
    for line in content.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def cmd_deps(path_str: str) -> None:
    root = Path(path_str).resolve()
    if not root.exists():
        print(f"{RED}[ERROR]{RESET} Path not found: {root}")
        sys.exit(1)

    print_header(f"Dependency Analysis: {root.name}")

    found_files: dict[str, str] = {}
    for dep_file in DEP_FILES:
        candidate = root / dep_file
        if candidate.exists():
            try:
                found_files[dep_file] = candidate.read_text(errors="replace")
            except Exception:
                pass

    if not found_files:
        print(f"{YELLOW}[WARN]{RESET} No dependency files found in {root}")
        print(f"  Looked for: {', '.join(DEP_FILES)}")
        sys.exit(0)

    # Display found files
    all_deps_summary = []
    for fname, content in found_files.items():
        print(f"\n{BOLD}{CYAN}Found:{RESET} {fname}")
        if fname == "package.json":
            parsed = parse_package_json(content)
            if parsed:
                deps = parsed.get("dependencies", [])
                dev = parsed.get("devDependencies", [])
                print(f"  {GREEN}dependencies ({len(deps)}):{RESET} {', '.join(deps[:8])}{'...' if len(deps) > 8 else ''}")
                print(f"  {DIM}devDependencies ({len(dev)}):{RESET} {', '.join(dev[:8])}{'...' if len(dev) > 8 else ''}")
                all_deps_summary.append(f"package.json dependencies: {', '.join(deps)}")
                all_deps_summary.append(f"package.json devDependencies: {', '.join(dev)}")
        elif fname == "requirements.txt":
            reqs = parse_requirements_txt(content)
            print(f"  {GREEN}packages ({len(reqs)}):{RESET} {', '.join(reqs[:10])}{'...' if len(reqs) > 10 else ''}")
            all_deps_summary.append(f"requirements.txt: {', '.join(reqs)}")
        else:
            # Show raw content preview
            preview = content[:400].replace("\n", " | ")
            print(f"  {DIM}{preview}...{RESET}")
            all_deps_summary.append(f"{fname}:\n{content[:1500]}")

    # Build combined content for AI
    combined = "\n\n".join(
        f"=== {fname} ===\n{content[:2000]}" for fname, content in found_files.items()
    )

    ai_prompt = (
        f"Project: {root.name}\n\n"
        "Dependency files found:\n\n"
        f"{combined}\n\n"
        "Review these dependencies for:\n"
        "1. Known security issues or vulnerabilities\n"
        "2. Outdated packages that should be upgraded\n"
        "3. Unnecessary bloat (redundant or replaceable packages)\n"
        "4. Missing important packages for this type of project\n\n"
        "Give a RISK ASSESSMENT with:\n"
        "- Overall risk level: LOW / MEDIUM / HIGH\n"
        "- Top security concerns\n"
        "- Top 3 actionable recommendations\n"
        "Be specific about package names."
    )

    print(f"\n{DIM}Sending dependencies to AI for risk assessment...{RESET}", flush=True)
    result = ask_ai(ai_prompt)
    print_section("DEPENDENCY RISK ASSESSMENT", colorize_severity(result))
    print()


# ─────────────────────────────────────────────────────────────────────────────
# CLI entrypoint
# ─────────────────────────────────────────────────────────────────────────────

def print_usage() -> None:
    print(f"""
{BOLD}{WHITE}{ICON}  BEDROCK CLI  v{VERSION}{RESET}
{GRAY}{TAG}{RESET}

{BOLD}Usage:{RESET}
  bedrock.py <command> [args]

{BOLD}Commands:{RESET}
  {CYAN}scan{RESET} [path]            Scan a project directory and produce an architecture report
  {CYAN}scaffold{RESET} <type> <name>  Generate project scaffolding
                          Types: {', '.join(sorted(SCAFFOLD_TYPES))}
  {CYAN}review{RESET} <file>           Architecture review of a single file
  {CYAN}diagram{RESET} [path]          Generate a Mermaid dependency diagram
  {CYAN}deps{RESET} [path]             Analyze dependencies for security/staleness
  {CYAN}audit{RESET} [path]            Full security + quality audit of a project
  {CYAN}refactor{RESET} <file>         AI suggests and applies refactoring plan
  {CYAN}test-gen{RESET} <file>         Generate comprehensive unit tests for a file
  {CYAN}migrate{RESET} <desc>          Generate a migration plan (DB, framework, lang)
  {CYAN}compare{RESET} <f1> <f2>       Side-by-side architectural comparison of two files

{BOLD}Examples:{RESET}
  python tools/bedrock.py scan ./my-project
  python tools/bedrock.py scaffold api my-rest-api
  python tools/bedrock.py review src/main.py
  python tools/bedrock.py diagram ./my-project
  python tools/bedrock.py deps ./my-project
  python tools/bedrock.py audit ./my-project
  python tools/bedrock.py refactor src/auth.py
  python tools/bedrock.py test-gen src/utils.py
  python tools/bedrock.py migrate "Django 3.2 to Django 5.0"
  python tools/bedrock.py compare src/old_handler.py src/new_handler.py

{BOLD}Auth:{RESET}
  Set {YELLOW}OPENROUTER_API_KEY{RESET} env var, or write key to {DIM}profiles/default/openrouter_key{RESET}
""")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="bedrock",
        description=f"{ICON} BEDROCK CLI — {TAG}",
        add_help=False,
    )
    parser.add_argument("command", nargs="?", help="Command to run")
    parser.add_argument("args", nargs="*", help="Command arguments")
    parser.add_argument("-h", "--help", action="store_true", help="Show help")
    parser.add_argument("-v", "--version", action="store_true", help="Show version")

    opts = parser.parse_args()

    if opts.version:
        print(f"BEDROCK CLI v{VERSION}")
        return

    if opts.help or not opts.command:
        print_usage()
        return

    cmd = opts.command.lower()
    args = opts.args

    if cmd == "scan":
        path = args[0] if args else "."
        cmd_scan(path)

    elif cmd == "scaffold":
        if len(args) < 2:
            print(f"{RED}[ERROR]{RESET} scaffold requires <type> and <name>")
            print(f"  Usage: bedrock.py scaffold <type> <name>")
            print(f"  Types: {', '.join(sorted(SCAFFOLD_TYPES))}")
            sys.exit(1)
        cmd_scaffold(args[0], args[1])

    elif cmd == "review":
        if not args:
            print(f"{RED}[ERROR]{RESET} review requires a file path")
            print(f"  Usage: bedrock.py review <file>")
            sys.exit(1)
        cmd_review(args[0])

    elif cmd == "diagram":
        path = args[0] if args else "."
        cmd_diagram(path)

    elif cmd == "deps":
        path = args[0] if args else "."
        cmd_deps(path)

    elif cmd == "audit":
        path = args[0] if args else "."
        cmd_audit(path)

    elif cmd == "refactor":
        if not args:
            print(f"{RED}[ERROR]{RESET} refactor requires a file path")
            sys.exit(1)
        cmd_refactor(args[0])

    elif cmd in ("test-gen", "testgen", "tests"):
        if not args:
            print(f"{RED}[ERROR]{RESET} test-gen requires a file path")
            sys.exit(1)
        cmd_test_gen(args[0])

    elif cmd == "migrate":
        if not args:
            print(f"{RED}[ERROR]{RESET} migrate requires a description, e.g. 'Django 3 to Django 5'")
            sys.exit(1)
        cmd_migrate(" ".join(args))

    elif cmd == "compare":
        if len(args) < 2:
            print(f"{RED}[ERROR]{RESET} compare requires two file paths")
            sys.exit(1)
        cmd_compare(args[0], args[1])

    else:
        print(f"{RED}[ERROR]{RESET} Unknown command: {cmd!r}")
        print_usage()
        sys.exit(1)


# ── New commands (v2) ─────────────────────────────────────────────────────────

def _read_file_safe(path: str, max_chars: int = 8000) -> tuple[str, str]:
    """Returns (content, lang_hint). Truncates if too large."""
    p = Path(path)
    if not p.exists():
        return "", ""
    ext = p.suffix.lstrip(".")
    try:
        raw = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return "", ext
    if len(raw) > max_chars:
        raw = raw[:max_chars] + f"\n... [truncated — {len(raw):,} total chars]"
    return raw, ext


def cmd_audit(path: str) -> None:
    """Full security + quality audit of a project directory."""
    root = Path(path).resolve()
    print(f"\n{BOLD}{WHITE}{ICON} BEDROCK AUDIT{RESET}  {DIM}{root}{RESET}\n")

    # Collect source files
    files_found = []
    for f in root.rglob("*"):
        if f.is_file() and f.suffix in EXT_LANG and not any(d in f.parts for d in SKIP_DIRS):
            files_found.append(f)

    # Sample up to 15 files
    sample = files_found[:15]
    combined = ""
    for f in sample:
        try:
            content = f.read_text(encoding="utf-8", errors="replace")[:1500]
            combined += f"\n=== {f.relative_to(root)} ===\n{content}\n"
        except Exception:
            pass

    print(f"  {DIM}Auditing {len(files_found)} source files (sampling {len(sample)})…{RESET}\n")

    prompt = (
        f"Security and quality audit of project at {root}.\n\n"
        f"Sampled source files:\n{combined[:8000]}\n\n"
        "Produce a comprehensive audit report with these EXACT sections:\n\n"
        "## SECURITY VULNERABILITIES\n"
        "List each vulnerability: [CRITICAL/HIGH/MEDIUM/LOW] filename:line — description — fix\n\n"
        "## CODE QUALITY ISSUES\n"
        "List each issue: [HIGH/MEDIUM/LOW] filename — issue — recommendation\n\n"
        "## DEPENDENCY RISKS\n"
        "Any risky patterns around dependencies, env vars, secrets.\n\n"
        "## MISSING SAFEGUARDS\n"
        "What's absent: input validation, auth, rate limiting, error handling, logging.\n\n"
        "## AUDIT SCORE\n"
        "Overall score 0-100 with brief justification.\n\n"
        "## TOP 5 ACTIONS\n"
        "The 5 highest-priority fixes, ordered by impact."
    )

    result = ask_ai(prompt, "You are a senior security engineer and code auditor. Be specific with file paths and line numbers where possible.")
    _print_colored_sections(result)


def cmd_refactor(file_path: str) -> None:
    """AI suggests a refactoring plan and offers to apply it."""
    content, ext = _read_file_safe(file_path)
    if not content:
        print(f"{RED}[ERROR]{RESET} Cannot read file: {file_path}")
        return

    print(f"\n{BOLD}{WHITE}{ICON} BEDROCK REFACTOR{RESET}  {DIM}{file_path}{RESET}\n")
    print(f"  {DIM}Analyzing {len(content):,} chars…{RESET}\n")

    prompt = (
        f"File to refactor ({ext}):\n\n```{ext}\n{content}\n```\n\n"
        "Produce a detailed refactoring plan:\n\n"
        "## ISSUES FOUND\n"
        "List each issue with exact location (line number), type, and severity.\n\n"
        "## REFACTORING STEPS\n"
        "Numbered steps in priority order. Each step: what to change, why, and example.\n\n"
        "## REFACTORED CODE\n"
        "Provide the complete refactored version of the file. Full file, no truncation.\n\n"
        "## BEFORE / AFTER SUMMARY\n"
        "Key metrics: lines changed, complexity reduction, patterns applied."
    )

    result = ask_ai(
        prompt,
        f"You are a senior software engineer specializing in {ext or 'software'} refactoring. "
        "Produce complete, runnable refactored code."
    )

    # Split to extract code block
    import re
    _print_colored_sections(result)

    code_match = re.search(r"## REFACTORED CODE\n```(?:\w+)?\n(.*?)```", result, re.DOTALL)
    if code_match:
        refactored = code_match.group(1).strip()
        print(f"\n  {CYAN}{BOLD}Refactored code ready.{RESET}")
        confirm = input(f"  Save to {file_path}? (y/n/new-filename): ").strip()
        if confirm.lower() == "y":
            Path(file_path).write_text(refactored, encoding="utf-8")
            print(f"  {GREEN}✓ Saved to {file_path}{RESET}")
        elif confirm and confirm.lower() != "n":
            Path(confirm).write_text(refactored, encoding="utf-8")
            print(f"  {GREEN}✓ Saved to {confirm}{RESET}")


def cmd_test_gen(file_path: str) -> None:
    """Generate comprehensive unit tests for a source file."""
    content, ext = _read_file_safe(file_path)
    if not content:
        print(f"{RED}[ERROR]{RESET} Cannot read file: {file_path}")
        return

    p = Path(file_path)
    print(f"\n{BOLD}{WHITE}{ICON} BEDROCK TEST-GEN{RESET}  {DIM}{file_path}{RESET}\n")

    # Detect test framework from existing files
    test_fw = "pytest"
    if (p.parent / "package.json").exists() or ext in ("js", "ts", "jsx", "tsx"):
        test_fw = "Jest"
    elif ext in ("rs",):
        test_fw = "Rust built-in tests"
    elif ext in ("go",):
        test_fw = "Go testing package"

    print(f"  {DIM}Generating {test_fw} tests for {p.name}…{RESET}\n")

    prompt = (
        f"Source file ({ext}):\n\n```{ext}\n{content}\n```\n\n"
        f"Generate comprehensive {test_fw} unit tests for this file.\n\n"
        "Requirements:\n"
        "1. Test every public function/method/class\n"
        "2. Cover: happy path, edge cases, error cases, boundary conditions\n"
        "3. Use mocks/stubs for external dependencies\n"
        "4. Write descriptive test names that explain what is being tested\n"
        "5. Group tests logically (by function/class)\n"
        "6. Include setup/teardown where needed\n"
        "7. Target ≥90% code coverage\n\n"
        "Output ONLY the complete test file. No explanation."
    )

    result = ask_ai(
        prompt,
        f"You are a senior test engineer expert in {test_fw}. Write thorough, idiomatic tests."
    )

    # Suggest test file name
    stem = p.stem
    if ext == "py":
        test_name = f"test_{stem}.py"
    elif ext in ("js", "ts"):
        test_name = f"{stem}.test.{ext}"
    elif ext == "go":
        test_name = f"{stem}_test.go"
    elif ext == "rs":
        test_name = f"{stem}_tests.rs"
    else:
        test_name = f"test_{stem}.{ext}"

    print(result)
    print(f"\n  {CYAN}Suggested file: {test_name}{RESET}")
    confirm = input(f"  Save tests? (y / new-filename / n): ").strip()
    if confirm.lower() == "y":
        (p.parent / test_name).write_text(result, encoding="utf-8")
        print(f"  {GREEN}✓ Saved to {p.parent / test_name}{RESET}")
    elif confirm and confirm.lower() != "n":
        Path(confirm).write_text(result, encoding="utf-8")
        print(f"  {GREEN}✓ Saved to {confirm}{RESET}")


def cmd_migrate(description: str) -> None:
    """Generate a migration plan for framework, database, or language version changes."""
    print(f"\n{BOLD}{WHITE}{ICON} BEDROCK MIGRATE{RESET}  {DIM}{description}{RESET}\n")

    # Try to gather context from current directory
    context_files = []
    for marker in ["package.json", "requirements.txt", "pyproject.toml", "Cargo.toml", "go.mod"]:
        p = Path(marker)
        if p.exists():
            try:
                context_files.append(f"=== {marker} ===\n{p.read_text()[:1000]}")
            except Exception:
                pass

    ctx = "\n".join(context_files) if context_files else "No project files found in current directory."

    print(f"  {DIM}Generating migration plan…{RESET}\n")

    prompt = (
        f"Migration request: {description}\n\n"
        f"Project context:\n{ctx}\n\n"
        "Create a comprehensive, step-by-step migration plan:\n\n"
        "## MIGRATION OVERVIEW\n"
        "What's changing, why it matters, expected effort (hours/days).\n\n"
        "## PRE-MIGRATION CHECKLIST\n"
        "What to do before starting (backups, tests, deps, CI).\n\n"
        "## BREAKING CHANGES\n"
        "All API/behavior changes that will break existing code. Show old → new syntax.\n\n"
        "## MIGRATION STEPS\n"
        "Numbered steps in order. Each step: command(s) to run + what changes.\n\n"
        "## FILE CHANGES\n"
        "Files most likely to need manual changes with specific examples.\n\n"
        "## AUTOMATED CODEMODS\n"
        "Any tools (codemods, migration scripts) that can automate parts of this.\n\n"
        "## TESTING THE MIGRATION\n"
        "How to verify the migration succeeded.\n\n"
        "## ROLLBACK PLAN\n"
        "How to undo the migration if something goes wrong.\n\n"
        "## ESTIMATED TIMELINE\n"
        "Small/medium/large project estimates."
    )

    result = ask_ai(
        prompt,
        "You are an expert software architect with deep migration experience. Be specific with exact commands and file paths."
    )

    _print_colored_sections(result)

    # Offer to save as markdown
    ts = datetime.now().strftime("%Y%m%d_%H%M%S") if "datetime" in dir() else "plan"
    import datetime as dt_mod
    ts = dt_mod.datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"migration_plan_{ts}.md"
    confirm = input(f"\n  Save migration plan to {fname}? (y/n): ").strip().lower()
    if confirm == "y":
        Path(fname).write_text(f"# Migration Plan: {description}\n\n{result}", encoding="utf-8")
        print(f"  {GREEN}✓ Saved to {fname}{RESET}")


def cmd_compare(file1: str, file2: str) -> None:
    """Side-by-side architectural comparison of two source files."""
    c1, ext1 = _read_file_safe(file1, max_chars=4000)
    c2, ext2 = _read_file_safe(file2, max_chars=4000)

    if not c1:
        print(f"{RED}[ERROR]{RESET} Cannot read: {file1}")
        return
    if not c2:
        print(f"{RED}[ERROR]{RESET} Cannot read: {file2}")
        return

    print(f"\n{BOLD}{WHITE}{ICON} BEDROCK COMPARE{RESET}\n")
    print(f"  {CYAN}A:{RESET} {file1}")
    print(f"  {CYAN}B:{RESET} {file2}\n")

    prompt = (
        f"Compare these two files architecturally:\n\n"
        f"=== FILE A: {file1} ===\n```{ext1}\n{c1}\n```\n\n"
        f"=== FILE B: {file2} ===\n```{ext2}\n{c2}\n```\n\n"
        "Produce a thorough comparison:\n\n"
        "## SIDE-BY-SIDE SUMMARY\n"
        "Brief description of each file's purpose and approach.\n\n"
        "## STRUCTURAL DIFFERENCES\n"
        "How they differ in organization, patterns, abstractions.\n\n"
        "## QUALITY COMPARISON\n"
        "Table: metric | File A | File B\n"
        "Metrics: readability, maintainability, testability, performance, security, complexity\n\n"
        "## WHAT A DOES BETTER\n"
        "Specific advantages of File A.\n\n"
        "## WHAT B DOES BETTER\n"
        "Specific advantages of File B.\n\n"
        "## RECOMMENDATION\n"
        "Which is the better foundation and why. What to borrow from each."
    )

    result = ask_ai(
        prompt,
        "You are a senior software architect. Compare these files with precise technical analysis."
    )

    _print_colored_sections(result)


def _print_colored_sections(text: str) -> None:
    """Print text with section headers colored."""
    import re
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("## "):
            print(f"\n{BOLD}{CYAN}{stripped}{RESET}")
        elif stripped.startswith("### "):
            print(f"\n{BOLD}{WHITE}{stripped}{RESET}")
        elif re.match(r"^\[CRITICAL\]", stripped):
            print(f"  {RED}{BOLD}{line}{RESET}")
        elif re.match(r"^\[HIGH\]", stripped):
            print(f"  {RED}{line}{RESET}")
        elif re.match(r"^\[MEDIUM\]", stripped):
            print(f"  {YELLOW}{line}{RESET}")
        elif re.match(r"^\[LOW\]", stripped):
            print(f"  {DIM}{line}{RESET}")
        elif re.match(r"^\[GOOD\]", stripped):
            print(f"  {GREEN}{line}{RESET}")
        else:
            print(f"  {line}")


if __name__ == "__main__":
    main()
