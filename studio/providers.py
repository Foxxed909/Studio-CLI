"""
All AI provider call functions for StudioCLI.
Handles Gemini, OpenRouter (+ streaming), Cursor, Ollama, Gemini CLI.
"""
import json
import subprocess
import shutil
import time
from urllib import request, error as urllib_error

from studio.console import console
from studio.data import API_BASE, OPENROUTER_BASE, CURSOR_RUNS_BASE, OLLAMA_BASE


# ── GEMINI (Google REST) ──────────────────────────────────────────────────────
def call_gemini(api_key, model, history, prompt, system_prompt=None, _retry=0):
    url      = f"{API_BASE}/{model}:generateContent"
    contents = [{"role": m["role"], "parts": [{"text": m["text"]}]} for m in history]
    contents.append({"role": "user", "parts": [{"text": prompt}]})
    body = {"contents": contents}
    if system_prompt:
        body["systemInstruction"] = {"parts": [{"text": system_prompt}]}
    payload = json.dumps(body).encode()
    req = request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json", "X-goog-api-key": api_key},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
        candidates = data.get("candidates") or []
        if not candidates:
            reason = (data.get("promptFeedback") or {}).get("blockReason", "unknown")
            return None, f"Gemini blocked the response (reason: {reason}). Try rephrasing."
        cand  = candidates[0]
        parts = (cand.get("content") or {}).get("parts") or []
        if not parts:
            finish = cand.get("finishReason", "unknown")
            return None, f"Gemini returned an empty response (finishReason: {finish})."
        return parts[0].get("text", ""), None
    except urllib_error.HTTPError as e:
        body2 = e.read().decode()
        if e.code in (429, 503) and _retry < 3:
            wait = 2 ** _retry
            console.print(f"[dim yellow]⏳ Rate limited — retrying in {wait}s ({_retry+1}/3)…[/dim yellow]")
            time.sleep(wait)
            return call_gemini(api_key, model, history, prompt, system_prompt, _retry + 1)
        if e.code in (401, 403):
            return None, "Invalid or expired API key — run /setup to update it."
        try:
            msg = json.loads(body2)["error"]["message"]
        except Exception:
            msg = body2
        return None, msg
    except Exception as e:
        return None, str(e)


def _or_msg_content(message):
    return message.get("text", message.get("content", ""))


def _positive_int(value, default=0):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


# ── OPENROUTER (REST) ─────────────────────────────────────────────────────────
def call_openrouter(api_key, model, history, prompt, system_prompt=None,
                    fast_mode=False, thinking_budget=0, max_tokens=None, _retry=0):
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    for m in history:
        messages.append({"role": "assistant" if m["role"] == "model" else m["role"], "content": _or_msg_content(m)})
    messages.append({"role": "user", "content": prompt})
    body = {"model": model, "messages": messages}
    thinking_budget = _positive_int(thinking_budget)
    if thinking_budget:
        body["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
    if max_tokens is not None:
        body["max_tokens"] = _positive_int(max_tokens, 4096)
    elif fast_mode:
        body["max_tokens"] = 512
    elif thinking_budget:
        body["max_tokens"] = 8192
    payload = json.dumps(body).encode()
    req = request.Request(OPENROUTER_BASE, data=payload, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://github.com/aistudio-cli",
        "X-Title": "AI Studio CLI",
    }, method="POST")
    try:
        with request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
        choices = data.get("choices") or []
        if not choices:
            err = (data.get("error") or {}).get("message", "empty response")
            return None, f"OpenRouter returned no choices: {err}"
        return choices[0]["message"]["content"], None
    except urllib_error.HTTPError as e:
        body = e.read().decode()
        if e.code in (429, 503) and _retry < 3:
            wait = 2 ** _retry
            console.print(f"[dim yellow]⏳ Rate limited — retrying in {wait}s ({_retry+1}/3)…[/dim yellow]")
            time.sleep(wait)
            return call_openrouter(
                api_key, model, history, prompt, system_prompt,
                fast_mode=fast_mode, thinking_budget=thinking_budget,
                max_tokens=max_tokens, _retry=_retry + 1,
            )
        try:
            msg = json.loads(body)["error"]["message"]
        except Exception:
            msg = body
        return None, msg
    except Exception as e:
        return None, str(e)


def call_openrouter_stream(api_key, model, history, prompt, system_prompt=None, fast_mode=False, thinking_budget=0):
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    for m in history:
        messages.append({"role": "assistant" if m["role"] == "model" else m["role"], "content": _or_msg_content(m)})
    messages.append({"role": "user", "content": prompt})
    body = {"model": model, "messages": messages, "stream": True}
    thinking_budget = _positive_int(thinking_budget)
    if thinking_budget:
        body["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
        body["max_tokens"] = 8192
    elif fast_mode:
        body["max_tokens"] = 512
    payload = json.dumps(body).encode()
    req = request.Request(OPENROUTER_BASE, data=payload, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://github.com/aistudio-cli",
        "X-Title": "AI Studio CLI",
    }, method="POST")
    try:
        with request.urlopen(req, timeout=300) as resp:
            for raw in resp:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except Exception:
                    continue
                choice    = (obj.get("choices") or [{}])[0]
                delta_obj = choice.get("delta") or {}
                content   = delta_obj.get("content")
                reasoning = delta_obj.get("reasoning") or delta_obj.get("reasoning_content")
                if reasoning:
                    yield None, None, reasoning
                if content:
                    yield content, None, None
        yield None, None, None
    except urllib_error.HTTPError as e:
        body = e.read().decode()
        try:
            msg = json.loads(body).get("error", {}).get("message") or body
        except Exception:
            msg = body
        yield None, msg, None
    except Exception as e:
        yield None, str(e), None


# ── CURSOR (REST) ─────────────────────────────────────────────────────────────
def call_cursor(api_key, model, history, prompt, system_prompt=None, stream=False):
    import base64
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    for m in history:
        messages.append({
            "role": "assistant" if m["role"] == "model" else m["role"],
            "content": m["text"],
        })
    messages.append({"role": "user", "content": prompt})
    payload = json.dumps({
        "model":    model or "claude-sonnet-4-5",
        "messages": messages,
        "stream":   False,
    }).encode()
    creds   = base64.b64encode(f"{api_key}:".encode()).decode()
    headers = {
        "Content-Type":  "application/json",
        "Authorization": f"Basic {creds}",
        "User-Agent":    "StudioCLI/5.9",
    }
    url = f"{CURSOR_RUNS_BASE}/chat/completions"
    try:
        req = request.Request(url, data=payload, headers=headers, method="POST")
        with request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
        choices = data.get("choices") or []
        if not choices:
            err = (data.get("error") or {}).get("message", "empty response")
            return None, f"Cursor API returned no choices: {err}"
        content = choices[0]["message"]["content"]
        return content, None
    except urllib_error.HTTPError as e:
        body = e.read().decode()
        try:
            msg = json.loads(body).get("error", {}).get("message") or body
        except Exception:
            msg = body
        return None, f"Cursor API {e.code}: {msg}"
    except Exception as e:
        return None, str(e)


# ── OLLAMA (local) ────────────────────────────────────────────────────────────
def call_ollama(model, history, prompt, system_prompt=None, stream=False):
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    for m in history:
        messages.append({"role": m["role"], "content": m["text"]})
    messages.append({"role": "user", "content": prompt})
    payload = json.dumps({"model": model, "messages": messages, "stream": stream}).encode()
    req = request.Request(
        OLLAMA_BASE, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if stream:
        def _ollama_stream():
            try:
                with request.urlopen(req, timeout=300) as resp:
                    for raw in resp:
                        line = raw.decode("utf-8", errors="replace").strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except Exception:
                            continue
                        content = (obj.get("message") or {}).get("content") or ""
                        if content:
                            yield content, None, None
                        if obj.get("done"):
                            break
                yield None, None, None
            except Exception as exc:
                yield None, str(exc), None
        return _ollama_stream()
    try:
        with request.urlopen(req, timeout=120) as resp:
            res = json.loads(resp.read().decode())
        return res["message"]["content"], None
    except Exception as exc:
        return None, str(exc)


# ── GEMINI CLI (subprocess) ───────────────────────────────────────────────────
def call_gemini_cli(prompt, sys_prompt=None):
    cli = shutil.which("gemini") or shutil.which("npx")
    if not cli:
        return None, "Gemini CLI not found. Install: npm i -g @google/generative-ai-cli"
    cmd = [cli]
    if cli.endswith("npx"):
        cmd += ["@google/generative-ai-cli"]
    if sys_prompt:
        cmd += ["--system", sys_prompt]
    cmd += ["--prompt", prompt]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return (result.stdout.strip() or None), (result.stderr.strip() or None)
    except subprocess.TimeoutExpired:
        return None, "Gemini CLI timed out after 60s"
    except Exception as e:
        return None, str(e)
