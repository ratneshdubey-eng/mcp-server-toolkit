"""
weather_server.py - MCP Server for real-time weather data

Exposes two tools to Claude / Copilot via the Model Context Protocol:
  - get_current_weather(city, units)
  - get_forecast(city, days, units)

Requires:
  OPENWEATHER_API_KEY environment variable

Usage:
  python src/weather_server.py
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
logger = logging.getLogger("weather-mcp-server")

API_KEY = os.getenv("OPENWEATHER_API_KEY", "")
BASE_URL = "https://api.openweathermap.org/data/2.5"

app = Server("weather-server")


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    """Declare the tools available on this MCP server."""
    return [
        types.Tool(
            name="get_current_weather",
            description="Get the current weather for a city including temperature, humidity, wind speed, and conditions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "City name, e.g. 'London' or 'New Delhi,IN'",
                    },
                    "units": {
                        "type": "string",
                        "enum": ["metric", "imperial", "standard"],
                        "default": "metric",
                        "description": "Temperature units: metric (Celsius), imperial (Fahrenheit), standard (Kelvin)",
                    },
                },
                "required": ["city"],
            },
        ),
        types.Tool(
            name="get_forecast",
            description="Get a multi-day weather forecast for a city (up to 5 days, 3-hour intervals).",
            inputSchema={
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "City name, e.g. 'Mumbai' or 'Paris,FR'",
                    },
                    "days": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 5,
                        "default": 3,
                        "description": "Number of days to forecast (1-5)",
                    },
                    "units": {
                        "type": "string",
                        "enum": ["metric", "imperial", "standard"],
                        "default": "metric",
                    },
                },
                "required": ["city"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    """Route tool calls to the appropriate handler."""
    if name == "get_current_weather":
        return await handle_current_weather(arguments)
    elif name == "get_forecast":
        return await handle_forecast(arguments)
    else:
        raise ValueError(f"Unknown tool: {name}")


async def handle_current_weather(args: dict[str, Any]) -> list[types.TextContent]:
    """Fetch current weather from OpenWeatherMap API."""
    city = args["city"]
    units = args.get("units", "metric")
    unit_symbol = {"metric": "C", "imperial": "F", "standard": "K"}.get(units, "C")

    if not API_KEY:
        return [types.TextContent(
            type="text",
            text="Error: OPENWEATHER_API_KEY environment variable is not set."
        )]

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BASE_URL}/weather",
                params={"q": city, "appid": API_KEY, "units": units},
                timeout=10.0,
            )
            response.raise_for_status()
            data = response.json()

        result = {
            "city": data["name"],
            "country": data["sys"]["country"],
            "temperature": f"{data['main']['temp']:.1f}\u00b0{unit_symbol}",
            "feels_like": f"{data['main']['feels_like']:.1f}\u00b0{unit_symbol}",
            "humidity": f"{data['main']['humidity']}%",
            "description": data["weather"][0]["description"].title(),
            "wind_speed": f"{data['wind']['speed']} m/s",
            "visibility": f"{data.get('visibility', 0) / 1000:.1f} km",
        }

        logger.info("Weather fetched for %s", city)
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    except httpx.HTTPStatusError as e:
        return [types.TextContent(type="text", text=f"API error: {e.response.status_code} - {e.response.text}")]
    except Exception as e:
        logger.exception("Error fetching weather")
        return [types.TextContent(type="text", text=f"Error: {str(e)}")]


async def handle_forecast(args: dict[str, Any]) -> list[types.TextContent]:
    """Fetch multi-day forecast from OpenWeatherMap API."""
    city = args["city"]
    days = args.get("days", 3)
    units = args.get("units", "metric")
    unit_symbol = {"metric": "C", "imperial": "F", "standard": "K"}.get(units, "C")
    cnt = days * 8  # 8 intervals per day (3-hour slots)

    if not API_KEY:
        return [types.TextContent(
            type="text",
            text="Error: OPENWEATHER_API_KEY environment variable is not set."
        )]

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BASE_URL}/forecast",
                params={"q": city, "appid": API_KEY, "units": units, "cnt": cnt},
                timeout=10.0,
            )
            response.raise_for_status()
            data = response.json()

        # Group by date
        days_map: dict[str, list] = {}
        for item in data["list"]:
            date = item["dt_txt"].split(" ")[0]
            days_map.setdefault(date, []).append(item)

        forecast = []
        for date, slots in list(days_map.items())[:days]:
            temps = [s["main"]["temp"] for s in slots]
            forecast.append({
                "date": date,
                "min_temp": f"{min(temps):.1f}\u00b0{unit_symbol}",
                "max_temp": f"{max(temps):.1f}\u00b0{unit_symbol}",
                "description": slots[len(slots) // 2]["weather"][0]["description"].title(),
                "humidity": f"{slots[len(slots) // 2]['main']['humidity']}%",
            })

        result = {
            "city": data["city"]["name"],
            "country": data["city"]["country"],
            "forecast": forecast,
        }

        logger.info("Forecast fetched for %s (%d days)", city, days)
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    except httpx.HTTPStatusError as e:
        return [types.TextContent(type="text", text=f"API error: {e.response.status_code} - {e.response.text}")]
    except Exception as e:
        logger.exception("Error fetching forecast")
        return [types.TextContent(type="text", text=f"Error: {str(e)}")]


async def main():
    logger.info("Starting Weather MCP Server...")
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
