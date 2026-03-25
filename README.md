# MCP Server Toolkit

A collection of production-ready **Model Context Protocol (MCP)** servers for integrating Claude, GitHub Copilot, and other AI assistants with real-world tools and services.

## What is MCP?

The [Model Context Protocol](https://modelcontextprotocol.io) is an open standard by Anthropic that allows AI assistants to securely connect to external data sources and tools. Think of it as a USB-C port for AI — a universal way to plug capabilities into any LLM.

## Servers Included

| Server | Description | Tools Exposed |
|--------|-------------|---------------|
| `weather_server.py` | Real-time weather via OpenWeatherMap | `get_current_weather`, `get_forecast` |
| `filesystem_server.py` | Safe local file operations | `read_file`, `write_file`, `list_directory`, `search_files` |
| `github_server.py` | GitHub API integration | `get_repo`, `list_issues`, `create_issue`, `search_code` |
| `bedrock_server.py` | AWS Bedrock model invocation | `invoke_claude`, `invoke_titan`, `list_models` |

## Project Structure

```
mcp-server-toolkit/
  src/
    weather_server.py      # OpenWeatherMap MCP server
    filesystem_server.py   # Local filesystem MCP server
    github_server.py       # GitHub API MCP server
    bedrock_server.py      # AWS Bedrock MCP server
  requirements.txt
  README.md
```

## Quick Start

### Install dependencies

```bash
pip install -r requirements.txt
```

### Run a server

```bash
# Weather server
python src/weather_server.py

# Filesystem server
python src/filesystem_server.py

# GitHub server
export GITHUB_TOKEN=your_token
python src/github_server.py

# AWS Bedrock server
export AWS_REGION=us-east-1
python src/bedrock_server.py
```

### Connect to Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "weather": {
      "command": "python",
      "args": ["/path/to/src/weather_server.py"],
      "env": { "OPENWEATHER_API_KEY": "your_key" }
    },
    "filesystem": {
      "command": "python",
      "args": ["/path/to/src/filesystem_server.py"]
    },
    "github": {
      "command": "python",
      "args": ["/path/to/src/github_server.py"],
      "env": { "GITHUB_TOKEN": "your_token" }
    },
    "bedrock": {
      "command": "python",
      "args": ["/path/to/src/bedrock_server.py"],
      "env": { "AWS_REGION": "us-east-1" }
    }
  }
}
```

## Requirements

- Python 3.11+
- `mcp` SDK (`pip install mcp`)
- AWS credentials configured (for Bedrock server)
- GitHub Personal Access Token (for GitHub server)
- OpenWeatherMap API key (for weather server)

## Architecture

Each server follows the MCP server pattern:
1. Define **tools** with JSON schemas for inputs
2. Implement tool **handlers** that call external APIs
3. Expose via **stdio transport** (default) or SSE

```
Claude / Copilot
      |
   MCP Client
      |
  [stdio/SSE]
      |
   MCP Server  <---> External API / Service
```

## Author

Built by [@ratneshdubey-eng](https://github.com/ratneshdubey-eng) | [ratneshdubey.in](https://ratneshdubey.in)
