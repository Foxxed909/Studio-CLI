"""
Project scanner — walks a directory tree, reads source files, detects tech stack.
Used by /enter and agent context injection.
"""
from pathlib import Path

from studio.data import SKIP_DIRS, CODE_EXTS, MAX_FILE_CHARS, MAX_TOTAL_CHARS


def scan_project(path):
    root  = Path(path).resolve()
    if not root.exists():
        return {"error": f"Not found: {path}"}
    if not root.is_dir():
        return {"error": f"Not a directory: {path}"}
    files       = {}
    tree_lines  = []
    total_chars = 0
    stats       = {"total_files": 0, "total_lines": 0, "total_size": 0, "by_ext": {}}

    def walk(cur, prefix="", depth=0):
        nonlocal total_chars
        if depth > 7:
            return
        try:
            items = sorted(cur.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        except OSError:
            return
        for i, item in enumerate(items):
            # Never follow symlinks while building model context. Even a symlink
            # located inside the workspace may target private files outside it,
            # and directory symlinks can also create recursion cycles.
            try:
                if item.is_symlink():
                    continue
                item.resolve().relative_to(root)
            except (OSError, ValueError):
                continue
            last = i == len(items) - 1
            conn = "└── " if last else "├── "
            ext2 = "    " if last else "│   "
            if item.is_dir():
                if item.name in SKIP_DIRS:
                    continue
                tree_lines.append(f"{prefix}{conn}📁 {item.name}/")
                walk(item, prefix + ext2, depth + 1)
            else:
                ext = item.suffix.lower()
                sz  = item.stat().st_size
                stats["total_files"] += 1
                stats["total_size"]  += sz
                stats["by_ext"][ext]  = stats["by_ext"].get(ext, 0) + 1
                sl = f"{sz}B" if sz < 1024 else f"{sz // 1024}KB"
                tree_lines.append(f"{prefix}{conn}📄 {item.name} ({sl})")
                if ext in CODE_EXTS and sz < 500000 and total_chars < MAX_TOTAL_CHARS:
                    try:
                        content = item.read_text(encoding="utf-8", errors="replace")
                        lns     = len(content.splitlines())
                        stats["total_lines"] += lns
                        rel = str(item.relative_to(root))
                        if len(content) > MAX_FILE_CHARS:
                            content = content[:MAX_FILE_CHARS] + f"\n...[{lns} lines, truncated]"
                        files[rel] = {"content": content, "lines": lns, "ext": ext, "size": sz}
                        total_chars += len(content)
                    except Exception:
                        pass

    walk(root)

    all_names   = " ".join(files.keys())
    all_content = " ".join(v.get("content", "")[:500] for v in files.values())
    checks = [
        ("package.json" in all_names,                                          "Node.js"),
        ("requirements.txt" in all_names or "pyproject.toml" in all_names,    "Python"),
        (any(".ts" in f for f in files),                                       "TypeScript"),
        (any(".tsx" in f or ".jsx" in f for f in files),                       "React"),
        (any(".vue" in f for f in files),                                      "Vue.js"),
        ("next.config" in all_names,                                           "Next.js"),
        ("vite.config" in all_names,                                           "Vite"),
        ("tailwind" in all_content.lower(),                                    "Tailwind CSS"),
        ("prisma" in all_content.lower(),                                      "Prisma"),
        ("supabase" in all_content.lower(),                                    "Supabase"),
        ("express" in all_content.lower(),                                     "Express"),
        ("fastapi" in all_content.lower(),                                     "FastAPI"),
        ("django" in all_content.lower(),                                      "Django"),
        ("docker" in all_names.lower(),                                        "Docker"),
        ("openai" in all_content.lower(),                                      "OpenAI"),
    ]
    stack   = [name for cond, name in checks if cond]
    prios   = ["main.py","app.py","index.py","server.py","index.js","main.js",
               "app.js","index.ts","index.html","App.tsx","App.jsx"]
    entries = [p for p in prios if any(f.endswith(p) or f == p for f in files)]

    return {
        "root":         str(root),
        "tree":         "\n".join(tree_lines),
        "files":        files,
        "stats":        stats,
        "tech_stack":   stack,
        "entry_points": entries[:5],
        "total_chars":  total_chars,
    }


def format_project_context(ctx, max_files=15):
    if "error" in ctx:
        return f"Error: {ctx['error']}"
    parts = [f"PROJECT ROOT: {ctx['root']}"]
    if ctx.get("tech_stack"):
        parts.append("TECH STACK: " + ", ".join(ctx["tech_stack"]))
    s  = ctx["stats"]
    sz = f"{s['total_size'] // 1024}KB" if s["total_size"] < 1048576 else f"{s['total_size'] // 1048576}MB"
    parts.append(f"STATS: {s['total_files']} files · {s['total_lines']:,} lines · {sz}")
    if ctx.get("entry_points"):
        parts.append("ENTRY POINTS: " + ", ".join(ctx["entry_points"]))
    tree_preview = "\n".join(ctx["tree"].split("\n")[:50])
    parts.append(f"DIRECTORY TREE:\n{tree_preview}")
    for fname, info in sorted(ctx["files"].items(), key=lambda x: -x[1]["size"])[:max_files]:
        parts.append(f"\nFILE: {fname} ({info['lines']} lines)\n\n{info['content']}")
    return "\n".join(parts)
