# MCP response observability with njs

Inspect [MCP] JSON-RPC responses to identify tool errors, RPC errors and
interim results without backend instrumentation.

## NGINX

Uses an [njs] [`js_body_filter`][body-filter] to classify JSON responses
and set MCP outcome variables. [`otel_span_attr`][span-attr] exports
these outcomes alongside HTTP status. Configure the filter and outcome
attributes in the
[NGINX configuration](nginx.conf).

## Demo environment

Mock backends using the [Go SDK][go-sdk] or [Python SDK][python-sdk] return
controlled MCP results without semantic telemetry export. The
[OTel Collector][collector] adds outcome dimensions to gateway metrics;
[Prometheus] and [Grafana] reveal errors inside HTTP 200 responses.

## Run

From demo/:

```sh
./run.sh njs-response-observability
python3 shared/scenarios/check.py --njs \
    --prometheus http://127.0.0.1:9090
```

To verify the observer with the same Python information backend as the
server-side example, with operation export off:

```sh
./run.sh njs-response-observability down
./run.sh njs-response-observability-python
```

Each starts mixed traffic and the complete monitoring stack. Local settings
are in [the demo guide](../README.md). These demos select SDK and njs
observation separately. Both sources can coexist in a deployment, with
separate HTTP request and backend operation counters.

## Architecture

```text
client -> NGINX + njs -> Go/Python MCP backends (no semantic exporter)
                 |
                 +-> edge HTTP/MCP spans -> Collector -> Grafana
```

## What to observe

Grafana adds `MCP njs edge outcomes`: complete, tool_error, rpc_error,
input_required, invalid_response and unobserved. Mixed traffic demonstrates
semantic failures within HTTP 200 independently of backend telemetry.
HTTP status remains a separate dimension.

The deterministic checker verifies a 70 KiB response is forwarded intact
while observation becomes unobserved. Edge-generated responses, SSE and
compressed bodies are also unobserved. The observer checks response shape
but does not fully validate MCP schemas. See njs/README.md for its contract.

The direct-call protocol scope and early HTTP 413 span limitation are the
same as native. Run `node t/mcp_observer.mjs` from the repository root.

[MCP]: https://modelcontextprotocol.io/specification/2026-07-28
[njs]: https://nginx.org/en/docs/njs/
[body-filter]: https://nginx.org/en/docs/http/ngx_http_js_module.html#js_body_filter
[span-attr]: https://nginx.org/en/docs/ngx_otel_module.html#otel_span_attr
[go-sdk]: https://pkg.go.dev/github.com/modelcontextprotocol/go-sdk@v1.7.0/mcp
[python-sdk]: https://py.sdk.modelcontextprotocol.io/
[collector]: https://opentelemetry.io/docs/collector/
[Prometheus]: https://prometheus.io/docs/introduction/overview/
[Grafana]: https://grafana.com/docs/grafana/latest/
