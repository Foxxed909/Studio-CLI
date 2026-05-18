#!/usr/bin/env node
"use strict";

const { Server } = require("@modelcontextprotocol/sdk/server/index.js");
const { StdioServerTransport } = require("@modelcontextprotocol/sdk/server/stdio.js");
const { CallToolRequestSchema, ListToolsRequestSchema } = require("@modelcontextprotocol/sdk/types.js");
const https = require("https");
const fs = require("fs");
const path = require("path");

// ---------------------------------------------------------------------------
// API key loading
// ---------------------------------------------------------------------------
function loadApiKey() {
  if (process.env.OPENROUTER_API_KEY) {
    return process.env.OPENROUTER_API_KEY.trim();
  }
  const keyFile = path.join(process.cwd(), "profiles", "default", "openrouter_key");
  try {
    return fs.readFileSync(keyFile, "utf8").trim();
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// HTTP helper — POST to OpenRouter
// ---------------------------------------------------------------------------
function openrouterPost(apiKey, body) {
  return new Promise((resolve, reject) => {
    const payload = JSON.stringify(body);
    const options = {
      hostname: "openrouter.ai",
      path: "/api/v1/chat/completions",
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(payload),
        "Authorization": `Bearer ${apiKey}`,
        "HTTP-Referer": "https://github.com/StudioCLI",
        "X-Title": "StudioCLI MCP",
      },
    };

    const req = https.request(options, (res) => {
      let data = "";
      res.on("data", (chunk) => { data += chunk; });
      res.on("end", () => {
        try {
          resolve(JSON.parse(data));
        } catch (e) {
          reject(new Error(`JSON parse error: ${data}`));
        }
      });
    });

    req.on("error", reject);
    req.write(payload);
    req.end();
  });
}

function extractContent(response) {
  if (response.error) {
    throw new Error(`API error: ${response.error.message || JSON.stringify(response.error)}`);
  }
  const choice = response.choices && response.choices[0];
  if (!choice) throw new Error("No choices in response");
  return choice.message && choice.message.content ? choice.message.content : "";
}

function makeTextResult(text) {
  return { content: [{ type: "text", text }] };
}

// ---------------------------------------------------------------------------
// Tool definitions
// ---------------------------------------------------------------------------
const TOOLS = [
  {
    name: "fox_chat",
    description: "Send a message to an AI model via StudioCLI and get a response",
    inputSchema: {
      type: "object",
      properties: {
        message: { type: "string", description: "The message to send to the AI" },
        model: { type: "string", description: "Model ID to use (default: google/gemini-2.5-flash)" },
        persona: { type: "string", description: "System persona for the AI (default: helpful assistant)" },
      },
      required: ["message"],
    },
  },
  {
    name: "fox_analyze_file",
    description: "Analyze a file for bugs, security issues, and code quality problems",
    inputSchema: {
      type: "object",
      properties: {
        file_path: { type: "string", description: "Path to the file to analyze" },
        focus: { type: "string", description: 'Area to focus on (e.g. "security", "performance", "bugs")' },
      },
      required: ["file_path"],
    },
  },
  {
    name: "fox_explain_code",
    description: "Explain what a piece of code does in plain English",
    inputSchema: {
      type: "object",
      properties: {
        code: { type: "string", description: "The code to explain" },
        language: { type: "string", description: "Programming language of the code" },
      },
      required: ["code"],
    },
  },
  {
    name: "fox_review_diff",
    description: "Review a git diff and provide actionable feedback",
    inputSchema: {
      type: "object",
      properties: {
        diff: { type: "string", description: "The git diff to review" },
        context: { type: "string", description: "Optional PR description or ticket context" },
      },
      required: ["diff"],
    },
  },
  {
    name: "fox_suggest_commit",
    description: "Suggest a git commit message for a diff or description of changes",
    inputSchema: {
      type: "object",
      properties: {
        diff: { type: "string", description: "The git diff or description of changes" },
      },
      required: ["diff"],
    },
  },
  {
    name: "fox_list_models",
    description: "List available AI models with their cost and speed characteristics",
    inputSchema: {
      type: "object",
      properties: {},
    },
  },
];

// ---------------------------------------------------------------------------
// Tool handlers
// ---------------------------------------------------------------------------
async function handleFoxChat(args, apiKey) {
  const model = args.model || "google/gemini-2.5-flash";
  const persona = args.persona || "helpful assistant";
  const response = await openrouterPost(apiKey, {
    model,
    messages: [
      { role: "system", content: `You are a ${persona}.` },
      { role: "user", content: args.message },
    ],
  });
  return makeTextResult(extractContent(response));
}

async function handleFoxAnalyzeFile(args, apiKey) {
  let content;
  try {
    content = fs.readFileSync(args.file_path, "utf8");
  } catch (e) {
    return makeTextResult(`Error reading file: ${e.message}`);
  }
  const focus = args.focus || "bugs, security issues, and code quality";
  const prompt = `Analyze this file for ${focus}:\n\n${content}`;
  const response = await openrouterPost(apiKey, {
    model: "google/gemini-2.5-flash",
    messages: [
      { role: "system", content: "You are a senior software engineer performing a thorough code analysis. Be specific and cite line numbers when relevant." },
      { role: "user", content: prompt },
    ],
  });
  return makeTextResult(extractContent(response));
}

async function handleFoxExplainCode(args, apiKey) {
  const lang = args.language ? `${args.language} ` : "";
  const prompt = `Explain this ${lang}code in plain English:\n\n${args.code}`;
  const response = await openrouterPost(apiKey, {
    model: "google/gemini-2.5-flash",
    messages: [
      { role: "system", content: "You are a helpful programming tutor. Explain code clearly and concisely." },
      { role: "user", content: prompt },
    ],
  });
  return makeTextResult(extractContent(response));
}

async function handleFoxReviewDiff(args, apiKey) {
  let prompt = `Review this git diff and provide actionable feedback:\n\n${args.diff}`;
  if (args.context) {
    prompt = `Context: ${args.context}\n\n${prompt}`;
  }
  const response = await openrouterPost(apiKey, {
    model: "google/gemini-2.5-flash",
    messages: [
      { role: "system", content: "You are a senior software engineer doing a rigorous code review. Provide structured feedback covering: correctness, security, performance, style, and test coverage. Be specific and actionable." },
      { role: "user", content: prompt },
    ],
  });
  return makeTextResult(extractContent(response));
}

async function handleFoxSuggestCommit(args, apiKey) {
  const prompt = `Write a conventional commit message (type(scope): description) for these changes:\n\n${args.diff}`;
  const response = await openrouterPost(apiKey, {
    model: "google/gemini-2.5-flash",
    messages: [
      { role: "system", content: "You are a git expert. Return ONLY the commit message string, nothing else. Use conventional commits format: type(scope): description. Types: feat, fix, docs, style, refactor, test, chore." },
      { role: "user", content: prompt },
    ],
  });
  return makeTextResult(extractContent(response).trim());
}

function handleFoxListModels() {
  const models = [
    { id: "google/gemini-2.5-flash", name: "Gemini 2.5 Flash", costPer1kIn: 0.000075, costPer1kOut: 0.0003, speed: "fast", badge: "FREE-ISH" },
    { id: "meta-llama/llama-3.3-70b-instruct:free", name: "Llama 3.3 70B", costPer1kIn: 0, costPer1kOut: 0, speed: "medium", badge: "FREE" },
    { id: "openai/gpt-4o", name: "GPT-4o", costPer1kIn: 0.0025, costPer1kOut: 0.010, speed: "medium", badge: "PRO" },
    { id: "anthropic/claude-sonnet-4-5", name: "Claude Sonnet 4.5", costPer1kIn: 0.003, costPer1kOut: 0.015, speed: "medium", badge: "PRO" },
    { id: "anthropic/claude-opus-4-5", name: "Claude Opus 4.5", costPer1kIn: 0.015, costPer1kOut: 0.075, speed: "slow", badge: "PRO" },
    { id: "google/gemini-2.5-pro", name: "Gemini 2.5 Pro", costPer1kIn: 0.00125, costPer1kOut: 0.005, speed: "medium", badge: "PRO" },
    { id: "openai/gpt-4o-mini", name: "GPT-4o Mini", costPer1kIn: 0.00015, costPer1kOut: 0.0006, speed: "fast", badge: "PRO" },
    { id: "mistralai/mistral-large", name: "Mistral Large", costPer1kIn: 0.002, costPer1kOut: 0.006, speed: "medium", badge: "PRO" },
  ];
  return makeTextResult(JSON.stringify(models, null, 2));
}

// ---------------------------------------------------------------------------
// Server setup
// ---------------------------------------------------------------------------
async function main() {
  const server = new Server(
    { name: "studio-mcp", version: "1.0.0" },
    { capabilities: { tools: {} } }
  );

  server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: TOOLS }));

  server.setRequestHandler(CallToolRequestSchema, async (req) => {
    const { name, arguments: args } = req.params;

    if (name === "fox_list_models") {
      return handleFoxListModels();
    }

    const apiKey = loadApiKey();
    if (!apiKey) {
      return makeTextResult(
        "Error: No OpenRouter API key found. Set OPENROUTER_API_KEY env var or create profiles/default/openrouter_key"
      );
    }

    try {
      switch (name) {
        case "fox_chat":         return await handleFoxChat(args, apiKey);
        case "fox_analyze_file": return await handleFoxAnalyzeFile(args, apiKey);
        case "fox_explain_code": return await handleFoxExplainCode(args, apiKey);
        case "fox_review_diff":  return await handleFoxReviewDiff(args, apiKey);
        case "fox_suggest_commit": return await handleFoxSuggestCommit(args, apiKey);
        default:
          return makeTextResult(`Unknown tool: ${name}`);
      }
    } catch (err) {
      return makeTextResult(`Error executing ${name}: ${err.message}`);
    }
  });

  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("Studio MCP server running on stdio");
}

main().catch((err) => {
  console.error("Fatal error:", err);
  process.exit(1);
});
