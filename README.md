# StudioCLI

A high-performance AI terminal built in Python. Chat with multiple AI providers, manage files, run agents, generate images, and ship code — all from the command line.

```
 ╭─────────────────────────────────────────╮
 │  ✦ StudioCLI  v6.0  ·  studio           │
 ├─────────────────────────────────────────┤
 │  AI-powered terminal for developers     │
 ╰─────────────────────────────────────────╯
```

---

## Install

**Windows**
```bat
install_windows.bat
```
Installs deps, deploys to `AppData`, and registers `studio` / `aistudio` as global commands. Run with `-u` to update.

**Anywhere (Python 3.12+)**
```bash
pip install rich prompt_toolkit
python aistudio.py
```

**Termux (Android)**
```bash
bash termux_setup.sh
```

---

## Quick Start

```bash
studio                  # launch
/help                   # all commands
/enter .                # load current project into context
/ui foxxia              # pick a UI style
/theme neon             # pick a color theme
/keys                   # set your API key (OpenRouter / Gemini)
```

---

## Providers

| Provider | How to activate |
|---|---|
| **OpenRouter** (default) | `/keys` → paste `sk-or-...` key |
| **Gemini CLI** | `npm i -g @google/gemini-cli` or `gemini` in PATH |
| **Ollama** (local) | `ollama serve` + `/model ollama/<name>` |
| **Cursor API** | `/keys` → paste Cursor key (Dev/Max plan) |
| **HuggingFace** | `/keys` → paste HF token (image generation) |

---

## Free Models (no key required via OpenRouter)

- `nvidia/nemotron-3-super-120b-a12b:free` ← default
- `openai/gpt-oss-120b:free`
- `meta-llama/llama-3.3-70b-instruct:free`
- `google/gemma-3-27b-it:free`
- `qwen/qwen3-coder:free`
- + 5 more via `/models`

---

## Commands

### Chat & AI
| Command | Description |
|---|---|
| `<message>` | Chat with the active AI model |
| `/model <id>` | Switch model |
| `/models` | Browse + pick model (arrow-key UI) |
| `/effort <level>` | Set reasoning depth: `low` `medium` `pro` `high` `xhigh` `mxh` |
| `/stream <on/off>` | Toggle streaming output |
| `/arena <q>` | Compare multiple models side-by-side |
| `/compare <q>` | Two-model comparison |
| `/persona <name>` | Switch AI persona (`coder` `senior` `hacker` `berry` `savannah` `cockroach` `silicon` …) |
| `/translate <lang> <text>` | Translate text |

### File Operations
| Command | Description |
|---|---|
| `/read <file>` | Read file into context |
| `/write <file> <prompt>` | AI writes a file |
| `/edit <file> <prompt>` | AI edits existing file |
| `/patch <file>` | AI generates + applies a diff patch |
| `/fix <file>` | AI diagnoses and fixes issues |
| `/fif <file>` | Find · Identify · Fix — structured AI analysis |
| `/analyze <file>` | Deep code analysis |
| `/code <prompt>` | Generate code snippet |
| `/diff <a> <b>` | Show unified diff between two files |

### Filesystem
| Command | Description |
|---|---|
| `/ls [path]` | List directory |
| `/tree [path]` | Directory tree |
| `/cat <file>` | Print file |
| `/find <pattern>` | Find files |
| `/grep <pattern>` | Grep across project |
| `/mkdir <path>` | Create directory |
| `/rm <path>` | Delete file/directory |
| `/cp <src> <dst>` | Copy |
| `/mv <src> <dst>` | Move |
| `/cd <path>` | Change working directory |
| `/wordcount <file>` | Count words/lines/chars |

### Project & Agents
| Command | Description |
|---|---|
| `/enter [path]` | Scan project + load full context |
| `/agents` | List all agents |
| `/agent <id> <task>` | Run a specific agent |
| `/squad <task>` | Auto-assign + run agent squad |
| `/broadcast <msg>` | Send message to all agents |
| `/mesh <task>` | Agent mesh with handoff |

### Dev Tools
| Command | Description |
|---|---|
| `/shell <cmd>` | Run shell command |
| `/run <file>` | Execute script |
| `/git <args>` | Git passthrough |
| `/watch <file>` | Watch file for changes |
| `/audit` | AI security scan of project |
| `/docs <file>` | AI generates documentation |
| `/test <file>` | AI generates tests |
| `/search <query>` | Semantic code search |
| `/bench` | Model benchmark |

### Session & Memory
| Command | Description |
|---|---|
| `/remember <text>` | Save a memory entry |
| `/forget <n>` | Remove memory entry by index |
| `/memory` | Show all memories |
| `/save [name]` | Save conversation |
| `/load [name]` | Load saved conversation |
| `/export [html/md]` | Export chat |
| `/history` | Print session turns |
| `/summarize` | Compress session into summary |
| `/clear` | Clear context + reset session |

### Profile & Plans
| Command | Description |
|---|---|
| `/profile` | View your full profile |
| `/plan` | Show current plan + limits |
| `/usage` | Session usage stats |
| `/insights` | Lifetime analytics |
| `/balance` | Token spend + cost estimate |
| `/upgrade <plan>` | Upgrade plan |
| `/trial` | Activate 5-hour Pro trial |

### UI & Appearance
| Command | Description |
|---|---|
| `/ui <style>` | Switch UI style |
| `/theme <name>` | Switch color theme |
| `/vibe <preset>` | One-shot UI + theme preset |
| `/quickstart` | Setup guide |

### Pro / Enterprise
| Command | Description |
|---|---|
| `/vault <op>` | Local secrets store (`set` `get` `delete` `list`) |
| `/team <op>` | Team management (`invite` `remove` `list` `role`) |
| `/audit-log` | Full audit trail (Max+) |
| `/priority-queue` | Priority task queue (Max+) |
| `/orgmetrics` | Org-wide analytics (Team+) |
| `/sso` | SSO/SAML config (Enterprise) |
| `/policy` | Org policy editor (Enterprise) |
| `/creator` | Creator analytics dashboard |

---

## UI Styles

Switch with `/ui <name>`:

| Style | Description |
|---|---|
| `studio` | Default — clean two-panel box |
| `claude` | Purple/violet, minimal |
| `codex` | Green terminal aesthetic |
| `gemini` | Blue gradient, Google-inspired |
| `ghost` | Ultra-minimal single-line |
| `nova` | Sci-fi magenta/cyan |
| `foxxia` | Orange/gold Foxxia Dev Studio branding |

---

## Themes

Switch with `/theme <name>` or use a `/vibe` preset:

`default` · `ocean` · `forest` · `sunset` · `mono` · `neon` · `rose` · `gold` · `arctic` · `ember` · `violet` · `matrix`

---

## Agents

12 built-in agents with specialties. Auto-assigned via `/squad` or called directly:

| Agent | Role |
|---|---|
| `lucifer` | Architect — system design |
| `blackcanary` | Frontend — React/UI |
| `blacklord` | Backend — APIs/DBs |
| `deathohmyson` | QA — testing/bugs |
| `wizzard` | AI/ML — models/pipelines |
| `applaude` | DevOps — CI/CD/infra |
| `ghost` | Security — audits/pentesting |
| `nova` | Performance — profiling/optimization |
| `berry` | Sharp generalist |
| `savannah` | Raw & unfiltered |
| `cockroach` | Code roaster (fixes too) |
| `silicon` | Elite coder + security expert |

---

## Plans

| Plan | Price | Messages | Images |
|---|---|---|---|
| Free | $0 | 10 / session | 1 / 3h |
| Starter | $5 | 100 / session | 3 / 3h |
| Pro | $18 | 500 / session | 10 / 3h |
| Dev | $35 | 2,000 / session | 50 / 3h |
| Max | $80 | 5,000 / session | 100 / 3h |
| Ultra | $250 | Unlimited | Unlimited |
| Team | $400 | Unlimited | Unlimited |
| Enterprise | Custom | Unlimited | Unlimited |

---

## Web Interface

A companion web UI lives in `web/`. It uses the same OpenRouter key and model list.

```bash
cd web
npm install
npm start
# → http://localhost:3456
```

Features: streaming chat, model picker, persona switcher, dark terminal theme.

---

## Stack

- **Python 3.12+** — single-file distribution (`aistudio.py`)
- **rich** — terminal UI (panels, tables, markdown, syntax highlighting)
- **prompt_toolkit** — REPL input, history, keybindings, completions
- **urllib** — HTTP (no external HTTP library)
- **Node.js / Express** — web interface (`web/`)

---

## Project Layout

```
StudioCLI/
├── aistudio.py          # full CLI (~9k lines)
├── test_studio.py       # test suite
├── install_windows.bat  # Windows installer
├── termux_setup.sh      # Android/Termux setup
├── index.html           # portfolio showcase page
├── web/
│   ├── server.js        # Express backend (SSE streaming)
│   └── public/
│       └── index.html   # web chat UI
├── public.md            # changelog
└── private.md           # architecture notes
```

---

## Running Tests

```bash
python test_studio.py
```

~130 command tests. API calls are skipped automatically in non-interactive mode.
