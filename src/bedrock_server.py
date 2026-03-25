"""
bedrock_server.py - MCP Server for AWS Bedrock model invocation

Exposes AWS Bedrock tools to Claude / Copilot via the Model Context Protocol:
  - invoke_claude(prompt, max_tokens, temperature)
  - invoke_titan(prompt, max_tokens, temperature)
  - list_models(provider)

Requires:
  AWS credentials configured via environment or ~/.aws/credentials
  AWS_REGION environment variable (default: us-east-1)

Usage:
  export AWS_REGION=us-east-1
  python src/bedrock_server.py
"""

import asyncio
import os
import json
import logging
from typing import Any

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bedrock-mcp-server")

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

app = Server("bedrock-server")


def get_bedrock_client():
    return boto3.client("bedrock-runtime", region_name=AWS_REGION)


def get_bedrock_mgmt_client():
    return boto3.client("bedrock", region_name=AWS_REGION)


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="invoke_claude",
            description="Invoke an Anthropic Claude model on AWS Bedrock and return the response.",
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "The user prompt to send to Claude"},
                    "model_id": {
                        "type": "string",
                        "default": "anthropic.claude-3-sonnet-20240229-v1:0",
                        "description": "Bedrock model ID for Claude",
                    },
                    "max_tokens": {
                        "type": "integer",
                        "default": 1024,
                        "minimum": 1,
                        "maximum": 4096,
                    },
                    "temperature": {
                        "type": "number",
                        "default": 0.7,
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                    "system_prompt": {
                        "type": "string",
                        "description": "Optional system prompt",
                    },
                },
                "required": ["prompt"],
            },
        ),
        types.Tool(
            name="invoke_titan",
            description="Invoke an Amazon Titan text model on AWS Bedrock.",
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "The input prompt"},
                    "model_id": {
                        "type": "string",
                        "default": "amazon.titan-text-express-v1",
                        "description": "Bedrock model ID for Titan",
                    },
                    "max_tokens": {
                        "type": "integer",
                        "default": 512,
                        "minimum": 1,
                        "maximum": 4096,
                    },
                    "temperature": {
                        "type": "number",
                        "default": 0.7,
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                },
                "required": ["prompt"],
            },
        ),
        types.Tool(
            name="list_models",
            description="List available foundation models on AWS Bedrock, optionally filtered by provider.",
            inputSchema={
                "type": "object",
                "properties": {
                    "provider": {
                        "type": "string",
                        "description": "Filter by provider name, e.g. 'Anthropic', 'Amazon', 'Meta'",
                    },
                    "modality": {
                        "type": "string",
                        "enum": ["TEXT", "IMAGE", "EMBEDDING"],
                        "description": "Filter by output modality",
                    },
                },
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    try:
        if name == "invoke_claude":
            return await handle_invoke_claude(arguments)
        elif name == "invoke_titan":
            return await handle_invoke_titan(arguments)
        elif name == "list_models":
            return await handle_list_models(arguments)
        else:
            raise ValueError(f"Unknown tool: {name}")
    except NoCredentialsError:
        return [types.TextContent(type="text", text="Error: AWS credentials not configured. Run 'aws configure' or set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY.")]
    except ClientError as e:
        return [types.TextContent(type="text", text=f"AWS error: {e.response['Error']['Code']} - {e.response['Error']['Message']}")]
    except Exception as e:
        logger.exception("Tool error: %s", name)
        return [types.TextContent(type="text", text=f"Error: {e}")]


async def handle_invoke_claude(args: dict[str, Any]) -> list[types.TextContent]:
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _invoke_claude_sync, args)
    return [types.TextContent(type="text", text=result)]


def _invoke_claude_sync(args: dict[str, Any]) -> str:
    client = get_bedrock_client()
    model_id = args.get("model_id", "anthropic.claude-3-sonnet-20240229-v1:0")
    messages = [{"role": "user", "content": args["prompt"]}]
    body: dict[str, Any] = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": args.get("max_tokens", 1024),
        "temperature": args.get("temperature", 0.7),
        "messages": messages,
    }
    if "system_prompt" in args:
        body["system"] = args["system_prompt"]

    response = client.invoke_model(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(body),
    )
    resp_body = json.loads(response["body"].read())
    content = resp_body.get("content", [])
    text = " ".join(block["text"] for block in content if block.get("type") == "text")
    usage = resp_body.get("usage", {})
    logger.info("Claude invoked: model=%s, input_tokens=%s, output_tokens=%s",
                model_id, usage.get("input_tokens"), usage.get("output_tokens"))
    return json.dumps({"model": model_id, "response": text, "usage": usage}, indent=2)


async def handle_invoke_titan(args: dict[str, Any]) -> list[types.TextContent]:
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _invoke_titan_sync, args)
    return [types.TextContent(type="text", text=result)]


def _invoke_titan_sync(args: dict[str, Any]) -> str:
    client = get_bedrock_client()
    model_id = args.get("model_id", "amazon.titan-text-express-v1")
    body = {
        "inputText": args["prompt"],
        "textGenerationConfig": {
            "maxTokenCount": args.get("max_tokens", 512),
            "temperature": args.get("temperature", 0.7),
            "stopSequences": [],
        },
    }
    response = client.invoke_model(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(body),
    )
    resp_body = json.loads(response["body"].read())
    results = resp_body.get("results", [])
    text = results[0].get("outputText", "") if results else ""
    logger.info("Titan invoked: model=%s", model_id)
    return json.dumps({"model": model_id, "response": text}, indent=2)


async def handle_list_models(args: dict[str, Any]) -> list[types.TextContent]:
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _list_models_sync, args)
    return [types.TextContent(type="text", text=result)]


def _list_models_sync(args: dict[str, Any]) -> str:
    client = get_bedrock_mgmt_client()
    params: dict[str, Any] = {"byOutputModality": "TEXT"}
    if "provider" in args:
        params["byProvider"] = args["provider"]
    if "modality" in args:
        params["byOutputModality"] = args["modality"]
    response = client.list_foundation_models(**params)
    models = [
        {
            "modelId": m["modelId"],
            "modelName": m["modelName"],
            "providerName": m["providerName"],
            "inputModalities": m.get("inputModalities", []),
            "outputModalities": m.get("outputModalities", []),
            "responseStreamingSupported": m.get("responseStreamingSupported", False),
        }
        for m in response.get("modelSummaries", [])
    ]
    return json.dumps({"region": AWS_REGION, "models": models, "count": len(models)}, indent=2)


async def main():
    logger.info("Starting AWS Bedrock MCP Server (region: %s)...", AWS_REGION)
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
