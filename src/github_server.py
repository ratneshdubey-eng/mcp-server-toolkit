"""
github_server.py - MCP Server for GitHub API integration

Exposes GitHub tools to Claude / Copilot via the Model Context Protocol:
  - get_repo(owner, repo)
  - list_issues(owner, repo, state, limit)
  - create_issue(owner, repo, title, body, labels)
  - search_code(query, language, per_page)

Requires:
  GITHUB_TOKEN environment variable (Personal Access Token or fine-grained token)

Usage:
  export GITHUB_TOKEN=ghp_xxx
  python src/github_server.py
"""

import asyncio
import os
import json
import logging
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("github-mcp-server")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
API_BASE = "https://api.github.com"
HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

app = Server("github-server")


def auth_headers() -> dict:
    h = dict(HEADERS)
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="get_repo",
            description="Get metadata about a GitHub repository (stars, forks, language, description, topics).",
            inputSchema={
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "Repository owner (user or org)"},
                    "repo": {"type": "string", "description": "Repository name"},
                },
                "required": ["owner", "repo"],
            },
        ),
        types.Tool(
            name="list_issues",
            description="List issues in a GitHub repository.",
            inputSchema={
                "type": "object",
                "properties": {
                    "owner": {"type": "string"},
                    "repo": {"type": "string"},
                    "state": {
                        "type": "string",
                        "enum": ["open", "closed", "all"],
                        "default": "open",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 100,
                    },
                },
                "required": ["owner", "repo"],
            },
        ),
        types.Tool(
            name="create_issue",
            description="Create a new issue in a GitHub repository.",
            inputSchema={
                "type": "object",
                "properties": {
                    "owner": {"type": "string"},
                    "repo": {"type": "string"},
                    "title": {"type": "string", "description": "Issue title"},
                    "body": {"type": "string", "description": "Issue body (Markdown supported)"},
                    "labels": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of label names",
                    },
                },
                "required": ["owner", "repo", "title"],
            },
        ),
        types.Tool(
            name="search_code",
            description="Search for code across GitHub repositories.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query (e.g., 'MCP server language:python')"},
                    "per_page": {
                        "type": "integer",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 30,
                    },
                },
                "required": ["query"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    try:
        if name == "get_repo":
            return await handle_get_repo(arguments)
        elif name == "list_issues":
            return await handle_list_issues(arguments)
        elif name == "create_issue":
            return await handle_create_issue(arguments)
        elif name == "search_code":
            return await handle_search_code(arguments)
        else:
            raise ValueError(f"Unknown tool: {name}")
    except Exception as e:
        logger.exception("Tool error: %s", name)
        return [types.TextContent(type="text", text=f"Error: {e}")]


async def handle_get_repo(args: dict[str, Any]) -> list[types.TextContent]:
    owner, repo = args["owner"], args["repo"]
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{API_BASE}/repos/{owner}/{repo}", headers=auth_headers(), timeout=10.0)
        r.raise_for_status()
        d = r.json()
    result = {
        "full_name": d["full_name"],
        "description": d.get("description"),
        "stars": d["stargazers_count"],
        "forks": d["forks_count"],
        "open_issues": d["open_issues_count"],
        "language": d.get("language"),
        "topics": d.get("topics", []),
        "homepage": d.get("homepage"),
        "html_url": d["html_url"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
    }
    return [types.TextContent(type="text", text=json.dumps(result, indent=2))]


async def handle_list_issues(args: dict[str, Any]) -> list[types.TextContent]:
    owner, repo = args["owner"], args["repo"]
    state = args.get("state", "open")
    limit = args.get("limit", 10)
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{API_BASE}/repos/{owner}/{repo}/issues",
            headers=auth_headers(),
            params={"state": state, "per_page": limit},
            timeout=10.0,
        )
        r.raise_for_status()
        issues = r.json()
    result = [
        {
            "number": i["number"],
            "title": i["title"],
            "state": i["state"],
            "author": i["user"]["login"],
            "labels": [lb["name"] for lb in i.get("labels", [])],
            "created_at": i["created_at"],
            "html_url": i["html_url"],
        }
        for i in issues
        if "pull_request" not in i  # exclude PRs from issue listing
    ]
    return [types.TextContent(type="text", text=json.dumps(result, indent=2))]


async def handle_create_issue(args: dict[str, Any]) -> list[types.TextContent]:
    if not GITHUB_TOKEN:
        return [types.TextContent(type="text", text="Error: GITHUB_TOKEN is not set. Cannot create issues.")]
    owner, repo = args["owner"], args["repo"]
    payload: dict[str, Any] = {"title": args["title"]}
    if "body" in args:
        payload["body"] = args["body"]
    if "labels" in args:
        payload["labels"] = args["labels"]
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{API_BASE}/repos/{owner}/{repo}/issues",
            headers=auth_headers(),
            json=payload,
            timeout=10.0,
        )
        r.raise_for_status()
        d = r.json()
    result = {"number": d["number"], "title": d["title"], "html_url": d["html_url"], "state": d["state"]}
    logger.info("Created issue #%d in %s/%s", d["number"], owner, repo)
    return [types.TextContent(type="text", text=json.dumps(result, indent=2))]


async def handle_search_code(args: dict[str, Any]) -> list[types.TextContent]:
    query = args["query"]
    per_page = args.get("per_page", 10)
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{API_BASE}/search/code",
            headers=auth_headers(),
            params={"q": query, "per_page": per_page},
            timeout=15.0,
        )
        r.raise_for_status()
        data = r.json()
    results = [
        {
            "name": item["name"],
            "path": item["path"],
            "repository": item["repository"]["full_name"],
            "html_url": item["html_url"],
        }
        for item in data.get("items", [])
    ]
    return [types.TextContent(type="text", text=json.dumps({"total": data["total_count"], "results": results}, indent=2))]


async def main():
    logger.info("Starting GitHub MCP Server...")
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
