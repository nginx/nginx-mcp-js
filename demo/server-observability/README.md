# MCP server-side observability

Compare backend [MCP] operation outcomes with gateway HTTP telemetry.

## NGINX

Validates MCP routing metadata and routes calls to tool backends using
[`json_set`][json-set] and [`map`][map]. The [OTel module][nginx-otel]
exports gateway HTTP spans with tool and backend attributes. Configure
routing and edge telemetry in the
[NGINX configuration](../native-routing/nginx.conf) and its includes.

## Demo environment

The [Python MCP SDK][python-sdk] (`mcp==2.3.0`) adds built-in operation
instrumentation for the information backend. Operations and data backends
use the [Go SDK][go-sdk] without instrumentation. The
[OTel Collector][collector], [Prometheus] and [Grafana] expose SDK outcomes
separately from NGINX request metrics.

## Run

From demo/, after stopping the previous example:

```sh
./run.sh server-observability
python3 shared/scenarios/check.py --sdk --mixed \
    --prometheus http://127.0.0.1:9090
python3 shared/scenarios/check.py --sdk \
    --prometheus http://127.0.0.1:9090
```

Requirements, ports and load settings are in [the demo guide](../README.md).

## Architecture

```text
client -> native NGINX -> Python information / Go operations and data
               |                     |
               +-> HTTP spans        +-> SDK MCP spans
                        OTel Collector -> Prometheus -> Grafana
```

## What to observe

Grafana provisions HTTP and `MCP server-side outcomes` dashboards. Mixed
traffic keeps HTTP 400/403, `Tool execution error` and `Internal RPC error`
rates nonzero. Both semantic errors can use HTTP 200. `input_required` is
an interim result, not a tool failure.

[Collector SDK pipeline](../../observability/otel/sdk.yaml) counts only
Python MCP tools/call operation spans into `mcp_exec_*`. HTTP spans and
ASGI instrumentation are excluded from that count; `edge_*` still counts
only NGINX HTTP requests. SDK operations include interim exchanges, not
just completed tool executions.

## Technical notes

SDK trace context comes from MCP request _meta; ASGI captures HTTP context
separately. This example does not provision trace storage or promise a
single HTTP/MCP parent chain. It retains the direct-call scope of native.

[MCP]: https://modelcontextprotocol.io/specification/2026-07-28
[json-set]: https://nginx.org/en/docs/http/ngx_http_json_module.html#json_set
[map]: https://nginx.org/en/docs/http/ngx_http_map_module.html#map
[nginx-otel]: https://nginx.org/en/docs/ngx_otel_module.html
[python-sdk]: https://py.sdk.modelcontextprotocol.io/
[go-sdk]: https://pkg.go.dev/github.com/modelcontextprotocol/go-sdk@v1.7.0/mcp
[collector]: https://opentelemetry.io/docs/collector/
[Prometheus]: https://prometheus.io/docs/introduction/overview/
[Grafana]: https://grafana.com/docs/grafana/latest/
