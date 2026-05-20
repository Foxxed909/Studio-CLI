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

### Developer Utilities
| Command | Description |
|---|---|
| `/calc <expr>` | Evaluate a math expression safely |
| `/uuid [count]` | Generate UUIDs (up to 20) |
| `/hash <text>` | Hash a string — MD5, SHA1, SHA256, SHA512 |
| `/b64 encode/decode <text>` | Base64 encode or decode |
| `/ts` | Current timestamp in 6 formats (Unix, ISO, UTC, local…) |
| `/ping <url>` | HTTP GET a URL and show status + latency |
| `/jwt <token>` | Decode a JWT (header + payload, no verification) |
| `/lorem [n]` | Generate placeholder text (n paragraphs) |
| `/spell <text>` | NATO phonetic alphabet for a string |

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

## Web Interface — v10 Beta

The companion web app (`web/`) ships a full **Gemini-inspired UI** redesign.

```bash
cd web
npm install
npm start
# → http://localhost:3456
```

### Layout

- **Transparent overlay header** — hamburger + StudioCLI wordmark + model picker + v10 badge + temp-chat toggle
- **Slide-in sidebar** — Gemini-style overlay with sparkle logo, nav links, recents, upgrade pill, and user avatar row
- **Pill-shaped input bar** — `+` attachment button, textarea, mic, send; full-width at bottom
- **Bottom sheet** — swipe-up tool tray: Files, Photos, Canvas, Settings, Deep Research, Web Search, Turbo, Computer Use
- **Model picker dropdown** — floating card with Free / GPT-4o Mini / Claude Sonnet / Gemini 2.5 Pro / Opus 4.7 tiers
- **Radial gradient background** — deep navy → near-black, shifts to flat `#212121` in Temp Chat mode

### v10 Beta

Toggle the **v10** badge in the header to unlock:

- Extended thinking mode (signals higher reasoning budget to the API)
- Canvas-mode visual toggle
- Gradient badge glow + toast notification
- Persisted in `localStorage` across sessions

### Research Profiles

When Deep Research is active, pick a **preset system prompt**:

| Preset | Focus |
|---|---|
| Deep Dive | Exhaustive multi-angle analysis |
| Academic | Citations, methodology, peer-review framing |
| Market Intel | Competitive landscape, trends, TAM |
| Technical | Architecture, implementation, trade-offs |
| Synthesis | Cross-domain pattern recognition |
| Devil's Advocate | Stress-test assumptions, surface blindspots |

### Features

| Feature | Description |
|---|---|
| Streaming chat | SSE-based streaming, all models |
| Group Chat | Query multiple models in parallel |
| Community Chat | Live SSE broadcast room (60 rolling messages) |
| Deep Research | Perplexity Sonar Pro — long-form structured reports |
| Web Search | Perplexity Sonar — real-time web grounding |
| Turbo mode | GPT-4o-mini fast-path |
| Computer Use | Browser automation agent (Chrome extension) |
| Persona switcher | 13 AI personas |
| Conversation history | 50 conversations, localStorage |
| Dashboard | Usage stats page |

### Security

All AI requests are proxied server-side — the OpenRouter API key is never sent to the browser.

- Body size guard (100 KB limit before JSON parsing)
- Community message XSS sanitization (HTML tags, `javascript:`, event attributes stripped server-side)
- Anti-prompt-injection suffix on all system prompts
- `X-OR-Key` header restricted to localhost only
- Rate limiting: 60 req/min per IP on `/api/chat`, 5/15 min on `/api/key`
- Strict CSP — no external `connectSrc`; all AI calls are server-side

### Chrome Extension

`web/public/extension/` is a Manifest V3 Chrome extension for the **Computer Use** feature.

```
extension/
  manifest.json   ← MV3, activeTab + scripting permissions
  background.js   ← service worker, session management
  content.js      ← DOM action executor (click, type, scroll, read, screenshot)
  popup.html/js   ← extension popup UI
  icon16.png      ← toolbar icon (16×16)
  icon48.png      ← extension page icon (48×48)
```

Load unpacked from `chrome://extensions` → **Developer mode** → **Load unpacked** → select the `extension/` folder.

---

## Stack

- **Python 3.12+** — single-file distribution (`aistudio.py`)
- **rich** — terminal UI (panels, tables, markdown, syntax highlighting)
- **prompt_toolkit** — REPL input, history, keybindings, completions
- **urllib** — HTTP (no external HTTP library)
- **Node.js / Express** — web interface (`web/`)
- **helmet + express-rate-limit** — web security hardening
- **OpenRouter API** — multi-provider AI routing

---

## Project Layout

```
StudioCLI/
├── aistudio.py          # full CLI (~9k lines)
├── studio/
│   └── providers.py     # OpenRouter / Gemini / Ollama provider adapters
├── test_studio.py       # test suite
├── install_windows.bat  # Windows installer
├── termux_setup.sh      # Android/Termux setup
├── web/
│   ├── server.js        # Express backend (SSE streaming, security)
│   ├── vercel.json      # Vercel deployment config
│   └── public/
│       ├── index.html   # Gemini v10 web chat UI (~3000 lines)
│       ├── pricing.html # Pricing page
│       ├── login.html   # Magic-link auth
│       ├── dashboard.html
│       └── extension/   # Chrome extension (Computer Use)
├── public.md            # changelog
└── private.md           # architecture notes
```

---

## Running Tests

```bash
python test_studio.py
```

~130 command tests. API calls are skipped automatically in non-interactive mode.
