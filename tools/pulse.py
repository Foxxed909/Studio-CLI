#!/usr/bin/env python3
"""
💓 PULSE CLI — Real-time AI-powered monitoring and alerting.
Watch endpoints. Detect anomalies. Get answers.
"""

import argparse
import json
import os
import sys
import time
import threading
from datetime import datetime
from pathlib import Path
from urllib import request as urllib_req
from urllib import error as urllib_err

VERSION = "1.0.0"

BOLD  = "\033[1m"
DIM   = "\033[2m"
GRN   = "\033[32m"
YEL   = "\033[33m"
RED   = "\033[31m"
CYN   = "\033[36m"
MAG   = "\033[35m"
RESET = "\033[0m"
UP    = "\033[A"
CLEAR = "\033[2K"

OR_BASE      = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "google/gemini-2.5-flash"
PULSE_LOG_DIR = Path.home() / ".pulse" / "logs"


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
            try:
                raw = p.read_text().strip()
                return json.loads(raw).get("key") or raw
            except Exception:
                return p.read_text().strip()
    return None


def ask_ai(prompt: str) -> str:
    key = load_key()
    if not key:
        return "[No API key]"
    payload = json.dumps({
        "model":      DEFAULT_MODEL,
        "messages":   [{"role": "user", "content": prompt}],
        "stream":     False,
        "max_tokens": 512,
    }).encode()
    req = urllib_req.Request(
        OR_BASE, data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}", "X-Title": "PULSE CLI"},
        method="POST",
    )
    try:
        with urllib_req.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())["choices"][0]["message"]["content"]
    except Exception as exc:
        return f"[AI error: {exc}]"


def check_endpoint(url: str, timeout: int = 10) -> dict:
    """Check a single URL. Returns status dict."""
    t0 = time.time()
    try:
        req = urllib_req.Request(url, headers={"User-Agent": "PULSE-CLI/1.0"}, method="GET")
        with urllib_req.urlopen(req, timeout=timeout) as resp:
            body = resp.read(2000)
            return {
                "url":     url,
                "status":  resp.status,
                "ok":      200 <= resp.status < 400,
                "latency": round((time.time() - t0) * 1000),
                "size":    len(body),
                "headers": dict(resp.headers),
                "ts":      datetime.now().isoformat(),
                "error":   None,
            }
    except urllib_err.HTTPError as exc:
        return {
            "url": url, "status": exc.code, "ok": False,
            "latency": round((time.time() - t0) * 1000),
            "size": 0, "headers": {}, "ts": datetime.now().isoformat(),
            "error": str(exc),
        }
    except Exception as exc:
        return {
            "url": url, "status": 0, "ok": False,
            "latency": round((time.time() - t0) * 1000),
            "size": 0, "headers": {}, "ts": datetime.now().isoformat(),
            "error": str(exc),
        }


def status_color(ok: bool, status: int) -> str:
    if ok:
        return GRN
    if status == 0:
        return RED
    return YEL


def latency_color(ms: int) -> str:
    if ms < 200:
        return GRN
    if ms < 1000:
        return YEL
    return RED


def fmt_status(r: dict) -> str:
    sc = status_color(r["ok"], r["status"])
    lc = latency_color(r["latency"])
    st = r["status"] if r["status"] else "ERR"
    tick = "✓" if r["ok"] else "✗"
    err  = f"  {DIM}{r['error'][:60]}{RESET}" if r["error"] else ""
    return (
        f"  {sc}{BOLD}{tick} {st}{RESET}  "
        f"{lc}{r['latency']:>5}ms{RESET}  "
        f"{DIM}{r['size']:>7} bytes{RESET}  "
        f"{r['url'][:55]}{err}"
    )


def log_result(r: dict) -> None:
    PULSE_LOG_DIR.mkdir(parents=True, exist_ok=True)
    day   = datetime.now().strftime("%Y-%m-%d")
    lfile = PULSE_LOG_DIR / f"pulse_{day}.jsonl"
    with lfile.open("a") as f:
        f.write(json.dumps(r) + "\n")


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_watch(urls: list[str], interval: int, count: int) -> None:
    """Continuously poll URLs and display live status."""
    print(f"\n{BOLD}{MAG}💓 PULSE{RESET}  {DIM}v{VERSION} — watching {len(urls)} endpoint(s) · {interval}s interval{RESET}")
    if count:
        print(f"  {DIM}Stopping after {count} checks.{RESET}")
    print(f"  {DIM}Ctrl+C to stop.{RESET}\n")

    checks   = 0
    failures: dict[str, int] = {url: 0 for url in urls}
    start    = time.time()

    try:
        while True:
            checks += 1
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"  {DIM}[{ts}] Check #{checks}{RESET}")

            results = []
            threads = []
            lock    = threading.Lock()

            def _check(u: str):
                r = check_endpoint(u)
                log_result(r)
                with lock:
                    results.append(r)

            for url in urls:
                t = threading.Thread(target=_check, args=(url,))
                threads.append(t)
                t.start()
            for t in threads:
                t.join()

            for r in sorted(results, key=lambda x: x["url"]):
                print(fmt_status(r))
                if not r["ok"]:
                    failures[r["url"]] = failures.get(r["url"], 0) + 1
                else:
                    failures[r["url"]] = 0

                # Alert after 3 consecutive failures
                if failures.get(r["url"], 0) == 3:
                    print(f"\n  {RED}{BOLD}⚠ ALERT: {r['url']} has failed 3 times in a row!{RESET}")
                    ai_note = ask_ai(
                        f"API endpoint alert: {r['url']} returned status {r['status']} "
                        f"with error '{r.get('error','unknown')}'. "
                        "In 2 sentences: what could cause this and what should I check first?"
                    )
                    print(f"  {DIM}AI: {ai_note}{RESET}\n")

            print()
            if count and checks >= count:
                break
            time.sleep(interval)

    except KeyboardInterrupt:
        elapsed = round(time.time() - start)
        print(f"\n  {DIM}Stopped after {checks} checks · {elapsed}s · logs at {PULSE_LOG_DIR}{RESET}\n")


def cmd_check(urls: list[str]) -> None:
    """Single-shot check of one or more URLs."""
    print(f"\n{BOLD}{MAG}💓 PULSE{RESET}  {DIM}Single check{RESET}\n")
    results = []
    threads = []
    lock    = threading.Lock()

    def _check(u: str):
        r = check_endpoint(u)
        log_result(r)
        with lock:
            results.append(r)

    for url in urls:
        t = threading.Thread(target=_check, args=(url,))
        threads.append(t)
        t.start()
    for t in threads:
        t.join()

    all_ok = all(r["ok"] for r in results)
    for r in sorted(results, key=lambda x: x["url"]):
        print(fmt_status(r))

    print(f"\n  {DIM}{'All healthy ✓' if all_ok else 'Issues detected ✗'}{RESET}\n")
    sys.exit(0 if all_ok else 1)


def cmd_analyze(urls: list[str]) -> None:
    """Deep analysis of an endpoint's response, headers, and performance."""
    print(f"\n{BOLD}{MAG}💓 PULSE{RESET}  {DIM}Deep analysis{RESET}\n")
    for url in urls:
        r = check_endpoint(url)
        sc = status_color(r["ok"], r["status"])
        print(f"  {sc}{BOLD}{r['status']}{RESET}  {url}")
        print(f"  {DIM}Latency:  {r['latency']}ms{RESET}")
        print(f"  {DIM}Size:     {r['size']} bytes{RESET}")
        if r["headers"]:
            print(f"  {DIM}Headers:{RESET}")
            important = ["content-type", "cache-control", "x-ratelimit-limit", "retry-after",
                         "cf-ray", "x-request-id", "strict-transport-security", "access-control-allow-origin"]
            for h in important:
                val = r["headers"].get(h) or r["headers"].get(h.title())
                if val:
                    print(f"    {DIM}{h}: {val}{RESET}")
        if r["error"]:
            print(f"  {RED}Error: {r['error']}{RESET}")

        # AI Analysis
        print(f"\n  {DIM}Asking AI…{RESET}")
        summary = (
            f"URL: {url}\n"
            f"Status: {r['status']}\n"
            f"Latency: {r['latency']}ms\n"
            f"Headers: {json.dumps(r['headers'], indent=2)[:800]}\n"
            f"Error: {r.get('error','none')}\n\n"
            "Analyze this HTTP response. Cover: 1) Is this healthy? 2) Performance assessment "
            "(latency benchmarks), 3) Security headers assessment (missing/weak headers), "
            "4) Specific concerns, 5) Top recommendation."
        )
        ai_result = ask_ai(summary)
        print(f"\n  {CYN}{BOLD}AI Analysis:{RESET}\n")
        for line in ai_result.split("\n"):
            print(f"  {line}")
        print()


def cmd_report(days: int = 1) -> None:
    """Generate an AI report from stored pulse logs."""
    print(f"\n{BOLD}{MAG}💓 PULSE{RESET}  {DIM}Report — last {days} day(s){RESET}\n")
    if not PULSE_LOG_DIR.exists():
        print("  No logs found. Run 'pulse watch' first.")
        return

    entries = []
    cutoff  = time.time() - (days * 86400)
    for f in sorted(PULSE_LOG_DIR.glob("*.jsonl"), reverse=True)[:days+1]:
        try:
            for line in f.read_text().splitlines():
                e = json.loads(line)
                if time.mktime(time.strptime(e["ts"][:19], "%Y-%m-%dT%H:%M:%S")) > cutoff:
                    entries.append(e)
        except Exception:
            pass

    if not entries:
        print(f"  No entries in the last {days} day(s).")
        return

    urls     = list({e["url"] for e in entries})
    total    = len(entries)
    failures = [e for e in entries if not e.get("ok")]
    avg_lat  = round(sum(e.get("latency", 0) for e in entries) / max(total, 1))

    print(f"  {DIM}Checks:     {total}{RESET}")
    print(f"  {DIM}Failures:   {len(failures)}{RESET}")
    print(f"  {DIM}Success:    {GRN}{round((total-len(failures))/max(total,1)*100)}%{RESET}")
    print(f"  {DIM}Avg latency:{avg_lat}ms{RESET}")
    print(f"  {DIM}Endpoints:  {', '.join(urls[:5])}{RESET}\n")

    summary = (
        f"Monitoring report — {total} checks over {days} day(s):\n"
        f"- {len(failures)} failures ({round(len(failures)/max(total,1)*100)}% error rate)\n"
        f"- Average latency: {avg_lat}ms\n"
        f"- Endpoints: {', '.join(urls)}\n"
        f"- Failure details: {json.dumps([{'url':f['url'],'status':f['status'],'error':f.get('error','')} for f in failures[:10]])}\n\n"
        "Provide: 1) Overall health assessment, 2) Patterns in failures, 3) Performance concerns, 4) Top 3 action items."
    )
    ai_report = ask_ai(summary)
    print(f"  {CYN}{BOLD}AI Report:{RESET}\n")
    for line in ai_report.split("\n"):
        print(f"  {line}")
    print()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="pulse",
        description=f"💓 PULSE CLI v{VERSION} — AI-powered endpoint monitoring",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  pulse check <url> [url...]          One-shot health check (exit 1 on failure)
  pulse watch <url> [url...] [-i 30]  Continuous polling (default 30s interval)
  pulse analyze <url>                 Deep response + security analysis
  pulse report [--days 7]             AI report from stored logs

Examples:
  pulse check https://api.example.com/health
  pulse watch https://my-app.com https://api.my-app.com -i 60
  pulse analyze https://api.github.com
  pulse report --days 3
""",
    )
    parser.add_argument("command", choices=["check", "watch", "analyze", "report"])
    parser.add_argument("urls",    nargs="*", help="URLs to monitor")
    parser.add_argument("-i", "--interval", type=int, default=30, help="Poll interval in seconds (watch mode)")
    parser.add_argument("-n", "--count",    type=int, default=0,  help="Number of checks (0 = infinite)")
    parser.add_argument("--days", type=int, default=1, help="Days to include in report")
    parser.add_argument("--version", action="store_true")
    parsed = parser.parse_args()

    if parsed.version:
        print(f"PULSE CLI v{VERSION}")
        return

    cmd = parsed.command

    if cmd == "report":
        cmd_report(parsed.days)
        return

    if not parsed.urls:
        print(f"{RED}Usage: pulse {cmd} <url> [url...]{RESET}")
        sys.exit(1)

    urls = parsed.urls

    if cmd == "check":
        cmd_check(urls)
    elif cmd == "watch":
        cmd_watch(urls, parsed.interval, parsed.count)
    elif cmd == "analyze":
        cmd_analyze(urls)


if __name__ == "__main__":
    main()
