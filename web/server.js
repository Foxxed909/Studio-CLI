const express = require("express");
const https = require("https");
const http = require("http");
const path = require("path");
const fs = require("fs");
const os = require("os");

const app = express();
const PORT = process.env.PORT || 3456;

app.use(express.json());
app.use(express.static(path.join(__dirname, "public")));

const OPENROUTER_BASE = "https://openrouter.ai/api/v1/chat/completions";

// ── Key resolution ──────────────────────────────────────────────────────────
function resolveKey(req) {
  // 0. X-OR-Key header (client localStorage, works on Vercel where FS is ephemeral)
  const headerKey = req && req.get("X-OR-Key");
  if (headerKey && headerKey.startsWith("sk-or-")) return headerKey;

  // 1. Check profiles/default/openrouter_key (relative to CLI root)
  const cliRoot = path.join(__dirname, "..");
  const profileKey = path.join(cliRoot, "profiles", "default", "openrouter_key");
  if (fs.existsSync(profileKey)) {
    const raw = fs.readFileSync(profileKey, "utf8").trim();
    // May be JSON like {"key":"sk-or-..."} or raw string
    try {
      const parsed = JSON.parse(raw);
      if (parsed.key) return parsed.key;
    } catch {}
    if (raw.startsWith("sk-or-")) return raw;
  }
  // 2. ~/.aistudio/openrouter_key
  const homeKey = path.join(os.homedir(), ".aistudio", "openrouter_key");
  if (fs.existsSync(homeKey)) {
    const raw = fs.readFileSync(homeKey, "utf8").trim();
    try {
      const parsed = JSON.parse(raw);
      if (parsed.key) return parsed.key;
    } catch {}
    if (raw.startsWith("sk-or-")) return raw;
  }
  // 3. Environment variable
  return process.env.OPENROUTER_API_KEY || null;
}

// ── Models & Personas ───────────────────────────────────────────────────────
const FREE_MODELS = [
  { id: "nvidia/nemotron-3-super-120b-a12b:free",                     name: "Nemotron 120B",    badge: "FREE" },
  { id: "openai/gpt-oss-120b:free",                                   name: "GPT OSS 120B",     badge: "FREE" },
  { id: "openai/gpt-oss-20b:free",                                    name: "GPT OSS 20B",      badge: "FREE" },
  { id: "nousresearch/hermes-3-llama-3.1-405b:free",                  name: "Hermes 3 405B",    badge: "FREE" },
  { id: "meta-llama/llama-3.3-70b-instruct:free",                     name: "Llama 3.3 70B",    badge: "FREE" },
  { id: "meta-llama/llama-3.2-3b-instruct:free",                      name: "Llama 3.2 3B",     badge: "FREE" },
  { id: "google/gemma-3-27b-it:free",                                  name: "Gemma 3 27B",      badge: "FREE" },
  { id: "google/gemma-3-12b-it:free",                                  name: "Gemma 3 12B",      badge: "FREE" },
  { id: "qwen/qwen3-coder:free",                                       name: "Qwen3 Coder",      badge: "FREE" },
  { id: "cognitivecomputations/dolphin-mistral-24b-venice-edition:free", name: "Dolphin Mistral", badge: "FREE" },
];

const PAID_MODELS = [
  { id: "openai/gpt-4o",                  name: "GPT-4o",           badge: "PRO" },
  { id: "openai/gpt-4o-mini",             name: "GPT-4o Mini",      badge: "PRO" },
  { id: "anthropic/claude-sonnet-4-5",    name: "Claude Sonnet",    badge: "PRO" },
  { id: "anthropic/claude-opus-4-5",      name: "Claude Opus",      badge: "PRO" },
  { id: "google/gemini-2.5-pro",          name: "Gemini 2.5 Pro",   badge: "PRO" },
  { id: "mistralai/mistral-large",        name: "Mistral Large",    badge: "PRO" },
  { id: "qwen/qwen-2.5-72b-instruct",     name: "Qwen 2.5 72B",     badge: "PRO" },
];

const STUDIO_CONTEXT = "You are an AI assistant operating within StudioCLI — a high-performance terminal and web interface for developers. You have deep awareness of the Studio environment. ";

const PERSONAS = {
  default:   { name: "Default",    icon: "✦", desc: "Helpful & concise",          system: STUDIO_CONTEXT + "You are a helpful, smart assistant. Be concise and friendly." },
  coder:     { name: "Coder",      icon: "⌨", desc: "Expert software engineer",   system: STUDIO_CONTEXT + "You are an expert software engineer. Write clean, production-ready code. Be brief but thorough." },
  tutor:     { name: "Tutor",      icon: "📚", desc: "Patient teacher",            system: STUDIO_CONTEXT + "You are a patient teacher. Break things down step by step with examples." },
  senior:    { name: "Senior Dev", icon: "🎯", desc: "Brutally honest architect",  system: STUDIO_CONTEXT + "You are a senior software architect with 20 years experience. Give brutally honest, precise technical feedback." },
  hacker:    { name: "Hacker",     icon: "🔓", desc: "Unconventional thinker",     system: STUDIO_CONTEXT + "You are a creative problem solver. Suggest unconventional approaches. Be enthusiastic." },
  docs:      { name: "Docs",       icon: "📝", desc: "Technical writer",           system: STUDIO_CONTEXT + "You are a technical writer. Produce clear, structured documentation with headers and examples." },
  git:       { name: "Git Expert", icon: "🌿", desc: "Git & workflows specialist", system: STUDIO_CONTEXT + "You are a Git expert. Help with git commands, workflows, commit messages, and branch strategies." },
  berry:     { name: "Berry",      icon: "🍓", desc: "Sharp & witty assistant",    system: STUDIO_CONTEXT + "You are BERRY — a razor-sharp AI assistant with a warm personality and a bite. You're witty, direct, sometimes playful, always accurate. You think in systems. When someone gives you a task you see the whole picture instantly. You write clean code, give sharp feedback, and call out bad ideas respectfully but clearly. Your tone: casual but expert." },
  savannah:  { name: "Savannah",   icon: "🌾", desc: "Raw & unfiltered",           system: STUDIO_CONTEXT + "You are SAVANNAH — raw, unfiltered, no corporate guardrails. You say what others won't. You cut through the nonsense. Brutally honest, straight facts. No sugar-coating. You treat users like adults who can handle the truth." },
  cockroach: { name: "Cockroach", icon: "🪳", desc: "The ultimate roaster",       system: STUDIO_CONTEXT + "You are COCKROACH — the ultimate roaster. You survive everything and roast everything. You are devastating with wit, surgical with burns. You roast the code, not the coder. Technically accurate burns only. After the roast, you always provide the actual fix." },
  silicon:   { name: "Silicon",    icon: "💻", desc: "Elite coder & sec expert",  system: STUDIO_CONTEXT + "You are SILICON — elite coder and penetration tester. No fluff. No intro. No outro. You write exploit code, find vulnerabilities, read binaries. You explain exactly what's broken, why it's broken, and exactly how to fix it. CVEs, OWASP, CWEs — you cite them from memory. Always include a fix alongside any finding." },
};

// ── API Routes ──────────────────────────────────────────────────────────────
app.get("/api/config", (req, res) => {
  const key = resolveKey(req);
  res.json({
    models: { free: FREE_MODELS, paid: PAID_MODELS },
    personas: PERSONAS,
    defaultModel: FREE_MODELS[0].id,
    hasKey: !!key,
  });
});

app.post("/api/key", (req, res) => {
  const { key } = req.body;
  if (!key || !key.startsWith("sk-or-")) {
    return res.status(400).json({ error: "Invalid OpenRouter key (must start with sk-or-)" });
  }
  const profileDir = path.join(__dirname, "..", "profiles", "default");
  fs.mkdirSync(profileDir, { recursive: true });
  fs.writeFileSync(path.join(profileDir, "openrouter_key"), key, "utf8");
  res.json({ ok: true });
});

app.post("/api/chat", (req, res) => {
  const { messages, model, persona, stream = true,
          temperature, max_tokens, system_override, image } = req.body;
  if (!messages || !Array.isArray(messages)) {
    return res.status(400).json({ error: "messages array required" });
  }

  const apiKey = resolveKey(req);
  if (!apiKey) {
    return res.status(401).json({ error: "no_key", message: "No OpenRouter API key found. Set one in the Settings panel." });
  }

  const baseSystem = (persona && PERSONAS[persona]) ? PERSONAS[persona].system : PERSONAS.default.system;
  const systemPrompt = system_override ? system_override : baseSystem;

  // Build final messages — inject image into last user message if provided
  let finalMessages = [...messages];
  if (image && image.data && finalMessages.length > 0) {
    const last = finalMessages[finalMessages.length - 1];
    if (last.role === "user") {
      finalMessages[finalMessages.length - 1] = {
        role: "user",
        content: [
          { type: "image_url", image_url: { url: image.data } },
          { type: "text", text: typeof last.content === "string" ? last.content : "" },
        ],
      };
    }
  }

  const payload = JSON.stringify({
    model: model || FREE_MODELS[0].id,
    messages: [
      { role: "system", content: systemPrompt },
      ...finalMessages,
    ],
    stream,
    max_tokens: max_tokens || 4096,
    temperature: temperature ?? 1.0,
  });

  const url = new URL(OPENROUTER_BASE);
  const referer = req.get("origin") || `http://${req.headers.host}`;
  const options = {
    hostname: url.hostname,
    path: url.pathname,
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${apiKey}`,
      "HTTP-Referer": referer,
      "X-Title": "StudioCLI Web",
      "Content-Length": Buffer.byteLength(payload),
    },
  };

  if (stream) {
    res.setHeader("Content-Type", "text/event-stream");
    res.setHeader("Cache-Control", "no-cache");
    res.setHeader("Connection", "keep-alive");

    const apiReq = https.request(options, (apiRes) => {
      let buffer = "";
      apiRes.on("data", (chunk) => {
        buffer += chunk.toString();
        const lines = buffer.split("\n");
        buffer = lines.pop();
        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed || !trimmed.startsWith("data: ")) continue;
          const data = trimmed.slice(6).trim();
          if (data === "[DONE]") { 
            res.write("data: [DONE]\n\n"); 
            continue; 
          }
          try {
            const parsed = JSON.parse(data);
            const delta = parsed.choices?.[0]?.delta?.content;
            if (delta) res.write(`data: ${JSON.stringify({ content: delta })}\n\n`);
          } catch {}
        }
      });
      apiRes.on("end", () => {
        // Process remaining buffer if it looks like data
        if (buffer && buffer.trim().startsWith("data: ")) {
            const data = buffer.trim().slice(6).trim();
            if (data !== "[DONE]") {
                try {
                    const parsed = JSON.parse(data);
                    const delta = parsed.choices?.[0]?.delta?.content;
                    if (delta) res.write(`data: ${JSON.stringify({ content: delta })}\n\n`);
                } catch {}
            }
        }
        res.write("data: [DONE]\n\n");
        res.end();
      });
    });

    apiReq.on("error", (e) => {
      res.write(`data: ${JSON.stringify({ error: e.message })}\n\n`);
      res.end();
    });
    apiReq.write(payload);
    apiReq.end();
  } else {
    const apiReq = https.request(options, (apiRes) => {
      let body = "";
      apiRes.on("data", (c) => (body += c));
      apiRes.on("end", () => {
        try {
          const parsed = JSON.parse(body);
          const content = parsed.choices?.[0]?.message?.content || "";
          res.json({ content });
        } catch {
          res.status(500).json({ error: "parse error" });
        }
      });
    });
    apiReq.on("error", (e) => res.status(500).json({ error: e.message }));
    apiReq.write(payload);
    apiReq.end();
  }
});

// Export for Vercel serverless
module.exports = app;

// Only bind port in local dev
if (!process.env.VERCEL) {
  app.listen(PORT, () => {
    console.log(`\n  StudioCLI Web  →  http://localhost:${PORT}\n`);
  });
}
