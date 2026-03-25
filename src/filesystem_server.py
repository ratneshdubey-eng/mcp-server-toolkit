"""
filesystem_server.py - MCP Server for safe local file operations

Exposes file system tools to Claude / Copilot via the Model Context Protocol:
  - read_file(path)
  - write_file(path, content)
  - list_directory(path)
  - search_files(directory, pattern)

Security: All operations are sandboxed to ALLOWED_BASE_DIR (default: ~/mcp-workspace).
Paths outside this directory are rejected.

Usage:
  python src/filesystem_server.py
"""

import asyncio
import os
import fnmatch
import json
import logging
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("filesystem-mcp-server")

# Sandbox: restrict all file operations to this base directory
ALLOWED_BASE_DIR = Path(
    os.getenv("MCP_WORKSPACE", os.path.expanduser("~/mcp-workspace"))
).resolve()

app = Server("filesystem-server")


def safe_path(raw: str) -> Path:
    """Resolve and validate that a path is inside the allowed sandbox."""
    resolved = (ALLOWED_BASE_DIR / raw).resolve()
    if not str(resolved).startswith(str(ALLOWED_BASE_DIR)):
        raise PermissionError(
            f"Access denied: '{raw}' is outside the allowed workspace ({ALLOWED_BASE_DIR})"
        )
    return resolved


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="read_file",
            description="Read the contents of a file inside the MCP workspace.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to the file"},
                },
                "required": ["path"],
            },
        ),
        types.Tool(
            name="write_file",
            description="Write content to a file inside the MCP workspace. Creates parent directories if needed.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to the file"},
                    "content": {"type": "string", "description": "Content to write"},
                    "append": {
                        "type": "boolean",
                        "default": False,
                        "description": "Append to existing file instead of overwriting",
                    },
                },
                "required": ["path", "content"],
            },
        ),
        types.Tool(
            name="list_directory",
            description="List files and subdirectories inside a workspace directory.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "default": ".",
                        "description": "Relative path to directory (default: workspace root)",
                    },
                },
            },
        ),
        types.Tool(
            name="search_files",
            description="Search for files matching a glob pattern inside the workspace.",
            inputSchema={
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "default": ".",
                        "description": "Directory to search in (relative to workspace)",
                    },
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern, e.g. '*.py' or 'data/*.json'",
                    },
                },
                "required": ["pattern"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    try:
        if name == "read_file":
            return await handle_read_file(arguments)
        elif name == "write_file":
            return await handle_write_file(arguments)
        elif name == "list_directory":
            return await handle_list_directory(arguments)
        elif name == "search_files":
            return await handle_search_files(arguments)
        else:
            raise ValueError(f"Unknown tool: {name}")
    except PermissionError as e:
        return [types.TextContent(type="text", text=f"Permission denied: {e}")]
    except Exception as e:
        logger.exception("Tool error: %s", name)
        return [types.TextContent(type="text", text=f"Error: {e}")]


async def handle_read_file(args: dict[str, Any]) -> list[types.TextContent]:
    path = safe_path(args["path"])
    if not path.exists():
        return [types.TextContent(type="text", text=f"File not found: {args['path']}")]
    content = path.read_text(encoding="utf-8")
    logger.info("Read file: %s (%d bytes)", path, len(content))
    return [types.TextContent(type="text", text=content)]


async def handle_write_file(args: dict[str, Any]) -> list[types.TextContent]:
    path = safe_path(args["path"])
    content = args["content"]
    append = args.get("append", False)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    path.open(mode, encoding="utf-8").write(content)
    logger.info("%s file: %s", "Appended" if append else "Wrote", path)
    return [types.TextContent(
        type="text",
        text=json.dumps({"success": True, "path": str(path), "bytes_written": len(content)})
    )]


async def handle_list_directory(args: dict[str, Any]) -> list[types.TextContent]:
    rel = args.get("path", ".")
    path = safe_path(rel)
    if not path.is_dir():
        return [types.TextContent(type="text", text=f"Not a directory: {rel}")]
    entries = []
    for entry in sorted(path.iterdir()):
        entries.append({
            "name": entry.name,
            "type": "directory" if entry.is_dir() else "file",
            "size": entry.stat().st_size if entry.is_file() else None,
        })
    return [types.TextContent(type="text", text=json.dumps(entries, indent=2))]


async def handle_search_files(args: dict[str, Any]) -> list[types.TextContent]:
    directory = safe_path(args.get("directory", "."))
    pattern = args["pattern"]
    matches = []
    for root, _dirs, files in os.walk(directory):
        for filename in files:
            if fnmatch.fnmatch(filename, pattern):
                full = Path(root) / filename
                rel = full.relative_to(ALLOWED_BASE_DIR)
                matches.append(str(rel))
    logger.info("Search '%s' in %s: %d matches", pattern, directory, len(matches))
    return [types.TextContent(type="text", text=json.dumps(matches, indent=2))]


async def main():
    ALLOWED_BASE_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Starting Filesystem MCP Server (sandbox: %s)...", ALLOWED_BASE_DIR)
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
