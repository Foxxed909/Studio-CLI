#!/usr/bin/env python3
"""
ORANGE CLI — Squeeze more out of your data
Data processing, quick automations, and pipeline management.
"""

import argparse
import csv
import io
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

VERSION = "1.0"

# ── ANSI colors ────────────────────────────────────────────────────────────────
ORANGE = "\033[33m"
RED    = "\033[31m"
GREEN  = "\033[32m"
CYAN   = "\033[36m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

# ── ASCII art header ───────────────────────────────────────────────────────────
HEADER = f"""{ORANGE}{BOLD}
   ___  ____   _   _   _  ___  ___
  / _ \\|  _ \\ / \\ | \\ | |/ __|| __|
 | | | | |_) / _ \\|  \\| | |  _| _|
 | |_| |  _ / ___ \\ |\\  | |_| | |__
  \\___/|_| /_/   \\_\\_| \\_|\\____\\____|

       🍊  Squeeze more out of your data  🍊
{RESET}{DIM}  v{VERSION} · stdlib only · python 3.12+{RESET}
"""

MAX_FILE_CHARS = 8000

# ── Model & API ────────────────────────────────────────────────────────────────
MODEL = "google/gemini-2.5-flash"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def get_api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if key:
        return key
    key_path = Path("profiles/default/openrouter_key")
    if key_path.exists():
        return key_path.read_text().strip()
    print(f"{RED}Error: OPENROUTER_API_KEY not set and profiles/default/openrouter_key not found.{RESET}")
    sys.exit(1)


def ask_ai(prompt: str) -> str:
    """Send prompt to AI via OpenRouter; return text response."""
    api_key = get_api_key()
    payload = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()

    req = urllib.request.Request(
        OPENROUTER_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/orange-cli",
            "X-Title": "ORANGE CLI",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
            return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        print(f"{RED}API error {e.code}: {body[:300]}{RESET}")
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"{RED}Network error: {e.reason}{RESET}")
        sys.exit(1)


# ── File reader ────────────────────────────────────────────────────────────────

def read_file_smart(path: str) -> tuple[str, str]:
    """Returns (content_for_ai, display_summary). Handles CSV/JSON/text."""
    p = Path(path)
    if not p.exists():
        print(f"{RED}File not found: {path}{RESET}")
        sys.exit(1)

    ext = p.suffix.lower()
    raw = p.read_text(errors="replace")

    if len(raw) > MAX_FILE_CHARS:
        content = raw[:MAX_FILE_CHARS] + f"\n...[truncated — {len(raw)} total chars]"
    else:
        content = raw

    if ext == ".csv":
        reader = csv.DictReader(io.StringIO(raw[:2000]))
        rows = list(reader)[:3]
        cols = reader.fieldnames or []
        total_lines = len(raw.splitlines())
        summary = (
            f"CSV: {total_lines} rows × {len(cols)} cols\n"
            f"Columns: {', '.join(cols)}\n"
            "Sample:\n"
        )
        for r in rows:
            summary += "  " + str(dict(list(r.items())[:5])) + "\n"
        return content, summary

    elif ext == ".json":
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                first_keys = list(data[0].keys()) if data and isinstance(data[0], dict) else ["?"]
                summary = (
                    f"JSON array: {len(data)} items\n"
                    f"First item keys: {', '.join(str(k) for k in first_keys[:10])}"
                )
            elif isinstance(data, dict):
                summary = (
                    f"JSON object: {len(data)} keys\n"
                    f"Keys: {', '.join(str(k) for k in list(data.keys())[:10])}"
                )
            else:
                summary = f"JSON {type(data).__name__}"
            return content, summary
        except Exception:
            return content, f"JSON (parse error) — {len(raw)} chars"

    elif ext == ".log":
        lines = raw.splitlines()
        levels = {"ERROR": 0, "WARN": 0, "WARNING": 0, "INFO": 0, "DEBUG": 0}
        for line in lines:
            up = line.upper()
            for lvl in levels:
                if lvl in up:
                    levels[lvl] += 1
                    break
        lvl_str = "  ".join(f"{k}:{v}" for k, v in levels.items() if v)
        summary = f"Log: {len(lines)} lines\nLevels: {lvl_str or 'unknown'}"
        return content, summary

    else:
        lines = raw.splitlines()
        words = len(raw.split())
        paragraphs = len([b for b in raw.split("\n\n") if b.strip()])
        summary = f"Text: {len(lines)} lines, {words} words, {paragraphs} paragraphs"
        return content, summary


# ── ASCII table helper ─────────────────────────────────────────────────────────

def draw_table(headers: list[str], rows: list[list[str]]) -> str:
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(str(cell)))

    def fmt_row(cells: list[str]) -> str:
        parts = []
        for i, cell in enumerate(cells):
            w = col_widths[i] if i < len(col_widths) else len(str(cell))
            parts.append(str(cell).ljust(w))
        return "| " + " | ".join(parts) + " |"

    sep = "+-" + "-+-".join("-" * w for w in col_widths) + "-+"
    lines = [sep, fmt_row(headers), sep]
    for row in rows:
        lines.append(fmt_row(row))
    lines.append(sep)
    return "\n".join(lines)


# ── Commands ───────────────────────────────────────────────────────────────────

def cmd_squeeze(args: argparse.Namespace) -> None:
    """AI-powered data summarization."""
    print(HEADER)
    file_path = args.file
    print(f"{CYAN}{BOLD}squeeze{RESET} {DIM}→{RESET} {file_path}\n")

    content, display_summary = read_file_smart(file_path)

    print(f"{ORANGE}{BOLD}File Summary{RESET}")
    print(f"{DIM}{display_summary}{RESET}\n")

    print(f"{DIM}Asking AI for insights…{RESET}\n")
    prompt = (
        f"Summarize this data and extract the 5 most important insights.\n\n"
        f"File: {file_path}\n"
        f"Metadata:\n{display_summary}\n\n"
        f"Content:\n{content}"
    )
    result = ask_ai(prompt)

    print(f"{ORANGE}{BOLD}AI Insights{RESET}")
    print(result)


def cmd_transform(args: argparse.Namespace) -> None:
    """Transform data with AI."""
    print(HEADER)
    file_path = args.file
    instruction = args.instruction
    print(f"{CYAN}{BOLD}transform{RESET} {DIM}→{RESET} {file_path}\n")

    content, display_summary = read_file_smart(file_path)

    print(f"{ORANGE}{BOLD}File Summary{RESET}")
    print(f"{DIM}{display_summary}{RESET}\n")

    print(f"{DIM}Applying transformation: {instruction!r}…{RESET}\n")
    prompt = f"Transform this data: {instruction}\n\nData:\n{content[:4000]}"
    result = ask_ai(prompt)

    print(f"{ORANGE}{BOLD}Transformed Result{RESET}")
    print(result)

    print(f"\n{DIM}Save to output file? (filename or Enter to skip): {RESET}", end="")
    try:
        out_path = input().strip()
    except (EOFError, KeyboardInterrupt):
        out_path = ""

    if out_path:
        Path(out_path).write_text(result)
        print(f"{GREEN}Saved to {out_path}{RESET}")


def cmd_pipeline(args: argparse.Namespace) -> None:
    """Generate a data pipeline script from a description."""
    print(HEADER)
    desc = args.desc
    print(f"{CYAN}{BOLD}pipeline{RESET} {DIM}→{RESET} {desc!r}\n")

    print(f"{DIM}Generating pipeline script…{RESET}\n")
    prompt = (
        f"Generate a complete, runnable Python 3.12 script for this data pipeline:\n\n"
        f"{desc}\n\n"
        f"Requirements:\n"
        f"- Use stdlib only (no third-party dependencies)\n"
        f"- Include a shebang line\n"
        f"- Add clear comments explaining each step\n"
        f"- Make it production-quality with error handling\n"
        f"- Include a __main__ block\n"
        f"Return ONLY the Python script, no explanations outside it."
    )
    result = ask_ai(prompt)

    # Strip markdown code fences if present
    lines = result.strip().splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    script = "\n".join(lines)

    print(f"{ORANGE}{BOLD}Generated Pipeline Script{RESET}")
    for line in script.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            print(f"{DIM}{line}{RESET}")
        elif stripped.startswith(("def ", "class ", "async def ")):
            print(f"{CYAN}{line}{RESET}")
        elif stripped.startswith(("import ", "from ")):
            print(f"{GREEN}{line}{RESET}")
        else:
            print(line)

    print(f"\n{DIM}Save to file? (filename or Enter to skip): {RESET}", end="")
    try:
        out_path = input().strip()
    except (EOFError, KeyboardInterrupt):
        out_path = ""

    if out_path:
        Path(out_path).write_text(script)
        os.chmod(out_path, 0o755)
        print(f"{GREEN}Saved to {out_path} (executable){RESET}")


def cmd_clean(args: argparse.Namespace) -> None:
    """Data cleaning suggestions with severity tags."""
    print(HEADER)
    file_path = args.file
    print(f"{CYAN}{BOLD}clean{RESET} {DIM}→{RESET} {file_path}\n")

    ext = Path(file_path).suffix.lower()
    if ext not in (".csv", ".json"):
        print(f"{RED}Warning: clean works best with CSV or JSON files. Got: {ext}{RESET}")

    content, display_summary = read_file_smart(file_path)

    print(f"{ORANGE}{BOLD}File Summary{RESET}")
    print(f"{DIM}{display_summary}{RESET}\n")

    print(f"{DIM}Analyzing data quality…{RESET}\n")
    prompt = (
        f"Analyze this data for quality issues: missing values, duplicates, inconsistent "
        f"formatting, outliers, type mismatches. List each issue with the column/key affected "
        f"and suggest a fix.\n\n"
        f"For each issue use EXACTLY this format:\n"
        f"[CRITICAL|WARNING|INFO] <column/key>: <description> → Fix: <suggestion>\n\n"
        f"Data ({file_path}):\n{content}"
    )
    result = ask_ai(prompt)

    print(f"{ORANGE}{BOLD}Data Quality Issues{RESET}\n")
    issue_num = 0
    for line in result.splitlines():
        stripped = line.strip()
        if not stripped:
            print()
            continue
        if stripped.startswith("[CRITICAL]"):
            issue_num += 1
            print(f"  {issue_num}. {RED}{BOLD}[CRITICAL]{RESET} {stripped[len('[CRITICAL]'):].strip()}")
        elif stripped.startswith("[WARNING]"):
            issue_num += 1
            print(f"  {issue_num}. {ORANGE}{BOLD}[WARNING]{RESET}  {stripped[len('[WARNING]'):].strip()}")
        elif stripped.startswith("[INFO]"):
            issue_num += 1
            print(f"  {issue_num}. {CYAN}[INFO]{RESET}     {stripped[len('[INFO]'):].strip()}")
        else:
            print(f"     {DIM}{stripped}{RESET}")


def _infer_csv_schema(raw: str) -> tuple[list[str], list[list[str]]]:
    """Infer schema from CSV: returns (headers, table_rows)."""
    reader = csv.DictReader(io.StringIO(raw))
    all_rows = list(reader)
    cols = reader.fieldnames or []

    table_rows = []
    for col in cols:
        values = [r.get(col, "") for r in all_rows if r.get(col, "").strip()]
        nullable = "YES" if any(r.get(col, "").strip() == "" for r in all_rows) else "NO"
        sample = values[0] if values else ""

        # Guess type
        inferred = "string"
        if values:
            try:
                [int(v) for v in values[:20] if v]
                inferred = "integer"
            except ValueError:
                try:
                    [float(v) for v in values[:20] if v]
                    inferred = "float"
                except ValueError:
                    low = [v.lower() for v in values[:20]]
                    if all(v in ("true", "false", "yes", "no", "1", "0") for v in low if v):
                        inferred = "boolean"

        table_rows.append([col, inferred, nullable, str(sample)[:40]])

    return ["Column", "Type", "Nullable", "Example"], table_rows


def _infer_json_schema(data, prefix: str = "") -> list[list[str]]:
    """Recursively infer JSON schema; returns list of [path, type, nullable, example]."""
    rows = []
    if isinstance(data, dict):
        for k, v in list(data.items())[:30]:
            path = f"{prefix}.{k}" if prefix else k
            t = type(v).__name__
            example = str(v)[:40] if not isinstance(v, (dict, list)) else f"[{t}]"
            rows.append([path, t, "?", example])
            if isinstance(v, (dict, list)) and v:
                sub = v if isinstance(v, dict) else (v[0] if v else {})
                rows.extend(_infer_json_schema(sub, path))
    elif isinstance(data, list) and data:
        rows.extend(_infer_json_schema(data[0], prefix + "[0]"))
    return rows


def cmd_schema(args: argparse.Namespace) -> None:
    """Infer and display schema from CSV or JSON."""
    print(HEADER)
    file_path = args.file
    print(f"{CYAN}{BOLD}schema{RESET} {DIM}→{RESET} {file_path}\n")

    p = Path(file_path)
    if not p.exists():
        print(f"{RED}File not found: {file_path}{RESET}")
        sys.exit(1)

    ext = p.suffix.lower()
    raw = p.read_text(errors="replace")

    print(f"{ORANGE}{BOLD}Inferred Schema{RESET}")

    if ext == ".csv":
        headers, rows = _infer_csv_schema(raw)
        print(f"{DIM}Source: CSV  ·  {len(rows)} columns{RESET}\n")
        print(draw_table(headers, rows))

    elif ext == ".json":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"{RED}JSON parse error: {e}{RESET}")
            sys.exit(1)

        if isinstance(data, list):
            print(f"{DIM}Source: JSON array  ·  {len(data)} items{RESET}\n")
            rows = _infer_json_schema(data[0] if data else {})
        else:
            print(f"{DIM}Source: JSON object  ·  {len(data)} keys{RESET}\n")
            rows = _infer_json_schema(data)

        if rows:
            print(draw_table(["Path", "Type", "Nullable", "Example"], rows))
        else:
            print(f"{DIM}(empty or scalar JSON){RESET}")

    else:
        print(f"{RED}schema supports CSV and JSON files only. Got: {ext}{RESET}")
        sys.exit(1)


def cmd_grep_ai(args: argparse.Namespace) -> None:
    """AI-powered semantic search."""
    print(HEADER)
    pattern = args.pattern
    file_path = args.file
    print(f"{CYAN}{BOLD}grep-ai{RESET} {DIM}pattern:{RESET} {pattern!r} {DIM}in{RESET} {file_path}\n")

    content, display_summary = read_file_smart(file_path)

    print(f"{ORANGE}{BOLD}File Summary{RESET}")
    print(f"{DIM}{display_summary}{RESET}\n")

    print(f"{DIM}Running semantic search…{RESET}\n")
    prompt = (
        f"Find all lines/entries that match this semantic pattern: '{pattern}'. "
        f"Quote the exact matching text. Explain why each match is relevant. "
        f"If the file has line numbers (plain text/log), include them.\n\n"
        f"File ({file_path}):\n{content}"
    )
    result = ask_ai(prompt)

    print(f"{ORANGE}{BOLD}Semantic Matches{RESET}\n")
    # Highlight lines that look like quoted matches
    for line in result.splitlines():
        stripped = line.strip()
        if stripped.startswith('"') or stripped.startswith("'"):
            print(f"  {GREEN}{line}{RESET}")
        elif stripped.lower().startswith(("line ", "match", "entry")):
            print(f"  {CYAN}{line}{RESET}")
        elif stripped.startswith(("-", "•", "*")):
            print(f"  {ORANGE}{line}{RESET}")
        else:
            print(f"  {line}")


# ── Main ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orange",
        description=f"{ORANGE}{BOLD}ORANGE CLI{RESET} — Squeeze more out of your data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            f"  {ORANGE}Commands:{RESET}\n"
            f"  {CYAN}squeeze{RESET}    <file>              AI-powered data summarization\n"
            f"  {CYAN}transform{RESET}  <file> <instruction> Transform data with AI\n"
            f"  {CYAN}pipeline{RESET}   <desc>              Generate a data pipeline script\n"
            f"  {CYAN}clean{RESET}      <file>              Data cleaning suggestions\n"
            f"  {CYAN}schema{RESET}     <file>              Infer and display schema (CSV/JSON)\n"
            f"  {CYAN}grep-ai{RESET}    <pattern> <file>    AI-powered semantic search\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"ORANGE CLI v{VERSION}")

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # squeeze
    p_squeeze = sub.add_parser("squeeze", help="AI-powered data summarization")
    p_squeeze.add_argument("file", help="File to summarize (CSV/JSON/log/text)")

    # transform
    p_transform = sub.add_parser("transform", help="Transform data with AI")
    p_transform.add_argument("file", help="Input file")
    p_transform.add_argument("instruction", help="Transformation instruction")

    # pipeline
    p_pipeline = sub.add_parser("pipeline", help="Generate a data pipeline script")
    p_pipeline.add_argument("desc", help="Description of the pipeline to generate")

    # clean
    p_clean = sub.add_parser("clean", help="Data cleaning suggestions")
    p_clean.add_argument("file", help="CSV or JSON file to analyze")

    # schema
    p_schema = sub.add_parser("schema", help="Infer and display schema")
    p_schema.add_argument("file", help="CSV or JSON file")

    # grep-ai
    p_grep = sub.add_parser("grep-ai", help="AI-powered semantic search")
    p_grep.add_argument("pattern", help="Semantic pattern to search for")
    p_grep.add_argument("file", help="File to search in")

    return parser


COMMAND_MAP = {
    "squeeze":  cmd_squeeze,
    "transform": cmd_transform,
    "pipeline": cmd_pipeline,
    "clean":    cmd_clean,
    "schema":   cmd_schema,
    "grep-ai":  cmd_grep_ai,
}


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        print(HEADER)
        parser.print_help()
        sys.exit(0)

    handler = COMMAND_MAP.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    try:
        handler(args)
    except KeyboardInterrupt:
        print(f"\n{DIM}Interrupted.{RESET}")
        sys.exit(130)


if __name__ == "__main__":
    main()
