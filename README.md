# NGINX for Model Context Protocol

Model Context Protocol (MCP) lets clients call tools provided by a server.
Over HTTP, a tool call is a JSON-RPC request sent by POST to a single
endpoint, such as `/mcp`. The RPC method `tools/call` selects the operation;
`params.name` selects the tool.

This repository provides NGINX routing recipes and runnable examples of
HTTP metrics, backend operation metrics, and JSON response observation.
The examples support direct calls to known tools using MCP 2026-07-28.
Clients that require tool discovery need an additional discovery endpoint
or adapter; these examples do not aggregate backend tool catalogs.

## Native request processing

The HTTP JSON module is available since NGINX 1.31.5 and requires
`--with-http_json_module` when building from source. The demos use the
official NGINX 1.31.6 `alpine-otel` image with the JSON module built in.

MCP 2026-07-28 mirrors the RPC method and tool name into HTTP headers.
NGINX can route using these headers. `client_body_early_read` and `json_set`
also make body fields available before routing and access checks. Comparing
headers with the body prevents a caller from routing to one tool while
asking the backend to execute another.

A request to the native example looks like this:

```http
POST /mcp HTTP/1.1
Host: localhost:9000
Content-Type: application/json
Accept: application/json, text/event-stream
MCP-Protocol-Version: 2026-07-28
Mcp-Method: tools/call
Mcp-Name: get_forecast

{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "get_forecast",
    "arguments": {},
    "_meta": {
      "io.modelcontextprotocol/protocolVersion": "2026-07-28",
      "io.modelcontextprotocol/clientCapabilities": {}
    }
  }
}
```

This abbreviated configuration illustrates the key settings:

```nginx
http {
    json_set $mcp_body_method $request_body method;
    json_set $mcp_body_tool $request_body params.name;

    map "$mcp_body_method:$mcp_body_tool" $mcp_upstream {
        default                   "";
        "tools/call:get_forecast" forecast_backend;
    }

    upstream forecast_backend {
        server 127.0.0.1:9001;
    }

    server {
        listen 9000;

        client_body_early_read on;
        client_max_body_size 64k;
        client_body_buffer_size 64k;

        location = /mcp {
            if ($http_mcp_method != $mcp_body_method) {
                return 400;
            }

            if ($http_mcp_name != $mcp_body_tool) {
                return 400;
            }

            if ($mcp_upstream = "") {
                return 403;
            }

            proxy_pass http://$mcp_upstream;
        }
    }
}
```

The [complete native example](demo/native-routing/nginx.conf) also checks HTTP
method, media type and protocol version. Request buffers must hold the
allowed body size so `$request_body` is available to `json_set`.

## What each observation layer provides

HTTP 200 can carry a JSON-RPC error or a tool result with `isError: true`.
HTTP status alone therefore does not tell you whether the tool succeeded.
An `input_required` result asks for more client input; it is neither a
completed success nor a tool failure.

| Layer | Observes | Requires |
| --- | --- | --- |
| Native NGINX | Routing, header/body checks, HTTP status and request latency | JSON module; OTel module for telemetry export |
| Server-side instrumentation | MCP operation outcomes and backend operation latency | Instrumented SDK/framework and exporter setup |
| njs at NGINX | Tool/RPC errors and interim results in JSON responses seen by the proxy | njs; no backend instrumentation |

Instrumentation support varies by SDK and framework. The server-side
example uses the official Python MCP SDK's built-in OpenTelemetry (OTel)
instrumentation for the information backend: three of the eight tools.
Go backends remain uninstrumented.

Backend operation metrics and proxy request metrics have different
boundaries and counters. They should be compared, not added together.
SDK and njs observation can complement each other; the supplied demos
select each source separately to make its contribution clear.

## Demo catalog

| Example | Type | Adds | Run from demo/ |
| --- | --- | --- | --- |
| [Native MCP routing and HTTP observability](demo/native-routing/README.md) | Observability | Body routing and HTTP telemetry, without njs | `./run.sh native-routing` |
| [MCP server-side observability](demo/server-observability/README.md) | Observability | Python information backend operation outcomes | `./run.sh server-observability` |
| [MCP response observability with njs](demo/njs-response-observability/README.md) | Observability | JSON response outcomes at NGINX | `./run.sh njs-response-observability` |
| [MCP structured gateway audit](demo/structured-audit/README.md) | Audit logs | JSON events explaining tool calls and gateway rejections | `./run.sh structured-audit` |
| [MCP searchable gateway audit](demo/searchable-audit/README.md) | Audit logs | Search tool calls and gateway decisions in Loki and Grafana | `./run.sh searchable-audit` |
| [Per-tool rate limits](demo/tool-rate-limiting/README.md) | Protection | Independent tool limits with NGINX OSS | `./run.sh tool-rate-limiting` |
| [Per-tool circuit breaker](demo/tool-circuit-breaking/README.md) | Protection | Blocks failing tools with OSS and njs | `./run.sh tool-circuit-breaking` |

Each example starts its backends, monitoring stack and traffic generator.
See [the demo guide](demo/README.md) for setup and verification.

## Reusable artifacts

| Directory | Contents |
| --- | --- |
| [nginx/](nginx/README.md) | Metadata, validation and OTel configuration snippets |
| [njs/](njs/README.md) | Bounded JSON-RPC response observer |
| [observability/](observability/README.md) | Collector pipelines and Grafana dashboards |
| [demo/](demo/README.md) | Runnable deployments, backends and mixed traffic |
| [t/](t/) | Tests using the same processing artifacts as demos |

NGINX configuration snippets have explicit `http`, `server` or `location`
contexts. Adapt upstreams, tool allowlists, limits and exporter endpoints
to your deployment; Docker DNS and mock tools belong to the demos.

## Protocol scope

Discovery, catalog aggregation and legacy initialization/session support
are outside the examples' direct-call scope.

The supplied allowlists use header-safe ASCII names. Base64-sentinel
`Mcp-Name` values are rejected, not decoded. Backends remain responsible for
complete JSON-RPC and tool schema validation. Request metadata is not an
authenticated identity.

References: [JSON module](https://nginx.org/en/docs/http/ngx_http_json_module.html),
[early body reading](https://nginx.org/en/docs/http/ngx_http_core_module.html#client_body_early_read),
[MCP transport](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http).
