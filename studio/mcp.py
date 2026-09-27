"""
Minimal MCP (Model Context Protocol) client for StudioCLI — the Connectors Hub.

Speaks JSON-RPC 2.0 over stdio (newline-delimited) to MCP servers spawned as
subprocesses. Supports the handshake (initialize), tools/list and tools/call.

Config lives at ~/.aistudio/mcp.json:
    {"servers": {"<name>": {"command": "npx", "args": ["-y", "pkg"], "env": {}}}}
"""
import json
import os
import subprocess
import threading
import time
import queue

from studio.paths import CONFIG_DIR

MCP_CONFIG = CONFIG_DIR / "mcp.json"


def load_mcp_config():
    """Return the MCP config dict ({'servers': {...}}). Never raises."""
    try:
        if MCP_CONFIG.exists():
            data = json.loads(MCP_CONFIG.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("servers", {})
                return data
    except Exception:
        pass
    return {"servers": {}}


def save_mcp_config(cfg):
    """Persist the MCP config. Returns True on success."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        MCP_CONFIG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


class MCPClient:
    """A single stdio MCP server connection. Use as a context manager."""

    def __init__(self, command, args=None, env=None, cwd=None):
        self.command = command
        self.args    = list(args or [])
        self.env     = env or {}
        self.cwd     = cwd
        self.proc    = None
        self._id     = 0
        self._lock   = threading.Lock()
        self._stdout_queue = queue.Queue()
        self._reader_thread = None
        self._stderr_thread = None
        self._stderr_lines = []

    # ── lifecycle ──────────────────────────────────────────────────────────
    def start(self, timeout=10):
        full_env = {**os.environ, **{k: str(v) for k, v in self.env.items()}}
        self.proc = subprocess.Popen(
            [self.command, *self.args],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, env=full_env, cwd=self.cwd,
        )
        self._reader_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader_thread.start()
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()
        # MCP handshake
        self._request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "StudioCLI", "version": "9.7"},
        }, timeout=timeout)
        self._notify("notifications/initialized", {})
        return self

    def close(self):
        if self.proc:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=3)
            except Exception:
                try: self.proc.kill()
                except Exception: pass
            self.proc = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.close()

    def _read_stdout(self):
        if not self.proc or not self.proc.stdout:
            return
        try:
            for line in self.proc.stdout:
                self._stdout_queue.put(line)
        finally:
            self._stdout_queue.put(None)

    def _drain_stderr(self):
        if not self.proc or not self.proc.stderr:
            return
        for line in self.proc.stderr:
            clean = line.rstrip()
            if clean:
                self._stderr_lines.append(clean)
                del self._stderr_lines[:-20]

    # ── JSON-RPC plumbing ───────────────────────────────────────────────────
    def _write(self, obj):
        if not self.proc or not self.proc.stdin:
            raise RuntimeError("MCP server is not running")
        self.proc.stdin.write(json.dumps(obj) + "\n")
        self.proc.stdin.flush()

    def _notify(self, method, params):
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def _request(self, method, params, timeout=20):
        with self._lock:
            self._id += 1
            rid = self._id
            self._write({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"MCP request '{method}' timed out after {timeout}s")
                try:
                    line = self._stdout_queue.get(timeout=remaining)
                except queue.Empty:
                    raise TimeoutError(f"MCP request '{method}' timed out after {timeout}s")
                if line is None:
                    detail = " | ".join(self._stderr_lines[-3:])
                    suffix = f": {detail}" if detail else ""
                    raise RuntimeError(f"MCP server exited unexpectedly{suffix}")
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except Exception:
                    continue
                if msg.get("id") == rid:
                    if "error" in msg:
                        raise RuntimeError(msg["error"].get("message", "MCP error"))
                    return msg.get("result", {})
                # Notifications and other request IDs remain ignored because
                # requests are serialized by _lock.


    # ── high-level API ────────────────────────────────────────────────────────
    def list_tools(self):
        return (self._request("tools/list", {}) or {}).get("tools", [])

    def call_tool(self, name, arguments=None):
        return self._request("tools/call", {"name": name, "arguments": arguments or {}})


def connect(name, cfg=None, timeout=10):
    """Open a started MCPClient for the named server from config. Raises on failure."""
    cfg = cfg or load_mcp_config()
    spec = (cfg.get("servers") or {}).get(name)
    if not spec:
        raise KeyError(f"No MCP server named '{name}' in config")
    if not spec.get("command"):
        raise ValueError(f"Server '{name}' has no command")
    return MCPClient(spec["command"], spec.get("args"), spec.get("env"), spec.get("cwd")).start(timeout=timeout)
