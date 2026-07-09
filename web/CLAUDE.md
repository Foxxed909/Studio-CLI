# StudioCLI Web

Express server + vanilla HTML/CSS/JS front-end that exposes StudioCLI as a browser app.

## Stack
- **Server**: Node.js + Express 4, `helmet`, `express-rate-limit`, `https` (stdlib)
- **Front-end**: Single-file HTML (`public/index.html`) — no bundler, no framework
- **CDN deps**: marked.js, DOMPurify, highlight.js (loaded via CDN in HTML)
- **AI**: OpenRouter API (`openrouter.ai/api/v1/chat/completions`), proxied server-side

## File map
```
web/
  server.js          ← Express app, all API routes, rate limiting, CSP
  package.json
  public/
    index.html       ← Main chat UI (CSS + JS all inline, ~2400 lines)
    dashboard.html   ← Usage stats dashboard (reads localStorage)
    landing.html     ← Marketing page
    studiotesting.html ← Dev/test scratchpad
    extension/       ← Chrome extension stub (Computer Use feature)
```

## Server key points
- All AI requests proxy through server — API key never exposed to browser
- Key resolution order: `Authorization: Bearer` header → `X-OR-Key` header → `profiles/default/openrouter_key` file → `~/.aistudio/openrouter_key` → `OPENROUTER_API_KEY` env var
- Rate limits: `chatLimit` (60 req/min) on `/api/chat`, `keyLimit` (5/15 min) on `/api/key`, `globalLimit` (200 req/min, skips localhost AND the chat/research/health/stats paths)
- CSP: `unsafe-inline` scripts allowed (single-file HTML pattern); `connectSrc` is `'self'` only — all external AI calls are server-side
- `/api/community/stream` — SSE broadcast, in-memory store (60 rolling messages), no persistence

## ALLOWED_MODELS (server enforced)
Free: llama-3.3-70b-instruct:free, gemma-3-27b-it:free, qwen3-coder:free, gemma-3-12b-it:free,
      llama-3.2-3b-instruct:free, gpt-oss-20b:free, gpt-oss-120b:free, hermes-3-llama-3.1-405b:free,
      dolphin-mistral-24b-venice-edition:free, nemotron-3-super-120b-a12b:free
Paid: gpt-4o, gpt-4o-mini, claude-sonnet-4-6, claude-opus-4-7, gemini-2.5-pro, mistral-large, qwen-2.5-72b-instruct
Special: perplexity/sonar (web search), perplexity/sonar-pro (deep research), openai/gpt-4o-mini (turbo)

**Any model ID sent to `/api/chat` must be in ALLOWED_MODELS or the server returns 400.**
GC_MODELS in index.html must use IDs from the list above.

## Front-end key points
- All state: `localStorage` (`studioSettings`, `studioConvos`, `studioTheme`, etc.)
- Conversations capped at 50, messages per conversation truncated at 100 for API calls
- Streaming via `fetch` + ReadableStream (EventSource only used for Community Chat)
- Markdown rendered with marked.js + DOMPurify + highlight.js; copy buttons use event delegation
- Group Chat sends each model in parallel via `Promise.allSettled`; responses are NOT saved to `messages[]` or conversation history
- `_cmConnect` only reconnects on error if `_cmOpen === true` (panel open)

## Design system (v11 redesign)
- ALL colors come from the :root tokens in index.html (warm dark #131211, terracotta
  --acc #d97757, IBM Plex Sans/Mono). Never hardcode palette values — the v10 "Gemini
  layer" full of #4285f4/#19c37d/#e8eaed hardcodes is exactly what the v11 retheme removed.
- Hover/pressed states use --hover/--hover2/--hover3 (warm-tinted alphas), not rgba(255,255,255,x).
- Monospace (--font-mono) is the voice for model names, plan badges, and metadata chips.
- No gradients, no glows, no glassmorphism. One accent, used sparingly.
- Toasts stack bottom-right (.toast-wrap); nothing may overlap the composer or header.

## Known gotchas
- `globalLimit` `skip` must be a single function combining localhost bypass AND path bypass — duplicate property kills the first
- `/api/research` double-`[DONE]`: the data handler must NOT re-emit `[DONE]` from upstream; only the `end` event sends the final `[DONE]`
- GC_MODELS must stay in sync with server ALLOWED_MODELS; stale model IDs produce "Unknown model" errors
- Community SSE reconnect loop: setting `_cmEvt = null` then checking `|| _cmEvt === null` always reconnects — use `_cmOpen` only
