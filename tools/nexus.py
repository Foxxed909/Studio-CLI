#!/usr/bin/env python3
"""
NEXUS — API Testing CLI
Brand: NEXUS · 🔌 · Bold cyan · "Test smarter, debug faster"
"""

import sys
import os
import json
import time
import urllib.request
import urllib.error
import urllib.parse
import statistics
from datetime import datetime

VERSION = "1.0"

CYAN   = "\033[36m"
GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

BRAND  = f"{BOLD}{CYAN}🔌 NEXUS{RESET}"
TAGLINE = f"{DIM}Test smarter, debug faster{RESET}"

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
            "HTTP-Referer": "https://github.com/StudioCLI/nexus",
            "X-Title": "NEXUS CLI",
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
# HTTP helper
# ---------------------------------------------------------------------------

def make_request(url: str, method: str = "GET", body: str = "", extra_headers: dict = None):
    method = method.upper()
    data = body.encode() if body else None
    headers = {"User-Agent": f"nexus/{VERSION}"}
    if body:
        headers["Content-Type"] = "application/json"
    if extra_headers:
        headers.update(extra_headers)

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            elapsed = time.time() - start
            status  = resp.status
            resp_headers = dict(resp.headers)
            body_bytes   = resp.read()
            try:
                body_text = body_bytes.decode("utf-8")
            except UnicodeDecodeError:
                body_text = body_bytes.decode("latin-1", errors="replace")
            return status, elapsed, resp_headers, body_text, None
    except urllib.error.HTTPError as e:
        elapsed = time.time() - start
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = ""
        return e.code, elapsed, dict(e.headers), err_body, None
    except Exception as exc:
        elapsed = time.time() - start
        return 0, elapsed, {}, "", str(exc)

# ---------------------------------------------------------------------------
# Status colour
# ---------------------------------------------------------------------------

def color_status(code: int) -> str:
    if 200 <= code < 300:
        return f"{BOLD}{GREEN}{code}{RESET}"
    if 300 <= code < 400:
        return f"{BOLD}{YELLOW}{code}{RESET}"
    if code >= 400:
        return f"{BOLD}{RED}{code}{RESET}"
    return f"{BOLD}{RED}{code}{RESET}"

def color_time(elapsed_ms: float) -> str:
    if elapsed_ms < 200:
        return f"{GREEN}{elapsed_ms:.0f}ms{RESET}"
    if elapsed_ms < 1000:
        return f"{YELLOW}{elapsed_ms:.0f}ms{RESET}"
    return f"{RED}{elapsed_ms:.0f}ms{RESET}"

# ---------------------------------------------------------------------------
# cmd: hit
# ---------------------------------------------------------------------------

def cmd_hit(args):
    if not args:
        print(f"{RED}Usage: nexus hit <url> [method] [--body '<json>'] [--header 'Key: Val']{RESET}")
        sys.exit(1)

    url    = args[0]
    method = "GET"
    body   = ""
    extra_headers = {}

    i = 1
    while i < len(args):
        a = args[i]
        if a == "--body" and i + 1 < len(args):
            body = args[i + 1]; i += 2
        elif a == "--header" and i + 1 < len(args):
            raw = args[i + 1]
            if ":" in raw:
                k, v = raw.split(":", 1)
                extra_headers[k.strip()] = v.strip()
            i += 2
        elif not a.startswith("--"):
            method = a; i += 1
        else:
            i += 1

    print(f"\n{BRAND}  {TAGLINE}")
    print(f"{DIM}{'─'*50}{RESET}")
    print(f"{BOLD}→ {method} {url}{RESET}")
    print()

    status, elapsed, resp_headers, resp_body, err = make_request(url, method, body, extra_headers)

    if err:
        print(f"{RED}Connection error: {err}{RESET}")
        sys.exit(1)

    elapsed_ms = elapsed * 1000
    print(f"  Status : {color_status(status)}")
    print(f"  Time   : {color_time(elapsed_ms)}")
    print(f"  Size   : {DIM}{len(resp_body)} bytes{RESET}")
    print()

    print(f"{BOLD}{CYAN}Headers:{RESET}")
    for k, v in list(resp_headers.items())[:8]:
        print(f"  {DIM}{k}:{RESET} {v}")
    print()

    print(f"{BOLD}{CYAN}Body (truncated to 2000 chars):{RESET}")
    preview = resp_body[:2000]
    try:
        parsed = json.loads(resp_body)
        preview = json.dumps(parsed, indent=2)[:2000]
    except Exception:
        pass
    print(preview)
    if len(resp_body) > 2000:
        print(f"{DIM}... ({len(resp_body) - 2000} more bytes){RESET}")
    print()

    api_key = load_api_key()
    prompt = (
        f"Analyze this API response:\n"
        f"Status: {status}\n"
        f"Response time: {elapsed_ms:.0f}ms\n"
        f"Body (truncated): {resp_body[:1500]}\n\n"
        f"Is this response correct? Any issues? What does it mean? Keep it concise."
    )
    print(f"{BOLD}{CYAN}🤖 AI Analysis:{RESET}")
    print(ask_ai(prompt, api_key))
    print()

# ---------------------------------------------------------------------------
# cmd: mock
# ---------------------------------------------------------------------------

def cmd_mock(args):
    if not args:
        print(f"{RED}Usage: nexus mock <description>{RESET}")
        sys.exit(1)

    description = " ".join(args)
    api_key = load_api_key()

    print(f"\n{BRAND}  {TAGLINE}")
    print(f"{DIM}{'─'*50}{RESET}")
    print(f"{BOLD}Generating mock response for:{RESET} {description}")
    print()

    prompt = (
        f"Generate a realistic mock JSON API response for: {description}. "
        f"Return ONLY valid JSON, no explanation, no markdown fences."
    )
    raw = ask_ai(prompt, api_key)

    # strip possible markdown fences
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])

    try:
        parsed = json.loads(raw)
        pretty = json.dumps(parsed, indent=2)
    except json.JSONDecodeError:
        print(f"{YELLOW}Warning: AI returned non-JSON. Raw output:{RESET}")
        print(raw)
        return

    print(f"{BOLD}{CYAN}Mock Response:{RESET}")
    print(pretty)
    print()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"nexus_mock_{ts}.json"
    with open(filename, "w") as f:
        f.write(pretty + "\n")
    print(f"{GREEN}✓ Saved to {filename}{RESET}")
    print()

# ---------------------------------------------------------------------------
# cmd: test
# ---------------------------------------------------------------------------

def cmd_test(args):
    if not args:
        print(f"{RED}Usage: nexus test <url>{RESET}")
        sys.exit(1)

    url = args[0]
    api_key = load_api_key()

    print(f"\n{BRAND}  {TAGLINE}")
    print(f"{DIM}{'─'*50}{RESET}")
    print(f"{BOLD}API Health Check:{RESET} {url}")
    print()

    results = {}
    for method in ("GET", "HEAD", "OPTIONS"):
        print(f"  {DIM}→ {method}...{RESET}", end="", flush=True)
        status, elapsed, headers, body, err = make_request(url, method)
        elapsed_ms = elapsed * 1000
        results[method] = {
            "status": status,
            "elapsed_ms": elapsed_ms,
            "headers": headers,
            "body": body,
            "error": err,
        }
        if err:
            print(f"\r  {method:<8} {RED}ERROR: {err}{RESET}")
        else:
            print(f"\r  {method:<8} {color_status(status)}  {color_time(elapsed_ms)}")

    print()
    print(f"{BOLD}{CYAN}Checks:{RESET}")

    get = results.get("GET", {})
    elapsed_ms = get.get("elapsed_ms", 9999)
    if elapsed_ms < 200:
        speed_label = f"{GREEN}Fast (<200ms){RESET}"
    elif elapsed_ms < 1000:
        speed_label = f"{YELLOW}OK (<1000ms){RESET}"
    else:
        speed_label = f"{RED}Slow (>1000ms){RESET}"
    print(f"  Response Speed   : {speed_label}  ({elapsed_ms:.0f}ms)")

    headers_get = get.get("headers", {})
    cors_val = headers_get.get("Access-Control-Allow-Origin", headers_get.get("access-control-allow-origin", ""))
    if cors_val:
        print(f"  CORS             : {GREEN}Present{RESET}  ({cors_val})")
    else:
        print(f"  CORS             : {YELLOW}Not detected{RESET}")

    auth_hint = any(k.lower() in ("www-authenticate", "authorization") for k in headers_get)
    if auth_hint:
        print(f"  Auth Headers     : {GREEN}Present{RESET}")
    else:
        print(f"  Auth Headers     : {DIM}None detected{RESET}")

    ct = headers_get.get("Content-Type", headers_get.get("content-type", ""))
    if "application/json" in ct:
        print(f"  Content-Type     : {GREEN}application/json ✓{RESET}")
    elif ct:
        print(f"  Content-Type     : {YELLOW}{ct}{RESET}")
    else:
        print(f"  Content-Type     : {DIM}Not set{RESET}")

    print()
    summary_parts = []
    for method, r in results.items():
        if r["error"]:
            summary_parts.append(f"{method}: ERROR ({r['error']})")
        else:
            summary_parts.append(f"{method}: {r['status']} in {r['elapsed_ms']:.0f}ms")
    summary_str = ", ".join(summary_parts)

    prompt = (
        f"I ran an API health check on {url}. Results: {summary_str}. "
        f"CORS: {'present' if cors_val else 'absent'}. "
        f"Content-Type: {ct or 'not set'}. "
        f"Summarize the API health briefly. Note any concerns."
    )
    print(f"{BOLD}{CYAN}🤖 AI Summary:{RESET}")
    print(ask_ai(prompt, api_key))
    print()

# ---------------------------------------------------------------------------
# cmd: docs
# ---------------------------------------------------------------------------

def cmd_docs(args):
    if not args:
        print(f"{RED}Usage: nexus docs <url>{RESET}")
        sys.exit(1)

    url = args[0]
    api_key = load_api_key()

    print(f"\n{BRAND}  {TAGLINE}")
    print(f"{DIM}{'─'*50}{RESET}")
    print(f"{BOLD}Generating docs for:{RESET} {url}")
    print()

    status, elapsed, headers, body, err = make_request(url, "GET")
    if err:
        print(f"{RED}Connection error: {err}{RESET}")
        sys.exit(1)

    elapsed_ms = elapsed * 1000
    print(f"  Status : {color_status(status)}   Time: {color_time(elapsed_ms)}")
    print()

    prompt = (
        f"Based on this API response from {url}:\n"
        f"Status: {status}\n"
        f"Headers: {json.dumps(dict(list(headers.items())[:10]))}\n"
        f"Body (truncated): {body[:1500]}\n\n"
        f"Write OpenAPI-style documentation including: endpoint URL, HTTP method, "
        f"response schema (inferred from JSON if possible), example request and response, "
        f"common errors. Format it cleanly in Markdown."
    )
    docs = ask_ai(prompt, api_key)

    print(f"{BOLD}{CYAN}Generated Documentation:{RESET}")
    print()
    print(docs)
    print()

    answer = input(f"{YELLOW}Save documentation? [y/N]: {RESET}").strip().lower()
    if answer == "y":
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"nexus_docs_{ts}.md"
        with open(filename, "w") as f:
            f.write(f"# API Documentation\n\nGenerated by NEXUS for `{url}`\n\n")
            f.write(docs + "\n")
        print(f"{GREEN}✓ Saved to {filename}{RESET}")
    print()

# ---------------------------------------------------------------------------
# cmd: load
# ---------------------------------------------------------------------------

def cmd_load(args):
    if not args:
        print(f"{RED}Usage: nexus load <url> [--count 10]{RESET}")
        sys.exit(1)

    url = args[0]
    count = 10

    i = 1
    while i < len(args):
        if args[i] == "--count" and i + 1 < len(args):
            try:
                count = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        else:
            i += 1

    api_key = load_api_key()

    print(f"\n{BRAND}  {TAGLINE}")
    print(f"{DIM}{'─'*50}{RESET}")
    print(f"{BOLD}Load Test:{RESET} {url}  ({count} requests)")
    print()

    times   = []
    statuses = {}
    errors  = 0

    for idx in range(1, count + 1):
        print(f"  {DIM}[{idx}/{count}]{RESET}", end=" ", flush=True)
        status, elapsed, _, _, err = make_request(url, "GET")
        elapsed_ms = elapsed * 1000

        if err:
            errors += 1
            print(f"{RED}ERROR{RESET}")
        else:
            times.append(elapsed_ms)
            statuses[status] = statuses.get(status, 0) + 1
            print(f"{color_status(status)}  {color_time(elapsed_ms)}")

    print()
    print(f"{BOLD}{CYAN}Results:{RESET}")

    if times:
        mn  = min(times)
        mx  = max(times)
        avg = statistics.mean(times)
        sorted_times = sorted(times)
        p95_idx = int(len(sorted_times) * 0.95)
        p95 = sorted_times[min(p95_idx, len(sorted_times) - 1)]

        print(f"  Min     : {color_time(mn)}")
        print(f"  Max     : {color_time(mx)}")
        print(f"  Avg     : {color_time(avg)}")
        print(f"  p95     : {color_time(p95)}")
    else:
        print(f"  {RED}No successful requests{RESET}")

    success = count - errors
    rate    = success / count * 100
    rate_color = GREEN if rate == 100 else (YELLOW if rate >= 80 else RED)
    print(f"  Success : {rate_color}{success}/{count} ({rate:.0f}%){RESET}")

    if statuses:
        print(f"  Codes   : {DIM}{statuses}{RESET}")
    if errors:
        print(f"  Errors  : {RED}{errors}{RESET}")

    print()

    summary = (
        f"URL: {url}, Requests: {count}, "
        f"Min: {min(times):.0f}ms, Max: {max(times):.0f}ms, Avg: {avg:.0f}ms, p95: {p95:.0f}ms, "
        f"Success rate: {rate:.0f}%, Status codes: {statuses}, Errors: {errors}"
    ) if times else f"URL: {url}, all {count} requests failed with errors."

    prompt = (
        f"Given these load test results: {summary}\n"
        f"What are the performance concerns and recommendations? Be specific and concise."
    )
    print(f"{BOLD}{CYAN}🤖 AI Analysis:{RESET}")
    print(ask_ai(prompt, api_key))
    print()

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

def print_help():
    print(f"""
{BRAND}  {TAGLINE}  v{VERSION}

{BOLD}Usage:{RESET}
  nexus <command> [args]

{BOLD}{CYAN}Commands:{RESET}
  {BOLD}hit{RESET}  <url> [method] [--body '<json>'] [--header 'Key: Val']
         Make an HTTP request and get AI analysis of the response

  {BOLD}mock{RESET} <description>
         Generate a realistic mock API response and save to JSON

  {BOLD}test{RESET} <url>
         Run an API health check suite (timing, CORS, auth, content-type)

  {BOLD}docs{RESET} <url>
         Generate OpenAPI-style documentation from a live response

  {BOLD}load{RESET} <url> [--count 10]
         Sequential load test with latency stats and AI recommendations

{BOLD}Examples:{RESET}
  nexus hit https://api.example.com/users
  nexus hit https://api.example.com/users POST --body '{{"name":"Alice"}}'
  nexus mock "user profile endpoint with avatar and preferences"
  nexus test https://api.example.com/health
  nexus docs https://api.example.com/products
  nexus load https://api.example.com/ping --count 20

{BOLD}Config:{RESET}
  Set OPENROUTER_API_KEY env var, or place key in profiles/default/openrouter_key
""")

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

COMMANDS = {
    "hit":  cmd_hit,
    "mock": cmd_mock,
    "test": cmd_test,
    "docs": cmd_docs,
    "load": cmd_load,
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
