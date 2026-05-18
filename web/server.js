require("dotenv").config();
const express = require("express");
const https = require("https");
const http = require("http");
const path = require("path");
const fs = require("fs");
const os = require("os");
const querystring = require("querystring");
const helmet = require("helmet");
const rateLimit = require("express-rate-limit");
const Stripe = require("stripe");

const stripe = Stripe(process.env.STRIPE_SECRET_KEY || "");

const STRIPE_PRICES = {
  starter: process.env.STRIPE_PRICE_STARTER,
  pro:     process.env.STRIPE_PRICE_PRO,
  dev:     process.env.STRIPE_PRICE_DEV,
  max:     process.env.STRIPE_PRICE_MAX,
  ultra:   process.env.STRIPE_PRICE_ULTRA,
};

// ── Subscription storage (profiles/<email>/subscription.json) ────────────────
function _subDir(email) {
  const safe = email.toLowerCase().replace(/[^a-z0-9._@-]/g, "_");
  const dir = path.join(__dirname, "..", "profiles", safe);
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}
function saveSub(email, data) {
  const p = path.join(_subDir(email), "subscription.json");
  fs.writeFileSync(p, JSON.stringify({ ...data, updatedAt: new Date().toISOString() }, null, 2));
}
function loadSub(email) {
  const p = path.join(_subDir(email), "subscription.json");
  if (!fs.existsSync(p)) return null;
  try { return JSON.parse(fs.readFileSync(p, "utf8")); } catch { return null; }
}

const app = express();
const PORT = process.env.PORT || 3456;

// ── Security headers ─────────────────────────────────────────────────────────
app.use(helmet({
  contentSecurityPolicy: {
    directives: {
      defaultSrc:  ["'self'"],
      scriptSrc:   ["'self'", "'unsafe-inline'", "cdn.jsdelivr.net", "cdnjs.cloudflare.com"],
      styleSrc:    ["'self'", "'unsafe-inline'", "cdnjs.cloudflare.com"],
      imgSrc:      ["'self'", "data:", "blob:"],
      connectSrc:  ["'self'", "cdn.jsdelivr.net", "cdnjs.cloudflare.com"],
      fontSrc:     ["'self'", "cdnjs.cloudflare.com"],
      frameSrc:    ["'self'"],
      objectSrc:     ["'none'"],
      scriptSrcAttr: ["'unsafe-inline'"],
    },
  },
  crossOriginEmbedderPolicy: false,
}));

// Permissions-Policy — helmet's permissionsPolicy config is unreliable across versions
app.use((_req, res, next) => {
  res.setHeader("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=(), fullscreen=(self)");
  next();
});

// ── High-load detection — sliding window of rate-limit hits ──────────────────
const _rlHits = [];   // timestamps of every 429 issued
function _recordRLHit() { _rlHits.push(Date.now()); if (_rlHits.length > 5000) _rlHits.splice(0, 1000); }
function _recentRLHits(windowMs = 60_000) { const cut = Date.now() - windowMs; return _rlHits.filter(t => t > cut).length; }
function isHighLoad() { return _recentRLHits() >= 20; } // 20+ rate-limit hits/min = high load

// ── Rate limiting ────────────────────────────────────────────────────────────
const chatLimit = rateLimit({
  windowMs: 60 * 1000,
  max: 60,
  standardHeaders: true,
  legacyHeaders: false,
  skip: (req) => req.ip === "::1" || req.ip === "127.0.0.1" || req.ip === "::ffff:127.0.0.1",
  handler: (req, res) => {
    _recordRLHit();
    res.status(429).json({ error: "Too many requests. Slow down.", highLoad: isHighLoad() });
  },
});
const keyLimit = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 5,
  handler: (req, res) => {
    _recordRLHit();
    res.status(429).json({ error: "Too many key attempts." });
  },
});
// Broad safety net — catches any endpoint not covered by chatLimit
const globalLimit = rateLimit({
  windowMs: 60 * 1000,
  max: 200,
  standardHeaders: true,
  legacyHeaders: false,
  handler: (req, res) => {
    _recordRLHit();
    res.status(429).json({ error: "Rate limit exceeded.", highLoad: isHighLoad() });
  },
  skip: (req) => {
    const isLocal = req.ip === "::1" || req.ip === "127.0.0.1" || req.ip === "::ffff:127.0.0.1";
    const hasOwnLimit = ["/api/chat","/api/research","/api/health","/api/stats"].some(p => req.path.startsWith(p));
    return isLocal || hasOwnLimit;
  },
});

// Stripe webhook — must use raw body BEFORE express.json()
app.post("/api/stripe/webhook", express.raw({ type: "application/json" }), (req, res) => {
  const sig    = req.headers["stripe-signature"];
  const secret = process.env.STRIPE_WEBHOOK_SECRET;
  if (!secret || secret === "whsec_placeholder") {
    return res.status(500).json({ error: "Webhook secret not configured" });
  }
  let event;
  try {
    event = stripe.webhooks.constructEvent(req.body, sig, secret);
  } catch (err) {
    return res.status(400).json({ error: `Webhook Error: ${err.message}` });
  }

  if (event.type === "checkout.session.completed") {
    const session = event.data.object;
    const { plan, email } = session.metadata || {};
    if (email && plan) {
      saveSub(email, {
        plan,
        stripeCustomerId:     session.customer,
        stripeSubscriptionId: session.subscription,
      });
    }
  }

  if (event.type === "customer.subscription.deleted") {
    const sub = event.data.object;
    const profilesDir = path.join(__dirname, "..", "profiles");
    if (fs.existsSync(profilesDir)) {
      for (const dir of fs.readdirSync(profilesDir)) {
        const subPath = path.join(profilesDir, dir, "subscription.json");
        if (!fs.existsSync(subPath)) continue;
        try {
          const data = JSON.parse(fs.readFileSync(subPath, "utf8"));
          if (data.stripeSubscriptionId === sub.id) {
            saveSub(dir.replace(/_/g, "@"), { ...data, plan: "free", stripeSubscriptionId: null });
            break;
          }
        } catch {}
      }
    }
  }

  res.json({ received: true });
});

app.use(express.json({ limit: "2mb" }));

// ── CORS — localhost only ────────────────────────────────────────────────────
const ALLOWED_ORIGINS = new Set([
  "http://localhost:3456",
  "http://127.0.0.1:3456",
  `http://localhost:${process.env.PORT || 3456}`,
  `http://127.0.0.1:${process.env.PORT || 3456}`,
]);
app.use((req, res, next) => {
  const origin = req.get("origin");
  if (origin && ALLOWED_ORIGINS.has(origin)) {
    res.setHeader("Access-Control-Allow-Origin", origin);
    res.setHeader("Vary", "Origin");
  }
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, X-OR-Key, Authorization");
  if (req.method === "OPTIONS") return res.sendStatus(204);
  next();
});

// ── Global request timeout ───────────────────────────────────────────────────
app.use((req, res, next) => {
  res.setTimeout(90000, () => {
    if (!res.headersSent) res.status(503).json({ error: "Request timed out." });
  });
  next();
});

app.use(globalLimit);
app.use(express.static(path.join(__dirname, "public")));

const OPENROUTER_BASE = "https://openrouter.ai/api/v1/chat/completions";
const DDG_API        = "https://api.duckduckgo.com/";

// ── Web Search Models ────────────────────────────────────────────────────────
const WEB_SEARCH_MODEL  = "perplexity/sonar";
const DEEP_RESEARCH_MODEL = "perplexity/sonar-pro";
const TURBO_MODEL       = "openai/gpt-4o-mini";

// ── Key resolution ──────────────────────────────────────────────────────────
function resolveKey(req) {
  // 0a. Authorization: Bearer sk-or-… header
  const authHeader = req && req.get("Authorization");
  if (authHeader && authHeader.startsWith("Bearer sk-or-")) {
    const k = authHeader.slice(7).trim();
    if (k.length <= 128) return k;
  }
  // 0b. X-OR-Key header (legacy, kept for backward compat)
  const headerKey = req && req.get("X-OR-Key");
  if (headerKey && headerKey.startsWith("sk-or-") && headerKey.length <= 128) return headerKey;

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
  { id: "openai/gpt-oss-20b:free",                                    name: "GPT OSS 20B",      badge: "FREE" },
  { id: "openai/gpt-oss-120b:free",                                   name: "GPT OSS 120B",     badge: "FREE" },
  { id: "nvidia/nemotron-3-super-120b-a12b:free",                     name: "Nemotron 120B",    badge: "FREE" },
  { id: "meta-llama/llama-3.3-70b-instruct:free",                     name: "Llama 3.3 70B",    badge: "FREE" },
  { id: "google/gemma-3-27b-it:free",                                  name: "Gemma 3 27B",      badge: "FREE" },
  { id: "qwen/qwen3-coder:free",                                       name: "Qwen3 Coder",      badge: "FREE" },
  { id: "google/gemma-3-12b-it:free",                                  name: "Gemma 3 12B",      badge: "FREE" },
  { id: "meta-llama/llama-3.2-3b-instruct:free",                      name: "Llama 3.2 3B",     badge: "FREE" },
  { id: "nousresearch/hermes-3-llama-3.1-405b:free",                  name: "Hermes 3 405B",    badge: "FREE" },
  { id: "cognitivecomputations/dolphin-mistral-24b-venice-edition:free", name: "Dolphin Mistral", badge: "FREE" },
];

const PAID_MODELS = [
  { id: "openai/gpt-4o",                  name: "GPT-4o",           badge: "PRO" },
  { id: "openai/gpt-4o-mini",             name: "GPT-4o Mini",      badge: "PRO" },
  { id: "anthropic/claude-sonnet-4-6",    name: "Claude Sonnet 4.6",badge: "PRO" },
  { id: "anthropic/claude-opus-4-7",      name: "Claude Opus 4.7",  badge: "PRO" },
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

// ── Pricing (cost per 1k tokens in/out in USD) ──────────────────────────────
const MODEL_PRICING = {
  "openai/gpt-4o":                          { in: 0.0025,  out: 0.010  },
  "openai/gpt-4o-mini":                     { in: 0.00015, out: 0.0006 },
  "anthropic/claude-sonnet-4-6":            { in: 0.003,   out: 0.015  },
  "anthropic/claude-opus-4-7":              { in: 0.015,   out: 0.075  },
  "google/gemini-2.5-pro":                  { in: 0.00125, out: 0.010  },
  "mistralai/mistral-large":                { in: 0.002,   out: 0.006  },
  "meta-llama/llama-3.3-70b-instruct":      { in: 0.0003,  out: 0.0004 },
  "qwen/qwen-2.5-72b-instruct":             { in: 0.0004,  out: 0.0004 },
};

function estimateCost(modelId, inTok, outTok) {
  let p = MODEL_PRICING[modelId];
  if (!p && modelId) p = MODEL_PRICING[modelId.replace(":free", "")];
  if (!p) return 0;
  return (inTok / 1000) * p.in + (outTok / 1000) * p.out;
}

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

app.post("/api/key", keyLimit, (req, res) => {
  // Only accept from loopback — this endpoint must never be public-facing
  const ip = req.ip || req.connection?.remoteAddress || "";
  const isLocal = ip === "127.0.0.1" || ip === "::1" || ip === "::ffff:127.0.0.1";
  if (!isLocal && !process.env.ALLOW_REMOTE_KEY) {
    return res.status(403).json({ error: "Forbidden" });
  }
  const { key } = req.body;
  if (!key || typeof key !== "string" || !key.startsWith("sk-or-") || key.length > 128) {
    return res.status(400).json({ error: "Invalid OpenRouter key" });
  }
  const profileDir = path.join(__dirname, "..", "profiles", "default");
  fs.mkdirSync(profileDir, { recursive: true });
  fs.writeFileSync(path.join(profileDir, "openrouter_key"), key, "utf8");
  res.json({ ok: true });
});

const ALLOWED_MODELS = new Set([
  ...FREE_MODELS.map(m => m.id),
  ...PAID_MODELS.map(m => m.id),
  WEB_SEARCH_MODEL, DEEP_RESEARCH_MODEL, TURBO_MODEL,
]);

// Strip any non-user/assistant roles to prevent system prompt injection via messages array
function sanitizeMessages(msgs) {
  return msgs
    .filter(m => m && typeof m === "object" && ["user", "assistant"].includes(m.role))
    .map(m => ({
      role: m.role,
      content: typeof m.content === "string" ? m.content.slice(0, 32000) : "",
    }));
}

app.post("/api/chat", chatLimit, (req, res) => {
  const { messages, model, persona, stream = true,
          temperature, max_tokens, system_override, image,
          top_p, frequency_penalty, presence_penalty, stop,
          web_search = false, turbo = false, deep_research = false } = req.body;
  if (!messages || !Array.isArray(messages) || messages.length === 0) {
    return res.status(400).json({ error: "messages array required" });
  }
  if (messages.length > 100) {
    return res.status(400).json({ error: "Too many messages (max 100)." });
  }
  // Validate image data size before processing (~3MB base64 limit)
  if (image && image.data && typeof image.data === "string" && image.data.length > 4_000_000) {
    return res.status(400).json({ error: "Image too large (max ~3MB)." });
  }

  const apiKey = resolveKey(req);
  if (!apiKey) {
    return res.status(401).json({ error: "no_key", message: "No OpenRouter API key found. Set one in the Settings panel." });
  }

  // ── Model selection with feature overrides ─────────────────────────────
  let resolvedModel = model || FREE_MODELS[0].id;
  // Reject unknown models — prevents billing abuse via expensive unlisted models
  if (model && !web_search && !turbo && !deep_research && !ALLOWED_MODELS.has(model)) {
    return res.status(400).json({ error: "Unknown model" });
  }
  if (deep_research) resolvedModel = DEEP_RESEARCH_MODEL;
  else if (web_search) resolvedModel = WEB_SEARCH_MODEL;
  else if (turbo) resolvedModel = TURBO_MODEL;

  const baseSystem = (persona && PERSONAS[persona]) ? PERSONAS[persona].system : PERSONAS.default.system;
  // system_override capped at 2000 chars — prevents prompt injection blowout
  const systemPrompt = (system_override && typeof system_override === "string")
    ? system_override.slice(0, 2000)
    : baseSystem;

  // Build final messages — inject image into last user message if provided
  let finalMessages = sanitizeMessages(messages);
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

  const payloadObj = {
    model: resolvedModel,
    messages: [
      { role: "system", content: systemPrompt },
      ...finalMessages,
    ],
    stream,
    max_tokens: turbo ? Math.min(max_tokens || 512, 512) : (max_tokens || 4096),
    temperature: temperature ?? 1.0,
  };
  if (top_p != null && top_p !== 1) payloadObj.top_p = top_p;
  if (frequency_penalty != null && frequency_penalty !== 0) payloadObj.frequency_penalty = frequency_penalty;
  if (presence_penalty != null && presence_penalty !== 0) payloadObj.presence_penalty = presence_penalty;
  if (Array.isArray(stop) && stop.length) payloadObj.stop = stop;

  const inTokens = Math.round(JSON.stringify(finalMessages).length / 4);
  const payload = JSON.stringify(payloadObj);

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
      let buffer = "", fullContent = "";
      apiRes.on("data", (chunk) => {
        buffer += chunk.toString();
        const lines = buffer.split("\n");
        buffer = lines.pop();
        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed || !trimmed.startsWith("data: ")) continue;
          const data = trimmed.slice(6).trim();
          if (data === "[DONE]") continue;
          try {
            const parsed = JSON.parse(data);
            if (parsed.error) {
              res.write(`data: ${JSON.stringify({ error: parsed.error.message || JSON.stringify(parsed.error) })}\n\n`);
              continue;
            }
            const delta = parsed.choices?.[0]?.delta?.content;
            if (delta) { fullContent += delta; res.write(`data: ${JSON.stringify({ content: delta })}\n\n`); }
          } catch {}
        }
      });
      apiRes.on("end", () => {
        if (buffer && buffer.trim().startsWith("data: ")) {
          const data = buffer.trim().slice(6).trim();
          if (data !== "[DONE]") {
            try {
              const parsed = JSON.parse(data);
              if (parsed.error) {
                res.write(`data: ${JSON.stringify({ error: parsed.error.message || JSON.stringify(parsed.error) })}\n\n`);
              } else {
                const delta = parsed.choices?.[0]?.delta?.content;
                if (delta) { fullContent += delta; res.write(`data: ${JSON.stringify({ content: delta })}\n\n`); }
              }
            } catch {}
          }
        }
        // Detect silent empty response — common when free-tier model is rate-limited or quota-exhausted
        if (!fullContent) {
          const modelName = resolvedModel.split("/").pop()?.replace(":free", "") || resolvedModel;
          res.write(`data: ${JSON.stringify({ error: `${modelName} returned no content. The free tier may be rate-limited or temporarily unavailable — try regenerating or switching to a different model.` })}\n\n`);
        }
        const outTokens = Math.round(fullContent.length / 4);
        const costUsd = estimateCost(resolvedModel, inTokens, outTokens);
        res.write(`data: ${JSON.stringify({ usage: { in_tokens: inTokens, out_tokens: outTokens, cost_usd: costUsd } })}\n\n`);
        res.write("data: [DONE]\n\n");
        res.end();
      });
    });

    apiReq.on("error", (e) => {
      if (!res.headersSent) res.setHeader("Content-Type", "text/event-stream");
      res.write(`data: ${JSON.stringify({ error: e.message })}\n\n`);
      res.end();
    });
    apiReq.setTimeout(30000, () => {
      apiReq.destroy(new Error("Upstream request timed out"));
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
          if (parsed.error) return res.status(502).json({ error: parsed.error.message || "API error" });
          const content = parsed.choices?.[0]?.message?.content || "";
          const outTokens = Math.round(content.length / 4);
          const costUsd = estimateCost(resolvedModel, inTokens, outTokens);
          res.json({ content, usage: { in_tokens: inTokens, out_tokens: outTokens, cost_usd: costUsd } });
        } catch {
          res.status(500).json({ error: "parse error" });
        }
      });
    });
    apiReq.on("error", (e) => res.status(500).json({ error: e.message }));
    apiReq.setTimeout(60000, () => {
      apiReq.destroy(new Error("Upstream request timed out"));
    });
    apiReq.write(payload);
    apiReq.end();
  }
});

// ── Helper: make a blocking HTTPS GET and return parsed JSON ────────────────
function httpsGet(urlStr, extraHeaders = {}) {
  return new Promise((resolve, reject) => {
    const u = new URL(urlStr);
    const options = {
      hostname: u.hostname,
      path:     u.pathname + u.search,
      method:   "GET",
      headers:  { "User-Agent": "StudioCLI-Web/9.3", ...extraHeaders },
    };
    const req = https.request(options, (res) => {
      let body = "";
      res.on("data", (c) => (body += c));
      res.on("end", () => {
        try { resolve(JSON.parse(body)); }
        catch { resolve({ raw: body }); }
      });
    });
    req.on("error", reject);
    req.setTimeout(6000, () => req.destroy(new Error("timeout")));
    req.end();
  });
}

// ── DuckDuckGo Instant Answer search ────────────────────────────────────────
async function ddgSearch(query, maxResults = 5) {
  const qs = querystring.stringify({ q: query, format: "json", no_html: "1", skip_disambig: "1" });
  try {
    const data = await httpsGet(`${DDG_API}?${qs}`);
    const results = [];
    if (data.Abstract) results.push({ title: data.Heading || query, url: data.AbstractURL || "", snippet: data.Abstract });
    for (const item of (data.RelatedTopics || []).slice(0, maxResults * 2)) {
      if (item && item.Text) results.push({ title: item.Text.slice(0, 80), url: item.FirstURL || "", snippet: item.Text });
    }
    return results.slice(0, maxResults);
  } catch {
    return [];
  }
}

// ── /api/search  — DuckDuckGo web search ────────────────────────────────────
app.get("/api/search", chatLimit, async (req, res) => {
  const query = (req.query.q || "").trim().slice(0, 200);
  if (!query) return res.status(400).json({ error: "q parameter required" });
  const results = await ddgSearch(query, 8);
  res.json({ query, results });
});

// ── /api/research  — deep research via sonar-pro or multi-step DDG ───────────
app.post("/api/research", chatLimit, async (req, res) => {
  const { topic, messages = [] } = req.body;
  if (!topic || typeof topic !== "string" || topic.trim().length === 0) {
    return res.status(400).json({ error: "topic required" });
  }
  if (topic.length > 500) return res.status(400).json({ error: "Topic too long (max 500 chars)." });
  const safeMessages = sanitizeMessages(messages);

  const apiKey = resolveKey(req);
  if (!apiKey) {
    // Fallback: DDG only
    const results = await ddgSearch(topic, 8);
    return res.json({ topic, results, source: "ddg" });
  }

  // Use sonar-pro for deep web research
  res.setHeader("Content-Type", "text/event-stream");
  res.setHeader("Cache-Control", "no-cache");
  res.setHeader("Connection", "keep-alive");

  const systemMsg = "You are a deep research assistant. Use your web search capability to find current, accurate information. Structure your response as: Overview → Key Findings → Analysis → Conclusion.";
  const payload = JSON.stringify({
    model: DEEP_RESEARCH_MODEL,
    messages: [
      { role: "system", content: systemMsg },
      ...safeMessages,
      { role: "user", content: `Conduct deep research on: ${topic.slice(0, 500)}` },
    ],
    stream: true,
    max_tokens: 4096,
  });

  const u = new URL(OPENROUTER_BASE);
  const options = {
    hostname: u.hostname,
    path:     u.pathname,
    method:   "POST",
    headers: {
      "Content-Type":    "application/json",
      "Authorization":   `Bearer ${apiKey}`,
      "HTTP-Referer":    req.get("origin") || `http://${req.headers.host}`,
      "X-Title":         "StudioCLI Web — Deep Research",
      "Content-Length":  Buffer.byteLength(payload),
    },
  };
  const apiReq = https.request(options, (apiRes) => {
    let buf = "";
    apiRes.on("data", (c) => {
      buf += c.toString();
      const lines = buf.split("\n"); buf = lines.pop();
      for (const line of lines) {
        const t = line.trim();
        if (!t || !t.startsWith("data: ")) continue;
        const d = t.slice(6).trim();
        if (d === "[DONE]") continue;
        try {
          const p = JSON.parse(d);
          const delta = p.choices?.[0]?.delta?.content;
          if (delta) res.write(`data: ${JSON.stringify({ content: delta })}\n\n`);
        } catch {}
      }
    });
    apiRes.on("end", () => { res.write("data: [DONE]\n\n"); res.end(); });
  });
  apiReq.on("error", (e) => { res.write(`data: ${JSON.stringify({ error: e.message })}\n\n`); res.end(); });
  apiReq.setTimeout(60000, () => { apiReq.destroy(new Error("Upstream research request timed out")); });
  apiReq.write(payload); apiReq.end();
});

// ── /api/health  — uptime ping ───────────────────────────────────────────────
const _startTime = Date.now();
app.get("/api/health", (req, res) => {
  const rlHits = _recentRLHits();
  res.json({
    ok: true,
    uptime: Math.floor((Date.now() - _startTime) / 1000),
    highLoad: isHighLoad(),
    rlHitsPerMin: rlHits,
  });
});

// ── /api/stats  — server-side request counters ───────────────────────────────
const _stats = { chat: 0, search: 0, research: 0, errors: 0 };
app.use((req, res, next) => {
  res.on("finish", () => {
    if (req.path === "/api/chat")     _stats.chat++;
    if (req.path === "/api/search")   _stats.search++;
    if (req.path === "/api/research") _stats.research++;
    if (res.statusCode >= 400)        _stats.errors++;
  });
  next();
});
app.get("/api/stats", (req, res) => {
  const ip = req.ip || "";
  const isLocal = ip === "127.0.0.1" || ip === "::1" || ip === "::ffff:127.0.0.1";
  if (!isLocal) return res.status(403).json({ error: "Forbidden" });
  res.json({ ..._stats, uptime: Math.floor((Date.now() - _startTime) / 1000) });
});

// ── Community Chat — SSE broadcast (no extra packages) ───────────────────────
const _cmClients = new Map();   // clientId → res
const _cmMessages = [];         // rolling last 60

function _cmBroadcast(payload) {
  const line = `data: ${JSON.stringify(payload)}\n\n`;
  for (const [id, res] of _cmClients) {
    try { res.write(line); } catch { _cmClients.delete(id); }
  }
}

app.get("/api/community/stream", (req, res) => {
  res.setHeader("Content-Type", "text/event-stream");
  res.setHeader("Cache-Control", "no-cache");
  res.setHeader("Connection", "keep-alive");
  res.setHeader("X-Accel-Buffering", "no");
  const id = Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
  _cmClients.set(id, res);
  // Send recent history + current count to newcomer
  res.write(`data: ${JSON.stringify({ type: "init", messages: _cmMessages, count: _cmClients.size })}\n\n`);
  // Tell everyone else the count went up
  _cmBroadcast({ type: "count", count: _cmClients.size });
  req.on("close", () => {
    _cmClients.delete(id);
    _cmBroadcast({ type: "count", count: _cmClients.size });
  });
});

const _cmLimit = rateLimit({ windowMs: 10_000, max: 5, standardHeaders: false, legacyHeaders: false,
  handler: (req, res) => res.status(429).json({ error: "Slow down — 5 messages per 10 s max." }) });

app.post("/api/community/message", _cmLimit, express.json({ limit: "4kb" }), (req, res) => {
  const name = String(req.body?.name || "Anonymous").trim().replace(/[<>]/g, "").slice(0, 24) || "Anonymous";
  const text = String(req.body?.text || "").trim().slice(0, 500);
  if (!text) return res.status(400).json({ error: "empty" });
  const msg = { type: "message", id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
    name, text, ts: Date.now() };
  _cmMessages.push(msg);
  if (_cmMessages.length > 60) _cmMessages.splice(0, _cmMessages.length - 60);
  _cmBroadcast(msg);
  res.json({ ok: true });
});

// ── Stripe Checkout ──────────────────────────────────────────────────────────
app.post("/api/stripe/create-checkout", async (req, res) => {
  const { plan, email } = req.body || {};
  if (!plan || !email) return res.status(400).json({ error: "plan and email required" });
  const priceId = STRIPE_PRICES[plan];
  if (!priceId) return res.status(400).json({ error: "Unknown plan" });
  if (!process.env.STRIPE_SECRET_KEY) return res.status(500).json({ error: "Stripe not configured" });

  try {
    const host = `${req.protocol}://${req.get("host")}`;
    const session = await stripe.checkout.sessions.create({
      payment_method_types: ["card"],
      mode:                 "subscription",
      customer_email:       email,
      line_items:           [{ price: priceId, quantity: 1 }],
      success_url:          `${host}/pricing.html?success=1&plan=${plan}&session_id={CHECKOUT_SESSION_ID}`,
      cancel_url:           `${host}/pricing.html?canceled=1`,
      metadata:             { plan, email },
    });
    res.json({ url: session.url });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

const _CREATOR_EMAILS = new Set(["applaudeai@gmail.com"]);

app.get("/api/stripe/plan", (req, res) => {
  const { email } = req.query;
  if (!email) return res.status(400).json({ error: "email required" });
  if (_CREATOR_EMAILS.has(email.toLowerCase().trim())) {
    return res.json({ plan: "creator", sub: { plan: "creator", credits: Infinity, updatedAt: new Date().toISOString() } });
  }
  const sub = loadSub(email);
  res.json({ plan: sub?.plan || "free", sub: sub || null });
});

// Export for Vercel serverless
module.exports = app;

// Only bind port in local dev
if (!process.env.VERCEL) {
  app.listen(PORT, () => {
    console.log(`\n  StudioCLI Web  →  http://localhost:${PORT}\n`);
  });
}
