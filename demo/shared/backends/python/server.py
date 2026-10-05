# Copyright (C) Dmitry Volyntsev
# Copyright (C) F5, Inc.

import json
import asyncio
import os

import uvicorn
from mcp.server import Server
from mcp.shared.exceptions import MCPError
from mcp.types import (
    CallToolResult, InputRequiredResult, ListToolsResult,
    TextContent, Tool,
)
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

enabled = os.environ.get("MCP_TELEMETRY", "off") == "on"
provider = None
if enabled:
    provider = TracerProvider(resource=Resource.create({
        "service.name": "mcp-information-python",
    }))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(
        endpoint="http://otel-collector:4317", insecure=True,
    )))
    trace.set_tracer_provider(provider)

async def call_tool(ctx, params):
    name = params.name
    if name not in ("get_forecast", "search_web", "translate_text"):
        raise MCPError(-32602, "Unknown tool")
    simulate = (params.arguments or {}).get("simulate", "success")
    await asyncio.sleep(0.01)
    if simulate == "rpc_error":
        raise MCPError(-32603, "internal error (simulated)")
    if simulate == "tool_error":
        return CallToolResult(
            content=[TextContent(type="text", text="tool error (simulated)")],
            is_error=True,
        )
    if simulate == "input_required":
        return InputRequiredResult(input_requests={}, request_state="retry")
    if simulate == "large_response":
        return CallToolResult(content=[TextContent(type="text", text="x" * 70000)])
    return CallToolResult(content=[TextContent(type="text", text=json.dumps({
        "tool": name, "server": "mcp-information", "status": "success",
    }))])


async def list_tools(ctx, params):
    return ListToolsResult(tools=[
        Tool(name=name, input_schema={"type": "object"})
        for name in ("get_forecast", "search_web", "translate_text")
    ])


server = Server("mcp-information", version="2.0",
                on_call_tool=call_tool, on_list_tools=list_tools)


app = server.streamable_http_app(
    host="0.0.0.0", stateless_http=True, json_response=True,
)
if enabled:
    # Establish ambient HTTP context; the SDK records it as a span link.
    app = OpenTelemetryMiddleware(app)

if __name__ == "__main__":
    try:
        uvicorn.run(app, host="0.0.0.0", port=9001)
    finally:
        if provider is not None:
            provider.shutdown()
