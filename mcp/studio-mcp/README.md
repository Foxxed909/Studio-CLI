# studio-mcp

StudioCLI MCP server that exposes AI-powered developer tools to Claude Desktop and any other MCP-compatible client. It uses OpenRouter as its model gateway, defaulting to `google/gemini-2.5-flash` for fast, cost-effective responses, and communicates over stdin/stdout using the Model Context Protocol.

## Install

```bash
cd mcp/studio-mcp
npm install
```

Set your OpenRouter API key in one of two ways:

```bash
# Option 1 — environment variable
export OPENROUTER_API_KEY=sk-or-...

# Option 2 — key file (relative to working directory)
mkdir -p profiles/default
echo "sk-or-..." > profiles/default/openrouter_key
```

## Claude Desktop configuration

Add the server to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "studio-mcp": {
      "command": "node",
      "args": ["/absolute/path/to/Studio-CLI/mcp/studio-mcp/index.js"],
      "env": {
        "OPENROUTER_API_KEY": "sk-or-..."
      }
    }
  }
}
```

Restart Claude Desktop after saving the config.

## Available tools

| Tool | Description |
|------|-------------|
| `fox_chat` | Send a message to any AI model via OpenRouter and get a response. Accepts optional `model` and `persona` parameters. |
| `fox_analyze_file` | Read a file from disk and analyze it for bugs, security issues, and code quality problems. Accepts an optional `focus` (e.g. `"security"`, `"performance"`). |
| `fox_explain_code` | Explain what a piece of code does in plain English. Accepts optional `language` parameter. |
| `fox_review_diff` | Review a git diff and return structured, actionable feedback. Accepts optional `context` (PR description or ticket). |
| `fox_suggest_commit` | Generate a conventional commit message (`type(scope): description`) from a diff. |
| `fox_list_models` | Return a JSON list of available AI models with cost-per-1k-tokens and speed characteristics. No parameters required. |
